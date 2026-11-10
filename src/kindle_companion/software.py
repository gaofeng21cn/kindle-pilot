"""Software metadata, separate from device and task state."""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .models import CompanionError


def software_info(root: Path) -> dict:
    try:
        manifest = json.loads((root / "opl-package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompanionError("SOFTWARE_METADATA_UNAVAILABLE", "Read software information from the Kindle Pilot plugin or source checkout.") from exc
    if manifest.get("package_id") != "kindle-pilot" or manifest.get("version") != __version__:
        raise CompanionError("SOFTWARE_IDENTITY_MISMATCH", "The software manifest does not match the loaded Kindle Pilot runtime.")
    carrier = manifest["codex_surface"]["configured_codex_plugin_carrier"]
    return {
        "ok": True,
        "package_id": manifest["package_id"],
        "display_name": manifest["display_name"],
        "description": manifest["description"],
        "version": __version__,
        "manifest_version": manifest["version"],
        "publication_channel_admission": manifest["publication_channel_admission"],
        "source_repo": manifest["source_repo"],
        "management_owner": carrier["kind"],
        "plugin_selector": carrier["plugin_selector"],
        "capability_abi": manifest["capability_abi"],
        "capability_catalog_ref": manifest["exports"]["capability_catalog_ref"],
        "core_module_ids": manifest["exports"]["core_module_ids"],
        "device_status": "not_checked",
    }
