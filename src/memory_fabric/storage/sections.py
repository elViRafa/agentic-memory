"""CRUD for flat `.ai-memory/*.md` sections (as opposed to the semantic memory-store tree)."""

from __future__ import annotations

import re

from memory_fabric.contracts import MemorySection, WriteMode, WriteResult
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.locking import locked_file
from memory_fabric.paths import local_memory_dir
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import (
    STEERING_SECTIONS,
    _is_steering_file,
    _jaccard_similar,
    _section_path,
    estimate_tokens,
)
from memory_fabric.storage.lifecycle import initialize_memory_fabric
from memory_fabric.templates import build_empty_section, now_iso

_STORE_FIRST_DEPRECATION = (
    "DEPRECATED (store-first model): root map sections are generated from memory-store/ "
    "and hand-written flat sections are being phased out. Write facts with "
    "write_memory_store_tool instead; write_local_memory will be removed in v1.0."
)


def _content_declares_steering(content: str) -> bool:
    """True if `content`'s own frontmatter declares `role: steering`."""
    if not content.lstrip().startswith("---"):
        return False
    try:
        metadata, _body = parse_frontmatter(content)
    except FrontmatterError:
        return False
    return str(metadata.get("role") or "").strip().lower() == "steering"


def flat_write_rejection(cwd: str, section: str, content: str) -> str | None:
    """Return why a flat write to `section` is not permitted, or None to allow it.

    Store-first (v1.0): the flat write path is narrowed to the steering/directive
    tier. The root map sections are generated views over ``memory-store/`` and
    must be written through ``write_memory_store_tool`` (then rebuilt by
    Dreaming), so a fact written to a flat map file can no longer rot the map.
    A section stays writable here only when it is steering — one of the canonical
    ``STEERING_SECTIONS``, content that declares ``role: steering``, or an
    existing on-disk file already marked steering.
    """
    if section in STEERING_SECTIONS or _content_declares_steering(content):
        return None
    existing = _section_path(cwd, section)
    if existing.exists() and _is_steering_file(existing):
        return None
    return (
        f"Writing the flat section `{section}` is no longer supported (store-first "
        "model, v1.0): root map sections are generated views over memory-store/. "
        f"Write facts with write_memory_store_tool, then run dream_tool to rebuild "
        f"the `{section}` map. To convert legacy hand-written sections, run "
        "`ai-memory migrate`. Only steering sections (framework-rules, "
        "ubiquitous-language, or content with `role: steering`) remain writable here."
    )


def read_section(cwd: str, section: str, max_tokens: int = 8000) -> MemorySection:
    path = _section_path(cwd, section)
    warnings: list[str] = []
    if not path.exists():
        raise FileNotFoundError(f"Memory section not found: {section}")

    try:
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        raise ValueError(f"Memory section `{section}` is unreadable: {exc}") from exc
    text = dump_frontmatter(metadata, body)
    truncated = False
    if estimate_tokens(text) > max_tokens:
        summary = str(metadata.get("summary") or "No summary available.")
        text = (
            f"Section `{section}` omitted because it exceeded the token budget.\n"
            f"Summary: {summary}\n"
        )
        truncated = True
        warnings.append("Section exceeded token budget; returned summary only.")

    return {
        "section": section,
        "path": str(path),
        "text": text,
        "metadata": metadata,
        "truncated": truncated,
        "warnings": warnings,
    }


