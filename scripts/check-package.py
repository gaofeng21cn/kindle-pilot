#!/usr/bin/env python3
"""Validate the Kindle Pilot OPL Framework v2 package metadata."""

import argparse
import json
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kindle_companion.capabilities import load_capability_catalog, load_package_manifest


MODULE_IDS = [
    "kindle-pilot.host.v1",
    "kindle.device.setup.v1",
    "kindle.mtp.transfer.v1",
    "kindle.reading.environment.v1",
    "kindle.account.reading.v1",
    "kindle.library.preservation.v1",
    "kindle.native.collections.v1",
    "kindle.wireless.maintenance.v1",
]


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    manifest = load_package_manifest(ROOT, unavailable_code="SOFTWARE_METADATA_UNAVAILABLE")
    load_capability_catalog(ROOT, package=manifest)
    identity = manifest["identity"]
    provides = manifest["provides"]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert identity["version"] == re.search(r'^version = "([^"]+)"$', pyproject, re.M)[1]
    python_range = re.search(r'^requires-python = "([^"]+)"$', pyproject, re.M)[1]
    assert {"name": "python", "version": python_range} in manifest["dependencies"]["runtimes"]
    assert provides["module_ids"] == MODULE_IDS
    assert (ROOT / identity["icon"]).is_file()
    skills = {skill["id"]: ROOT / skill["path"] / "SKILL.md" for skill in provides["skills"]}
    assert skills == {
        path.parent.name: path for path in (ROOT / "skills").glob("*/SKILL.md")
    }
    for cli in provides["cli_bin"]:
        cli_path = ROOT / cli["path"]
        assert cli_path.is_file() and os.access(cli_path, os.X_OK), f"CLI is not executable: {cli_path}"
    assert manifest["host_hints"]["codex"]["sync_enabled"] is False
    print(json.dumps({
        "ok": True,
        "package_id": identity["id"],
        "version": identity["version"],
        "module_count": len(MODULE_IDS),
    }))


if __name__ == "__main__":
    main()
