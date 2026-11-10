import base64
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
import zipfile
import subprocess
from dataclasses import replace
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import sys
from types import SimpleNamespace
from unittest.mock import patch

from kindle_companion.manifest import load_manifest
from kindle_companion.models import Asset, CompanionError
from kindle_companion.wireless import dropbear_host_key, prepare_session, ssh_arguments, verify_connection
from kindle_companion.pairing import _candidate, pairing_proof, prepare_plugin, validate_pairing_code


ROOT = Path(__file__).resolve().parents[1]


class WirelessTests(unittest.TestCase):
    def test_koreader_pairing_proof_keeps_screen_code_off_network(self):
        proof = pairing_proof("A1B2C3", "a" * 32, "A" * 68, "b" * 32)
        self.assertEqual(len(proof), 40)
        self.assertNotIn("A1B2C3", proof)
        self.assertEqual(validate_pairing_code("a1b2c3"), "A1B2C3")
        self.assertEqual(validate_pairing_code("a1b2c3d4e5f6", 12), "A1B2C3D4E5F6")
        with self.assertRaises(CompanionError):
            validate_pairing_code("1234")

    def test_pairing_scan_skips_empty_or_malformed_responses(self):
        class EmptyClient:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def settimeout(self, _): pass
            def sendall(self, _): pass
            def recv(self, _): return b""

        identity = Path(tempfile.mkdtemp()) / "id_ed25519"
        identity.with_suffix(".pub").write_text("ssh-ed25519 " + "A" * 68 + "\n")
        setup = {"pairing_port": 2223, "host_public_b64": "B" * 68}
        with patch("kindle_companion.pairing.socket.create_connection", return_value=EmptyClient()):
            self.assertIsNone(_candidate("192.168.1.2", "192.168.1.187", "A1B2C3D4E5F6", setup, identity))

    def test_plugin_pairing_protocol_uses_real_line_terminators(self):
        daemon = (ROOT / "assets/kindlepilot.koplugin/pairing_daemon.lua").read_text()
        self.assertIn('local protocol_eol = "\\n"', daemon)
        self.assertIn('.. protocol_eol)', daemon)
        self.assertNotIn('.. "\\\\n")', daemon)
        self.assertIn('if not op or not nonce or #nonce ~= 32 then', daemon)
        self.assertIn('local ok, result = pcall(handle_client, client)', daemon)
        self.assertIn('local value, err = client:receive(1)', daemon)
        self.assertIn('%s+HELLO%s+', daemon)

    def test_koreader_pairing_setup_contains_plugin_and_no_client_private_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "reader.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("koreader/dropbear", b"fixture dropbear")
            route = load_manifest(ROOT / "manifests/compatibility.json").routes[0]
            config = dict(route.wireless_maintenance, asset="reader.zip",
                          dropbear_sha256=hashlib.sha256(b"fixture dropbear").hexdigest())
            route = replace(route, wireless_maintenance=config,
                            assets=(Asset("reader.zip", "https://example.invalid/reader.zip",
                                          hashlib.sha256(archive.read_bytes()).hexdigest(), "fixture"),))
            snapshot = {"firmware": "Kindle 5.20.1.0.2 (fixture)",
                        "device": {"serial_sha256": "a" * 64}}
            setup = prepare_plugin(route, archive, snapshot, root / "setup", 10)
            stage = Path(setup["stage"])
            self.assertTrue((stage / "koreader/plugins/KindlePilot.koplugin/main.lua").is_file())
            self.assertTrue((stage / "koreader/plugins/KindlePilot.koplugin/pairing_daemon.lua").is_file())
            self.assertTrue((stage / "koreader/plugins/KindlePilot.koplugin/pairing_daemon_entry.lua").is_file())
            self.assertTrue((stage / "koreader/KindlePilot/config.lua").is_file())
            self.assertTrue((stage / "koreader/KindlePilot/server_hostkey").is_file())
            self.assertFalse(any("id_ed25519" in name for name in setup["files"]))
            self.assertIn("pairing_port", (stage / "koreader/KindlePilot/config.lua").read_text())

    def test_transfer_uploads_and_reads_back_with_one_mtp_session(self):
        spec = importlib.util.spec_from_file_location("wireless_cli", ROOT / "scripts/kindle-wireless.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            stage = output / "stage"
            files = {"documents/KindlePilot-Wireless.sh": b"fixture launcher\n",
                     "kindlepilot/wireless/fixture/start.sh": b"fixture start\n"}
            for relative, data in files.items():
                local = stage / relative
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
            session = {"route": "vera-cs-5.20.1.0.2", "stage": str(stage),
                       "files": {p: hashlib.sha256(data).hexdigest() for p, data in files.items()}}
            session_file = output / "session.json"
            session_file.write_text(json.dumps(session))

            def transfer(commands):
                commands = list(commands)
                puts = [i for i, line in enumerate(commands) if line.startswith("put ")]
                gets = [i for i, line in enumerate(commands) if line.startswith("get ")]
                self.assertEqual(len(puts), 2)
                self.assertEqual(len(gets), 2)
                self.assertLess(max(puts), min(gets))
                for i, data in enumerate(files.values()):
                    (output / "readback" / str(i)).write_bytes(data)
                return SimpleNamespace(output="")

            with patch.object(cli, "MtpClient") as client, patch.object(
                    sys, "argv", ["kindle-wireless.py", "transfer", "--session", str(session_file)]):
                client.return_value.run.side_effect = transfer
                with redirect_stdout(StringIO()):
                    self.assertEqual(cli.main(), 0)
                client.return_value.run.assert_called_once()

    def test_tagged_identity_readback_handles_firmware_file_without_newline(self):
        route = load_manifest(ROOT / "manifests/compatibility.json").routes[0]
        session = dict(bind_interface="en0", source_ip="192.168.10.20", identity_file="private-key",
                       port=2224, known_hosts="known-hosts", host_key_alias="fixture-session",
                       firmware="5.20.1.0.2", serial_sha256="a" * 64)
        output = ("FIRMWARE=Kindle 5.20.1.0.2 (fixture)\nSERIAL=" + "a" * 64 + "  /proc/usid\nDROPBEAR="
                  + route.wireless_maintenance["dropbear_sha256"] + "  /mnt/us/koreader/dropbear\n")
        with patch("kindle_companion.wireless.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output, "")):
            self.assertTrue(verify_connection(session, route, "192.168.10.21")["identity_verified"])
        with patch("kindle_companion.wireless.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output.replace("a" * 64, "b" * 64), "")):
            with self.assertRaises(CompanionError):
                verify_connection(session, route, "192.168.10.21")

    def test_prepared_session_pins_host_and_keeps_client_private_key_off_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "reader.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("koreader/dropbear", b"fixture dropbear")
            route = load_manifest(ROOT / "manifests/compatibility.json").routes[0]
            config = dict(route.wireless_maintenance, asset="reader.zip",
                          dropbear_sha256=hashlib.sha256(b"fixture dropbear").hexdigest())
            route = replace(route, wireless_maintenance=config,
                            assets=(Asset("reader.zip", "https://example.invalid/reader.zip",
                                          hashlib.sha256(archive.read_bytes()).hexdigest(), "fixture"),))
            snapshot = {"firmware": "Kindle 5.20.1.0.2 (fixture)",
                        "device": {"serial_sha256": "a" * 64}}
            session = prepare_session(route, archive, snapshot, root / "session", "en0", "192.168.10.20", 10)
            stage = Path(session["stage"])
            self.assertFalse(any("id_ed25519" in name for name in session["files"]))
            private, public = dropbear_host_key((root / "session/server_openssh_key").read_bytes())
            self.assertEqual(len(private), 83)
            self.assertEqual(base64.b64decode(Path(session["known_hosts"]).read_text().split()[2]), public)
            command = ssh_arguments(session, "192.168.10.21")
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("HostKeyAlias=" + session["host_key_alias"], command)
            start = next(stage.rglob("start.sh")).read_text()
            stop = next(stage.rglob("stop.sh")).read_text()
            launcher = (stage / "documents/KindlePilot-Wireless.sh").read_text()
            embedded = next(line.split(",", 1)[1] for line in launcher.splitlines() if line.startswith("# Icon:"))
            self.assertEqual(hashlib.sha256(base64.b64decode(embedded)).hexdigest(), config["launcher_cover"]["sha256"])
            self.assertIn("-s -j -k", start)
            self.assertIn("! -s 192.168.10.20/32 --dport 2224 -j DROP", start)
            self.assertIn("iptables -D INPUT -p tcp ! -s 192.168.10.20/32 --dport 2224 -j DROP", stop)
            self.assertIn("192.168.10.20/32", stop)
            self.assertIn("sleep 10", stop)
            self.assertNotIn("@@", start + stop)
            self.assertFalse(session["native_collection_write_implied"])
            with self.assertRaises(CompanionError):
                prepare_session(route, archive, snapshot, root / "second", "en0", "127.0.0.1", 10)
            with self.assertRaises(CompanionError):
                ssh_arguments(session, "192.168.10.21; echo unsafe")


if __name__ == "__main__":
    unittest.main()
