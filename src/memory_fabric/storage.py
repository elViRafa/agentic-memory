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
    StoreEntry,
    StoreListResult,
    StoreReadResult,
    StoreWriteResult,
    WriteMode,
    WriteResult,
)
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.locking import locked_file
from memory_fabric.paths import global_memory_dir, local_memory_dir, memory_store_dir, project_root
from memory_fabric.security import redact_secrets
from memory_fabric.templates import (
    LOCAL_GITIGNORE,
    SECTION_TEMPLATES,
    build_empty_section,
    build_memory_file,
    now_iso,
    build_agents_md,
    build_agents_rule_memory,
    build_agents_rule_dreaming,
    build_cursor_rule,
    build_windsurf_rule,
    build_claude_md,
    build_copilot_md,
)
from memory_fabric.llm import call_llm
from memory_fabric.version import __version__



SECTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
STORE_PATH_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 3}


def _validate_store_path(store_path: str) -> list[str]:
    """Validate a semantic store path like 'architecture/decisions/auth-service'.

    Returns a list of validated segments, or raises ValueError.
    """
    segments = store_path.strip("/").split("/")
    if not segments or segments == [""]:
        raise ValueError("store_path must not be empty")
    if len(segments) > 5:
        raise ValueError("store_path must not exceed 5 levels of nesting")
    for seg in segments:
        if not STORE_PATH_SEGMENT.match(seg):
            raise ValueError(
                f"Invalid store_path segment '{seg}': "
                "must be lowercase alphanumeric, starting with a letter or digit, "
                "using only a-z, 0-9, hyphens, and underscores"
            )
    return segments


def _resolve_store_file(cwd: str, store_path: str) -> Path:
    """Resolve a semantic store path to an absolute filesystem path."""
    segments = _validate_store_path(store_path)
    filename = segments[-1] + ".md"
    dir_segments = segments[:-1]
    store_root = memory_store_dir(cwd)
    target_dir = store_root
    for seg in dir_segments:
        target_dir = target_dir / seg
    return target_dir / filename


def _path_to_store_path(store_root: Path, file_path: Path) -> str:
    """Convert an absolute file path inside memory-store/ to a store_path string."""
    relative = file_path.relative_to(store_root)
    parts = list(relative.parts)
    # Remove .md extension from last segment
    if parts and parts[-1].endswith(".md"):
        parts[-1] = parts[-1][:-3]
    return "/".join(parts)


def initialize_memory_fabric(
    cwd: str,
    install_hooks: bool = False,
    memory_prompt: str | None = None,
) -> InitResult:
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

    # Create memory-store directory with .gitkeep
    store_dir = memory_store_dir(root)
    store_dir.mkdir(parents=True, exist_ok=True)
    gitkeep = store_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")
        files_created.append(str(gitkeep))

    if memory_prompt is not None:
        prompt_path = memory_dir / "memory_prompt.txt"
        if memory_prompt.strip():
            prompt_path.write_text(memory_prompt.strip() + "\n", encoding="utf-8")
            files_created.append(str(prompt_path))
        elif prompt_path.exists():
            prompt_path.unlink()

    # Deploy Agent Instructions and Rules to all supported platforms
    def _deploy_file(path: Path, content: str, append_if_exists: bool = False) -> None:
        """Write a file if it doesn't exist, or append Memory Fabric block if requested."""
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            files_created.append(str(path))
        elif append_if_exists:
            existing = path.read_text(encoding="utf-8")
            if "Memory Fabric" not in existing:
                separator = "\n" if existing.endswith("\n") else "\n\n"
                path.write_text(existing + separator + content, encoding="utf-8")
                files_created.append(str(path) + " (appended)")

    # Universal fallback (Gemini CLI, Codex, Antigravity)
    _deploy_file(root / "AGENTS.md", build_agents_md())

    # Generic IDE rules (.agents/rules/) — Cline, generic agents
    agents_rules_dir = root / ".agents" / "rules"
    agents_rules_dir.mkdir(parents=True, exist_ok=True)
    _deploy_file(agents_rules_dir / "memory-store.md", build_agents_rule_memory())
    _deploy_file(agents_rules_dir / "dreaming.md", build_agents_rule_dreaming())

    # Cursor IDE (.cursor/rules/*.mdc)
    cursor_rules_dir = root / ".cursor" / "rules"
    cursor_rules_dir.mkdir(parents=True, exist_ok=True)
    _deploy_file(cursor_rules_dir / "memory-fabric.mdc", build_cursor_rule())

    # Windsurf IDE (.windsurf/rules/*.md)
    windsurf_rules_dir = root / ".windsurf" / "rules"
    windsurf_rules_dir.mkdir(parents=True, exist_ok=True)
    _deploy_file(windsurf_rules_dir / "memory-fabric.md", build_windsurf_rule())

    # Claude Code (CLAUDE.md) — create or append
    _deploy_file(root / "CLAUDE.md", build_claude_md(), append_if_exists=True)

    # GitHub Copilot (.github/copilot-instructions.md) — create or append
    github_dir = root / ".github"
    github_dir.mkdir(parents=True, exist_ok=True)
    _deploy_file(github_dir / "copilot-instructions.md", build_copilot_md(), append_if_exists=True)

    if install_hooks:
        git_dir = root / ".git"
        if git_dir.exists() and git_dir.is_dir():
            hooks_dir = git_dir / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            
            # Post-commit hook (Dreaming)
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
                
            # Pre-commit hook (Agent Rules Sync)
            pre_commit = hooks_dir / "pre-commit"
            sync_cmd = "ai-memory sync-agents || true"
            add_cmd = "git add .agents/rules/ .cursor/rules/memory-fabric.mdc .windsurf/rules/memory-fabric.md CLAUDE.md .github/copilot-instructions.md 2>/dev/null || true"
            if pre_commit.exists():
                existing_content = pre_commit.read_text(encoding="utf-8")
                if sync_cmd not in existing_content:
                    separator = "\n" if existing_content.endswith("\n") else "\n\n"
                    new_content = existing_content + separator + f"# Added by Memory Fabric installer\n{sync_cmd}\n{add_cmd}\n"
                    pre_commit.write_text(new_content, encoding="utf-8")
                    files_created.append(str(pre_commit))
            else:
                hook_content = (
                    "#!/bin/sh\n"
                    "# Memory Fabric pre-commit hook\n"
                    "echo \"Syncing Memory Fabric Agent Rules...\"\n"
                    f"{sync_cmd}\n"
                    f"{add_cmd}\n"
                )
                pre_commit.write_text(hook_content, encoding="utf-8")
                files_created.append(str(pre_commit))

            if os.name != "nt":
                try:
                    for hook_file in [post_commit, pre_commit]:
                        mode = hook_file.stat().st_mode
                        hook_file.chmod(mode | 0o111)
                except Exception as exc:
                    warnings.append(f"Failed to set executable permissions on git hooks: {exc}")
        else:
            warnings.append("Git repository not found; hooks were not installed.")

    return {
        "created": bool(files_created),
        "memory_dir": str(memory_dir),
        "files_created": files_created,
        "warnings": warnings,
    }


