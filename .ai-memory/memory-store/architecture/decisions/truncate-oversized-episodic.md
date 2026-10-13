---
store_path: architecture/decisions/truncate-oversized-episodic
title: "Truncate oversized episodic files in combined context"
summary: "Truncate oversized episodic files in combined context"
priority: high
tags: [adr, retrieval, budget, r0-4]
schema_version: 1.3
last_updated: "2026-08-15T17:10:58-04:00"
---

ADR: break the "never slice a file mid-document" invariant for oversized non-steering files only.

## Context
The field report's session collapse was one 8k-token journal monopolizing `read_combined_context`. The old invariant protected prose coherence; a journal that silently evicts the architecture map is the worse failure.

## Decision
No single non-steering file may claim more than `MEMORY_FABRIC_FILE_SHARE_CAP` (default 0.25) of `max_tokens`. Beyond that, include the summary plus leading body and mark the fragment `[truncated]`.

Steering and Tier 0 stay always-on in full.

## Consequences
- Oversized journals can no longer evict maps.
- A truncated journal is still better than a one-line omission stub.
- Override the cap with `MEMORY_FABRIC_FILE_SHARE_CAP` (0-1).
