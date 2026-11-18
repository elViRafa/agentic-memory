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

# Fallback candidate cap when the SQLite index is missing. Index-backed search
# ranks the full local corpus and does not truncate before BM25.
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
    fixed phrase. Each result includes a ``backend`` field (``index``,
    ``ripgrep``, or ``python``) and a ``score`` from the shared BM25 ranker.
    A file that also contains the original phrase is boosted above a partial
    token match.

    When ``.ai-memory/private/index.db`` is available, ranking uses the full
    local corpus (IDF from every indexed file). Ripgrep/Python scan is only
    the fallback when the index is missing or corrupt.
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

    indexed = _keyword_search_index(cwd, query, content, max_results)
    if indexed is not None:
        ranked, phrase_hit, candidate_n = indexed
        for result in ranked:
            result["backend"] = "index"
        _record_search(
            cwd,
            ranked,
            query=query,
            started=started,
            backend="index",
            token_n=len(tokens),
            content_token_n=len(content),
            candidate_n=candidate_n,
            phrase_hit=phrase_hit,
        )
        return ranked

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


def _keyword_search_index(
    cwd: str,
    query: str,
    content: list[str],
    max_results: int,
) -> tuple[list[SearchResult], bool, int] | None:
    """Rank the full local corpus from ``index.db``. None → use scan fallback."""
    from memory_fabric.storage.index import IndexRow, close_quietly, load_rows, sync_index

    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
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

    searchable: list[IndexRow] = [
        row
        for row in rows
        if _is_searchable_memory_path(memory_dir, row.path) and row.rank_text.strip()
    ]
    if not searchable:
        return None

    docs = [tokenize(row.rank_text) for row in searchable]
    # Corpus-wide IDF over every indexed searchable file.
    scores = bm25_scores(content, docs)

    phrase_hit = False
    decorated: list[tuple[float, int, SearchResult]] = []
    for index, (row, score) in enumerate(zip(searchable, scores, strict=True)):
        if score <= 0:
            continue
        blended = blended_score(
            score,
            row.priority,
            row.last_updated,
            key=row.section_key,
            query_present=True,
            review_status=row.review_status or None,
            superseded_by=row.superseded_by or None,
        )
        if blended > 0 and _contains_phrase(query, row.rank_text):
            blended *= _PHRASE_BOOST
            phrase_hit = True
        if blended <= 0:
            successor = (row.superseded_by or "").strip()
            if successor and score > 0:
                # Label closed matches so the agent sees the successor.
                decorated.append(
                    (
                        0.0001,
                        -index,
                        {
                            "section": _search_section_label(row.path),
                            "path": str(row.path),
                            "line": 1,
                            "snippet": f"Closed by `{successor}`",
                            "score": 0.0,
                        },
                    )
                )
            continue
        # Snippet filled after top-k selection so a common token does not
        # force a full-corpus re-read.
        decorated.append(
            (
                blended,
                -index,
                {
                    "section": _search_section_label(row.path),
                    "path": str(row.path),
                    "line": 1,
                    "snippet": "",
                    "score": round(float(blended), 6),
                },
            )
        )

    # Global memory sits outside the project index — scan and merge by score.
    global_root = global_memory_dir()
    if global_root.exists():
        global_raw = _keyword_search_python(content, [global_root], _CANDIDATE_CAP)
        global_ranked, global_phrase = _rank_search_results(
            query, content, global_raw, max_results
        )
        phrase_hit = phrase_hit or global_phrase
        for offset, result in enumerate(global_ranked):
            decorated.append((float(result.get("score") or 0.0), -(10_000 + offset), result))

    decorated = _apply_semantic_blend(query, content, searchable, docs, decorated)

    if not decorated:
        semantic = _semantic_rerank(query, content, searchable, docs, max_results)
        if semantic is not None:
            return semantic
        return [], False, len(searchable)

    decorated.sort(key=lambda item: (item[0], item[1]), reverse=True)
    ranked: list[SearchResult] = []
    seen: set[str] = set()
    for score, _neg, result in decorated:
        if result["path"] in seen:
            continue
        seen.add(result["path"])
        if not result.get("snippet"):
            line_number, snippet = _snippet_from_path(Path(result["path"]), content)
            result["line"] = line_number
            result["snippet"] = snippet
        result["score"] = round(float(score), 6)
        ranked.append(result)
        if len(ranked) >= max_results:
            break

    if not ranked:
        semantic = _semantic_rerank(query, content, searchable, docs, max_results)
        if semantic is not None:
            return semantic

    return ranked, phrase_hit, len(searchable)


def _first_match_snippet(text: str, content: list[str]) -> tuple[int, str]:
    needles = set(content)
    for number, line in enumerate(text.splitlines(), start=1):
        if needles & set(tokenize(line)):
            return number, line.strip()
    first = text.strip().splitlines()
    if first:
        return 1, first[0].strip()[:200]
    return 1, ""


