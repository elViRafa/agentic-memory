"""Registry + safe-write engine for wiring memory-fabric into AI coding
clients' *lifecycle hook* mechanisms — session-start marking, end-of-session
journal enforcement, and pre-compaction checkpoints (ROADMAP.md Phase 3 §5.2)
— as distinct from clients.py/installer.py, which wire the MCP server
connection itself.

Unlike MCP config (a shared json/toml/cli engine with only the config shape
varying), each client's hook mechanism has its own event model — Claude
Code's SessionStart/Stop/PreCompact schema (matcher-based blocks) turned out
structurally identical to Codex's (verified from Codex's own Rust source),
close to but not identical with Gemini CLI's (flat hook-definition lists, no
matcher on lifecycle events), and further clients diverge more still (Cursor,
Windsurf, Cline). So this is not a shared engine with format branches:
`HOOK_ADAPTERS` registers one real, implemented adapter per client — sharing
the matcher-block merge/remove helpers where the shape genuinely matches
(claude-code, codex), independent logic where it doesn't (gemini-cli). A
client absent from this registry has no hook support yet; `install_hooks()`
reports that plainly instead of silently no-op'ing — see ROADMAP.md Phase 3
§5.2's "Client capability survey" for what's still open (verified 2026-07-16:
Cursor's SessionStart-equivalent context injection has an open upstream bug;
VS Code Copilot Hooks looks implementable but is labeled Preview and wasn't
verified against primary docs; Windsurf and Cline lack a compaction-signal
hook and, for Windsurf, any session-lifecycle hook at all).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_fabric.clients import resolve_cli_binary
from memory_fabric.contracts import HookInstallResult
from memory_fabric.installer import _backup_file, _unified_diff
from memory_fabric.locking import locked_file

# Trailing shell comment marking a hook command as ours: safe to append after
# any command (including one ending in `|| true`) and lets install/uninstall
# find and update/remove exactly our own entries without touching hooks a
# user added by hand for the same event/matcher. Shared across every adapter.
_MANAGED_MARKER = "# memory-fabric-managed"


@dataclass(frozen=True)
class HookAdapter:
    name: str
    installer: Callable[..., HookInstallResult]


HOOK_ADAPTERS: dict[str, HookAdapter] = {}


def install_hooks(
    cwd: str,
    client: str,
    *,
    dry_run: bool = False,
    uninstall: bool = False,
) -> HookInstallResult:
    adapter = HOOK_ADAPTERS.get(client)
    if adapter is None:
        supported = ", ".join(sorted(HOOK_ADAPTERS)) or "(none yet)"
        return {
            "client": client,
            "ok": False,
            "changed": False,
            "supported": False,
            "path": "",
            "diff": "",
            "backup_path": "",
            "warnings": [
                f"No lifecycle-hook support for client {client!r} yet. Currently "
                f"supported: {supported}. See ROADMAP.md Phase 3 §5.2 for the "
                "client-hook survey covering the rest."
            ],
        }
    cwd_path = Path(cwd).expanduser().resolve()
    return adapter.installer(cwd_path, dry_run=dry_run, uninstall=uninstall)


def _is_managed_command(command: Any) -> bool:
    return isinstance(command, str) and command.rstrip().endswith(_MANAGED_MARKER)


# --- shared JSON safe-write scaffolding, used by every adapter below ---------------
# Same read/parse/backup-on-malformed-JSON/dry-run-diff/write-if-changed shape as
# installer.py's `_install_json`, reused here rather than re-implemented per client.


def _read_config_or_backup(
    path: Path, client: str, *, dry_run: bool
) -> tuple[dict[str, Any] | None, str, HookInstallResult | None]:
    """Read+parse a JSON hook config, or back it up and report a failure result.

    Returns ``(config, old_text, None)`` on success, or ``(None, "", failure)``
    if the existing file is malformed — the caller returns ``failure`` as-is
    (after adding any of its own warnings) without writing anything.
    """
    old_text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        config = json.loads(old_text) if old_text.strip() else {}
    except json.JSONDecodeError as exc:
        backup_path = "" if dry_run else _backup_file(path)
        return (
            None,
            "",
            {
                "client": client,
                "ok": False,
                "changed": False,
                "supported": True,
                "path": str(path),
                "diff": "",
                "backup_path": backup_path,
                "warnings": [
                    f"{path} contains invalid JSON ({exc}); backed up original and aborted."
                ],
            },
        )
    return config, old_text, None


def _finalize_hook_write(
    client: str,
    path: Path,
    old_text: str,
    new_text: str,
    changed: bool,
    *,
    dry_run: bool,
    warnings: list[str],
) -> HookInstallResult:
    diff = _unified_diff(old_text, new_text, str(path)) if dry_run else ""
    if not dry_run and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(path):
            path.write_text(new_text, encoding="utf-8")
    return {
        "client": client,
        "ok": True,
        "changed": changed,
        "supported": True,
        "path": str(path),
        "diff": diff,
        "backup_path": "",
        "warnings": warnings,
    }


# --- shared matcher-block merge/remove, used by claude-code AND codex --------------
# Both clients use the identical {"matcher": ..., "hooks": [{"type": "command", ...}]}
# block shape (Codex's confirmed straight from its `MatcherGroup`/`HookHandlerConfig`
# Rust structs in codex-rs/config/src/hook_config.rs — not assumed from a doc example),
# so the merge/remove logic itself is shared; only the managed-blocks builder, the
# config file path, and the trust-step warning differ per client.


def _merge_matcher_block_hooks(
    config: dict[str, Any], managed_blocks: dict[str, list[dict[str, Any]]]
) -> tuple[dict[str, Any], list[str]]:
    """Add/update our managed hook entries without touching anything else.

    For each event, find the existing matcher-block with the same `matcher`
    value; if found, drop only our own previously-managed command from it
    (identified by `_MANAGED_MARKER`) and append the current one — any other
    hooks a user added to that same block are left untouched. If no block
    with that matcher exists yet, a new block is appended to the event's list.
    """
    warnings: list[str] = []
    new_config = dict(config)
    hooks_root = dict(new_config.get("hooks", {}))

    for event, blocks_to_add in managed_blocks.items():
        raw_existing = hooks_root.get(event, [])
        if not isinstance(raw_existing, list):
            warnings.append(
                f"{event} in existing hooks config was not a list as expected; "
                "replacing with a fresh memory-fabric entry."
            )
            raw_existing = []
        existing_blocks: list[Any] = list(raw_existing)

        for block in blocks_to_add:
            matcher = block["matcher"]
            managed_hook = block["hooks"][0]
            for i, existing_block in enumerate(existing_blocks):
                if isinstance(existing_block, dict) and existing_block.get("matcher") == matcher:
                    kept_hooks = [
                        h
                        for h in existing_block.get("hooks", [])
                        if not (isinstance(h, dict) and _is_managed_command(h.get("command")))
                    ]
                    kept_hooks.append(managed_hook)
                    existing_blocks[i] = {**existing_block, "hooks": kept_hooks}
                    break
            else:
                existing_blocks.append({"matcher": matcher, "hooks": [managed_hook]})

        hooks_root[event] = existing_blocks

    new_config["hooks"] = hooks_root
    return new_config, warnings


def _remove_matcher_block_hooks(
    config: dict[str, Any], managed_events: tuple[str, ...]
) -> tuple[dict[str, Any], bool]:
    """Remove only memory-fabric's managed hook entries; leave everything else."""
    if "hooks" not in config or not isinstance(config["hooks"], dict):
        return config, False

    new_config = dict(config)
    hooks_root = dict(new_config["hooks"])
    removed_any = False

    for event in managed_events:
        raw_blocks = hooks_root.get(event)
        if not isinstance(raw_blocks, list):
            continue
        new_blocks = []
        for block in raw_blocks:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue
            kept_hooks = []
            for h in block.get("hooks", []):
                if isinstance(h, dict) and _is_managed_command(h.get("command")):
                    removed_any = True
                    continue
                kept_hooks.append(h)
            if kept_hooks:
                new_blocks.append({**block, "hooks": kept_hooks})
            # else: the block held only our entry — drop it rather than
            # leaving an empty {"matcher": ..., "hooks": []} behind.
        if new_blocks:
            hooks_root[event] = new_blocks
        else:
            hooks_root.pop(event, None)

    if hooks_root:
        new_config["hooks"] = hooks_root
    else:
        new_config.pop("hooks", None)

    return new_config, removed_any


