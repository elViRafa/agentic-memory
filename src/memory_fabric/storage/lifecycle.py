"""Project lifecycle: bootstrap, agent-rule sync, status, and health checks."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from memory_fabric.clients import resolve_cli_binary
from memory_fabric.contracts import DoctorResult, InitResult, StatusResult
from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.paths import global_memory_dir, local_memory_dir, memory_store_dir, project_root
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path,
    _is_steering_file,
    _is_store_path,
    _iter_markdown_files,
    _path_to_store_path,
    _read_memory_path,
    _steering_context_enabled,
    _steering_sync_enabled,
    estimate_tokens,
)
from memory_fabric.templates import (
    DIRECTIVES_BLOCK_END,
    DIRECTIVES_BLOCK_START,
    GENERATED_MAP_SECTIONS,
    INSTRUCTIONS_BLOCK_END,
    INSTRUCTIONS_BLOCK_START,
    LOCAL_GITIGNORE,
    SECTION_TEMPLATES,
    STORE_CATEGORY_SCAFFOLD,
    build_agents_md,
    build_agents_md_instructions,
    build_agents_rule_directives,
    build_agents_rule_dreaming,
    build_agents_rule_memory,
    build_claude_md,
    build_combined_instructions,
    build_copilot_md,
    build_cursor_directives,
    build_cursor_rule,
    build_memory_file,
    build_project_directives_block,
    build_windsurf_directives,
    build_windsurf_rule,
    order_directive_sections,
    wrap_managed_block,
)
from memory_fabric.version import __version__

# Git hooks: the block between these markers is owned by Memory Fabric and is
# replaced wholesale on re-init, so `ai-memory init --install-hooks` upgrades
# stale hooks (e.g. after a venv move) without duplicating lines.
_HOOK_BLOCK_START = "# >>> memory-fabric >>>"
_HOOK_BLOCK_END = "# <<< memory-fabric <<<"

# Unmarked lines written by installers before v0.7.1; stripped on upgrade.
_LEGACY_HOOK_LINES = {
    "# Added by Memory Fabric installer",
    'echo "Running Memory Fabric capture + Dreaming..."',
    "ai-memory capture || true",
    "ai-memory dream --mode light --apply || true",
    'echo "Syncing Memory Fabric Agent Rules..."',
    "ai-memory sync-agents || true",
    "git add .agents/rules/ .cursor/rules/memory-fabric.mdc .windsurf/rules/memory-fabric.md CLAUDE.md .github/copilot-instructions.md 2>/dev/null || true",
}


def _build_hook_block(bin_path: str, inner_lines: list[str]) -> str:
    lines = [
        _HOOK_BLOCK_START,
        f'MEMORY_FABRIC_BIN="{bin_path}"',
        'if ! [ -x "$MEMORY_FABRIC_BIN" ] && ! command -v "$MEMORY_FABRIC_BIN" >/dev/null 2>&1; then',
        '  MEMORY_FABRIC_BIN="ai-memory"',
        "fi",
        'if [ -x "$MEMORY_FABRIC_BIN" ] || command -v "$MEMORY_FABRIC_BIN" >/dev/null 2>&1; then',
        *inner_lines,
        "else",
        '  echo "memory-fabric: hook skipped (ai-memory not found)" >&2',
        "fi",
        _HOOK_BLOCK_END,
    ]
    return "\n".join(lines)


def _splice_hook_block(lines: list[str], block_lines: list[str]) -> tuple[list[str], bool]:
    """Replace an existing marked block in-place; report whether one was found."""
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        if lines[i].strip() == _HOOK_BLOCK_START and not replaced:
            j = i + 1
            while j < len(lines) and lines[j].strip() != _HOOK_BLOCK_END:
                j += 1
            out.extend(block_lines)
            i = j + 1
            replaced = True
        else:
            out.append(lines[i])
            i += 1
    return out, replaced


def _install_hook_block(
    hook_path: Path, comment: str, block: str, files_created: list[str]
) -> None:
    block_lines = block.splitlines()
    if hook_path.exists():
        original = hook_path.read_text(encoding="utf-8")
        lines = [ln for ln in original.splitlines() if ln.strip() not in _LEGACY_HOOK_LINES]
        lines, replaced = _splice_hook_block(lines, block_lines)
        if not replaced:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(block_lines)
        new_content = "\n".join(lines) + "\n"
        if new_content != original:
            hook_path.write_text(new_content, encoding="utf-8")
            files_created.append(str(hook_path))
    else:
        hook_path.write_text(f"#!/bin/sh\n# {comment}\n{block}\n", encoding="utf-8")
        files_created.append(str(hook_path))


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

    # Pre-scaffold the canonical store categories (ROADMAP Phase 2.2): visible
    # structure steers an agent's first writes toward the right category. Empty
    # dirs are invisible to map regeneration until a first entry lands, so this
    # changes nothing else.
    for category in STORE_CATEGORY_SCAFFOLD:
        category_keep = store_dir / category / ".gitkeep"
        category_keep.parent.mkdir(parents=True, exist_ok=True)
        if not category_keep.exists():
            category_keep.write_text("", encoding="utf-8")
            files_created.append(str(category_keep))

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

            cli_bin, bin_warning = resolve_cli_binary()
            if bin_warning:
                warnings.append(bin_warning)

            # Post-commit hook: passive capture (record the commit) then Dreaming
            # (consolidate + extract). Capture runs first so the just-made commit
            # is on disk as episodic memory before consolidation reads it.
            post_commit = hooks_dir / "post-commit"
            post_block = _build_hook_block(
                cli_bin,
                [
                    '  echo "Running Memory Fabric capture + Dreaming..."',
                    '  "$MEMORY_FABRIC_BIN" capture || echo "memory-fabric: capture failed (non-fatal)" >&2',
                    '  "$MEMORY_FABRIC_BIN" dream --mode light --apply || echo "memory-fabric: dream failed (non-fatal)" >&2',
                ],
            )
            _install_hook_block(
                post_commit, "Memory Fabric post-commit hook", post_block, files_created
            )

            # Pre-commit hook (Agent Rules Sync)
            pre_commit = hooks_dir / "pre-commit"
            pre_block = _build_hook_block(
                cli_bin,
                [
                    '  echo "Syncing Memory Fabric Agent Rules..."',
                    '  "$MEMORY_FABRIC_BIN" sync-agents || echo "memory-fabric: sync-agents failed (non-fatal)" >&2',
                    "  git add -A .agents/rules/ .cursor/rules/ .windsurf/rules/ AGENTS.md CLAUDE.md .github/copilot-instructions.md 2>/dev/null || true",
                ],
            )
            _install_hook_block(
                pre_commit, "Memory Fabric pre-commit hook", pre_block, files_created
            )

            if os.name != "nt":
                try:
                    for hook_file in [post_commit, pre_commit]:
                        mode = hook_file.stat().st_mode
                        hook_file.chmod(mode | 0o111)
                except Exception as exc:  # noqa: BLE001 - reported via warnings, not swallowed.
                    warnings.append(f"Failed to set executable permissions on git hooks: {exc}")
        else:
            warnings.append("Git repository not found; hooks were not installed.")

    # Generate index.md and memory-store/index.md through the same code path
    # Dreaming uses, so a fresh scaffold already satisfies doctor's consistency
    # checks (P-03: doctor right after init used to show 7 warnings that only
    # a first dream would clear).
    try:
        from memory_fabric.storage.consolidation import _regenerate_index_root

        # compile_consolidated=False: the compiled context document is a
        # Dreaming artifact; init only needs the indexes doctor checks.
        _regenerate_index_root(memory_dir, mode="light", compile_consolidated=False)
    except Exception as exc:  # noqa: BLE001 - reported via warnings, not swallowed.
        warnings.append(f"Could not generate the initial memory indexes: {exc}")

    return {
        "created": bool(files_created),
        "memory_dir": str(memory_dir),
        "files_created": files_created,
        "warnings": warnings,
    }


# Fabric headings written by pre-v1.1 syncs (no managed markers). Kept as a
# one-time upgrade fallback in sync (CLAUDE.md/copilot only) and as doctor's
# stale-legacy-block detector for content sync must no longer rewrite.
_LEGACY_FABRIC_BLOCK_RE = re.compile(
    r"(^|\n)(?:# Agent Instructions — Memory Fabric|"
    r"## Memory Fabric — Semantic Store Agent Instructions).*$",
    re.DOTALL,
)
_FABRIC_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:Memory Fabric — |Agent Instructions — Memory Fabric)", re.MULTILINE
)


def _splice_marker_block(
    text: str, start: str, end: str, inner: str | None, insert_before: str | None = None
) -> str:
    """Replace/append/remove a marker-managed block, touching nothing outside it.

    ``inner`` is the block's new content (markers added here); ``None`` removes
    the block entirely. A block that is already present is always replaced where
    it stands — never relocated, so a file a user has arranged by hand keeps its
    layout. A *new* block is inserted immediately above ``insert_before`` (a
    marker string) when that marker is present, and appended otherwise.

    Insertion adds exactly one blank-line separator on whichever side the new
    block was joined, and removal strips that same separator, so
    append/prepend → remove → re-insert round-trips content outside the markers
    byte-for-byte.
    """
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    match = pattern.search(text)
    if inner is not None:
        block = wrap_managed_block(start, inner, end)
        if match:
            return text[: match.start()] + block + text[match.end() :]
        if not text.strip():
            return block + "\n"
        anchor = text.find(insert_before) if insert_before else -1
        if anchor != -1:
            return text[:anchor] + block + "\n\n" + text[anchor:]
        separator = "\n" if text.endswith("\n") else "\n\n"
        return text + separator + block + "\n"
    if not match:
        return text
    before, after = text[: match.start()], text[match.end() :]
    # Drop the newline that terminated the closing marker's line, then the one
    # blank-line separator insertion added — before the block when it was
    # appended, after it when it was inserted above another block.
    if after.startswith("\n"):
        after = after[1:]
    if before.endswith("\n\n"):
        before = before[:-1]
    elif after.startswith("\n"):
        after = after[1:]
    return before + after


def _collect_sync_directives(memory_dir: Path) -> list[tuple[str, str]]:
    """`(section, body)` pairs for every steering section with `sync: true`
    (the default), in deterministic composition order, frontmatter stripped."""
    if not memory_dir.exists():
        return []
    by_name: dict[str, str] = {}
    for path in sorted(memory_dir.glob("*.md")):
        if _is_ignored_local_memory_path(memory_dir, path) or not _is_steering_file(path):
            continue
        if not _steering_sync_enabled(path):
            continue
        section, _metadata, body, read_warning = _read_memory_path(path)
        if read_warning:
            continue
        by_name[section] = body.strip()
    return [(name, by_name[name]) for name in order_directive_sections(list(by_name))]


def _refresh_instructions_block(text: str, inner: str) -> str:
    """Refresh the fabric-protocol content of a shared instruction file.

    Marker-managed block present → replace its content. Otherwise, a legacy
    (pre-v1.1) heading-to-EOF fabric block is wrapped in markers once — after
    which everything outside the markers is permanently the user's. Files with
    no fabric content at all are returned unchanged (sync never introduces the
    protocol into a file the user kept clean of it).
    """
    if INSTRUCTIONS_BLOCK_START in text and INSTRUCTIONS_BLOCK_END in text:
        return _splice_marker_block(text, INSTRUCTIONS_BLOCK_START, INSTRUCTIONS_BLOCK_END, inner)
    block = wrap_managed_block(INSTRUCTIONS_BLOCK_START, inner, INSTRUCTIONS_BLOCK_END)
    new_text, upgrades = _LEGACY_FABRIC_BLOCK_RE.subn(lambda m: m.group(1) + block, text, count=1)
    if upgrades:
        return new_text.rstrip("\n") + "\n"
    return text


def sync_agent_rules(cwd: str, check: bool = False) -> dict[str, Any]:
    """Regenerate all agent instruction files from canonical templates, and
    compose `sync: true` steering directives into per-tool files.

    Shared user files (AGENTS.md, CLAUDE.md, .github/copilot-instructions.md)
    are only ever modified inside Memory Fabric's managed marker blocks; user
    content outside the markers is preserved byte-for-byte.

    With ``check=True`` nothing is written: the result reports every path whose
    content would change (`would_change`) and ``success`` is True only when the
    tree is clean — the CI drift gate behind `ai-memory sync-agents --check`.
    """
    root = project_root(cwd)
    memory_dir = local_memory_dir(root)
    changed_paths: list[str] = []

    def _write_if_different(path: Path, content: str) -> None:
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                return
        changed_paths.append(str(path))
        if check:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _remove_if_present(path: Path) -> None:
        if not path.exists():
            return
        changed_paths.append(str(path))
        if not check:
            path.unlink()

    # Generic IDE rules
    _write_if_different(root / ".agents" / "rules" / "memory-store.md", build_agents_rule_memory())
    _write_if_different(root / ".agents" / "rules" / "dreaming.md", build_agents_rule_dreaming())

    # Cursor
    _write_if_different(root / ".cursor" / "rules" / "memory-fabric.mdc", build_cursor_rule())

    # Windsurf
    _write_if_different(root / ".windsurf" / "rules" / "memory-fabric.md", build_windsurf_rule())

    # Project directives (v1.1): compose every `sync: true` steering section
    # into one document, distributed as full files per tool. With no syncable
    # directive left, the generated files are torn down cleanly.
    directive_sections = _collect_sync_directives(memory_dir)
    directives_synced = [name for name, _body in directive_sections]
    directive_targets = {
        root / ".agents" / "rules" / "project-directives.md": build_agents_rule_directives,
        root / ".cursor" / "rules" / "project-directives.mdc": build_cursor_directives,
        root / ".windsurf" / "rules" / "project-directives.md": build_windsurf_directives,
    }
    directives_block: str | None = None
    if directive_sections:
        directives_block = build_project_directives_block(directive_sections)
        for target, builder in directive_targets.items():
            _write_if_different(target, builder(directives_block))
    else:
        for target in directive_targets:
            _remove_if_present(target)

    # Shared user files: refresh the instructions block inside its markers
    # (with a one-time legacy-heading upgrade for CLAUDE.md/copilot), then
    # replace/append/remove the project-directives block. Nothing outside the
    # marker pairs is ever modified.
    #
    # A directives block that isn't in the file yet is inserted *above* the
    # instructions block so project rules lead the file: an agent that skips
    # the memory protocol (no MCP tools configured) has already read them.
    # Blocks that already exist stay where the file has them — sync never
    # reorders a file the user has been living with.
    shared_files: list[tuple[Path, str]] = [
        (root / "AGENTS.md", build_agents_md_instructions()),
        (root / "CLAUDE.md", build_combined_instructions()),
        (root / ".github" / "copilot-instructions.md", build_combined_instructions()),
    ]
    for path, instructions_inner in shared_files:
        if path.exists():
            old_text = path.read_text(encoding="utf-8")
            new_text = old_text
            if path.name == "AGENTS.md":
                # AGENTS.md is the user's file: refresh only an existing marker
                # block, never legacy-upgrade (doctor flags stale blocks instead).
                if INSTRUCTIONS_BLOCK_START in new_text and INSTRUCTIONS_BLOCK_END in new_text:
                    new_text = _splice_marker_block(
                        new_text,
                        INSTRUCTIONS_BLOCK_START,
                        INSTRUCTIONS_BLOCK_END,
                        instructions_inner,
                    )
            elif "Memory Fabric" in new_text:
                new_text = _refresh_instructions_block(new_text, instructions_inner)
            new_text = _splice_marker_block(
                new_text,
                DIRECTIVES_BLOCK_START,
                DIRECTIVES_BLOCK_END,
                directives_block,
                insert_before=INSTRUCTIONS_BLOCK_START,
            )
            if new_text != old_text:
                _write_if_different(path, new_text)
        elif directives_block is not None:
            # No file yet: create it holding just the directives block so
            # AGENTS.md-only readers still receive the project directives.
            _write_if_different(
                path,
                wrap_managed_block(DIRECTIVES_BLOCK_START, directives_block, DIRECTIVES_BLOCK_END)
                + "\n",
            )

    if check:
        clean = not changed_paths
        return {
            "success": clean,
            "message": (
                "Agent files are in sync."
                if clean
                else f"{len(changed_paths)} file(s) out of sync — run `ai-memory sync-agents`."
            ),
            "would_change": changed_paths,
            "directives_synced": directives_synced,
        }
    return {
        "success": True,
        "message": f"Synchronized {len(changed_paths)} file(s).",
        "synced_files": changed_paths,
        "directives_synced": directives_synced,
    }


def status(cwd: str) -> StatusResult:
    memory_dir = local_memory_dir(cwd)
    local_files = (
        [str(path) for path in _iter_markdown_files(memory_dir)] if memory_dir.exists() else []
    )

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
            except (OSError, UnicodeDecodeError):
                pass  # size/token stats are informational; a skipped file just omits a row

    from memory_fabric.storage.capture import capture_stats
    from memory_fabric.storage.snapshots import list_snapshots

    snapshots = list_snapshots(cwd) if memory_dir.exists() else []
    candidates_root = memory_dir / "candidates"
    candidates_count = (
        sum(1 for p in candidates_root.iterdir() if p.is_dir()) if candidates_root.is_dir() else 0
    )

    return {
        "cwd": str(project_root(cwd)),
        "memory_dir": str(memory_dir),
        "memory_exists": memory_dir.exists(),
        "global_dir": str(global_memory_dir()),
        "provider_configured": bool(os.environ.get("MEMORY_FABRIC_LLM_PROVIDER")),
        "local_files": local_files,
        "memory_sizes": sizes,
        "version": __version__,
        "capture": capture_stats(cwd),
        "snapshots": {
            "count": len(snapshots),
            "latest": snapshots[0]["name"] if snapshots else None,
        },
        "candidates_count": candidates_count,
    }


def _merge_driver_warnings(cwd: str) -> list[str]:
    """Warn when the semantic merge driver is only half-installed.

    `.gitattributes` is committed and shared; the driver command is per-clone.
    A teammate who clones and merges without registering it gets ordinary
    textual conflicts in `.ai-memory/` with no indication why — the single most
    common way memory conflicts show up on a team.
    """
    # Imported lazily: merge_driver imports from this package.
    from memory_fabric.merge_driver import merge_driver_status

    try:
        status = merge_driver_status(cwd)
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never fail doctor.
        return [f"Could not determine merge-driver status: {exc}"]

    if status["declared"] and not status["registered"]:
        return [
            "This repo declares the Memory Fabric merge driver in .gitattributes, but this "
            "clone has not registered it, so .ai-memory files will produce textual merge "
            "conflicts. Run `ai-memory init --merge-driver` (per-clone, by git's design). "
            "Already mid-merge? `ai-memory resolve-conflicts`."
        ]
    if status["registered"] and not status["declared"]:
        return [
            "The Memory Fabric merge driver is registered in this clone but no .gitattributes "
            "rule points at it, so git never calls it. Run `ai-memory init --merge-driver` and "
            "commit .gitattributes."
        ]
    return []


def doctor(cwd: str, check_network: bool = False) -> DoctorResult:
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
        warnings.append(
            "Optional package `mcp` is not installed; MCP server tools will be unavailable."
        )

    warnings.extend(_merge_driver_warnings(cwd))

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
        # v1.1 routing keys: optional, but strictly boolean when present.
        for routing_key in ("sync", "context"):
            if routing_key in metadata and not isinstance(metadata[routing_key], bool):
                errors.append(
                    f"{path}: `{routing_key}` must be a boolean (true/false), "
                    f"got: {metadata[routing_key]!r}"
                )

    index_path = memory_dir / "index.md"
    if not index_path.exists():
        warnings.append("index.md is missing")
    else:
        try:
            _index_metadata, index_body = parse_frontmatter(index_path.read_text(encoding="utf-8"))
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
            extra_in_index = {
                sec for sec in listed_sections - existing_local_sections if "/" not in sec
            }

            for sec in missing_in_index:
                warnings.append(
                    f"Section `{sec}` exists in local memory but is missing from index.md "
                    "(run `ai-memory dream --mode light --apply` to regenerate the index)"
                )
            for sec in extra_in_index:
                warnings.append(
                    f"Section `{sec}` is listed in index.md but the corresponding file does not exist"
                )
        except Exception as exc:  # noqa: BLE001 - reported via errors, not swallowed.
            errors.append(f"Failed to check index consistency: {exc}")

    # Verify consistency of memory-store sub-index
    store_root = memory_dir / "memory-store"
    if store_root.exists():
        store_index_path = store_root / "index.md"
        if not store_index_path.exists():
            warnings.append(
                "memory-store/index.md is missing "
                "(run `ai-memory dream --mode light --apply` to generate it)"
            )
        else:
            try:
                _store_meta, store_body = parse_frontmatter(
                    store_index_path.read_text(encoding="utf-8")
                )
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
                    warnings.append(
                        f"Store file `{sp}` exists but is missing from memory-store/index.md"
                    )
                for sp in extra_in_store_index:
                    warnings.append(
                        f"Store file `{sp}` is listed in memory-store/index.md but the file does not exist"
                    )
            except Exception as exc:  # noqa: BLE001 - reported via errors, not swallowed.
                errors.append(f"Failed to check memory-store index consistency: {exc}")

    _check_legacy_flat_sections(memory_dir, warnings)
    _check_directive_budget(memory_dir, warnings)
    _check_steering_secrets(memory_dir, warnings)
    _check_stale_fabric_blocks(cwd, warnings)
    _check_ignored_agent_files(cwd, warnings)
    _check_hook_health(cwd, warnings)
    _check_install_drift(warnings)
    _check_llm_provider(warnings, check_network=check_network)
    if check_network:
        _check_pypi_drift(warnings)

    if not shutil.which("rg"):
        warnings.append("rg not found; keyword search will use Python fallback")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_files": checked_files,
    }


def _check_legacy_flat_sections(memory_dir: Path, warnings: list[str]) -> None:
    """Flag root map sections that are hand-written rather than generated.

    Store-first (v1.0): the map sections are generated views over
    ``memory-store/<category>/``, rebuilt by Dreaming, and no longer have a
    supported flat write path. A file at one of those names without
    ``generated: true`` frontmatter is legacy hand-written content from before
    the store-first migration — point the user at ``ai-memory migrate``, which
    splits it into the store and rewrites the flat file as a generated map.

    An *empty* legacy map (a bare scaffold, or a stub whose store category never
    received an entry) is exempt: ``migrate`` skips it by the same rule, so
    warning about it is a permanent nag with no action that clears it. The next
    Dream regenerates the file and stamps ``generated: true`` on its own.
    """
    for section in sorted(GENERATED_MAP_SECTIONS):
        path = memory_dir / f"{section}.md"
        if not path.exists():
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue  # unreadable files are already reported by the per-file loop
        if not metadata.get("generated") and _map_has_migratable_content(section, body):
            warnings.append(
                f"`{section}.md` is a hand-written root section, but under the store-first "
                f"model it must be a generated map over memory-store/{section}/. Run "
                "`ai-memory migrate` to split its content into the store and regenerate the map."
            )


def _map_has_migratable_content(section: str, body: str) -> bool:
    """True when `ai-memory migrate` would extract at least one entry from a map.

    Deliberately mirrors migrate's own skip rules (empty body, init starter
    placeholder, no non-empty chunk) rather than re-deciding what "has content"
    means, so doctor can never flag a file migrate refuses to act on. Imported
    lazily for the same reason the consolidation import in `init` is: keeps
    lifecycle out of the maps/migrate import chain at module load.
    """
    from memory_fabric.storage.maps import _is_starter_placeholder
    from memory_fabric.storage.migrate import _split_by_headings

    if not body.strip() or _is_starter_placeholder(section, body):
        return False
    return any(chunk.strip() for _heading, chunk in _split_by_headings(body))


_DIRECTIVE_BUDGET_DEFAULT = 3000


def _steering_files(memory_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(memory_dir.glob("*.md"))
        if not _is_ignored_local_memory_path(memory_dir, path) and _is_steering_file(path)
    ]


def _check_directive_budget(memory_dir: Path, warnings: list[str]) -> None:
    """Warn when the always-loaded context surface outgrows its budget.

    The surface is the global Tier 0 file plus every `context: true` steering
    section — all of it injected in full into every session, exempt from the
    normal token budget, so nothing else pushes back on its growth. The
    `sync: true` block is sized separately in the message: synced directives
    live in per-tool files, not in MCP context, so they don't count against
    this budget.
    """
    threshold = _DIRECTIVE_BUDGET_DEFAULT
    try:
        env_threshold = int(os.environ.get("MEMORY_FABRIC_DIRECTIVE_BUDGET", ""))
        if env_threshold > 0:
            threshold = env_threshold
    except (ValueError, TypeError):
        pass

    context_tokens = 0
    sync_tokens = 0
    tier0 = global_memory_dir() / "directives.md"
    if tier0.exists():
        # An unreadable Tier 0 file just drops out of the size estimate.
        with contextlib.suppress(OSError, UnicodeDecodeError):
            context_tokens += estimate_tokens(tier0.read_text(encoding="utf-8"))
    for path in _steering_files(memory_dir):
        try:
            tokens = estimate_tokens(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if _steering_context_enabled(path):
            context_tokens += tokens
        if _steering_sync_enabled(path):
            sync_tokens += tokens

    if context_tokens > threshold:
        warnings.append(
            f"Always-loaded context surface is ~{context_tokens} tokens (budget: {threshold}; "
            f"override via MEMORY_FABRIC_DIRECTIVE_BUDGET). Every session pays this in full — "
            f"trim the global Tier 0 file or set `context: false` on long steering sections "
            f"(synced directives reach file-reading agents anyway; the `sync: true` block is "
            f"~{sync_tokens} tokens and costs no context)."
        )


def _check_steering_secrets(memory_dir: Path, warnings: list[str]) -> None:
    """Detect-only secret scan over hand-curated steering files.

    Hand edits bypass the write path's redaction, so doctor re-runs the same
    detector here — warning only, never rewriting the file.
    """
    for path in _steering_files(memory_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        _redacted, matches = redact_secrets(text)
        if matches:
            warnings.append(
                f"{path}: {matches} potential secret(s) detected in this hand-curated steering "
                "file (hand edits bypass write-path redaction). Remove them and rotate any real "
                "credentials — doctor never rewrites files."
            )


def _check_stale_fabric_blocks(cwd: str, warnings: list[str]) -> None:
    """Flag fabric headings living outside managed marker blocks.

    Pre-v1.1 syncs wrote heading-to-EOF blocks into the shared user files with
    no markers. Sync now only rewrites inside its markers, so an unmarked
    fabric block will drift stale forever — the user must delete it once
    (CLAUDE.md/copilot get auto-upgraded by sync; AGENTS.md never does, by
    design, so this is the only signal for it).
    """
    root = project_root(cwd)
    marker_block_res = [
        re.compile(
            re.escape(start) + r".*?" + re.escape(end),
            re.DOTALL,
        )
        for start, end in (
            (INSTRUCTIONS_BLOCK_START, INSTRUCTIONS_BLOCK_END),
            (DIRECTIVES_BLOCK_START, DIRECTIVES_BLOCK_END),
        )
    ]
    for relative in ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"):
        path = root / relative
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        outside = text
        for pattern in marker_block_res:
            outside = pattern.sub("", outside)
        if _FABRIC_HEADING_RE.search(outside):
            warnings.append(
                f"{relative} contains a Memory Fabric block outside the managed markers "
                "(stale content from a pre-1.1 sync). Delete that block by hand and re-run "
                "`ai-memory sync-agents` — sync only rewrites content inside its markers."
            )


def _check_ignored_agent_files(cwd: str, warnings: list[str]) -> None:
    """Flag generated agent files the host repo's .gitignore excludes.

    These files are the entire delivery mechanism: a teammate (or a CI agent,
    or Copilot on someone else's checkout) only ever sees the protocol and the
    project directives because the files are committed. A broad ignore rule —
    `AGENTS.md` swept up by a docs pattern, `.cursor/` or `.windsurf/` ignored
    as editor cruft — means `sync-agents` keeps succeeding while nothing ever
    reaches anyone else. Nothing else in the system notices, hence this check.

    Force-added files need no special handling: `git check-ignore` consults the
    index by default (that is what `--no-index` turns off), so a tracked file is
    never reported even when a pattern matches it — which is the right answer
    here, since a committed file is delivered regardless of the ignore rule.
    """
    root = project_root(cwd)
    candidates = [
        "AGENTS.md",
        "CLAUDE.md",
        ".github/copilot-instructions.md",
        ".agents/rules/memory-store.md",
        ".agents/rules/dreaming.md",
        ".agents/rules/project-directives.md",
        ".cursor/rules/memory-fabric.mdc",
        ".cursor/rules/project-directives.mdc",
        ".windsurf/rules/memory-fabric.md",
        ".windsurf/rules/project-directives.md",
    ]
    existing = [rel for rel in candidates if (root / rel).exists()]
    if not existing:
        return

    from memory_fabric.storage.capture import _git

    # Exit 1 ("nothing ignored"), a non-git directory (exit 128), and a missing
    # git binary all surface as None here — all three mean "no warning", so the
    # single call needs no branching around it.
    ignored_out = _git(str(root), "check-ignore", "--", *existing)
    undelivered = sorted(
        {line.strip() for line in (ignored_out or "").splitlines() if line.strip()}
    )
    if undelivered:
        warnings.append(
            f"Generated agent file(s) are gitignored and untracked: {', '.join(undelivered)}. "
            "They are regenerated locally but never committed, so teammates and CI agents "
            "receive neither the memory protocol nor the project directives. Remove the "
            "ignore rule (or `git add -f` these paths) to restore delivery."
        )


def _check_install_drift(warnings: list[str]) -> None:
    """Warn when a bare `ai-memory` on PATH is a different installation.

    The tested machine had three coexisting copies (0.3.0 global on PATH,
    0.5.0 in the uvx cache, 0.7.0 in the project venv) with no signal — old
    hooks or other shells silently ran a stale version.
    """
    on_path = shutil.which("ai-memory")
    if not on_path:
        return
    try:
        path_dir = Path(on_path).resolve().parent
        running_dir = Path(sys.executable).resolve().parent
    except OSError:
        return
    if path_dir != running_dir:
        warnings.append(
            f"`ai-memory` on PATH resolves to `{on_path}`, a different installation than the one "
            f"running this command (`{running_dir}`). Bare `ai-memory` invocations (old git hooks, "
            "other shells) may silently use a stale version."
        )


def _check_pypi_drift(warnings: list[str]) -> None:
    """Best-effort comparison of the local version against the latest on PyPI.

    Network access is opt-in (`ai-memory doctor` passes check_network=True,
    the default unless `--offline` is given); any failure — offline, timeout,
    proxy — is silent by design.
    """
    try:
        import json as _json
        import urllib.request

        with urllib.request.urlopen(
            "https://pypi.org/pypi/memory-fabric/json", timeout=2.0
        ) as response:
            data = _json.load(response)
        latest = str(data.get("info", {}).get("version") or "")
    except (OSError, ValueError):
        return
    if latest and latest != __version__:
        warnings.append(
            f"Installed memory-fabric is {__version__} but PyPI's latest is {latest}. If your MCP "
            "client was configured via uvx, its cached server may be even older — re-run "
            "`ai-memory install` after upgrading (or `uv cache clean memory-fabric`)."
        )


def _check_llm_provider(warnings: list[str], check_network: bool) -> None:
    """Preflight the configured LLM provider so a misconfiguration surfaces in
    `ai-memory doctor` instead of as an opaque failure mid-Dream (field-test
    finding AV-2: a nonexistent OLLAMA_MODEL produced a raw HTTP-error string
    with no actionable next step).

    API-key-presence checks are pure env-var reads (no network, always run).
    The Ollama reachability + model-existence check is a real socket call —
    gated behind `check_network` (same opt-out-via-`--offline` flag as the
    PyPI check) even though it defaults to localhost, for the same
    local-first-by-default reasoning as `_check_pypi_drift`.
    """
    provider = (os.environ.get("MEMORY_FABRIC_LLM_PROVIDER") or "").strip().lower()
    if not provider:
        return

    if provider == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            warnings.append("MEMORY_FABRIC_LLM_PROVIDER=gemini but GEMINI_API_KEY is not set.")
        return
    if provider == "openai":
        base_url = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL") or ""
        if not os.environ.get("OPENAI_API_KEY") and (not base_url or "api.openai.com" in base_url):
            warnings.append("MEMORY_FABRIC_LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        return
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            warnings.append(
                "MEMORY_FABRIC_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set."
            )
        return
    if provider != "ollama":
        warnings.append(
            f"MEMORY_FABRIC_LLM_PROVIDER is set to an unrecognized value: `{provider}`."
        )
        return

    if not check_network:
        return

    host = (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL") or "gemma2"
    try:
        import json as _json
        import urllib.request

        with urllib.request.urlopen(f"{host}/api/tags", timeout=3.0) as response:
            data = _json.load(response)
        installed = {str(m.get("name") or "") for m in data.get("models", [])}
        # Ollama model names carry an implicit ":latest" tag; accept either form.
        installed_bare = {name.split(":", 1)[0] for name in installed}
        if model not in installed and model.split(":", 1)[0] not in installed_bare:
            warnings.append(
                f"Ollama is reachable at {host} but model `{model}` (OLLAMA_MODEL) is not "
                f"installed. Run `ollama pull {model}` or `ollama list` to see available models."
            )
    except (OSError, ValueError):
        warnings.append(
            f"MEMORY_FABRIC_LLM_PROVIDER=ollama but Ollama is not reachable at {host}. "
            "Start Ollama, or check OLLAMA_HOST if it runs elsewhere."
        )


def _check_hook_health(cwd: str, warnings: list[str]) -> None:
    """Warn when installed Memory Fabric git hooks cannot resolve the CLI.

    Resolves the binary the same way the hook script does (pinned path, then
    PATH fallback) so a hook that would silently skip is surfaced here.
    """
    hooks_dir = project_root(cwd) / ".git" / "hooks"
    if not hooks_dir.is_dir():
        return
    for name in ("pre-commit", "post-commit"):
        hook = hooks_dir / name
        if not hook.exists():
            continue
        try:
            content = hook.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "memory-fabric" not in content and "Memory Fabric" not in content:
            continue
        pinned = re.search(r'^MEMORY_FABRIC_BIN="([^"]+)"', content, re.MULTILINE)
        if pinned:
            bin_path = pinned.group(1)
            if Path(bin_path).exists() or shutil.which(bin_path) or shutil.which("ai-memory"):
                continue
            warnings.append(
                f"Git hook `{name}` points at `{bin_path}`, which does not exist, and no "
                "`ai-memory` fallback is on PATH — the hook is being skipped. Re-run "
                "`ai-memory init --install-hooks` from the environment where memory-fabric is installed."
            )
        elif re.search(r"^\s*ai-memory ", content, re.MULTILINE) and not shutil.which("ai-memory"):
            warnings.append(
                f"Git hook `{name}` invokes `ai-memory` via PATH but it is not on PATH — the hook "
                "fails silently on every commit. Re-run `ai-memory init --install-hooks` to pin "
                "the absolute CLI path."
            )
