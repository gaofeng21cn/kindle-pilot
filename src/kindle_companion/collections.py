from __future__ import annotations

import hashlib
import importlib
import re
import sys
import types
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from .compat import resolve_asset, route_firmware_status
from .models import CompanionError, Route
from .verify import sha256_file


RUNTIME_FILES = (
    "run.sh", "refresh.sh", "policy.sh", "export.sql", "prepare-edit.sql",
    "verify-edit.sql", "validate-request.sql", "backup-check.sh",
    "kc-backup-check", "mtp.sh", "kc-screen",
)
FORMATS = {".azw", ".azw3", ".mobi", ".prc", ".kfx", ".pdf", ".txt"}


def write_new(path: Path, data: bytes) -> None:
    """Resume identical preparation without replacing a different artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and path.read_bytes() != data):
        raise CompanionError("COLLECTION_OUTPUT_CONFLICT", f"existing output differs: {path}")
    if not path.exists():
        with path.open("xb") as handle:
            handle.write(data)


def series_name(location: str) -> str | None:
    stem = PurePosixPath(location).stem
    # KXO push IDs are removed only at the end; a hyphen within a title is kept.
    stem = re.sub(r"_[A-Z0-9]{20,40}$", "", stem)
    match = re.fullmatch(r"(.+?)\s+-\s+(?:(?:第)?\d+.*[卷巻话話冊册]|[卷巻话話冊册].*).*", stem)
    return match.group(1).strip() if match else None


def inventory(snapshot: dict[str, Any], scope: str) -> dict[str, Any]:
    """Use indexed UUIDs and exact source paths; never infer missing files."""
    root = PurePosixPath(scope)
    if not root.is_absolute() or ".." in root.parts or not str(root).startswith("/mnt/us/documents/"):
        raise CompanionError("COLLECTION_SCOPE", "scope must be under /mnt/us/documents/")
    counts = Counter(r["book_uuid"] for r in snapshot["relations"])
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded: list[dict[str, str]] = []
    for book in snapshot["books"]:
        location = book.get("location")
        if not location:
            continue
        path = PurePosixPath(location)
        if (not path.is_relative_to(root) or ".." in path.parts
                or any(p.startswith(".") or p.lower().endswith(".sdr") for p in path.parts[4:])
                or path.suffix.lower() not in FORMATS):
            continue
        name = series_name(location)
        if name is None:
            excluded.append({"uuid": book["uuid"], "reason": "unrecognized_series", "location": location})
            continue
        groups[name].append({
            "uuid": book["uuid"], "title": book["title"], "location": location,
            "format": path.suffix.lower().lstrip("."),
            "collection_count": book["collection_count"],
            "relation_count": counts[book["uuid"]],
            "counts_consistent": book["collection_count"] == counts[book["uuid"]],
        })
    return {
        "schema": "kindle-pilot-series/v1", "snapshot_id": snapshot["snapshot_id"],
        "device": snapshot["device"], "firmware": snapshot["firmware"], "scope": str(root),
        "collections": snapshot["collections"],
        "series": [{"name": n, "books": sorted(v, key=lambda b: b["location"])} for n, v in sorted(groups.items())],
        "unmatched": excluded,
    }


class KCAdapter:
    """Headless access to the pinned KC release's pure planner and contracts.

    The Calibre plugin entrypoint and UI are not imported. Device writes remain
    owned by KC's backup, precondition, capability and pending-result checks.
    """

    def __init__(self, archive: Path, route: Route) -> None:
        self.route = route
        self.config = route.native_collections
        if not self.config:
            raise CompanionError("COLLECTION_UNSUPPORTED", "route has no native collection adapter")
        asset = resolve_asset(route, self.config["asset"])
        if sha256_file(archive) != asset.sha256:
            raise CompanionError("COLLECTION_ARCHIVE_HASH", "KC archive SHA-256 does not match the manifest")
        self.archive = archive.resolve()
        name = "_kindlepilot_kc_" + asset.sha256[:16]
        package = types.ModuleType(name)
        package.__path__ = [str(self.archive)]
        # Reload the namespace for this verified archive, not a stale cache path.
        for old in list(sys.modules):
            if old == name or old.startswith(name + "."):
                del sys.modules[old]
        sys.modules[name] = package
        self.protocol = importlib.import_module(name + ".protocol")
        self.planner = importlib.import_module(name + ".planner")
        self.probe = importlib.import_module(name + ".probe")
        self.ledger = importlib.import_module(name + ".ledger")

    def snapshot(self, path: Path) -> dict[str, Any]:
        value = self.checked(self.protocol.validate, self.checked(self.protocol.loads, path.read_bytes()))
        if value["schema"] != "kc-bookshelf-export/v2":
            raise CompanionError("COLLECTION_SNAPSHOT", "expected a KC read-only snapshot")
        match = re.search(r"\b\d+\.\d+(?:\.\d+)*\b", value["firmware"])
        if not match or route_firmware_status(self.route, match.group()) != "supported":
            raise CompanionError("COLLECTION_FIRMWARE", "snapshot firmware does not match this exact route")
        return value

    def checked(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except self.protocol.Invalid as exc:
            raise CompanionError("COLLECTION_CONTRACT", str(exc)) from exc

    def runtime(self, checker: Path) -> dict[str, bytes]:
        build = self.config["checker_build"]
        if sha256_file(checker) != build["artifact_sha256"]:
            raise CompanionError("COLLECTION_CHECKER_HASH", "compiled checker differs from the verified manifest artifact")
        with zipfile.ZipFile(self.archive) as source:
            files = {n: source.read("runtime/" + n) for n in RUNTIME_FILES}
        files["kc-backup-check"] = checker.read_bytes()
        return files

    def launcher(self, files: dict[str, bytes], mode: str) -> bytes:
        titles = {"check": "Check Native Collections", "probe": "Test Native Collections", "edit": "Apply Native Collections"}
        if mode not in titles:
            raise CompanionError("COLLECTION_MODE", "unknown launcher mode")
        if mode == "edit" and self.config.get("status") != "verified":
            raise CompanionError("COLLECTION_UNVERIFIED", "native collection edits are not verified for this route")
        runtime = "/mnt/us/kc-sync/runtime/" + self.config["runtime_id"]
        if not re.fullmatch(r"/mnt/us/kc-sync/runtime/[A-Za-z0-9.-]+", runtime):
            raise CompanionError("COLLECTION_RUNTIME_PATH", "invalid runtime identifier")
        checks = "\n".join(
            '[ "$(sha256sum ' + runtime + '/' + n + " | cut -d ' ' -f 1)\" = \""
            + hashlib.sha256(files[n]).hexdigest() + '" ] || exit 4' for n in RUNTIME_FILES
        )
        option = {"check": "--refresh", "probe": "--self-test", "edit": ""}[mode]
        text = (
            "#!/bin/sh\n# Name: KindlePilot - " + titles[mode] + "\n# Author: KindlePilot\n"
            "set -eu\numask 077\nmkdir -p /mnt/us/kc-sync/pilot\n"
            "exec > /mnt/us/kc-sync/pilot/" + mode + ".log 2>&1\n" + checks + "\n"
        )
        if mode == "check":
            text += (
                "printf 'FIRMWARE='; cat /etc/prettyversion.txt; printf '\\n'\n"
                "for c in sqlite3 uuidgen sha256sum curl stat; do command -v \"$c\"; done\n"
                "if [ -s /tmp/session_token ]; then echo TOKEN_PRESENT=1; else echo TOKEN_PRESENT=0; fi\n"
            )
        text += "sh " + runtime + "/run.sh " + option + "\n"
        text += "echo KINDLEPILOT_ENTRY_FINISHED\nsync\n"
        return text.encode("utf-8")

    def stage(self, checker: Path, output: Path) -> dict[str, Any]:
        files = self.runtime(checker)
        for name, data in files.items():
            write_new(output / "kc-sync/runtime" / self.config["runtime_id"] / name, data)
        # Editing is offered only after this firmware's complete device acceptance.
        modes = ["check", "probe"]
        if self.config.get("status") == "verified":
            modes.append("edit")
        for mode in modes:
            suffix = {"check": "Check", "probe": "Test", "edit": "Apply"}[mode]
            write_new(output / "documents" / ("KindlePilot-Collections-" + suffix + ".sh"), self.launcher(files, mode))
        return {"runtime": self.config["runtime_id"], "output": str(output), "modes": modes, "device_write": False}

    def prepare_probe(self, snapshot: dict[str, Any], book_uuid: str, output: Path) -> dict[str, Any]:
        used = {r["book_uuid"] for r in snapshot["relations"]}
        books = {b["uuid"]: b for b in snapshot["books"]}
        book = books.get(book_uuid)
        if (not book or not book["location"] or PurePosixPath(book["location"]).suffix.lower() not in FORMATS
                or book_uuid in used or book["collection_count"] != 0):
            raise CompanionError("COLLECTION_PROBE_BOOK", "probe requires an indexed local book with no existing memberships and count zero")
        request = self.checked(self.probe.prepare_probe, snapshot, book_uuid, "kindlepilot-" + snapshot["device"]["instance_id"])
        paths = self.queue(request, "probe", output)
        return {"job_id": request["job_id"], "collection": request["operations"][0]["args"]["name"],
                "book_uuid": book_uuid, "book_title": book["title"],
                "operations": [o["kind"] for o in request["operations"]], "paths": paths, "device_write": False}

    def queue(self, request: dict[str, Any], mode: str, output: Path) -> list[str]:
        request = self.checked(self.protocol.validate, request)
        if mode not in {"probe", "edit"} or not re.fullmatch(r"[0-9a-fA-F-]{36}", request["job_id"]):
            raise CompanionError("COLLECTION_QUEUE", "invalid job or mode")
        if mode == "edit" and self.config.get("status") != "verified":
            raise CompanionError("COLLECTION_UNVERIFIED", "native collection edits are not verified for this route")
        raw = self.protocol.canonical(request)
        name = request["job_id"]
        folder = output / "kc-sync/mtp-inbox"
        marker = (hashlib.sha256(raw).hexdigest() + " " + mode + "\n").encode("ascii")
        write_new(folder / (name + ".json"), raw)
        write_new(folder / (name + ".ready"), marker)
        return [str(folder / (name + ext)) for ext in (".json", ".ready")]

    def receipt(self, request_path: Path, result_path: Path, current: dict[str, Any]) -> dict[str, Any]:
        request = self.checked(self.protocol.loads, request_path.read_bytes())
        result = self.checked(self.protocol.loads, result_path.read_bytes())
        rows = self.checked(self.ledger.validate_receipt, request, result)
        if current["device"] != request["device"]:
            raise CompanionError("COLLECTION_DEVICE", "snapshot and receipt belong to different devices")
        cat = self.checked(self.planner.Catalog, current)
        last = {o["collection_uuid"]: o for o in request["operations"]}
        durable = []
        for cid, op in last.items():
            state = cat.state(cid)
            durable.append({"collection_uuid": cid, "expected": op["after"], "observed": state, "matches": state == op["after"]})
        relation_counts = Counter(r["book_uuid"] for r in current["relations"])
        touched = {uid for op in request["operations"] for uid in op["args"].get("members", [])}
        is_probe = [o["kind"] for o in request["operations"]] == [
            "create_collection", "rename_collection", "add_members", "remove_members", "add_members", "delete_collection",
        ]
        counts = []
        for uid in sorted(touched):
            book = cat.books.get(uid)
            expected = 0 if is_probe else relation_counts[uid]
            counts.append({"book_uuid": uid, "expected": expected,
                           "observed": book["collection_count"] if book else None,
                           "matches": book is not None and book["collection_count"] == expected
                           and relation_counts[uid] == expected})
        confirmed = all(row["status"] == "confirmed" for row in rows.values())
        refreshed = self.protocol.digest(current) != request["snapshot_digest"]
        return {"job_id": request["job_id"], "all_operations_confirmed": confirmed,
                "operations": [{"kind": o["kind"], **rows[o["op_id"]]} for o in request["operations"]],
                "current_state": durable,
                "book_counts": counts,
                "snapshot_refreshed": refreshed,
                "verified": confirmed and refreshed and all(r["matches"] for r in durable + counts),
                "capabilities": current["capabilities"]["verified_operations"]}

    def plan_series(self, snapshot: dict[str, Any], scope: str, prefix: str, selected: list[str]) -> dict[str, Any]:
        if not selected:
            raise CompanionError("COLLECTION_SELECTION", "select explicit series names; inventory does not authorize a batch")
        report = inventory(snapshot, scope)
        groups = {s["name"]: s["books"] for s in report["series"]}
        existing: dict[str, list[str]] = defaultdict(list)
        for shelf in snapshot["collections"]:
            existing[shelf["name"]].append(shelf["uuid"])
        intents, adopted = [], []
        from uuid import uuid4
        for name in selected:
            if name not in groups:
                raise CompanionError("COLLECTION_SERIES", "series not found in the indexed scope: " + name)
            if any(not b["counts_consistent"] for b in groups[name]):
                raise CompanionError("COLLECTION_COUNTS", "native membership counts are inconsistent; no edits planned for: " + name)
            title = prefix + name
            ids = existing.get(title, [])
            if len(ids) > 1:
                raise CompanionError("COLLECTION_NAME", "multiple collections have the same name")
            cid = ids[0] if ids else str(uuid4())
            if ids:
                adopted.append(cid)
            else:
                intents.append(self.planner.intent("create_collection", cid, {"name": title}))
            intents.append(self.planner.intent("add_members", cid, {"members": sorted(b["uuid"] for b in groups[name])}))
        plan = self.checked(self.planner.plan, snapshot, intents, adopted, "kindlepilot-" + snapshot["device"]["instance_id"])
        value = plan.data
        if self.config.get("status") != "verified":
            value["blockers"].append({"code": "ROUTE_NOT_VERIFIED", "message": "This model/firmware has not passed durable native collection acceptance.", "collection_uuid": None})
            value = self.protocol.seal(value, "plan_digest")
        return value
