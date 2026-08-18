---
store_path: architecture/decisions/coding-memory-benchmark
title: "Coding-memory benchmark (R6-3)"
summary: "Coding-memory benchmark (R6-3)"
priority: medium
tags: [benchmark, eval, retrieval]
schema_version: 1.3
last_updated: "2026-08-15T17:32:57-04:00"
evidence: [src/memory_fabric/eval/bench.py, benchmarks/coding-memory/README.md, tests/test_bench.py]
---

Shipped `ai-memory bench` and an extractable runner at `benchmarks/coding-memory/`.

The built-in fixture is the field-report recall set: TOT_LOCAL CAD vs system columns, `test_*.py` naming, no DRF, and the PRD 0008/0009 `urnas_add_pos_calc` reversal. Scoring is memory-on vs memory-off retrieval via `keyword_search` + `context_for_task`. No LLM is required.

Builtin result (2026-08-15): memory-on recall 1.00, memory-off 0.00, lift 1.00.

Users can run the same harness on their own store with `ai-memory bench --fixture . --suite .ai-memory/evals/bench.yaml`. Multi-repo expansion and LongMemEval/LoCoMo adapters remain open.
