#!/usr/bin/env python3
"""Prepare, transfer, connect and stop optional temporary Wi-Fi maintenance."""
from __future__ import annotations

import argparse
import ipaddress
import json
import shlex
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kindle_companion.manifest import load_manifest
from kindle_companion.models import CompanionError
from kindle_companion.mtp import MtpClient, quote_batch_arg
from kindle_companion.verify import sha256_file
from kindle_companion.wireless import prepare_session, ssh_arguments, verify_connection


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "manifests/compatibility.json")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="create fresh keys and device launchers locally")
    prepare.add_argument("--route", required=True)
    prepare.add_argument("--snapshot", type=Path, required=True)
    prepare.add_argument("--archive", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--interface", default="en0")
    prepare.add_argument("--duration", type=int, default=1800)
    for name in ("transfer", "connect", "discover", "stop"):
        command = sub.add_parser(name)
        command.add_argument("--session", type=Path, required=True)
        if name in {"connect", "stop"}:
            command.add_argument("--host", required=True)
        if name == "discover":
            command.add_argument("--network", required=True, help="explicit local IPv4 network, /24 or smaller")
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "prepare":
            route = next((r for r in manifest.routes if r.id == args.route), None)
            if not route:
                raise CompanionError("WIRELESS_ROUTE", "route not found")
            source = subprocess.check_output(["ipconfig", "getifaddr", args.interface], text=True).strip()
            result = prepare_session(route, args.archive, json.loads(args.snapshot.read_text()), args.output,
                                     args.interface, source, args.duration)
            print(json.dumps({"session": str(args.output / "session.json"), "files": len(result["files"]),
                              "device_started": False}, ensure_ascii=False))
            return 0
        session = json.loads(args.session.read_text())
        route = next((r for r in manifest.routes if r.id == session["route"]), None)
        if not route or not route.wireless_maintenance:
            raise CompanionError("WIRELESS_ROUTE", "session route not found")
        if args.command == "transfer":
            stage = Path(session["stage"])
            commands = []
            files = []
            for relative, digest in session["files"].items():
                local = stage / relative
                if local.resolve().is_relative_to(stage.resolve()) is False or sha256_file(local) != digest:
                    raise CompanionError("WIRELESS_STAGE", "session file changed before transfer")
                files.append((relative, local, digest))
                commands += ["mkpath " + quote_batch_arg("/" + str(Path(relative).parent)),
                             "put " + quote_batch_arg(local) + " " + quote_batch_arg("/" + str(Path(relative).parent))]
            readback = args.session.parent / "readback"
            readback.mkdir(exist_ok=True)
            commands += ["get " + quote_batch_arg("/" + relative) + " " + quote_batch_arg(readback / str(i))
                         for i, (relative, _, _) in enumerate(files)]
            result = MtpClient().run(commands + ["exit"])
            (args.session.parent / "transfer.log").write_text(result.output)
            if any(sha256_file(readback / str(i)) != digest for i, (_, _, digest) in enumerate(files)):
                raise CompanionError("WIRELESS_READBACK", "device file differs after transfer")
            print(json.dumps({"files_verified": len(files), "device_started": False,
                              "next": "disconnect USB; open KindlePilot - Wireless on the native Library"}))
        elif args.command == "connect":
            result = verify_connection(session, route, args.host)
            (args.session.parent / "connection.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
        elif args.command == "discover":
            network = ipaddress.IPv4Network(args.network, strict=False)
            if network.prefixlen < 24 or not network.is_private or ipaddress.IPv4Address(session["source_ip"]) not in network:
                raise CompanionError("WIRELESS_DISCOVERY", "select the host's explicit private subnet, /24 or smaller")

            def probe(address: ipaddress.IPv4Address) -> str | None:
                with socket.socket() as connection:
                    connection.bind((session["source_ip"], 0))
                    connection.settimeout(0.4)
                    try:
                        connection.connect((str(address), session["port"]))
                        return str(address)
                    except OSError:
                        return None

            with ThreadPoolExecutor(max_workers=24) as pool:
                candidates = [x for x in pool.map(probe, network.hosts()) if x]
            connected = []
            for host in candidates:
                try:
                    connected.append(verify_connection(session, route, host))
                except CompanionError:
                    continue
            if len(connected) != 1:
                raise CompanionError("WIRELESS_DISCOVERY", "expected exactly one server matching this session host key")
            (args.session.parent / "connection.json").write_text(json.dumps(connected[0], indent=2) + "\n")
            print(json.dumps(connected[0]))
        else:
            verify_connection(session, route, args.host)
            stop = shlex.quote(session["remote_base"] + "/stop.sh")
            command = "nohup sh -c " + shlex.quote("sleep 1; sh " + stop) + " >/dev/null 2>&1 </dev/null &"
            result = subprocess.run(ssh_arguments(session, args.host) + [command], capture_output=True, timeout=10)
            if result.returncode:
                raise CompanionError("WIRELESS_STOP", "stop command was not accepted")
            print(json.dumps({"stop_requested": True, "confirmed_stopped": False,
                              "next": "verify the listener is closed and read the session status"}))
        return 0
    except (CompanionError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
