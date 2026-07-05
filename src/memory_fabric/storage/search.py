"""Keyword search across local, global, and semantic-store memory files."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from memory_fabric.contracts import SearchResult
from memory_fabric.paths import global_memory_dir, local_memory_dir
from memory_fabric.storage._shared import _iter_markdown_files, _path_to_store_path


def keyword_search(cwd: str, query: str, max_results: int = 10) -> list[SearchResult]:
    """Search memory files by keyword. Returns results with a `backend` field
    indicating which search engine was used ('ripgrep' or 'python').
    """
    if not query.strip() or max_results <= 0:
        return []

    roots = [path for path in [local_memory_dir(cwd), global_memory_dir()] if path.exists()]
    if not roots:
        return []

    if shutil.which("rg"):
        results = _keyword_search_rg(query, roots, max_results)
        if results:
            for r in results:
                r["backend"] = "ripgrep"
            return results

    results = _keyword_search_python(query, roots, max_results)
    for r in results:
        r["backend"] = "python"
    return results


def _keyword_search_rg(query: str, roots: list[Path], max_results: int) -> list[SearchResult]:
    command = [
        "rg",
        "--json",
        "--ignore-case",
        "--fixed-strings",
        query,
        *[str(root) for root in roots],
    ]
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5.0,
    )
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
