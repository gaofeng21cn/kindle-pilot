from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .capabilities import capability_info
from .compat import decide_route
from .discovery import discover
from .manifest import load_manifest
from .models import CompanionError
from .state import load_state, record_step, save_state, summarize
from .verify import verify_asset


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests" / "compatibility.json"
DEFAULT_STATE = Path("kindle-pilot-state.json")


def _emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _error(exc: CompanionError, json_mode: bool) -> int:
    if json_mode:
        _emit({"ok": False, "error": {"code": exc.code, "message": exc.message}})
    else:
        print(f"ERROR [{exc.code}] {exc.message}", file=sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kindle-pilot",
        description="Kindle Pilot Agent-guided Kindle install and library workflow",
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--json", action="store_true", dest="json_mode")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="detect USB identity and compatibility")
    probe.add_argument("--firmware", required=True)
    probe.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)

    sub.add_parser("status", help="show persisted workflow state")
    sub.add_parser("software-info", help="read software identity without accessing a device or task")
    sub.add_parser("capabilities", help="list package-owned KindlePilot capability modules")

    step = sub.add_parser("record-step", help="record a workflow observation")
    step.add_argument("step_id")
    step.add_argument(
        "--status",
        choices=("pending", "done", "blocked", "not_applicable"),
        default="done",
    )
    step.add_argument("--evidence", default="")
    step.add_argument("--confirmed", action="store_true")

    asset = sub.add_parser("resolve-asset", help="show one verified asset declaration")
    asset.add_argument("asset_name")
    asset.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    asset.add_argument("--route", required=True)

    verify = sub.add_parser("verify-asset", help="check an asset SHA-256")
    verify.add_argument("path", type=Path)
    verify.add_argument("--sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "software-info":
            from .software import software_info

            _emit(software_info(PROJECT_ROOT))
            return 0

        if args.command == "capabilities":
            _emit(capability_info(PROJECT_ROOT))
            return 0

        if args.command == "probe":
            manifest = load_manifest(args.manifest)
            device = discover()
            decision = decide_route(manifest, device, args.firmware)
            state = load_state(args.state)
            state["device"] = device.as_dict()
            state["firmware"] = args.firmware
            state["route"] = decision.route.id if decision.route else None
            state["route_status"] = (
                "supported" if decision.firmware_status == "supported" else "unsupported"
            )
            save_state(args.state, state)
            _emit(
                {
                    "ok": True,
                    "device": device.as_dict(),
                    "firmware": args.firmware,
                    "decision": decision.as_dict(),
                    "state_path": str(args.state),
                }
            )
            return 0 if decision.allowed else 3

        if args.command == "status":
            _emit({"ok": True, "state": summarize(load_state(args.state))})
            return 0

        if args.command == "record-step":
            state = load_state(args.state)
            step = record_step(
                state,
                args.step_id,
                args.status,
                evidence=args.evidence,
                confirmed=args.confirmed,
            )
            save_state(args.state, state)
            _emit({"ok": True, "step": args.step_id, "record": step})
            return 0

        if args.command == "resolve-asset":
            manifest = load_manifest(args.manifest)
            route = next((r for r in manifest.routes if r.id == args.route), None)
            if route is None:
                raise CompanionError("ROUTE_NOT_FOUND", f"route not found: {args.route}")
            selected = next((a for a in route.assets if a.name == args.asset_name), None)
            if selected is None:
                raise CompanionError(
                    "ASSET_NOT_FOUND",
                    f"asset not declared for {args.route}: {args.asset_name}",
                )
            _emit(
                {
                    "ok": True,
                    "asset": {
                        "name": selected.name,
                        "url": selected.url,
                        "sha256": selected.sha256,
                        "source": selected.source,
                        "required": selected.required,
                        "redistribute": selected.redistribute,
                        "license": selected.license,
                    },
                }
            )
            return 0

        if args.command == "verify-asset":
            result = verify_asset(args.path, args.sha256)
            _emit({"ok": bool(result["ok"]), "verification": result})
            return 0 if result["ok"] else 4

        raise CompanionError("COMMAND_UNKNOWN", f"unknown command: {args.command}")
    except CompanionError as exc:
        return _error(exc, args.json_mode)


if __name__ == "__main__":
    raise SystemExit(main())
