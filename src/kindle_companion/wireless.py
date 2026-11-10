"""Prepare a short-lived, device-bound SSH session without replacing KOReader."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import base64
import re
import shlex
import struct
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .collections import write_new
from .compat import resolve_asset, route_firmware_status
from .models import CompanionError, Route
from .verify import sha256_file


START_TEMPLATE = r'''#!/bin/sh
# Name: KindlePilot - Wireless Maintenance
# Author: KindlePilot
set -eu
umask 077
BASE=@@BASE@@
HOSTKEY="$BASE/server_hostkey"
mkdir -p "$BASE/settings/SSH"
exec > "$BASE/start.log" 2>&1
[ "$(sha256sum /proc/usid | cut -d ' ' -f 1)" = '@@SERIAL@@' ]
[ "$(awk '{print $2}' /etc/prettyversion.txt)" = '@@FIRMWARE@@' ]
[ "$(sha256sum @@DROPBEAR@@ | cut -d ' ' -f 1)" = '@@DROPBEAR_SHA@@' ]
[ "$(sha256sum "$BASE/settings/SSH/authorized_keys" | cut -d ' ' -f 1)" = '@@PUBLIC_SHA@@' ]
[ "$(sha256sum "$BASE/stop.sh" | cut -d ' ' -f 1)" = '@@STOP_SHA@@' ]
[ "$(sha256sum "$HOSTKEY" | cut -d ' ' -f 1)" = '@@HOSTKEY_SHA@@' ]
if [ -r "$BASE/server.pid" ] && kill -0 "$(cat "$BASE/server.pid")" 2>/dev/null; then
 echo SESSION_ALREADY_RUNNING
 exit 0
fi
cd "$BASE"
IP=$(ip -4 addr show dev wlan0 | awk '/inet / {split($2,a,"/"); print a[1]; exit}')
[ -n "$IP" ] || { echo WIFI_ADDRESS_MISSING; exit 4; }
chmod 700 "$BASE" "$BASE/settings" "$BASE/settings/SSH"
chmod 600 "$BASE/settings/SSH/authorized_keys" "$HOSTKEY"
iptables -C INPUT -p tcp ! -s @@SOURCE@@/32 --dport @@PORT@@ -j DROP 2>/dev/null || iptables -I INPUT 1 -p tcp ! -s @@SOURCE@@/32 --dport @@PORT@@ -j DROP
iptables -C INPUT -p tcp -s @@SOURCE@@/32 --dport @@PORT@@ -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp -s @@SOURCE@@/32 --dport @@PORT@@ -j ACCEPT
iptables -C OUTPUT -p tcp -d @@SOURCE@@/32 --sport @@PORT@@ -j ACCEPT 2>/dev/null || iptables -I OUTPUT 1 -p tcp -d @@SOURCE@@/32 --sport @@PORT@@ -j ACCEPT
if ! @@DROPBEAR@@ -E -s -j -k -r "$HOSTKEY" -p "$IP:@@PORT@@" -P "$BASE/server.pid" > "$BASE/server.log" 2>&1; then
 sh "$BASE/stop.sh"
 exit 4
fi
nohup sh "$BASE/stop.sh" --timer > "$BASE/timer.log" 2>&1 </dev/null &
printf '%s\n' "$!" > "$BASE/timer.pid"
printf 'IP=%s\nPORT=@@PORT@@\nSOURCE=@@SOURCE@@\nDURATION=@@DURATION@@\nSTATE=running\n' "$IP" > "$BASE/status"
cat "$BASE/status"
sync
echo KINDLEPILOT_WIRELESS_READY
if command -v eips >/dev/null 2>&1; then
 eips 1 2 "KindlePilot wireless ready" || :
 eips 1 3 "$IP:@@PORT@@ (key login)" || :
fi
'''

STOP_TEMPLATE = r'''#!/bin/sh
set -eu
BASE=@@BASE@@
if [ "${1:-}" = --timer ]; then
 sleep @@DURATION@@
elif [ -r "$BASE/timer.pid" ]; then
 TIMER=$(cat "$BASE/timer.pid")
 case "$TIMER" in ''|*[!0-9]*) exit 4;; esac
 if [ -r "/proc/$TIMER/cmdline" ] && tr '\000' ' ' < "/proc/$TIMER/cmdline" | grep -F "$BASE/stop.sh --timer" >/dev/null; then
  kill "$TIMER" 2>/dev/null || :
 fi
fi
if [ -r "$BASE/server.pid" ]; then
 PID=$(cat "$BASE/server.pid")
 case "$PID" in ''|*[!0-9]*) exit 4;; esac
 if [ -r "/proc/$PID/cmdline" ] && tr '\000' ' ' < "/proc/$PID/cmdline" | grep -F "$BASE/server.pid" >/dev/null; then
  pkill -TERM -P "$PID" 2>/dev/null || :
  kill "$PID" 2>/dev/null || :
 fi
 rm -f "$BASE/server.pid"
fi
iptables -D INPUT -p tcp -s @@SOURCE@@/32 --dport @@PORT@@ -j ACCEPT 2>/dev/null || :
iptables -D INPUT -p tcp ! -s @@SOURCE@@/32 --dport @@PORT@@ -j DROP 2>/dev/null || :
iptables -D OUTPUT -p tcp -d @@SOURCE@@/32 --sport @@PORT@@ -j ACCEPT 2>/dev/null || :
printf 'STATE=stopped\n' > "$BASE/status"
rm -f "$BASE/settings/SSH/authorized_keys" "$BASE/server_hostkey"
sync
'''


def _render(template: str, values: dict[str, str]) -> bytes:
    for key, value in values.items():
        template = template.replace("@@" + key + "@@", value)
    if re.search(r"@@[A-Z_]+@@", template):
        raise CompanionError("WIRELESS_TEMPLATE", "unresolved wireless template field")
    return template.encode()


def _ssh_string(data: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(data):
        raise CompanionError("WIRELESS_HOST_KEY", "truncated SSH key field")
    size = struct.unpack_from(">I", data, offset)[0]
    end = offset + 4 + size
    if end > len(data):
        raise CompanionError("WIRELESS_HOST_KEY", "truncated SSH key value")
    return data[offset + 4:end], end


def _wire_string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def dropbear_host_key(openssh_private: bytes) -> tuple[bytes, bytes]:
    """Convert a freshly generated unencrypted OpenSSH Ed25519 host key.

    Dropbear stores the algorithm and the 64-byte seed/public pair as SSH
    strings. Public wire bytes are returned for exact host-key pinning.
    """
    lines = openssh_private.splitlines()
    raw = base64.b64decode(b"".join(lines[1:-1]), validate=True)
    if not raw.startswith(b"openssh-key-v1\x00"):
        raise CompanionError("WIRELESS_HOST_KEY", "expected an OpenSSH key")
    pos = len(b"openssh-key-v1\x00")
    cipher, pos = _ssh_string(raw, pos)
    kdf, pos = _ssh_string(raw, pos)
    _, pos = _ssh_string(raw, pos)
    if cipher != b"none" or kdf != b"none" or struct.unpack_from(">I", raw, pos)[0] != 1:
        raise CompanionError("WIRELESS_HOST_KEY", "expected one unencrypted session host key")
    public, pos = _ssh_string(raw, pos + 4)
    private, _ = _ssh_string(raw, pos)
    if private[:4] != private[4:8]:
        raise CompanionError("WIRELESS_HOST_KEY", "host-key check values differ")
    algorithm, pos = _ssh_string(private, 8)
    pub, pos = _ssh_string(private, pos)
    secret, _ = _ssh_string(private, pos)
    if algorithm != b"ssh-ed25519" or len(pub) != 32 or len(secret) != 64 or secret[32:] != pub:
        raise CompanionError("WIRELESS_HOST_KEY", "invalid Ed25519 host key")
    if public != _wire_string(algorithm) + _wire_string(pub):
        raise CompanionError("WIRELESS_HOST_KEY", "public host key differs from its private key")
    return _wire_string(algorithm) + _wire_string(secret), public


def prepare_session(route: Route, archive: Path, snapshot: dict[str, Any], output: Path,
                    interface: str, source_ip: str, duration: int = 1800) -> dict[str, Any]:
    config = route.wireless_maintenance
    if not config:
        raise CompanionError("WIRELESS_UNSUPPORTED", "route has no wireless maintenance capability")
    ip = ipaddress.IPv4Address(source_ip)
    if not ip.is_private or ip.is_loopback or not re.fullmatch(r"[A-Za-z0-9_.-]+", interface):
        raise CompanionError("WIRELESS_SOURCE", "expected the current host LAN interface and private IPv4 address")
    if not 10 <= duration <= config["maximum_duration_seconds"]:
        raise CompanionError("WIRELESS_DURATION", "wireless duration is outside the route limit")
    fw = re.search(r"\b\d+\.\d+(?:\.\d+)*\b", snapshot["firmware"])
    serial = snapshot["device"]["serial_sha256"]
    if not fw or route_firmware_status(route, fw.group()) != "supported" or not re.fullmatch(r"[0-9a-f]{64}", serial or ""):
        raise CompanionError("WIRELESS_IDENTITY", "snapshot must bind this exact firmware and device serial digest")
    if sha256_file(archive) != resolve_asset(route, config["asset"]).sha256:
        raise CompanionError("WIRELESS_ASSET_HASH", "KOReader archive differs from compatibility manifest")
    with zipfile.ZipFile(archive) as source:
        if hashlib.sha256(source.read(config["dropbear_member"])).hexdigest() != config["dropbear_sha256"]:
            raise CompanionError("WIRELESS_DROPBEAR_HASH", "embedded Dropbear differs from the qualified component")
    if output.exists() and any(output.iterdir()):
        raise CompanionError("WIRELESS_OUTPUT", "use a new session directory; resume existing sessions from session.json")
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    session_id = uuid.uuid4().hex
    private_key = output.resolve() / "id_ed25519"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "kindlepilot-" + session_id,
                    "-f", str(private_key)], check=True, capture_output=True)
    public_key = private_key.with_suffix(".pub").read_bytes()
    host_key_path = output / "server_openssh_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "kindlepilot-server-" + session_id,
                    "-f", str(host_key_path)], check=True, capture_output=True)
    host_key, host_public = dropbear_host_key(host_key_path.read_bytes())
    base = "/mnt/us/kindlepilot/wireless/" + session_id
    values = {"BASE": shlex.quote(base), "SOURCE": str(ip), "PORT": str(config["port"]),
              "DURATION": str(duration), "FIRMWARE": fw.group(), "SERIAL": serial,
              "DROPBEAR": shlex.quote(config["dropbear_path"]),
              "HOSTKEY_SHA": hashlib.sha256(host_key).hexdigest(),
              "DROPBEAR_SHA": config["dropbear_sha256"], "PUBLIC_SHA": hashlib.sha256(public_key).hexdigest()}
    stop = _render(STOP_TEMPLATE, values)
    values["STOP_SHA"] = hashlib.sha256(stop).hexdigest()
    start = _render(START_TEMPLATE, values)
    remote_base = Path("kindlepilot/wireless") / session_id
    stage = output / "stage"
    write_new(stage / remote_base / "settings/SSH/authorized_keys", public_key)
    write_new(stage / remote_base / "stop.sh", stop)
    write_new(stage / remote_base / "start.sh", start)
    write_new(stage / remote_base / "server_hostkey", host_key)
    (stage / remote_base / "server_hostkey").chmod(0o600)
    icon = b""
    if config.get("launcher_cover"):
        cover = config["launcher_cover"]
        path = Path(__file__).resolve().parents[2] / cover["path"]
        if sha256_file(path) != cover["sha256"]:
            raise CompanionError("WIRELESS_COVER_HASH", "launcher cover differs from the manifest")
        icon = b"# Icon: data:image/png;base64," + base64.b64encode(path.read_bytes()) + b"\n"
    launcher = ("#!/bin/sh\n# Name: KindlePilot - Wireless Maintenance\n# Author: KindlePilot\n").encode() + icon + (
                "set -eu\n"
                + '[ "$(sha256sum ' + shlex.quote(base + "/start.sh") + " | cut -d ' ' -f 1)\" = \""
                + hashlib.sha256(start).hexdigest() + '" ]\nsh ' + shlex.quote(base + "/start.sh") + "\n").encode()
    write_new(stage / "documents/KindlePilot-Wireless.sh", launcher)
    local_known_hosts = output.resolve() / "known_hosts"
    host_alias = "kindlepilot-" + session_id
    write_new(local_known_hosts, host_alias.encode() + b" ssh-ed25519 " + base64.b64encode(host_public) + b"\n")
    files = {str(p.relative_to(stage)): sha256_file(p) for p in stage.rglob("*") if p.is_file()}
    result = {"schema": "kindle-pilot-wireless-session/v1", "session_id": session_id,
              "route": route.id, "firmware": fw.group(), "serial_sha256": serial,
              "source_ip": str(ip), "bind_interface": interface, "port": config["port"],
              "duration_seconds": duration, "remote_base": base, "stage": str(stage.resolve()),
              "identity_file": str(private_key), "known_hosts": str(local_known_hosts), "files": files,
              "host_key_alias": host_alias,
              "device_started": False, "native_collection_write_implied": False}
    write_new(output / "session.json", (json.dumps(result, indent=2) + "\n").encode())
    return result


def ssh_arguments(session: dict[str, Any], host: str) -> list[str]:
    """Pin the session host key even when DHCP changes the device address."""
    try:
        ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError as exc:
        raise CompanionError("WIRELESS_HOST", "expected an observed device IPv4 address") from exc
    return ["ssh", "-B", session["bind_interface"], "-b", session["source_ip"],
            "-i", session["identity_file"], "-p", str(session["port"]),
            "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
            "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + session["known_hosts"],
            "-o", "HostKeyAlias=" + session["host_key_alias"], "root@" + host]


def verify_connection(session: dict[str, Any], route: Route, host: str) -> dict[str, Any]:
    config = route.wireless_maintenance
    dropbear_path = session.get("dropbear_path", config["dropbear_path"])
    if dropbear_path not in {config["dropbear_path"], config.get("pairing_dropbear_path")}:
        raise CompanionError("WIRELESS_IDENTITY", "session runtime path is not declared by the route")
    serial_hash_mode = session.get("serial_hash_mode", "proc_usid")
    if serial_hash_mode not in {"proc_usid", "usb_serial"}:
        raise CompanionError("WIRELESS_IDENTITY", "unknown serial digest mode")
    serial_command = ("tr -d '\\r\\n' < /proc/usid | sha256sum" if serial_hash_mode == "usb_serial"
                      else "sha256sum /proc/usid")
    command = ("printf 'FIRMWARE='; cat /etc/prettyversion.txt; printf '\\nSERIAL='; "
               + serial_command + "; printf 'DROPBEAR='; sha256sum "
               + shlex.quote(dropbear_path))
    result = subprocess.run(ssh_arguments(session, host) + [command], capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise CompanionError("WIRELESS_CONNECTION", result.stderr.strip() or "SSH connection failed")
    lines = result.stdout.splitlines()
    fields = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines if "=" in line}
    fw = re.search(r"\b\d+\.\d+(?:\.\d+)*\b", fields.get("FIRMWARE", ""))
    serial = fields.get("SERIAL", "").split()[0] if fields.get("SERIAL") else ""
    dropbear = fields.get("DROPBEAR", "").split()[0] if fields.get("DROPBEAR") else ""
    if (set(fields) != {"FIRMWARE", "SERIAL", "DROPBEAR"} or not fw
            or fw.group() != session["firmware"] or serial != session["serial_sha256"]
            or dropbear != route.wireless_maintenance["dropbear_sha256"]):
        raise CompanionError("WIRELESS_IDENTITY", "SSH connected but device identity or component changed")
    return {"host": host, "ssh_connected": True, "host_key_pinned": True,
            "identity_verified": True, "firmware": fw.group(), "dropbear_path": dropbear_path,
            "dropbear_sha256": dropbear, "native_collection_write_implied": False}
