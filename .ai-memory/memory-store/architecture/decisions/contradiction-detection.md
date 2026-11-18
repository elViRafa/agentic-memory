---
store_path: architecture/decisions/contradiction-detection
title: "Contradiction precision and pack surface"
summary: "Live rule: contradiction detection is advisory"
priority: high
tags: [dreaming, doctor, contradictions, pack]
schema_version: 1.3
last_updated: "2026-11-18T10:37:13-03:00"
evidence: [src/memory_fabric/storage/contradictions.py, tests/test_contradictions.py]
---

Live rule: contradiction detection is advisory. It never deletes a memory and never writes a winner pointer on disk.

Scan:
- Compare claims (bullets, numbered items, sentences; Markdown headings attach to the claims under them; drop fenced code), including two claims inside one file.
- Load up to 150 non-generated store files per top-level category. Skip `episodic/` and `failures/`. Reach every category even when one folder is huge.
- Cap deep claim-pair work per category at `150*149/2` via inverted indexes (numeric head buckets, rare-token polarity postings). Keep at most 50 hits.

Numeric:
- Extract `(head, quantity, unit)` per claim. Conflict when head matches, unit matches if both have one, and quantities differ.
- Skip successive-version path pairs (`sN` / `vN` / `waveN`). Skip generic heads that have no unit. Skip unit-less integers (keep decimals and united values).

Polarity:
- Cue applies to the whole claim (English + Portuguese). Prefer negation when both cues appear.
- Shared rare content word with opposite polarity is a hit. Words in ≥25% of scanned files are vocabulary and are dropped.
- Skip bugs-vs-other polarity pairs.

Topic:
- A shared top-level folder is only a candidate filter. Require a rare shared token or claim Jaccard ≥0.25.

Replacement:
- Lexical handoff/replacement phrases that name a slash-separated store path emit a `replacement` hit. Advisory only; the target file is not edited.

Intra-file:
- Successive `Next:` / `Próximo:` remainders inside one file emit one hit.

Pack:
- `index.md` keeps at most 5 hits ranked reversal > numeric > replacement > polarity, plus `contradiction_count`, trimmed to about 150 tokens.
- Full list goes to gitignored `evals/contradictions.json`. Doctor surfaces the top hits.
