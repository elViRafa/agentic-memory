"""Self-verifying citations: memory that can prove it's still true.

Any memory file may carry an ``evidence`` frontmatter list of citation refs:
a file path (``src/auth.py``), a path with a line number (``src/auth.py:42``),
or a commit (``commit:<hash>``). ``verify_evidence`` checks each ref still
resolves against the current tree. A memory citing a file that was renamed
or deleted is the single most common way project memory rots — this makes
that rot machine-detectable instead of something a human stumbles on months
later (exactly what happened to this project's own `architecture.md` before
the store-first migration).

Unverifiable ref kinds (``pr:123``, URLs) are skipped rather than flagged —
verifying them would require a network call, which conflicts with the
local-first guarantee.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.paths import local_memory_dir, project_root
from memory_fabric.storage._shared import (
    _get_section_key,
    _is_ignored_local_memory_path,
    _iter_markdown_files,
)

_PATH_LINE_RE = re.compile(r"^(?P<path>.+):(?P<line>\d+)$")
_UNVERIFIABLE_PREFIXES = ("pr:", "issue:", "url:", "http://", "https://")


def _classify_ref(ref: str) -> tuple[str, str]:
    ref = ref.strip()
    if ref.startswith("commit:"):
        return "commit", ref[len("commit:") :].strip()
    if ref.startswith(_UNVERIFIABLE_PREFIXES):
        return "unverifiable", ref
    return "path", ref


def _check_path_ref(root: Path, ref: str) -> str | None:
    """Return a problem string if the ref doesn't resolve, else None."""
    match = _PATH_LINE_RE.match(ref)
    rel_path = match.group("path") if match else ref
    line_no = int(match.group("line")) if match else None

    target = root / rel_path
    if not target.exists():
        return f"file not found: {rel_path}"
    if line_no is not None:
        try:
            with target.open("r", encoding="utf-8", errors="replace") as fh:
                line_count = sum(1 for _ in fh)
        except OSError:
            return None  # binary or unreadable — don't fail the check over this
        if line_no > line_count:
            return f"{rel_path} has {line_count} lines, evidence cites line {line_no}"
    return None


def _check_commit_ref(root: Path, commit_hash: str) -> str | None:
    try:
        res = subprocess.run(
            ["git", "cat-file", "-e", commit_hash],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=5.0,
            check=False,
        )
    except Exception:
        return None  # not a git repo, or git unavailable — skip rather than false-fail
    if res.returncode != 0:
        return f"commit not found: {commit_hash}"
    return None


def verify_evidence(
    cwd: str, mark_broken: bool = True, memory_dir: Path | None = None
) -> dict[str, Any]:
    """Check every memory file's ``evidence`` refs against the current tree.

    Returns ``{"checked_files", "broken", "marked_broken", "ok", "warnings"}``.
    ``broken`` is a list of ``{"key", "path", "problems"}``. When
    ``mark_broken`` is True (the default for the explicit ``ai-memory verify``
    command; eval calls this with False to stay read-only), broken files get
    ``review_status: broken-evidence`` stamped in place.

    ``memory_dir`` defaults to the live ``.ai-memory/`` but can point at a
    snapshot copy (e.g. when scoring a Dreaming snapshot) — evidence refs are
    read from whichever memory tree is passed, always checked against the
    real project tree at ``cwd`` since source files don't move with snapshots.
    """
    root = project_root(cwd)
    memory_dir = memory_dir if memory_dir is not None else local_memory_dir(cwd)
    checked = 0
    broken: list[dict[str, Any]] = []
    marked: list[str] = []
    warnings: list[str] = []

    for path in _iter_markdown_files(memory_dir):
        if _is_ignored_local_memory_path(memory_dir, path):
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            warnings.append(f"{path}: {exc}")
            continue

        evidence = metadata.get("evidence")
        if not evidence or not isinstance(evidence, list):
            continue
        checked += 1

        problems: list[str] = []
        for ref in evidence:
            kind, value = _classify_ref(str(ref))
            if kind == "path":
                problem = _check_path_ref(root, value)
            elif kind == "commit":
                problem = _check_commit_ref(root, value)
            else:
                continue
            if problem:
                problems.append(problem)

        if problems:
            key = _get_section_key(memory_dir, path)
            broken.append({"key": key, "path": str(path), "problems": problems})
            if mark_broken and metadata.get("review_status") != "broken-evidence":
                metadata["review_status"] = "broken-evidence"
                path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
                marked.append(key)

    return {
        "checked_files": checked,
        "broken": broken,
        "marked_broken": marked,
        "ok": not broken,
        "warnings": warnings,
    }
