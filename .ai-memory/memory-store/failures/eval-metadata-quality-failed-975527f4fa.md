---
store_path: failures/eval-metadata-quality-failed-975527f4fa
title: "eval metadata_quality failed every memory-store file with <stem>_section_missing"
summary: "eval metadata_quality failed every memory-store file with <stem>_section_missing"
priority: medium
tags: [drift, eval, failure, fix, store-first]
schema_version: 1.3
last_updated: "2026-07-13T21:32:03-04:00"
occurrences: 1
error_signature: "eval metadata_quality failed every memory-store file with <stem>_section_missing (e.g. <val>) even though the files were written by write_memory_store itself"
---

## Occurrence 1 — 2026-07-13T21:32:03-04:00

**Error:**
eval metadata_quality failed every memory-store file with <stem>_section_missing (e.g. "overview.md is missing `section`") even though the files were written by write_memory_store itself

**Fix:**
Store files are identified by store_path, not section — write_memory_store never writes a section field. Fixed eval/memory_quality.py to require store_path for files under memory-store/ (is_store flag added to the eval loader) and eval/_shared.py's _is_ignored_memory_path to delegate to storage's _is_ignored_local_memory_path (its hand-copied variant had drifted and scored consolidated_memory.md). Doctor had this exact local-vs-store split fixed long ago; when adding any new per-file validation, branch on store_path-vs-section from the start.
