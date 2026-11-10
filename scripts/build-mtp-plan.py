#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kindle_companion.models import CompanionError
from kindle_companion.plan import build_delete_plan, build_put_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an auditable OpenMTP batch file")
    parser.add_argument("mode", choices=("put", "delete"))
    parser.add_argument("local_or_path")
    parser.add_argument("remote_root", nargs="?")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "put":
            if not args.remote_root:
                parser.error("put requires REMOTE_ROOT")
            commands = build_put_plan(Path(args.local_or_path), args.remote_root)
        else:
            commands = build_delete_plan(args.local_or_path.split(","))
    except CompanionError as exc:
        parser.error(f"[{exc.code}] {exc.message}")
    text = "\n".join(commands) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
