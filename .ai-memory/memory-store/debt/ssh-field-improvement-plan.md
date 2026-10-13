---
store_path: debt/ssh-field-improvement-plan
title: "SSH field improvements shipped in 1.4.3"
summary: "SSH field improvements shipped in 1.4.3"
priority: high
tags: [field, ssh, roadmap]
schema_version: 1.3
last_updated: "2026-10-13T16:39:35-03:00"
evidence: [src/memory_fabric/version.py, PLAN_SSH_FIELD_IMPROVEMENTS.md]
---

memory-fabric 1.4.3 in this tree implements the in-repo SSH field plan. Host install on the remote SSH machine is still manual.

- retrieval_quality always probes a sentence of two content words that are not neighbors on one line. No retrieval fixture is required.
- FastMCP initialize reports memory_fabric.__version__. The installed SDK has no FastMCP version argument, so the low-level server version is set after construction.
- Templates keep keyword_search_tool first for a sentence. context_for_task_tool packs a file into a budget.
- Doctor collapses missing-index paths into one warning. The contradiction pack is trimmed to 5 entries and 150 tokens. Cursor stop still runs guard-journal, and dream --if-index-stale rebuilds a stale memory-store index even during the light-dream cooldown.
- Query packs cap episodic files and other oversized notes at 15% of the budget. high_priority_inflation also warns at 24 high files.
- Doctor names PATH, ./env or ./.venv ai-memory, and a memory-fabric-mcp command from .cursor/mcp.json when those versions are older than the doctor.
