"""Candidate-store mechanics for Dreaming: creation, local dedup, diffing against
live memory, applying approved changes, rewrite-task detection, and regenerating
the project index / consolidated_memory.md compiled view.
"""

from __future__ import annotations

import difflib
import re
import shutil
import tempfile
from pathlib import Path

from memory_fabric.contracts import DreamConsolidation, DreamRewriteTask
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.locking import locked_file
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage._shared import (
    PRIORITY_ORDER,
    _get_section_key,
    _is_generated_file,
    _is_ignored_local_memory_path,
    _is_steering_file,
    _is_store_path,
    _iter_markdown_files,
    _path_to_store_path,
    _read_memory_path,
    _safe_parse_for_sort,
    _write_markdown_if_changed,
)
from memory_fabric.templates import build_empty_section, now_iso


def _regenerate_index(cwd: str, mode: str) -> list[str]:
    memory_dir = local_memory_dir(cwd)
    return _regenerate_index_root(memory_dir, mode=mode)


def _extract_key_topics(body: str) -> str:
    """Extract H2 headings or top-level list items to list as key topics."""
    topics: list[str] = []
    # Find h2 headings, e.g. ## Topic Name
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("## "):
            topic = line[3:].strip()
            if topic:
                topics.append(topic)
    if not topics:
        # Fallback to top-level list items if no h2 headings exist
        for line in body.splitlines():
            if line.startswith("- ") or line.startswith("* "):
                topic = line[2:].strip()
                if topic:
                    if len(topic) > 60:
                        topic = topic[:57] + "..."
                    topics.append(topic)
                    if len(topics) >= 3:
                        break
    if not topics:
        return "None recorded"

    cleaned_topics = [t.replace("|", "\\|") for t in topics]
    return "<br>".join(f"• {t}" for t in cleaned_topics)


def _compile_consolidated_memory(memory_dir: Path) -> str:
    """Compile all active memory sections into a single read-only string."""
    fragments = []

    prompt_path = memory_dir / "memory_prompt.txt"
    if not prompt_path.exists():
        for parent in memory_dir.parents:
            if parent.name == ".ai-memory":
                prompt_path = parent / "memory_prompt.txt"
                break

    if prompt_path.exists():
        try:
            p_text = prompt_path.read_text(encoding="utf-8").strip()
            if p_text:
                fragments.append(
                    f"<!-- memory-fabric:local/memory_prompt -->\nMemory Prompt Steering Instructions:\n{p_text}"
                )
        except (OSError, UnicodeDecodeError):
            pass  # optional steering file; absence/unreadability is not an error
    local_files = [
        path
        for path in _iter_markdown_files(memory_dir)
        if path.name != "consolidated_memory.md"
        and not _is_ignored_local_memory_path(memory_dir, path)
        and not _is_store_path(memory_dir, path)
        and not _is_steering_file(path)
    ]
    steering_files = [
        path
        for path in sorted(memory_dir.glob("*.md"))
        if not _is_ignored_local_memory_path(memory_dir, path) and _is_steering_file(path)
    ]
    store_root = memory_dir / "memory-store"
    store_files = (
        [p for p in _iter_markdown_files(store_root) if p.name != "index.md"]
        if store_root.exists()
        else []
    )

    def sort_key(path: Path) -> tuple[int, int, str, str]:
        metadata, _body, _warning = _safe_parse_for_sort(path)
        priority = str(metadata.get("priority") or "medium")
        index_rank = 0 if path == memory_dir / "index.md" else 1
        return (PRIORITY_ORDER.get(priority, 1), index_rank, path.name, str(path))

    # Same order as fresh context assembly: steering first (always loaded),
    # then local maps and store files interleaved strictly by priority.
    for path in steering_files:
        section_name, metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            continue
        full_text = dump_frontmatter(metadata, body)
        fragments.append(f"<!-- memory-fabric:local/{section_name} -->\n{full_text.strip()}")

    for path in sorted(local_files + store_files, key=sort_key):
        section_name, metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            continue
        full_text = dump_frontmatter(metadata, body)
        if _is_store_path(memory_dir, path):
            section_key = f"store/{_path_to_store_path(store_root, path)}"
        else:
            section_key = f"local/{section_name}"
        fragments.append(f"<!-- memory-fabric:{section_key} -->\n{full_text.strip()}")

    return "\n\n".join(fragments).strip() + "\n"


