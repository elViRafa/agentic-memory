"""Task-scoped retrieval of current evidence and historical leads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_fabric.contracts import ContextBundle
from memory_fabric.diary.roles import classify_role
from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage._evidence import (
    EvidenceState,
    current_successor,
    evidence_state,
    identifiers,
    note_rank_text,
    open_file_reference,
    query_passage,
    query_tokens,
    topical_match,
)
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path,
    _is_steering_file,
    _iter_markdown_files,
    _read_memory_path,
    estimate_tokens,
)
from memory_fabric.storage.context import (
    _collect_sections_from_index,
    _file_share_cap_tokens,
    _format_fragment,
    _load_always_on,
    _resolve_token_budget,
    _section_key,
    _warn_steering_budget,
    _with_pack_stats,
)
from memory_fabric.storage.ranking import blended_score, bm25_scores, tokenize

_DEFAULT_K = 8


@dataclass(frozen=True)
class _TaskFragment:
    key: str
    text: str
    state: EvidenceState
    excerpt: bool = False


def context_for_task(
    cwd: str,
    query: str,
    files_open: list[str] | None = None,
    max_tokens: int | None = None,
    top_k: int = _DEFAULT_K,
) -> ContextBundle:
    """Return always-on steering and relevant evidence within the task budget."""
    max_tokens = _resolve_token_budget(max_tokens)
    warnings: list[str] = []
    steering_keys: list[str] = []
    steering: list[str] = []
    memory_dir = local_memory_dir(cwd)
    costs = _load_always_on(cwd, memory_dir, steering, steering_keys, warnings)
    _warn_steering_budget(costs, max_tokens, warnings)

    candidates, index_used = _task_candidates(cwd, memory_dir, warnings)
    candidates = [item for item in candidates if item["key"] not in steering_keys]
    terms = query_tokens(query)[1]
    ranked = _rank_candidates(candidates, terms, files_open or [])
    cap = _file_share_cap_tokens(max_tokens)
    delivered: list[_TaskFragment] = []
    eligible = False

    for item in ranked:
        if len(delivered) >= top_k and eligible:
            break
        fragment, has_evidence = _task_fragment(item, terms, cap, warnings)
        eligible |= has_evidence
        if fragment is None or len(delivered) >= top_k:
            continue
        proposed_text = "\n\n".join([*steering, *(part.text for part in delivered), fragment.text])
        if estimate_tokens(proposed_text + "\n") <= max_tokens:
            delivered.append(fragment)

    fragments = [*steering, *(fragment.text for fragment in delivered)]
    text = "\n\n".join(fragments) + ("\n" if fragments else "")
    included = [*steering_keys, *(fragment.key for fragment in delivered)]
    included_keys = set(included)
    priority_by_key = {
        item["key"]: str(item["metadata"].get("priority") or "medium") for item in candidates
    }
    for fragment in delivered:
        if fragment.excerpt:
            warnings.append(
                f"Truncated `{fragment.key}` to a query excerpt under the per-file share cap."
            )

    bundle: ContextBundle = {
        "text": text,
        "included_sections": included,
        "omitted_sections": [key for key in priority_by_key if key not in included_keys],
        "token_budget": max_tokens,
        "estimated_tokens": estimate_tokens(text),
        "warnings": warnings,
    }
    scope = query.strip() or " ".join(files_open or []).strip()
    if scope:
        if any(fragment.state == "current" for fragment in delivered):
            bundle["retrieval_status"] = "matched"
        elif delivered:
            bundle["retrieval_status"] = "historical_only"
        elif eligible:
            bundle["retrieval_status"] = "budget_limited"
        else:
            bundle["retrieval_status"] = "no_match"

    return _with_pack_stats(
        cwd,
        bundle,
        startup_mode="full",
        index_used=index_used,
        query=scope,
        fragments=fragments,
        priority_by_key=priority_by_key,
    )


def _task_candidates(
    cwd: str, memory_dir: Path, warnings: list[str]
) -> tuple[list[dict[str, Any]], bool]:
    indexed = _collect_sections_from_index(cwd, memory_dir, "", warnings)
    if indexed is not None:
        return [item for item in indexed if classify_role(item["key"]) != "map"], True

    candidates = []
    seen: set[str] = set()
    for path in _iter_markdown_files(memory_dir):
        if _is_ignored_local_memory_path(memory_dir, path) or _is_steering_file(path):
            continue
        section, metadata, body, warning = _read_memory_path(path)
        if warning:
            warnings.append(warning)
            continue
        key = _section_key(path, section)
        if key in seen or classify_role(key) == "map":
            continue
        seen.add(key)
        candidates.append(
            {
                "key": key,
                "metadata": metadata,
                "rank_text": note_rank_text(path.stem, metadata, body),
                "path": path,
            }
        )
    return candidates, False


def _lifecycle(key: str, metadata: dict[str, Any]) -> tuple[EvidenceState, str]:
    successor = str(metadata.get("superseded_by") or "").strip()
    return evidence_state(
        key,
        str(metadata.get("review_status") or ""),
        successor,
        str(metadata.get("role") or ""),
    ), successor


def _rank_candidates(
    candidates: list[dict[str, Any]], terms: list[str], files: list[str]
) -> list[dict[str, Any]]:
    docs = [tokenize(item["rank_text"]) for item in candidates]
    scores = bm25_scores(terms, docs)
    exact = identifiers(terms)
    by_key = {item["key"]: item for item in candidates}
    lifecycle = {key: _lifecycle(key, item["metadata"]) for key, item in by_key.items()}
    store_lifecycle = {
        key.removeprefix("store/"): status
        for key, status in lifecycle.items()
        if key.startswith("store/")
    }
    ranked: dict[str, dict[str, Any]] = {}
    links: dict[str, tuple[float, str]] = {}
    for item, raw, words in zip(candidates, scores, docs, strict=True):
        key = item["key"]
        state, successor = lifecycle[key]
        if state == "broken":
            continue
        reference = (
            open_file_reference(item["rank_text"], files)
            if key.startswith("store/failures/")
            else ""
        )
        topical = topical_match(terms, exact, set(words), item["path"].stem)
        if not topical and (not reference or state == "historical"):
            continue
        meta = item["metadata"]
        score = blended_score(
            raw,
            str(meta.get("priority") or "medium"),
            str(meta.get("last_updated") or ""),
            key=key,
            query_present=True,
            role=str(meta.get("role") or "") or None,
        ) + (2.0 if reference else 0.0)
        ranked[key] = {
            **item,
            "score": score,
            "state": state,
            "reference": "" if topical else reference,
        }

        if state == "closed":
            target = current_successor(successor, store_lifecycle)
            target_key = f"store/{target}"
            if target and (target_key not in links or score > links[target_key][0]):
                links[target_key] = (score, key.removeprefix("store/"))

    for key, (score, predecessor) in links.items():
        item = ranked.get(key) or {**by_key[key], "state": "current", "reference": "", "score": 0.0}
        ranked[key] = {**item, "score": max(score, item["score"]), "predecessor": predecessor}

    return sorted(
        ranked.values(),
        key=lambda item: (item["state"] == "current", item["score"]),
        reverse=True,
    )


def _task_fragment(
    item: dict[str, Any], terms: list[str], cap: int, warnings: list[str]
) -> tuple[_TaskFragment | None, bool]:
    key = item["key"]
    try:
        raw = item["path"].read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(raw)
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        warnings.append(f"{item['path']}: {exc}")
        return None, False

    state, successor = _lifecycle(key, metadata)
    if state != item["state"]:
        return None, False

    label = ""
    if state == "closed":
        text = f"Historical lead (closed). `{key}` closed by `{successor}`."
        if estimate_tokens(text) > cap:
            return None, True
        return _TaskFragment(key, _format_fragment(key, text), state), True

    if state == "historical":
        label = "Historical lead (stale). Verify before applying.\n\n"
    elif predecessor := item.get("predecessor"):
        label = f"Successor to `{predecessor}`.\n\n"

    text = label + raw.strip()
    if estimate_tokens(text) <= cap:
        return _TaskFragment(key, _format_fragment(key, text), state), True

    # Account for the source line before choosing how much of the passage fits.
    first_line = raw[: len(raw) - len(body)].count("\n")
    char_limit = 3 * cap + 2
    number, passage = query_passage(body, terms, char_limit, reference=item["reference"])
    source = f"{label}Source: `{key}`, line {first_line + number}.\n\n"
    if len(passage) + len(source) > char_limit:
        _, passage = query_passage(
            body, terms, char_limit - len(source), reference=item["reference"]
        )
    if not passage:
        return None, True
    text = source + passage
    return _TaskFragment(key, _format_fragment(key, text), state, excerpt=True), True
