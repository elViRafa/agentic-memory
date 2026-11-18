---
store_path: architecture/decisions/outdated-memory-close-events
title: "Outdated memory uses close events"
summary: "Outdated memory uses close events — project memory entry."
priority: medium
tags: [architecture, decisions, memory-lifecycle, close, entrenchment]
schema_version: 1.3
last_updated: "2026-11-18T11:07:23-03:00"
---

Age is not truth. A claim stays current until a later claim closes it via a named `supersedes:` path that writes `superseded_by`, plus `valid_from`, `closed_at`, and `close_kind` (`update` or `revision`). Standing roles (steering, decisions, schemas, architecture) are never age-stamped stale; dream clears age-only stale on those roles when there is no successor. Entrenchment blocks weaker roles (episodic, failures, debt) from closing stronger ones. Contradiction hits and prose-only close claims become pending reviews; promote writes the close. Current packs omit history roles without a query, pack the live posture slice only, and label closed hits with their successor on maps, search, read, and task packs.
