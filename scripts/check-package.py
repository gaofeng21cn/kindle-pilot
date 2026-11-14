#!/usr/bin/env python3
"""Validate software identity and its Framework-compatible content lock."""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-lock", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "opl-package.json"
    manifest = json.loads(manifest_path.read_text())
    plugin = json.loads((root / ".codex-plugin/plugin.json").read_text())
    authority = json.loads((root / "plugin.json").read_text())
    marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text())
    catalog_ref = manifest["exports"]["capability_catalog_ref"]
    catalog = json.loads((root / catalog_ref).read_text())
    python_version = re.search(r'^version = "([^"]+)"$', (root / "pyproject.toml").read_text(), re.M)[1]
    runtime_version = re.search(r'^__version__ = "([^"]+)"$', (root / "src/kindle_companion/__init__.py").read_text(), re.M)[1]
    assert manifest["package_id"] == plugin["name"] == marketplace["plugins"][0]["name"] == "kindle-pilot"
    assert manifest["version"] == plugin["version"] == python_version == runtime_version
    assert authority["name"] == plugin["name"] and authority["version"] == plugin["version"]
    assert authority["extensions"]["com.openai"]["interface"] == plugin["interface"]
    assert catalog["schema"] == "kindle-pilot-capability-catalog/v1"
    assert catalog["package_id"] == manifest["package_id"]
    assert catalog["capability_abi"] == manifest["capability_abi"]
    assert [module["id"] for module in catalog["modules"]] == manifest["exports"]["core_module_ids"]
    assert len({module["id"] for module in catalog["modules"]}) == len(catalog["modules"])
    assert manifest["display_name"] == plugin["interface"]["displayName"] == marketplace["interface"]["displayName"]
    assert plugin["skills"] == "./skills/"
    skill_ids = sorted(path.parent.name for path in (root / "skills").glob("*/SKILL.md"))
    assert sorted(manifest["exports"]["core_skill_ids"]) == skill_ids, "Core skills must use skills/<id>/SKILL.md"
    assert (root / manifest["exports"]["optional_skill_policy_ref"]).is_file()
    paths = sorted([
        ".agents/plugins/marketplace.json", ".codex-plugin/plugin.json", "plugin.json", "LICENSE", "README.md", "README.en.md", "THIRD_PARTY_NOTICES.md", "pyproject.toml",
        *[str(file.relative_to(root)) for directory in ["src", "skills", "scripts", "docs", "manifests", "assets", "capabilities"]
          for file in (root / directory).rglob("*") if file.is_file() and "__pycache__" not in file.parts and file.suffix not in [".pyc", ".pyo"]],
    ])
    digest = hashlib.sha256()
    for relative in paths:
        name = relative.encode()
        body = (root / relative).read_bytes()
        digest.update(struct.pack(">Q", len(name)) + name + struct.pack(">Q", len(body)) + body)
    expected = {"algorithm": "sha256", "canonicalization": "ordered_path_length_file_length_bytes", "paths": paths, "digest": "sha256:" + digest.hexdigest()}
    if args.write_lock:
        manifest["content_lock"] = expected
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert manifest["content_lock"] == expected, "Package content changed; run python3 scripts/check-package.py --write-lock"
    print(json.dumps({"ok": True, "package_id": manifest["package_id"], "version": manifest["version"], "payload_files": len(paths)}))


if __name__ == "__main__":
    main()
