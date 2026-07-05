"""Point-in-time snapshots of local memory, and restoring from them."""

from __future__ import annotations

import shutil

from memory_fabric.contracts import WriteResult
from memory_fabric.locking import locked_file
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage._shared import (
    SECTION_PATTERN,
    _is_ignored_local_memory_path,
    _iter_markdown_files,
)
from memory_fabric.templates import now_iso


def create_snapshot(cwd: str, name: str | None = None) -> str:
    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        raise FileNotFoundError(f"Local memory directory does not exist: {memory_dir}")

    snapshot_name = name or "memory-" + now_iso().replace(":", "").replace("+", "_").replace(
        "-", ""
    )
    snapshot_dir = memory_dir / "snapshots" / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for path in _iter_markdown_files(memory_dir):
        if _is_ignored_local_memory_path(memory_dir, path):
            continue
        relative = path.relative_to(memory_dir)
        target = snapshot_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return snapshot_name


def rollback(cwd: str, snapshot: str) -> WriteResult:
    if not SECTION_PATTERN.match(snapshot):
        raise ValueError("snapshot must contain only letters, numbers, underscores, and hyphens")

    memory_dir = local_memory_dir(cwd)
    snapshot_dir = memory_dir / "snapshots" / snapshot
    if not snapshot_dir.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot}")

    changed = False
    for source in _iter_markdown_files(snapshot_dir):
        relative = source.relative_to(snapshot_dir)
        target = memory_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(target):
            shutil.copy2(source, target)
        changed = True

    return {
        "changed": changed,
        "path": str(memory_dir),
        "redactions": 0,
        "warnings": [],
    }
