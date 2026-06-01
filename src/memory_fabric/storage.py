"""Core Memory Fabric operations."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from memory_fabric.contracts import (
    ContextBundle,
    DoctorResult,
    DreamResult,
    InitResult,
    MemorySection,
    PatchPreview,
    SearchResult,
    StatusResult,
    WriteMode,
    WriteResult,
)
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.locking import locked_file
from memory_fabric.paths import global_memory_dir, local_memory_dir, project_root
from memory_fabric.security import redact_secrets
from memory_fabric.templates import LOCAL_GITIGNORE, SECTION_TEMPLATES, build_empty_section, build_memory_file, now_iso


SECTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 3}


def initialize_memory_fabric(cwd: str) -> InitResult:
    root = project_root(cwd)
    memory_dir = local_memory_dir(root)
    memory_dir.mkdir(parents=True, exist_ok=True)

    files_created: list[str] = []
    for section in SECTION_TEMPLATES:
        path = memory_dir / f"{section}.md"
        if not path.exists():
            path.write_text(build_memory_file(section), encoding="utf-8")
            files_created.append(str(path))

    gitignore = memory_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(LOCAL_GITIGNORE, encoding="utf-8")
        files_created.append(str(gitignore))

    return {
        "created": bool(files_created),
        "memory_dir": str(memory_dir),
        "files_created": files_created,
        "warnings": [],
    }


def read_combined_context(cwd: str, max_tokens: int = 4000) -> ContextBundle:
    warnings: list[str] = []
    included: list[str] = []
    omitted: list[str] = []
    fragments: list[str] = []
    remaining = max_tokens

    tier0 = global_memory_dir() / "directives.md"
    if tier0.exists():
        text = tier0.read_text(encoding="utf-8")
        fragments.append(_format_fragment("global/directives", text))
        included.append("global/directives")
        remaining -= estimate_tokens(text)
    else:
        warnings.append(f"Tier 0 directives not found: {tier0}")

    for path in _ordered_context_files(cwd):
        section_name, metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            warnings.append(read_warning)
            omitted.append(str(path))
            continue

        full_text = dump_frontmatter(metadata, body)
        section_key = _section_key(path, section_name)
        token_estimate = estimate_tokens(full_text)
        if token_estimate <= max(remaining, 0):
            fragments.append(_format_fragment(section_key, full_text))
            included.append(section_key)
            remaining -= token_estimate
        else:
            summary = str(metadata.get("summary") or "No summary available.")
            summary_text = (
                f"Section `{section_key}` omitted because it exceeded the remaining token budget.\n"
                f"Summary: {summary}\n"
            )
            fragments.append(_format_fragment(section_key, summary_text))
            omitted.append(section_key)
            remaining -= estimate_tokens(summary_text)

    text = "\n\n".join(fragments).strip() + ("\n" if fragments else "")
    return {
        "text": text,
        "included_sections": included,
        "omitted_sections": omitted,
        "token_budget": max_tokens,
        "estimated_tokens": estimate_tokens(text),
        "warnings": warnings,
    }


def read_section(cwd: str, section: str, max_tokens: int = 8000) -> MemorySection:
    path = _section_path(cwd, section)
    warnings: list[str] = []
    if not path.exists():
        raise FileNotFoundError(f"Memory section not found: {section}")

    metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    text = dump_frontmatter(metadata, body)
    truncated = False
    if estimate_tokens(text) > max_tokens:
        summary = str(metadata.get("summary") or "No summary available.")
        text = (
            f"Section `{section}` omitted because it exceeded the token budget.\n"
            f"Summary: {summary}\n"
        )
        truncated = True
        warnings.append("Section exceeded token budget; returned summary only.")

    return {
        "section": section,
        "path": str(path),
        "text": text,
        "metadata": metadata,
        "truncated": truncated,
        "warnings": warnings,
    }


def keyword_search(cwd: str, query: str, max_results: int = 10) -> list[SearchResult]:
    if not query.strip() or max_results <= 0:
        return []

    roots = [path for path in [local_memory_dir(cwd), global_memory_dir()] if path.exists()]
    if not roots:
        return []

    if shutil.which("rg"):
        results = _keyword_search_rg(query, roots, max_results)
        if results:
            return results

    return _keyword_search_python(query, roots, max_results)


def write_local_memory(
    cwd: str,
    section: str,
    content: str,
    mode: WriteMode = "append",
) -> WriteResult:
    if mode not in {"append", "replace"}:
        raise ValueError("mode must be 'append' or 'replace'")

    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        initialize_memory_fabric(cwd)

    path = _section_path(cwd, section)
    redacted, redactions = redact_secrets(content)
    warnings = ["Detected and redacted secrets before writing memory."] if redactions else []

    with locked_file(path):
        if path.exists():
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        else:
            metadata, body = parse_frontmatter(build_empty_section(section))

        metadata["section"] = section
        metadata["last_updated"] = now_iso()

        if mode == "replace":
            new_body = redacted.strip() + "\n"
        else:
            clean_existing = body.rstrip()
            clean_new = redacted.strip()
            if clean_existing and clean_new:
                new_body = clean_existing + "\n\n" + clean_new + "\n"
            elif clean_new:
                new_body = clean_new + "\n"
            else:
                new_body = clean_existing + "\n"

        path.write_text(dump_frontmatter(metadata, new_body), encoding="utf-8")

    return {
        "changed": True,
        "path": str(path),
        "redactions": redactions,
        "warnings": warnings,
    }


def propose_memory_patch(cwd: str, instructions: str) -> PatchPreview:
    memory_dir = local_memory_dir(cwd)
    index_path = memory_dir / "index.md"
    sanitized, redactions = redact_secrets(instructions)
    warnings = ["Detected and redacted secrets before creating patch preview."] if redactions else []

    if not index_path.exists():
        return {
            "patch": "",
            "affected_files": [],
            "redactions": redactions,
            "warnings": warnings + [f"Index file not found: {index_path}"],
        }

    original = index_path.read_text(encoding="utf-8").splitlines(keepends=True)
    proposed_text = index_path.read_text(encoding="utf-8").rstrip()
    proposed_text += "\n\n## Proposed Memory Update\n\n"
    proposed_text += sanitized.strip() + "\n"
    proposed = proposed_text.splitlines(keepends=True)

    patch = "".join(
        difflib.unified_diff(
            original,
            proposed,
            fromfile=str(index_path),
            tofile=str(index_path),
        )
    )
    return {
        "patch": patch,
        "affected_files": [str(index_path)],
        "redactions": redactions,
        "warnings": warnings,
    }


def status(cwd: str) -> StatusResult:
    memory_dir = local_memory_dir(cwd)
    local_files = [str(path) for path in _iter_markdown_files(memory_dir)] if memory_dir.exists() else []
    return {
        "cwd": str(project_root(cwd)),
        "memory_dir": str(memory_dir),
        "memory_exists": memory_dir.exists(),
        "global_dir": str(global_memory_dir()),
        "provider_configured": bool(os.environ.get("MEMORY_FABRIC_LLM_PROVIDER")),
        "local_files": local_files,
    }


def doctor(cwd: str) -> DoctorResult:
    memory_dir = local_memory_dir(cwd)
    errors: list[str] = []
    warnings: list[str] = []
    checked_files: list[str] = []

    if not memory_dir.exists():
        errors.append(f"Local memory directory does not exist: {memory_dir}")
        return {"ok": False, "errors": errors, "warnings": warnings, "checked_files": checked_files}

    for path in _iter_markdown_files(memory_dir):
        checked_files.append(str(path))
        try:
            metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            errors.append(f"{path}: {exc}")
            continue

        for field in ["section", "summary", "priority", "tags", "schema_version", "last_updated"]:
            if field not in metadata:
                errors.append(f"{path}: missing required field `{field}`")
        if metadata.get("priority") not in {"high", "medium", "low"}:
            errors.append(f"{path}: priority must be high, medium, or low")
        if not isinstance(metadata.get("tags"), list):
            errors.append(f"{path}: tags must be an inline list")

    if not (memory_dir / "index.md").exists():
        warnings.append("index.md is missing")
    if not shutil.which("rg"):
        warnings.append("rg not found; keyword search will use Python fallback")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_files": checked_files,
    }


def dream(cwd: str, mode: str = "light") -> DreamResult:
    if mode not in {"light", "deep"}:
        raise ValueError("mode must be 'light' or 'deep'")

    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        initialize_memory_fabric(cwd)

    snapshot = create_snapshot(cwd)
    checked_files = _regenerate_index(cwd, mode=mode)
    warnings: list[str] = []
    if not os.environ.get("MEMORY_FABRIC_LLM_PROVIDER"):
        warnings.append("No LLM provider configured; ran local maintenance only.")

    return {
        "changed": True,
        "snapshot": snapshot,
        "warnings": warnings,
        "checked_files": checked_files,
    }


def create_snapshot(cwd: str, name: str | None = None) -> str:
    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        raise FileNotFoundError(f"Local memory directory does not exist: {memory_dir}")

    snapshot_name = name or "memory-" + now_iso().replace(":", "").replace("+", "_").replace("-", "")
    snapshot_dir = memory_dir / "snapshots" / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for path in _iter_markdown_files(memory_dir):
        relative = path.relative_to(memory_dir)
        target = snapshot_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return snapshot_name


def rollback(cwd: str, snapshot: str) -> WriteResult:
    if not SECTION_PATTERN.match(snapshot):
        raise ValueError("snapshot must contain only letters, numbers, underscores, and hyphens")

    memory_dir = local_memory_dir(cwd)
    snapshot_dir = memory_dir / "snapshots" / snapshot
    if not snapshot_dir.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot}")

    changed = False
    for source in _iter_markdown_files(snapshot_dir):
        relative = source.relative_to(snapshot_dir)
        target = memory_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(target):
            shutil.copy2(source, target)
        changed = True

    return {
        "changed": changed,
        "path": str(memory_dir),
        "redactions": 0,
        "warnings": [],
    }


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _section_path(cwd: str | Path, section: str) -> Path:
    if not SECTION_PATTERN.match(section):
        raise ValueError("section must contain only letters, numbers, underscores, and hyphens")
    return local_memory_dir(cwd) / f"{section}.md"


def _read_memory_path(path: Path) -> tuple[str, dict[str, Any], str, str | None]:
    try:
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        return path.stem, {}, "", f"{path}: {exc}"
    section = str(metadata.get("section") or path.stem)
    return section, metadata, body, None


def _ordered_context_files(cwd: str) -> list[Path]:
    local_files = [
        path
        for path in _iter_markdown_files(local_memory_dir(cwd))
        if "private" not in path.parts and "snapshots" not in path.parts
    ]
    global_files = [
        path
        for path in _iter_markdown_files(global_memory_dir())
        if path.name != "directives.md"
    ]

    def local_sort_key(path: Path) -> tuple[int, int, str]:
        metadata, _body, _warning = _safe_parse_for_sort(path)
        priority = str(metadata.get("priority") or "medium")
        index_rank = 0 if path.name == "index.md" else 1
        return (PRIORITY_ORDER.get(priority, 1), index_rank, path.name)

    high_and_medium = [path for path in local_files if local_sort_key(path)[0] in {0, 1}]
    low = [path for path in local_files if local_sort_key(path)[0] >= 3]
    return sorted(high_and_medium, key=local_sort_key) + sorted(global_files) + sorted(low, key=local_sort_key)


def _safe_parse_for_sort(path: Path) -> tuple[dict[str, Any], str, str | None]:
    try:
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        return metadata, body, None
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        return {}, "", str(exc)


def _iter_markdown_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def _section_key(path: Path, section: str) -> str:
    if ".ai-memory" in path.parts:
        return f"local/{section}"
    return f"global/{section}"


def _format_fragment(section: str, text: str) -> str:
    return f"<!-- memory-fabric:{section} -->\n{text.strip()}"


def _keyword_search_rg(query: str, roots: list[Path], max_results: int) -> list[SearchResult]:
    command = [
        "rg",
        "--json",
        "--ignore-case",
        "--fixed-strings",
        query,
        *[str(root) for root in roots],
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
        results.append(
            {
                "section": path.stem,
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
            for line_number, line in enumerate(lines, start=1):
                if needle in line.lower():
                    results.append(
                        {
                            "section": path.stem,
                            "path": str(path),
                            "line": line_number,
                            "snippet": line.strip(),
                        }
                    )
                    if len(results) >= max_results:
                        return results
    return results


def _regenerate_index(cwd: str, mode: str) -> list[str]:
    memory_dir = local_memory_dir(cwd)
    checked_files = [str(path) for path in _iter_markdown_files(memory_dir) if path.name != "index.md"]
    lines = [
        "# Project Memory Index",
        "",
        f"Updated by Memory Fabric Dreaming mode `{mode}` at {now_iso()}.",
        "",
        "| Section | Priority | Summary |",
        "| --- | --- | --- |",
    ]
    for path in _iter_markdown_files(memory_dir):
        if path.name == "index.md" or "snapshots" in path.parts:
            continue
        metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        section = metadata.get("section", path.stem)
        priority = metadata.get("priority", "medium")
        summary = str(metadata.get("summary", "")).replace("|", "\\|")
        lines.append(f"| `{section}` | {priority} | {summary} |")

    index_path = memory_dir / "index.md"
    if index_path.exists():
        metadata, _body = parse_frontmatter(index_path.read_text(encoding="utf-8"))
    else:
        metadata, _body = parse_frontmatter(build_empty_section("index"))
    metadata["last_updated"] = now_iso()
    metadata["summary"] = "Map of available project memory sections."
    metadata["priority"] = "high"
    index_path.write_text(dump_frontmatter(metadata, "\n".join(lines) + "\n"), encoding="utf-8")
    return checked_files
