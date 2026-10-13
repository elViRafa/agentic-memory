---
store_path: architecture/decisions/contradiction-detection
title: "Contradiction precision and pack surface"
summary: "Contradiction detection remains advisory (never deletes or picks a winner)"
priority: high
tags: [dreaming, doctor, contradictions, pack]
schema_version: 1.3
last_updated: "2026-09-21T08:21:25-03:00"
evidence: [src/memory_fabric/storage/contradictions.py, tests/test_contradictions.py]
---

Contradiction detection remains advisory (never deletes or picks a winner).

**Precision (2026-09-21):**
- Generic-ident IDF: idents in ≥25% of scanned files are vocabulary (`lora`, `cpt`), not decisions — polarity on them is dropped.
- Same-topic gate: polarity/numeric require shared top-level store prefix or title/body Jaccard ≥0.25.
- Successive-version numeric skip: paths that differ only by `sN` / `vN` / `waveN` are evolution, not conflict.
- Bugs-vs-other polarity skip: a bug fix that says "do not use LoRA on embeddings" is not an ADR against training LoRA.

**Pack surface:**
- `index.md` frontmatter keeps at most 5 hits (reversal > numeric > polarity) plus `contradiction_count`.
- Full advisory list is written to gitignored `evals/contradictions.json` (also written to the live tree because `evals/` is excluded from candidate apply).
- Doctor still surfaces top hits; agents must not treat pack YAML as a wall of actionable ADRs.

Episodic journals and failure records remain skipped. Cap is 150 files / 50 hits for the full scan.