def write_local_memory(
    cwd: str,
    section: str,
    content: str,
    mode: WriteMode = "append",
) -> WriteResult:
    if mode not in {"append", "replace"}:
        raise ValueError("mode must be 'append' or 'replace'")

    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        initialize_memory_fabric(cwd)

    path = _section_path(cwd, section)

    with locked_file(path):
        recovery_warning: str | None = None
        if path.exists():
            try:
                metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
                if mode == "append":
                    # Can't safely merge into content we can't read — refuse
                    # loudly instead of silently dropping whatever is there.
                    raise ValueError(
                        f"Cannot append to section `{section}`: existing file is unreadable "
                        f"({exc}). Use mode='replace' to overwrite it."
                    ) from exc
                # replace mode: the caller's intent is to overwrite anyway, so
                # a corrupted existing file must not block that — start fresh.
                metadata, body = parse_frontmatter(build_empty_section(section))
                recovery_warning = f"Existing section `{section}` could not be read ({exc}) and was fully replaced."
        else:
            metadata, body = parse_frontmatter(build_empty_section(section))

        # Check if the input content starts with frontmatter, and extract it
        input_body = content
        if content.lstrip().startswith("---"):
            try:
                input_meta, parsed_body = parse_frontmatter(content)
                input_body = parsed_body
                # Merge metadata fields except core managed fields
                for k, v in input_meta.items():
                    if k not in {"section", "last_updated", "schema_version"}:
                        metadata[k] = v
            except FrontmatterError:
                pass  # content merely starts with "---"; treat it as plain body text

        redacted, redactions = redact_secrets(input_body)
        warnings = ["Detected and redacted secrets before writing memory."] if redactions else []
        if recovery_warning:
            warnings.append(recovery_warning)

        metadata["section"] = section
        metadata["last_updated"] = now_iso()

        changed = True
        if mode == "replace":
            new_body = redacted.strip() + "\n"
        else:
            clean_existing = body.rstrip()
            clean_new = redacted.strip()

            # Prevent duplicate lines/bullets during append.
            # Two-pass check: (1) exact match after normalization, (2) Jaccard similarity
            # for near-duplicates with slightly different wording.
            if clean_existing and clean_new:
                existing_raw_lines = [line for line in clean_existing.splitlines() if line.strip()]
                existing_lines_lower = {line.strip().lower() for line in existing_raw_lines}
                # Remove common list prefixes for better duplicate detection
                existing_normalized = {
                    re.sub(r"^[-*+]\s+", "", line).strip() for line in existing_lines_lower
                }

                new_lines = clean_new.splitlines()
                filtered_lines = []
                for line in new_lines:
                    stripped = line.strip()
                    if not stripped:
                        filtered_lines.append(line)
                        continue
                    norm_line = re.sub(r"^[-*+]\s+", "", stripped).strip().lower()
                    # Pass 1: exact match
                    if norm_line in existing_normalized or stripped.lower() in existing_lines_lower:
                        continue
                    # Pass 2: semantic near-duplicate via Jaccard similarity
                    if any(
                        _jaccard_similar(norm_line, existing) for existing in existing_normalized
                    ):
                        continue
                    filtered_lines.append(line)

                clean_new = "\n".join(filtered_lines).strip()

            if clean_existing and clean_new:
                new_body = clean_existing + "\n\n" + clean_new + "\n"
            elif clean_new:
                new_body = clean_new + "\n"
            elif clean_existing:
                new_body = clean_existing + "\n"
                changed = False
                warnings.append("No new unique memory content was appended (duplicates filtered).")
            else:
                new_body = ""
                changed = False

        if changed:
            path.write_text(dump_frontmatter(metadata, new_body), encoding="utf-8")

    # Steering sections stay hand-curated; every other flat write is deprecated
    # in favor of the semantic store (maps are generated views over it).
    role = str(metadata.get("role") or "").strip().lower()
    is_steering = role == "steering" or (not role and section in STEERING_SECTIONS)
    if not is_steering:
        warnings.append(_STORE_FIRST_DEPRECATION)
    if metadata.get("generated"):
        warnings.append(
            f"`{section}.md` is a generated map: the next Dreaming run folds this hand edit "
            f"into memory-store/{section}/map-notes-pending-review.md and rebuilds the map."
        )

    return {
        "changed": changed,
        "path": str(path.resolve()),
        "redactions": redactions,
        "warnings": warnings,
    }