def sync_agent_rules(cwd: str) -> dict[str, Any]:
    """Regenerate all agent instruction files from canonical templates.

    This does NOT read from AGENTS.md. Instead, it regenerates all platform-specific
    files directly from the canonical templates in templates.py, guaranteeing
    consistency. AGENTS.md itself is left untouched so users can add project-specific
    context to it without fear of it leaking into IDE rule files.
    """
    root = project_root(cwd)
    synced_files: list[str] = []

    def _write_if_different(path: Path, content: str) -> None:
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        synced_files.append(str(path))

    # Generic IDE rules
    _write_if_different(root / ".agents" / "rules" / "memory-store.md", build_agents_rule_memory())
    _write_if_different(root / ".agents" / "rules" / "dreaming.md", build_agents_rule_dreaming())

    # Cursor
    _write_if_different(root / ".cursor" / "rules" / "memory-fabric.mdc", build_cursor_rule())

    # Windsurf
    _write_if_different(root / ".windsurf" / "rules" / "memory-fabric.md", build_windsurf_rule())

    # Claude Code — only update if Memory Fabric content already exists (don't create)
    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        existing = claude_md.read_text(encoding="utf-8")
        if "Memory Fabric" in existing:
            new_content = re.sub(
                r"(?:# Agent Instructions — Memory Fabric|## Memory Fabric — Semantic Store Agent Instructions).*$",
                build_claude_md().strip(),
                existing,
                flags=re.DOTALL,
            )
            if new_content != existing:
                claude_md.write_text(new_content, encoding="utf-8")
                synced_files.append(str(claude_md))

    # GitHub Copilot — only update if Memory Fabric content already exists
    copilot_md = root / ".github" / "copilot-instructions.md"
    if copilot_md.exists():
        existing = copilot_md.read_text(encoding="utf-8")
        if "Memory Fabric" in existing:
            new_content = re.sub(
                r"(?:# Agent Instructions — Memory Fabric|## Memory Fabric — Semantic Store Agent Instructions).*$",
                build_copilot_md().strip(),
                existing,
                flags=re.DOTALL,
            )
            if new_content != existing:
                copilot_md.write_text(new_content, encoding="utf-8")
                synced_files.append(str(copilot_md))

    return {"success": True, "message": f"Synchronized {len(synced_files)} file(s).", "synced_files": synced_files}


def read_combined_context(cwd: str, max_tokens: int = 4000) -> ContextBundle:
    warnings: list[str] = []
    included: list[str] = []
    omitted: list[str] = []
    fragments: list[str] = []
    remaining = max_tokens

    # Try to load from pre-compiled consolidated_memory.md cache to save time
    memory_dir = local_memory_dir(cwd)
    consolidated_path = memory_dir / "consolidated_memory.md"
    tier0 = global_memory_dir() / "directives.md"
    
    if consolidated_path.exists() and not tier0.exists():
        try:
            content = consolidated_path.read_text(encoding="utf-8")
            # Remove any existing memory prompt fragment in the compiled cache first to avoid duplicates or stale data
            content = re.sub(r"<!-- memory-fabric:local/memory_prompt -->\n.*?(?=\n\n<!-- memory-fabric:|$)", "", content, flags=re.DOTALL)
            
            prompt_path = memory_dir / "memory_prompt.txt"
            prompt_text = ""
            if prompt_path.exists():
                p_text = prompt_path.read_text(encoding="utf-8").strip()
                if p_text:
                    prompt_text = f"<!-- memory-fabric:local/memory_prompt -->\nMemory Prompt Steering Instructions:\n{p_text}\n\n"
            
            full_content = (prompt_text + content).strip() + "\n"
            est_tokens = estimate_tokens(full_content)
            if est_tokens <= max_tokens:
                for match in re.finditer(r"<!-- memory-fabric:([a-zA-Z0-9_/.-]+) -->", full_content):
                    included.append(match.group(1))
                return {
                    "text": full_content,
                    "included_sections": included,
                    "omitted_sections": [],
                    "token_budget": max_tokens,
                    "estimated_tokens": est_tokens,
                    "warnings": [f"Tier 0 directives not found: {tier0}"],
                }
        except Exception:
            pass

    if tier0.exists():
        text = tier0.read_text(encoding="utf-8")
        fragments.append(_format_fragment("global/directives", text))
        included.append("global/directives")
        remaining -= estimate_tokens(text)
    else:
        warnings.append(f"Tier 0 directives not found: {tier0}")

    # Load session-level memory prompt steering agent judgment
    prompt_path = memory_dir / "memory_prompt.txt"
    if prompt_path.exists():
        try:
            p_text = prompt_path.read_text(encoding="utf-8").strip()
            if p_text:
                fragments.append(_format_fragment("local/memory_prompt", f"Memory Prompt Steering Instructions:\n{p_text}"))
                included.append("local/memory_prompt")
                remaining -= estimate_tokens(p_text)
        except Exception as exc:
            warnings.append(f"Failed to read memory_prompt.txt: {exc}")

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
        "path": str(path.resolve()),
        "redactions": redactions,
        "warnings": warnings,
    }


