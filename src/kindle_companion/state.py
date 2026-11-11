from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CompanionError


STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    actor: str
    prerequisites: tuple[str, ...] = ()
    manual: bool = False


STEPS: tuple[Step, ...] = (
    Step(
        "prevent_update",
        "Prevent automatic firmware update",
        "user",
        ("connected", "route_supported"),
        manual=True,
    ),
    Step(
        "download_assets",
        "Download and verify the selected Véra assets",
        "agent",
        ("route_supported",),
    ),
    Step(
        "transfer_assets",
        "Transfer the two Véra books to /documents",
        "agent",
        ("download_assets", "connected"),
    ),
    Step(
        "font_calibration",
        "Configure the Font Calibration theme",
        "user",
        ("transfer_assets",),
        manual=True,
    ),
    Step(
        "trigger_jailbreak",
        "Open the Véra book and confirm the JAILBROKEN marker",
        "user",
        ("font_calibration",),
        manual=True,
    ),
    Step(
        "remove_fillers",
        "Remove temporary filler files and stale update bins",
        "agent",
        ("trigger_jailbreak",),
    ),
    Step(
        "kpm_ready",
        "Confirm KPM commands are available",
        "user",
        ("trigger_jailbreak",),
        manual=True,
    ),
    Step(
        "install_koreader",
        "Install and launch KOReader",
        "agent",
        ("kpm_ready",),
    ),
    Step(
        "install_plugins",
        "Install Moon and kindle.koplugin",
        "agent",
        ("install_koreader",),
    ),
    Step(
        "install_wireless",
        "Provision the wireless pairing plugin with the reading environment",
        "agent",
        ("install_koreader",),
    ),
    Step(
        "runtime_verify",
        "Verify KOReader, Moon, and Kindle Library runtime behavior",
        "user",
        ("install_plugins",),
        manual=True,
    ),
    Step(
        "wireless_verify",
        "Pair over Wi-Fi and verify device identity and session cleanup",
        "agent",
        ("install_wireless",),
    ),
    Step(
        "account_login",
        "Complete WeRead and Fanqie QR sign-in",
        "user",
        ("runtime_verify",),
        manual=True,
    ),
    Step(
        "library_verify",
        "Open representative books and verify local and account shelves",
        "user",
        ("account_login",),
        manual=True,
    ),
)

STEP_INDEX = {step.id: step for step in STEPS}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "device": None,
        "firmware": None,
        "route": None,
        "route_status": None,
        "steps": {
            step.id: {
                "status": "pending",
                "updated_at": None,
                "evidence": "",
            }
            for step in STEPS
        },
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanionError("STATE_READ", f"cannot read state {path}: {exc}") from exc
    if data.get("schema_version") != STATE_SCHEMA_VERSION:
        raise CompanionError("STATE_SCHEMA", f"unsupported state schema in {path}")
    if not isinstance(data.get("steps"), dict):
        raise CompanionError("STATE_SHAPE", f"state {path} has no steps object")
    for step in STEPS:
        data["steps"].setdefault(
            step.id,
            {"status": "pending", "updated_at": None, "evidence": ""},
        )
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _prerequisites_met(state: dict[str, Any], step: Step) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for prerequisite in step.prerequisites:
        if prerequisite in STEP_INDEX:
            status = state["steps"].get(prerequisite, {}).get("status")
            if status != "done":
                missing.append(prerequisite)
            continue
        if prerequisite == "connected":
            if not state.get("device"):
                missing.append(prerequisite)
            continue
        if prerequisite == "route_supported":
            if state.get("route_status") != "supported":
                missing.append(prerequisite)
            continue
        missing.append(prerequisite)
    return not missing, missing


def record_step(
    state: dict[str, Any],
    step_id: str,
    status: str,
    evidence: str = "",
    confirmed: bool = False,
) -> dict[str, Any]:
    step = STEP_INDEX.get(step_id)
    if not step:
        raise CompanionError("STEP_UNKNOWN", f"unknown workflow step: {step_id}")
    if status not in {"pending", "done", "blocked", "not_applicable"}:
        raise CompanionError("STEP_STATUS", f"invalid step status: {status}")
    if step.manual and status == "done" and not confirmed:
        raise CompanionError(
            "CONFIRMATION_REQUIRED",
            f"step {step_id} is a user-visible action; repeat with --confirmed after observing it",
        )
    met, missing = _prerequisites_met(state, step)
    if status == "done" and not met:
        raise CompanionError(
            "STEP_PREREQUISITE",
            f"cannot complete {step_id}; missing: {', '.join(missing)}",
        )
    state["steps"][step_id] = {
        "status": status,
        "updated_at": utc_now(),
        "evidence": evidence,
    }
    return state["steps"][step_id]


def summarize(state: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    next_step = None
    for step in STEPS:
        status = state["steps"][step.id]["status"]
        counts[status] = counts.get(status, 0) + 1
        if next_step is None and status not in {"done", "not_applicable"}:
            next_step = {
                "id": step.id,
                "title": step.title,
                "actor": step.actor,
                "manual": step.manual,
            }
    return {
        "device": state.get("device"),
        "firmware": state.get("firmware"),
        "route": state.get("route"),
        "route_status": state.get("route_status"),
        "counts": counts,
        "next_step": next_step,
        "steps": state["steps"],
    }
