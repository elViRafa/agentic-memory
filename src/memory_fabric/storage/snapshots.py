"""Point-in-time snapshots of local memory, restoring from them, and retention.

Every dream creates one snapshot (rollback baseline) plus one candidates/
working copy. Without retention both directories grow forever — one full copy
of the memory tree per dream call (P-11). ``prune_dream_artifacts`` keeps the
newest N of each and runs automatically at the end of an applied dream;
``list_snapshots`` makes rollback discoverable without touching ``.ai-memory/``
by hand (P-12).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from memory_fabric.contracts import WriteResult
from memory_fabric.locking import locked_file
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage._shared import (
    SECTION_PATTERN,
    _is_ignored_local_memory_path,
    _iter_markdown_files,
)
from memory_fabric.templates import now_iso

_KEEP_SNAPSHOTS_DEFAULT = 10
_KEEP_CANDIDATES_DEFAULT = 3


def _keep_from_env(env_name: str, default: int) -> int:
    try:
        value = int(os.environ.get(env_name, ""))
        if value >= 0:
            return value
    except (TypeError, ValueError):
        pass
    return default


def create_snapshot(cwd: str, name: str | None = None) -> str:
    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        raise FileNotFoundError(f"Local memory directory does not exist: {memory_dir}")

    snapshot_name = name or "memory-" + now_iso().replace(":", "").replace("+", "_").replace(
        "-", ""
    )
    snapshot_dir = memory_dir / "snapshots" / snapshot_name
    if name is None:
        # Timestamps have second resolution; two dreams inside the same second
        # (e.g. back-to-back post-commit hooks) must not crash on a collision.
        counter = 1
        while snapshot_dir.exists():
            snapshot_dir = memory_dir / "snapshots" / f"{snapshot_name}-{counter}"
            counter += 1
        snapshot_name = snapshot_dir.name
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for path in _iter_markdown_files(memory_dir):
        if _is_ignored_local_memory_path(memory_dir, path):
            continue
        relative = path.relative_to(memory_dir)
        target = snapshot_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return snapshot_name


def list_snapshots(cwd: str, memory_dir: Path | None = None) -> list[dict[str, Any]]:
    """Newest-first list of available snapshots with basic stats.

    The official way to discover a valid ``rollback --to`` target — agents and
    users are told never to browse ``.ai-memory/`` with raw file tools.
    """
    memory_dir = memory_dir if memory_dir is not None else local_memory_dir(cwd)
    snapshots_root = memory_dir / "snapshots"
    if not snapshots_root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in snapshots_root.iterdir():
        if not path.is_dir():
            continue
        try:
            files = [f for f in path.rglob("*") if f.is_file()]
            mtime = path.stat().st_mtime
        except OSError:
            continue
        entries.append(
            {
                "name": path.name,
                "created": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
                "files": len(files),
                "size_bytes": sum(f.stat().st_size for f in files),
                "_mtime": mtime,
            }
        )
    entries.sort(key=lambda e: (e["_mtime"], e["name"]), reverse=True)
    for entry in entries:
        entry.pop("_mtime", None)
    return entries


def prune_dream_artifacts(
    cwd: str,
    keep_snapshots: int | None = None,
    keep_candidates: int | None = None,
    protect: Iterable[str] = (),
    dry_run: bool = False,
    memory_dir: Path | None = None,
) -> dict[str, Any]:
    """Delete all but the newest N snapshot and candidate directories.

    Snapshots are rollback baselines (default keep 10, env
    ``MEMORY_FABRIC_KEEP_SNAPSHOTS``); candidates are dream working copies
    that were already applied or discarded (default keep 3, env
    ``MEMORY_FABRIC_KEEP_CANDIDATES``). Names in ``protect`` (the artifacts
    of the dream currently running) are never removed. Best-effort: unreadable
    or locked directories are skipped, not fatal.
    """
    memory_dir = memory_dir if memory_dir is not None else local_memory_dir(cwd)
    if keep_snapshots is None:
        keep_snapshots = _keep_from_env("MEMORY_FABRIC_KEEP_SNAPSHOTS", _KEEP_SNAPSHOTS_DEFAULT)
    if keep_candidates is None:
        keep_candidates = _keep_from_env("MEMORY_FABRIC_KEEP_CANDIDATES", _KEEP_CANDIDATES_DEFAULT)

    protected = {name for name in protect if name}
    removed: dict[str, list[str]] = {"snapshots": [], "candidates": []}
    for kind, keep in (("snapshots", keep_snapshots), ("candidates", keep_candidates)):
        root = memory_dir / kind
        if not root.is_dir():
            continue
        try:
            dirs = [p for p in root.iterdir() if p.is_dir()]
        except OSError:
            continue
        dirs.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        for path in dirs[keep:]:
            if path.name in protected:
                continue
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)
            removed[kind].append(path.name)

    return {
        "removed_snapshots": removed["snapshots"],
        "removed_candidates": removed["candidates"],
        "keep_snapshots": keep_snapshots,
        "keep_candidates": keep_candidates,
        "dry_run": dry_run,
    }


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
