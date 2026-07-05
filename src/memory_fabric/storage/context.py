"""Assembling the full memory context bundle: relevance scoring, ordering, and
token-budget trimming across local sections, the semantic store, and global directives.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from memory_fabric.contracts import ContextBundle
from memory_fabric.frontmatter import dump_frontmatter
from memory_fabric.paths import global_memory_dir, local_memory_dir
from memory_fabric.storage._shared import (
    PRIORITY_ORDER,
    _is_ignored_local_memory_path,
    _is_store_path,
    _iter_markdown_files,
    _path_to_store_path,
    _read_memory_path,
    _safe_parse_for_sort,
    estimate_tokens,
)


def _score_section_relevance(query: str, text: str) -> float:
    """BM25-inspired keyword overlap score between a query and a memory section.

    Returns a relevance score in [0, 1] suitable for sorting. Higher = more
    relevant to the query. Uses word-set overlap (term frequency weighted) with
    no external dependencies.
    """
    if not query or not text:
        return 0.0

    def _words(s: str) -> list[str]:
        return [w.strip(".,;:!?\"'()[]{}").lower() for w in s.split() if len(w) > 2]

    query_words = set(_words(query))
    if not query_words:
        return 0.0

    doc_words = _words(text)
    if not doc_words:
        return 0.0

    # TF-weighted intersection: count how many times query terms appear
    hits = sum(1 for w in doc_words if w in query_words)
    # Normalise by document length (dampened log scale to avoid huge docs dominating)
    import math

    score = hits / (1 + math.log(1 + len(doc_words)))
    return score


def read_combined_context(
    cwd: str,
    max_tokens: int | None = None,
    query: str | None = None,
) -> ContextBundle:
    """Load and assemble the combined memory context.

    Args:
        cwd:        Project root directory.
        max_tokens: Token budget for context assembly. Defaults to the value of
                    ``MEMORY_FABRIC_TOKEN_BUDGET`` env var, or 4000 if not set.
        query:      Optional natural-language query. When provided, sections are
                    ranked by BM25-style keyword relevance before the token budget
                    is applied — ensuring the most relevant content is included
                    first. Cache is bypassed when a query is provided.
    """
    # Resolve token budget: env var > caller arg > default
    _default_budget = 4000
    try:
        _env_budget = int(os.environ.get("MEMORY_FABRIC_TOKEN_BUDGET", ""))
        _default_budget = _env_budget if _env_budget > 0 else _default_budget
    except (ValueError, TypeError):
        pass
    if max_tokens is None:
        max_tokens = _default_budget

    warnings: list[str] = []
    included: list[str] = []
    omitted: list[str] = []
    fragments: list[str] = []
    remaining = max_tokens

    # Try to load from pre-compiled consolidated_memory.md cache to save time.
    # The cache is only valid if no source memory file has been modified since it was generated.
    memory_dir = local_memory_dir(cwd)
    consolidated_path = memory_dir / "consolidated_memory.md"
    tier0 = global_memory_dir() / "directives.md"

    # Skip cache entirely when a query is provided — cached content is not
    # ordered by relevance, so query-ranked assembly must be done fresh.
    if consolidated_path.exists() and not tier0.exists() and not query:
        try:
            cache_mtime = consolidated_path.stat().st_mtime
            # Collect all source .md files that feed into the combined context.
            source_files = [
                p for p in memory_dir.rglob("*.md") if p != consolidated_path and p.is_file()
            ]
            # If any source file is newer than the cache, skip the cache entirely.
            cache_is_stale = any(p.stat().st_mtime > cache_mtime for p in source_files)
            if not cache_is_stale:
                content = consolidated_path.read_text(encoding="utf-8")
                # Remove any existing memory prompt fragment in the compiled cache first to avoid duplicates or stale data
                content = re.sub(
                    r"<!-- memory-fabric:local/memory_prompt -->\n.*?(?=\n\n<!-- memory-fabric:|$)",
                    "",
                    content,
                    flags=re.DOTALL,
                )

                prompt_path = memory_dir / "memory_prompt.txt"
                prompt_text = ""
                if prompt_path.exists():
                    p_text = prompt_path.read_text(encoding="utf-8").strip()
                    if p_text:
                        prompt_text = f"<!-- memory-fabric:local/memory_prompt -->\nMemory Prompt Steering Instructions:\n{p_text}\n\n"

                full_content = (prompt_text + content).strip() + "\n"
                est_tokens = estimate_tokens(full_content)
                if est_tokens <= max_tokens:
                    for match in re.finditer(
                        r"<!-- memory-fabric:([a-zA-Z0-9_/.-]+) -->", full_content
                    ):
                        included.append(match.group(1))
                    return {
                        "text": full_content,
                        "included_sections": included,
                        "omitted_sections": [],
                        "token_budget": max_tokens,
                        "estimated_tokens": est_tokens,
                        "warnings": [f"Tier 0 directives not found: {tier0}"],
                    }
        except Exception:
            pass

    if tier0.exists():
        text = tier0.read_text(encoding="utf-8")
        fragments.append(_format_fragment("global/directives", text))
        included.append("global/directives")
        remaining -= estimate_tokens(text)
    else:
        warnings.append(f"Tier 0 directives not found: {tier0}")

    # Load session-level memory prompt steering agent judgment
    prompt_path = memory_dir / "memory_prompt.txt"
    if prompt_path.exists():
        try:
            p_text = prompt_path.read_text(encoding="utf-8").strip()
            if p_text:
                fragments.append(
                    _format_fragment(
                        "local/memory_prompt", f"Memory Prompt Steering Instructions:\n{p_text}"
                    )
                )
                included.append("local/memory_prompt")
                remaining -= estimate_tokens(p_text)
        except Exception as exc:
            warnings.append(f"Failed to read memory_prompt.txt: {exc}")

    # Read all sections first so we can score and sort them if there's a query
    sections_data: list[dict[str, Any]] = []
    for path in _ordered_context_files(cwd):
        section_name, metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            warnings.append(read_warning)
            omitted.append(str(path))
            continue

        full_text = dump_frontmatter(metadata, body)
        section_key = _section_key(path, section_name)

        score = 0.0
        if query:
            score = _score_section_relevance(query, full_text)

        sections_data.append(
            {
                "key": section_key,
                "text": full_text,
                "metadata": metadata,
                "score": score,
                "original_index": len(sections_data),
            }
        )

    # Sort sections if query provided (stable sort: highest score first, fallback to original order)
    if query:
        sections_data.sort(key=lambda x: (x["score"], -x["original_index"]), reverse=True)

    for item in sections_data:
        section_key = item["key"]
        full_text = item["text"]
        metadata = item["metadata"]

        token_estimate = estimate_tokens(full_text)
        if token_estimate <= max(remaining, 0):
            fragments.append(_format_fragment(section_key, full_text))
            included.append(section_key)
            remaining -= token_estimate
        else:
            summary = str(metadata.get("summary") or "No summary available.")
            summary_text = (
                f"Section `{section_key}` omitted because it exceeded the remaining token budget.\n"
                f"Summary: {summary}\n"
            )
            fragments.append(_format_fragment(section_key, summary_text))
            omitted.append(section_key)
            remaining -= estimate_tokens(summary_text)

    text = "\n\n".join(fragments).strip() + ("\n" if fragments else "")
    return {
        "text": text,
        "included_sections": included,
        "omitted_sections": omitted,
        "token_budget": max_tokens,
        "estimated_tokens": estimate_tokens(text),
        "warnings": warnings,
    }


def _ordered_context_files(cwd: str) -> list[Path]:
    memory_dir = local_memory_dir(cwd)
    local_files = [
        path
        for path in _iter_markdown_files(memory_dir)
        if not _is_ignored_local_memory_path(memory_dir, path)
        and not _is_store_path(memory_dir, path)
    ]
    global_files = [
        path for path in _iter_markdown_files(global_memory_dir()) if path.name != "directives.md"
    ]
    # Include memory-store files
    store_root = memory_dir / "memory-store"
    store_files = (
        [p for p in _iter_markdown_files(store_root) if p.name != "index.md"]
        if store_root.exists()
        else []
    )

    def local_sort_key(path: Path) -> tuple[int, int, str]:
        metadata, _body, _warning = _safe_parse_for_sort(path)
        priority = str(metadata.get("priority") or "medium")
        index_rank = 0 if path.name == "index.md" else 1
        return (PRIORITY_ORDER.get(priority, 1), index_rank, path.name)

    def store_sort_key(path: Path) -> tuple[int, str]:
        metadata, _body, _warning = _safe_parse_for_sort(path)
        priority = str(metadata.get("priority") or "medium")
        return (PRIORITY_ORDER.get(priority, 1), str(path))

    high_and_medium = [path for path in local_files if local_sort_key(path)[0] in {0, 1}]
    low = [path for path in local_files if local_sort_key(path)[0] >= 3]
    store_high_medium = [p for p in store_files if store_sort_key(p)[0] in {0, 1}]
    store_low = [p for p in store_files if store_sort_key(p)[0] >= 3]

    return (
        sorted(high_and_medium, key=local_sort_key)
        + sorted(store_high_medium, key=store_sort_key)
        + sorted(global_files)
        + sorted(low, key=local_sort_key)
        + sorted(store_low, key=store_sort_key)
    )


def _section_key(path: Path, section: str) -> str:
    # Check if path is inside memory-store/
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "memory-store" and i > 0:
            store_root = Path(*parts[: i + 1])
            try:
                sp = _path_to_store_path(store_root, path)
                return f"store/{sp}"
            except ValueError:
                pass
    if ".ai-memory" in parts:
        return f"local/{section}"
    return f"global/{section}"


def _format_fragment(section: str, text: str) -> str:
    return f"<!-- memory-fabric:{section} -->\n{text.strip()}"
