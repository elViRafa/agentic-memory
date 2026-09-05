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
    _is_steering_file,
    _is_store_path,
    _iter_markdown_files,
    _path_to_store_path,
    _read_memory_path,
    _safe_parse_for_sort,
    _steering_context_enabled,
    estimate_tokens,
)
from memory_fabric.storage.hygiene import MAP_QUERY_CAP_TOKENS, steering_body_is_placeholder
from memory_fabric.storage.ranking import (
    blended_score,
    bm25_scores,
    is_commit_capture,
    tokenize,
)

_DEFAULT_BUDGET = 4000
_FILE_SHARE_CAP_DEFAULT = 0.25
_STEERING_WARN_FRACTION = 0.5
_COMPACT_OMISSION = (
    "{n} more sections omitted; search with keyword_search_tool or read memory-store/index.md"
)


def _resolve_token_budget(max_tokens: int | None) -> int:
    default = _DEFAULT_BUDGET
    try:
        env_budget = int(os.environ.get("MEMORY_FABRIC_TOKEN_BUDGET", ""))
        if env_budget > 0:
            default = env_budget
    except (ValueError, TypeError):
        pass
    if max_tokens is None:
        return default
    return max_tokens if max_tokens > 0 else default


def _file_share_cap_tokens(max_tokens: int) -> int:
    raw = os.environ.get("MEMORY_FABRIC_FILE_SHARE_CAP", "")
    try:
        fraction = float(raw) if raw else _FILE_SHARE_CAP_DEFAULT
    except (ValueError, TypeError):
        fraction = _FILE_SHARE_CAP_DEFAULT
    if fraction <= 0 or fraction > 1:
        fraction = _FILE_SHARE_CAP_DEFAULT
    return max(1, int(max_tokens * fraction))


def _startup_mode() -> str:
    mode = (os.environ.get("MEMORY_FABRIC_STARTUP_MODE") or "maps").strip().lower()
    return mode if mode in {"maps", "full"} else "maps"


def _should_skip_startup_dump(query: str | None) -> bool:
    if query:
        return False
    flag = (os.environ.get("MEMORY_FABRIC_SKIP_STARTUP_DUMP") or "").strip().lower()
    return flag in {"1", "true", "yes"}


def _skip_dump_bundle(cwd: str, max_tokens: int) -> ContextBundle:
    text = (
        "Startup context was already delivered (MEMORY_FABRIC_SKIP_STARTUP_DUMP "
        "or the MCP Resource `memory-fabric://context/` was served this session). "
        "Skipping a second dump. Use `keyword_search_tool` or `context_for_task_tool` "
        "for task-scoped retrieval; read `memory-store/index.md` for the map.\n"
    )
    bundle: ContextBundle = {
        "text": text,
        "included_sections": [],
        "omitted_sections": [],
        "token_budget": max_tokens,
        "estimated_tokens": estimate_tokens(text),
        "warnings": [
            f"Skipped full startup dump for {cwd}; resource already injected or "
            "MEMORY_FABRIC_SKIP_STARTUP_DUMP is set."
        ],
    }
    return _with_pack_stats(cwd, bundle, startup_mode="skipped", index_used=False, query=None)


def _cap_section_text(full_text: str, metadata: dict[str, Any], cap: int) -> tuple[str, bool]:
    """Trim a non-steering file to ``cap`` tokens: summary + leading body."""
    if estimate_tokens(full_text) <= cap:
        return full_text, False
    summary = str(metadata.get("summary") or "").strip()
    prefix = f"Summary: {summary}\n\n" if summary else ""
    # Inverse of estimate_tokens (chars/4 for long strings).
    budget_chars = max(cap * 3, 200)
    body = full_text
    if len(prefix) + len(body) > budget_chars:
        cut = max(0, budget_chars - len(prefix))
        body = body[:cut].rsplit("\n", 1)[0] + "\n\n[truncated]\n"
    text = prefix + body
    while estimate_tokens(text) > cap and len(text) > 80:
        text = text[: int(len(text) * 0.85)].rsplit("\n", 1)[0] + "\n\n[truncated]\n"
    return text, True


def _source_files_for_cache(memory_dir: Path, consolidated_path: Path) -> list[Path]:
    return [
        p
        for p in memory_dir.rglob("*.md")
        if p != consolidated_path
        and p.is_file()
        and not _is_ignored_local_memory_path(memory_dir, p)
    ]


