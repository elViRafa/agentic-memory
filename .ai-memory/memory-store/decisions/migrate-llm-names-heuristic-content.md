---
store_path: decisions/migrate-llm-names-heuristic-content
title: "Migrate: LLM names chunks, heuristic owns content"
summary: "Migrate: LLM names chunks, heuristic owns content"
priority: high
tags: [migration, store-first, llm, design]
schema_version: 1.3
last_updated: "2026-07-13T21:31:45-04:00"
evidence: [src/memory_fabric/storage/migrate.py, src/memory_fabric/storage/maps.py, CHANGELOG.md]
---

`ai-memory migrate` (v0.8, storage/migrate.py) deliberately inverts the ROADMAP's original "LLM-assisted split with heuristic fallback" wording: the heading-based heuristic split is ALWAYS the content pipeline (chunks are verbatim source text, fence-aware, so "never delete user content" holds by construction), and a configured LLM only proposes better NAMES (store_path/title/tags) for those chunks, validated per entry and falling back to heuristic names on any failure. Rationale: letting an LLM rewrite content would require verifying nothing was lost or rephrased, which is unprovable in general; naming is the part where an LLM adds value at zero content risk. Related: after a section's entries land, migrate rewrites the flat file as a generated map via maps._generate_category_map directly — deliberately bypassing regenerate_maps' hand-edit fold, which would re-blob the just-granularized body into map-notes-pending-review.
