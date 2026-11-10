#!/usr/bin/env python3
"""Install Moon, Kindle Library and wireless pairing together after KOReader setup."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kindle_companion.discovery import discover
from kindle_companion.manifest import load_manifest
from kindle_companion.models import CompanionError
from kindle_companion.mtp import MtpClient
from kindle_companion.reading_setup import prepare_reading_setup, transfer_reading_setup
from kindle_companion.state import load_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifests/compatibility.json")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="verify pinned archives and prepare one plugin batch locally")
    prepare.add_argument("--state", type=Path, required=True)
    prepare.add_argument("--asset-dir", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--without-wireless", action="store_true", help="skip wireless provisioning when the user opts out")
    prepare.add_argument("--wireless-setup", type=Path, help="reuse an existing USB-bound wireless setup.json")
    transfer = sub.add_parser("transfer", help="check the connected device; upload missing plugins and read back every file")
    transfer.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        data = load_state(args.state) if args.command == "prepare" else json.loads(args.plan.read_text())
        route = next((r for r in manifest.routes if r.id == data.get("route")), None)
        if not route:
            raise CompanionError("READING_ROUTE", "state or setup has no supported route; probe the Kindle first")
        if args.command == "prepare":
            if args.without_wireless and args.wireless_setup:
                raise CompanionError("READING_OPTIONS", "choose either no wireless provisioning or reuse an existing setup")
            result = prepare_reading_setup(route, data, args.asset_dir, args.output,
                                           wireless=False if args.without_wireless else None, existing_wireless=args.wireless_setup)
            targets = ["/" + component["directory"] for component in result["components"]]
            if result["wireless_setup"] and not result["reuse_wireless"]:
                targets += ["/koreader/plugins/KindlePilot.koplugin", "/koreader/KindlePilot", "/kindlepilot/runtime/dropbear"]
            print(json.dumps({"plan": str(args.output / "reading-setup.json"), "files": len(result["files"]),
                              "wireless_setup": result["wireless_setup"], "device_written": False,
                              "targets": targets},
                             ensure_ascii=False))
        else:
            device = discover()
            result = transfer_reading_setup(args.plan, route, device, MtpClient())
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (CompanionError, OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