def write_memory_store(
    cwd: str,
    store_path: str,
    content: str,
    title: str = "",
    tags: list[str] | None = None,
    priority: str = "medium",
    mode: WriteMode = "replace",
) -> StoreWriteResult:
    """Write a memory file to a semantic store path."""
    if mode not in {"append", "replace"}:
        raise ValueError("mode must be 'append' or 'replace'")
    if priority not in {"high", "medium", "low"}:
        raise ValueError("priority must be 'high', 'medium', or 'low'")

    path = _resolve_store_file(cwd, store_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with locked_file(path):
        if path.exists():
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        else:
            display_title = title or store_path.split("/")[-1].replace("-", " ").title()
            metadata = {
                "store_path": store_path,
                "title": display_title,
                "summary": f"Memory: {display_title}.",
                "priority": priority,
                "tags": tags or [],
                "schema_version": "1.3",
            }
            body = ""

        # Check if the input content starts with frontmatter, and extract it
        input_body = content
        if content.lstrip().startswith("---"):
            try:
                input_meta, parsed_body = parse_frontmatter(content)
                input_body = parsed_body
                for k, v in input_meta.items():
                    if k not in {"store_path", "last_updated", "schema_version"}:
                        metadata[k] = v
            except Exception:
                pass

        redacted, redactions = redact_secrets(input_body)
        warnings: list[str] = ["Detected and redacted secrets before writing memory."] if redactions else []

        # Update metadata
        metadata["store_path"] = store_path
        metadata["last_updated"] = now_iso()
        if title:
            metadata["title"] = title
        if tags is not None:
            metadata["tags"] = tags
        if priority:
            metadata["priority"] = priority

        changed = True
        if mode == "replace":
            new_body = redacted.strip() + "\n"
        else:
            clean_existing = body.rstrip()
            clean_new = redacted.strip()

            if clean_existing and clean_new:
                existing_lines = {line.strip().lower() for line in clean_existing.splitlines() if line.strip()}
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
            # Auto-generate summary from title or first content line
            first_line = new_body.strip().split("\n")[0].strip() if new_body.strip() else ""
            if title:
                metadata["summary"] = title[:150]
            elif first_line and first_line != metadata.get("summary", ""):
                summary_text = first_line.lstrip("#").strip()
                if len(summary_text) > 150:
                    summary_text = summary_text[:147] + "..."
                metadata["summary"] = summary_text

            path.write_text(dump_frontmatter(metadata, new_body), encoding="utf-8")

    return {
        "changed": changed,
        "path": str(path.resolve()),
        "store_path": store_path,
        "redactions": redactions,
        "warnings": warnings,
    }


def read_memory_store(
    cwd: str,
    store_path: str,
    max_tokens: int = 8000,
) -> StoreReadResult:
    """Read a single memory-store file by its semantic path."""
    path = _resolve_store_file(cwd, store_path)
    warnings: list[str] = []
    if not path.exists():
        raise FileNotFoundError(f"Memory store file not found: {store_path}")

    metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    text = dump_frontmatter(metadata, body)
    truncated = False
    if estimate_tokens(text) > max_tokens:
        summary = str(metadata.get("summary") or "No summary available.")
        text = (
            f"Store file `{store_path}` omitted because it exceeded the token budget.\n"
            f"Summary: {summary}\n"
        )
        truncated = True
        warnings.append("Store file exceeded token budget; returned summary only.")

    return {
        "store_path": store_path,
        "path": str(path.resolve()),
        "text": text,
        "metadata": metadata,
        "truncated": truncated,
        "warnings": warnings,
    }


def list_memory_store(
    cwd: str,
    prefix: str = "",
    tags: list[str] | None = None,
    max_results: int = 50,
) -> StoreListResult:
    """List files in the memory store, optionally filtered by prefix and/or tags."""
    store_root = memory_store_dir(cwd)
    warnings: list[str] = []
    entries: list[StoreEntry] = []

    if not store_root.exists():
        return {"entries": [], "total": 0, "warnings": ["Memory store not found."]}

    for path in sorted(store_root.rglob("*.md")):
        if not path.is_file() or path.name == "index.md":
            continue

        sp = _path_to_store_path(store_root, path)

        # Filter by prefix
        if prefix and not sp.startswith(prefix.strip("/")):
            continue

        try:
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            warnings.append(f"Could not parse store file: {path}")
            continue

        file_tags = metadata.get("tags", [])
        if not isinstance(file_tags, list):
            file_tags = []

        # Filter by tags (intersection)
        if tags and not set(tags).intersection(set(file_tags)):
            continue

        entries.append({
            "store_path": sp,
            "path": str(path.resolve()),
            "summary": str(metadata.get("summary", "")),
            "priority": str(metadata.get("priority", "medium")),
            "tags": file_tags,
            "last_updated": str(metadata.get("last_updated", "")),
        })

    # Sort by priority (high first), then alphabetically
    entries.sort(key=lambda e: (PRIORITY_ORDER.get(e["priority"], 1), e["store_path"]))

    total = len(entries)
    if total > max_results:
        entries = entries[:max_results]
        warnings.append(f"Results truncated to {max_results} of {total} total entries.")

    return {"entries": entries, "total": total, "warnings": warnings}


def delete_memory_store(
    cwd: str,
    store_path: str,
) -> WriteResult:
    """Remove a store file and clean up empty parent directories."""
    path = _resolve_store_file(cwd, store_path)
    if not path.exists():
        raise FileNotFoundError(f"Memory store file not found: {store_path}")

    with locked_file(path):
        path.unlink()

    # Clean up empty parent directories within memory-store/
    store_root = memory_store_dir(cwd)
    current = path.parent
    while current != store_root and current.is_relative_to(store_root):
        try:
            remaining = [f for f in current.iterdir() if f.name != ".gitkeep"]
            if not remaining:
                # Remove .gitkeep if it exists, then the dir
                gitkeep = current / ".gitkeep"
                if gitkeep.exists():
                    gitkeep.unlink()
                current.rmdir()
                current = current.parent
            else:
                break
        except OSError:
            break

    return {
        "changed": True,
        "path": str(path.resolve()),
        "redactions": 0,
        "warnings": [],
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
        "version": __version__,
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
        if _is_ignored_local_memory_path(memory_dir, path):
            continue
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

        is_store = _is_store_path(memory_dir, path)
        name_field = "store_path" if is_store else "section"
        for field in [name_field, "summary", "priority", "tags", "schema_version", "last_updated"]:
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
            
            existing_local_sections = {
                path.stem
                for path in _iter_markdown_files(memory_dir)
                if path.name != "index.md"
                   and not _is_ignored_local_memory_path(memory_dir, path)
                   and not _is_store_path(memory_dir, path)
            }
            
            missing_in_index = existing_local_sections - listed_sections
            extra_in_index = {sec for sec in listed_sections - existing_local_sections if "/" not in sec}
            
            for sec in missing_in_index:
                warnings.append(f"Section `{sec}` exists in local memory but is missing from index.md")
            for sec in extra_in_index:
                warnings.append(f"Section `{sec}` is listed in index.md but the corresponding file does not exist")
        except Exception as exc:
            errors.append(f"Failed to check index consistency: {exc}")

    # Verify consistency of memory-store sub-index
    store_root = memory_dir / "memory-store"
    if store_root.exists():
        store_index_path = store_root / "index.md"
        if not store_index_path.exists():
            warnings.append("memory-store/index.md is missing")
        else:
            try:
                store_meta, store_body = parse_frontmatter(store_index_path.read_text(encoding="utf-8"))
                listed_store_paths = set()
                for line in store_body.splitlines():
                    if line.strip().startswith("|") and not line.strip().startswith("| ---"):
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if parts:
                            sec_raw = parts[0]
                            if sec_raw.startswith("`") and sec_raw.endswith("`"):
                                listed_store_paths.add(sec_raw.strip("`"))
                
                existing_store_paths = {
                    _path_to_store_path(store_root, path)
                    for path in _iter_markdown_files(store_root)
                    if path.name != "index.md"
                }
                
                missing_in_store_index = existing_store_paths - listed_store_paths
                extra_in_store_index = listed_store_paths - existing_store_paths
                
                for sp in missing_in_store_index:
                    warnings.append(f"Store file `{sp}` exists but is missing from memory-store/index.md")
                for sp in extra_in_store_index:
                    warnings.append(f"Store file `{sp}` is listed in memory-store/index.md but the file does not exist")
            except Exception as exc:
                errors.append(f"Failed to check memory-store index consistency: {exc}")

    if not shutil.which("rg"):
        warnings.append("rg not found; keyword search will use Python fallback")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_files": checked_files,
    }


def _is_llm_ready(context: Any = None) -> bool:
    provider = (os.environ.get("MEMORY_FABRIC_LLM_PROVIDER") or "").strip().lower()
    if provider:
        if provider == "gemini" and os.environ.get("GEMINI_API_KEY"):
            return True
        if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
            return True
        if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            return True
        if provider == "ollama":
            return True
    if context is not None:
        client_params = getattr(context.session, "client_params", None)
        if (
            client_params is not None
            and getattr(client_params, "capabilities", None) is not None
            and getattr(client_params.capabilities, "sampling", None) is not None
        ):
            return True
    return False


def _get_section_key(root: Path, path: Path) -> str:
    """Get the canonical section key relative to the root directory (live or candidate)."""
    store_root = root / "memory-store"
    if store_root.exists():
        try:
            path.relative_to(store_root)
            sp = _path_to_store_path(store_root, path)
            return f"store/{sp}"
        except ValueError:
            pass
    try:
        metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        sec_name = metadata.get("section") or path.stem
    except Exception:
        sec_name = path.stem
    return f"local/{sec_name}"


async def dream(
    cwd: str,
    mode: str = "light",
    apply: bool = False,
    llm_rewrite: bool = False,
    max_rewrite_tasks: int = 5,
    context: Any = None,
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
    llm_active = _is_llm_ready(context)
    
    duplicates_found = 0
    lines_removed = 0
    files_touched: list[str] = []

    current_consolidation_hash = None
    dream_contradictions = []
    dream_warnings = []

    if llm_active:
        try:
            # 1. Read files into payload
            sections_data = {}
            for path in _iter_markdown_files(candidate_root):
                if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
                    continue
                metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                key = _get_section_key(candidate_root, path)
                sections_data[key] = body

            # Calculate consolidation input hash
            hash_input = []
            for name in sorted(sections_data.keys()):
                hash_input.append(f"section:{name}")
                hash_input.append(sections_data[name])
            hash_input.append(f"git_diff:{git_diff_text or ''}")
            hash_input.append(f"session:{session_text or ''}")
            hash_input.append(f"tool_calls:{tool_calls_text or ''}")
            
            import hashlib
            current_consolidation_hash = hashlib.md5("\n".join(hash_input).encode("utf-8")).hexdigest()

            # Read previous consolidation metadata from index.md
            previous_consolidation_hash = None
            previous_contradictions = []
            previous_warnings = []
            index_path = memory_dir / "index.md"
            if index_path.exists():
                try:
                    index_metadata, _ = parse_frontmatter(index_path.read_text(encoding="utf-8"))
                    previous_consolidation_hash = index_metadata.get("consolidation_hash")
                    previous_contradictions = index_metadata.get("contradictions", [])
                    previous_warnings = index_metadata.get("consolidation_warnings", [])
                except Exception:
                    pass

            if previous_consolidation_hash == current_consolidation_hash:
                # Skip LLM consolidation call and use cached results
                resp_data = {
                    "consolidated_files": {},
                    "contradictions": previous_contradictions,
                    "warnings": previous_warnings
                }
            else:
                # 2. Build consolidation prompt
                prompt = (
                    "You are an AI memory consolidation assistant. Below is the project memory index and section bodies.\n"
                    "Review the sections to: (1) merge redundant facts or guidelines, (2) resolve overlapping points, "
                    "(3) check for contradiction warnings between files, and (4) incorporate recent Git logs/transcripts if provided.\n"
                    "Specifically, extract dates, specific IDs, and missing metadata from the recent transcripts or logs "
                    "to enrich the relevant memory sections. If a memory file is outdated or stale, clean it up or propose removing "
                    "redundancies.\n"
                    "Note: sections with `local/` prefix are flat top-level memory files, and sections with `store/` prefix "
                    "are semantic memory store files located in nested directories. Preserve the exact key prefixes in your response.\n\n"
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

                response_str = await call_llm(prompt, "You are a software architect memory consolidation agent.", context)
                cleaned_resp = response_str.strip()
                
                resp_data = None
                try:
                    resp_data = json.loads(cleaned_resp)
                except json.JSONDecodeError:
                    start = cleaned_resp.find('{')
                    end = cleaned_resp.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        try:
                            resp_data = json.loads(cleaned_resp[start:end+1])
                        except json.JSONDecodeError:
                            pass
                
                if resp_data is None:
                    import re
                    blocks = re.findall(r'```(?:json)?\s*(.*?)\s*```', cleaned_resp, re.DOTALL)
                    for block in blocks:
                        try:
                            resp_data = json.loads(block.strip())
                            break
                        except json.JSONDecodeError:
                            pass
                            
                if resp_data is None:
                    # Fallback to direct load to raise the JSONDecodeError
                    resp_data = json.loads(cleaned_resp)

            consolidated_files = resp_data.get("consolidated_files", {})
            for key, new_body in consolidated_files.items():
                if key.startswith("store/"):
                    store_path = key[len("store/"):]
                    try:
                        _validate_store_path(store_path)
                    except ValueError as exc:
                        warnings.append(f"Consolidation skipped store path with invalid format: {key}. Error: {exc}")
                        continue
                    
                    segments = store_path.strip("/").split("/")
                    filename = segments[-1] + ".md"
                    dir_segments = segments[:-1]
                    target_dir = candidate_root / "memory-store"
                    for seg in dir_segments:
                        target_dir = target_dir / seg
                    sec_path = target_dir / filename
                else:
                    sec_name = key[len("local/"):] if key.startswith("local/") else key
                    if not SECTION_PATTERN.match(sec_name):
                        warnings.append(f"Consolidation skipped section with invalid name: {key}")
                        continue
                    sec_path = candidate_root / f"{sec_name}.md"

                if sec_path.exists():
                    metadata, old_body = parse_frontmatter(sec_path.read_text(encoding="utf-8"))
                else:
                    if key.startswith("store/"):
                        metadata = {
                            "store_path": store_path,
                            "title": segments[-1].replace("-", " ").title(),
                            "summary": f"Memory store section for {store_path}.",
                            "priority": "medium",
                            "tags": [],
                            "schema_version": 1.3,
                            "last_updated": now_iso()
                        }
                        old_body = ""
                    else:
                        metadata, old_body = parse_frontmatter(build_empty_section(sec_name))
                
                if old_body.strip() != new_body.strip():
                    rel_path = str(sec_path.relative_to(candidate_root)).replace("\\", "/")
                    files_touched.append(rel_path)
                    duplicates_found += 1
                    lines_removed += max(0, len(old_body.splitlines()) - len(new_body.splitlines()))
                    
                    sec_path.parent.mkdir(parents=True, exist_ok=True)
                    metadata["last_updated"] = now_iso()
                    sec_path.write_text(dump_frontmatter(metadata, new_body), encoding="utf-8")

            dream_contradictions = resp_data.get("contradictions", [])
            dream_warnings = resp_data.get("warnings", [])

            for c in dream_contradictions:
                warnings.append(f"Contradiction detected: {c}")
            for w in dream_warnings:
                warnings.append(f"Consolidation warning: {w}")

            # Recalculate the hash using the final consolidated contents to ensure
            # the next run correctly identifies that consolidation has already occurred.
            if consolidated_files:
                final_sections_data = {}
                for path in _iter_markdown_files(candidate_root):
                    if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
                        continue
                    metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                    key = _get_section_key(candidate_root, path)
                    final_sections_data[key] = body

                hash_input = []
                for name in sorted(final_sections_data.keys()):
                    hash_input.append(f"section:{name}")
                    hash_input.append(final_sections_data[name])
                hash_input.append(f"git_diff:{git_diff_text or ''}")
                hash_input.append(f"session:{session_text or ''}")
                hash_input.append(f"tool_calls:{tool_calls_text or ''}")
                current_consolidation_hash = hashlib.md5("\n".join(hash_input).encode("utf-8")).hexdigest()

        except Exception as exc:
            warnings.append(f"LLM-based consolidation failed; falling back to local. Error: {exc}")
            local_c = _consolidate_candidate_memory(candidate_root)
            duplicates_found = local_c["duplicates_found"]
            lines_removed = local_c["lines_removed"]
            files_touched = local_c["files_touched"]
            current_consolidation_hash = None
            dream_contradictions = []
            dream_warnings = []
    else:
        local_c = _consolidate_candidate_memory(candidate_root)
        duplicates_found = local_c["duplicates_found"]
        lines_removed = local_c["lines_removed"]
        files_touched = local_c["files_touched"]
        current_consolidation_hash = None
        dream_contradictions = []
        dream_warnings = []

    consolidation: DreamConsolidation = {
        "duplicates_found": duplicates_found,
        "lines_removed": lines_removed,
        "files_touched": sorted(files_touched),
    }

    # 3. LLM-based Summarization / Summary refreshing
    if llm_active:
        import hashlib
        for path in _iter_markdown_files(candidate_root):
            if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
                continue
            try:
                metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                key = _get_section_key(candidate_root, path)
                
                body_hash = hashlib.md5(body.strip().encode("utf-8")).hexdigest()
                current_hash = metadata.get("summary_hash")
                current_summary = metadata.get("summary")
                
                is_store = key.startswith("store/")
                store_path = key[len("store/"):] if is_store else ""
                sec_name = key[len("local/"):] if key.startswith("local/") else key
                
                # Check if it has a valid custom summary and the content has not changed
                has_custom_summary = current_summary and current_summary not in {
                    "Map of available project memory sections.",
                    "Project architecture, boundaries, and important system flows.",
                    "Important data models, schemas, and contracts.",
                    "Architecture and product decisions with rationale.",
                    "Known technical debt, risks, and cleanup targets.",
                    "Project-specific vocabulary and domain terms.",
                    "Framework-specific conventions and constraints.",
                    f"Project memory section for {sec_name}.",
                    f"Memory store section for {store_path}."
                }
                
                if has_custom_summary and current_hash == body_hash:
                    continue
                
                sum_prompt = (
                    f"Generate a concise, 1-sentence summary of the following project memory section named `{key}`. "
                    "The summary must be informative, help coding assistants decide when to read this file, and be under 150 characters. "
                    "Output ONLY the summary text, no quotes or intro:\n\n"
                    f"{body}"
                )
                new_summary = await call_llm(sum_prompt, "You are a concise summarizer of software documentation.", context)
                new_summary_clean = new_summary.strip().strip('"\'')
                if new_summary_clean and len(new_summary_clean) > 5:
                    metadata["summary"] = new_summary_clean
                    metadata["summary_hash"] = body_hash
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
            key = _get_section_key(candidate_root, path)
            lu_str = metadata.get("last_updated")
            if lu_str:
                lu_dt = datetime.fromisoformat(lu_str.replace("Z", "+00:00"))
                if lu_dt.tzinfo is None:
                    lu_dt = lu_dt.replace(tzinfo=timezone.utc)
                if (now_dt - lu_dt).days > 30:
                    if metadata.get("review_status") != "stale":
                        metadata["review_status"] = "stale"
                        path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
                        warnings.append(f"Section `{key}` has not been updated in over 30 days and is marked as stale.")
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

    # Now regenerate the index file in the candidate store
    checked_files = _regenerate_index_root(
        candidate_root,
        mode=mode,
        consolidation_hash=current_consolidation_hash,
        contradictions=dream_contradictions,
        warnings=dream_warnings,
    )

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
    
    # Check if consolidated_memory.md actually changed
    source_compiled = candidate_root / "consolidated_memory.md"
    target_compiled = memory_dir / "consolidated_memory.md"
    compiled_changed = False
    if source_compiled.exists():
        if not target_compiled.exists():
            compiled_changed = True
        else:
            try:
                if source_compiled.read_text(encoding="utf-8") != target_compiled.read_text(encoding="utf-8"):
                    compiled_changed = True
            except Exception:
                compiled_changed = True

    if apply and (affected_files or compiled_changed):
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
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5.0
        )
        if res.returncode != 0 or "true" not in res.stdout.lower():
            return ""
            
        git_info = []
        
        # Git diff
        res_diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5.0
        )
        if res_diff.returncode == 0 and res_diff.stdout.strip():
            diff_text = res_diff.stdout
            if len(diff_text) > 4000:
                diff_text = diff_text[:4000] + "\n... [Diff truncated due to size] ...\n"
            git_info.append("=== Git Working Copy Diff ===\n" + diff_text)
            
        # Git recent log
        res_log = subprocess.run(
            ["git", "log", "-n", "5", "--oneline"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5.0
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
           and not _is_store_path(memory_dir, path)
    ]
    global_files = [
        path
        for path in _iter_markdown_files(global_memory_dir())
        if path.name != "directives.md"
    ]
    # Include memory-store files
    store_root = memory_dir / "memory-store"
    store_files = [p for p in _iter_markdown_files(store_root) if p.name != "index.md"] if store_root.exists() else []

    def local_sort_key(path: Path) -> tuple[int, int, str]:
        metadata, _body, _warning = _safe_parse_for_sort(path)
        priority = str(metadata.get("priority") or "medium")
        index_rank = 0 if path.name == "index.md" else 1
        return (PRIORITY_ORDER.get(priority, 1), index_rank, path.name)

    def store_sort_key(path: Path) -> tuple[int, str]:
        metadata, _body, _warning = _safe_parse_for_sort(path)
        priority = str(metadata.get("priority") or "medium")
        return (PRIORITY_ORDER.get(priority, 1), str(path))

    high_and_medium = [path for path in local_files if local_sort_key(path)[0] in {0, 1}]
    low = [path for path in local_files if local_sort_key(path)[0] >= 3]
    store_high_medium = [p for p in store_files if store_sort_key(p)[0] in {0, 1}]
    store_low = [p for p in store_files if store_sort_key(p)[0] >= 3]

    return (
        sorted(high_and_medium, key=local_sort_key)
        + sorted(store_high_medium, key=store_sort_key)
        + sorted(global_files)
        + sorted(low, key=local_sort_key)
        + sorted(store_low, key=store_sort_key)
    )


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
    if path.name == "consolidated_memory.md":
        return True
    return bool({"private", "snapshots", "evals", "candidates"}.intersection(relative_parts))


def _is_store_path(memory_dir: Path, path: Path) -> bool:
    """Check if a path is inside the memory-store/ subdirectory."""
    store_root = memory_dir / "memory-store"
    try:
        path.relative_to(store_root)
        return True
    except ValueError:
        return False


def _section_key(path: Path, section: str) -> str:
    # Check if path is inside memory-store/
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "memory-store" and i > 0:
            store_root = Path(*parts[:i + 1])
            try:
                sp = _path_to_store_path(store_root, path)
                return f"store/{sp}"
            except ValueError:
                pass
    if ".ai-memory" in parts:
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
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5.0
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
            store_root = Path(*parts[:i + 1])
            try:
                sp = _path_to_store_path(store_root, path)
                return f"store:{sp}"
            except ValueError:
                pass
    return path.stem


def _regenerate_index(cwd: str, mode: str) -> list[str]:
    memory_dir = local_memory_dir(cwd)
    return _regenerate_index_root(memory_dir, mode=mode)


def _extract_key_topics(body: str) -> str:
    """Extract H2 headings or top-level list items to list as key topics."""
    topics: list[str] = []
    # Find h2 headings, e.g. ## Topic Name
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("## "):
            topic = line[3:].strip()
            if topic:
                topics.append(topic)
    if not topics:
        # Fallback to top-level list items if no h2 headings exist
        for line in body.splitlines():
            if line.startswith("- ") or line.startswith("* "):
                topic = line[2:].strip()
                if topic:
                    if len(topic) > 60:
                        topic = topic[:57] + "..."
                    topics.append(topic)
                    if len(topics) >= 3:
                        break
    if not topics:
        return "None recorded"
    
    cleaned_topics = [t.replace("|", "\\|") for t in topics]
    return "<br>".join(f"• {t}" for t in cleaned_topics)


def _compile_consolidated_memory(memory_dir: Path) -> str:
    """Compile all active memory sections into a single read-only string."""
    fragments = []
    
    prompt_path = memory_dir / "memory_prompt.txt"
    if not prompt_path.exists():
        for parent in memory_dir.parents:
            if parent.name == ".ai-memory":
                prompt_path = parent / "memory_prompt.txt"
                break

    if prompt_path.exists():
        try:
            p_text = prompt_path.read_text(encoding="utf-8").strip()
            if p_text:
                fragments.append(f"<!-- memory-fabric:local/memory_prompt -->\nMemory Prompt Steering Instructions:\n{p_text}")
        except Exception:
            pass
    local_files = [
        path
        for path in _iter_markdown_files(memory_dir)
        if path.name != "consolidated_memory.md"
           and not _is_ignored_local_memory_path(memory_dir, path)
           and not _is_store_path(memory_dir, path)
    ]
    
    def local_sort_key(path: Path) -> tuple[int, int, str]:
        metadata, _body, _warning = _safe_parse_for_sort(path)
        priority = str(metadata.get("priority") or "medium")
        index_rank = 0 if path.name == "index.md" else 1
        return (PRIORITY_ORDER.get(priority, 1), index_rank, path.name)
        
    ordered_files = sorted(local_files, key=local_sort_key)
    
    for path in ordered_files:
        section_name, metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            continue
        full_text = dump_frontmatter(metadata, body)
        section_key = f"local/{section_name}"
        fragments.append(f"<!-- memory-fabric:{section_key} -->\n{full_text.strip()}")

    # Include memory-store files
    store_root = memory_dir / "memory-store"
    if store_root.exists():
        store_files = sorted(p for p in _iter_markdown_files(store_root) if p.name != "index.md")
        for path in store_files:
            section_name, metadata, body, read_warning = _read_memory_path(path)
            if read_warning:
                continue
            full_text = dump_frontmatter(metadata, body)
            sp = _path_to_store_path(store_root, path)
            section_key = f"store/{sp}"
            fragments.append(f"<!-- memory-fabric:{section_key} -->\n{full_text.strip()}")

    return "\n\n".join(fragments).strip() + "\n"


def _regenerate_index_root(
    memory_dir: Path,
    mode: str,
    consolidation_hash: str | None = None,
    contradictions: list[str] | None = None,
    warnings: list[str] | None = None,
) -> list[str]:
    checked_files = [
        str(path)
        for path in _iter_markdown_files(memory_dir)
        if path.name != "index.md"
           and not _is_ignored_local_memory_path(memory_dir, path)
           and not _is_store_path(memory_dir, path)
    ]
    lines = [
        "# Project Memory Index",
        "",
        f"Updated by Memory Fabric Dreaming mode `{mode}` at {now_iso()}.",
        "",
        "| Section | Priority | Summary | Key Topics |",
        "| --- | --- | --- | --- |",
    ]
    for path in _iter_markdown_files(memory_dir):
        if path.name == "index.md" or _is_ignored_local_memory_path(memory_dir, path):
            continue
        if _is_store_path(memory_dir, path):
            continue
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        section = metadata.get("section", path.stem)
        priority = metadata.get("priority", "medium")
        summary = str(metadata.get("summary", "")).replace("|", "\\|")
        topics = _extract_key_topics(body)
        lines.append(f"| `{section}` | {priority} | {summary} | {topics} |")

    # Add pointer to dedicated memory-store index
    store_root = memory_dir / "memory-store"
    if store_root.exists():
        store_files = sorted(p for p in _iter_markdown_files(store_root) if p.name != "index.md")
        if store_files:
            lines.append("")
            lines.append("## Memory Store")
            lines.append("")
            lines.append("Please see the dedicated [Memory Store Index](memory-store/index.md) for a map of available semantic memory store files.")

            # Compile memory-store/index.md
            store_index_lines = [
                "# Memory Store Index",
                "",
                f"Updated by Memory Fabric Dreaming mode `{mode}` at {now_iso()}.",
                "",
                "| Path | Priority | Summary | Key Topics | Tags |",
                "| --- | --- | --- | --- | --- |",
            ]
            for sf in store_files:
                try:
                    sf_meta, sf_body = parse_frontmatter(sf.read_text(encoding="utf-8"))
                    sp = _path_to_store_path(store_root, sf)
                    sf_priority = sf_meta.get("priority", "medium")
                    sf_summary = str(sf_meta.get("summary", "")).replace("|", "\\|")
                    sf_topics = _extract_key_topics(sf_body)
                    sf_tags = sf_meta.get("tags", [])
                    tags_str = ", ".join(sf_tags) if isinstance(sf_tags, list) else str(sf_tags)
                    store_index_lines.append(f"| `{sp}` | {sf_priority} | {sf_summary} | {sf_topics} | {tags_str} |")
                    checked_files.append(str(sf))
                except Exception:
                    pass

            store_index_path = store_root / "index.md"
            store_root.mkdir(parents=True, exist_ok=True)
            
            store_metadata = {
                "store_path": "index",
                "title": "Memory Store Index",
                "summary": "Index of all semantic memory store files.",
                "priority": "high",
                "tags": ["index", "memory-store"],
                "schema_version": "1.3",
                "last_updated": now_iso()
            }
            store_index_path.write_text(dump_frontmatter(store_metadata, "\n".join(store_index_lines) + "\n"), encoding="utf-8")

    index_path = memory_dir / "index.md"
    if index_path.exists():
        metadata, _body = parse_frontmatter(index_path.read_text(encoding="utf-8"))
    else:
        metadata, _body = parse_frontmatter(build_empty_section("index"))
    
    if consolidation_hash is not None:
        metadata["consolidation_hash"] = consolidation_hash
    if contradictions is not None:
        metadata["contradictions"] = contradictions
    if warnings is not None:
        metadata["consolidation_warnings"] = warnings

    metadata["last_updated"] = now_iso()
    metadata["summary"] = "Map of available project memory sections."
    metadata["priority"] = "high"
    index_path.write_text(dump_frontmatter(metadata, "\n".join(lines) + "\n"), encoding="utf-8")

    try:
        consolidated_content = _compile_consolidated_memory(memory_dir)
        (memory_dir / "consolidated_memory.md").write_text(consolidated_content, encoding="utf-8")
    except Exception:
        pass

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
        if _is_ignored_local_memory_path(root, path):
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

    # Also promote consolidated_memory.md if it exists in candidate_root
    source_compiled = candidate_root / "consolidated_memory.md"
    target_compiled = memory_dir / "consolidated_memory.md"
    if source_compiled.exists():
        target_compiled.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(target_compiled):
            shutil.copy2(source_compiled, target_compiled)


def _build_rewrite_tasks(candidate_root: Path, max_rewrite_tasks: int) -> list[DreamRewriteTask]:
    tasks: list[DreamRewriteTask] = []
    for path in sorted(path for path in _iter_markdown_files(candidate_root) if path.name != "index.md"):
        if _is_ignored_local_memory_path(candidate_root, path):
            continue
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        section = _get_section_key(candidate_root, path)
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
