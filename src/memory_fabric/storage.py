"""Core Memory Fabric operations."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterable

from memory_fabric.contracts import (
    ContextBundle,
    DoctorResult,
    DreamConsolidation,
    DreamResult,
    DreamRewriteTask,
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
from memory_fabric.llm import call_llm


SECTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 3}


def initialize_memory_fabric(cwd: str, install_hooks: bool = False) -> InitResult:
    root = project_root(cwd)
    memory_dir = local_memory_dir(root)
    memory_dir.mkdir(parents=True, exist_ok=True)

    files_created: list[str] = []
    warnings: list[str] = []
    for section in SECTION_TEMPLATES:
        path = memory_dir / f"{section}.md"
        if not path.exists():
            path.write_text(build_memory_file(section), encoding="utf-8")
            files_created.append(str(path))

    gitignore = memory_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(LOCAL_GITIGNORE, encoding="utf-8")
        files_created.append(str(gitignore))

    if install_hooks:
        git_dir = root / ".git"
        if git_dir.exists() and git_dir.is_dir():
            hooks_dir = git_dir / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            post_commit = hooks_dir / "post-commit"
            
            hook_cmd = "ai-memory dream --mode light --apply || true"
            if post_commit.exists():
                existing_content = post_commit.read_text(encoding="utf-8")
                if hook_cmd not in existing_content:
                    separator = "\n" if existing_content.endswith("\n") else "\n\n"
                    new_content = existing_content + separator + f"# Added by Memory Fabric installer\n{hook_cmd}\n"
                    post_commit.write_text(new_content, encoding="utf-8")
                    files_created.append(str(post_commit))
            else:
                hook_content = (
                    "#!/bin/sh\n"
                    "# Memory Fabric post-commit hook\n"
                    "echo \"Running Memory Fabric Dreaming...\"\n"
                    f"{hook_cmd}\n"
                )
                post_commit.write_text(hook_content, encoding="utf-8")
                files_created.append(str(post_commit))
                
            if os.name != "nt":
                try:
                    mode = post_commit.stat().st_mode
                    post_commit.chmod(mode | 0o111)
                except Exception as exc:
                    warnings.append(f"Failed to set executable permissions on post-commit hook: {exc}")
        else:
            warnings.append("Git repository not found; post-commit hook was not installed.")

    return {
        "created": bool(files_created),
        "memory_dir": str(memory_dir),
        "files_created": files_created,
        "warnings": warnings,
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
    
    with locked_file(path):
        if path.exists():
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        else:
            metadata, body = parse_frontmatter(build_empty_section(section))

        # Check if the input content starts with frontmatter, and extract it
        input_body = content
        if content.lstrip().startswith("---"):
            try:
                input_meta, parsed_body = parse_frontmatter(content)
                input_body = parsed_body
                # Merge metadata fields except core managed fields
                for k, v in input_meta.items():
                    if k not in {"section", "last_updated", "schema_version"}:
                        metadata[k] = v
            except Exception:
                pass

        redacted, redactions = redact_secrets(input_body)
        warnings = ["Detected and redacted secrets before writing memory."] if redactions else []

        metadata["section"] = section
        metadata["last_updated"] = now_iso()

        changed = True
        if mode == "replace":
            new_body = redacted.strip() + "\n"
        else:
            clean_existing = body.rstrip()
            clean_new = redacted.strip()
            
            # Prevent duplicate lines/bullets during append
            if clean_existing and clean_new:
                existing_lines = {line.strip().lower() for line in clean_existing.splitlines() if line.strip()}
                # Remove common list prefixes for better duplicate detection
                existing_normalized = {re.sub(r"^[-*+]\s+", "", line).strip() for line in existing_lines}
                
                new_lines = clean_new.splitlines()
                filtered_lines = []
                for line in new_lines:
                    stripped = line.strip()
                    if not stripped:
                        filtered_lines.append(line)
                        continue
                    norm_line = re.sub(r"^[-*+]\s+", "", stripped).strip().lower()
                    if norm_line in existing_normalized or stripped.lower() in existing_lines:
                        continue
                    filtered_lines.append(line)
                
                clean_new = "\n".join(filtered_lines).strip()
                
            if clean_existing and clean_new:
                new_body = clean_existing + "\n\n" + clean_new + "\n"
            elif clean_new:
                new_body = clean_new + "\n"
            elif clean_existing:
                new_body = clean_existing + "\n"
                changed = False
                warnings.append("No new unique memory content was appended (duplicates filtered).")
            else:
                new_body = ""
                changed = False

        if changed:
            path.write_text(dump_frontmatter(metadata, new_body), encoding="utf-8")

    return {
        "changed": changed,
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
    
    sizes: dict[str, dict[str, int]] = {}
    if memory_dir.exists():
        for path in _iter_markdown_files(memory_dir):
            if _is_ignored_local_memory_path(memory_dir, path):
                continue
            try:
                content = path.read_text(encoding="utf-8")
                sizes[path.name] = {
                    "bytes": len(content.encode("utf-8")),
                    "tokens": estimate_tokens(content),
                }
            except Exception:
                pass

    return {
        "cwd": str(project_root(cwd)),
        "memory_dir": str(memory_dir),
        "memory_exists": memory_dir.exists(),
        "global_dir": str(global_memory_dir()),
        "provider_configured": bool(os.environ.get("MEMORY_FABRIC_LLM_PROVIDER")),
        "local_files": local_files,
        "memory_sizes": sizes,
    }


def doctor(cwd: str) -> DoctorResult:
    memory_dir = local_memory_dir(cwd)
    errors: list[str] = []
    warnings: list[str] = []
    checked_files: list[str] = []

    if not memory_dir.exists():
        errors.append(f"Local memory directory does not exist: {memory_dir}")
        return {"ok": False, "errors": errors, "warnings": warnings, "checked_files": checked_files}

    # Check directory permissions
    if not os.access(memory_dir, os.R_OK):
        errors.append(f"Memory directory is not readable: {memory_dir}")
    if not os.access(memory_dir, os.W_OK):
        errors.append(f"Memory directory is not writable: {memory_dir}")

    # Validate MCP availability
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ImportError:
        warnings.append("Optional package `mcp` is not installed; MCP server tools will be unavailable.")

    for path in _iter_markdown_files(memory_dir):
        checked_files.append(str(path))
        # Check permissions
        if not os.access(path, os.R_OK):
            errors.append(f"File is not readable: {path}")
        if not os.access(path, os.W_OK):
            errors.append(f"File is not writable: {path}")

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

    index_path = memory_dir / "index.md"
    if not index_path.exists():
        warnings.append("index.md is missing")
    else:
        try:
            index_metadata, index_body = parse_frontmatter(index_path.read_text(encoding="utf-8"))
            listed_sections = set()
            for line in index_body.splitlines():
                if line.strip().startswith("|") and not line.strip().startswith("| ---"):
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if parts:
                        sec_raw = parts[0]
                        if sec_raw.startswith("`") and sec_raw.endswith("`"):
                            listed_sections.add(sec_raw.strip("`"))
            
            existing_sections = {
                path.stem
                for path in _iter_markdown_files(memory_dir)
                if path.name != "index.md" and not _is_ignored_local_memory_path(memory_dir, path)
            }
            
            missing_in_index = existing_sections - listed_sections
            extra_in_index = listed_sections - existing_sections
            
            for sec in missing_in_index:
                warnings.append(f"Section `{sec}` exists in local memory but is missing from index.md")
            for sec in extra_in_index:
                warnings.append(f"Section `{sec}` is listed in index.md but the corresponding file does not exist")
        except Exception as exc:
            errors.append(f"Failed to check index consistency: {exc}")

    if not shutil.which("rg"):
        warnings.append("rg not found; keyword search will use Python fallback")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_files": checked_files,
    }


def _is_llm_ready() -> bool:
    provider = (os.environ.get("MEMORY_FABRIC_LLM_PROVIDER") or "").strip().lower()
    if not provider:
        return False
    if provider == "gemini" and os.environ.get("GEMINI_API_KEY"):
        return True
    if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        return True
    if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return True
    return False


def dream(
    cwd: str,
    mode: str = "light",
    apply: bool = False,
    llm_rewrite: bool = False,
    max_rewrite_tasks: int = 5,
) -> DreamResult:
    if mode not in {"light", "deep"}:
        raise ValueError("mode must be 'light' or 'deep'")
    if max_rewrite_tasks < 0:
        raise ValueError("max_rewrite_tasks must be >= 0")

    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        initialize_memory_fabric(cwd)

    snapshot = create_snapshot(cwd)
    candidate_root = _create_candidate_store(memory_dir, snapshot)

    # Ingest external inputs
    git_diff_text = _get_git_diff(cwd)
    session_text = ""
    tool_calls_text = ""
    
    session_path = memory_dir / "private" / "session_transcripts.md"
    if session_path.exists():
        try:
            session_text = session_path.read_text(encoding="utf-8")
        except Exception:
            pass
            
    tool_calls_path = memory_dir / "private" / "tool_calls.jsonl"
    if tool_calls_path.exists():
        try:
            tool_calls_text = tool_calls_path.read_text(encoding="utf-8")
        except Exception:
            pass

    warnings: list[str] = []
    llm_active = _is_llm_ready()
    
    duplicates_found = 0
    lines_removed = 0
    files_touched: list[str] = []

    if llm_active:
        try:
            # 1. Read files into payload
            sections_data = {}
            for path in _iter_markdown_files(candidate_root):
                if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
                    continue
                metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                sec_name = metadata.get("section", path.stem)
                sections_data[sec_name] = body

            # 2. Build consolidation prompt
            prompt = (
                "You are an AI memory consolidation assistant. Below is the project memory index and section bodies.\n"
                "Review the sections to: (1) merge redundant facts or guidelines, (2) resolve overlapping points, "
                "(3) check for contradiction warnings between files, and (4) incorporate recent Git logs/transcripts if provided.\n\n"
            )
            if git_diff_text:
                prompt += f"Recent Git Diff/Logs:\n{git_diff_text}\n\n"
            if session_text:
                prompt += f"Recent Session Transcripts:\n{session_text}\n\n"
            if tool_calls_text:
                prompt += f"Recent Tool Calls:\n{tool_calls_text}\n\n"

            prompt += "Active Project Memory Sections:\n" + json.dumps(sections_data, indent=2) + "\n\n"
            prompt += (
                "Output a JSON object ONLY, with no surrounding markdown or explanation, matching this schema:\n"
                "{\n"
                '  "consolidated_files": {\n'
                '    "section_name": "clean markdown body text",\n'
                "    ...\n"
                "  },\n"
                '  "contradictions": ["description of contradiction", ...],\n'
                '  "warnings": ["warning note", ...]\n'
                "}"
            )

            response_str = call_llm(prompt, "You are a software architect memory consolidation agent.")
            cleaned_resp = response_str.strip()
            if cleaned_resp.startswith("```"):
                lines = cleaned_resp.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned_resp = "\n".join(lines).strip()

            resp_data = json.loads(cleaned_resp)
            consolidated_files = resp_data.get("consolidated_files", {})
            for sec_name, new_body in consolidated_files.items():
                if not SECTION_PATTERN.match(sec_name):
                    warnings.append(f"Consolidation skipped section with invalid name: {sec_name}")
                    continue
                sec_path = candidate_root / f"{sec_name}.md"
                if sec_path.exists():
                    metadata, old_body = parse_frontmatter(sec_path.read_text(encoding="utf-8"))
                else:
                    metadata, old_body = parse_frontmatter(build_empty_section(sec_name))
                
                if old_body.strip() != new_body.strip():
                    files_touched.append(f"{sec_name}.md")
                    duplicates_found += 1
                    lines_removed += max(0, len(old_body.splitlines()) - len(new_body.splitlines()))
                    sec_path.write_text(dump_frontmatter(metadata, new_body), encoding="utf-8")

            for c in resp_data.get("contradictions", []):
                warnings.append(f"Contradiction detected: {c}")
            for w in resp_data.get("warnings", []):
                warnings.append(f"Consolidation warning: {w}")

        except Exception as exc:
            warnings.append(f"LLM-based consolidation failed; falling back to local. Error: {exc}")
            local_c = _consolidate_candidate_memory(candidate_root)
            duplicates_found = local_c["duplicates_found"]
            lines_removed = local_c["lines_removed"]
            files_touched = local_c["files_touched"]
    else:
        local_c = _consolidate_candidate_memory(candidate_root)
        duplicates_found = local_c["duplicates_found"]
        lines_removed = local_c["lines_removed"]
        files_touched = local_c["files_touched"]

    consolidation: DreamConsolidation = {
        "duplicates_found": duplicates_found,
        "lines_removed": lines_removed,
        "files_touched": sorted(files_touched),
    }

    # Now regenerate the index file in the candidate store
    checked_files = _regenerate_index_root(candidate_root, mode=mode)

    # 3. LLM-based Summarization / Summary refreshing
    if llm_active:
        for path in _iter_markdown_files(candidate_root):
            if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
                continue
            try:
                metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                sec_name = metadata.get("section", path.stem)
                sum_prompt = (
                    f"Generate a concise, 1-sentence summary of the following project memory section named `{sec_name}`. "
                    "The summary must be informative, help coding assistants decide when to read this file, and be under 150 characters. "
                    "Output ONLY the summary text, no quotes or intro:\n\n"
                    f"{body}"
                )
                new_summary = call_llm(sum_prompt, "You are a concise summarizer of software documentation.")
                new_summary_clean = new_summary.strip().strip('"\'')
                if new_summary_clean and len(new_summary_clean) > 5:
                    metadata["summary"] = new_summary_clean
                    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
            except Exception as exc:
                warnings.append(f"Failed to generate summary for `{path.name}`: {exc}")

    # Stale section detection in candidate files
    now_dt = datetime.now(timezone.utc)
    for path in _iter_markdown_files(candidate_root):
        if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            lu_str = metadata.get("last_updated")
            if lu_str:
                lu_dt = datetime.fromisoformat(lu_str.replace("Z", "+00:00"))
                if lu_dt.tzinfo is None:
                    lu_dt = lu_dt.replace(tzinfo=timezone.utc)
                if (now_dt - lu_dt).days > 30:
                    if metadata.get("review_status") != "stale":
                        metadata["review_status"] = "stale"
                        path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
                        warnings.append(f"Section `{metadata.get('section', path.stem)}` has not been updated in over 30 days and is marked as stale.")
        except Exception:
            pass

    # Secret scanning on inputs and candidate files
    redactions = 0
    if git_diff_text:
        _, r_count = redact_secrets(git_diff_text)
        redactions += r_count
    if session_text:
        _, r_count = redact_secrets(session_text)
        redactions += r_count
    if tool_calls_text:
        _, r_count = redact_secrets(tool_calls_text)
        redactions += r_count

    for path in _iter_markdown_files(candidate_root):
        try:
            text = path.read_text(encoding="utf-8")
            redacted, r_count = redact_secrets(text)
            if r_count > 0:
                path.write_text(redacted, encoding="utf-8")
                redactions += r_count
        except Exception:
            pass

    if redactions > 0:
        warnings.append(f"Detected and redacted {redactions} secrets during Dreaming.")

    patch_preview, affected_files = _diff_memory_roots(memory_dir, candidate_root)
    rewrite_tasks = _build_rewrite_tasks(candidate_root, max_rewrite_tasks=max_rewrite_tasks)

    if not apply:
        warnings.append("Dreaming generated a non-destructive candidate store; apply changes explicitly to update live memory.")
    if llm_rewrite:
        provider = os.environ.get("MEMORY_FABRIC_LLM_PROVIDER")
        if not provider:
            warnings.append("No LLM provider configured; generated local rewrite tasks for an external agent instead.")
        else:
            warnings.append(
                f"Provider `{provider}` is configured, but this build uses agent-assisted rewrite tasks and does not call provider adapters directly."
            )
    elif not os.environ.get("MEMORY_FABRIC_LLM_PROVIDER"):
        warnings.append("No LLM provider configured; ran local maintenance only.")

    changed = False
    if apply and affected_files:
        _apply_candidate_to_live(memory_dir, candidate_root, affected_files)
        changed = True

    return {
        "changed": changed,
        "snapshot": snapshot,
        "warnings": warnings,
        "checked_files": checked_files,
        "candidate_store": str(candidate_root),
        "patch_preview": patch_preview,
        "affected_files": affected_files,
        "consolidation": consolidation,
        "rewrite_tasks": rewrite_tasks if llm_rewrite else [],
        "apply_required": not apply,
        "redactions": redactions,
    }


def _get_git_diff(cwd: str) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False
        )
        if res.returncode != 0 or "true" not in res.stdout.lower():
            return ""
            
        git_info = []
        
        # Git diff
        res_diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False
        )
        if res_diff.returncode == 0 and res_diff.stdout.strip():
            git_info.append("=== Git Working Copy Diff ===\n" + res_diff.stdout)
            
        # Git recent log
        res_log = subprocess.run(
            ["git", "log", "-n", "5", "--oneline"],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False
        )
        if res_log.returncode == 0 and res_log.stdout.strip():
            git_info.append("=== Recent Git Commits ===\n" + res_log.stdout)
            
        return "\n\n".join(git_info)
    except Exception:
        pass
    return ""


def create_snapshot(cwd: str, name: str | None = None) -> str:
    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        raise FileNotFoundError(f"Local memory directory does not exist: {memory_dir}")

    snapshot_name = name or "memory-" + now_iso().replace(":", "").replace("+", "_").replace("-", "")
    snapshot_dir = memory_dir / "snapshots" / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for path in _iter_markdown_files(memory_dir):
        if _is_ignored_local_memory_path(memory_dir, path):
            continue
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
    memory_dir = local_memory_dir(cwd)
    local_files = [
        path
        for path in _iter_markdown_files(memory_dir)
        if not _is_ignored_local_memory_path(memory_dir, path)
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


def _is_ignored_local_memory_path(memory_dir: Path, path: Path) -> bool:
    try:
        relative_parts = path.relative_to(memory_dir).parts
    except ValueError:
        return False
    return bool({"private", "snapshots", "evals", "candidates"}.intersection(relative_parts))


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
    return _regenerate_index_root(memory_dir, mode=mode)


def _regenerate_index_root(memory_dir: Path, mode: str) -> list[str]:
    checked_files = [
        str(path)
        for path in _iter_markdown_files(memory_dir)
        if path.name != "index.md" and not _is_ignored_local_memory_path(memory_dir, path)
    ]
    lines = [
        "# Project Memory Index",
        "",
        f"Updated by Memory Fabric Dreaming mode `{mode}` at {now_iso()}.",
        "",
        "| Section | Priority | Summary |",
        "| --- | --- | --- |",
    ]
    for path in _iter_markdown_files(memory_dir):
        if path.name == "index.md" or _is_ignored_local_memory_path(memory_dir, path):
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


def _create_candidate_store(memory_dir: Path, snapshot: str) -> Path:
    source = memory_dir / "snapshots" / snapshot
    if not source.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot}")

    candidates_dir = memory_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    candidate_root = Path(tempfile.mkdtemp(prefix=f"{snapshot}-", dir=str(candidates_dir)))
    for path in _iter_markdown_files(source):
        relative = path.relative_to(source)
        target = candidate_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return candidate_root


def _consolidate_candidate_memory(candidate_root: Path) -> DreamConsolidation:
    seen: dict[str, tuple[str, int]] = {}
    files_touched: list[str] = []
    duplicates_found = 0
    lines_removed = 0

    for path in sorted(path for path in _iter_markdown_files(candidate_root) if path.name != "index.md"):
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        original_lines = body.splitlines()
        deduped_lines: list[str] = []
        removed_this_file = 0

        for line_number, line in enumerate(original_lines, start=1):
            normalized = _normalize_dedupe_line(line)
            if not normalized:
                deduped_lines.append(line)
                continue
            if normalized in seen:
                duplicates_found += 1
                lines_removed += 1
                removed_this_file += 1
                continue
            seen[normalized] = (str(path.relative_to(candidate_root)), line_number)
            deduped_lines.append(line)

        if removed_this_file:
            path.write_text(dump_frontmatter(metadata, "\n".join(deduped_lines) + "\n"), encoding="utf-8")
            files_touched.append(str(path.relative_to(candidate_root)))

    return {
        "duplicates_found": duplicates_found,
        "lines_removed": lines_removed,
        "files_touched": sorted(files_touched),
    }


def _normalize_dedupe_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("#"):
        return None
    cleaned = re.sub(r"^[-*+]\s+", "", stripped)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    if len(cleaned) < 24:
        return None
    return cleaned


def _diff_memory_roots(before_root: Path, after_root: Path) -> tuple[str, list[str]]:
    relative_paths = sorted(
        set(_relative_markdown_paths(before_root, ignore_local_paths=True))
        | set(_relative_markdown_paths(after_root, ignore_local_paths=False))
    )
    patch_fragments: list[str] = []
    changed: list[str] = []

    for relative in relative_paths:
        before_path = before_root / relative
        after_path = after_root / relative
        before_text = before_path.read_text(encoding="utf-8") if before_path.exists() else ""
        after_text = after_path.read_text(encoding="utf-8") if after_path.exists() else ""
        if before_text == after_text:
            continue
        changed.append(str(relative))
        patch_fragments.append(
            "".join(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True),
                    after_text.splitlines(keepends=True),
                    fromfile=str(before_path),
                    tofile=str(after_path),
                )
            )
        )

    return "".join(patch_fragments), changed


def _relative_markdown_paths(root: Path, ignore_local_paths: bool = False) -> set[Path]:
    if not root.exists():
        return set()
    paths: set[Path] = set()
    for path in _iter_markdown_files(root):
        if ignore_local_paths and _is_ignored_local_memory_path(root, path):
            continue
        paths.add(path.relative_to(root))
    return paths


def _apply_candidate_to_live(memory_dir: Path, candidate_root: Path, affected_files: list[str]) -> None:
    for relative_text in affected_files:
        relative = Path(relative_text)
        source = candidate_root / relative
        target = memory_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            with locked_file(target):
                shutil.copy2(source, target)
            continue
        if target.exists():
            with locked_file(target):
                target.unlink()


def _build_rewrite_tasks(candidate_root: Path, max_rewrite_tasks: int) -> list[DreamRewriteTask]:
    tasks: list[DreamRewriteTask] = []
    for path in sorted(path for path in _iter_markdown_files(candidate_root) if path.name != "index.md"):
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        section = str(metadata.get("section") or path.stem)
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if len(lines) < 5:
            reason = "Section is short and may benefit from enrichment with concrete details."
        elif len(lines) > 80:
            reason = "Section is long and may benefit from compression and clearer structure."
        else:
            continue
        tasks.append(
            {
                "section": section,
                "reason": reason,
                "instruction": (
                    f"Rewrite section `{section}` to preserve factual content while improving clarity, "
                    "removing repetition, and keeping frontmatter unchanged. Return a unified diff patch."
                ),
            }
        )
        if len(tasks) >= max_rewrite_tasks:
            break
    return tasks
