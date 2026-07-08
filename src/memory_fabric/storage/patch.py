"""Preview a proposed memory update as a unified diff, without writing to disk."""

from __future__ import annotations

import difflib
import re

from memory_fabric.contracts import PatchPreview
from memory_fabric.paths import local_memory_dir
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import SECTION_PATTERN, _jaccard_similar, _resolve_store_file


def propose_memory_patch(cwd: str, instructions: str) -> PatchPreview:
    """Generate a diff preview of a proposed memory update without writing to disk.

    Parses ``instructions`` to identify the target section or store path, reads
    the current file content, applies the proposed change in-memory, and returns
    a unified diff so the agent or user can review it before committing.

    The ``instructions`` string should start with a directive line in one of
    these formats::

        section: <section_name>
        store: <store/path>

    Followed by the proposed content.  If no directive line is found, the entire
    instructions string is treated as content to be appended to ``index.md``.
    """
    memory_dir = local_memory_dir(cwd)
    sanitized, redactions = redact_secrets(instructions)
    warnings: list[str] = []
    if redactions:
        warnings.append("Detected and redacted secrets before creating patch preview.")

    # --- Parse directive line --------------------------------------------------
    target_section: str | None = None
    target_store: str | None = None
    proposed_content = sanitized.strip()

    lines = sanitized.splitlines()
    if lines:
        first = lines[0].strip()
        if first.lower().startswith("section:"):
            target_section = first.split(":", 1)[1].strip()
            proposed_content = "\n".join(lines[1:]).strip()
        elif first.lower().startswith("store:"):
            target_store = first.split(":", 1)[1].strip()
            proposed_content = "\n".join(lines[1:]).strip()

    if not proposed_content:
        return {
            "patch": "",
            "affected_files": [],
            "redactions": redactions,
            "warnings": warnings + ["No proposed content provided after directive line."],
        }

    # --- Resolve target file --------------------------------------------------
    if target_store:
        try:
            target_path = _resolve_store_file(cwd, target_store)
        except ValueError as exc:
            return {
                "patch": "",
                "affected_files": [],
                "redactions": redactions,
                "warnings": warnings + [f"Invalid store path: {exc}"],
            }
    elif target_section:
        if not SECTION_PATTERN.match(target_section):
            return {
                "patch": "",
                "affected_files": [],
                "redactions": redactions,
                "warnings": warnings
                + [
                    f"Invalid section name '{target_section}': must match [A-Za-z0-9][A-Za-z0-9_-]*"
                ],
            }
        target_path = memory_dir / f"{target_section}.md"
    else:
        # Fallback: append preview to index.md
        target_path = memory_dir / "index.md"

    # --- Read current content -------------------------------------------------
    if target_path.exists():
        try:
            original_text = target_path.read_text(encoding="utf-8")
            original_lines = original_text.splitlines(keepends=True)
        except OSError as exc:
            return {
                "patch": "",
                "affected_files": [],
                "redactions": redactions,
                "warnings": warnings + [f"Cannot read target file: {exc}"],
            }
    else:
        original_text = ""
        original_lines = []
        warnings.append(
            f"Target file does not exist yet; patch shows new file creation: {target_path}"
        )

    # --- Simulate the write (append mode by default) -------------------------
    # Use the same deduplication logic as write_local_memory for append.
    existing_body = original_text.rstrip()
    clean_new = proposed_content.strip()

    if existing_body:
        # Deduplicate (same logic as write_local_memory append)
        existing_lines_lower = {
            line.strip().lower() for line in existing_body.splitlines() if line.strip()
        }
        existing_normalized = {
            re.sub(r"^[-*+]\s+", "", line).strip() for line in existing_lines_lower
        }
        new_input_lines = clean_new.splitlines()
        filtered = []
        for line in new_input_lines:
            stripped = line.strip()
            if not stripped:
                filtered.append(line)
                continue
            norm = re.sub(r"^[-*+]\s+", "", stripped).strip().lower()
            if norm in existing_normalized or stripped.lower() in existing_lines_lower:
                warnings.append(f"Line filtered as duplicate: {stripped!r}")
                continue
            if any(_jaccard_similar(norm, ex) for ex in existing_normalized):
                warnings.append(f"Line filtered as semantic near-duplicate: {stripped!r}")
                continue
            filtered.append(line)
        clean_new = "\n".join(filtered).strip()
        proposed_text = (
            existing_body + "\n\n" + clean_new + "\n" if clean_new else existing_body + "\n"
        )
    else:
        proposed_text = clean_new + "\n"

    proposed_lines = proposed_text.splitlines(keepends=True)

    # --- Generate unified diff -----------------------------------------------
    # Content lines keep their own newlines (splitlines(keepends=True)), so the
    # default lineterm="\n" must stay: lineterm="" strips the newline from the
    # ---/+++/@@ header lines only, and joining then mangles the header into
    # `--- ... (current)+++ ... (proposed)@@ ...` — unparseable by any standard
    # diff tool (P-06).
    from_label = str(target_path) + " (current)"
    to_label = str(target_path) + " (proposed)"
    patch = "".join(
        difflib.unified_diff(
            original_lines,
            proposed_lines,
            fromfile=from_label,
            tofile=to_label,
        )
    )

    if not patch:
        warnings.append(
            "No changes detected — proposed content is identical to existing content (all duplicates filtered)."
        )

    return {
        "patch": patch,
        "affected_files": [str(target_path)],
        "redactions": redactions,
        "warnings": warnings,
    }
