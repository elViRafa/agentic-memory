---
store_path: decisions/token-keyword-search
title: "Keyword search matches content words, not the whole sentence"
summary: "Keyword search matches content words, not the whole sentence"
priority: high
tags: [decisions, search, field-diary]
schema_version: 1.3
last_updated: "2026-10-13T12:56:07-03:00"
evidence: [src/memory_fabric/storage/search.py]
---

Field diaries on remote SSH workspaces (fabric 1.4.0 and 1.4.2, consent level counts) showed sentence-length keyword searches returning zero hits: 41 of 44 searches, and every search of length 29–73. Hits occurred only for queries of length 4, 9, and 13. The remote had no ripgrep, and both backends required the entire query as one fixed substring, so BM25 never saw a candidate.

`keyword_search` now tokenizes with the shared NFKD tokenizer, drops a small English and Portuguese stopword set, and retrieves files that contain any content token. Ripgrep ORs those tokens as fixed strings; the Python fallback does the same token match when `rg` is missing or returns nothing. Ranking still uses the shared BM25 blend. A file that also contains the original phrase (whitespace-folded) is boosted so it ranks above a file that only repeats the words apart.

Empty queries and `max_results` are unchanged. A stopword-only query returns no hits and is still recorded.

Diary `search.run` now stores `token_n`, `content_token_n`, `candidate_n`, and `phrase_hit` without query text at the `counts` level. `write_session_journal` records `journal.written` instead of `checkpoint.session_end`, so the stop hook can still show sessions that never journaled. Tool failures record `error_code` `cannot_append` or `cwd_does_not_exist` without the path. Doctor warns when `.cursor/` or `AGENTS.md` is present and `.cursor/hooks.json` is not; it does not install the file.
