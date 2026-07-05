"""CRUD for flat `.ai-memory/*.md` sections (as opposed to the semantic memory-store tree)."""

from __future__ import annotations

import re

from memory_fabric.contracts import MemorySection, WriteMode, WriteResult
from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.locking import locked_file
from memory_fabric.paths import local_memory_dir
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import _jaccard_similar, _section_path, estimate_tokens
from memory_fabric.storage.lifecycle import initialize_memory_fabric
from memory_fabric.templates import build_empty_section, now_iso


def read_section(cwd: str, section: str, max_tokens: int = 8000) -> MemorySection:
    path = _section_path(cwd, section)
    warnings: list[str] = []
    if not path.exists():
        raise FileNotFoundError(f"Memory section not found: {section}")

    metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
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
        if path.exists():
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
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
            except Exception:
                pass

        redacted, redactions = redact_secrets(input_body)
        warnings = ["Detected and redacted secrets before writing memory."] if redactions else []

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

    return {
        "changed": changed,
        "path": str(path.resolve()),
        "redactions": redactions,
        "warnings": warnings,
    }
