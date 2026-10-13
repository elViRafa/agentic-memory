"""Cursor (and similar) hook handlers that deny raw file-tool writes into ``.ai-memory/``.

Fail open: any parse/IO error allows the call. Never wedge a session over
memory bookkeeping. Steering files a human may hand-edit are excluded.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from memory_fabric.paths import local_memory_dir, project_root
from memory_fabric.storage._shared import STEERING_SECTIONS, _is_steering_file

_DENY_MESSAGE = (
    "Do not read or write `.ai-memory/` with raw file tools. "
    "Use `write_memory_store_tool` to record facts, `read_memory_store_tool` / "
    "`keyword_search_tool` / `context_for_task_tool` to retrieve them, and "
    "`write_local_memory_tool` only for `role: steering` directives."
)


def _extract_paths(payload: dict[str, Any]) -> list[str]:
    """Best-effort path extraction from Cursor hook stdin JSON."""
    found: list[str] = []
    for key in ("file_path", "filePath", "path"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            found.append(value)
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("arguments")
    if isinstance(tool_input, dict):
        for key in ("path", "file_path", "filePath", "target_file", "targetFile"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                found.append(value)
        files = tool_input.get("files")
        if isinstance(files, list):
            for item in files:
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, dict):
                    for key in ("path", "file_path"):
                        value = item.get(key)
                        if isinstance(value, str) and value:
                            found.append(value)
    return found


def _is_steering_allowlisted(memory_dir: Path, target: Path) -> bool:
    try:
        rel = target.resolve().relative_to(memory_dir.resolve())
    except ValueError:
        return False
    if len(rel.parts) != 1 or not rel.parts[0].endswith(".md"):
        return False
    stem = Path(rel.parts[0]).stem
    if stem in STEERING_SECTIONS:
        return True
    return _is_steering_file(target)


def path_is_protected_memory(cwd: str, raw_path: str) -> bool:
    """True when ``raw_path`` is inside ``.ai-memory/`` and is not a steering file."""
    root = project_root(cwd)
    memory_dir = local_memory_dir(cwd)
    target = Path(raw_path)
    if not target.is_absolute():
        target = root / target
    try:
        target.resolve().relative_to(memory_dir.resolve())
    except ValueError:
        # Also catch paths that mention .ai-memory even if the project root differs.
        normalized = raw_path.replace("\\", "/")
        if "/.ai-memory/" not in f"/{normalized}":
            return False
        # Path is under some .ai-memory; treat store/candidates/private as protected.
        return "/memory-store/" in normalized or any(
            part in normalized for part in ("/candidates/", "/private/", "/snapshots/", "/evals/")
        )
    return not _is_steering_allowlisted(memory_dir, target)


def evaluate_hook_payload(cwd: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a Cursor-shaped hook decision. Fail-open on empty/unknown payloads."""
    paths = _extract_paths(payload)
    if not paths:
        return {"permission": "allow"}
    for raw in paths:
        try:
            if path_is_protected_memory(cwd, raw):
                return {
                    "permission": "deny",
                    "user_message": _DENY_MESSAGE,
                    "agent_message": _DENY_MESSAGE,
                }
        except Exception:  # noqa: BLE001 - fail open
            return {"permission": "allow"}
    return {"permission": "allow"}


def run_hook_guard(cwd: str, stdin_text: str | None = None) -> tuple[int, str]:
    """Read hook JSON from stdin (or ``stdin_text``), print a decision, return exit code.

    Exit 2 + deny JSON blocks the tool (Cursor contract). Exit 0 allows.
    Any parse error exits 0 (fail open).
    """
    raw = stdin_text if stdin_text is not None else sys.stdin.read()
    if not raw.strip():
        return 0, json.dumps({"permission": "allow"})
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0, json.dumps({"permission": "allow"})
    if not isinstance(payload, dict):
        return 0, json.dumps({"permission": "allow"})
    try:
        decision = evaluate_hook_payload(cwd, payload)
    except Exception:  # noqa: BLE001 - fail open
        return 0, json.dumps({"permission": "allow"})
    if decision.get("permission") == "deny":
        return 2, json.dumps(decision, ensure_ascii=False)
    return 0, json.dumps(decision, ensure_ascii=False)
