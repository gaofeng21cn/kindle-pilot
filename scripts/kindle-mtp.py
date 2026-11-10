#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kindle_companion.mtp import MtpClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe single-session OpenMTP helper")
    parser.add_argument("command", choices=("storage", "ls", "delete", "mkdir", "put"))
    parser.add_argument("values", nargs="*")
    args = parser.parse_args()
    client = MtpClient()
    if args.command == "storage":
        output = client.storage_info()
    elif args.command == "ls":
        output = client.list_path(args.values[0] if args.values else "/")
    elif args.command == "delete":
        output = client.delete_paths(args.values)
    elif args.command == "mkdir":
        output = client.mkdir(args.values[0])
    elif args.command == "put":
        if len(args.values) != 2:
            parser.error("put requires LOCAL_PATH REMOTE_DIR")
        output = client.put(Path(args.values[0]), args.values[1])
    else:  # pragma: no cover
        parser.error(args.command)
    if isinstance(output, dict) or isinstance(output, list):
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(output.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
