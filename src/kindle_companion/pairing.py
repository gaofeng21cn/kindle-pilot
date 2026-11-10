"""KOReader-plugin pairing for recurring Kindle wireless maintenance."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import socket
import subprocess
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .collections import write_new
from .compat import resolve_asset, route_firmware_status
from .models import CompanionError, Route
from .verify import sha256_file
from .wireless import dropbear_host_key, verify_connection

PLUGIN_ROOT = Path("assets/kindlepilot.koplugin")


def validate_pairing_code(code: str, digits: int = 6) -> str:
    value = code.strip().upper()
    if not re.fullmatch(r"[0-9A-F]{" + str(digits) + r"}", value):
        raise CompanionError("WIRELESS_PAIRING_CODE", f"pairing code must be {digits} hexadecimal characters")
    return value


def pairing_public_b64(public_key: bytes) -> str:
    fields = public_key.decode("ascii").strip().split()
    if len(fields) < 2 or fields[0] != "ssh-ed25519":
        raise CompanionError("WIRELESS_PAIRING_KEY", "expected an Ed25519 OpenSSH public key")
    return fields[1]


def pairing_proof(code: str, client_nonce: str, client_public_b64: str, device_nonce: str) -> str:
    normalized_code = code.strip().upper()
    if len(normalized_code) not in (6, 12) or not re.fullmatch(r"[0-9A-F]+", normalized_code):
        raise CompanionError("WIRELESS_PAIRING_CODE", "pairing code must be 6 hexadecimal characters")
    if (not re.fullmatch(r"[0-9a-fA-F]{32}", client_nonce)
            or not re.fullmatch(r"[0-9a-fA-F]{32}", device_nonce)):
        raise CompanionError("WIRELESS_PAIRING_NONCE", "pairing nonce must be 16 random bytes in hex")
    if not re.fullmatch(r"[A-Za-z0-9+/=]{40,180}", client_public_b64):
        raise CompanionError("WIRELESS_PAIRING_KEY", "pairing public key is not valid base64")
    message = f"{client_nonce}|{client_public_b64}|{device_nonce}".encode()
    return hmac.new(normalized_code.encode(), message, hashlib.sha1).hexdigest()


def _plugin_config(values: dict[str, Any]) -> bytes:
    lines = ["return {\n"]
    for key, value in values.items():
        if isinstance(value, str):
            lines.append(f"    {key} = {json.dumps(value, ensure_ascii=False)},\n")
        else:
            lines.append(f"    {key} = {value},\n")
    lines.append("}\n")
    return "".join(lines).encode()


def _stop_script(base: str, ssh_port: int) -> bytes:
    return f'''#!/bin/sh
set -eu
BASE={base!r}
PID="$BASE/dropbear.pid"
AUTH="$BASE/settings/SSH/authorized_keys"
if [ -r "$PID" ]; then kill "$(cat "$PID")" 2>/dev/null || :; fi
SOURCE=$(awk -F= '/^SOURCE=/ {{print $2}}' "$BASE/status" 2>/dev/null || :)
case "$SOURCE" in ''|*[!0-9.]*) SOURCE=;; esac
if [ -n "$SOURCE" ]; then
  iptables -D INPUT -p tcp -s "$SOURCE/32" --dport {ssh_port} -j ACCEPT 2>/dev/null || :
  iptables -D INPUT -p tcp ! -s "$SOURCE/32" --dport {ssh_port} -j DROP 2>/dev/null || :
  iptables -D OUTPUT -p tcp -d "$SOURCE/32" --sport {ssh_port} -j ACCEPT 2>/dev/null || :
fi
rm -f "$PID" "$AUTH" "$BASE/timer.pid"
printf 'STATE=stopped\\n' > "$BASE/status"
sync
'''.encode()


def prepare_plugin(route: Route, archive: Path, snapshot: dict[str, Any], output: Path,
                   duration: int = 1800) -> dict[str, Any]:
    config = route.wireless_maintenance
    if not config:
        raise CompanionError("WIRELESS_UNSUPPORTED", "route has no wireless maintenance capability")
    if output.exists() and any(output.iterdir()):
        raise CompanionError("WIRELESS_OUTPUT", "use a new KOReader pairing setup directory")
    firmware_match = re.search(r"\b\d+\.\d+(?:\.\d+)*\b", snapshot["firmware"])
    serial = snapshot["device"]["serial_sha256"]
    if (not firmware_match or route_firmware_status(route, firmware_match.group()) != "supported"
            or not re.fullmatch(r"[0-9a-f]{64}", serial or "")):
        raise CompanionError("WIRELESS_IDENTITY", "snapshot must bind this exact firmware and device serial digest")
    if not 10 <= duration <= config["maximum_duration_seconds"]:
        raise CompanionError("WIRELESS_DURATION", "wireless duration is outside the route limit")
    if sha256_file(archive) != resolve_asset(route, config["asset"]).sha256:
        raise CompanionError("WIRELESS_ASSET_HASH", "KOReader archive differs from compatibility manifest")
    with zipfile.ZipFile(archive) as source:
        if hashlib.sha256(source.read(config["dropbear_member"])).hexdigest() != config["dropbear_sha256"]:
            raise CompanionError("WIRELESS_DROPBEAR_HASH", "embedded Dropbear differs from the qualified component")
    output.mkdir(parents=True, exist_ok=True); output.chmod(0o700)
    setup_id = uuid.uuid4().hex
    host_path = output / "server_openssh_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "kindlepilot-plugin-" + setup_id,
                    "-f", str(host_path)], check=True, capture_output=True)
    host_key, host_public = dropbear_host_key(host_path.read_bytes())
    host_public_b64 = base64.b64encode(host_public).decode()
    base = "/mnt/us/koreader/KindlePilot"
    stage = output / "stage"
    plugin_stage = stage / "koreader/plugins/KindlePilot.koplugin"
    for name in ("_meta.lua", "main.lua"):
        write_new(plugin_stage / name, (PLUGIN_ROOT / name).read_bytes())
    write_new(stage / "koreader/KindlePilot/config.lua", _plugin_config({
        "pairing_port": config["pairing_port"], "ssh_port": config["port"],
        "pairing_code_digits": config["pairing_code_digits"],
        "pairing_code_ttl_seconds": config["pairing_code_ttl_seconds"],
        "pairing_max_attempts": config["pairing_max_attempts"],
        "session_duration_seconds": duration, "host_public_b64": host_public_b64,
    }))
    write_new(stage / "koreader/KindlePilot/server_hostkey", host_key)
    write_new(stage / "koreader/KindlePilot/server_hostkey.pub", (host_public_b64 + "\n").encode())
    write_new(stage / "koreader/KindlePilot/stop.sh", _stop_script(base, config["port"]))
    (stage / "koreader/KindlePilot/server_hostkey").chmod(0o600)
    files = {str(p.relative_to(stage)): sha256_file(p) for p in stage.rglob("*") if p.is_file()}
    setup = {"schema": "kindle-pilot-koreader-pairing/v1", "setup_id": setup_id,
             "route": route.id, "firmware": firmware_match.group(), "serial_sha256": serial,
             "pairing_port": config["pairing_port"], "ssh_port": config["port"],
             "duration_seconds": duration, "remote_base": base, "stage": str(stage.resolve()),
             "host_public_b64": host_public_b64, "host_key_sha256": hashlib.sha256(host_key).hexdigest(),
             "files": files, "device_started": False}
    write_new(output / "setup.json", (json.dumps(setup, indent=2) + "\n").encode())
    return setup


def _network(source_ip: str, value: str | None) -> ipaddress.IPv4Network:
    address = ipaddress.IPv4Address(source_ip)
    if not address.is_private or address.is_loopback:
        raise CompanionError("WIRELESS_SOURCE", "pairing requires a private LAN source address")
    network = ipaddress.IPv4Network(value, strict=False) if value else ipaddress.IPv4Network(f"{source_ip}/24", strict=False)
    if not network.is_private or network.prefixlen < 24 or address not in network:
        raise CompanionError("WIRELESS_DISCOVERY", "pairing network must be an explicit private /24 or smaller subnet")
    return network


def _candidate(host: str, source_ip: str, code: str, setup: dict[str, Any], identity: Path) -> dict[str, Any] | None:
    nonce = uuid.uuid4().hex; public = pairing_public_b64(identity.with_suffix(".pub").read_bytes())
    try:
        with socket.create_connection((host, int(setup["pairing_port"])), timeout=1.2) as client:
            client.settimeout(2.5); client.sendall(f"KINDLEPILOT/PAIR1 HELLO {nonce}\n".encode())
            challenge_lines = client.recv(256).decode(errors="replace").splitlines()
            if not challenge_lines: return None
            challenge = challenge_lines[0].split()
            if len(challenge) != 3 or challenge[:2] != ["KINDLEPILOT/PAIR1", "CHALLENGE"]: return None
            proof = pairing_proof(code, nonce, public, challenge[2])
            client.sendall(f"KINDLEPILOT/PAIR1 AUTH {nonce} {public} {proof}\n".encode())
            response_lines = client.recv(512).decode(errors="replace").splitlines()
            if not response_lines: return None
            response = response_lines[0].split()
            if len(response) != 6 or response[:2] != ["KINDLEPILOT/PAIR1", "OK"]: return None
            _, _, session, host_public, port, duration = response
            if host_public != setup["host_public_b64"]: return None
            return {"host": host, "session_id": session, "host_public_b64": host_public,
                    "port": int(port), "duration_seconds": int(duration)}
    except (OSError, UnicodeError, ValueError, CompanionError, IndexError): return None


def pair_session(route: Route, setup: dict[str, Any], output: Path, source_ip: str,
                 code: str, network: str | None = None) -> dict[str, Any]:
    configured_digits = int(route.wireless_maintenance["pairing_code_digits"])
    normalized_code = code.strip().upper()
    if len(normalized_code) == 12 and configured_digits == 6:
        # Accept one-time codes from the pre-0.2.0 plugin while the device is
        # being updated; new plugin instances emit six-character codes.
        validate_pairing_code(normalized_code, 12)
    else:
        validate_pairing_code(normalized_code, configured_digits)
    if setup.get("route") != route.id: raise CompanionError("WIRELESS_PAIRING_IDENTITY", "setup route differs")
    net = _network(source_ip, network); output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()): raise CompanionError("WIRELESS_OUTPUT", "use a new pairing session directory")
    identity = output / "id_ed25519"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "kindlepilot-session-" + uuid.uuid4().hex,
                    "-f", str(identity)], check=True, capture_output=True)
    with ThreadPoolExecutor(max_workers=24) as pool:
        results = [result for result in pool.map(lambda address: _candidate(str(address), source_ip, normalized_code, setup, identity), net.hosts()) if result]
    if len(results) != 1: raise CompanionError("WIRELESS_PAIRING_DISCOVERY", "expected one paired Kindle")
    paired = results[0]; alias = "kindlepilot-plugin-" + setup["setup_id"]
    known_hosts = output / "known_hosts"
    write_new(known_hosts, (alias + " ssh-ed25519 " + paired["host_public_b64"] + "\n").encode())
    session = {"schema": "kindle-pilot-wireless-session/v2", "session_id": paired["session_id"],
               "setup_id": setup["setup_id"], "route": route.id, "firmware": setup["firmware"],
               "serial_sha256": setup["serial_sha256"], "source_ip": source_ip,
               "bind_interface": setup.get("bind_interface", "en0"), "port": paired["port"],
               "remote_base": setup["remote_base"], "identity_file": str(identity.resolve()),
               "known_hosts": str(known_hosts.resolve()), "host_key_alias": alias,
               "host": paired["host"], "duration_seconds": paired["duration_seconds"],
               "pairing_code_used": True, "transport": "koreader_plugin_pairing",
               "device_started": True, "native_collection_write_implied": False}
    write_new(output / "session.json", (json.dumps(session, indent=2) + "\n").encode())
    verified = verify_connection(session, route, paired["host"])
    session["identity_verified"] = verified["identity_verified"]
    (output / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    write_new(output / "connection.json", (json.dumps(verified, indent=2) + "\n").encode())
    return session
