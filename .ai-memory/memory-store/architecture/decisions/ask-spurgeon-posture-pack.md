---
store_path: architecture/decisions/ask-spurgeon-posture-pack
title: "Ask Spurgeon posture pack and eval gates"
summary: "Field learning from ask-spurgeon (search-sermons) store: live page is `current-posture-*` at medium priority while historical `*next-session*` notes stay high with identical `last_updated` after dream"
priority: medium
tags: [ask-spurgeon, ranking, eval, field]
schema_version: 1.3
last_updated: "2026-11-02T16:41:21-03:00"
evidence: [src/memory_fabric/storage/ranking.py, src/memory_fabric/storage/context.py, src/memory_fabric/eval/memory_quality.py, tests/test_field_topology.py]
---

Field learning from ask-spurgeon (search-sermons) store: live page is `current-posture-*` at medium priority while historical `*next-session*` notes stay high with identical `last_updated` after dreams.

Product rules now in memory-fabric:
- Rank `current-posture` / `current-posture-*` and `role: posture` as live handoffs.
- Pin the newest eligible posture file in every context pack after steering.
- On posture write and on dream, demote sibling `*next-session*` files to low and set `superseded_by` without bumping `last_updated`.
- Resolved/historical high writes go to low (`historical`, `executed`, `not the live queue`).
- Clear sticky `review_status: stale` on body/summary edits; clear when last_updated is within 30 days; pack stale steering as summary only.
- `superseded_by` hard-omits from packs (score 0), same class as stale.
- Eval: large stores without retrieval fixtures fail; built-in `current posture` pack probe; `priority_inflation` fails and blocks composite pass.

Regression: `tests/test_field_topology.py::AskSpurgeonPostureShapeTests`.