def _regenerate_index_root(
    memory_dir: Path,
    mode: str,
    consolidation_hash: str | None = None,
    contradictions: list[str] | None = None,
    warnings: list[str] | None = None,
    compile_consolidated: bool = True,
) -> list[str]:
    checked_files = [
        str(path)
        for path in _iter_markdown_files(memory_dir)
        if path.name != "index.md"
        and not _is_ignored_local_memory_path(memory_dir, path)
        and not _is_store_path(memory_dir, path)
    ]
    # NOTE: no timestamp in the body — the frontmatter `last_updated` carries
    # it. A timestamped body would defeat the changed-content check below and
    # dirty the git tree on every Dream (P-15).
    lines = [
        "# Project Memory Index",
        "",
        f"Updated by Memory Fabric Dreaming mode `{mode}`.",
        "",
        "| Section | Priority | Summary | Key Topics |",
        "| --- | --- | --- | --- |",
    ]
    for path in _iter_markdown_files(memory_dir):
        if path.name == "index.md" or _is_ignored_local_memory_path(memory_dir, path):
            continue
        if _is_store_path(memory_dir, path):
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            # Same non-fatal-skip pattern as _consolidate_candidate_memory and
            # _process_and_finalize_candidate (see 7ee983a) — this loop just
            # wasn't covered by that fix, so a malformed flat section still
            # crashed every `dream` (light and deep) via index regeneration.
            if warnings is not None:
                warnings.append(
                    f"Skipped {path.relative_to(memory_dir)} during index regeneration: {exc}"
                )
            continue
        section = metadata.get("section", path.stem)
        priority = metadata.get("priority", "medium")
        summary = str(metadata.get("summary", "")).replace("|", "\\|")
        topics = _extract_key_topics(body)
        lines.append(f"| `{section}` | {priority} | {summary} | {topics} |")

    # Add pointer to dedicated memory-store index
    store_root = memory_dir / "memory-store"
    if store_root.exists():
        store_files = sorted(p for p in _iter_markdown_files(store_root) if p.name != "index.md")
        if store_files:
            lines.append("")
            lines.append("## Memory Store")
            lines.append("")
            lines.append(
                "Please see the dedicated [Memory Store Index](memory-store/index.md) for a map of available semantic memory store files."
            )

        # Compile memory-store/index.md (body kept timestamp-free, see above).
        # Written even when the store is still empty so a freshly initialized
        # project passes doctor's index-consistency checks (P-03).
        store_index_lines = [
            "# Memory Store Index",
            "",
            f"Updated by Memory Fabric Dreaming mode `{mode}`.",
            "",
            "| Path | Priority | Summary | Key Topics | Tags |",
            "| --- | --- | --- | --- | --- |",
        ]
        for sf in store_files:
            try:
                sf_meta, sf_body = parse_frontmatter(sf.read_text(encoding="utf-8"))
                sp = _path_to_store_path(store_root, sf)
                sf_priority = sf_meta.get("priority", "medium")
                sf_summary = str(sf_meta.get("summary", "")).replace("|", "\\|")
                sf_topics = _extract_key_topics(sf_body)
                sf_tags = sf_meta.get("tags", [])
                tags_str = ", ".join(sf_tags) if isinstance(sf_tags, list) else str(sf_tags)
                store_index_lines.append(
                    f"| `{sp}` | {sf_priority} | {sf_summary} | {sf_topics} | {tags_str} |"
                )
                checked_files.append(str(sf))
            except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
                if warnings is not None:
                    warnings.append(
                        f"Skipped {sf.relative_to(store_root)} during index regeneration: {exc}"
                    )

        store_index_path = store_root / "index.md"
        store_root.mkdir(parents=True, exist_ok=True)

        store_metadata = {
            "store_path": "index",
            "title": "Memory Store Index",
            "summary": "Index of all semantic memory store files.",
            "priority": "high",
            "tags": ["index", "memory-store"],
            "schema_version": "1.3",
            "last_updated": now_iso(),
        }
        _write_markdown_if_changed(
            store_index_path, store_metadata, "\n".join(store_index_lines) + "\n"
        )

    index_path = memory_dir / "index.md"
    if index_path.exists():
        metadata, _body = parse_frontmatter(index_path.read_text(encoding="utf-8"))
    else:
        metadata, _body = parse_frontmatter(build_empty_section("index"))

    if consolidation_hash is not None:
        metadata["consolidation_hash"] = consolidation_hash
    if contradictions is not None:
        metadata["contradictions"] = contradictions
    if warnings is not None:
        metadata["consolidation_warnings"] = warnings

    metadata["last_updated"] = now_iso()
    metadata["summary"] = "Map of available project memory sections."
    metadata["priority"] = "high"
    _write_markdown_if_changed(index_path, metadata, "\n".join(lines) + "\n")

    if compile_consolidated:
        try:
            consolidated_content = _compile_consolidated_memory(memory_dir)
            consolidated_path = memory_dir / "consolidated_memory.md"
            if (
                not consolidated_path.exists()
                or consolidated_path.read_text(encoding="utf-8") != consolidated_content
            ):
                consolidated_path.write_text(consolidated_content, encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            if warnings is not None:
                warnings.append(f"Failed to write consolidated_memory.md: {exc}")

    return checked_files


def _create_candidate_store(memory_dir: Path, snapshot: str) -> Path:
    source = memory_dir / "snapshots" / snapshot
    if not source.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot}")

    candidates_dir = memory_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    candidate_root = Path(tempfile.mkdtemp(prefix=f"{snapshot}-", dir=str(candidates_dir)))
    for path in _iter_markdown_files(source):
        relative = path.relative_to(source)
        target = candidate_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return candidate_root


