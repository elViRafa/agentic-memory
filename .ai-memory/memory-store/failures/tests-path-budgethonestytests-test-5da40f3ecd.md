---
store_path: failures/tests-path-budgethonestytests-test-5da40f3ecd
title: "tests/test_retrieval.py BudgetHonestyTests.test_compact_omission_line_not_per_se"
summary: "tests/test_retrieval.py BudgetHonestyTests.test_compact_omission_line_not_per_section_placeholders failed on Windows: AssertionError 'more sections omitted' not found in combined context text, while o"
priority: medium
tags: [budget, ci, failure, fix, omission, retrieval, windows]
schema_version: 1.3
last_updated: "2026-08-18T20:21:04-04:00"
occurrences: 1
error_signature: "tests<path> budgethonestytests.test_compact_omission_line_not_per_section_placeholders failed on windows: assertionerror <val> not found in combined context text, while omitted_sections was non-empty. the packer reserved the raw omission string then the over-budget trim popped the formatted omission"
failure_key: assertionerror
---

## Occurrence 1 — 2026-08-18T20:21:04-04:00

**Error:**
tests/test_retrieval.py BudgetHonestyTests.test_compact_omission_line_not_per_section_placeholders failed on Windows: AssertionError 'more sections omitted' not found in combined context text, while omitted_sections was non-empty. The packer reserved the raw omission string then the over-budget trim popped the formatted omission-notice fragment first.

**Fix:**
Reserve the formatted omission-notice fragment size, always keep that line when anything was omitted, and drop competing maps/store sections instead of popping the notice. Count always-on tokens from assembled fragments (including HTML wrappers and join separators).
