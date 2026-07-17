"""Project lifecycle: bootstrap, agent-rule sync, status, and health checks."""

from __future__ import annotations

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
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path,
    _is_store_path,
    _iter_markdown_files,
    _path_to_store_path,
    estimate_tokens,
)
from memory_fabric.templates import (
    GENERATED_MAP_SECTIONS,
    LOCAL_GITIGNORE,
    SECTION_TEMPLATES,
    STORE_CATEGORY_SCAFFOLD,
    build_agents_md,
    build_agents_rule_dreaming,
    build_agents_rule_memory,
    build_claude_md,
    build_copilot_md,
    build_cursor_rule,
    build_memory_file,
    build_windsurf_rule,
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
                    "  git add .agents/rules/ .cursor/rules/memory-fabric.mdc .windsurf/rules/memory-fabric.md CLAUDE.md .github/copilot-instructions.md 2>/dev/null || true",
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

    return {
        "success": True,
        "message": f"Synchronized {len(synced_files)} file(s).",
        "synced_files": synced_files,
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
    """
    for section in sorted(GENERATED_MAP_SECTIONS):
        path = memory_dir / f"{section}.md"
        if not path.exists():
            continue
        try:
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue  # unreadable files are already reported by the per-file loop
        if not metadata.get("generated"):
            warnings.append(
                f"`{section}.md` is a hand-written root section, but under the store-first "
                f"model it must be a generated map over memory-store/{section}/. Run "
                "`ai-memory migrate` to split its content into the store and regenerate the map."
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
