"""Keyword search across local, global, and semantic-store memory files."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
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

    Each result includes a ``backend`` field (``ripgrep`` or ``python``) and a
    ``score`` from the shared BM25 ranker.
    """
    if not query.strip() or max_results <= 0:
        return []

    started = time.perf_counter()
    roots = [path for path in [local_memory_dir(cwd), global_memory_dir()] if path.exists()]
    if not roots:
        return []

    candidate_cap = max(_CANDIDATE_CAP, max_results)
    backend = "python"
    if shutil.which("rg"):
        raw = _keyword_search_rg(query, roots, candidate_cap)
        if raw:
            backend = "ripgrep"
        else:
            raw = _keyword_search_python(query, roots, candidate_cap)
    else:
        raw = _keyword_search_python(query, roots, candidate_cap)

    ranked = _rank_search_results(query, raw, max_results)
    for result in ranked:
        result["backend"] = backend
    from memory_fabric.diary.instrument import record_search_run

    record_search_run(
        cwd, ranked, query=query, ms=(time.perf_counter() - started) * 1000, backend=backend
    )
    return ranked


def _rank_search_results(
    query: str, results: list[SearchResult], max_results: int
) -> list[SearchResult]:
    if not results:
        return []
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
    for path in unique_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        docs.append(tokenize(text))
        metas.append(_rank_metadata(text))

    query_tokens = tokenize(query)
    scores = bm25_scores(query_tokens, docs)
    path_scores = {
        str(path): blended_score(
            score,
            priority,
            last_updated,
            key=str(path),
            query_present=True,
            review_status=review_status or None,
            superseded_by=superseded_by or None,
        )
        for path, score, (priority, last_updated, review_status, superseded_by) in zip(
            unique_paths, scores, metas, strict=True
        )
    }

    decorated: list[tuple[float, int, SearchResult]] = []
    for index, result in enumerate(results):
        decorated.append((path_scores.get(result["path"], 0.0), -index, result))
    decorated.sort(key=lambda item: (item[0], item[1]), reverse=True)

    ranked: list[SearchResult] = []
    for score, _neg_index, result in decorated[:max_results]:
        result["score"] = round(float(score), 6)
        ranked.append(result)
    return ranked


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


def _keyword_search_rg(query: str, roots: list[Path], max_results: int) -> list[SearchResult]:
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
        query,
        *[str(root) for root in roots],
    ]
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
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event["data"]
        path = Path(data["path"]["text"])
        if not _path_is_searchable(path, roots):
            continue
        section_label = _search_section_label(path)
        results.append(
            {
                "section": section_label,
                "path": str(path),
                "line": int(data["line_number"]),
                "snippet": data["lines"]["text"].strip(),
            }
        )
        if len(results) >= max_results:
            break
    return results


def _keyword_search_python(query: str, roots: list[Path], max_results: int) -> list[SearchResult]:
    needle = query.lower()
    results: list[SearchResult] = []
    for root in roots:
        for path in _iter_markdown_files(root):
            if not _is_searchable_memory_path(root, path):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            section_label = _search_section_label(path)
            for line_number, line in enumerate(lines, start=1):
                if needle in line.lower():
                    results.append(
                        {
                            "section": section_label,
                            "path": str(path),
                            "line": line_number,
                            "snippet": line.strip(),
                        }
                    )
                    if len(results) >= max_results:
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
