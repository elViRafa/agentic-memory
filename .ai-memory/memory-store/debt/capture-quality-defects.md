---
store_path: debt/capture-quality-defects
title: "Capture-quality defects: unicode slugs, failure dedup, generic summaries, orphaned review queue"
summary: "Capture-quality defects: unicode slugs, failure dedup, generic summaries, orphaned review queue"
priority: medium
tags: [capture, slugs, unicode, failures, summaries, review-status, debt]
schema_version: 1.3
last_updated: "2026-08-15T10:31:11-04:00"
evidence: ["src/memory_fabric/storage/migrate.py:45", "src/memory_fabric/storage/failures.py:65", "src/memory_fabric/storage/store.py:171", "src/memory_fabric/storage/capture.py:260"]
---

Capture *rate* is solved and measured (100% with hooks). Capture *quality* has four defects that make captured knowledge hard to retrieve later, all verified in v1.2.0.

**1. Slugs mangle non-ASCII.** `_slugify` (`migrate.py:45-48`) does `re.sub(r"[^a-z0-9]+", "-", text.strip().lower())`. Python `str.lower()` does not decompose accents, so each accented run becomes `-`: `seção` → `se-o`, `importação` → `importa-o`, `gráfico` → `gr-fico`. **`unicodedata.normalize("NFKD")` appears nowhere in the repo.** Same bug in `_hint_for` (`failures.py:65-67`) via `re.findall(r"[a-z0-9]+", ...)`, which collapses Portuguese-only error text to the hint `error`. Fix: NFKD + drop combining marks before the existing ASCII filter, shared by both call sites. Contradicts the documented Unicode-safe core characteristic.

**2. Failure memories almost never accumulate** (`occurrences: 1` nearly everywhere in the field store), defeating the highest-ROI category claim. Lookup is two-stage (`failures.py:118-140`): exact slug `{hint}-{sha1(normalized)[:10]}`, then a similar-file scan. Dominant causes of missed merges:
   - the similar-scan **filters candidates by the `_hint_for` prefix** (`failures.py:89`), so a differing first-four-words prefix means the right file is never even compared;
   - `_jaccard_similar` requires ≥3 words of length >2 in **both** strings (`_shared.py:395-396`), so short errors can never merge;
   - default threshold 0.4 (`MEMORY_FABRIC_FAILURE_MERGE_THRESHOLD`) is easily missed by rewording;
   - `_normalize_error` truncates to 300 chars, and old entries lacking `error_signature` skip the Jaccard branch entirely (`failures.py:96`).
   Fix: match on a structured signature (exception class / error code / tool name) first, prose Jaccard as fallback, and widen the candidate scan.

**3. Generic summaries are produced by design.** `write_memory_store` sets `summary = title[:150]`, else the first body line with `#` stripped (`store.py:171-180`), and new files default to `"Memory: {title}."` (`store.py:91`). There is **no** weak-summary rejection on the write path. `eval/_bad_summary()` (`memory_quality.py:172-182`) already encodes the rule but is applied only to required root sections. Field store has two decisions whose summary is literally `"Contexto"`. This becomes a retrieval bug (not a style nit) once summaries are the primary context surface.

**4. `review_status: pending` has no consumer.** Written by every commit capture (`capture.py:260`) plus the `needs-review` tag (`capture.py:267`, `maps.py:173`), and drained **only** by the deep-dream episodic rollup for files older than 14 days (`consolidation.py:413-421`) — which the field report documents as barely running (LM Studio timeout, `n_keep >= n_ctx`, sampling deadlock). Result: ~75 episodic entries, mostly unreviewed; the store is a commit log, not a project brain. No CLI subcommand consumes it (full list confirmed in `cli.py`). Needs an `ai-memory review` queue that promotes captures into `architecture/`, `decisions/`, or `failures/`.

Planned as phase R4 of `ROADMAP_IMPROVE_REAL_USAGE.md`.
