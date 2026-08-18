"""Task-scoped retrieval: steering + top-k ranked store entries + related failures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_fabric.contracts import ContextBundle
from memory_fabric.frontmatter import dump_frontmatter
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path,
    _iter_markdown_files,
    _path_to_store_path,
    _read_memory_path,
    estimate_tokens,
)
from memory_fabric.storage.context import (
    _file_share_cap_tokens,
    _format_fragment,
    _load_always_on,
    _resolve_token_budget,
    _section_key,
    _warn_steering_budget,
)
from memory_fabric.storage.ranking import blended_score, bm25_scores, tokenize

_DEFAULT_K = 8


def context_for_task(
    cwd: str,
    query: str,
    files_open: list[str] | None = None,
    max_tokens: int | None = None,
    top_k: int = _DEFAULT_K,
) -> ContextBundle:
    """Return a task-scoped pack: steering + top-k ranked memories at full length.

    Mid-session alternative to re-dumping ``read_combined_context``. Selection
    is narrow, so a larger budget is spent usefully.
    """
    max_tokens = _resolve_token_budget(max_tokens)
    warnings: list[str] = []
    included: list[str] = []
    omitted: list[str] = []
    fragments: list[str] = []
    memory_dir = local_memory_dir(cwd)

    always_on = _load_always_on(cwd, memory_dir, fragments, included, warnings)
    _warn_steering_budget(always_on, max_tokens, warnings)
    remaining = max_tokens - sum(tok for _label, tok in always_on)

    candidates = _collect_task_candidates(cwd, memory_dir, files_open, warnings)
    if not query.strip():
        query = " ".join(files_open or [])
    _score_candidates(candidates, query)
    candidates.sort(key=lambda item: item["score"], reverse=True)

    cap = _file_share_cap_tokens(max_tokens)
    taken = 0
    for item in candidates:
        if taken >= top_k or remaining <= 0:
            omitted.append(item["key"])
            continue
        text = item["text"]
        if estimate_tokens(text) > cap:
            # Task pack prefers full length; still refuse to monopolize.
            from memory_fabric.storage.context import _cap_section_text

            text, truncated = _cap_section_text(text, item["metadata"], cap)
            if truncated:
                warnings.append(f"Truncated `{item['key']}` to the per-file share cap.")
        fragment = _format_fragment(item["key"], text)
        cost = estimate_tokens(fragment)
        if cost <= remaining:
            fragments.append(fragment)
            included.append(item["key"])
            remaining -= cost
            taken += 1
        else:
            omitted.append(item["key"])

    text = "\n\n".join(fragments).strip() + ("\n" if fragments else "")
    estimated = estimate_tokens(text)
    if estimated > max_tokens and fragments:
        while estimated > max_tokens and len(fragments) > 1:
            dropped = fragments.pop()
            estimated = estimate_tokens("\n\n".join(fragments).strip() + "\n")
            # Best-effort: keep included list aligned with fragments.
            _ = dropped
        text = "\n\n".join(fragments).strip() + "\n"
        estimated = estimate_tokens(text)

    bundle: ContextBundle = {
        "text": text,
        "included_sections": included,
        "omitted_sections": omitted,
        "token_budget": max_tokens,
        "estimated_tokens": estimated,
        "warnings": warnings,
    }
    from memory_fabric.storage.context import _with_pack_stats

    priority_by_key = {
        str(item["key"]): str((item.get("metadata") or {}).get("priority") or "medium")
        for item in candidates
    }
    return _with_pack_stats(
        cwd,
        bundle,
        startup_mode="full",
        index_used=False,
        query=query,
        fragments=fragments,
        priority_by_key=priority_by_key,
    )


def _collect_task_candidates(
    cwd: str,
    memory_dir: Path,
    files_open: list[str] | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    store_root = memory_dir / "memory-store"
    candidates: list[dict[str, Any]] = []
    open_basenames = {Path(p).name.lower() for p in (files_open or []) if p}

    roots = []
    if store_root.exists():
        roots.append(store_root)
    # Root maps also compete — they point at the right store path.
    roots.append(memory_dir)

    seen: set[str] = set()
    for root in roots:
        for path in _iter_markdown_files(root):
            if _is_ignored_local_memory_path(memory_dir, path):
                continue
            if path.parent == memory_dir and path.name == "consolidated_memory.md":
                continue
            if root == memory_dir and path.parent != memory_dir:
                continue
            section_name, metadata, body, read_warning = _read_memory_path(path)
            if read_warning:
                warnings.append(read_warning)
                continue
            key = _section_key(path, section_name)
            if key in seen:
                continue
            seen.add(key)
            store_path = ""
            if store_root.exists():
                try:
                    path.relative_to(store_root)
                    store_path = _path_to_store_path(store_root, path)
                except ValueError:
                    store_path = ""
            boost = 0.0
            if open_basenames and store_path.startswith("failures/"):
                blob = (body + " " + str(metadata.get("title") or "")).lower()
                if any(name in blob for name in open_basenames):
                    boost = 2.0
            candidates.append(
                {
                    "key": key,
                    "text": dump_frontmatter(metadata, body),
                    "metadata": metadata,
                    "store_path": store_path,
                    "boost": boost,
                    "score": 0.0,
                }
            )
    return candidates


def _score_candidates(candidates: list[dict[str, Any]], query: str) -> None:
    if not candidates:
        return
    query_tokens = tokenize(query)
    docs = [tokenize(item["text"]) for item in candidates]
    scores = bm25_scores(query_tokens, docs) if query_tokens else [1.0] * len(candidates)
    for item, raw in zip(candidates, scores, strict=True):
        metadata = item["metadata"]
        item["score"] = blended_score(
            raw,
            str(metadata.get("priority") or "medium"),
            str(metadata.get("last_updated") or ""),
            key=str(item["key"]),
        ) + float(item.get("boost") or 0.0)
