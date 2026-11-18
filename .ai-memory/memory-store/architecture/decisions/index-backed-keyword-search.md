---
store_path: architecture/decisions/index-backed-keyword-search
title: "Index-backed keyword search with optional semantic blend"
summary: "keyword_search ranks the full local corpus from `.ai-memory/private/index.db` with corpus-wide BM25 IDF"
priority: high
tags: [search, retrieval, index, semantic]
schema_version: 1.3
last_updated: "2026-11-18T08:48:20-03:00"
evidence: [src/memory_fabric/storage/search.py, src/memory_fabric/storage/semantic.py, tests/test_retrieval.py]
---

keyword_search ranks the full local corpus from `.ai-memory/private/index.db` with corpus-wide BM25 IDF. Ripgrep/Python scan (capped at 200 candidates) is only the fallback when the index is missing. Optional `memory-fabric[semantic]` (fastembed) blends cosine for paraphrase hits; absent the extra, search stays lexical. Diary analyze gates zero-hit and candidate-cap `search.run` rows.

Proof: IndexBuriedFileTests (scan miss past 200 → index hit), SemanticSearchTests (paraphrase with injectible embedder; exact tokens still win), sentence/field/posture/150ms gates stay green.