# --- claude-code: SessionStart / Stop / PreCompact via .claude/settings.json ------

_CLAUDE_CODE_MANAGED_EVENTS = ("SessionStart", "Stop", "PreCompact")


def _build_claude_code_managed_blocks(
    cli_bin: str, cwd_abs: str
) -> dict[str, list[dict[str, Any]]]:
    """The hook blocks memory-fabric owns, keyed by event name.

    SessionStart marks the session and re-injects a short reminder (matchers
    `startup`/`resume` — deliberately NOT `compact`, since PreCompact already
    owns the mid-session checkpoint below, and re-marking session start on a
    mid-session compaction would wrongly reset the guard-journal window).
    Stop enforces the journal (`guard-journal` already exits 2 with the reason
    on stderr, which is exactly what Claude Code's Stop hook reads on a plain
    exit 2 — no JSON envelope needed). PreCompact runs a best-effort, never-
    blocking light dream: PreCompact's exit-2/block path gives Claude no
    stderr feedback (unlike Stop), so blocking compaction to force a journal
    write would strand the agent with no explanation — a silent local
    maintenance pass is the safe, useful thing this event can actually do.
    """
    quoted_bin = f'"{cli_bin}"'
    session_start_cmd = (
        f'{quoted_bin} --cwd "{cwd_abs}" session-start --hook-format claude-code {_MANAGED_MARKER}'
    )
    stop_cmd = f'{quoted_bin} --cwd "{cwd_abs}" guard-journal {_MANAGED_MARKER}'
    precompact_cmd = (
        f'{quoted_bin} --cwd "{cwd_abs}" dream --mode light --apply || true {_MANAGED_MARKER}'
    )
    return {
        "SessionStart": [
            {"matcher": "startup", "hooks": [{"type": "command", "command": session_start_cmd}]},
            {"matcher": "resume", "hooks": [{"type": "command", "command": session_start_cmd}]},
        ],
        "Stop": [
            {"matcher": "", "hooks": [{"type": "command", "command": stop_cmd}]},
        ],
        "PreCompact": [
            {"matcher": "manual", "hooks": [{"type": "command", "command": precompact_cmd}]},
            {"matcher": "auto", "hooks": [{"type": "command", "command": precompact_cmd}]},
        ],
    }