def _consolidate_candidate_memory(candidate_root: Path) -> DreamConsolidation:
    seen: dict[str, tuple[str, int]] = {}
    files_touched: list[str] = []
    duplicates_found = 0
    lines_removed = 0
    warnings: list[str] = []

    for path in sorted(
        path for path in _iter_markdown_files(candidate_root) if path.name != "index.md"
    ):
        if _is_generated_file(path):
            continue  # derived views are rebuilt from the store, not deduped
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            # A single malformed memory file (hand-edited, BOM, etc.) must not
            # take down the whole Dream cycle — skip it and surface a warning
            # instead, matching how _is_generated_file/_is_steering_file
            # already treat unparsable files as non-fatal.
            warnings.append(
                f"Skipped {path.relative_to(candidate_root)} during consolidation: {exc}"
            )
            continue
        original_lines = body.splitlines()
        deduped_lines: list[str] = []
        removed_this_file = 0

        for line_number, line in enumerate(original_lines, start=1):
            normalized = _normalize_dedupe_line(line)
            if not normalized:
                deduped_lines.append(line)
                continue
            if normalized in seen:
                duplicates_found += 1
                lines_removed += 1
                removed_this_file += 1
                continue
            seen[normalized] = (str(path.relative_to(candidate_root)), line_number)
            deduped_lines.append(line)

        if removed_this_file:
            path.write_text(
                dump_frontmatter(metadata, "\n".join(deduped_lines) + "\n"), encoding="utf-8"
            )
            files_touched.append(str(path.relative_to(candidate_root)))

    return {
        "duplicates_found": duplicates_found,
        "lines_removed": lines_removed,
        "files_touched": sorted(files_touched),
        "warnings": warnings,
    }


def _normalize_dedupe_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("#"):
        return None
    cleaned = re.sub(r"^[-*+]\s+", "", stripped)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    if len(cleaned) < 24:
        return None
    return cleaned


def _diff_memory_roots(before_root: Path, after_root: Path) -> tuple[str, list[str]]:
    relative_paths = sorted(
        set(_relative_markdown_paths(before_root, ignore_local_paths=True))
        | set(_relative_markdown_paths(after_root, ignore_local_paths=False))
    )
    patch_fragments: list[str] = []
    changed: list[str] = []

    for relative in relative_paths:
        before_path = before_root / relative
        after_path = after_root / relative
        before_text = before_path.read_text(encoding="utf-8") if before_path.exists() else ""
        after_text = after_path.read_text(encoding="utf-8") if after_path.exists() else ""
        if before_text == after_text:
            continue
        changed.append(str(relative))
        patch_fragments.append(
            "".join(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True),
                    after_text.splitlines(keepends=True),
                    fromfile=str(before_path),
                    tofile=str(after_path),
                )
            )
        )

    return "".join(patch_fragments), changed


def _relative_markdown_paths(root: Path, ignore_local_paths: bool = False) -> set[Path]:
    if not root.exists():
        return set()
    paths: set[Path] = set()
    for path in _iter_markdown_files(root):
        if _is_ignored_local_memory_path(root, path):
            continue
        paths.add(path.relative_to(root))
    return paths


def _apply_candidate_to_live(
    memory_dir: Path, candidate_root: Path, affected_files: list[str]
) -> None:
    for relative_text in affected_files:
        relative = Path(relative_text)
        source = candidate_root / relative
        target = memory_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            with locked_file(target):
                shutil.copy2(source, target)
            continue
        if target.exists():
            with locked_file(target):
                target.unlink()

    # Also promote consolidated_memory.md if it exists in candidate_root
    source_compiled = candidate_root / "consolidated_memory.md"
    target_compiled = memory_dir / "consolidated_memory.md"
    if source_compiled.exists():
        target_compiled.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(target_compiled):
            shutil.copy2(source_compiled, target_compiled)


def _build_rewrite_tasks(candidate_root: Path, max_rewrite_tasks: int) -> list[DreamRewriteTask]:
    tasks: list[DreamRewriteTask] = []
    for path in sorted(
        path for path in _iter_markdown_files(candidate_root) if path.name != "index.md"
    ):
        if _is_ignored_local_memory_path(candidate_root, path):
            continue
        if _is_generated_file(path):
            continue  # maps are regenerated, never rewritten by agents
        try:
            _metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue  # unparsable file — surfaced earlier in consolidation warnings
        section = _get_section_key(candidate_root, path)
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if len(lines) < 5:
            reason = "Section is short and may benefit from enrichment with concrete details."
        elif len(lines) > 80:
            reason = "Section is long and may benefit from compression and clearer structure."
        else:
            continue
        tasks.append(
            {
                "section": section,
                "reason": reason,
                "instruction": (
                    f"Rewrite section `{section}` to preserve factual content while improving clarity, "
                    "removing repetition, and keeping frontmatter unchanged. Return a unified diff patch."
                ),
            }
        )
        if len(tasks) >= max_rewrite_tasks:
            break
    return tasks
