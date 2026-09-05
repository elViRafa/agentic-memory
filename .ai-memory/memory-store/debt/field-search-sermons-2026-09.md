---
store_path: debt/field-search-sermons-2026-09
title: "Field defects from search-sermons store (write/rank/pack)"
summary: "Catalog of memory-fabric defects observed on the search-sermons store (~120 files, diary counts+queries) and closed in this change"
priority: high
tags: [field, search-sermons, retrieval, write-path, doctor]
schema_version: 1.3
last_updated: "2026-09-05T17:16:54-04:00"
---

Catalog of memory-fabric defects observed on the search-sermons store (~120 files, diary counts+queries) and closed in this change. No domain facts copied.

## Write / dream

- Priority inflation: agents stamp `high` on almost every file; pack then omits dozens of high entries. Write now warns when ≥50% of ≥8 store files are high; doctor/eval warn the same.
- Timestamp summaries: live handoffs used `summary: **Updated:** …`. `_bad_summary` missed them. Write derives a real sentence; doctor flags weak store summaries.
- Finished waves stay high: `*-complete` paths now store as `low`; resolved bodies cannot stay `high`.
- CUDA OOM duplicates: two wordings now share `failure_key=cuda|oom` and collapse.
- Placeholder steering (empty ubiquitous-language) is skipped in the always-on pack and warned by doctor.

## Read / pack / search

- Query packs spent budget on generated maps. Maps are down-ranked, capped, and unmatched (BM25=0) files are omitted from query packs.
- Historical `*-v2-*` and `*-complete` lose to `next-session-handoff` / `current` (lifecycle penalty + 14-day recency on handoff keys).
- `context_for_task` uses `index.db` (same path as startup).
- Custom prefixes (`fine-tuning/`, `pretraining/`) are diary roles, not `other`.
- `search.run` records `backend` even when `hit_n` is 0.

## Tests

Synthetic topology in `tests/test_field_topology.py` (no Spurgeon/CPT/Vultr text).
