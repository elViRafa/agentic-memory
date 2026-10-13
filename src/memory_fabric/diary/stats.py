"""Build PackStats from a finished context bundle — no warning-string scraping
beyond a closed code map, and no user slugs in the result."""

from __future__ import annotations

import re
from typing import Any

from memory_fabric.contracts import ContextBundle, PackStats
from memory_fabric.diary.roles import classify_priority, classify_role
from memory_fabric.storage._shared import estimate_tokens

_FRAGMENT_KEY = re.compile(r"^<!-- memory-fabric:([^ ]+) -->")

_WARNING_CODE_MARKERS: tuple[tuple[str, str], ...] = (
    ("skipped full startup", "startup_skipped"),
    ("already delivered", "startup_skipped"),
    ("always-on steering", "steering_over_half"),
    ("share cap", "file_share_capped"),
    ("truncated `", "file_share_capped"),
)


def tokens_by_key_from_fragments(fragments: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for fragment in fragments:
        match = _FRAGMENT_KEY.match(fragment.lstrip())
        if not match:
            continue
        key = match.group(1)
        if key == "omission-notice":
            continue
        out[key] = estimate_tokens(fragment)
    return out


def warning_codes(warnings: list[str]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        lowered = warning.lower()
        for marker, code in _WARNING_CODE_MARKERS:
            if marker in lowered and code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def build_pack_stats(
    *,
    included: list[str],
    omitted: list[str],
    token_budget: int,
    estimated_tokens: int,
    warnings: list[str],
    tokens_by_key: dict[str, int] | None = None,
    priority_by_key: dict[str, str] | None = None,
    startup_mode: str,
    index_used: bool,
    query_present: bool,
    query_len: int,
) -> PackStats:
    tokens_by_key = tokens_by_key or {}
    priority_by_key = priority_by_key or {}
    tokens_by_role: dict[str, int] = {}
    included_by_role: dict[str, int] = {}
    omitted_by_role: dict[str, int] = {}
    included_by_priority: dict[str, int] = {}
    omitted_by_priority: dict[str, int] = {}

    largest_tokens = 0
    largest_role: str | None = None
    truncated_n = 0
    codes = warning_codes(warnings)
    if "file_share_capped" in codes:
        truncated_n = sum(1 for w in warnings if "truncated" in w.lower())

    for key in included:
        role = classify_role(key)
        included_by_role[role] = included_by_role.get(role, 0) + 1
        tok = int(tokens_by_key.get(key, 0))
        tokens_by_role[role] = tokens_by_role.get(role, 0) + tok
        if tok > largest_tokens:
            largest_tokens = tok
            largest_role = role
        pri = classify_priority(priority_by_key.get(key))
        included_by_priority[pri] = included_by_priority.get(pri, 0) + 1

    for key in omitted:
        role = classify_role(key)
        omitted_by_role[role] = omitted_by_role.get(role, 0) + 1
        pri = classify_priority(priority_by_key.get(key))
        omitted_by_priority[pri] = omitted_by_priority.get(pri, 0) + 1

    budget_fit = estimated_tokens <= token_budget
    if not budget_fit and "budget_exhausted" not in codes:
        codes.append("budget_exhausted")
    if startup_mode == "skipped" and "startup_skipped" not in codes:
        codes.append("startup_skipped")
    if not index_used and startup_mode in {"full"} and "index_fallback_scan" not in codes:
        codes.append("index_fallback_scan")

    return {
        "token_budget": token_budget,
        "estimated_tokens": estimated_tokens,
        "budget_fit": budget_fit,
        "startup_mode": startup_mode,
        "index_used": index_used,
        "query_present": query_present,
        "query_len": query_len,
        "tokens_by_role": tokens_by_role,
        "included_by_role": included_by_role,
        "omitted_by_role": omitted_by_role,
        "included_by_priority": included_by_priority,
        "omitted_by_priority": omitted_by_priority,
        "largest_included_tokens": largest_tokens,
        "largest_included_role": largest_role,
        "truncated_n": truncated_n,
        "warning_codes": codes,
    }


def attach_pack_stats(
    bundle: ContextBundle,
    *,
    tokens_by_key: dict[str, int] | None = None,
    priority_by_key: dict[str, str] | None = None,
    startup_mode: str,
    index_used: bool,
    query: str | None,
    fragments: list[str] | None = None,
) -> ContextBundle:
    if tokens_by_key is None and fragments:
        tokens_by_key = tokens_by_key_from_fragments(fragments)
    stats = build_pack_stats(
        included=list(bundle.get("included_sections") or []),
        omitted=list(bundle.get("omitted_sections") or []),
        token_budget=int(bundle.get("token_budget") or 0),
        estimated_tokens=int(bundle.get("estimated_tokens") or 0),
        warnings=list(bundle.get("warnings") or []),
        tokens_by_key=tokens_by_key,
        priority_by_key=priority_by_key,
        startup_mode=startup_mode,
        index_used=index_used,
        query_present=bool(query),
        query_len=len(query or ""),
    )
    updated: dict[str, Any] = dict(bundle)
    updated["pack_stats"] = stats
    return updated  # type: ignore[return-value]
