---
store_path: decisions/field-diary-no-phone-home
title: "Field diary is local, approved, never uploaded"
summary: "An optional **field diary** records what Memory Fabric did (tools, timings, budget composition, role histograms) so real sessions can improve this project"
priority: high
tags: [decisions, privacy, diary, field-pack]
schema_version: 1.3
last_updated: "2026-11-02T19:09:08-03:00"
---

An optional **field diary** records what Memory Fabric did (tools, timings, budget composition, role histograms) so real sessions can improve this project. It is not telemetry.

**Consent:** `ai-memory diary approve` is CLI-only, TTY or `--yes`. There is no MCP approve tool. Stored in `get_global_root()/diary.json` (`approved`, `level` `counts`|`counts+queries`). `MEMORY_FABRIC_DIARY=0` kills recording; `=1` does not approve. Per-project mute: `.ai-memory/private/diary-mute`.

**Words:** approve/revoke/diary/pack/counts/analyze — not enable/usage/export/metrics. Distinct from the session **journal** (what the agent accomplished).

**Default `counts` must include role/token buckets** (`PackStats`), not just included_n. Totals-only would not have found the 1.2.x journal-vs-maps failure. Query text only at `counts+queries`, always redacted. No memory-store bodies. No upload path.

**`context.pack` also records `posture_slot`:** closed label `absent`|`included`|`omitted`|`unknown` for the live posture pin. Section keys are never written.

Slice 1 (consent + CLI) and slice 2 (PackStats recording) shipped in **v1.4.0**. **`ai-memory diary pack`** and **`ai-memory diary analyze`** shipped as the follow-up:

- Pack reads `get_global_root()/diary/events-*.jsonl`, allowlists event fields, redacts secrets and absolute paths, and writes `get_global_root()/field-packs/field-<UTC stamp>/` (`manifest.json`, `events.jsonl`, `summary.json`). Optional `--from`/`--to`/`--out`. Nothing is transmitted; the user copies the folder.
- Analyze reads a pack folder or local diary and scores per `project_id`: posture inclusion on no-query vs query packs, steering token share of budget, omitted-high priority inflation, tool.call mix/failure rate, and top redacted queries when present. Exit 1 when a project with enough samples fails a gate.
