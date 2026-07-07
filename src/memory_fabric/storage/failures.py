"""Failure memory: durable error -> fix pairs.

The highest-signal memory category for a coding agent: "I hit this exact
error before, and here's what fixed it." There is no reliable cross-language
way to auto-detect "a bug was just fixed" from git alone, so this is an
agent-invoked, purpose-built write — not part of passive capture.

Repeat encounters of the *same kind* of error (paths and numbers normalized
away) collapse onto one growing store entry instead of fragmenting into many
near-duplicate files, so "this keeps happening" becomes visible as a rising
``occurrences`` count rather than being lost across N separate memories.
"""

from __future__ import annotations

import hashlib
import re

from memory_fabric.contracts import WriteResult
from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.paths import memory_store_dir
from memory_fabric.storage.store import read_memory_store, write_memory_store
from memory_fabric.templates import now_iso

# Strip volatile specifics so the SAME kind of error (seen with different
# file paths, line numbers, PIDs, or addresses across occurrences) collapses
# onto one signature instead of fragmenting into near-duplicate slugs.
_NORMALIZE_PATH_RE = re.compile(r"(?:[A-Za-z]:)?[/\\][\w./\\-]+")
_NORMALIZE_NUMBER_RE = re.compile(r"\d+")


def _normalize_error(error_summary: str) -> str:
    text = error_summary.strip().lower()
    text = _NORMALIZE_PATH_RE.sub("<path>", text)
    text = _NORMALIZE_NUMBER_RE.sub("<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]


def _slug_for(normalized: str) -> str:
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    words = re.findall(r"[a-z0-9]+", normalized)
    hint = "-".join(words[:4]) or "error"
    return f"{hint}-{digest}"


def write_failure_memory(
    cwd: str,
    error_summary: str,
    fix_summary: str,
    tags: list[str] | None = None,
) -> WriteResult:
    """Record an error -> fix pair as durable, deduplicated memory.

    Call this immediately after fixing a bug. The error text is normalized
    (paths and numbers stripped) into a stable slug under
    ``memory-store/failures/<slug>``; a repeat of the same normalized error
    accumulates onto that same entry with an incrementing ``occurrences``
    counter rather than creating a new near-duplicate file.
    """
    normalized = _normalize_error(error_summary)
    slug = _slug_for(normalized)
    store_path = f"failures/{slug}"

    occurrences = 1
    try:
        existing = read_memory_store(cwd, store_path)
        occurrences = int(existing["metadata"].get("occurrences") or 0) + 1
    except FileNotFoundError:
        pass

    block = (
        f"## Occurrence {occurrences} — {now_iso()}\n\n"
        f"**Error:**\n{error_summary.strip()}\n\n"
        f"**Fix:**\n{fix_summary.strip()}\n"
    )

    first_line = error_summary.strip().splitlines()[0] if error_summary.strip() else "Failure"
    result = write_memory_store(
        cwd,
        store_path=store_path,
        content=block,
        title=first_line[:80],
        tags=sorted({"failure", "fix", *(tags or [])}),
        priority="medium",
        mode="append",
    )

    # write_memory_store doesn't know about `occurrences` — stamp it directly
    # so the counter always reflects call count even when append-mode dedup
    # filters out lines identical to a prior occurrence's body text.
    path = memory_store_dir(cwd) / f"{store_path}.md"
    if path.exists():
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        metadata["occurrences"] = occurrences
        path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")

    warnings = list(result.get("warnings", []))
    if occurrences > 1:
        warnings.append(
            f"This error signature has now occurred {occurrences} times — "
            "consider whether a systemic fix is warranted."
        )

    return {
        "changed": result["changed"] or occurrences > 1,
        "path": result["path"],
        "redactions": result["redactions"],
        "warnings": warnings,
    }
