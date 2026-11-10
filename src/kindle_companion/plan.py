from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import CompanionError


def _safe_remote(path: str) -> str:
    if not path.startswith("/") or path == "/" or "//" in path:
        raise CompanionError("REMOTE_PATH", f"unsafe remote path: {path}")
    if any(part in {".", ".."} for part in path.split("/")):
        raise CompanionError("REMOTE_PATH", f"unsafe remote path: {path}")
    return path.rstrip("/")


def build_put_plan(local_root: Path, remote_root: str) -> tuple[str, ...]:
    """Build an auditable OpenMTP batch for a directory tree."""
    remote_root = _safe_remote(remote_root)
    if not local_root.is_dir():
        raise CompanionError("LOCAL_TREE", f"local directory not found: {local_root}")
    from .mtp import quote_batch_arg

    commands: list[str] = [f"mkpath {quote_batch_arg(remote_root)}"]
    seen_dirs = {remote_root}
    for path in sorted(local_root.rglob("*")):
        if path.is_symlink() or path.name in {".DS_Store", "__MACOSX"}:
            continue
        relative = path.relative_to(local_root).as_posix()
        target = f"{remote_root}/{relative}"
        if path.is_dir():
            commands.append(f"mkpath {quote_batch_arg(target)}")
            seen_dirs.add(target)
            continue
        parent = target.rsplit("/", 1)[0]
        if parent not in seen_dirs:
            commands.append(f"mkpath {quote_batch_arg(parent)}")
            seen_dirs.add(parent)
        commands.append(f"put {quote_batch_arg(path)} {quote_batch_arg(parent)}")
    commands.append("exit")
    return tuple(commands)


def build_delete_plan(paths: Iterable[str]) -> tuple[str, ...]:
    targets = tuple(paths)
    if not targets:
        raise CompanionError("DELETE_TARGETS", "no delete targets were supplied")
    from .mtp import quote_batch_arg

    normalized: list[str] = ["cd /"]
    for target in targets:
        safe_target = _safe_remote(target)
        if safe_target in {"/documents", "/koreader", "/libkh", "/"}:
            raise CompanionError("DELETE_SCOPE", f"refusing broad delete target: {target}")
        normalized.append(f"rm {quote_batch_arg(safe_target)}")
    normalized.append("exit")
    return tuple(normalized)