def _try_consolidated_cache(
    cwd: str,
    max_tokens: int,
    query: str | None,
) -> ContextBundle | None:
    """Return a cache hit, or None to fall through to the authoritative path."""
    if query or _startup_mode() != "full":
        return None
    memory_dir = local_memory_dir(cwd)
    consolidated_path = memory_dir / "consolidated_memory.md"
    tier0 = global_memory_dir() / "directives.md"
    if not consolidated_path.exists() or tier0.exists():
        return None
    try:
        cache_mtime = consolidated_path.stat().st_mtime
        source_files = _source_files_for_cache(memory_dir, consolidated_path)
        if any(p.stat().st_mtime > cache_mtime for p in source_files):
            return None
        content = consolidated_path.read_text(encoding="utf-8")
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
                prompt_text = (
                    f"<!-- memory-fabric:local/memory_prompt -->\n"
                    f"Memory Prompt Steering Instructions:\n{p_text}\n\n"
                )
        full_content = (prompt_text + content).strip() + "\n"
        est_tokens = estimate_tokens(full_content)
        if est_tokens > max_tokens:
            return None
        included = [
            match.group(1)
            for match in re.finditer(r"<!-- memory-fabric:([a-zA-Z0-9_/.-]+) -->", full_content)
        ]
        cached_bundle: ContextBundle = {
            "text": full_content,
            "included_sections": included,
            "omitted_sections": [],
            "token_budget": max_tokens,
            "estimated_tokens": est_tokens,
            "warnings": [f"Tier 0 directives not found: {tier0}"],
        }
        return _with_pack_stats(
            cwd, cached_bundle, startup_mode="full", index_used=False, query=query
        )
    except (OSError, UnicodeDecodeError):
        return None


def _load_always_on(
    cwd: str,
    memory_dir: Path,
    fragments: list[str],
    included: list[str],
    warnings: list[str],
) -> list[tuple[str, int]]:
    """Tier 0 + memory prompt + steering. Returns (label, tokens) for budget warnings."""
    costs: list[tuple[str, int]] = []
    tier0 = global_memory_dir() / "directives.md"
    if tier0.exists():
        text = tier0.read_text(encoding="utf-8")
        fragment = _format_fragment("global/directives", text)
        fragments.append(fragment)
        included.append("global/directives")
        costs.append((str(tier0), estimate_tokens(fragment)))
    else:
        warnings.append(f"Tier 0 directives not found: {tier0}")

    prompt_path = memory_dir / "memory_prompt.txt"
    if prompt_path.exists():
        try:
            p_text = prompt_path.read_text(encoding="utf-8").strip()
            if p_text:
                fragment = _format_fragment(
                    "local/memory_prompt", f"Memory Prompt Steering Instructions:\n{p_text}"
                )
                fragments.append(fragment)
                included.append("local/memory_prompt")
                costs.append((str(prompt_path), estimate_tokens(fragment)))
        except Exception as exc:  # noqa: BLE001 - reported via warnings, not swallowed.
            warnings.append(f"Failed to read memory_prompt.txt: {exc}")

    for path in _steering_section_files(memory_dir):
        section_name, metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            warnings.append(read_warning)
            continue
        if steering_body_is_placeholder(body):
            warnings.append(
                f"Skipped placeholder steering file {path.name} so it does not "
                "occupy the always-on budget."
            )
            continue
        full_text = dump_frontmatter(metadata, body)
        key = f"local/{section_name}"
        fragment = _format_fragment(key, full_text)
        fragments.append(fragment)
        included.append(key)
        costs.append((str(path), estimate_tokens(fragment)))
    return costs


def _warn_steering_budget(
    costs: list[tuple[str, int]], max_tokens: int, warnings: list[str]
) -> None:
    total = sum(tok for _label, tok in costs)
    if max_tokens <= 0 or total <= max_tokens * _STEERING_WARN_FRACTION:
        return
    named = ", ".join(f"{Path(label).name} (~{tok} tokens)" for label, tok in costs)
    warnings.append(
        f"Always-on steering + Tier 0 consume ~{total} tokens "
        f"({total / max_tokens:.0%} of the {max_tokens}-token budget): {named}. "
        "Trim those files or raise MEMORY_FABRIC_TOKEN_BUDGET."
    )


