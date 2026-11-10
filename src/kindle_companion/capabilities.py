"""Read the package-owned KindlePilot capability catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .models import CompanionError


CATALOG_RELATIVE = Path("capabilities/kindle-pilot.json")


def load_capability_catalog(root: Path) -> dict[str, Any]:
    """Load and cross-check the one package-owned capability catalog.

    This is a read-only software discovery path. It does not inspect a Kindle,
    read workflow state, or infer device support from package presence.
    """
    package_path = root / "opl-package.json"
    catalog_path = root / CATALOG_RELATIVE
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompanionError(
            "CAPABILITY_CATALOG_UNAVAILABLE",
            "Read the Kindle Pilot capability catalog from the installed package or source checkout.",
        ) from exc

    if package.get("package_id") != "kindle-pilot" or package.get("version") != __version__:
        raise CompanionError("SOFTWARE_IDENTITY_MISMATCH", "The software manifest does not match the loaded Kindle Pilot runtime.")
    if catalog.get("schema") != "kindle-pilot-capability-catalog/v1" or catalog.get("package_id") != package["package_id"]:
        raise CompanionError("CAPABILITY_CATALOG_SCHEMA", "The capability catalog is not owned by this Kindle Pilot package.")
    ref = package.get("exports", {}).get("capability_catalog_ref")
    if ref != str(CATALOG_RELATIVE):
        raise CompanionError("CAPABILITY_CATALOG_REF", "The package does not point to its canonical capability catalog.")
    modules = catalog.get("modules")
    if not isinstance(modules, list) or not modules:
        raise CompanionError("CAPABILITY_CATALOG_EMPTY", "The Kindle Pilot capability catalog has no modules.")
    module_ids = [module.get("id") for module in modules]
    if any(not isinstance(module_id, str) or not module_id for module_id in module_ids) or len(module_ids) != len(set(module_ids)):
        raise CompanionError("CAPABILITY_CATALOG_IDENTITY", "Capability module ids must be distinct non-empty strings.")
    if catalog.get("capability_abi") != package.get("capability_abi"):
        raise CompanionError("CAPABILITY_ABI_MISMATCH", "Package and capability catalog ABI declarations differ.")
    if package.get("exports", {}).get("core_module_ids") != module_ids:
        raise CompanionError("CAPABILITY_EXPORT_MISMATCH", "Package exports do not match the capability catalog order.")
    return catalog


def capability_info(root: Path) -> dict[str, Any]:
    catalog = load_capability_catalog(root)
    package = json.loads((root / "opl-package.json").read_text(encoding="utf-8"))
    return {
        "ok": True,
        "schema": catalog["schema"],
        "package_id": package["package_id"],
        "display_name": package["display_name"],
        "version": package["version"],
        "capability_abi": catalog["capability_abi"],
        "modules": catalog["modules"],
        "device_status": "not_checked",
        "route_status": "manifest_bound",
        "account_status": "human_confirmation_required",
    }