def _snippet_from_path(path: Path, content: list[str]) -> tuple[int, str]:
    """Read the file for a body-accurate snippet (rank_text joins title/summary)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 1, ""
    return _first_match_snippet(text, content)


def _semantic_enabled() -> bool:
    import os

    flag = (os.environ.get("MEMORY_FABRIC_SEMANTIC") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _apply_semantic_blend(
    query: str,
    content: list[str],
    searchable: list,
    docs: list[list[str]],
    decorated: list[tuple[float, int, SearchResult]],
) -> list[tuple[float, int, SearchResult]]:
    """Blend cosine into lexical scores and append strong paraphrase-only hits."""
    from memory_fabric.storage.index import IndexRow

    if not _semantic_enabled():
        return decorated
    from memory_fabric.storage.semantic import (
        blend_scores,
        cosine_similarity,
        embed_texts,
        semantic_available,
    )

    rows: list[IndexRow] = list(searchable)
    if not semantic_available() or not rows:
        return decorated
    texts = [query] + [row.rank_text for row in rows]
    vectors = embed_texts(texts)
    if not vectors or len(vectors) != len(texts):
        return decorated
    query_vec = vectors[0]
    path_to_cosine: dict[str, float] = {}
    path_to_tokens: dict[str, set[str]] = {}
    for row, vec, tokens in zip(rows, vectors[1:], docs, strict=True):
        path_to_cosine[str(row.path)] = cosine_similarity(query_vec, vec)
        path_to_tokens[str(row.path)] = set(tokens)

    content_set = set(content)
    seen_paths = {result["path"] for _score, _neg, result in decorated}
    blended_rows: list[tuple[float, int, SearchResult]] = []
    for score, neg_index, result in decorated:
        path = result["path"]
        cosine = path_to_cosine.get(path, 0.0)
        has_exact = bool(content_set & path_to_tokens.get(path, set()))
        if has_exact:
            new_score = blend_scores(score, cosine, lexical_weight=0.85)
        else:
            new_score = blend_scores(score, cosine, lexical_weight=0.35)
        blended_rows.append((new_score, neg_index, result))

    # Paraphrase-only files (no shared content token) with strong cosine.
    for index, row in enumerate(rows):
        path = str(row.path)
        if path in seen_paths:
            continue
        cosine = path_to_cosine.get(path, 0.0)
        if cosine < 0.55:
            continue
        if content_set & path_to_tokens.get(path, set()):
            continue
        line_number, snippet = _snippet_from_path(row.path, content)
        if not snippet:
            first = row.rank_text.strip().splitlines()
            snippet = first[0].strip()[:200] if first else ""
            line_number = 1
        blended_rows.append(
            (
                cosine * 0.5,
                -(100_000 + index),
                {
                    "section": _search_section_label(row.path),
                    "path": path,
                    "line": line_number,
                    "snippet": snippet,
                    "score": round(cosine * 0.5, 6),
                },
            )
        )
    return blended_rows


def _semantic_rerank(
    query: str,
    content: list[str],
    searchable: list,
    docs: list[list[str]],
    max_results: int,
) -> tuple[list[SearchResult], bool, int] | None:
    """When BM25 finds nothing, surface paraphrase hits via embeddings."""
    from memory_fabric.storage.index import IndexRow

    if not _semantic_enabled():
        return None
    from memory_fabric.storage.semantic import (
        cosine_similarity,
        embed_texts,
        semantic_available,
    )

    rows: list[IndexRow] = list(searchable)
    if not semantic_available() or not rows:
        return None
    texts = [query] + [row.rank_text for row in rows]
    vectors = embed_texts(texts)
    if not vectors or len(vectors) != len(texts):
        return None
    query_vec = vectors[0]
    content_set = set(content)
    scored: list[tuple[float, int, IndexRow, str]] = []
    for index, (row, vec, tokens) in enumerate(
        zip(rows, vectors[1:], docs, strict=True)
    ):
        sim = cosine_similarity(query_vec, vec)
        if sim < 0.35:
            continue
        exact = bool(content_set & set(tokens))
        weight = sim * (0.5 if exact else 1.0)
        scored.append((weight, index, row, row.rank_text))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    ranked: list[SearchResult] = []
    for weight, _index, row, text in scored[:max_results]:
        line_number, snippet = _snippet_from_path(row.path, content) if content else (1, "")
        if not snippet:
            first = text.strip().splitlines()
            snippet = first[0].strip()[:200] if first else ""
            line_number = 1
        ranked.append(
            {
                "section": _search_section_label(row.path),
                "path": str(row.path),
                "line": line_number,
                "snippet": snippet,
                "score": round(float(weight), 6),
            }
        )
    return ranked, False, len(rows)


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
    metas: list[tuple[str, str, str, str, str]] = []
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
    for path, score, text, (priority, last_updated, review_status, superseded_by, role) in zip(
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
            role=role or None,
        )
        if blended > 0 and _contains_phrase(query, text):
            blended *= _PHRASE_BOOST
            phrase_hit = True
        if blended <= 0 and (superseded_by or "").strip() and score > 0:
            # Keep a tiny score so the closed file can surface as a label.
            blended = 0.0001
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
        # Label closed matches on the scan fallback the same way as the index path.
        try:
            text = Path(result["path"]).read_text(encoding="utf-8")
            _p, _lu, _rs, superseded, _role = _rank_metadata(text)
            if (superseded or "").strip() and score <= 0.0001:
                result["snippet"] = f"Closed by `{superseded.strip()}`"
                result["score"] = 0.0
        except (OSError, UnicodeDecodeError):
            pass
        ranked.append(result)
        if len(ranked) >= max_results:
            break
    return ranked, phrase_hit


def _priority_and_updated(text: str) -> tuple[str, str]:
    priority, last_updated, _review, _superseded, _role = _rank_metadata(text)
    return priority, last_updated


def _rank_metadata(text: str) -> tuple[str, str, str, str, str]:
    priority = "medium"
    last_updated = ""
    review_status = ""
    superseded_by = ""
    role = ""
    if not text.lstrip().startswith("---"):
        return priority, last_updated, review_status, superseded_by, role
    try:
        from memory_fabric.frontmatter import parse_frontmatter

        metadata, _body = parse_frontmatter(text)
    except Exception:  # noqa: BLE001 - ranking metadata is best-effort.
        return priority, last_updated, review_status, superseded_by, role
    return (
        str(metadata.get("priority") or "medium"),
        str(metadata.get("last_updated") or ""),
        str(metadata.get("review_status") or ""),
        str(metadata.get("superseded_by") or ""),
        str(metadata.get("role") or ""),
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
