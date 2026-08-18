"""Fail-open JSONL writer for the local field diary.

``record`` is a no-op unless a human approved the diary. A write error never
propagates — the product path (MCP/CLI) must keep working.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memory_fabric.diary.consent import diary_dir, is_approved
from memory_fabric.locking import locked_file
from memory_fabric.templates import now_iso

_MAX_DAY_BYTES = 5 * 1024 * 1024


def record(event: dict[str, Any], *, cwd: str | None = None) -> None:
    """Append one JSON object as a line. Silent no-op when not approved."""
    if not is_approved(cwd):
        return
    try:
        _append(event)
    except OSError:
        return


def _append(event: dict[str, Any]) -> None:
    payload = dict(event)
    payload.setdefault("ts", now_iso())
    payload.setdefault("schema_version", 1)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    root = diary_dir()
    root.mkdir(parents=True, exist_ok=True)
    today = (payload.get("ts") or now_iso())[:10]
    path = _rotate_if_needed(root / f"events-{today}.jsonl")
    with locked_file(path), path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _rotate_if_needed(path: Path) -> Path:
    """If today's file is over the cap, write to events-DATE.N.jsonl instead."""
    try:
        size = path.stat().st_size
    except OSError:
        return path
    if size < _MAX_DAY_BYTES:
        return path
    n = 1
    while True:
        rotated = path.with_name(f"{path.stem}.{n}{path.suffix}")
        try:
            rotated_size = rotated.stat().st_size
        except OSError:
            return rotated
        if rotated_size < _MAX_DAY_BYTES:
            return rotated
        n += 1