def _collect_startup_maps(
    memory_dir: Path, warnings: list[str], omitted: list[str]
) -> list[dict[str, Any]]:
    """Root maps + memory-store/index.md only. Does not walk granular store files."""
    paths: list[Path] = []
    if memory_dir.exists():
        for path in sorted(memory_dir.glob("*.md")):
            if _is_startup_map_path(memory_dir, path):
                paths.append(path)
    store_index = memory_dir / "memory-store" / "index.md"
    if store_index.exists():
        paths.append(store_index)
    sections: list[dict[str, Any]] = []
    for path in paths:
        section_name, metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            warnings.append(read_warning)
            omitted.append(str(path))
            continue
        full_text = dump_frontmatter(metadata, body)
        section_key = _section_key(path, section_name)
        sections.append(
            {
                "key": section_key,
                "text": full_text,
                "metadata": metadata,
                "path": path,
                "rank_text": full_text,
                "original_index": len(sections),
            }
        )
    return sections


def _collect_sections_full_scan(
    cwd: str,
    memory_dir: Path,
    query: str | None,
    warnings: list[str],
    omitted: list[str],
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    maps_only = query is None and _startup_mode() == "maps"
    for path in _ordered_context_files(cwd):
        if maps_only and not _is_startup_map_path(memory_dir, path):
            continue
        if query is None and is_commit_capture(str(path).replace("\\", "/")):
            continue
        section_name, metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            warnings.append(read_warning)
            omitted.append(str(path))
            continue
        full_text = dump_frontmatter(metadata, body)
        section_key = _section_key(path, section_name)
        sections.append(
            {
                "key": section_key,
                "text": full_text,
                "metadata": metadata,
                "path": path,
                "rank_text": full_text,
                "original_index": len(sections),
            }
        )
    return sections


def _collect_sections_from_index(
    cwd: str,
    memory_dir: Path,
    query: str | None,
    warnings: list[str],
) -> list[dict[str, Any]] | None:
    try:
        from memory_fabric.storage.index import close_quietly, load_rows, sync_index
    except Exception:  # noqa: BLE001 - index is optional; fall back to full scan.
        return None
    conn = sync_index(cwd)
    if conn is None:
        return None
    try:
        rows = load_rows(conn, memory_dir)
    finally:
        close_quietly(conn)
    if not rows:
        return None
    maps_only = query is None and _startup_mode() == "maps"
    sections: list[dict[str, Any]] = []
    for row in rows:
        if row.is_steering:
            continue
        if maps_only and not row.is_map:
            continue
        if query is None and is_commit_capture(row.section_key):
            continue
        sections.append(
            {
                "key": row.section_key,
                "text": None,
                "metadata": {
                    "summary": row.summary,
                    "priority": row.priority,
                    "title": row.title,
                    "last_updated": row.last_updated,
                    "tags": row.tags,
                },
                "path": row.path,
                "rank_text": row.rank_text,
                "original_index": len(sections),
            }
        )
    return sections


def _ensure_section_body(item: dict[str, Any], warnings: list[str], omitted: list[str]) -> bool:
    """Load the file body for an index row. Returns False if unreadable."""
    if item.get("text"):
        return True
    path: Path = item["path"]
    section_name, metadata, body, read_warning = _read_memory_path(path)
    if read_warning:
        warnings.append(read_warning)
        omitted.append(item["key"])
        return False
    item["text"] = dump_frontmatter(metadata, body)
    item["metadata"] = metadata
    item["key"] = _section_key(path, section_name)
    return True


def _rank_sections(sections: list[dict[str, Any]], query: str | None) -> None:
    if not sections:
        return
    query_tokens = tokenize(query or "")
    if query_tokens:
        docs = [tokenize(str(item.get("rank_text") or item.get("text") or "")) for item in sections]
        scores = bm25_scores(query_tokens, docs)
    else:
        scores = [1.0] * len(sections)
    for item, raw in zip(sections, scores, strict=True):
        metadata = item["metadata"]
        item["score"] = blended_score(
            raw,
            str(metadata.get("priority") or "medium"),
            str(metadata.get("last_updated") or ""),
            key=str(item["key"]),
            query_present=bool(query_tokens),
        )
    sections.sort(key=lambda x: (x["score"], -x["original_index"]), reverse=True)


def _assemble_fragments(fragments: list[str]) -> str:
    if not fragments:
        return ""
    return "\n\n".join(fragments).strip() + "\n"


def _omission_notice_fragment(n: int) -> str:
    return _format_fragment("omission-notice", _COMPACT_OMISSION.format(n=n))


def _is_omission_notice(fragment: str) -> bool:
    return fragment.startswith("<!-- memory-fabric:omission-notice")


def _refresh_omission_notice(fragments: list[str], omitted: list[str]) -> None:
    fragments[:] = [f for f in fragments if not _is_omission_notice(f)]
    if omitted:
        fragments.append(_omission_notice_fragment(len(omitted)))


def _fit_to_budget(
    fragments: list[str],
    included: list[str],
    omitted: list[str],
    *,
    always_on_n: int,
    max_tokens: int,
    steering_used: int,
) -> None:
    """Keep the compact omission line; drop competing sections if the join is over budget.

    Always-on steering may legally exceed ``max_tokens``. Competing maps/store
    fragments must not. The post-join trim used to pop the omission notice first,
    leaving ``omitted_sections`` set with no textual cue — the Windows flake in
    ``test_compact_omission_line_not_per_section_placeholders``.
    """
    _refresh_omission_notice(fragments, omitted)
    if steering_used > max_tokens:
        return
    while estimate_tokens(_assemble_fragments(fragments)) > max_tokens:
        drop_at = None
        for i in range(len(fragments) - 1, -1, -1):
            if _is_omission_notice(fragments[i]) or i < always_on_n:
                continue
            drop_at = i
            break
        if drop_at is None:
            break
        fragments.pop(drop_at)
        competing_i = drop_at - always_on_n
        key = included.pop(always_on_n + competing_i)
        omitted.append(key)
        _refresh_omission_notice(fragments, omitted)


def _pack_sections(
    sections: list[dict[str, Any]],
    remaining: int,
    max_tokens: int,
    fragments: list[str],
    included: list[str],
    omitted: list[str],
    warnings: list[str],
    *,
    query: str | None = None,
) -> None:
    cap = _file_share_cap_tokens(max_tokens)
    compact_reserve = estimate_tokens(_omission_notice_fragment(999)) + 2
    packable = max(0, remaining - compact_reserve)
    budget_exhausted = packable <= 0
    query_present = bool(query and query.strip())

    for item in sections:
        key = item["key"]
        if budget_exhausted:
            omitted.append(key)
            continue
        if query_present and float(item.get("score") or 0) <= 0:
            omitted.append(key)
            continue
        if not _ensure_section_body(item, warnings, omitted):
            continue
        full_text = item["text"]
        metadata = item["metadata"]
        item_cap = cap
        if query_present:
            from memory_fabric.diary.roles import classify_role

            if classify_role(key) == "map":
                item_cap = min(cap, MAP_QUERY_CAP_TOKENS)
        capped, truncated = _cap_section_text(full_text, metadata, item_cap)
        fragment = _format_fragment(key, capped)
        cost = estimate_tokens(fragment)
        if cost <= packable:
            fragments.append(fragment)
            included.append(key)
            packable -= cost
            remaining -= cost
            if truncated:
                warnings.append(f"Truncated `{key}` to the per-file share cap ({item_cap} tokens).")
        else:
            omitted.append(key)
            budget_exhausted = True
            # Everything after this is omitted (budget exhausted).
            # Remaining items are recorded below.
            rest = []
            started = False
            for later in sections:
                if later["key"] == key:
                    started = True
                    continue
                if started:
                    rest.append(later["key"])
            omitted.extend(rest)
            break


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
                    ranked by Okapi BM25 (plus priority and recency) before the
                    token budget is applied. Cache is bypassed when a query is
                    provided.
    """
    max_tokens = _resolve_token_budget(max_tokens)
    if _should_skip_startup_dump(query):
        return _skip_dump_bundle(cwd, max_tokens)

    cached = _try_consolidated_cache(cwd, max_tokens, query)
    if cached is not None:
        return cached

    warnings: list[str] = []
    included: list[str] = []
    omitted: list[str] = []
    fragments: list[str] = []
    memory_dir = local_memory_dir(cwd)

    always_on = _load_always_on(cwd, memory_dir, fragments, included, warnings)
    _warn_steering_budget(always_on, max_tokens, warnings)
    always_on_n = len(fragments)
    used = estimate_tokens(_assemble_fragments(fragments))
    remaining = max_tokens - used

    # Maps-first no-query must not touch the store tree (or the SQLite index):
    # walking 1000 granular files to pack 6 maps is the p95 we are killing.
    sections: list[dict[str, Any]]
    index_used = False
    if query is None and _startup_mode() == "maps":
        sections = _collect_startup_maps(memory_dir, warnings, omitted)
    else:
        indexed = _collect_sections_from_index(cwd, memory_dir, query, warnings)
        index_used = indexed is not None
        sections = (
            indexed
            if indexed is not None
            else _collect_sections_full_scan(cwd, memory_dir, query, warnings, omitted)
        )

    _rank_sections(sections, query)
    _pack_sections(
        sections, remaining, max_tokens, fragments, included, omitted, warnings, query=query
    )
    _fit_to_budget(
        fragments,
        included,
        omitted,
        always_on_n=always_on_n,
        max_tokens=max_tokens,
        steering_used=used,
    )

    text = _assemble_fragments(fragments)
    estimated = estimate_tokens(text)

    bundle: ContextBundle = {
        "text": text,
        "included_sections": included,
        "omitted_sections": omitted,
        "token_budget": max_tokens,
        "estimated_tokens": estimated,
        "warnings": warnings,
    }
    priority_by_key = {
        str(item["key"]): str((item.get("metadata") or {}).get("priority") or "medium")
        for item in sections
    }
    return _with_pack_stats(
        cwd,
        bundle,
        startup_mode=_startup_mode() if query is None else "full",
        index_used=index_used,
        query=query,
        fragments=fragments,
        priority_by_key=priority_by_key,
    )


def _is_startup_map_path(memory_dir: Path, path: Path) -> bool:
    """Root maps and memory-store/index.md — no granular store bodies."""
    if path == memory_dir / "memory-store" / "index.md":
        return True
    if path.parent == memory_dir and path.suffix == ".md":
        if path.name == "consolidated_memory.md":
            return False
        return not _is_steering_file(path)
    return False


def _steering_section_files(memory_dir: Path) -> list[Path]:
    """Root steering section files routed into context (always loaded in full).

    Steering files with an effective ``context: false`` flag are excluded
    entirely: they are distributed through `sync-agents` per-tool files
    instead, and never compete for the token budget either.
    """
    if not memory_dir.exists():
        return []
    return [
        path
        for path in sorted(memory_dir.glob("*.md"))
        if not _is_ignored_local_memory_path(memory_dir, path)
        and _is_steering_file(path)
        and _steering_context_enabled(path)
    ]


def _ordered_context_files(cwd: str) -> list[Path]:
    """Budget-competing memory files, ordered strictly by priority.

    Store-first model: local map files and memory-store files are interleaved in
    one priority-sorted sequence — no flat-before-store bias. Steering sections
    are excluded here because `read_combined_context` always loads them in full.
    """
    memory_dir = local_memory_dir(cwd)
    local_files = [
        path
        for path in _iter_markdown_files(memory_dir)
        if not _is_ignored_local_memory_path(memory_dir, path)
        and not _is_store_path(memory_dir, path)
        and not _is_steering_file(path)
    ]
    global_files = [
        path for path in _iter_markdown_files(global_memory_dir()) if path.name != "directives.md"
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

    # `low` is rank 2 in PRIORITY_ORDER; the previous `>= 3` comparison silently
    # dropped low-priority files from the context entirely.
    budgeted = local_files + store_files
    high_and_medium = [p for p in budgeted if sort_key(p)[0] in {0, 1}]
    low = [p for p in budgeted if sort_key(p)[0] >= 2]

    return sorted(high_and_medium, key=sort_key) + sorted(global_files) + sorted(low, key=sort_key)


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


def _with_pack_stats(
    cwd: str,
    bundle: ContextBundle,
    *,
    startup_mode: str,
    index_used: bool,
    query: str | None,
    fragments: list[str] | None = None,
    priority_by_key: dict[str, str] | None = None,
) -> ContextBundle:
    from memory_fabric.diary.instrument import record_context_pack
    from memory_fabric.diary.stats import attach_pack_stats

    finished = attach_pack_stats(
        bundle,
        priority_by_key=priority_by_key,
        startup_mode=startup_mode,
        index_used=index_used,
        query=query,
        fragments=fragments,
    )
    record_context_pack(cwd, finished, query=query)
    return finished
