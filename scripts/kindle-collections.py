#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kindle_companion.collections import KCAdapter, inventory, write_new
from kindle_companion.manifest import load_manifest
from kindle_companion.models import CompanionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KindlePilot native collection inventory and guarded KC capability trial")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "manifests/compatibility.json")
    parser.add_argument("--route", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage", help="prepare hash-checked runtime and device launchers locally")
    stage.add_argument("--checker", required=True, type=Path)
    stage.add_argument("--output", required=True, type=Path)
    inspect = sub.add_parser("inspect", help="group indexed local books without changing collections")
    inspect.add_argument("--snapshot", required=True, type=Path)
    inspect.add_argument("--scope", default="/mnt/us/documents/Downloads/Items01")
    inspect.add_argument("--native-catalog", type=Path, help="matching catalog export with collection visibility")
    inspect.add_argument("--output", required=True, type=Path)
    probe = sub.add_parser("probe", help="prepare the fixed six-step test for one uncollected local book")
    probe.add_argument("--snapshot", required=True, type=Path)
    probe.add_argument("--book", required=True)
    probe.add_argument("--output", required=True, type=Path)
    receipt = sub.add_parser("receipt", help="compare a KC receipt with the request and a fresh device snapshot")
    receipt.add_argument("--request", required=True, type=Path)
    receipt.add_argument("--result", required=True, type=Path)
    receipt.add_argument("--snapshot", required=True, type=Path)
    plan = sub.add_parser("plan-series", help="preview additions for explicit series; unsupported firmware remains blocked")
    plan.add_argument("--snapshot", required=True, type=Path)
    plan.add_argument("--scope", default="/mnt/us/documents/Downloads/Items01")
    plan.add_argument("--prefix", default="漫画｜")
    plan.add_argument("--series", action="append", required=True)
    plan.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        route = next((r for r in load_manifest(args.manifest).routes if r.id == args.route), None)
        if route is None:
            raise CompanionError("ROUTE_NOT_FOUND", args.route)
        adapter = KCAdapter(args.archive, route)
        snapshot = adapter.snapshot(args.snapshot) if hasattr(args, "snapshot") else None
        if args.command == "stage":
            result = adapter.stage(args.checker, args.output)
        elif args.command == "inspect":
            native = json.loads(args.native_catalog.read_text()) if args.native_catalog else None
            report = inventory(snapshot, args.scope, native)
            write_new(args.output, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
            result = {"series": len(report["series"]), "local_books": sum(len(s["books"]) for s in report["series"]),
                      "unmatched": len(report["unmatched"]), "collections": len(report["collections"]), "output": str(args.output)}
        elif args.command == "probe":
            result = adapter.prepare_probe(snapshot, args.book, args.output)
        elif args.command == "receipt":
            result = adapter.receipt(args.request, args.result, snapshot)
        else:
            result = adapter.plan_series(snapshot, args.scope, args.prefix, args.series)
            write_new(args.output, adapter.protocol.canonical(result))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "receipt" and not result["verified"]:
            return 3
        if args.command == "plan-series" and result["blockers"]:
            return 3
        return 0
    except (CompanionError, OSError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
