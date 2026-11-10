from __future__ import annotations

import hashlib
from pathlib import Path

from .models import CompanionError


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CompanionError("ASSET_READ", f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def verify_asset(path: Path, expected: str) -> dict[str, str | bool]:
    actual = sha256_file(path)
    normalized = expected.lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise CompanionError("ASSET_HASH_FORMAT", f"invalid expected SHA-256: {expected}")
    return {
        "path": str(path),
        "expected_sha256": normalized,
        "actual_sha256": actual,
        "ok": actual == normalized,
    }
