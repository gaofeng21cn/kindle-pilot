#!/usr/bin/env python3
"""Export, preview and apply exact native collection targets over SSH."""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kindle_companion.collection_additions import (
    CATALOG_SQL,
    prepare_addition,
    prepare_rename,
    prepare_retirement,
    verify_addition,
)
from kindle_companion.collections import write_new
from kindle_companion.manifest import load_manifest
from kindle_companion.models import CompanionError
from kindle_companion.wireless import ssh_arguments, verify_connection


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "manifests/compatibility.json")
    parser.add_argument("--route", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export-sql", help="write the read-only catalog query")
    export.add_argument("--output", type=Path, required=True)
    preview = sub.add_parser("preview", help="prepare a local addition preview")
    preview.add_argument("--catalog", type=Path, required=True)
    preview.add_argument("--targets", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    rename = sub.add_parser("rename-preview", help="prepare exact collection title changes without touching a device")
    rename.add_argument("--catalog", type=Path, required=True)
    rename.add_argument("--targets", type=Path, required=True)
    rename.add_argument("--output", type=Path, required=True)
    retire = sub.add_parser("retire-preview", help="prepare exact task-owned collection retirement")
    retire.add_argument("--catalog", type=Path, required=True)
    retire.add_argument("--targets", type=Path, required=True)
    retire.add_argument("--output", type=Path, required=True)
    apply = sub.add_parser("apply", help="apply explicit create/add targets using a bound SSH connection")
    for option in ("host", "session", "targets", "state-dir"):
        apply.add_argument("--" + option, required=True)
    apply.add_argument("--operation", choices=("add", "rename", "retire"), default="add",
                       help="apply additions, exact renames, or task-owned retirement")
    args = parser.parse_args()
    try:
        route = next((r for r in load_manifest(args.manifest).routes if r.id == args.route), None)
        if not route or not route.native_collections:
            raise CompanionError("COLLECTION_ROUTE", "native collection route is missing")
        if args.command == "export-sql":
            write_new(args.output, CATALOG_SQL.encode())
            return 0
        target_file = json.loads(Path(args.targets).read_text())
        targets = target_file["collections"]
        if args.command == "rename-preview":
            catalog = json.loads(args.catalog.read_text())
            write_new(args.output, encode([prepare_rename(catalog, target) for target in targets]))
            return 0
        if args.command == "retire-preview":
            catalog = json.loads(args.catalog.read_text())
            original_ids = set(target_file.get("original_collection_ids", []))
            destinations = {str(uid): set(collection_ids) for uid, collection_ids in target_file.get("destinations", {}).items()}
            write_new(args.output, encode([
                prepare_retirement(catalog, target, original_ids, destinations)
                for target in targets
            ]))
            return 0
        ids = [t["uuid"] for t in targets]
        if len(ids) != len(set(ids)) or not targets or len(targets) > 50:
            raise CompanionError("COLLECTION_TARGET", "expected 1-50 distinct explicit targets")
        if args.command == "preview":
            catalog = json.loads(args.catalog.read_text())
            write_new(args.output, encode([prepare_addition(catalog, t, int(time.time())) for t in targets]))
            return 0
        operation = args.operation
        config_key = "task_owned_cleanup" if operation == "retire" else "additions"
        config = route.native_collections.get(config_key, {})
        native_config = route.native_collections.get("additions", {})
        if config.get("status") != "verified":
            raise CompanionError("COLLECTION_UNVERIFIED", f"native {operation} changes are not qualified for this route")
        session = json.loads(Path(args.session).read_text())
        if session["route"] != route.id:
            raise CompanionError("COLLECTION_IDENTITY", "wireless session belongs to a different route")
        verify_connection(session, route, args.host)
        ssh = ssh_arguments(session, args.host)

        def remote(command: str, data: bytes | None = None, timeout: int = 60) -> bytes:
            result = subprocess.run(ssh + [command], input=data, capture_output=True, timeout=timeout)
            if result.returncode:
                raise CompanionError("COLLECTION_SSH", result.stderr.decode(errors="replace") + result.stdout.decode(errors="replace"))
            return result.stdout

        observed = remote("sha256sum /usr/lib/ccat/change.lua").decode().split()
        if not observed or observed[0] != native_config["native_change_sha256"]:
            raise CompanionError("COLLECTION_IDENTITY", "native service changed")

        def catalog() -> dict:
            return json.loads(remote("sqlite3 -batch -bail -readonly /var/local/cc.db", CATALOG_SQL.encode()))

        state = Path(args.state_dir)
        state.mkdir(parents=True, exist_ok=True)
        raw_targets = Path(args.targets).read_bytes()
        state_identity = encode({"operation": operation, "targets_sha256": hashlib.sha256(raw_targets).hexdigest()})
        identity_path = state / "operation.json"
        if identity_path.exists() and identity_path.read_bytes() != state_identity:
            raise CompanionError("COLLECTION_STATE_CONFLICT", "state directory belongs to a different operation or target file")
        write_new(identity_path, state_identity)
        write_new(state / "targets.json", raw_targets)
        base = "/mnt/us/kc-sync/pilot/" + operation + "-" + hashlib.sha256(raw_targets).hexdigest()[:16]
        remote("mkdir -p " + shlex.quote(base))
        results = []

        def prepare_target(before: dict, target: dict) -> dict:
            if operation == "add":
                return prepare_addition(before, target, int(time.time()))
            if operation == "rename":
                return prepare_rename(before, target)
            original_ids = set(target_file.get("original_collection_ids", []))
            destinations = {str(uid): set(collection_ids)
                            for uid, collection_ids in target_file.get("destinations", {}).items()}
            return prepare_retirement(before, target, original_ids, destinations)

        def verify_target(before: dict, after: dict, prepared: dict) -> dict:
            if operation == "add":
                return verify_addition(before, after, prepared)
            if operation == "rename":
                return verify_rename(before, after, prepared)
            return verify_retirement(before, after, prepared)

        for index, target in enumerate(targets):
            row = state / str(index)
            if (row / "prepared.json").exists():
                prepared = json.loads((row / "prepared.json").read_text())
                before = json.loads((row / "before.json").read_text())
                verdict = verify_target(before, catalog(), prepared)
                if not verdict["verified"]:
                    raise CompanionError("COLLECTION_RECONCILE", "saved change requires read-only reconciliation; no replay")
                results.append(verdict)
                continue
            before = catalog()
            prepared = prepare_target(before, target)
            if not prepared["payload"]["commands"]:
                results.append({"name": target.get("name", target.get("current_name", target["uuid"])), "already_present": True})
                continue
            write_new(row / "before.json", encode(before))
            write_new(row / "prepared.json", encode(prepared))
            body = encode(prepared["payload"])
            write_new(row / "request.json", body)
            rdir = base + "/" + str(index)
            remote("mkdir " + shlex.quote(rdir))
            remote("cat > " + shlex.quote(rdir + "/request.json"), body)
            if remote("cat " + shlex.quote(rdir + "/request.json")) != body:
                raise CompanionError("COLLECTION_TRANSFER", "request readback differs")
            script = f'''set -eu
umask 077
BASE={shlex.quote(rdir)}
[ ! -e "$BASE/submitted" ]
[ ! -e /mnt/us/kc-sync/state/pending.json ]
LOCK=/tmp/kindlepilot-native-write.lock
mkdir "$LOCK" || exit 4
trap 'rmdir "$LOCK" 2>/dev/null || :' 0
[ "$(sha256sum "$BASE/request.json" | cut -d ' ' -f 1)" = '{hashlib.sha256(body).hexdigest()}' ]
sqlite3 -batch -bail -readonly /var/local/cc.db '.timeout 1500' ".backup '$BASE/cc-before.db'"
HELPER=/mnt/us/kc-sync/runtime/{route.native_collections['runtime_id']}/kc-backup-check
[ "$(sha256sum "$HELPER" | cut -d ' ' -f 1)" = '{route.native_collections['checker_build']['artifact_sha256']}' ]
"$HELPER" "$BASE/cc-before.db"
printf '%s\\n' submitted > "$BASE/submitted"
sync
AUTH=$(cat /tmp/session_token)
HTTP=$(curl --noproxy '*' --connect-timeout 3 --max-time 20 -sS -o "$BASE/response.json" -w '%{{http_code}}' -H "AuthToken: $AUTH" -H 'Content-Type: application/json' --data-binary @"$BASE/request.json" http://127.0.0.1:9101/change) || HTTP=000
unset AUTH
[ "$HTTP" = 200 ]
cat "$BASE/response.json"
'''
            response = remote("sh", script.encode(), timeout=45)
            write_new(row / "response.log", response)
            if not json.loads(response.decode().splitlines()[-1]).get("ok"):
                raise CompanionError("COLLECTION_RESPONSE", "native service did not confirm success")
            for attempt in range(2):
                time.sleep(1)
                after = catalog()
                verdict = verify_target(before, after, prepared)
                write_new(row / f"after-{attempt}.json", encode(after))
                write_new(row / f"verification-{attempt}.json", encode(verdict))
                if not verdict["verified"]:
                    raise CompanionError("COLLECTION_READBACK", "native state differs; stopped without replay")
            results.append(verdict)
            print(json.dumps({"done": index + 1, "total": len(targets), "operation": operation,
                              "name": target.get("name", target.get("current_name", target["uuid"]))}, ensure_ascii=False), flush=True)
        write_new(state / "results.json", encode(results))
        write_new(state / "catalog-final.json", encode(catalog()))
        return 0
    except (CompanionError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
