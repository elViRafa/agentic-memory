"""Close events and entrenchment for obsolete-memory handling.

A claim stays current until a later claim closes it. ``last_updated`` is an
edit clock, not truth. Standing roles (steering, decisions, schemas,
architecture) are not age-stamped stale; a weaker role cannot close a
stronger one.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from memory_fabric.diary.roles import classify_role
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.storage._shared import _iter_markdown_files
from memory_fabric.templates import now_iso

# Higher number = more entrenched. A writer may close only a target whose
# rank is <= its own rank.
ENTRENCHMENT_RANK: dict[str, int] = {
    "steering": 100,
    "tier0": 100,
    "decisions": 90,
    "schema": 90,
    "architecture": 70,
    "posture": 50,
    "rule": 40,
    "debt": 30,
    "failure": 20,
    "episodic": 10,
    "episodic_commit": 5,
    "map": 0,
    "other": 25,
}

# Age-based ``review_status: stale`` must never hit these roles.
STANDING_ROLES = frozenset({"steering", "tier0", "decisions", "schema", "architecture"})

_SUPERSEDES_LINE_RE = re.compile(r"(?im)^\s*supersedes\s*:\s*(.+?)\s*$")
_STORE_PATH_TOKEN_RE = re.compile(
    r"\b([a-z][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)+)\b",
    re.IGNORECASE,
)
_PROSE_SUPERSEDED_RE = re.compile(
    r"(?i)\b(?:superseded(?:\s+by)?|supersedes|replaced\s+by|"
    r"substitu[ií]do\s+por|n[aã]o\s+usar\s+mais)\b"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_DATE_HEADING_RE = re.compile(
    r"(?i)(?:^|\b)((?:20\d{2})[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01]))"
)
_NEXT_STEP_RE = re.compile(
    r"(?im)^\s*(?:[-*+]|\d+[.)])?\s*(?:next(?:\s+session)?|pr[oó]ximo)\s*:?\s*(.+)$"
)


def role_for_store_path(store_path: str, *, role: str | None = None) -> str:
    """Entrenchment role for a store path (and optional frontmatter role)."""
    explicit = (role or "").strip().lower()
    if explicit == "posture":
        return "posture"
    if explicit in ENTRENCHMENT_RANK:
        return explicit
    from memory_fabric.storage.hygiene import is_posture_path

    if is_posture_path(store_path, role=role):
        return "posture"
    return classify_role(f"store/{store_path.replace(chr(92), '/').strip('/')}")


def role_for_section_key(key: str, *, role: str | None = None) -> str:
    text = (key or "").replace("\\", "/").strip("/")
    if text.startswith("local/"):
        return classify_role(text)
    if text.startswith("store/"):
        return role_for_store_path(text[len("store/") :], role=role)
    return classify_role(text)


def entrenchment_rank(role: str | None) -> int:
    return ENTRENCHMENT_RANK.get((role or "other").strip().lower(), ENTRENCHMENT_RANK["other"])


def is_standing_role(role: str | None) -> bool:
    return (role or "").strip().lower() in STANDING_ROLES


def is_history_role(role: str | None) -> bool:
    return (role or "").strip().lower() in {"episodic", "episodic_commit", "failure"}


def can_close(writer_role: str | None, target_role: str | None) -> bool:
    """True when the writer is at least as entrenched as the target."""
    return entrenchment_rank(writer_role) >= entrenchment_rank(target_role)


def _parse_iso(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def can_close_by_valid_time(
    writer_meta: dict[str, Any] | None,
    target_meta: dict[str, Any] | None,
) -> bool:
    """Refuse when a backfilled earlier ``valid_from`` would close a later claim.

    A fact written later with an earlier ``valid_from`` (backfill) must not
    close a decision whose valid interval starts after that backfill.
    """
    writer_vf = _parse_iso(str((writer_meta or {}).get("valid_from") or "") or None)
    if writer_vf is None:
        writer_vf = _parse_iso(str((writer_meta or {}).get("last_updated") or "") or None)
    target_vf = _parse_iso(str((target_meta or {}).get("valid_from") or "") or None)
    if target_vf is None:
        target_vf = _parse_iso(str((target_meta or {}).get("last_updated") or "") or None)
    if writer_vf is None or target_vf is None:
        return True
    return writer_vf >= target_vf


def parse_supersedes_paths(
    content: str,
    *,
    explicit: list[str] | None = None,
) -> list[str]:
    """Collect store paths named by ``supersedes:`` metadata or a leading line."""
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        path = raw.strip().strip("`\"'").rstrip(".,;")
        path = path.replace("\\", "/").strip("/")
        if path.endswith(".md"):
            path = path[:-3]
        if not path or "/" not in path:
            return
        if path in seen:
            return
        seen.add(path)
        found.append(path)

    for item in explicit or []:
        add(str(item))

    text = content or ""
    # Frontmatter may already have been stripped by the caller; still accept a
    # body that starts with ``supersedes: path``.
    for match in _SUPERSEDES_LINE_RE.finditer(text):
        for token in re.split(r"[,;]", match.group(1)):
            add(token)
    return found


def extract_named_store_paths(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _STORE_PATH_TOKEN_RE.finditer(text or ""):
        path = match.group(1).replace("\\", "/").strip("/")
        if path.endswith(".md"):
            path = path[:-3]
        if path in seen or path.count("/") < 1:
            continue
        seen.add(path)
        found.append(path)
    return found


def body_claims_superseded_without_field(metadata: dict[str, Any], body: str) -> bool:
    if str(metadata.get("superseded_by") or "").strip():
        return False
    head = (body or "")[:1200]
    return bool(_PROSE_SUPERSEDED_RE.search(head))


def apply_close_metadata(
    metadata: dict[str, Any],
    *,
    successor: str,
    close_kind: str,
) -> dict[str, Any]:
    """Stamp close fields without bumping ``last_updated``."""
    updated = dict(metadata)
    updated["superseded_by"] = successor
    updated["closed_at"] = now_iso()
    kind = (close_kind or "update").strip().lower()
    if kind not in {"update", "revision"}:
        kind = "update"
    updated["close_kind"] = kind
    return updated


def close_store_file(
    store_root: Path,
    target_store_path: str,
    *,
    successor: str,
    close_kind: str = "update",
) -> bool:
    """Write ``superseded_by`` on an existing store file. Returns True on write."""
    path = store_root / f"{target_store_path}.md"
    if not path.is_file():
        # Nested path segments.
        parts = target_store_path.replace("\\", "/").strip("/").split("/")
        path = store_root.joinpath(*parts[:-1], f"{parts[-1]}.md") if parts else path
    if not path.is_file():
        return False
    try:
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FrontmatterError):
        return False
    if str(metadata.get("superseded_by") or "").strip() == successor:
        return False
    metadata = apply_close_metadata(metadata, successor=successor, close_kind=close_kind)
    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
    return True


def clear_age_only_stale_on_standing(
    memory_root: Path,
) -> list[str]:
    """Clear ``review_status: stale`` on standing roles with no successor.

    One-time / dream-pass cleanup so Phaser-4 decisions and framework-rules
    re-enter packs after age-as-truth is retired for those roles.
    """
    cleared: list[str] = []
    for path in _iter_markdown_files(memory_root):
        if path.name == "index.md":
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        if str(metadata.get("review_status") or "").strip().lower() != "stale":
            continue
        if str(metadata.get("superseded_by") or "").strip():
            continue
        try:
            rel = path.relative_to(memory_root).as_posix()
        except ValueError:
            continue
        if rel.startswith("memory-store/"):
            store_path = rel[len("memory-store/") :]
            if store_path.endswith(".md"):
                store_path = store_path[:-3]
            role = role_for_store_path(store_path, role=str(metadata.get("role") or "") or None)
            key = f"store/{store_path}"
        else:
            role = role_for_section_key(
                f"local/{path.stem}", role=str(metadata.get("role") or "") or None
            )
            key = f"local/{path.stem}"
        if not is_standing_role(role):
            continue
        metadata.pop("review_status", None)
        path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
        cleared.append(key)
    return cleared


def is_closed_metadata(metadata: dict[str, Any] | None) -> bool:
    meta = metadata or {}
    if str(meta.get("superseded_by") or "").strip():
        return True
    if str(meta.get("closed_at") or "").strip():
        return True
    status = str(meta.get("review_status") or "").strip().lower()
    return status in {"stale", "broken-evidence"}


def closed_by_line(metadata: dict[str, Any] | None) -> str:
    meta = metadata or {}
    successor = str(meta.get("superseded_by") or "").strip()
    if successor:
        return f"Closed by `{successor}`."
    status = str(meta.get("review_status") or "").strip().lower()
    if status:
        return f"Closed ({status})."
    if str(meta.get("closed_at") or "").strip():
        return "Closed."
    return ""


def split_posture_sections(body: str) -> list[tuple[str, str, str]]:
    """Return ``(sort_key, heading, section_body)`` newest-last for dated headings.

    Sections without a date keep insertion order with sort_key ``0000-00-00``.
    """
    text = body or ""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("0000-00-00", "", text.strip())]

    sections: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(2).strip()
        chunk = text[start:end].strip()
        date_match = _DATE_HEADING_RE.search(heading)
        sort_key = "0000-00-00"
        if date_match:
            raw = date_match.group(1).replace("/", "-")
            parts = raw.split("-")
            if len(parts) == 3:
                sort_key = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        sections.append((sort_key, heading, chunk))
    return sections


def live_posture_body(body: str) -> tuple[str, list[str]]:
    """Keep the latest dated section plus undated preamble / standing constraints.

    Returns ``(packed_body, named_next_session_paths)``.
    """
    sections = split_posture_sections(body)
    if len(sections) <= 1:
        named = extract_named_store_paths(body)
        return (body or "").strip() + ("\n" if body else ""), [
            p for p in named if "next-session" in p.lower()
        ]

    dated = [s for s in sections if s[0] != "0000-00-00"]
    undated = [s for s in sections if s[0] == "0000-00-00"]
    if not dated:
        named = extract_named_store_paths(body)
        return (body or "").strip() + "\n", [p for p in named if "next-session" in p.lower()]

    latest_key = max(s[0] for s in dated)
    latest = [s for s in dated if s[0] == latest_key][-1]
    earlier_dated = [s for s in dated if s[0] < latest_key]

    parts: list[str] = []
    for _key, heading, chunk in undated:
        # Drop undated next-step lines that an earlier dated section already
        # closed; keep standing "Do not" / constraint prose.
        if _looks_like_next_step_block(chunk) and earlier_dated:
            continue
        block = f"## {heading}\n\n{chunk}".strip() if heading else chunk
        if block.strip():
            parts.append(block.strip())

    latest_block = f"## {latest[1]}\n\n{latest[2]}".strip()
    parts.append(latest_block)

    packed = "\n\n".join(parts).strip() + "\n"
    named = [p for p in extract_named_store_paths(latest[2]) if "next-session" in p.lower()]
    # Also keep bare ``Next: ...`` targets that are store paths.
    for match in _NEXT_STEP_RE.finditer(latest[2]):
        for path in extract_named_store_paths(match.group(1)):
            if "next-session" in path.lower() and path not in named:
                named.append(path)
    return packed, named


def _looks_like_next_step_block(chunk: str) -> bool:
    text = (chunk or "").strip()
    if not text:
        return False
    if _NEXT_STEP_RE.search(text):
        return True
    lowered = text.casefold()
    return lowered.startswith("next:") or lowered.startswith("next session")


def ensure_valid_from(metadata: dict[str, Any]) -> dict[str, Any]:
    """Set ``valid_from`` once from ``last_updated`` when missing."""
    if str(metadata.get("valid_from") or "").strip():
        return metadata
    lu = str(metadata.get("last_updated") or "").strip()
    if lu:
        metadata = dict(metadata)
        metadata["valid_from"] = lu
    return metadata
