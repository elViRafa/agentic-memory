"""Registry + safe-write engine for wiring memory-fabric into AI coding
clients' *lifecycle hook* mechanisms — session-start marking, end-of-session
journal enforcement, and pre-compaction checkpoints (ROADMAP.md Phase 3 §5.2)
— as distinct from clients.py/installer.py, which wire the MCP server
connection itself.

Unlike MCP config (a shared json/toml/cli engine with only the config shape
varying), each client's hook mechanism has its own event model entirely —
Claude Code's SessionStart/Stop/PreCompact schema does not generalize to
Cursor's hooks (beta) or Codex's `notify`. So this is not a shared engine with
format branches: `HOOK_ADAPTERS` registers one real, implemented adapter per
client. A client absent from this registry has no hook support yet;
`install_hooks()` reports that plainly instead of silently no-op'ing — see
ROADMAP.md Phase 3 §5.2's "Client capability survey" for what's still open.
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
# user added by hand for the same event/matcher.
_MANAGED_MARKER = "# memory-fabric-managed"
_MANAGED_EVENTS = ("SessionStart", "Stop", "PreCompact")


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


# --- claude-code: SessionStart / Stop / PreCompact via .claude/settings.json ------


def _is_managed_command(command: Any) -> bool:
    return isinstance(command, str) and command.rstrip().endswith(_MANAGED_MARKER)


def _build_managed_blocks(cli_bin: str, cwd_abs: str) -> dict[str, list[dict[str, Any]]]:
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


def _merge_managed_hooks(
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


def _remove_managed_hooks(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Remove only memory-fabric's managed hook entries; leave everything else."""
    if "hooks" not in config or not isinstance(config["hooks"], dict):
        return config, False

    new_config = dict(config)
    hooks_root = dict(new_config["hooks"])
    removed_any = False

    for event in _MANAGED_EVENTS:
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


def _install_claude_code_hooks(
    cwd: Path, *, dry_run: bool = False, uninstall: bool = False
) -> HookInstallResult:
    path = cwd / ".claude" / "settings.json"
    cli_bin, bin_warning = resolve_cli_binary()
    warnings: list[str] = [bin_warning] if bin_warning else []

    old_text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        config = json.loads(old_text) if old_text.strip() else {}
    except json.JSONDecodeError as exc:
        backup_path = "" if dry_run else _backup_file(path)
        warnings.append(f"{path} contains invalid JSON ({exc}); backed up original and aborted.")
        return {
            "client": "claude-code",
            "ok": False,
            "changed": False,
            "supported": True,
            "path": str(path),
            "diff": "",
            "backup_path": backup_path,
            "warnings": warnings,
        }

    if uninstall:
        new_config, removed = _remove_managed_hooks(config)
        if removed:
            new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
            changed = True
        else:
            warnings.append(f"No memory-fabric hooks found in {path}; nothing to remove.")
            new_text = old_text
            changed = False
    else:
        managed_blocks = _build_managed_blocks(cli_bin, str(cwd))
        new_config, merge_warnings = _merge_managed_hooks(config, managed_blocks)
        warnings.extend(merge_warnings)
        new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
        changed = new_text != old_text

    diff = _unified_diff(old_text, new_text, str(path)) if dry_run else ""
    if not dry_run and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(path):
            path.write_text(new_text, encoding="utf-8")

    return {
        "client": "claude-code",
        "ok": True,
        "changed": changed,
        "supported": True,
        "path": str(path),
        "diff": diff,
        "backup_path": "",
        "warnings": warnings,
    }


HOOK_ADAPTERS["claude-code"] = HookAdapter(name="claude-code", installer=_install_claude_code_hooks)
