"""CRUD for the semantic `memory-store/` tree (as opposed to flat `.ai-memory/*.md` sections)."""

from __future__ import annotations

import re

from memory_fabric.contracts import (
    StoreEntry,
    StoreListResult,
    StoreReadResult,
    StoreWriteResult,
    WriteMode,
    WriteResult,
)
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.locking import locked_file
from memory_fabric.paths import memory_store_dir
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import (
    PRIORITY_ORDER,
    _path_to_store_path,
    _resolve_store_file,
    estimate_tokens,
)
from memory_fabric.templates import now_iso


def write_memory_store(
    cwd: str,
    store_path: str,
    content: str,
    title: str = "",
    tags: list[str] | None = None,
    priority: str | None = None,
    mode: WriteMode = "replace",
    evidence: list[str] | None = None,
) -> StoreWriteResult:
    """Write a memory file to a semantic store path.

    Args:
        priority: ``high``/``medium``/``low``. When omitted, an existing file
                  keeps its current priority (same contract as ``tags`` and
                  ``title``); new files default to ``medium``.
        evidence: Optional list of citation refs this memory depends on, e.g.
                  ``"src/auth.py"``, ``"src/auth.py:42"``, or ``"commit:<hash>"``.
                  ``ai-memory verify`` checks these still resolve and flags the
                  memory when they don't — the mechanism that lets rot be
                  caught by a machine instead of a human noticing years later.
    """
    if mode not in {"append", "replace"}:
        raise ValueError("mode must be 'append' or 'replace'")
    if priority is not None and priority not in {"high", "medium", "low"}:
        raise ValueError("priority must be 'high', 'medium', or 'low'")

    path = _resolve_store_file(cwd, store_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with locked_file(path):
        recovery_warning: str | None = None
        needs_fresh_metadata = not path.exists()
        if path.exists():
            try:
                metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
                if mode == "append":
                    # Can't safely merge into content we can't read — refuse
                    # loudly instead of silently dropping whatever is there.
                    raise ValueError(
                        f"Cannot append to {store_path}: existing file is unreadable ({exc}). "
                        "Use mode='replace' to overwrite it."
                    ) from exc
                # replace mode: the caller's intent is to overwrite anyway, so
                # a corrupted existing file must not block that — start fresh,
                # same as the "file does not exist" branch below.
                needs_fresh_metadata = True
                body = ""
                recovery_warning = (
                    f"Existing {store_path} could not be read ({exc}) and was fully replaced."
                )
            else:
                if mode == "replace":
                    # `review_status` is derived state (stamped by verify/dream);
                    # a full rewrite starts clean unless the caller re-supplies it.
                    metadata.pop("review_status", None)

        if needs_fresh_metadata:
            display_title = title or store_path.split("/")[-1].replace("-", " ").title()
            metadata = {
                "store_path": store_path,
                "title": display_title,
                "summary": f"Memory: {display_title}.",
                "priority": priority or "medium",
                "tags": tags or [],
                "schema_version": "1.3",
            }
            body = ""

        # Check if the input content starts with frontmatter, and extract it
        input_body = content
        if content.lstrip().startswith("---"):
            try:
                input_meta, parsed_body = parse_frontmatter(content)
                input_body = parsed_body
                for k, v in input_meta.items():
                    if k not in {"store_path", "last_updated", "schema_version"}:
                        metadata[k] = v
            except FrontmatterError:
                pass  # content merely starts with "---"; treat it as plain body text

        redacted, redactions = redact_secrets(input_body)
        warnings: list[str] = (
            ["Detected and redacted secrets before writing memory."] if redactions else []
        )
        if recovery_warning:
            warnings.append(recovery_warning)

        # Update metadata
        metadata["store_path"] = store_path
        metadata["last_updated"] = now_iso()
        if title:
            metadata["title"] = title
        if tags is not None:
            metadata["tags"] = tags
        if priority is not None:
            metadata["priority"] = priority
        metadata.setdefault("priority", "medium")
        if evidence is not None:
            metadata["evidence"] = evidence

        changed = True
        if mode == "replace":
            new_body = redacted.strip() + "\n"
        else:
            clean_existing = body.rstrip()
            clean_new = redacted.strip()

            if clean_existing and clean_new:
                existing_lines = {
                    line.strip().lower() for line in clean_existing.splitlines() if line.strip()
                }
                existing_normalized = {
                    re.sub(r"^[-*+]\s+", "", line).strip() for line in existing_lines
                }

                new_lines = clean_new.splitlines()
                filtered_lines = []
                for line in new_lines:
                    stripped = line.strip()
                    if not stripped:
                        filtered_lines.append(line)
                        continue
                    norm_line = re.sub(r"^[-*+]\s+", "", stripped).strip().lower()
                    if norm_line in existing_normalized or stripped.lower() in existing_lines:
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
            # Auto-generate summary from title or first content line
            first_line = new_body.strip().split("\n")[0].strip() if new_body.strip() else ""
            if title:
                metadata["summary"] = title[:150]
            elif first_line and first_line != metadata.get("summary", ""):
                summary_text = first_line.lstrip("#").strip()
                if len(summary_text) > 150:
                    summary_text = summary_text[:147] + "..."
                metadata["summary"] = summary_text

            path.write_text(dump_frontmatter(metadata, new_body), encoding="utf-8")

    return {
        "changed": changed,
        "path": str(path.resolve()),
        "store_path": store_path,
        "redactions": redactions,
        "warnings": warnings,
    }


def read_memory_store(
    cwd: str,
    store_path: str,
    max_tokens: int = 8000,
) -> StoreReadResult:
    """Read a single memory-store file by its semantic path."""
    path = _resolve_store_file(cwd, store_path)
    warnings: list[str] = []
    if not path.exists():
        raise FileNotFoundError(f"Memory store file not found: {store_path}")

    metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    text = dump_frontmatter(metadata, body)
    truncated = False
    if estimate_tokens(text) > max_tokens:
        summary = str(metadata.get("summary") or "No summary available.")
        text = (
            f"Store file `{store_path}` omitted because it exceeded the token budget.\n"
            f"Summary: {summary}\n"
        )
        truncated = True
        warnings.append("Store file exceeded token budget; returned summary only.")

    return {
        "store_path": store_path,
        "path": str(path.resolve()),
        "text": text,
        "metadata": metadata,
        "truncated": truncated,
        "warnings": warnings,
    }


def list_memory_store(
    cwd: str,
    prefix: str = "",
    tags: list[str] | None = None,
    max_results: int = 50,
) -> StoreListResult:
    """List files in the memory store, optionally filtered by prefix and/or tags."""
    store_root = memory_store_dir(cwd)
    warnings: list[str] = []
    entries: list[StoreEntry] = []

    if not store_root.exists():
        return {"entries": [], "total": 0, "warnings": ["Memory store not found."]}

    for path in sorted(store_root.rglob("*.md")):
        if not path.is_file() or path.name == "index.md":
            continue

        sp = _path_to_store_path(store_root, path)

        # Filter by prefix
        if prefix and not sp.startswith(prefix.strip("/")):
            continue

        try:
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            warnings.append(f"Could not parse store file: {path}")
            continue

        file_tags = metadata.get("tags", [])
        if not isinstance(file_tags, list):
            file_tags = []

        # Filter by tags (intersection)
        if tags and not set(tags).intersection(set(file_tags)):
            continue

        entries.append(
            {
                "store_path": sp,
                "path": str(path.resolve()),
                "summary": str(metadata.get("summary", "")),
                "priority": str(metadata.get("priority", "medium")),
                "tags": file_tags,
                "last_updated": str(metadata.get("last_updated", "")),
            }
        )

    # Sort by priority (high first), then alphabetically
    entries.sort(key=lambda e: (PRIORITY_ORDER.get(e["priority"], 1), e["store_path"]))

    total = len(entries)
    if total > max_results:
        entries = entries[:max_results]
        warnings.append(f"Results truncated to {max_results} of {total} total entries.")

    return {"entries": entries, "total": total, "warnings": warnings}


def delete_memory_store(
    cwd: str,
    store_path: str,
) -> WriteResult:
    """Remove a store file and clean up empty parent directories."""
    path = _resolve_store_file(cwd, store_path)
    if not path.exists():
        raise FileNotFoundError(f"Memory store file not found: {store_path}")

    with locked_file(path):
        path.unlink()

    # Clean up empty parent directories within memory-store/
    store_root = memory_store_dir(cwd)
    current = path.parent
    while current != store_root and current.is_relative_to(store_root):
        try:
            remaining = [f for f in current.iterdir() if f.name != ".gitkeep"]
            if not remaining:
                # Remove .gitkeep if it exists, then the dir
                gitkeep = current / ".gitkeep"
                if gitkeep.exists():
                    gitkeep.unlink()
                current.rmdir()
                current = current.parent
            else:
                break
        except OSError:
            break

    return {
        "changed": True,
        "path": str(path.resolve()),
        "redactions": 0,
        "warnings": [],
    }
