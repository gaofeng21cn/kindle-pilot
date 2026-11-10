#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kindle_companion.compat import resolve_asset
from kindle_companion.manifest import load_manifest
from kindle_companion.models import CompanionError
from kindle_companion.verify import sha256_file
from kindle_companion.collections import write_new


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the KC read-only checker with the manifest's SQLite version")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "manifests/compatibility.json")
    parser.add_argument("--route", required=True)
    parser.add_argument("--sqlite-archive", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--host-cc", default="cc")
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        route = next((r for r in manifest.routes if r.id == args.route), None)
        if route is None or not route.native_collections:
            raise CompanionError("COLLECTION_UNSUPPORTED", "route has no collection checker build")
        build = route.native_collections["checker_build"]
        for path, name in ((args.sqlite_archive, build["sqlite_asset"]), (args.source, build["source_asset"])):
            if sha256_file(path) != resolve_asset(route, name).sha256:
                raise CompanionError("BUILD_SOURCE_HASH", "source SHA-256 mismatch: " + name)
        args.output.mkdir(parents=True, exist_ok=True)
        root = args.output.resolve()
        with zipfile.ZipFile(args.sqlite_archive) as source:
            for name in ("sqlite3.c", "sqlite3.h"):
                write_new(root / name, source.read(build["sqlite_prefix"] + "/" + name))
        write_new(root / "kc_backup_check.c", args.source.read_bytes())
        common = ["-Os", "-DSQLITE_THREADSAFE=0", "-DSQLITE_OMIT_LOAD_EXTENSION=1", "-DSQLITE_DEFAULT_MEMSTATUS=0",
                  "-I", str(root), str(root / "kc_backup_check.c"), str(root / "sqlite3.c"), "-lm"]
        subprocess.run([args.host_cc, *common, "-o", str(root / "kc-backup-check-host")], check=True)
        subprocess.run([str(root / "kc-backup-check-host"), "--self-test"], check=True)
        actual_zig = subprocess.check_output([args.zig, "version"], text=True).strip()
        if actual_zig != build["zig"]:
            raise CompanionError("BUILD_TOOL_VERSION", "Zig version differs from the qualified build: " + actual_zig)
        subprocess.run([args.zig, "cc", "-target", build["target"], "-mcpu=" + build["cpu"], "-static", "-fno-sanitize=all",
                        *common, "-Wl,-s", "-o", str(root / "kc-backup-check")], check=True)
        actual = sha256_file(root / "kc-backup-check")
        receipt = {"route": route.id, "sqlite": build["sqlite_version"], "zig": actual_zig,
                   "source_sha256": sha256_file(args.source), "sqlite_archive_sha256": sha256_file(args.sqlite_archive),
                   "artifact_sha256": actual, "manifest_match": actual == build["artifact_sha256"]}
        (root / "build.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        if not receipt["manifest_match"]:
            raise CompanionError("BUILD_ARTIFACT_HASH", "rebuilt helper differs; retain the receipt for review before transfer")
        print(json.dumps(receipt, indent=2))
        return 0
    except (CompanionError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
