"""Exercise the first-install plan against an in-memory OpenMTP filesystem."""
from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from kindle_companion.manifest import load_manifest
from kindle_companion.models import Asset, CompanionError, DeviceIdentity
from kindle_companion.mtp import MtpClient
from kindle_companion.reading_setup import prepare_reading_setup, snapshot_from_state, transfer_reading_setup
from kindle_companion.state import empty_state, load_state, record_step, save_state
from kindle_companion.wireless import verify_connection
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DEVICE = DeviceIdentity("Kindle Colorsoft Signature Edition", "TESTSERIAL0001")


class MtpFilesystem:
    def __init__(self):
        self.files = {"/koreader/luajit": b"runtime", "/koreader/reader.lua": b"reader"}
        self.commands = []
        self.sessions = []
        self.corrupt_readback = False
        self.free = 1024 ** 3

    def run(self, args, **kwargs):
        commands = Path(args[-1]).read_text().splitlines()
        self.sessions.append(commands)
        output = []
        for command in commands:
            parts = shlex.split(command)
            self.commands.append(parts)
            if parts[0] == "lsext-r":
                paths = set()
                for name in self.files:
                    relative = name.removeprefix("/koreader/")
                    if relative != name:
                        paths.add(relative)
                        paths.update(str(p) for p in Path(relative).parents if str(p) != ".")
                output += [f"{i} 65537 3000 10 20261111T000000. {name}" for i, name in enumerate(sorted(paths), 1)]
            elif parts[0] == "storage-info":
                output.append(f"used 1000 (1%), free {self.free} bytes of {self.free + 1000}")
            elif parts[0] == "put":
                local = Path(parts[1])
                self.files[parts[2] + "/" + local.name] = local.read_bytes()
            elif parts[0] == "get":
                Path(parts[2]).write_bytes(b"corrupt" if self.corrupt_readback else self.files[parts[1]])
            elif parts[0] not in {"mkpath", "exit"}:
                raise AssertionError("unexpected MTP command: " + command)
        return subprocess.CompletedProcess(args, 0, "\n".join(output), "")

    def client(self):
        return MtpClient(Path("fixture-mtp"), runner=self.run)


class ReadingSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kindle-reading-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        route = load_manifest(ROOT / "manifests/compatibility.json").routes[0]
        assets = []
        for asset, directory in [("moon.zip", "book.koplugin"), ("kindle.zip", "kindle.koplugin"), ("reader.zip", "koreader")]:
            path = self.root / asset
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(directory + "/main.lua", b"fixture main")
                archive.writestr(directory + "/_meta.lua", b"fixture metadata")
                if asset == "reader.zip":
                    archive.writestr("koreader/dropbear", b"fixture dropbear")
            assets.append(Asset(asset, "https://example.invalid/" + asset, hashlib.sha256(path.read_bytes()).hexdigest(), "fixture"))
        self.route = replace(route, assets=tuple(assets),
                             wireless_maintenance=dict(route.wireless_maintenance, asset="reader.zip",
                                                       dropbear_sha256=hashlib.sha256(b"fixture dropbear").hexdigest()),
                             reading_environment={"wireless_maintenance_default": True, "plugins": [
                                 {"asset": "moon.zip", "directory": "book.koplugin"},
                                 {"asset": "kindle.zip", "directory": "kindle.koplugin"}]})
        self.state = dict(empty_state(), route=route.id, route_status="supported", firmware="5.20.1.0.2", device=DEVICE.as_dict())
        self.state["steps"]["install_koreader"]["status"] = "done"

    def prepare(self, name="setup", **kwargs):
        result = prepare_reading_setup(self.route, self.state, self.root, self.root / name, **kwargs)
        return self.root / name / "reading-setup.json", result

    def test_new_install_transfers_all_components_and_verifies_bytes_together(self):
        path, plan = self.prepare()
        device = MtpFilesystem()
        result = transfer_reading_setup(path, self.route, DEVICE, device.client())
        self.assertEqual(result["files_verified"], len(plan["files"]))
        self.assertEqual(len(device.sessions), 2)  # preflight, then one write/readback batch
        self.assertTrue(result["mtp_readback_verified"])
        self.assertFalse(result["application_loaded"])
        self.assertFalse(result["accounts_verified"])
        self.assertFalse(result["wireless_paired"])
        self.assertIn("/koreader/plugins/book.koplugin/main.lua", device.files)
        self.assertIn("/koreader/plugins/kindle.koplugin/main.lua", device.files)
        self.assertIn("/koreader/plugins/KindlePilot.koplugin/pairing_daemon.lua", device.files)
        config = device.files["/koreader/KindlePilot/config.lua"].decode()
        self.assertIn('pairing_code_format = "decimal"', config)
        self.assertNotIn("id_ed25519", "\n".join(device.files))
        with self.assertRaises(CompanionError) as raised:
            transfer_reading_setup(path, self.route, DEVICE, device.client())
        self.assertEqual(raised.exception.code, "READING_ALREADY_TRANSFERRED")

    def test_existing_plugins_accounts_and_wireless_identity_are_reused(self):
        path, plan = self.prepare()
        device = MtpFilesystem()
        for name in ("book.koplugin", "kindle.koplugin"):
            for file in ("main.lua", "_meta.lua", "account.lua"):
                device.files[f"/koreader/plugins/{name}/{file}"] = b"existing user configuration"
        result = transfer_reading_setup(path, self.route, DEVICE, device.client())
        self.assertEqual(len(result["reused_plugins"]), 2)
        self.assertEqual(device.files["/koreader/plugins/book.koplugin/account.lua"], b"existing user configuration")
        key = device.files["/koreader/KindlePilot/server_hostkey"]
        path2, _ = self.prepare("reuse", existing_wireless=Path(plan["wireless_setup"]))
        device.commands = []
        transfer_reading_setup(path2, self.route, DEVICE, device.client())
        self.assertFalse(any(c[0] == "put" for c in device.commands))
        self.assertEqual(device.files["/koreader/KindlePilot/server_hostkey"], key)

    def test_wrong_device_changed_stage_and_readback_mismatch_do_not_report_success(self):
        path, plan = self.prepare()
        device = MtpFilesystem()
        with self.assertRaises(CompanionError):
            transfer_reading_setup(path, self.route, DeviceIdentity(DEVICE.product, "OTHER"), device.client())
        self.assertEqual(device.sessions, [])
        staged = Path(plan["stage"]) / next(iter(plan["files"]))
        original = staged.read_bytes()
        staged.write_bytes(b"tampered")
        with self.assertRaises(CompanionError) as raised:
            transfer_reading_setup(path, self.route, DEVICE, device.client())
        self.assertEqual(raised.exception.code, "READING_STAGE")
        self.assertEqual(device.sessions, [])
        staged.write_bytes(original)
        device.corrupt_readback = True
        with self.assertRaises(CompanionError) as raised:
            transfer_reading_setup(path, self.route, DEVICE, device.client())
        self.assertEqual(raised.exception.code, "READING_READBACK")
        self.assertFalse((path.parent / "transfer-receipt.json").exists())

    def test_partial_plugins_existing_wireless_and_low_space_stop_before_put(self):
        path, _ = self.prepare()
        for existing, error in [
            ({"/koreader/plugins/book.koplugin/main.lua": b"incomplete"}, "READING_PARTIAL"),
            ({"/koreader/settings/KindlePilot/config.lua": b"legacy identity"}, "READING_WIRELESS_EXISTS"),
            ({}, "READING_SPACE"),
        ]:
            with self.subTest(error=error):
                device = MtpFilesystem()
                device.files.update(existing)
                if error == "READING_SPACE":
                    device.free = 0
                with self.assertRaises(CompanionError) as raised:
                    transfer_reading_setup(path, self.route, DEVICE, device.client())
                self.assertEqual(raised.exception.code, error)
                self.assertFalse(any(c[0] == "put" for c in device.commands))

    def test_wireless_opt_out_and_exact_route_and_asset_gates(self):
        _, plan = self.prepare(wireless=False)
        self.assertIsNone(plan["wireless_setup"])
        self.assertTrue(all("/plugins/" in name for name in plan["files"]))
        for key, value in [("firmware", "5.20.2"), ("device", dict(product="Kindle Paperwhite 11", serial=DEVICE.serial))]:
            with self.assertRaises(CompanionError):
                snapshot_from_state(self.route, dict(self.state, **{key: value}))
        (self.root / "moon.zip").write_bytes(b"changed archive")
        with self.assertRaises(CompanionError) as raised:
            self.prepare("bad-asset")
        self.assertEqual(raised.exception.code, "READING_ASSET_HASH")

    def test_archive_escape_is_rejected_before_any_device_access(self):
        path = self.root / "moon.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("book.koplugin/main.lua", b"main")
            archive.writestr("book.koplugin/_meta.lua", b"metadata")
            archive.writestr("book.koplugin/../../settings.reader.lua", b"unsafe")
        assets = tuple(replace(asset, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                       if asset.name == "moon.zip" else asset for asset in self.route.assets)
        self.route = replace(self.route, assets=assets)
        with self.assertRaises(CompanionError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, "READING_ARCHIVE")
        self.assertFalse((self.root / "settings.reader.lua").exists())

    def test_usb_serial_verification_normalizes_proc_newline_and_preserves_legacy_mode(self):
        snapshot = snapshot_from_state(self.route, self.state)
        path = self.root / "usid"
        for ending in ("", "\n", "\r\n"):
            path.write_bytes((DEVICE.serial + ending).encode())
            output = subprocess.check_output(["sh", "-c", "tr -d '\\r\\n' < " + shlex.quote(str(path))])
            self.assertEqual(hashlib.sha256(output).hexdigest(), snapshot["device"]["serial_sha256"])
        session = dict(bind_interface="en0", source_ip="192.168.10.20", identity_file="private",
                       port=2224, known_hosts="known-hosts", host_key_alias="fixture", firmware="5.20.1.0.2",
                       serial_sha256=snapshot["device"]["serial_sha256"], serial_hash_mode="usb_serial")
        output = f'FIRMWARE=Kindle 5.20.1.0.2\nSERIAL={session["serial_sha256"]}\nDROPBEAR={self.route.wireless_maintenance["dropbear_sha256"]}\n'
        with patch("kindle_companion.wireless.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output, "")) as run:
            self.assertTrue(verify_connection(session, self.route, "192.168.10.21")["identity_verified"])
            self.assertIn("tr -d", run.call_args.args[0][-1])
            verify_connection(dict(session, serial_hash_mode="proc_usid"), self.route, "192.168.10.21")
            self.assertIn("sha256sum /proc/usid", run.call_args.args[0][-1])

    def test_old_workflow_state_adds_wireless_steps_without_repeating_finished_plugins(self):
        path = self.root / "state.json"
        state = self.state
        state["steps"].pop("install_wireless")
        state["steps"].pop("wireless_verify")
        state["steps"]["install_plugins"]["status"] = "done"
        save_state(path, state)
        loaded = load_state(path)
        self.assertEqual(loaded["steps"]["install_plugins"]["status"], "done")
        self.assertEqual(loaded["steps"]["install_wireless"]["status"], "pending")
        record_step(loaded, "install_wireless", "done", "transfer receipt verified")
        record_step(loaded, "wireless_verify", "done", "identity and cleanup readback verified")


if __name__ == "__main__":
    unittest.main()
