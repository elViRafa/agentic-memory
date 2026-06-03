---
store_path: architecture/decisions/dream-store-subfolders
title: "Supporting Nested Subdirectories in Memory Store Dreaming"
summary: "Details hierarchical memory storage structure using `local/` and `store/` prefixes for accurate path preservation during consolidation."
priority: high
tags: [dreaming, memory-store, architecture]
schema_version: 1.3
last_updated: "2026-06-03T14:17:12-04:00"
summary_hash: a73cc9c3a4e1b6f5bc283b9d9188175e
---

The dreaming consolidation process was updated to fully support hierarchically organized, nested memory files inside the memory-store/ subdirectory. Canonical prefix keys (local/ for top-level flat sections and store/ for nested store files) are now used in LLM payloads, ensuring that consolidation, fact-checking, and summary generation preserve target directory paths instead of flattening or duplicating them. The doctor consistency checks were also corrected to validate store_path instead of section for nested memory store files.