def _install_claude_code_hooks(
    cwd: Path, *, dry_run: bool = False, uninstall: bool = False
) -> HookInstallResult:
    path = cwd / ".claude" / "settings.json"
    cli_bin, bin_warning = resolve_cli_binary()
    warnings: list[str] = [bin_warning] if bin_warning else []

    config, old_text, failure = _read_config_or_backup(path, "claude-code", dry_run=dry_run)
    if failure is not None:
        failure["warnings"] = [*failure["warnings"], *warnings]
        return failure
    assert config is not None

    if uninstall:
        new_config, removed = _remove_matcher_block_hooks(config, _CLAUDE_CODE_MANAGED_EVENTS)
        if removed:
            new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
            changed = True
        else:
            warnings.append(f"No memory-fabric hooks found in {path}; nothing to remove.")
            new_text = old_text
            changed = False
    else:
        managed_blocks = _build_claude_code_managed_blocks(cli_bin, str(cwd))
        new_config, merge_warnings = _merge_matcher_block_hooks(config, managed_blocks)
        warnings.extend(merge_warnings)
        new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
        changed = new_text != old_text

    return _finalize_hook_write(
        "claude-code", path, old_text, new_text, changed, dry_run=dry_run, warnings=warnings
    )


HOOK_ADAPTERS["claude-code"] = HookAdapter(name="claude-code", installer=_install_claude_code_hooks)


