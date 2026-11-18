"""Shared write/read hygiene heuristics.

Field stores (search-sermons scale) showed agents stamping every file
``high``, summaries that are only a timestamp, completed handoffs that
never drop in rank, and empty steering that still occupies the always-on
budget. One module so write, doctor, eval, and the packer cannot drift.
"""

from __future__ import annotations

import re
from pathlib import Path

from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.storage._shared import _iter_markdown_files

_GENERIC_SUMMARIES = frozenset(
    {
        "",
        "contexto",
        "context",
        "summary",
        "tbd",
        "todo",
        "n/a",
        "na",
    }
)
_TIMESTAMP_SUMMARY_RE = re.compile(
    r"^\s*(?:\*{0,2}updated\*{0,2}\s*:?\s*)?"
    r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})",
    re.IGNORECASE,
)
_UPDATED_PREFIX_RE = re.compile(r"^\s*\*{0,2}updated\*{0,2}\s*:", re.IGNORECASE)
_RESOLVED_RE = re.compile(
    r"\b(resolvido|resolved|fixed|done|obsolete|superseded|do not re-run|"
    r"historical|executed|not the live queue)\b",
    re.IGNORECASE,
)
_POSTURE_STEM_RE = re.compile(r"^current-posture(?:-.*)?$", re.IGNORECASE)
_PLACEHOLDER_STEERING = (
    "record project terminology here",
    "record project terminology",
    "record framework rules here",
)
HIGH_PRIORITY_WARN_MIN_FILES = 8
HIGH_PRIORITY_WARN_FRACTION = 0.5
# 23% of a 128-file field store is about 29, so 24 warns there.
# Stores under HIGH_PRIORITY_WARN_MIN_FILES stay quiet.
HIGH_PRIORITY_WARN_ABSOLUTE = 24
STEERING_PLACEHOLDER_CHARS = 24
MAP_QUERY_CAP_TOKENS = 120


def is_timestamp_summary(summary: str) -> bool:
    """True for ``**Updated:** 2026-09-04 ~01:20 ET`` and date-only lines."""
    text = (summary or "").strip()
    if not text:
        return False
    if _TIMESTAMP_SUMMARY_RE.match(text):
        return True
    return bool(_UPDATED_PREFIX_RE.match(text) and re.search(r"\d{4}", text))


def is_weak_summary(summary: str, title: str = "", heading: str = "") -> bool:
    """Summaries that cannot drive maps-first retrieval."""
    s = (summary or "").strip()
    if not s or s.lower() in _GENERIC_SUMMARIES:
        return True
    if len(s) < 16:
        return True
    if is_timestamp_summary(s):
        return True
    lowered = s.lower().rstrip(".")
    title_l = (title or "").strip().lower().rstrip(".")
    if title_l and lowered in {title_l, f"memory: {title_l}"}:
        return True
    heading_l = heading.lstrip("#").strip().lower().rstrip(".")
    return bool(heading_l and lowered == heading_l)


def looks_complete_path(store_path: str) -> bool:
    """Last segment ends with ``-complete`` (finished wave, not live handoff)."""
    last = store_path.replace("\\", "/").strip("/").split("/")[-1]
    stem = last[:-3] if last.endswith(".md") else last
    return stem.endswith("-complete")


def looks_resolved_text(text: str) -> bool:
    return bool(text and _RESOLVED_RE.search(text))


def is_posture_path(store_path: str, *, role: str | None = None) -> bool:
    """True for ``current-posture`` / ``current-posture-*`` or ``role: posture``."""
    if (role or "").strip().lower() == "posture":
        return True
    return bool(_POSTURE_STEM_RE.match(_path_stem(store_path)))


def is_next_session_path(store_path: str) -> bool:
    """True when the last path segment contains ``next-session``."""
    return "next-session" in _path_stem(store_path).lower()


