---
store_path: decisions/field-diary-no-phone-home
title: "Field diary is local, approved, never uploaded"
summary: "Field diary is local, approved, never uploaded"
priority: high
tags: [decisions, privacy, diary, field-pack]
schema_version: 1.3
last_updated: "2026-08-18T10:06:44-04:00"
---

An optional **field diary** records what Memory Fabric did (tools, timings, budget composition, role histograms) so real sessions can improve this project. It is not telemetry.

**Consent:** `ai-memory diary approve` is CLI-only, TTY or `--yes`. There is no MCP approve tool. Stored in `get_global_root()/diary.json` (`approved`, `level` `counts`|`counts+queries`). `MEMORY_FABRIC_DIARY=0` kills recording; `=1` does not approve. Per-project mute: `.ai-memory/private/diary-mute`.

**Words:** approve/revoke/diary/pack/counts — not enable/usage/export/metrics. Distinct from the session **journal** (what the agent accomplished).

**Default `counts` must include role/token buckets** (`PackStats`), not just included_n. Totals-only would not have found the 1.2.x journal-vs-maps failure. Query text only at `counts+queries`, always redacted. No memory-store bodies. No upload path.

Slice 1 (consent + CLI) and slice 2 (PackStats recording on the product boundary) shipped in **v1.4.0**. `diary pack` and maintainer analyze remain follow-up. Events live in `get_global_root()/diary/` until pack lands — copy that folder.
