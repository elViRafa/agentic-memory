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
import os
import re

from memory_fabric.contracts import WriteResult
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.paths import memory_store_dir
from memory_fabric.storage.ranking import slugify, token_jaccard
from memory_fabric.storage.store import read_memory_store, write_memory_store
from memory_fabric.templates import now_iso

# Strip volatile specifics so the SAME kind of error (seen with different
# file paths, line numbers, PIDs, quoted literals, or addresses across
# occurrences) collapses onto one signature instead of fragmenting into
# near-duplicate slugs. Python exception messages almost always embed the
# offending value, so anything that looks like a literal must be masked.
_NORMALIZE_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_NORMALIZE_PATH_RE = re.compile(r"(?:[A-Za-z]:)?[/\\][\w./\\-]+")
_NORMALIZE_HEX_RE = re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{8,40}\b")
_NORMALIZE_NUMBER_RE = re.compile(r"\d+")

# Even after masking, two reports of the same root cause rarely normalize to
# the same exact string (agents reword the surrounding sentence). Records
# whose slug hint matches are therefore also compared by word-set Jaccard
# similarity; at or above this threshold the new report merges into the
# existing entry instead of creating a fresh file.
_FAILURE_MERGE_THRESHOLD_DEFAULT = 0.4


def _failure_merge_threshold() -> float:
    try:
        value = float(os.environ.get("MEMORY_FABRIC_FAILURE_MERGE_THRESHOLD", ""))
        if 0.0 <= value <= 1.0:
            return value
    except (TypeError, ValueError):
        pass
    return _FAILURE_MERGE_THRESHOLD_DEFAULT


def _normalize_error(error_summary: str) -> str:
    text = error_summary.strip().lower()
    text = _NORMALIZE_QUOTED_RE.sub("<val>", text)
    text = _NORMALIZE_PATH_RE.sub("<path>", text)
    text = _NORMALIZE_HEX_RE.sub("<hex>", text)
    text = _NORMALIZE_NUMBER_RE.sub("<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]


_EXCEPTION_RE = re.compile(
    r"\b((?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*(?:Error|Exception|Warning|Fault))\b"
)
_ERROR_CODE_RE = re.compile(r"\b([A-Z]{2,}[-_]\d+|E[A-Z]+\d+)\b")
_GENERIC_EXCEPTIONS = frozenset(
    {
        "error",
        "exception",
        "valueerror",
        "typeerror",
        "keyerror",
        "attributeerror",
        "runtimeerror",
        "indexerror",
        "assertionerror",
        "oserror",
    }
)


def _structured_failure_key(error_summary: str) -> str:
    """Exception class + error code, independent of surrounding prose language."""
    classes = _EXCEPTION_RE.findall(error_summary)
    codes = _ERROR_CODE_RE.findall(error_summary)
    parts: list[str] = []
    if classes:
        parts.append(classes[0].rsplit(".", 1)[-1].lower())
    if codes:
        parts.append(codes[0].lower())
    return "|".join(parts)


def _hint_for(normalized: str) -> str:
    slug = slugify(normalized)
    words = [w for w in slug.split("-") if w]
    return "-".join(words[:4]) or "error"


def _slug_for(normalized: str) -> str:
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{_hint_for(normalized)}-{digest}"


def _find_similar_failure(cwd: str, normalized: str, structured_key: str) -> str | None:
    """Return the slug of an existing failure entry this report should merge into.

    Structured key (exception class / error code) is tried first across the
    whole failures/ directory. Prose Jaccard is the fallback, no longer
    gated on the first-four-words hint prefix.
    """
    failures_dir = memory_store_dir(cwd) / "failures"
    if not failures_dir.is_dir():
        return None
    threshold = _failure_merge_threshold()
    for path in sorted(failures_dir.glob("*.md")):
        try:
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        stored_key = str(metadata.get("failure_key") or "")
        if structured_key and stored_key and structured_key == stored_key:
            # Generic exceptions (ValueError, TypeError) are too common to
            # merge on class alone; require a code or a non-generic name.
            specific = "|" in structured_key or structured_key not in _GENERIC_EXCEPTIONS
            if specific:
                return path.stem
        signature = str(metadata.get("error_signature") or "")
        if signature and token_jaccard(normalized, signature, min_tokens=3) >= threshold:
            return path.stem
    return None


def write_failure_memory(
    cwd: str,
    error_summary: str,
    fix_summary: str,
    tags: list[str] | None = None,
) -> WriteResult:
    """Record an error -> fix pair as durable, deduplicated memory.

    Call this immediately after fixing a bug. The error text is normalized
    (quoted literals, paths, hex ids, and numbers masked) into a stable slug
    under ``memory-store/failures/<slug>``; a repeat of the same normalized
    error accumulates onto that same entry with an incrementing
    ``occurrences`` counter. Reports that normalize differently but share the
    slug hint and a similar signature (word-set Jaccard, tunable via
    ``MEMORY_FABRIC_FAILURE_MERGE_THRESHOLD``) also merge instead of
    scattering into near-duplicate files.
    """
    normalized = _normalize_error(error_summary)
    structured_key = _structured_failure_key(error_summary)
    slug = _slug_for(normalized)
    store_path = f"failures/{slug}"

    occurrences = 1
    matched = False
    try:
        existing = read_memory_store(cwd, store_path)
        occurrences = int(existing["metadata"].get("occurrences") or 0) + 1
        matched = True
    except FileNotFoundError:
        pass

    if not matched:
        similar_slug = _find_similar_failure(cwd, normalized, structured_key)
        if similar_slug is not None:
            slug = similar_slug
            store_path = f"failures/{slug}"
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

    # write_memory_store doesn't know about `occurrences`/`error_signature` —
    # stamp them directly so the counter always reflects call count even when
    # append-mode dedup filters out lines identical to a prior occurrence's
    # body text. The first signature is kept as the canonical one that future
    # reports are compared against.
    path = memory_store_dir(cwd) / f"{store_path}.md"
    if path.exists():
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        metadata["occurrences"] = occurrences
        metadata.setdefault("error_signature", normalized)
        if structured_key:
            metadata.setdefault("failure_key", structured_key)
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
