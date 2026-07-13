"""Git merge driver for Memory Fabric files: memory that merges with the code
it describes instead of producing textual conflicts on every timestamp both
branches happened to touch.

Registered via ``ai-memory init --merge-driver`` (writes ``.gitattributes`` +
a *local* git config entry — merge driver commands are per-clone by git's own
design, so this must be re-run after every fresh clone; `.gitattributes`
itself is committed and shared, only the driver command registration is
local). Git then invokes, on every conflicting merge of a matched path::

    <driver-command> <ancestor> <ours> <theirs>

and expects the merged result written into ``<ours>``, exiting 0 for a clean
merge or non-zero (with the file left holding whatever content, typically
conflict markers) otherwise.

Merge strategy, cheapest-safe-outcome first:

1. Identical sides, or only one side changed the body -> take that side.
2. Both sides purely *appended* to a shared prefix (the overwhelmingly common
   case for memory files: two branches each add new facts/journal entries)
   -> concatenate, deduplicating exact-duplicate lines the same way
   ``write_memory_store``'s append mode already does.
3. Anything else (both sides edited existing lines, or a body was rewritten
   rather than extended) -> defer to ``git merge-file`` for git's own
   standard textual 3-way merge with conflict markers. This never makes
   things worse than not having the driver installed at all.

Frontmatter fields we know how to reconcile safely regardless of path:
``tags`` (union), ``priority`` (the more urgent value wins), ``last_updated``
(the later timestamp wins). A generated map (``generated: true``) that falls
through to case 3 and ends up with conflict markers in its frontmatter is
self-healing: the next Dreaming run fails to parse it, treats it as having no
prior generation state, and fully regenerates it from the store.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.paths import project_root
from memory_fabric.storage._shared import CURRENT_SCHEMA_VERSION, PRIORITY_ORDER, _jaccard_similar

_IDENTITY_FIELDS = ("section", "store_path")


def _dedupe_append(existing_new: str, incoming_new: str) -> str:
    """Concatenate two branches' additions to a shared prefix, dropping lines
    from the incoming side that are exact or near-duplicates of lines already
    kept from the existing side (same filter `write_local_memory` applies)."""
    existing_clean = existing_new.strip("\n")
    if not incoming_new.strip():
        return existing_clean + ("\n" if existing_clean else "")

    existing_lines_lower = {
        line.strip().lower() for line in existing_clean.splitlines() if line.strip()
    }
    existing_normalized = {re.sub(r"^[-*+]\s+", "", line).strip() for line in existing_lines_lower}

    kept: list[str] = []
    for line in incoming_new.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        norm = re.sub(r"^[-*+]\s+", "", stripped).strip().lower()
        if norm in existing_normalized or stripped.lower() in existing_lines_lower:
            continue
        if any(_jaccard_similar(norm, existing) for existing in existing_normalized):
            continue
        kept.append(line)

    incoming_clean = "\n".join(kept).strip("\n")
    if not incoming_clean:
        return existing_clean + "\n" if existing_clean else ""
    if not existing_clean:
        return incoming_clean + "\n"
    return existing_clean + "\n\n" + incoming_clean + "\n"


def _merge_frontmatter(ours_meta: dict[str, Any], theirs_meta: dict[str, Any]) -> dict[str, Any]:
    merged = dict(ours_meta)

    ours_tags_raw = ours_meta.get("tags")
    theirs_tags_raw = theirs_meta.get("tags")
    ours_tags: list[Any] = ours_tags_raw if isinstance(ours_tags_raw, list) else []
    theirs_tags: list[Any] = theirs_tags_raw if isinstance(theirs_tags_raw, list) else []
    if ours_tags or theirs_tags:
        union: list[Any] = []
        for tag in [*ours_tags, *theirs_tags]:
            if tag not in union:
                union.append(tag)
        merged["tags"] = union

    ours_prio = str(ours_meta.get("priority") or "medium")
    theirs_prio = str(theirs_meta.get("priority") or "medium")
    if PRIORITY_ORDER.get(theirs_prio, 1) < PRIORITY_ORDER.get(ours_prio, 1):
        merged["priority"] = theirs_prio

    ours_lu = str(ours_meta.get("last_updated") or "")
    theirs_lu = str(theirs_meta.get("last_updated") or "")
    merged["last_updated"] = (
        max(ours_lu, theirs_lu) if ours_lu and theirs_lu else (ours_lu or theirs_lu)
    )

    merged["schema_version"] = CURRENT_SCHEMA_VERSION

    for key, value in theirs_meta.items():
        if key not in merged:
            merged[key] = value

    return merged


def resolve_conflict(
    ancestor_text: str, ours_text: str, theirs_text: str
) -> tuple[str | None, list[str]]:
    """Attempt a semantic 3-way merge of a Memory Fabric markdown file.

    Returns ``(merged_text, warnings)``. ``merged_text`` is ``None`` when the
    change shape isn't safely auto-mergeable — the caller should fall back to
    ``git merge-file`` in that case.
    """
    warnings: list[str] = []
    if ours_text == theirs_text:
        return ours_text, warnings

    try:
        _ancestor_meta, ancestor_body = (
            parse_frontmatter(ancestor_text) if ancestor_text.strip() else ({}, "")
        )
        ours_meta, ours_body = parse_frontmatter(ours_text)
        theirs_meta, theirs_body = parse_frontmatter(theirs_text)
    except FrontmatterError as exc:
        warnings.append(f"unparsed frontmatter on one side; deferring to textual merge: {exc}")
        return None, warnings

    for field in _IDENTITY_FIELDS:
        if field in ours_meta and field in theirs_meta and ours_meta[field] != theirs_meta[field]:
            warnings.append(f"`{field}` differs between branches; deferring to textual merge.")
            return None, warnings

    merged_body: str
    if ours_body == theirs_body:
        merged_body = ours_body
    elif ancestor_body == ours_body:
        merged_body = theirs_body
    elif ancestor_body == theirs_body:
        merged_body = ours_body
    elif ours_body.startswith(ancestor_body) and theirs_body.startswith(ancestor_body):
        ours_new = ours_body[len(ancestor_body) :]
        theirs_new = theirs_body[len(ancestor_body) :]
        merged_body = ancestor_body + _dedupe_append(ours_new, theirs_new)
    else:
        warnings.append(
            "body changes on both sides are not pure appends; deferring to textual merge."
        )
        return None, warnings

    merged_meta = _merge_frontmatter(ours_meta, theirs_meta)
    return dump_frontmatter(merged_meta, merged_body), warnings


def _git_merge_file_fallback(ancestor: str, ours: str, theirs: str) -> int:
    """Run git's own textual 3-way merge, writing conflict markers into `ours`
    on failure. Matches default git behavior exactly — the safety net for any
    change shape our semantic merge doesn't understand."""
    try:
        res = subprocess.run(
            ["git", "merge-file", ours, ancestor, theirs],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ai-memory merge-driver: git merge-file unavailable: {exc}", file=sys.stderr)
        return 1
    return res.returncode


def run(ancestor: str, ours: str, theirs: str) -> int:
    """Entry point for `ai-memory merge-driver <ancestor> <ours> <theirs>`."""
    ancestor_text = (
        Path(ancestor).read_text(encoding="utf-8", errors="replace")
        if Path(ancestor).exists()
        else ""
    )
    ours_text = Path(ours).read_text(encoding="utf-8", errors="replace")
    theirs_text = (
        Path(theirs).read_text(encoding="utf-8", errors="replace") if Path(theirs).exists() else ""
    )

    merged, warnings = resolve_conflict(ancestor_text, ours_text, theirs_text)
    for warning in warnings:
        print(f"ai-memory merge-driver: {warning}", file=sys.stderr)

    if merged is not None:
        Path(ours).write_text(merged, encoding="utf-8")
        return 0

    return _git_merge_file_fallback(ancestor, ours, theirs)


def install_merge_driver(cwd: str) -> dict[str, Any]:
    """Wire the merge driver into this clone: `.gitattributes` (shared, committed)
    + local `git config` (per-clone, per git's own design — must be re-run after
    every fresh clone)."""
    root = project_root(cwd)
    git_dir = root / ".git"
    if not (git_dir.exists() and git_dir.is_dir()):
        return {
            "ok": False,
            "gitattributes_changed": False,
            "warnings": ["Git repository not found; merge driver was not installed."],
        }

    gitattributes = root / ".gitattributes"
    pattern_line = ".ai-memory/**/*.md merge=memory-fabric\n"
    existing = gitattributes.read_text(encoding="utf-8") if gitattributes.exists() else ""
    changed_attrs = False
    if "merge=memory-fabric" not in existing:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        gitattributes.write_text(existing + separator + pattern_line, encoding="utf-8")
        changed_attrs = True

    driver_cmd = f'"{sys.executable}" -m memory_fabric.cli merge-driver %O %A %B'
    subprocess.run(
        ["git", "config", "merge.memory-fabric.name", "Memory Fabric semantic merge"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "merge.memory-fabric.driver", driver_cmd],
        cwd=root,
        check=False,
        capture_output=True,
    )

    return {
        "ok": True,
        "gitattributes_changed": changed_attrs,
        "warnings": [
            "Merge driver registration is per-clone by git's own design: "
            "commit .gitattributes, but re-run `ai-memory init --merge-driver` "
            "(or have teammates run it) after every fresh clone."
        ],
    }
