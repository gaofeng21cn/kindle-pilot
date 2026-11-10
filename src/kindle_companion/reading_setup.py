"""Prepare Moon, Kindle Library and wireless maintenance in one install batch."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .collections import write_new
from .compat import product_code, resolve_asset, route_firmware_status
from .models import CompanionError, DeviceIdentity, Route
from .mtp import MtpClient, parse_listing, parse_storage_info, quote_batch_arg
from .pairing import prepare_plugin
from .verify import sha256_file


def snapshot_from_state(route: Route, state: dict[str, Any]) -> dict[str, Any]:
    device = state.get("device") or {}
    firmware = state.get("firmware") or ""
    serial = device.get("serial") or ""
    if (state.get("route") != route.id or state.get("route_status") != "supported"
            or product_code(device.get("product", "")) not in route.device_codes
            or route_firmware_status(route, firmware) != "supported"
            or not re.fullmatch(r"[A-Z0-9]+", serial)):
        raise CompanionError("READING_IDENTITY", "probe state must identify this exact device and firmware")
    if state.get("steps", {}).get("install_koreader", {}).get("status") != "done":
        raise CompanionError("READING_KOREADER", "install and confirm KOReader before preparing its plugins")
    return {"firmware": firmware, "device": {"serial_sha256": hashlib.sha256(serial.encode()).hexdigest()},
            "serial_hash_mode": "usb_serial"}


def _extract_plugin(archive: Path, root: str, stage: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (not path.parts or path.parts[0] != root or path.is_absolute()
                    or ".." in path.parts or "\\" in entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise CompanionError("READING_ARCHIVE", "plugin archive contains an unsafe or unexpected path")
        names = {entry.filename for entry in entries}
        if not {root + "/main.lua", root + "/_meta.lua"} <= names:
            raise CompanionError("READING_ARCHIVE", "plugin archive has no loadable main.lua and _meta.lua")
        for entry in entries:
            if not entry.is_dir():
                write_new(stage / "koreader/plugins" / entry.filename, source.read(entry))


def prepare_reading_setup(route: Route, state: dict[str, Any], asset_dir: Path, output: Path,
                          *, wireless: bool | None = None, existing_wireless: Path | None = None) -> dict[str, Any]:
    snapshot = snapshot_from_state(route, state)
    config = route.reading_environment
    if not config:
        raise CompanionError("READING_UNSUPPORTED", "route has no reading environment declaration")
    if wireless is None:
        wireless = config["wireless_maintenance_default"]
    if output.exists() and any(output.iterdir()):
        raise CompanionError("READING_OUTPUT", "use a new reading setup directory")
    selected = [component["asset"] for component in config["plugins"]]
    if wireless:
        if not route.wireless_maintenance or route.wireless_maintenance.get("status") != "verified":
            raise CompanionError("WIRELESS_UNSUPPORTED", "route has no qualified wireless transport")
        if not existing_wireless:
            selected.append(route.wireless_maintenance["asset"])
    for name in set(selected):
        if sha256_file(asset_dir / name) != resolve_asset(route, name).sha256:
            raise CompanionError("READING_ASSET_HASH", f"asset differs from compatibility manifest: {name}")
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    stage = output / "stage"
    components = []
    for component in config["plugins"]:
        _extract_plugin(asset_dir / component["asset"], component["directory"], stage)
        components.append({"directory": "koreader/plugins/" + component["directory"],
                           "asset": component["asset"]})
    wireless_setup = None
    if wireless and existing_wireless:
        previous = json.loads(existing_wireless.read_text())
        # Reuse an identity only when the local record can bind it to this USB device.
        if (previous.get("route") != route.id or previous.get("firmware") != snapshot["firmware"]
                or previous.get("serial_hash_mode") != "usb_serial"
                or previous.get("serial_sha256") != snapshot["device"]["serial_sha256"]):
            raise CompanionError("READING_WIRELESS_IDENTITY", "existing setup must bind this USB serial and firmware; keep legacy installs on their existing wireless workflow")
        wireless_setup = str(existing_wireless.resolve())
    elif wireless:
        setup = prepare_plugin(route, asset_dir / route.wireless_maintenance["asset"], snapshot, output / "wireless")
        wireless_setup = str((output / "wireless/setup.json").resolve())
        for relative in setup["files"]:
            write_new(stage / relative, (Path(setup["stage"]) / relative).read_bytes())
    files = {str(path.relative_to(stage)): sha256_file(path) for path in sorted(stage.rglob("*")) if path.is_file()}
    result = {"schema": "kindle-pilot-reading-setup/v1", "route": route.id,
              "firmware": snapshot["firmware"], "usb_serial_sha256": snapshot["device"]["serial_sha256"],
              "stage": str(stage.resolve()), "components": components, "files": files,
              "wireless_setup": wireless_setup, "reuse_wireless": bool(wireless and existing_wireless),
              "device_written": False, "application_loaded": False, "accounts_verified": False}
    write_new(output / "reading-setup.json", (json.dumps(result, indent=2) + "\n").encode())
    return result


def transfer_reading_setup(plan_path: Path, route: Route, device: DeviceIdentity,
                           client: MtpClient) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text())
    if (plan.get("schema") != "kindle-pilot-reading-setup/v1" or plan.get("route") != route.id
            or product_code(device.product) not in route.device_codes
            or hashlib.sha256(device.serial.encode()).hexdigest() != plan["usb_serial_sha256"]
            or route_firmware_status(route, plan["firmware"]) != "supported"):
        raise CompanionError("READING_IDENTITY", "connected USB device differs from the prepared install")
    if not route.reading_environment:
        raise CompanionError("READING_UNSUPPORTED", "route has no reading environment declaration")
    receipt_path = plan_path.parent / "transfer-receipt.json"
    if receipt_path.exists():
        raise CompanionError("READING_ALREADY_TRANSFERRED", "read the existing receipt; application and pairing checks are next")
    stage = Path(plan["stage"])
    components = [{"directory": "koreader/plugins/" + p["directory"], "asset": p["asset"]}
                  for p in route.reading_environment["plugins"]]
    if plan["components"] != components or not all(
            component["directory"] + "/" + name in plan["files"]
            for component in components for name in ("main.lua", "_meta.lua")):
        raise CompanionError("READING_STAGE", "prepared component list is incomplete or differs from the route")
    if set(plan["files"]) != {str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file()}:
        raise CompanionError("READING_STAGE", "staged file list changed after preparation")
    allowed_roots = [component["directory"] for component in components]
    allowed_roots += ["koreader/plugins/KindlePilot.koplugin", "koreader/KindlePilot", "kindlepilot/runtime"]
    for relative, digest in plan["files"].items():
        local = stage / relative
        if (PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts
                or any(char in relative for char in ("\\", "\r", "\n", "\x00"))
                or not any(relative.startswith(root + "/") for root in allowed_roots)
                or not local.resolve().is_relative_to(stage.resolve()) or local.is_symlink()
                or sha256_file(local) != digest):
            raise CompanionError("READING_STAGE", "staged file changed or is outside the declared plugin targets")
    # One read-only preflight, followed by one write/readback session. No competing clients.
    preflight = client.run(["lsext-r /koreader", "storage-info 65537", "exit"])
    (plan_path.parent / "preflight.log").write_text(preflight.output)
    names = set(parse_listing(preflight.output))
    if not {"luajit", "reader.lua"} <= names:
        raise CompanionError("READING_KOREADER", "KOReader runtime is missing; finish its KPM installation first")
    skipped = []
    for component in plan["components"]:
        relative = component["directory"].removeprefix("koreader/")
        if relative in names or any(name.startswith(relative + "/") for name in names):
            if not {relative + "/main.lua", relative + "/_meta.lua"} <= names:
                raise CompanionError("READING_PARTIAL", "existing plugin is incomplete; inspect before replacing: " + relative)
            skipped.append(component["directory"])
    wireless_names = ["KindlePilot", "settings/KindlePilot", "plugins/KindlePilot.koplugin"]
    wireless_exists = any(name == root or name.startswith(root + "/") for name in names for root in wireless_names)
    if plan["wireless_setup"] and not plan["reuse_wireless"] and wireless_exists:
        raise CompanionError("READING_WIRELESS_EXISTS", "reuse the existing pairing setup; device host identity must not be replaced")
    commands = []
    checks = []
    if plan["reuse_wireless"]:
        setup = json.loads(Path(plan["wireless_setup"]).read_text())
        base = setup["remote_base"]
        if base not in {"/mnt/us/koreader/KindlePilot", "/mnt/us/koreader/settings/KindlePilot"}:
            raise CompanionError("READING_WIRELESS_IDENTITY", "unexpected existing wireless identity path")
        if not {"plugins/KindlePilot.koplugin/main.lua", "plugins/KindlePilot.koplugin/pairing_daemon.lua",
                "plugins/KindlePilot.koplugin/pairing_daemon_entry.lua"} <= names:
            raise CompanionError("READING_PARTIAL", "existing wireless plugin is incomplete")
        checks.append((base.removeprefix("/mnt/us/") + "/server_hostkey", setup["host_key_sha256"]))
    files = [(relative, digest) for relative, digest in plan["files"].items()
             if not any(relative.startswith(root + "/") for root in skipped)]
    needed = sum((stage / relative).stat().st_size for relative, _ in files)
    if parse_storage_info(preflight.output)["free_bytes"] < needed + 10 * 1024 * 1024:
        raise CompanionError("READING_SPACE", "insufficient free space for the plugin batch plus 10 MiB reserve")
    readback = plan_path.parent / "readback"
    readback.mkdir(exist_ok=True)
    # Verify a reused identity before any plugin upload in this batch.
    for i, (relative, _) in enumerate(checks):
        commands.append("get " + quote_batch_arg("/" + relative) + " " + quote_batch_arg(readback / ("identity-" + str(i))))
    if checks:
        client.run(commands + ["exit"])
        for i, (_, digest) in enumerate(checks):
            if sha256_file(readback / ("identity-" + str(i))) != digest:
                raise CompanionError("READING_WIRELESS_IDENTITY", "device host key differs from the existing pairing record")
    commands = []
    for relative, _ in files:
        parent = "/" + str(PurePosixPath(relative).parent)
        commands += ["mkpath " + quote_batch_arg(parent),
                     "put " + quote_batch_arg(stage / relative) + " " + quote_batch_arg(parent)]
    commands += ["get " + quote_batch_arg("/" + relative) + " " + quote_batch_arg(readback / str(i))
                 for i, (relative, _) in enumerate(files)]
    result = client.run(commands + ["storage-info 65537", "exit"])
    (plan_path.parent / "transfer.log").write_text(result.output)
    for i, (_, digest) in enumerate(files):
        if sha256_file(readback / str(i)) != digest:
            raise CompanionError("READING_READBACK", "device file differs after transfer")
    receipt = {"schema": "kindle-pilot-reading-transfer/v1", "files_verified": len(files),
               "reused_plugins": skipped, "wireless_setup": plan["wireless_setup"],
               "storage": parse_storage_info(result.output), "mtp_readback_verified": True,
               "application_loaded": False, "wireless_paired": False, "accounts_verified": False,
               "next": "disconnect USB; launch KOReader and Moon; open KindlePilot 无线维护 and pair"}
    write_new(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode())
    return receipt
