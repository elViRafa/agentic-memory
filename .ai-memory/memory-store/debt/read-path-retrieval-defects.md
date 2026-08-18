---
store_path: debt/read-path-retrieval-defects
title: "Read-path retrieval defects verified in code (v1.2.0)"
summary: "Read-path retrieval defects verified in code (v1.2.0)"
priority: high
tags: [retrieval, context, debt, bm25, budget, phase4]
schema_version: 1.3
last_updated: "2026-08-15T10:30:37-04:00"
evidence: ["src/memory_fabric/storage/context.py:208", "src/memory_fabric/storage/search.py:15", "src/memory_fabric/storage/_shared.py:230"]
---

Field report `Z_REPORT_REAL_USAGE_ANALYSYS.md` graded the memory read path D. Each claim was traced to specific code in v1.2.0 and confirmed:

1. **Bundle exceeds its own budget.** Tier 0, steering, and per-section omission placeholders all subtract from `remaining` (`context.py:147,163,179,229`), but the section loop keeps appending placeholders after the budget is exhausted. Reproduced live: `token_budget` 4000, `estimated_tokens` 6065, 11 included / 37 omitted.

2. **Priority is discarded when a query is given.** `context.py:208-209` sorts on `_score_section_relevance` alone, so a low-priority resolved-debt entry outranks a high-priority architecture map on one keyword hit.

3. **There is no BM25 anywhere** — this sharpens the report's "BM25 has no IDF". `_score_section_relevance` (`context.py:29-56`) is TF over log document length: no IDF, no k1, no b. `keyword_search` (`search.py:15-36`) performs **zero ranking** — ripgrep or Python substring scan, first `max_results` matches in filesystem order. The `keyword_search_tool` docstring's "ranked results" (`server.py:143`) is not implemented.

4. **Every file is read and frontmatter-parsed before trimming** (`context.py:183-205`). Measured p95 ~390 ms at 500 files, ~740 ms at 1000 (ROADMAP.md 2.1 Q10) vs a 150 ms target.

5. **`keyword_search` does not exclude ignored dirs.** It calls bare `_iter_markdown_files` (`search.py:88`) and never applies `_is_ignored_local_memory_path` (`_shared.py:230-237`), which the context path does apply. Only protection is `.ai-memory/.gitignore` honored by ripgrep; the Python fallback has none. Explains observed hits on stale `candidates/.../consolidated_memory.md`.

6. **The consolidated cache is useless at scale.** It is bypassed on any `query` and whenever compiled content exceeds the budget (`context.py:99,127`), i.e. exactly when the store is large. Its staleness scan uses unfiltered `rglob` (`context.py:103-107`), so touching `candidates/` invalidates a valid cache.

7. **Maps are generated then omitted for budget** — inverted, since generated maps are the table of contents. `MEMORY_FABRIC_MAP_TOKEN_CAP` applies at generation time only (`maps.py:116-124`); there is no read-time cap.

**Why eval says 88/100 anyway:** `eval` scores store hygiene (map freshness, metadata, coverage). Nothing in `eval/memory_quality.py` asks whether a realistic task query surfaces the right memory, so no retrieval regression can fail CI.

Remediation plan: `ROADMAP_IMPROVE_REAL_USAGE.md` phases R0 (honest budget) and R1 (frontmatter index + real BM25 + maps-first startup).
