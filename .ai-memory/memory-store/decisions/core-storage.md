---
store_path: decisions/core-storage
section: core-storage
summary: "Decisions regarding markdown file storage, staleness, and memory deduplication."
priority: medium
tags: [decisions, storage, core, markdown]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Core Storage Decisions

This document records the granular decisions made for markdown file ingestion, parsing, and storage.

## Staleness
- Decided to auto-detect memory files not updated in the last 30 days and mark them as stale by setting `review_status: stale` in metadata.
- Optimized dreaming stale check to avoid writing metadata updates and warning logs for files already marked stale.

## Write Integrity
- Corrected `write_local_memory` to automatically extract and parse frontmatter delimiters from incoming payload content, merging metadata fields directly instead of polluting the body.
- Reinforced `write_local_memory` in append mode to filter out duplicate lines/bullets before writing, returning `changed=False` with a warning if no unique content is written.
