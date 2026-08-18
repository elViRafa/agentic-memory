"""Shared relevance ranking for context assembly and keyword search.

Okapi BM25 over Unicode-aware tokens, blended with priority and recency.
One ranker serves both ``read_combined_context`` and ``keyword_search`` so
the two relevance systems cannot disagree.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

PRIORITY_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}
K1 = 1.2
B = 0.75
RECENCY_HALF_LIFE_DAYS = 90.0
RECENCY_FLOOR = 0.3

# Passive per-commit captures are raw material for dreaming, not answers.
_COMMITS_MARKERS = ("/episodic/commits/", "episodic/commits/")


def tokenize(text: str) -> list[str]:
    """Unicode-aware tokens: NFKD, casefold, ``\\w+``.

    Accented languages (Portuguese ``seção``, ``importação``) survive as
    base letters so they rank at all — the same defect class as ASCII slugs.
    """
    if not text:
        return []
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch)).casefold()
    return _TOKEN_RE.findall(stripped)


def slugify(text: str, max_chars: int = 60) -> str:
    """NFKD-transliterate then keep ``a-z0-9-``, matching store-path charset.

    ``seção de importação`` → ``secao-de-importacao`` (not ``se-o-de-importa-o``).
    """
    nfkd = unicodedata.normalize("NFKD", text.strip())
    ascii_text = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")
    if max_chars > 0:
        slug = slug[:max_chars].rstrip("-")
    return slug


def priority_weight(priority: str | None) -> float:
    return PRIORITY_WEIGHTS.get((priority or "medium").strip().lower(), 0.6)


def recency_weight(
    last_updated: str | None, *, half_life_days: float = RECENCY_HALF_LIFE_DAYS
) -> float:
    """Exponential decay on ``last_updated``. Missing/unparseable dates are neutral."""
    if not last_updated:
        return 0.5
    try:
        dt = datetime.fromisoformat(str(last_updated).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        age_days = max(
            0.0,
            (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds() / 86400.0,
        )
        if half_life_days <= 0:
            return 1.0
        decay = RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * math.exp(
            -age_days * math.log(2) / half_life_days
        )
        return decay
    except (ValueError, TypeError, OverflowError):
        return 0.5


def is_commit_capture(key: str) -> bool:
    """True for per-commit episodic captures (``episodic/commits/**``)."""
    normalized = key.replace("\\", "/")
    return any(marker in normalized for marker in _COMMITS_MARKERS)


def category_penalty(key: str) -> float:
    """Deprioritize per-commit captures below every other category."""
    return 0.05 if is_commit_capture(key) else 1.0


def bm25_scores(
    query_tokens: Sequence[str],
    documents: Sequence[Sequence[str]],
    *,
    k1: float = K1,
    b: float = B,
) -> list[float]:
    """Okapi BM25 scores for each document. IDF is computed from *documents*."""
    n = len(documents)
    if n == 0:
        return []
    if not query_tokens:
        return [0.0] * n

    unique_q = list(dict.fromkeys(query_tokens))
    df: dict[str, int] = dict.fromkeys(unique_q, 0)
    for tokens in documents:
        seen = set(tokens)
        for term in unique_q:
            if term in seen:
                df[term] += 1

    avgdl = sum(len(doc) for doc in documents) / n
    scores: list[float] = []
    for tokens in documents:
        tf: dict[str, int] = {}
        for term in tokens:
            tf[term] = tf.get(term, 0) + 1
        dl = len(tokens) or 1
        score = 0.0
        for term in unique_q:
            n_q = df.get(term, 0)
            if n_q == 0:
                continue
            # Plus-1 RSJ IDF so a term that appears in every doc still scores.
            idf = math.log((n - n_q + 0.5) / (n_q + 0.5) + 1.0)
            freq = tf.get(term, 0)
            denom = freq + k1 * (1.0 - b + b * dl / (avgdl or 1.0))
            if denom:
                score += idf * (freq * (k1 + 1.0)) / denom
        scores.append(score)
    return scores


def blended_score(
    bm25: float,
    priority: str | None,
    last_updated: str | None,
    *,
    key: str = "",
) -> float:
    """``bm25 * priority_weight * recency_weight * category_penalty``."""
    raw = bm25 if bm25 > 0 else 0.0
    # No-query / zero-BM25 still needs a priority*recency order so a high
    # architecture map outranks a low resolved-debt entry.
    base = raw if raw > 0 else 1.0
    return base * priority_weight(priority) * recency_weight(last_updated) * category_penalty(key)


def token_jaccard(a: str, b: str, *, min_tokens: int = 2) -> float:
    """Jaccard overlap of Unicode tokens. Used as failure-signature fallback."""
    words_a = set(tokenize(a))
    words_b = set(tokenize(b))
    if len(words_a) < min_tokens or len(words_b) < min_tokens:
        return 0.0
    union = words_a | words_b
    if not union:
        return 0.0
    return len(words_a & words_b) / len(union)
