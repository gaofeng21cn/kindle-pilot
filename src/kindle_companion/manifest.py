from __future__ import annotations

import json
from pathlib import Path

from .models import CompatibilityManifest, CompanionError


def load_manifest(path: Path) -> CompatibilityManifest:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompanionError("MANIFEST_READ", f"cannot read manifest {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CompanionError("MANIFEST_JSON", f"invalid manifest JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompanionError("MANIFEST_SHAPE", "manifest root must be an object")
    return CompatibilityManifest.from_dict(data)