# --- gemini-cli: SessionStart / AfterAgent / PreCompress via .gemini/settings.json --
# Verified 2026-07-16 against https://geminicli.com/docs/hooks/reference.md and
# .../hooks/index.md (fetched directly, not from training-data recall). Unlike
# Claude Code, lifecycle hooks (SessionStart/SessionEnd/Notification/PreCompress)
# are NOT matcher-based — only tool hooks (BeforeTool/AfterTool) use `matcher` —
# so each event's array holds hook-definition objects directly, no {matcher,
# hooks: [...]} wrapper. AfterAgent (our Stop-equivalent) documents exit code 2 as
# "Rejects the response and triggers an automatic retry turn using stderr as the
# feedback prompt" — the same plain-exit-2-plus-stderr contract `guard-journal`
# already implements for Claude Code, so it is reused unchanged here. PreCompress
# is documented "Advisory Only... cannot block or modify the compression process"
# — the same constraint PreCompact has on Claude Code, so it gets the same
# never-blocking light-dream checkpoint. One unconfirmed detail, flagged rather
# than silently assumed: the docs don't show a complete SessionStart stdout
# example, so it's unverified whether `hookSpecificOutput.hookEventName` is
# required alongside `additionalContext` — included anyway (harmless if ignored,
# and Gemini CLI's hook schema is explicitly modeled on Claude Code's).

_GEMINI_CLI_MANAGED_EVENTS = ("SessionStart", "AfterAgent", "PreCompress")


def _build_gemini_cli_managed_hooks(cli_bin: str, cwd_abs: str) -> dict[str, dict[str, Any]]:
    quoted_bin = f'"{cli_bin}"'
    session_start_cmd = (
        f'{quoted_bin} --cwd "{cwd_abs}" session-start --hook-format gemini-cli {_MANAGED_MARKER}'
    )
    after_agent_cmd = f'{quoted_bin} --cwd "{cwd_abs}" guard-journal {_MANAGED_MARKER}'
    precompress_cmd = (
        f'{quoted_bin} --cwd "{cwd_abs}" dream --mode light --apply || true {_MANAGED_MARKER}'
    )
    return {
        "SessionStart": {"type": "command", "command": session_start_cmd},
        "AfterAgent": {"type": "command", "command": after_agent_cmd},
        "PreCompress": {"type": "command", "command": precompress_cmd},
    }


