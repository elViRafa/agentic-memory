"""Contradiction detection over the memory store.

Deterministic first (numeric disagreement, polarity on a shared identifier,
explicit reversal of a named decision). LLM-assisted when a provider is
already in play for a deep dream. Conflicts are surfaced for review —
never silently resolved or deleted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.storage._shared import (
    _is_generated_file,
    _is_ignored_local_memory_path,
    _iter_markdown_files,
    _jaccard_similar,
    _path_to_store_path,
)

# Cap the O(n^2) pair scan. Advisory, not an index.
_SCAN_LIMIT = 150
_MAX_HITS = 50
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_IDENT_RE = re.compile(
    r"\b("
    r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+"
    r"|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"
    r"|[A-Z][a-z0-9]+(?:[A-Z][a-zA-Z0-9]+)+"
    r"|[A-Z]{2,6}"
    r")\b"
)
_STOP_IDENTS = frozenset(
    {
        "AND",
        "THE",
        "FOR",
        "NOT",
        "YES",
        "ALL",
        "ANY",
        "BUT",
        "CAN",
        "MAY",
        "API",
        "URL",
        "URI",
        "HTTP",
        "JSON",
        "YAML",
        "HTML",
        "CSS",
        "SQL",
        "CLI",
        "MCP",
        "TTL",
        "UTC",
        "ADR",
        "PRD",
        "RFC",
        "UUID",
        "GIT",
        "TODO",
        "NOTE",
        "FIXME",
    }
)
_NEG_RE = re.compile(
    r"\b(?:"
    r"do\s+not|don't|does\s+not|must\s+not|no\s+longer|never|"
    r"avoid|deprecated?|removed?|reverted?|revers(?:e|es|ed|al)|"
    r"superseded?|instead\s+of|without|disabled?|dropped?|"
    r"banned?|forbidden|withdrawn|not\s+(?:use|add|enable)|"
    r"do\s+not\s+(?:use|add|enable)"
    r")\b",
    re.IGNORECASE,
)
_POS_RE = re.compile(
    r"\b(?:"
    r"use|uses|using|add|adds|added|adding|enable|enabled|must|always|"
    r"require|required|adopt|keep|introduce|implement|chose|choose|chosen"
    r")\b",
    re.IGNORECASE,
)
_REVERSAL_RE = re.compile(
    r"(?:revers(?:e|es|ed|al)|supersed(?:e|es|ed)|retract(?:s|ed)|rolls?\s+back)\s+"
    r"(?:of\s+)?"
    r"(?:(?:PRD|ADR|RFC|decision)\s*)?#?\s*"
    r"(?P<ref>\d{2,}|\w[\w-]{2,})",
    re.IGNORECASE,
)
_SKIP_TOP = frozenset({"episodic", "failures"})
ContradictionKind = Literal["numeric", "polarity", "reversal", "llm"]


@dataclass(frozen=True)
class Contradiction:
    store_path_a: str
    store_path_b: str
    kind: ContradictionKind
    message: str
    evidence: str = ""


@dataclass
class _Entry:
    store_path: str
    title: str
    body: str
    numbers: frozenset[str]
    idents: dict[str, str]  # ident.casefold() -> polarity ("pos" | "neg" | "")


def detect_contradictions(memory_root: Path) -> list[Contradiction]:
    """Scan ``memory_root`` and return advisory contradiction records.

    ``memory_root`` is a `.ai-memory/` directory (live or candidate).
    """
    entries = _load_entries(memory_root)
    hits: list[Contradiction] = []
    hits.extend(_detect_numeric(entries))
    hits.extend(_detect_polarity(entries))
    hits.extend(_detect_reversals(entries))
    return _dedupe(hits)[:_MAX_HITS]


def format_contradiction(hit: Contradiction) -> str:
    return hit.message


def detect_contradiction_messages(memory_root: Path) -> list[str]:
    return [format_contradiction(hit) for hit in detect_contradictions(memory_root)]


async def enrich_contradictions_with_llm(
    memory_root: Path,
    existing_messages: list[str],
    call_llm: Any,
    context: Any = None,
) -> list[str]:
    """Ask the already-configured LLM about overlapping pairs the net missed.

    Defensive: any parse/provider failure returns ``existing_messages`` unchanged.
    Callers must pass the same ``call_llm`` the dream path is already using so
    tests that mock it keep covering this branch.
    """
    pairs = _unresolved_overlap_pairs(memory_root, existing_messages)
    if not pairs:
        return list(existing_messages)
    prompt = _llm_contradiction_prompt(pairs)
    try:
        raw = await call_llm(
            prompt,
            "You detect contradictions between project-memory files. "
            "Return JSON only. Do not pick a winner.",
            context,
        )
    except Exception:  # noqa: BLE001 - advisory enrichment must never fail a dream.
        return list(existing_messages)
    extra = _parse_llm_contradictions(raw)
    merged = list(existing_messages)
    for item in extra:
        if item and item not in merged:
            merged.append(item)
    return merged


def _load_entries(memory_root: Path) -> list[_Entry]:
    store_root = memory_root / "memory-store"
    if not store_root.is_dir():
        return []
    entries: list[_Entry] = []
    for path in sorted(_iter_markdown_files(store_root)):
        if path.name == "index.md" or _is_generated_file(path):
            continue
        if _is_ignored_local_memory_path(memory_root, path):
            continue
        relative = path.relative_to(store_root)
        if relative.parts and relative.parts[0] in _SKIP_TOP:
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        if not body.strip():
            continue
        store_path = _path_to_store_path(store_root, path)
        title = str(metadata.get("title") or path.stem)
        entries.append(
            _Entry(
                store_path=store_path,
                title=title,
                body=body,
                numbers=frozenset(_NUMBER_RE.findall(body)),
                idents=_ident_polarities(body),
            )
        )
        if len(entries) >= _SCAN_LIMIT:
            break
    return entries


def _ident_polarities(body: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _IDENT_RE.finditer(body):
        raw = match.group(1)
        if raw.upper() in _STOP_IDENTS:
            continue
        key = raw.casefold()
        polarity = _window_polarity(body, match.start(), match.end())
        # Prefer negation when the same ident appears with both polarities.
        if key in found and found[key] == "neg":
            continue
        if polarity:
            found[key] = polarity
        elif key not in found:
            found[key] = ""
    return found


def _window_polarity(body: str, start: int, end: int) -> str:
    window = body[max(0, start - 80) : min(len(body), end + 80)]
    if _NEG_RE.search(window):
        return "neg"
    if _POS_RE.search(window):
        return "pos"
    return ""


def _detect_numeric(entries: list[_Entry]) -> list[Contradiction]:
    hits: list[Contradiction] = []
    for i, a in enumerate(entries):
        if not a.numbers:
            continue
        for b in entries[i + 1 :]:
            if not b.numbers or a.numbers == b.numbers:
                continue
            if not _jaccard_similar(a.body, b.body, threshold=0.3):
                continue
            only_a = " / ".join(sorted(a.numbers - b.numbers)[:3]) or "-"
            only_b = " / ".join(sorted(b.numbers - a.numbers)[:3]) or "-"
            hits.append(
                Contradiction(
                    store_path_a=a.store_path,
                    store_path_b=b.store_path,
                    kind="numeric",
                    message=(
                        f"`{a.store_path}` and `{b.store_path}` cover similar content "
                        f"but state different numbers ({only_a} vs {only_b}) "
                        "- review for conflict [heuristic]"
                    ),
                    evidence=f"{only_a} vs {only_b}",
                )
            )
    return hits


def _detect_polarity(entries: list[_Entry]) -> list[Contradiction]:
    hits: list[Contradiction] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            shared = set(a.idents) & set(b.idents)
            for ident in sorted(shared):
                pol_a = a.idents[ident]
                pol_b = b.idents[ident]
                if pol_a not in {"pos", "neg"} or pol_b not in {"pos", "neg"}:
                    continue
                if pol_a == pol_b:
                    continue
                pair = (a.store_path, b.store_path, ident)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                hits.append(
                    Contradiction(
                        store_path_a=a.store_path,
                        store_path_b=b.store_path,
                        kind="polarity",
                        message=(
                            f"`{a.store_path}` and `{b.store_path}` disagree about "
                            f"`{ident}` ({pol_a} vs {pol_b}) - review for conflict [polarity]"
                        ),
                        evidence=ident,
                    )
                )
    return hits


def _detect_reversals(entries: list[_Entry]) -> list[Contradiction]:
    hits: list[Contradiction] = []
    for later in entries:
        blob = f"{later.title}\n{later.body}"
        for match in _REVERSAL_RE.finditer(blob):
            ref = match.group("ref")
            for earlier in entries:
                if earlier.store_path == later.store_path:
                    continue
                if not _mentions_decision_ref(earlier, ref):
                    continue
                hits.append(
                    Contradiction(
                        store_path_a=earlier.store_path,
                        store_path_b=later.store_path,
                        kind="reversal",
                        message=(
                            f"`{later.store_path}` reverses `{earlier.store_path}` "
                            f"({ref}) - review for conflict [reversal]"
                        ),
                        evidence=ref,
                    )
                )
    return hits


def _mentions_decision_ref(entry: _Entry, ref: str) -> bool:
    if ref.isdigit():
        pat = re.compile(rf"\b(?:prd|adr|rfc)[\s_-]*{re.escape(ref)}\b", re.IGNORECASE)
        if pat.search(f"{entry.title}\n{entry.body}"):
            return True
        slug = entry.store_path.rsplit("/", 1)[-1]
        return ref in slug
    needle = ref.casefold()
    return needle in entry.store_path.casefold() or needle in entry.title.casefold()


def _dedupe(hits: list[Contradiction]) -> list[Contradiction]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[Contradiction] = []
    for hit in hits:
        key = (
            min(hit.store_path_a, hit.store_path_b),
            max(hit.store_path_a, hit.store_path_b),
            hit.kind,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _unresolved_overlap_pairs(
    memory_root: Path, existing_messages: list[str]
) -> list[tuple[_Entry, _Entry]]:
    entries = _load_entries(memory_root)
    already = " ".join(existing_messages)
    pairs: list[tuple[_Entry, _Entry]] = []
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            if a.store_path in already and b.store_path in already:
                continue
            if not _jaccard_similar(a.body, b.body, threshold=0.3):
                continue
            pairs.append((a, b))
            if len(pairs) >= 6:
                return pairs
    return pairs


def _llm_contradiction_prompt(pairs: list[tuple[_Entry, _Entry]]) -> str:
    blocks = []
    for a, b in pairs:
        blocks.append(f"A `{a.store_path}`:\n{a.body[:400]}\n\nB `{b.store_path}`:\n{b.body[:400]}")
    joined = "\n\n---\n\n".join(blocks)
    return (
        "Compare each pair of project-memory excerpts. List only real contradictions "
        "(opposing decisions, reversed requirements, incompatible numbers). "
        "Do not choose a winner and do not invent conflicts.\n\n"
        f"{joined}\n\n"
        'Return JSON: {"contradictions": ["`path-a` and `path-b`: description [llm]", ...]}'
    )


def _parse_llm_contradictions(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        import json

        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = data.get("contradictions") or []
    else:
        return []
    out: list[str] = []
    for item in values:
        if isinstance(item, str) and item.strip():
            msg = item.strip()
            if "[llm]" not in msg:
                msg = f"{msg} [llm]"
            out.append(msg)
    return out
