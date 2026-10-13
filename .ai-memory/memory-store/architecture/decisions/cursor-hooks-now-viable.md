---
store_path: architecture/decisions/cursor-hooks-now-viable
title: "Cursor lifecycle hooks are no longer blocked — adapter is viable"
summary: "Cursor lifecycle hooks are no longer blocked — adapter is viable"
priority: high
tags: [cursor, hooks, capture, client-hooks, decision]
schema_version: 1.3
last_updated: "2026-08-15T10:30:51-04:00"
evidence: ["src/memory_fabric/client_hooks.py:46", "src/memory_fabric/cli.py:584"]
---

`client_hooks.py` (docstring lines 12-23) and `ROADMAP_CAPTURE_HOOKS.md` 2.1 both record Cursor as **held** because SessionStart context injection had an open upstream bug. **That is now stale.** Verified 2026-08-15 against Cursor's current hooks documentation.

Cursor ships a stable project-level `.cursor/hooks.json` (schema `version: 1`, also user-level `~/.cursor/hooks.json`) with these relevant events:

- `sessionStart`, `sessionEnd`
- `stop` (supports `loop_limit` for follow-up loops)
- `preCompact`
- `preToolUse` / `postToolUse` / `postToolUseFailure` (matcher on tool type: `Write`, `Read`, `Shell`, `Task`, or `MCP: ...`)
- `beforeReadFile`, `afterFileEdit`
- `beforeShellExecution`, `beforeMCPExecution`
- `beforeSubmitPrompt`

Contract details that matter for our primitives:
- Command hooks exchange JSON over stdin/stdout. Exit 0 = success, **exit 2 = block** (same as returning deny), other non-zero fails open unless `failClosed: true`. This matches `ai-memory guard-journal`, which already exits 2 with a stderr reason (hardened 2026-07-16).
- `preToolUse` may return `permission`, `user_message`, `agent_message`, `updated_input`. `postToolUse` may return `additional_context`.
- Matchers use **JavaScript** regex, not POSIX classes.

**Consequence — bigger than parity with the three shipped clients.** A `preToolUse` hook matching `Write` (plus `beforeReadFile`) can *mechanically deny* raw file-tool writes into `.ai-memory/` and explain the redirect to `write_memory_store_tool` via `agent_message`. That converts the loudest instruction-only rule in every rules file into a real mechanism — the same instructions-to-mechanisms move Phase 3.2 made for journaling. Field evidence says the instruction-only version fails routinely: git status at session start repeatedly shows agent file-tool writes into `.ai-memory/`.

Adding the adapter is contained: one `HookAdapter` entry in `HOOK_ADAPTERS` (`client_hooks.py:46-49`, registry at lines 329/461/585), one `_install_cursor_hooks`, and a `--hook-format cursor` branch in `session-start` (`cli.py:584-585`). Note Cursor already has **MCP** install support (`clients.py:420-428`) — only the hook adapter is missing.

Design rule: fail **open** on hook error so memory bookkeeping can never wedge a session, and scope the write matcher to exclude hand-curated steering files.

Planned as phase R2 of `ROADMAP_IMPROVE_REAL_USAGE.md`.
