"""Read the package-owned KindlePilot capability catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .models import CompanionError


CATALOG_RELATIVE = Path("capabilities/kindle-pilot.json")
PACKAGE_ID = "kindle-pilot"
PACKAGE_SCHEMA = "opl.package.v2"


def load_package_manifest(root: Path, *, unavailable_code: str) -> dict[str, Any]:
    try:
        package = json.loads((root / "opl-package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompanionError(
            unavailable_code,
            "Read the Kindle Pilot manifest from the installed package or source checkout.",
        ) from exc
    identity = package.get("identity") if isinstance(package, dict) else None
    if (
        not isinstance(identity, dict)
        or package.get("schema_version") != PACKAGE_SCHEMA
        or identity.get("id") != PACKAGE_ID
        or identity.get("version") != __version__
    ):
        raise CompanionError("SOFTWARE_IDENTITY_MISMATCH", "The software manifest does not match the loaded Kindle Pilot runtime.")
    return package


def load_capability_catalog(root: Path, *, package: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load and cross-check the one package-owned capability catalog.

    This is a read-only software discovery path. It does not inspect a Kindle,
    read workflow state, or infer device support from package presence.
    """
    if package is None:
        package = load_package_manifest(root, unavailable_code="CAPABILITY_CATALOG_UNAVAILABLE")
    catalog_path = root / CATALOG_RELATIVE
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompanionError(
            "CAPABILITY_CATALOG_UNAVAILABLE",
            "Read the Kindle Pilot capability catalog from the installed package or source checkout.",
        ) from exc

    if catalog.get("schema") != "kindle-pilot-capability-catalog/v1" or catalog.get("package_id") != package["identity"]["id"]:
        raise CompanionError("CAPABILITY_CATALOG_SCHEMA", "The capability catalog is not owned by this Kindle Pilot package.")
    modules = catalog.get("modules")
    if not isinstance(modules, list) or not modules:
        raise CompanionError("CAPABILITY_CATALOG_EMPTY", "The Kindle Pilot capability catalog has no modules.")
    module_ids = [module.get("id") for module in modules]
    if any(not isinstance(module_id, str) or not module_id for module_id in module_ids) or len(module_ids) != len(set(module_ids)):
        raise CompanionError("CAPABILITY_CATALOG_IDENTITY", "Capability module ids must be distinct non-empty strings.")
    if package.get("provides", {}).get("module_ids") != module_ids:
        raise CompanionError("CAPABILITY_EXPORT_MISMATCH", "Package module ids do not match the capability catalog order.")
    abi = catalog.get("capability_abi")
    if not isinstance(abi, dict) or abi.get("id") != module_ids[0] or modules[0].get("kind") != "aggregate":
        raise CompanionError("CAPABILITY_ABI_MISMATCH", "The catalog ABI must identify its aggregate host module.")
    return catalog


def capability_info(root: Path) -> dict[str, Any]:
    package = load_package_manifest(root, unavailable_code="CAPABILITY_CATALOG_UNAVAILABLE")
    catalog = load_capability_catalog(root, package=package)
    identity = package["identity"]
    return {
        "ok": True,
        "schema": catalog["schema"],
        "package_id": identity["id"],
        "display_name": identity["name"]["en-US"],
        "version": identity["version"],
        "capability_abi": catalog["capability_abi"],
        "modules": catalog["modules"],
        "device_status": "not_checked",
        "route_status": "manifest_bound",
        "account_status": "human_confirmation_required",
    }
