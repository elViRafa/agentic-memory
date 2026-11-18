"""Contradiction detection over the memory store.

Deterministic first (numeric disagreement, polarity on a shared rare word,
explicit reversal / lexical replacement of a named decision). LLM-assisted
when a provider is already in play for a deep dream. Conflicts are surfaced
for review — never silently resolved or deleted.

Field stores (search-sermons scale) showed whole-file digit bags and
folder-as-topic drowning the pack. Claim-level comparison, IDF gates, an
inverted-index candidate walk, and a per-category scan keep doctor/dream
fast while still reaching every top-level folder.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
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
from memory_fabric.storage.ranking import tokenize

# Cap files loaded per top-level category (not a global alphabetical stop).
_SCAN_LIMIT = 150
# Deep claim-pair comparisons per category: same cost as a 150-file pair walk.
_PAIR_BUDGET = _SCAN_LIMIT * (_SCAN_LIMIT - 1) // 2
_MAX_HITS = 50
_PACK_MAX = 5
_PACK_TOKEN_MAX = 150
_GENERIC_IDENT_FRAC = 0.25
_SAME_TOPIC_JACCARD = 0.25
_NUMERIC_BUCKET_CAP = 32
_POLARITY_POSTING_CAP = 24
# Decimals allow 1–2 fractional digits (0.46 / 0,46). Longer comma groups
# like ``147,163`` are two integers (line cites), not one decimal.
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.,]\d{1,2})?(?!\d)")
_HEX_RE = re.compile(r"^[0-9a-f]{7,}$", re.IGNORECASE)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
_UNIT_RE = re.compile(
    r"^(?:%|ms|s|sec|secs|second|seconds|min|mins|minute|minutes|"
    r"h|hr|hrs|hour|hours|gb|gib|mb|mib|kb|kib|b|bytes)$",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_BULLET_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_IDENT_RE = re.compile(
    r"\b("
    r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+"
    r"|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"
    r"|[A-Z][a-z0-9]+(?:[A-Z][a-zA-Z0-9]+)+"
    r"|[A-Z]{2,6}"
    r")\b"
)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "to",
        "for",
        "and",
        "or",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "not",
        "no",
        "do",
        "does",
        "did",
        "we",
        "our",
        "you",
        "your",
        "they",
        "their",
        "de",
        "da",
        "do",
        "dos",
        "das",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "para",
        "por",
        "com",
        "sem",
        "um",
        "uma",
        "que",
        "se",
        "os",
        "as",
        "o",
        "e",
        "ou",
        "ao",
        "aos",
        "vs",
        "via",
        "per",
        # Polarity cue lemmas — never polarity *evidence*.
        "use",
        "uses",
        "using",
        "usar",
        "usa",
        "add",
        "adds",
        "added",
        "adding",
        "enable",
        "enabled",
        "must",
        "always",
        "require",
        "required",
        "adopt",
        "keep",
        "introduce",
        "implement",
        "chose",
        "choose",
        "chosen",
        "deve",
        "sempre",
        "obrigatorio",
        "avoid",
        "never",
        "deprecated",
        "removed",
        "reverted",
        "without",
        "disabled",
        "dropped",
        "banned",
        "forbidden",
        "withdrawn",
        "nunca",
        "jamais",
        "evite",
        "proibido",
        "nao",
    }
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
    r"do\s+not\s+(?:use|add|enable)|"
    r"n[aã]o|nunca|jamais|evite|proibido|sem"
    r")\b",
    re.IGNORECASE,
)
_POS_RE = re.compile(
    r"\b(?:"
    r"use|uses|using|add|adds|added|adding|enable|enabled|must|always|"
    r"require|required|adopt|keep|introduce|implement|chose|choose|chosen|"
    r"usar|usa|deve|sempre|obrigat[oó]rio|obrigatorio"
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
_REPLACEMENT_RE = re.compile(
    r"(?:"
    r"superseded\s+pointer|"
    r"superseded\s+by|supersedes|replaced\s+by|no\s+longer\s+use|"
    r"substitu[ií]do\s+por|n[aã]o\s+usar\s+mais"
    r")",
    re.IGNORECASE,
)
_STORE_PATH_RE = re.compile(
    r"\b([a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)+)\b",
    re.IGNORECASE,
)
_NEXT_STEP_RE = re.compile(
    r"^(?:next|pr[oó]ximo)\s*:\s*(.+)$",
    re.IGNORECASE,
)
# Normalize successive wave/version tokens so s2 vs s3 is evolution, not conflict.
_VERSION_TOKEN_RE = re.compile(
    r"(?:^|[-_/])(?:s|v|wave|phase|step|epoch|round)[-_]?\d+(?=$|[-_/])",
    re.IGNORECASE,
)
_SKIP_TOP = frozenset({"episodic", "failures"})
_KIND_RANK = {"reversal": 0, "numeric": 1, "replacement": 2, "llm": 3, "polarity": 4}
ContradictionKind = Literal["numeric", "polarity", "reversal", "replacement", "llm"]


@dataclass(frozen=True)
class Contradiction:
    store_path_a: str
    store_path_b: str
    kind: ContradictionKind
    message: str
    evidence: str = ""


@dataclass(frozen=True)
class _Quantity:
    head: str
    quantity: str
    unit: str
    raw: str


@dataclass
class _Claim:
    text: str
    store_path: str
    title: str
    tokens: frozenset[str]
    polarity: str  # "pos" | "neg" | ""
    quantities: tuple[_Quantity, ...]
    content_words: frozenset[str]


@dataclass
class _Entry:
    store_path: str
    title: str
    body: str
    claims: list[_Claim] = field(default_factory=list)


def detect_contradictions(memory_root: Path) -> list[Contradiction]:
    """Scan ``memory_root`` and return advisory contradiction records.

    ``memory_root`` is a `.ai-memory/` directory (live or candidate).
    """
    entries = _load_entries(memory_root)
    if not entries:
        return []
    generic = _generic_tokens(entries)
    hits: list[Contradiction] = []
    hits.extend(_detect_numeric(entries, generic))
    hits.extend(_detect_polarity(entries, generic))
    hits.extend(_detect_reversals(entries))
    hits.extend(_detect_replacements(entries))
    hits.extend(_detect_intra_file_next_steps(entries))
    return _dedupe(hits)[:_MAX_HITS]


def format_contradiction(hit: Contradiction) -> str:
    return hit.message


def detect_contradiction_messages(memory_root: Path) -> list[str]:
    return [format_contradiction(hit) for hit in detect_contradictions(memory_root)]


def select_pack_contradictions(
    hits: list[Contradiction], max_n: int = _PACK_MAX
) -> list[Contradiction]:
    """Top-N hits for ``index.md`` frontmatter (reversal > numeric > replacement > polarity)."""
    if max_n <= 0:
        return []
    ranked = sorted(
        hits,
        key=lambda h: (_KIND_RANK.get(h.kind, 9), h.message),
    )
    return ranked[:max_n]


def contradiction_pack_tokens(messages: list[str]) -> int:
    """Token estimate used by eval's contradiction pack cap (chars // 4)."""
    return sum(max(1, len(str(item)) // 4) for item in messages)


def _trim_pack_messages(messages: list[str], *, max_n: int, max_tokens: int) -> list[str]:
    """Drop or shorten strings until the pack fits the eval count and token caps."""
    fitted = [text for text in (str(item).strip() for item in messages) if text][:max_n]
    while fitted and (len(fitted) > 8 or contradiction_pack_tokens(fitted) > max_tokens):
        longest_i = max(range(len(fitted)), key=lambda i: len(fitted[i]))
        item = fitted[longest_i]
        over = contradiction_pack_tokens(fitted) - max_tokens
        if over <= 0 or len(fitted) > 8:
            fitted.pop(longest_i)
            continue
        new_len = len(item) - (over * 4 + 4)
        if new_len < 12:
            fitted.pop(longest_i)
            continue
        fitted[longest_i] = item[:new_len].rstrip()
    return fitted


def pack_contradiction_messages(
    hits: list[Contradiction],
    llm_messages: list[str] | None = None,
    max_n: int = _PACK_MAX,
    max_tokens: int = _PACK_TOKEN_MAX,
) -> tuple[list[str], int]:
    """Return ``(messages_for_index_frontmatter, total_hit_count)``.

    LLM strings that are not already covered by a deterministic hit can fill
    remaining pack slots. Full hit count includes deterministic hits only;
    LLM extras are advisory add-ons for the pack list. The returned messages
    stay under both the entry cap and the eval token cap.
    """
    selected = select_pack_contradictions(hits, max_n=max_n)
    messages = [format_contradiction(h) for h in selected]
    total = len(hits)
    if llm_messages and len(messages) < max_n:
        for raw in llm_messages:
            text = str(raw or "").strip()
            if not text or text in messages:
                continue
            messages.append(text)
            if len(messages) >= max_n:
                break
    return _trim_pack_messages(messages, max_n=max_n, max_tokens=max_tokens), total


def write_contradiction_report(
    memory_root: Path,
    hits: list[Contradiction],
    llm_messages: list[str] | None = None,
) -> Path | None:
    """Write the full advisory list to gitignored ``evals/contradictions.json``."""
    evals = memory_root / "evals"
    try:
        evals.mkdir(parents=True, exist_ok=True)
        payload = {
            "count": len(hits),
            "pack_max": _PACK_MAX,
            "hits": [
                {
                    "store_path_a": h.store_path_a,
                    "store_path_b": h.store_path_b,
                    "kind": h.kind,
                    "message": h.message,
                    "evidence": h.evidence,
                }
                for h in hits
            ],
            "llm_messages": [str(m) for m in (llm_messages or []) if str(m).strip()],
        }
        path = evals / "contradictions.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path
    except OSError:
        return None


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
    per_category: Counter[str] = Counter()
    for path in sorted(_iter_markdown_files(store_root)):
        if path.name == "index.md" or _is_generated_file(path):
            continue
        if _is_ignored_local_memory_path(memory_root, path):
            continue
        relative = path.relative_to(store_root)
        if relative.parts and relative.parts[0] in _SKIP_TOP:
            continue
        top = relative.parts[0].casefold() if relative.parts else ""
        if per_category[top] >= _SCAN_LIMIT:
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        if not body.strip():
            continue
        store_path = _path_to_store_path(store_root, path)
        title = str(metadata.get("title") or path.stem)
        claims = _split_claims(body, store_path=store_path, title=title)
        if not claims:
            continue
        entries.append(_Entry(store_path=store_path, title=title, body=body, claims=claims))
        per_category[top] += 1
    return entries


def _split_claims(body: str, *, store_path: str, title: str) -> list[_Claim]:
    text = _FENCE_RE.sub(" ", body)
    claims: list[_Claim] = []
    heading = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            continue
        line = _BULLET_RE.sub("", line)
        pieces = [p.strip() for p in _SENTENCE_SPLIT_RE.split(line) if p.strip()]
        for piece in pieces:
            claim_text = f"{heading}: {piece}" if heading else piece
            claim = _build_claim(claim_text, store_path=store_path, title=title)
            if claim is not None:
                claims.append(claim)
    return claims


def _build_claim(text: str, *, store_path: str, title: str) -> _Claim | None:
    tokens = tokenize(text)
    if not tokens:
        return None
    polarity = _claim_polarity(text)
    quantities = tuple(_extract_quantities(text))
    content_words = frozenset(
        tok
        for tok in tokens
        if len(tok) > 2
        and tok not in _STOP_WORDS
        and not _NUMBER_TOKEN_RE.fullmatch(tok)
        and tok.upper() not in _STOP_IDENTS
    )
    # Also attach CamelCase / snake_case idents so polarity on DRF still works.
    for match in _IDENT_RE.finditer(text):
        raw = match.group(1)
        if raw.upper() in _STOP_IDENTS:
            continue
        key = raw.casefold()
        if len(key) < 3:
            continue
        content_words = content_words | {key}
    return _Claim(
        text=text,
        store_path=store_path,
        title=title,
        tokens=frozenset(tokens),
        polarity=polarity,
        quantities=quantities,
        content_words=content_words,
    )


def _claim_polarity(text: str) -> str:
    has_neg = bool(_NEG_RE.search(text))
    has_pos = bool(_POS_RE.search(text))
    if has_neg:
        return "neg"
    if has_pos:
        return "pos"
    return ""


def _extract_quantities(text: str) -> list[_Quantity]:
    """Pull ``(head, quantity, unit)`` triples from a claim.

    Quantity regex runs on the raw claim so ``0.46`` / ``0,46`` stay one value.
    Head is the nearest content token before the number.
    """
    found: list[_Quantity] = []
    for match in _NUMBER_TOKEN_RE.finditer(text):
        raw = match.group(0)
        if _YEAR_RE.fullmatch(raw) or _HEX_RE.fullmatch(raw):
            continue
        # Map the match onto the tokenized stream to find the head.
        before = text[: match.start()]
        before_tokens = tokenize(before)
        head = ""
        for prev in reversed(before_tokens):
            if prev in _STOP_WORDS or _NUMBER_TOKEN_RE.fullmatch(prev):
                continue
            if len(prev) <= 1:
                continue
            head = prev
            break
        if not head:
            continue
        after = text[match.end() :]
        after_tokens = tokenize(after)
        unit = ""
        if after_tokens and _UNIT_RE.fullmatch(after_tokens[0]):
            unit = after_tokens[0].casefold()
        quantity = raw.replace(",", ".")
        # Integers with no unit are usually indexes, line cites, or counts — not
        # decision metrics. Keep decimals (refusal 0.46) and united values (3600 s).
        if not unit and "." not in quantity:
            continue
        found.append(_Quantity(head=head, quantity=quantity, unit=unit, raw=raw))
    return found


def _generic_tokens(entries: list[_Entry]) -> frozenset[str]:
    """Content words that appear in enough files to be vocabulary, not a decision."""
    if len(entries) < 4:
        return frozenset()
    counts: Counter[str] = Counter()
    for entry in entries:
        words: set[str] = set()
        for claim in entry.claims:
            words.update(claim.content_words)
        for word in words:
            counts[word] += 1
    threshold = max(2, int(len(entries) * _GENERIC_IDENT_FRAC + 0.999))
    return frozenset(word for word, n in counts.items() if n >= threshold)


def _top_level_prefix(store_path: str) -> str:
    parts = [p for p in store_path.replace("\\", "/").strip("/").split("/") if p]
    return parts[0].casefold() if parts else ""


def _same_topic_claims(
    a: _Claim, b: _Claim, generic: frozenset[str], *, same_folder: bool
) -> bool:
    """Folder alone is not enough; require a rare shared token or claim Jaccard."""
    shared = (a.content_words & b.content_words) - generic
    if shared:
        return True
    if _jaccard_similar(a.text, b.text, threshold=_SAME_TOPIC_JACCARD):
        return True
    # Cross-folder pairs still need the overlap above; same_folder only filters
    # which candidates the index produces — never a sufficient gate by itself.
    _ = same_folder
    return False


def _normalize_versioned_path(store_path: str) -> str:
    text = store_path.replace("\\", "/").casefold()
    return _VERSION_TOKEN_RE.sub("-N", text)


def _successive_version_pair(a: str, b: str) -> bool:
    """True when paths differ only by wave/version tokens (s2 vs s3, v2 vs v3)."""
    na = _normalize_versioned_path(a)
    nb = _normalize_versioned_path(b)
    if na != nb:
        return False
    return a.replace("\\", "/").casefold() != b.replace("\\", "/").casefold()


def _bugs_vs_other(a: str, b: str) -> bool:
    pa = _top_level_prefix(a)
    pb = _top_level_prefix(b)
    return (pa == "bugs") != (pb == "bugs") and (pa == "bugs" or pb == "bugs")


def _claim_index(entries: list[_Entry]) -> list[_Claim]:
    claims: list[_Claim] = []
    for entry in entries:
        claims.extend(entry.claims)
    return claims


def _detect_numeric(
    entries: list[_Entry], generic: frozenset[str]
) -> list[Contradiction]:
    claims = _claim_index(entries)
    buckets: dict[tuple[str, str], list[tuple[_Claim, _Quantity]]] = defaultdict(list)
    for claim in claims:
        for qty in claim.quantities:
            buckets[(qty.head, qty.unit)].append((claim, qty))

    hits: list[Contradiction] = []
    budgets: Counter[str] = Counter()
    for (head, unit), rows in buckets.items():
        head_is_generic = head in generic
        # Cap large generic buckets; rare heads stay fully comparable within the cap.
        if len(rows) > _NUMERIC_BUCKET_CAP:
            by_cat: dict[str, list[tuple[_Claim, _Quantity]]] = defaultdict(list)
            for row in rows:
                by_cat[_top_level_prefix(row[0].store_path)].append(row)
            groups = [group[:_NUMERIC_BUCKET_CAP] for group in by_cat.values()]
        else:
            groups = [rows]

        for group in groups:
            for i, (claim_a, qty_a) in enumerate(group):
                for claim_b, qty_b in group[i + 1 :]:
                    if claim_a.store_path == claim_b.store_path and claim_a.text == claim_b.text:
                        continue
                    if qty_a.quantity == qty_b.quantity:
                        continue
                    if _successive_version_pair(claim_a.store_path, claim_b.store_path):
                        continue
                    same_folder = _top_level_prefix(claim_a.store_path) == _top_level_prefix(
                        claim_b.store_path
                    )
                    # Shared rare head is itself a topic signal. Generic heads
                    # without a unit are index/noise ("note 3"); with a unit they
                    # still need claim Jaccard. Cross-folder rare heads need topic.
                    if head_is_generic:
                        if not unit:
                            continue
                        if not _jaccard_similar(
                            claim_a.text, claim_b.text, threshold=_SAME_TOPIC_JACCARD
                        ):
                            continue
                    elif not same_folder and not _same_topic_claims(
                        claim_a, claim_b, generic, same_folder=False
                    ):
                        continue
                    cat = _top_level_prefix(claim_a.store_path) or _top_level_prefix(
                        claim_b.store_path
                    )
                    if budgets[cat] >= _PAIR_BUDGET:
                        continue
                    budgets[cat] += 1
                    unit_note = f" {unit}" if unit else ""
                    hits.append(
                        Contradiction(
                            store_path_a=claim_a.store_path,
                            store_path_b=claim_b.store_path,
                            kind="numeric",
                            message=(
                                f"`{claim_a.store_path}` and `{claim_b.store_path}` "
                                f"disagree on `{head}` "
                                f"({qty_a.raw}{unit_note} vs {qty_b.raw}{unit_note}) "
                                "- review for conflict [heuristic]"
                            ),
                            evidence=f"{head}:{qty_a.raw} vs {qty_b.raw}",
                        )
                    )
    return hits


def _detect_polarity(
    entries: list[_Entry], generic: frozenset[str]
) -> list[Contradiction]:
    claims = _claim_index(entries)
    postings: dict[str, list[_Claim]] = defaultdict(list)
    for claim in claims:
        if claim.polarity not in {"pos", "neg"}:
            continue
        for word in claim.content_words:
            if word in generic:
                continue
            postings[word].append(claim)

    # Collect candidate (pair -> best word) so acronyms like DRF beat "django".
    best: dict[tuple[str, str], tuple[tuple[int, int, str], str, _Claim, _Claim]] = {}
    budgets: Counter[str] = Counter()
    for word in sorted(postings, key=_polarity_word_rank):
        rows = postings[word]
        if len(rows) < 2 or len(rows) > _POLARITY_POSTING_CAP:
            continue
        by_cat: dict[str, list[_Claim]] = defaultdict(list)
        for claim in rows:
            by_cat[_top_level_prefix(claim.store_path)].append(claim)
        groups: list[list[_Claim]] = list(by_cat.values())
        if len(by_cat) > 1 and len(rows) <= _POLARITY_POSTING_CAP:
            groups.append(rows)

        for group in groups:
            for i, claim_a in enumerate(group):
                for claim_b in group[i + 1 :]:
                    if claim_a.store_path == claim_b.store_path and claim_a.text == claim_b.text:
                        continue
                    if _bugs_vs_other(claim_a.store_path, claim_b.store_path):
                        continue
                    if claim_a.polarity == claim_b.polarity:
                        continue
                    if word not in claim_a.content_words or word not in claim_b.content_words:
                        continue
                    same_folder = _top_level_prefix(claim_a.store_path) == _top_level_prefix(
                        claim_b.store_path
                    )
                    if not _same_topic_claims(claim_a, claim_b, generic, same_folder=same_folder):
                        continue
                    # Rare shared vocabulary alone over-fires on words like ``llm``.
                    # Require claim overlap so Portuguese/English LoRA pairs still hit
                    # while unrelated decisions that merely mention the same stack do not.
                    if not _jaccard_similar(
                        claim_a.text, claim_b.text, threshold=_SAME_TOPIC_JACCARD
                    ):
                        continue
                    cat = _top_level_prefix(claim_a.store_path) or _top_level_prefix(
                        claim_b.store_path
                    )
                    pair_key = (
                        min(claim_a.store_path, claim_b.store_path),
                        max(claim_a.store_path, claim_b.store_path),
                    )
                    rank = _polarity_word_rank(word)
                    prev = best.get(pair_key)
                    if prev is not None and prev[0] <= rank:
                        continue
                    if prev is None:
                        if budgets[cat] >= _PAIR_BUDGET:
                            continue
                        budgets[cat] += 1
                    best[pair_key] = (rank, word, claim_a, claim_b)

    hits: list[Contradiction] = []
    for _pair, (_rank, word, claim_a, claim_b) in best.items():
        hits.append(
            Contradiction(
                store_path_a=claim_a.store_path,
                store_path_b=claim_b.store_path,
                kind="polarity",
                message=(
                    f"`{claim_a.store_path}` and `{claim_b.store_path}` disagree "
                    f"about `{word}` ({claim_a.polarity} vs {claim_b.polarity}) "
                    "- review for conflict [polarity]"
                ),
                evidence=word,
            )
        )
    return hits


def _polarity_word_rank(word: str) -> tuple[int, int, str]:
    """Prefer short acronyms / snake_case idents as polarity evidence."""
    if "_" in word:
        return (1, -len(word), word)
    if 2 <= len(word) <= 6:
        return (0, len(word), word)
    return (2, -len(word), word)


def _detect_reversals(entries: list[_Entry]) -> list[Contradiction]:
    hits: list[Contradiction] = []
    claims = _claim_index(entries)
    for later in claims:
        for match in _REVERSAL_RE.finditer(later.text):
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


def _detect_replacements(entries: list[_Entry]) -> list[Contradiction]:
    hits: list[Contradiction] = []
    known_paths = {entry.store_path.casefold() for entry in entries}
    for entry in entries:
        for claim in entry.claims:
            if not _REPLACEMENT_RE.search(claim.text):
                continue
            for match in _STORE_PATH_RE.finditer(claim.text):
                target = match.group(1).replace("\\", "/")
                # Skip the claiming file naming itself.
                if target.casefold() == entry.store_path.casefold():
                    continue
                # Prefer real store paths; still emit when the slug looks like one.
                if "/" not in target:
                    continue
                evidence = target
                if known_paths and target.casefold() not in known_paths:
                    # Still advisory — path may point at a live note not in the
                    # capped scan window, or at a handoff the writer named.
                    pass
                hits.append(
                    Contradiction(
                        store_path_a=entry.store_path,
                        store_path_b=target,
                        kind="replacement",
                        message=(
                            f"`{entry.store_path}` names `{target}` as a replacement "
                            "- review for conflict [replacement]"
                        ),
                        evidence=evidence,
                    )
                )
    return hits


_NEXT_STEP_SEARCH_RE = re.compile(
    r"(?:^|:\s*)(?:next|pr[oó]ximo)\s*:\s*(.+)$",
    re.IGNORECASE,
)


def _next_step_remainder(claim_text: str) -> str | None:
    """Return the remainder after a Next:/Próximo: cue, else None."""
    match = _NEXT_STEP_SEARCH_RE.search(claim_text.strip())
    if not match:
        match = _NEXT_STEP_RE.match(claim_text.strip())
    if not match:
        return None
    remainder = match.group(1).strip()
    return remainder or None


def _detect_intra_file_next_steps(entries: list[_Entry]) -> list[Contradiction]:
    """Flag successive 'Next:' / 'Próximo:' directives inside one posture file."""
    hits: list[Contradiction] = []
    for entry in entries:
        nexts = [
            rem.casefold()
            for claim in entry.claims
            if (rem := _next_step_remainder(claim.text)) is not None
        ]
        seen: set[str] = set()
        for i, rem_a in enumerate(nexts):
            for rem_b in nexts[i + 1 :]:
                if rem_a == rem_b:
                    continue
                key = "|".join(sorted((rem_a, rem_b)))
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    Contradiction(
                        store_path_a=entry.store_path,
                        store_path_b=entry.store_path,
                        kind="polarity",
                        message=(
                            f"`{entry.store_path}` lists successive next steps "
                            f"({rem_a} vs {rem_b}) - review for conflict [intra-file]"
                        ),
                        evidence=f"{rem_a} vs {rem_b}",
                    )
                )
    return hits


def _mentions_decision_ref(entry: _Entry, ref: str) -> bool:
    blob = f"{entry.title}\n{entry.body}"
    if ref.isdigit():
        pat = re.compile(rf"\b(?:prd|adr|rfc)[\s_-]*{re.escape(ref)}\b", re.IGNORECASE)
        if pat.search(blob):
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
    generic = _generic_tokens(entries)
    pairs: list[tuple[_Entry, _Entry]] = []
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            if a.store_path in already and b.store_path in already:
                continue
            # File-level topic: any claim pair that shares a rare token or Jaccard.
            related = False
            for ca in a.claims:
                for cb in b.claims:
                    same_folder = _top_level_prefix(a.store_path) == _top_level_prefix(
                        b.store_path
                    )
                    if _same_topic_claims(ca, cb, generic, same_folder=same_folder):
                        related = True
                        break
                if related:
                    break
            if not related:
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
