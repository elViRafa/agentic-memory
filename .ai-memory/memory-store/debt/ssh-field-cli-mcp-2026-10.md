---
store_path: debt/ssh-field-cli-mcp-2026-10
title: "SSH field check saved for follow-up"
summary: "SSH field check saved for follow-up"
priority: high
tags: [field, ssh, search, mcp, cli]
schema_version: 1.3
last_updated: "2026-10-13T14:01:10-03:00"
evidence: [FIELD_SSH_2026-10.md]
---

The 2026-10-13 SSH field check (two workspaces on a remote host) is saved in the repo at FIELD_SSH_2026-10.md, with the follow-up checklist in ROADMAP.md section 12.

Cursor on that host uses pipx memory-fabric 1.4.2. One workspace venv is still 1.2.2. MCP lists 21 tools and context_for_task finds sentence queries. keyword_search on the installed 1.4.2 returns hit_n 0 for those same sentences. Eval scored 95 pass and 78 warn without catching that miss. Doctor reported 45 and 68 stale-index warnings. Neither workspace has .cursor/hooks.json.

The token-search, diary-count, journal.written, and missing-hooks doctor changes in this working tree are not installed there yet.
