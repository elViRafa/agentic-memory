---
store_path: architecture/decisions/contradiction-detection
title: "Full contradiction detection (R7-3)"
summary: "Full contradiction detection (R7-3)"
priority: high
tags: [dreaming, doctor, contradictions]
schema_version: 1.3
last_updated: "2026-08-15T17:32:57-04:00"
evidence: [src/memory_fabric/storage/contradictions.py, tests/test_contradictions.py]
---

Contradiction detection is no longer numbers-only. `storage/contradictions.py` flags three deterministic kinds:

- numeric Jaccard clashes (the original P-10 TTL 3600 vs 60 net)
- polarity on a shared identifier (use DRF vs do not use DRF)
- named decision reversals (PRD 0009 reverses PRD 0008 / `urnas_add_pos_calc`)

Dreaming and `doctor` surface hits for review. Nothing is deleted or auto-chosen. Deep dream can ask the already-configured LLM about remaining overlapping pairs via the same `call_llm` the consolidation path uses, so mocks still cover it.

Episodic journals and failure records are skipped. Cap is 150 files / 50 hits.
