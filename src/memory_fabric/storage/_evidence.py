"""Shared eligibility and passage selection for search and task packs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from memory_fabric.storage.close import role_for_section_key
from memory_fabric.storage.ranking import review_status_penalty, tokenize

EvidenceState = Literal["current", "historical", "closed", "broken"]

# Function words only. Dropped before candidate generation so "the" / "de"
# do not pull every file. BM25 then ranks the remaining content tokens.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "from",
        "by",
        "at",
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
        "how",
        "what",
        "when",
        "where",
        "why",
        "who",
        "which",
        "does",
        "do",
        "did",
        "not",
        "no",
        "into",
        "about",
        "over",
        "under",
        "than",
        "then",
        "so",
        "if",
        "but",
        "we",
        "our",
        "you",
        "your",
        "can",
        "should",
        "would",
        "could",
        "o",
        "os",
        "um",
        "uma",
        "uns",
        "umas",
        "de",
        "da",
        "das",
        "dos",
        "e",
        "ou",
        "em",
        "na",
        "nos",
        "nas",
        "para",
        "por",
        "com",
        "que",
        "se",
        "ao",
        "aos",
        "como",
        "quando",
        "onde",
        "porque",
        "qual",
        "quais",
        "nao",
        "after",
        "before",
        "has",
        "have",
        "had",
        "may",
        "might",
        "must",
        "will",
        "me",
        "my",
        "he",
        "she",
        "they",
        "them",
        "their",
        "am",
        "all",
        "any",
        "sera",
        "foi",
        "era",
        "ser",
        "esta",
        "estao",
        "sao",
        "pode",
        "posso",
        "meu",
        "minha",
        "pelo",
        "pela",
        "pelos",
        "pelas",
        "isso",
        "isto",
        "esse",
        "essa",
        "este",
        "antes",
        "depois",
    }
)


def query_tokens(query: str) -> tuple[list[str], list[str]]:
    """Return ``(all folded tokens, content tokens)`` with stopwords removed."""
    tokens = tokenize(query)
    content = list(
        dict.fromkeys(token for token in tokens if token not in _STOPWORDS and len(token) >= 2)
    )
    return tokens, content


def identifiers(terms: list[str]) -> set[str]:
    return {term for term in terms if re.search(r"[^_]_[^_]", term)}


def topical_match(terms: list[str], exact: set[str], words: set[str], stem: str) -> bool:
    """Match an identifier as a unit, or require topical overlap for a question."""
    if exact:
        return bool(exact & words)
    overlap = words.intersection(terms)
    # A named topic in the filename also anchors a short or underspecified query.
    return bool(overlap) and (
        len(overlap) >= min(2, len(terms))
        or (len(terms) <= 3 and bool(overlap.intersection(tokenize(stem))))
    )


def evidence_state(key: str, review_status: str, successor: str, role: str) -> EvidenceState:
    if successor.strip():
        return "closed"
    if review_status.strip().lower() == "broken-evidence":
        return "broken"
    resolved_role = role_for_section_key(key, role=role)
    if not review_status_penalty(review_status, role=resolved_role):
        return "historical"
    return "current"


def current_successor(target: str, lifecycle: dict[str, tuple[EvidenceState, str]]) -> str:
    seen: set[str] = set()
    while target in lifecycle and target not in seen:
        seen.add(target)
        state, successor = lifecycle[target]
        if state == "current":
            return target
        if state != "closed":
            break
        target = successor
    return ""


def note_rank_text(stem: str, metadata: dict[str, Any], body: str) -> str:
    tags = metadata.get("tags")
    return " ".join(
        (
            stem,
            str(metadata.get("title") or metadata.get("section") or stem),
            str(metadata.get("summary") or ""),
            " ".join(map(str, tags)) if isinstance(tags, list) else "",
            body,
        )
    )


def open_file_reference(text: str, files: list[str]) -> str:
    """Find a literal filename or path in a failure note."""
    normalized = text.replace("\\", "/").casefold()
    for file in files:
        file = file.replace("\\", "/").casefold().removeprefix("./")
        name = Path(file).name
        if not name:
            continue
        pattern = rf"(?<![\w./-])(?:[a-z]:)?/?(?:[\w.-]+/)*{re.escape(name)}(?![\w./-])"
        for match in re.finditer(pattern, normalized):
            reference = match[0].removeprefix("./")
            if (
                reference == name
                or file in (name, reference)
                or file.endswith("/" + reference)
                or reference.endswith("/" + file)
            ):
                return reference
    return ""


_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_WORD = re.compile(r"\w+")


def query_passage(
    body: str, terms: list[str], char_limit: int, *, reference: str = ""
) -> tuple[int, str]:
    """Return a bounded passage and its 1-based starting line within the body."""
    if char_limit <= 0:
        return 1, ""
    lines = body.splitlines()
    topic = set(terms)
    exact = identifiers(terms)
    best = (-1, -1, -1)
    anchor = 0
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        words = set(tokenize(line))
        score = (
            int(bool(reference and open_file_reference(line, [reference]))),
            len(exact & words),
            len(topic & words),
        )
        if score > best:
            anchor, best = index, score

    passage: list[str] = []
    remaining = char_limit
    for index in range(anchor, len(lines)):
        line = lines[index].rstrip()
        if index > anchor and _HEADING.match(line):
            break
        if remaining <= 0:
            break
        if len(line) > remaining:
            # A long paragraph may contain the match far past its leading text.
            if index > anchor and (
                not _HEADING.match(lines[anchor]) or any(part.strip() for part in passage[1:])
            ):
                break
            focus = -1
            if reference:
                focus = line.replace("\\", "/").casefold().find(reference)
            if focus < 0:
                match = next(
                    (m for m in _WORD.finditer(line) if set(tokenize(m[0])) & (exact or topic)),
                    None,
                )
                focus = match.start() if match else 0
            start = max(0, focus - remaining // 4)
            line = line[start : start + remaining]
        passage.append(line)
        remaining -= len(line) + 1
    return anchor + 1, "\n".join(passage).strip()
