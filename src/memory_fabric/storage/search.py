"""Keyword search across local, global, and semantic-store memory files."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from memory_fabric.contracts import SearchResult
from memory_fabric.paths import global_memory_dir, local_memory_dir
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path,
    _iter_markdown_files,
    _path_to_store_path,
)
from memory_fabric.storage.ranking import blended_score, bm25_scores, tokenize

_CANDIDATE_CAP = 200
# A verbatim phrase should outrank a file that only repeats the same words apart.
_PHRASE_BOOST = 4.0

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
        "do",
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
    }
)


def _is_generated_store_index(memory_dir: Path, path: Path) -> bool:
    return path == memory_dir / "memory-store" / "index.md"


def _is_searchable_memory_path(memory_dir: Path, path: Path) -> bool:
    if _is_ignored_local_memory_path(memory_dir, path):
        return False
    return not _is_generated_store_index(memory_dir, path)


def _owning_root(path: Path, roots: list[Path]) -> Path | None:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return root
        except ValueError:
            continue
    return None


def _path_is_searchable(path: Path, roots: list[Path]) -> bool:
    root = _owning_root(path, roots)
    if root is None:
        return True
    return _is_searchable_memory_path(root, path)


def keyword_search(cwd: str, query: str, max_results: int = 10) -> list[SearchResult]:
    """Search memory files by keyword. Returns score-ordered results.

    A sentence is matched on its content words (stopwords removed), not as one
    fixed phrase. Each result includes a ``backend`` field (``ripgrep`` or
    ``python``) and a ``score`` from the shared BM25 ranker. A file that also
    contains the original phrase is boosted above a partial token match.
    """
    if not query.strip() or max_results <= 0:
        return []

    started = time.perf_counter()
    tokens, content = _search_tokens(query)
    if not content:
        _record_search(
            cwd,
            [],
            query=query,
            started=started,
            backend="",
            token_n=len(tokens),
            content_token_n=0,
            candidate_n=0,
            phrase_hit=False,
        )
        return []

    roots = [path for path in [local_memory_dir(cwd), global_memory_dir()] if path.exists()]
    if not roots:
        _record_search(
            cwd,
            [],
            query=query,
            started=started,
            backend="",
            token_n=len(tokens),
            content_token_n=len(content),
            candidate_n=0,
            phrase_hit=False,
        )
        return []

    candidate_cap = max(_CANDIDATE_CAP, max_results)
    backend = "python"
    patterns = _rg_patterns(query, content)
    if shutil.which("rg"):
        raw = _keyword_search_rg(patterns, roots, candidate_cap)
        if raw:
            backend = "ripgrep"
        else:
            raw = _keyword_search_python(content, roots, candidate_cap)
    else:
        raw = _keyword_search_python(content, roots, candidate_cap)

    ranked, phrase_hit = _rank_search_results(query, content, raw, max_results)
    for result in ranked:
        result["backend"] = backend
    _record_search(
        cwd,
        ranked,
        query=query,
        started=started,
        backend=backend,
        token_n=len(tokens),
        content_token_n=len(content),
        candidate_n=len({result["path"] for result in raw}),
        phrase_hit=phrase_hit,
    )
    return ranked


def _search_tokens(query: str) -> tuple[list[str], list[str]]:
    """Return ``(all folded tokens, content tokens)`` with stopwords removed."""
    tokens = tokenize(query)
    content = list(
        dict.fromkeys(
            token for token in tokens if token not in _STOPWORDS and len(token) >= 2
        )
    )
    return tokens, content


def _rg_patterns(query: str, content: list[str]) -> list[str]:
    """Folded content tokens, plus the original surface form when accents differ."""
    patterns = list(content)
    content_set = set(content)
    for raw in re.findall(r"\w+", query, flags=re.UNICODE):
        folded = tokenize(raw)
        if not folded or folded[0] not in content_set:
            continue
        if raw.casefold() != folded[0]:
            patterns.append(raw)
    return list(dict.fromkeys(patterns))


def _record_search(
    cwd: str,
    ranked: list[SearchResult],
    *,
    query: str,
    started: float,
    backend: str,
    token_n: int,
    content_token_n: int,
    candidate_n: int,
    phrase_hit: bool,
) -> None:
    from memory_fabric.diary.instrument import record_search_run

    record_search_run(
        cwd,
        ranked,
        query=query,
        ms=(time.perf_counter() - started) * 1000,
        backend=backend,
        token_n=token_n,
        content_token_n=content_token_n,
        candidate_n=candidate_n,
        phrase_hit=phrase_hit,
    )


def _folded_phrase(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch)).casefold()
    return re.sub(r"\s+", " ", stripped).strip()


def _contains_phrase(query: str, text: str) -> bool:
    phrase = _folded_phrase(query)
    if len(phrase) < 2:
        return False
    return phrase in _folded_phrase(text)


def _rank_search_results(
    query: str, content_tokens: list[str], results: list[SearchResult], max_results: int
) -> tuple[list[SearchResult], bool]:
    if not results:
        return [], False
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for result in results:
        key = result["path"]
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(Path(key))

    docs: list[list[str]] = []
    metas: list[tuple[str, str, str, str]] = []
    texts: list[str] = []
    for path in unique_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        texts.append(text)
        docs.append(tokenize(text))
        metas.append(_rank_metadata(text))

    scores = bm25_scores(content_tokens, docs)
    phrase_hit = False
    path_scores: dict[str, float] = {}
    for path, score, text, (priority, last_updated, review_status, superseded_by) in zip(
        unique_paths, scores, texts, metas, strict=True
    ):
        blended = blended_score(
            score,
            priority,
            last_updated,
            key=str(path),
            query_present=True,
            review_status=review_status or None,
            superseded_by=superseded_by or None,
        )
        if blended > 0 and _contains_phrase(query, text):
            blended *= _PHRASE_BOOST
            phrase_hit = True
        path_scores[str(path)] = blended

    decorated: list[tuple[float, int, SearchResult]] = []
    for index, result in enumerate(results):
        decorated.append((path_scores.get(result["path"], 0.0), -index, result))
    decorated.sort(key=lambda item: (item[0], item[1]), reverse=True)

    ranked: list[SearchResult] = []
    seen_ranked: set[str] = set()
    for score, _neg_index, result in decorated:
        if result["path"] in seen_ranked:
            continue
        seen_ranked.add(result["path"])
        result["score"] = round(float(score), 6)
        ranked.append(result)
        if len(ranked) >= max_results:
            break
    return ranked, phrase_hit


def _priority_and_updated(text: str) -> tuple[str, str]:
    priority, last_updated, _review, _superseded = _rank_metadata(text)
    return priority, last_updated


def _rank_metadata(text: str) -> tuple[str, str, str, str]:
    priority = "medium"
    last_updated = ""
    review_status = ""
    superseded_by = ""
    if not text.lstrip().startswith("---"):
        return priority, last_updated, review_status, superseded_by
    try:
        from memory_fabric.frontmatter import parse_frontmatter

        metadata, _body = parse_frontmatter(text)
    except Exception:  # noqa: BLE001 - ranking metadata is best-effort.
        return priority, last_updated, review_status, superseded_by
    return (
        str(metadata.get("priority") or "medium"),
        str(metadata.get("last_updated") or ""),
        str(metadata.get("review_status") or ""),
        str(metadata.get("superseded_by") or ""),
    )


def _keyword_search_rg(
    patterns: list[str], roots: list[Path], max_files: int
) -> list[SearchResult]:
    if not patterns:
        return []
    command = [
        "rg",
        "--json",
        "--ignore-case",
        "--fixed-strings",
        "--glob",
        "!**/private/**",
        "--glob",
        "!**/snapshots/**",
        "--glob",
        "!**/evals/**",
        "--glob",
        "!**/candidates/**",
        "--glob",
        "!**/consolidated_memory.md",
        "--glob",
        "!**/memory-store/index.md",
    ]
    for pattern in patterns:
        command.extend(["-e", pattern])
    command.extend(str(root) for root in roots)
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode not in {0, 1}:
        return []

    results: list[SearchResult] = []
    seen: set[str] = set()
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event["data"]
        path = Path(data["path"]["text"])
        path_key = str(path)
        if path_key in seen or not _path_is_searchable(path, roots):
            continue
        seen.add(path_key)
        results.append(
            {
                "section": _search_section_label(path),
                "path": path_key,
                "line": int(data["line_number"]),
                "snippet": data["lines"]["text"].strip(),
            }
        )
        if len(results) >= max_files:
            break
    return results


def _keyword_search_python(
    content_tokens: list[str], roots: list[Path], max_files: int
) -> list[SearchResult]:
    needles = set(content_tokens)
    if not needles:
        return []
    results: list[SearchResult] = []
    for root in roots:
        for path in _iter_markdown_files(root):
            if not _is_searchable_memory_path(root, path):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not needles & set(tokenize(text)):
                continue
            line_number = 1
            snippet = ""
            for number, line in enumerate(text.splitlines(), start=1):
                if needles & set(tokenize(line)):
                    line_number = number
                    snippet = line.strip()
                    break
            results.append(
                {
                    "section": _search_section_label(path),
                    "path": str(path),
                    "line": line_number,
                    "snippet": snippet,
                }
            )
            if len(results) >= max_files:
                return results
    return results


def _search_section_label(path: Path) -> str:
    """Generate a section label for search results, using store: prefix for store files."""
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "memory-store" and i > 0:
            store_root = Path(*parts[: i + 1])
            try:
                sp = _path_to_store_path(store_root, path)
                return f"store:{sp}"
            except ValueError:
                pass
    return path.stem
