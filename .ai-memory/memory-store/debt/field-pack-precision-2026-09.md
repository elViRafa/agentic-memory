---
store_path: debt/field-pack-precision-2026-09
title: "Field pack precision roadmap U1–U5 shipped"
summary: "Real-usage pack fixes shipped against the search-sermons field store (dogfood 2026-09-21):"
priority: medium
tags: [field, search-sermons, retrieval, contradictions]
schema_version: 1.3
last_updated: "2026-09-21T08:22:17-03:00"
---

Real-usage pack fixes shipped against the search-sermons field store (dogfood 2026-09-21):

- Contradiction pack: index.md frontmatter ≤5 (was 50); full list in evals/contradictions.json; IDF dropped generic lora/cpt polarity across categories.
- Stale/superseded: review_status + superseded_by in blended_score and SQLite index v2; context_for_task omits stale.
- Eval: must_include/must_exclude pack tasks + contradiction_pack_hygiene; empty UL is fail; index-only dream deltas not a quality win.
- Dream churn: fingerprint cooldown, discard no-op snapshots/candidates, keep_candidates=0 after apply (search-sermons candidates 3→0).
- Doctor: stale-only decisions/, off_topic_failure, ADR-under-diary warnings.

Deferred: hybrid embeddings, link graph, valid_from query language.