def is_live_handoff_path(store_path: str, *, role: str | None = None) -> bool:
    if is_posture_path(store_path, role=role):
        return True
    last = _path_stem(store_path)
    return last in {"next-session-handoff", "current"}


def sibling_high_handoffs(store_root: Path, store_path: str) -> list[str]:
    """Other ``*-handoff`` files in the same first segment that are still high."""
    parts = [p for p in store_path.replace("\\", "/").strip("/").split("/") if p]
    if len(parts) < 2:
        return []
    prefix = parts[0]
    folder = store_root / prefix
    if not folder.is_dir():
        return []
    current = "/".join(parts)
    found: list[str] = []
    for path in folder.rglob("*.md"):
        if "handoff" not in path.stem.lower():
            continue
        relative = path.relative_to(store_root).as_posix()
        sp = relative[:-3] if relative.endswith(".md") else relative
        if sp == current:
            continue
        try:
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        if str(metadata.get("priority") or "").lower() == "high":
            found.append(sp)
    return found


def demote_sibling_next_session_files(
    store_root: Path,
    posture_store_path: str,
    *,
    keep_paths: list[str] | None = None,
) -> list[str]:
    """Demote sibling ``*next-session*`` files under the same first segment.

    Sets ``priority: low`` and ``superseded_by`` to *posture_store_path*.
    Does not bump ``last_updated`` (recency must stay meaningful).
    Paths listed in *keep_paths* (still named by the live posture slice) stay open.
    Returns the demoted store paths.
    """
    parts = [p for p in posture_store_path.replace("\\", "/").strip("/").split("/") if p]
    if len(parts) < 2:
        return []
    prefix = parts[0]
    folder = store_root / prefix
    if not folder.is_dir():
        return []
    current = "/".join(parts)
    keep = {
        p.replace("\\", "/").strip("/")
        for p in (keep_paths or [])
        if str(p).strip()
    }
    demoted: list[str] = []
    for path in folder.rglob("*.md"):
        relative = path.relative_to(store_root).as_posix()
        sp = relative[:-3] if relative.endswith(".md") else relative
        if sp == current or not is_next_session_path(sp):
            continue
        if sp in keep:
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        changed = False
        if str(metadata.get("priority") or "").lower() != "low":
            metadata["priority"] = "low"
            changed = True
        if str(metadata.get("superseded_by") or "").strip() != current:
            from memory_fabric.storage.close import apply_close_metadata

            metadata = apply_close_metadata(
                metadata, successor=current, close_kind="update"
            )
            changed = True
        if not changed:
            continue
        try:
            path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
        except OSError:
            continue
        demoted.append(sp)
    return demoted


def store_priority_counts(store_root: Path) -> tuple[int, int]:
    """Return ``(high_count, total)`` for granular store files (not index.md)."""
    if not store_root.is_dir():
        return 0, 0
    high = 0
    total = 0
    for path in _iter_markdown_files(store_root):
        if path.name == "index.md":
            continue
        total += 1
        try:
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        if str(metadata.get("priority") or "").lower() == "high":
            high += 1
    return high, total


def high_priority_inflation(high: int, total: int) -> bool:
    if total < HIGH_PRIORITY_WARN_MIN_FILES:
        return False
    if high >= HIGH_PRIORITY_WARN_ABSOLUTE:
        return True
    return high / total >= HIGH_PRIORITY_WARN_FRACTION


def steering_body_is_placeholder(body: str) -> bool:
    """True for empty or leftover init stubs that should not eat the budget."""
    text = re.sub(r"^#.*$", "", body or "", flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < STEERING_PLACEHOLDER_CHARS:
        return True
    lowered = text.lower()
    return any(phrase in lowered for phrase in _PLACEHOLDER_STEERING)


def _path_stem(store_path: str) -> str:
    last = store_path.replace("\\", "/").strip("/").split("/")[-1]
    return last[:-3] if last.endswith(".md") else last
