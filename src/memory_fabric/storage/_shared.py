"""Low-level primitives shared by every storage submodule.

Path/section resolution, frontmatter schema migration, markdown file discovery,
token estimation, and near-duplicate detection. No submodule-specific logic lives
here — if only one submodule needs it, it belongs in that submodule instead.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.paths import local_memory_dir, memory_store_dir

SECTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
STORE_PATH_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}  # contiguous 0-2 mapping

# Steering sections are hand-curated directives, not budget-competing memory:
# context assembly always loads them in full. Sections can opt in/out with a
# `role: steering` frontmatter field; these two canonical names are steering by
# default so stores created before the marker existed keep working.
STEERING_SECTIONS = frozenset({"framework-rules", "ubiquitous-language"})

# Current schema version for all Memory Fabric markdown files.
CURRENT_SCHEMA_VERSION = "1.3"

# Jaccard similarity threshold for near-duplicate detection during append.
# Lines with overlap ratio >= this threshold are treated as duplicates.
# Set via MEMORY_FABRIC_DEDUP_THRESHOLD env var (float 0.0-1.0, default 0.85).
_DEDUP_THRESHOLD_DEFAULT = 0.85


def _validate_store_path(store_path: str) -> list[str]:
    """Validate a semantic store path like 'architecture/decisions/auth-service'.

    Returns a list of validated segments, or raises ValueError.
    """
    segments = store_path.strip("/").split("/")
    if not segments or segments == [""]:
        raise ValueError("store_path must not be empty")
    if len(segments) > 5:
        raise ValueError("store_path must not exceed 5 levels of nesting")
    for seg in segments:
        if not STORE_PATH_SEGMENT.match(seg):
            raise ValueError(
                f"Invalid store_path segment '{seg}': "
                "must be lowercase alphanumeric, starting with a letter or digit, "
                "using only a-z, 0-9, hyphens, and underscores"
            )
    return segments


def _resolve_store_file(cwd: str, store_path: str) -> Path:
    """Resolve a semantic store path to an absolute filesystem path."""
    segments = _validate_store_path(store_path)
    filename = segments[-1] + ".md"
    dir_segments = segments[:-1]
    store_root = memory_store_dir(cwd)
    target_dir = store_root
    for seg in dir_segments:
        target_dir = target_dir / seg
    return target_dir / filename


def _path_to_store_path(store_root: Path, file_path: Path) -> str:
    """Convert an absolute file path inside memory-store/ to a store_path string."""
    relative = file_path.relative_to(store_root)
    parts = list(relative.parts)
    # Remove .md extension from last segment
    if parts and parts[-1].endswith(".md"):
        parts[-1] = parts[-1][:-3]
    return "/".join(parts)


def _get_section_key(root: Path, path: Path) -> str:
    """Get the canonical section key relative to the root directory (live or candidate).

    Root-relative, unlike `context._section_key` which infers scope by scanning
    for literal ".ai-memory"/"memory-store" path segments — that heuristic doesn't
    hold for Dreaming's temp-dir candidate/snapshot roots, which need this instead.
    """
    store_root = root / "memory-store"
    if store_root.exists():
        try:
            path.relative_to(store_root)
            sp = _path_to_store_path(store_root, path)
            return f"store/{sp}"
        except ValueError:
            pass
    try:
        metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        sec_name = metadata.get("section") or path.stem
    except Exception:
        sec_name = path.stem
    return f"local/{sec_name}"


def _section_path(cwd: str | Path, section: str) -> Path:
    if not SECTION_PATTERN.match(section):
        raise ValueError("section must contain only letters, numbers, underscores, and hyphens")
    return local_memory_dir(cwd) / f"{section}.md"


def _migrate_frontmatter(metadata: dict[str, Any], path: Path) -> dict[str, Any]:
    """Upgrade frontmatter from older schema versions to the current version.

    This is a forward-only migration that adds missing required fields with
    safe defaults. It does NOT rewrite the file — upgrades are applied in
    memory only, so old files continue to work without an explicit migration
    command. Re-writes happen naturally on the next write operation.

    Supported upgrades:
    - Any schema < 1.3: add missing required fields with safe defaults.
    """
    from memory_fabric.templates import now_iso  # avoid circular import at module level

    # Fields required since v1.3
    if "summary" not in metadata:
        metadata["summary"] = f"Memory section: {path.stem}."
    if "priority" not in metadata:
        metadata["priority"] = "medium"
    if "tags" not in metadata:
        metadata["tags"] = []
    if "last_updated" not in metadata:
        metadata["last_updated"] = now_iso()

    # Normalize priority to a valid value
    if metadata.get("priority") not in {"high", "medium", "low"}:
        metadata["priority"] = "medium"

    # Stamp the current schema version in memory (written on next save)
    metadata["schema_version"] = CURRENT_SCHEMA_VERSION

    return metadata


def _read_memory_path(path: Path) -> tuple[str, dict[str, Any], str, str | None]:
    try:
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        return path.stem, {}, "", f"{path}: {exc}"
    # Apply schema migration transparently on every read (no file write).
    metadata = _migrate_frontmatter(metadata, path)
    section = str(metadata.get("section") or path.stem)
    return section, metadata, body, None


def _safe_parse_for_sort(path: Path) -> tuple[dict[str, Any], str, str | None]:
    try:
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        return metadata, body, None
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        return {}, "", str(exc)


def _iter_markdown_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def _is_ignored_local_memory_path(memory_dir: Path, path: Path) -> bool:
    try:
        relative_parts = path.relative_to(memory_dir).parts
    except ValueError:
        return False
    if path.name == "consolidated_memory.md":
        return True
    return bool({"private", "snapshots", "evals", "candidates"}.intersection(relative_parts))


def _is_store_path(memory_dir: Path, path: Path) -> bool:
    """Check if a path is inside the memory-store/ subdirectory."""
    store_root = memory_dir / "memory-store"
    try:
        path.relative_to(store_root)
        return True
    except ValueError:
        return False


def _is_generated_file(path: Path) -> bool:
    """True for files whose frontmatter marks them `generated: true`.

    Generated files are derived views (root maps, discovery indexes): Dreaming
    rebuilds them from the store, so they are excluded from consolidation
    payloads, LLM summarization, staleness marking, and rewrite tasks.
    """
    try:
        metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FrontmatterError):
        return False
    return bool(metadata.get("generated"))


def _is_steering_file(path: Path) -> bool:
    """Check whether a section file is a steering directive (always loaded).

    An explicit `role:` frontmatter field wins; without one, the canonical
    STEERING_SECTIONS names are steering by default.
    """
    try:
        metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FrontmatterError):
        return path.stem in STEERING_SECTIONS
    role = str(metadata.get("role") or "").strip().lower()
    if role:
        return role == "steering"
    return path.stem in STEERING_SECTIONS


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a string.

    Uses a chars/4 heuristic (standard for most Latin-alphabet LLM tokenizers).
    For very short strings that tend to be code/symbols, uses chars/3 to avoid
    undercounting. This is still a heuristic — for exact counts, use tiktoken.
    """
    if not text:
        return 0
    if len(text) < 100:
        return max(1, len(text) // 3)
    return max(1, len(text) // 4)


def _jaccard_similar(line_a: str, line_b: str, threshold: float | None = None) -> bool:
    """Return True if two strings are semantically near-duplicates.

    Computes the Jaccard similarity of their word sets (intersection / union).
    Requires no embeddings or external libraries — pure standard library.

    Examples where exact matching would fail but this catches the duplicate:
      - "Added auth middleware"  vs  "Auth middleware added to route handlers"
      - "We use PostgreSQL"      vs  "PostgreSQL is the database of choice"

    Requires at least 3 significant words in each string to avoid false
    positives on very short content like numbered bullet items.
    """
    if threshold is None:
        try:
            threshold = float(os.environ.get("MEMORY_FABRIC_DEDUP_THRESHOLD", ""))
        except (ValueError, TypeError):
            threshold = _DEDUP_THRESHOLD_DEFAULT

    # Tokenize into a set of lowercase words (strip punctuation, require len > 2)
    def _words(text: str) -> set[str]:
        return {w.strip(".,;:!?\"'()[]{}") for w in text.lower().split() if len(w) > 2}

    words_a = _words(line_a)
    words_b = _words(line_b)
    # Require at least 3 meaningful words in BOTH strings before applying Jaccard.
    # Short strings like "Bullet 2" only yield 1 word ("bullet"), making them
    # prone to spurious matches.
    if len(words_a) < 3 or len(words_b) < 3:
        return False
    intersection = words_a & words_b
    union = words_a | words_b
    if not union:
        return False
    return len(intersection) / len(union) >= threshold
