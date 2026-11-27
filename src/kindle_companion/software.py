"""Software metadata, separate from device and task state."""

from __future__ import annotations

from pathlib import Path

from .capabilities import CATALOG_RELATIVE, load_capability_catalog, load_package_manifest


def software_info(root: Path) -> dict:
    manifest = load_package_manifest(root, unavailable_code="SOFTWARE_METADATA_UNAVAILABLE")
    identity = manifest["identity"]
    catalog = load_capability_catalog(root, package=manifest)
    return {
        "ok": True,
        "package_id": identity["id"],
        "display_name": identity["name"]["en-US"],
        "description": identity["summary"]["en-US"],
        "version": identity["version"],
        "manifest_version": identity["version"],
        # The checkout does not attest release admission or a Codex installation.
        "publication_channel_admission": None,
        "source_repo": identity["repository"],
        "management_owner": "opl_framework",
        "plugin_selector": None,
        "capability_abi": catalog["capability_abi"],
        "capability_catalog_ref": CATALOG_RELATIVE.as_posix(),
        "core_module_ids": manifest["provides"]["module_ids"],
        "device_status": "not_checked",
    }