def _merge_gemini_cli_managed_hooks(
    config: dict[str, Any], managed: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    new_config = dict(config)
    hooks_root = dict(new_config.get("hooks", {}))

    for event, managed_entry in managed.items():
        raw_existing = hooks_root.get(event, [])
        if not isinstance(raw_existing, list):
            warnings.append(
                f"{event} in existing hooks config was not a list as expected; "
                "replacing with a fresh memory-fabric entry."
            )
            raw_existing = []
        kept = [
            h
            for h in raw_existing
            if not (isinstance(h, dict) and _is_managed_command(h.get("command")))
        ]
        kept.append(managed_entry)
        hooks_root[event] = kept

    new_config["hooks"] = hooks_root
    return new_config, warnings


def _remove_gemini_cli_managed_hooks(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if "hooks" not in config or not isinstance(config["hooks"], dict):
        return config, False

    new_config = dict(config)
    hooks_root = dict(new_config["hooks"])
    removed_any = False

    for event in _GEMINI_CLI_MANAGED_EVENTS:
        raw = hooks_root.get(event)
        if not isinstance(raw, list):
            continue
        kept = []
        for h in raw:
            if isinstance(h, dict) and _is_managed_command(h.get("command")):
                removed_any = True
                continue
            kept.append(h)
        if kept:
            hooks_root[event] = kept
        else:
            hooks_root.pop(event, None)

    if hooks_root:
        new_config["hooks"] = hooks_root
    else:
        new_config.pop("hooks", None)

    return new_config, removed_any


def _install_gemini_cli_hooks(
    cwd: Path, *, dry_run: bool = False, uninstall: bool = False
) -> HookInstallResult:
    path = cwd / ".gemini" / "settings.json"
    cli_bin, bin_warning = resolve_cli_binary()
    warnings: list[str] = [bin_warning] if bin_warning else []

    config, old_text, failure = _read_config_or_backup(path, "gemini-cli", dry_run=dry_run)
    if failure is not None:
        failure["warnings"] = [*failure["warnings"], *warnings]
        return failure
    assert config is not None

    if uninstall:
        new_config, removed = _remove_gemini_cli_managed_hooks(config)
        if removed:
            new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
            changed = True
        else:
            warnings.append(f"No memory-fabric hooks found in {path}; nothing to remove.")
            new_text = old_text
            changed = False
    else:
        managed = _build_gemini_cli_managed_hooks(cli_bin, str(cwd))
        new_config, merge_warnings = _merge_gemini_cli_managed_hooks(config, managed)
        warnings.extend(merge_warnings)
        new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
        changed = new_text != old_text

    return _finalize_hook_write(
        "gemini-cli", path, old_text, new_text, changed, dry_run=dry_run, warnings=warnings
    )


HOOK_ADAPTERS["gemini-cli"] = HookAdapter(name="gemini-cli", installer=_install_gemini_cli_hooks)


# --- codex: SessionStart / Stop / PreCompact via .codex/hooks.json -----------------
# Verified 2026-07-16 directly against Codex's Rust source (not docs, which 403'd on
# every fetch attempt): codex-rs/hooks/src/lib.rs (event names + matcher-dispatch
# list), codex-rs/config/src/hook_config.rs (HooksFile/HookEventsToml/MatcherGroup/
# HookHandlerConfig — the exact hooks.json wire schema), codex-rs/hooks/src/events/
# common.rs (matcher semantics), and codex-rs/hooks/src/events/{session_start,stop,
# compact}.rs (per-event test suites showing exact I/O). This is source-of-truth
# reading, a step beyond the doc-page verification done for the other two clients.
#
# hooks.json's shape is structurally IDENTICAL to Claude Code's settings.json hooks
# (same {"matcher": ..., "hooks": [{"type": "command", ...}]} blocks under a "hooks"
# key) — confirmed from the actual struct definitions, not inferred — so the shared
# `_merge_matcher_block_hooks`/`_remove_matcher_block_hooks` helpers above are reused
# unchanged; only the managed-blocks builder and file path differ.
#
# Two things that differ from Claude Code, both confirmed from source:
# - Matchers support exact pipe-separated alternation for pure alphanumeric/underscore
#   patterns (`events/common.rs::is_exact_matcher` + `matches_matcher`): a matcher of
#   "startup|resume" matches either value in ONE block, so SessionStart/PreCompact each
#   need only one block instead of Claude Code's two. `Stop` isn't in
#   `HOOK_EVENT_NAMES_WITH_MATCHERS` (lib.rs) — its matcher is accepted but ignored
#   during dispatch, so `""` (match-all) is used, matching Claude Code's convention.
# - Stop's exit-2 contract is confirmed identical (`events/stop.rs`'s own test is
#   literally named `exit_code_two_uses_stderr_feedback_only`): non-empty stderr on
#   exit 2 blocks with that text as the reason, so `guard-journal` is reused unchanged.
#   One confirmed trap avoided: a test named `exit_code_two_without_stderr_does_not_
#   block` shows exit 2 with *empty* stderr is silently ignored — not a concern here
#   since `guard_journal()`'s `reason` is always non-empty when it blocks.
# - PreCompact's output schema (`PreCompactCommandOutputWire`) only carries the
#   universal `continue`/`stopReason`/`suppressOutput`/`systemMessage` fields, no
#   hook-specific context-injection field — same advisory-shaped constraint accepted
#   for Claude Code's PreCompact and Gemini CLI's PreCompress, so it gets the same
#   never-blocking light-dream checkpoint (never sets `continue: false`).
#
# One thing NOT fully resolved and flagged rather than guessed: newly-added or
# modified hooks go through a hash-based trust gate (`hook_trust_status` in
# discovery.rs) and are discovered-but-not-executed until trusted — confirmed from
# source, but the exact end-user trust command/flow wasn't found in the portion of
# the CLI source checked. `install_hooks(..., "codex")` surfaces this as an explicit
# warning on every install rather than silently implying "done" the way Claude
# Code/Gemini CLI's installs can.
#
# Config-path confidence note: `.codex/hooks.json` for the project scope is inferred
# from `ConfigLayerSource::Project { dot_codex_folder }` (the project layer's hook
# folder defaults to that same directory) and matches this repo's own existing
# project-scoped MCP config path for codex (`.codex/config.toml`, see clients.py) —
# high confidence, but unlike the exact schema above, not read from a literal
# "here is where hooks.json lives" line in the source.

_CODEX_MANAGED_EVENTS = ("SessionStart", "Stop", "PreCompact")


def _build_codex_managed_blocks(cli_bin: str, cwd_abs: str) -> dict[str, list[dict[str, Any]]]:
    quoted_bin = f'"{cli_bin}"'
    session_start_cmd = (
        f'{quoted_bin} --cwd "{cwd_abs}" session-start --hook-format codex {_MANAGED_MARKER}'
    )
    stop_cmd = f'{quoted_bin} --cwd "{cwd_abs}" guard-journal {_MANAGED_MARKER}'
    precompact_cmd = (
        f'{quoted_bin} --cwd "{cwd_abs}" dream --mode light --apply || true {_MANAGED_MARKER}'
    )
    return {
        "SessionStart": [
            {
                "matcher": "startup|resume",
                "hooks": [{"type": "command", "command": session_start_cmd}],
            },
        ],
        "Stop": [
            {"matcher": "", "hooks": [{"type": "command", "command": stop_cmd}]},
        ],
        "PreCompact": [
            {
                "matcher": "manual|auto",
                "hooks": [{"type": "command", "command": precompact_cmd}],
            },
        ],
    }


def _install_codex_hooks(
    cwd: Path, *, dry_run: bool = False, uninstall: bool = False
) -> HookInstallResult:
    path = cwd / ".codex" / "hooks.json"
    cli_bin, bin_warning = resolve_cli_binary()
    warnings: list[str] = [bin_warning] if bin_warning else []

    config, old_text, failure = _read_config_or_backup(path, "codex", dry_run=dry_run)
    if failure is not None:
        failure["warnings"] = [*failure["warnings"], *warnings]
        return failure
    assert config is not None

    if uninstall:
        new_config, removed = _remove_matcher_block_hooks(config, _CODEX_MANAGED_EVENTS)
        if removed:
            new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
            changed = True
        else:
            warnings.append(f"No memory-fabric hooks found in {path}; nothing to remove.")
            new_text = old_text
            changed = False
    else:
        managed_blocks = _build_codex_managed_blocks(cli_bin, str(cwd))
        new_config, merge_warnings = _merge_matcher_block_hooks(config, managed_blocks)
        warnings.extend(merge_warnings)
        new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
        changed = new_text != old_text
        if changed:
            warnings.append(
                "Codex requires newly added or modified hooks to be explicitly trusted "
                "before they run (hash-based trust gate) — check Codex CLI's hook-trust "
                "command/UI after this install, or the hooks will be discovered but not "
                "executed."
            )

    return _finalize_hook_write(
        "codex", path, old_text, new_text, changed, dry_run=dry_run, warnings=warnings
    )


HOOK_ADAPTERS["codex"] = HookAdapter(name="codex", installer=_install_codex_hooks)
