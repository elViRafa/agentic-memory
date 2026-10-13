---
store_path: failures/merged-generated-map-carried-193c800971
title: "Merged generated map carried a body_hash that could not match its own body on Wi"
summary: "Merged generated map carried a body_hash that could not match its own body on Wi"
priority: medium
tags: [ci, failure, fix, line-endings, merge-driver, windows]
schema_version: 1.3
last_updated: "2026-07-29T18:23:25+00:00"
occurrences: 1
error_signature: "merged generated map carried a body_hash that could not match its own body on windows; regenerate_maps then read the merge as a hand edit and folded it into memory-store/"
---

## Occurrence 1 — 2026-07-29T18:23:25+00:00

**Error:**
Merged generated map carried a body_hash that could not match its own body on Windows; regenerate_maps then read the merge as a hand edit and folded it into memory-store/

**Fix:**
merge_driver._union_merge_bodies now writes its temp files as bytes and normalizes git's output to LF. Path.write_text translates \n to \r\n on Windows, git returned the CRLF it was handed, and parse_frontmatter normalizes line endings back out on read — so hashing the raw merge output broke the invariant the re-stamp exists to hold. Caught by the Windows CI matrix (4 of 12 jobs); the regression test reproduces it off Windows by making git's stdout CRLF directly, since the CRLF comes from the write and not from the input.
