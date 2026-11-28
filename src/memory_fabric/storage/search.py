"""Keyword search across local, global, and semantic-store memory files."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from memory_fabric.contracts import SearchResult
from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.paths import global_memory_dir, local_memory_dir
from memory_fabric.storage._evidence import (
    EvidenceState,
    evidence_state,
    identifiers,
    note_rank_text,
    query_passage,
    query_tokens,
    topical_match,
)
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path,
    _iter_markdown_files,
    _path_to_store_path,
    _validate_store_path,
)
from memory_fabric.storage.context import _section_key
from memory_fabric.storage.ranking import blended_score, bm25_scores, tokenize

# Fallback candidate cap when the SQLite index is missing. Index-backed search
# ranks the full local corpus and does not truncate before BM25.
_CANDIDATE_CAP = 200
# A verbatim phrase should outrank a file that only repeats the same words apart.
_PHRASE_BOOST = 4.0


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
    tokens, content = query_tokens(query)
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
    raw: list[SearchResult] = []
    scan_capped = False
    if shutil.which("rg"):
        raw, scan_capped = _keyword_search_rg(patterns, roots, candidate_cap)
        if raw:
            backend = "ripgrep"
    if not raw:
        raw, scan_capped = _keyword_search_python(content, roots, candidate_cap)

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
        scan_capped=scan_capped,
    )
    return ranked


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
    scan_capped: bool = False,
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
        scan_capped=scan_capped,
    )


@lru_cache(maxsize=1024)
def _folded_phrase(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch)).casefold()
    return re.sub(r"\s+", " ", stripped).strip()


def _contains_phrase(query: str, text: str) -> bool:
    phrase = _folded_phrase(query)
    if len(phrase) < 2:
        return False
    return phrase in _folded_phrase(text)


@dataclass(frozen=True)
class _SearchNote:
    path: Path
    key: str
    rank_text: str
    priority: str
    updated: str
    review_status: str
    successor: str
    role: str
    body: str | None = None
    first_line: int = 0

    @property
    def state(self) -> EvidenceState:
        return evidence_state(self.key, self.review_status, self.successor, self.role)


@dataclass(frozen=True)
class _SearchHit:
    note: _SearchNote
    score: float
    predecessor: str = ""


def _load_search_note(path: Path) -> _SearchNote | None:
    try:
        raw = path.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(raw) if raw.startswith("---\n") else ({}, raw)
    except (OSError, UnicodeDecodeError, FrontmatterError):
        return None
    section = str(metadata.get("section") or path.stem)
    return _SearchNote(
        path=path,
        key=_section_key(path, section),
        rank_text=note_rank_text(path.stem, metadata, body),
        priority=str(metadata.get("priority") or "medium"),
        updated=str(metadata.get("last_updated") or ""),
        review_status=str(metadata.get("review_status") or ""),
        successor=str(metadata.get("superseded_by") or "").strip(),
        role=str(metadata.get("role") or ""),
        body=body,
        first_line=raw[: len(raw) - len(body)].count("\n"),
    )


def _keyword_search_index(
    cwd: str,
    query: str,
    content: list[str],
    max_results: int,
) -> tuple[list[SearchResult], bool, int] | None:
    from memory_fabric.storage.index import close_quietly, load_rows, sync_index

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

    notes = [
        _SearchNote(
            row.path,
            row.section_key,
            row.rank_text,
            row.priority,
            row.last_updated,
            row.review_status or "",
            (row.superseded_by or "").strip(),
            row.role,
        )
        for row in rows
        if _is_searchable_memory_path(memory_dir, row.path) and row.rank_text.strip()
    ]
    if not notes:
        return None

    hits, phrase_hit = _rank_notes(query, content, notes)
    _blend_semantic_hits(query, content, notes, hits)
    global_root = global_memory_dir()
    if global_root.exists():
        raw, _ = _keyword_search_python(content, [global_root], _CANDIDATE_CAP)
        global_hits, global_phrase = _rank_notes(query, content, _load_candidates(raw))
        hits.update(global_hits)
        phrase_hit = phrase_hit or global_phrase
    return _search_results(hits, content, max_results), phrase_hit, len(notes)


@lru_cache(maxsize=1024)
def _rank_tokens(text: str) -> tuple[str, ...]:
    # The index refreshes rank text from disk; changed text always has a new cache key.
    return tuple(tokenize(text))


def _rank_notes(
    query: str, terms: list[str], notes: list[_SearchNote]
) -> tuple[dict[Path, _SearchHit], bool]:
    docs = [_rank_tokens(note.rank_text) for note in notes]
    scores = bm25_scores(terms, docs)
    exact = identifiers(terms)
    by_path = {note.path: note for note in notes}
    hits: dict[Path, _SearchHit] = {}
    successors: dict[Path, _SearchHit] = {}
    phrase_hit = False
    for note, raw, words in zip(notes, scores, docs, strict=True):
        if raw <= 0 or not topical_match(terms, exact, set(words), note.path.stem):
            continue
        if note.state == "broken":
            continue
        score = blended_score(
            raw,
            note.priority,
            note.updated,
            key=note.key,
            query_present=True,
            role=note.role,
        )
        if _contains_phrase(query, note.rank_text):
            score *= _PHRASE_BOOST
            phrase_hit = True
        hits[note.path] = _SearchHit(note, score)
        if note.state == "closed":
            target = _follow_successor(note, by_path)
            if target and (target.path not in successors or score > successors[target.path].score):
                successors[target.path] = _SearchHit(target, score, note.key.removeprefix("store/"))

    for path, hit in successors.items():
        if path in hits:
            hit = replace(hit, score=max(hit.score, hits[path].score))
        hits[path] = hit
    return hits, phrase_hit


def _follow_successor(note: _SearchNote, by_path: dict[Path, _SearchNote]) -> _SearchNote | None:
    if not note.key.startswith("store/"):
        return None
    root = note.path.parents[note.key.count("/") - 1]
    seen = {note.path}
    while note.state == "closed":
        try:
            parts = _validate_store_path(note.successor)
        except ValueError:
            return None
        path = root.joinpath(*parts).with_suffix(".md")
        if (
            path in seen
            or _is_generated_store_index(root.parent, path)
            or not path.resolve().is_relative_to(root.resolve())
        ):
            return None
        seen.add(path)
        target = by_path.get(path) or _load_search_note(path)
        if target is None:
            return None
        note = target
    return note if note.state == "current" else None


def _blend_semantic_hits(
    query: str, terms: list[str], notes: list[_SearchNote], hits: dict[Path, _SearchHit]
) -> None:
    """Rerank current evidence and admit current paraphrases for ordinary questions."""
    import os

    from memory_fabric.storage.semantic import (
        blend_scores,
        cosine_similarity,
        embed_texts,
        semantic_available,
    )

    flag = (os.environ.get("MEMORY_FABRIC_SEMANTIC") or "1").strip().lower()
    if flag in {"0", "false", "no", "off"} or identifiers(terms) or not semantic_available():
        return

    current = [note for note in notes if note.state == "current"]
    if not current:
        return
    texts = [query, *(note.rank_text for note in current)]
    vectors = embed_texts(texts)
    if not vectors or len(vectors) != len(texts):
        return
    threshold = 0.55 if hits else 0.35
    for note, vector in zip(current, vectors[1:], strict=True):
        cosine = cosine_similarity(vectors[0], vector)
        if hit := hits.get(note.path):
            hits[note.path] = replace(
                hit, score=blend_scores(hit.score, cosine, lexical_weight=0.85)
            )
        elif cosine >= threshold:
            hits[note.path] = _SearchHit(note, cosine * 0.5)


def _search_results(
    hits: dict[Path, _SearchHit], terms: list[str], max_results: int
) -> list[SearchResult]:
    ranked = sorted(
        hits.values(), key=lambda hit: (hit.note.state == "current", hit.score), reverse=True
    )
    results: list[SearchResult] = []
    for hit in ranked:
        note = hit.note if hit.note.body is not None else _load_search_note(hit.note.path)
        if note is None or note.state != hit.note.state:
            continue
        if note.state == "closed":
            line = 1
            snippet = f"Historical lead (closed). Closed by `{note.successor}`."
        else:
            number, snippet = query_passage(note.body or "", terms, 360)
            line = note.first_line + number
            if not snippet:
                snippet = note.rank_text.strip()[:360]
            if note.state == "historical":
                snippet = f"Historical lead (stale). Verify before applying. {snippet}"
            elif hit.predecessor:
                snippet = f"Successor to `{hit.predecessor}`. {snippet}"
        results.append(
            {
                "section": _search_section_label(note.path),
                "path": str(note.path),
                "line": line,
                "snippet": snippet,
                "score": round(hit.score, 6),
            }
        )
        if len(results) >= max_results:
            break
    return results


def _load_candidates(results: list[SearchResult]) -> list[_SearchNote]:
    paths = dict.fromkeys(Path(result["path"]) for result in results)
    return [note for path in paths if (note := _load_search_note(path)) is not None]


def _rank_search_results(
    query: str, content_tokens: list[str], results: list[SearchResult], max_results: int
) -> tuple[list[SearchResult], bool]:
    hits, phrase_hit = _rank_notes(query, content_tokens, _load_candidates(results))
    return _search_results(hits, content_tokens, max_results), phrase_hit


def _keyword_search_rg(
    patterns: list[str], roots: list[Path], max_files: int
) -> tuple[list[SearchResult], bool]:
    if not patterns:
        return [], False
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
        return [], False
    if completed.returncode not in {0, 1}:
        return [], False

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
        if len(results) == max_files:
            return results, True
        seen.add(path_key)
        results.append(
            {
                "section": _search_section_label(path),
                "path": path_key,
                "line": int(data["line_number"]),
                "snippet": data["lines"]["text"].strip(),
            }
        )
    return results, False


def _keyword_search_python(
    content_tokens: list[str], roots: list[Path], max_files: int
) -> tuple[list[SearchResult], bool]:
    needles = set(content_tokens)
    if not needles:
        return [], False
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
            if len(results) == max_files:
                return results, True
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
    return results, False


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
