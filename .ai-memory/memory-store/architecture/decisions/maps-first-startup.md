---
store_path: architecture/decisions/maps-first-startup
title: "Maps-first startup context is the default"
summary: "Maps-first startup context is the default"
priority: high
tags: [adr, retrieval, r1-3]
schema_version: 1.3
last_updated: "2026-08-15T17:10:58-04:00"
---

ADR: no-query `read_combined_context` loads steering + Tier 0 + generated maps + `memory-store/index.md`, and no granular store bodies.

## Why
The field report's sharpest observation: maps are generated then omitted for budget. Maps *are* the table of contents. Dumping journals at session start is the bug.

## Escape hatch
`MEMORY_FABRIC_STARTUP_MODE=full` restores the old all-files dump (still under the honest budget + file-share cap).

## Mid-session
Use `context_for_task_tool` / `ai-memory retrieve` or `keyword_search_tool` for granular facts.
