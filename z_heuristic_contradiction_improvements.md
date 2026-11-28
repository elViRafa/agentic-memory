# Heuristic contradiction improvements

Handoff for a later session. Improve contradiction detection in pure Python.
Do not download a model. Do not add PyTorch, transformers, fastembed, or any
new dependency. The base package stays `dependencies = []`.

These changes only improve the advisory detector. They do not decide that a
new memory replaces an old one. A hit stays a review proposal. Nothing in
this work writes `superseded_by`.

## Why

`src/memory_fabric/storage/contradictions.py` compares whole files with three
heuristics:

- Numeric: two files with different digit bags, same topic, body Jaccard >= 0.3.
- Polarity: a `snake_case` / `CamelCase` / 2–6 letter acronym, then an 80-character
  window looking for English cues (`do not`, `use`).
- Named reversal: a regex like `reverses ADR-12`, then a lookup of that token in
  another file's path or title.

Same top-level folder counts as the same topic (`_same_topic`). The scan loads
files in alphabetical order and stops at `_SCAN_LIMIT = 150`, so a large store
fills the window inside `fine-tuning/` and never reaches `pretraining/`.
Episodic files and failures are skipped. Pairs of sections inside one file are
never compared, so `fine-tuning/current-posture-2026-10-31` can contain three
successive "next step" sections and produce no hit.

## Out of scope

- NLI classifiers (`mDeBERTa`, DeBERTa-large, MiniCheck) and any model download.
- Closing a memory. `supersedes:` on write, entrenchment, and the review queue
  belong to the obsolete-memory plan, not to this change.
- The 30-day `review_status: stale` stamp in `finalize.py`.
- Dream body rewrites that refresh `last_updated`.

## Changes

### 1. Compare claims, not whole files

Split each body into claims before any pair check:

- One claim per bullet, numbered item, or sentence.
- A Markdown heading starts a new claim group. Keep the heading text on the claims under it.
- Drop empty lines and fenced code.

Run numeric and polarity checks on claim pairs. Two files conflict only when
two claims conflict. Also compare claims inside a single file. That is what
surfaces three "next step" sections in one posture file.

Keep the existing whole-file reversal regex, but run it on each claim too.

### 2. Align numbers with a name and a unit

Stop comparing the set of all digits in a file.

From each claim, extract triples `(head, quantity, unit)`:

- `quantity` is an integer or decimal, including `0.46` and `0,46`.
- `unit` is an optional token such as `%`, `ms`, `s`, `GB`, `MiB`.
- `head` is the nearest content word before the quantity, using
  `memory_fabric.storage.ranking.tokenize`. Skip years (`19xx`/`20xx`),
  hex hashes, and bare line-looking integers with no head.

Two claims conflict when they share a head (and the same unit, when both have
one) and the quantities differ. Two different numbers with no shared head do
not conflict. Successive-version paths (`s2` vs `s3`, `v2` vs `v3`) stay
exempt, as `_successive_version_pair` already does.

### 3. Sentence-bounded negation, English and Portuguese

Delete the 80-character window in `_window_polarity`. A cue counts only inside
the same claim.

English cues stay: `do not`, `don't`, `never`, `must not`, `avoid`, `deprecated`,
and the existing positive list (`use`, `must`, `always`, `require`).

Add Portuguese cues in the same lists:

- Negative: `não`, `nao`, `nunca`, `jamais`, `evite`, `proibido`, `sem`.
- Positive: `usar`, `usa`, `deve`, `sempre`, `obrigatório`, `obrigatorio`.

Apply the cue to the claim's content words, not only to identifiers that match
`_IDENT_RE`. A shared rare word with opposite polarity is enough. Keep the
existing IDF drop: a word that appears in at least 25% of scanned files
(`_GENERIC_IDENT_FRAC`) is vocabulary, not a decision. That is the gate that
removed `LoRA` / `CPT` spam.

Prefer negation when the same word is both positive and negative in one claim.

### 4. Same folder is not the same topic

`_same_topic` must not return true only because both paths start with
`fine-tuning/`. Require a shared rare token (the IDF gate above) or Jaccard
overlap of the two claims at the existing `_SAME_TOPIC_JACCARD` threshold
(0.25). A shared folder may remain a candidate filter so unrelated categories
are not paired. It must not be sufficient on its own.

### 5. Lexical replacement phrases become review hits

Add a fourth kind, `replacement`, beside `numeric`, `polarity`, and `reversal`.

In a claim, match phrases:

- `superseded by`, `supersedes`, `replaced by`, `no longer use`
- `substituído por`, `substituido por`, `não usar mais`, `nao usar mais`

When the same claim names a `memory-store` path (a slash-separated slug such
as `decisions/lab-only-sem-prontuario` or `fine-tuning/next-session-handoff`),
emit a hit whose evidence is that path. Do not write `superseded_by`. The hit
is advisory, like the others.

### 6. Scan every category

Remove the alphabetical stop at 150 files as the coverage rule.

Load every non-generated store file except `episodic/` and `failures/`
(keep `_SKIP_TOP`). Cap work per top-level category: at most 150 files from
that category, then at most N claim-pairs (start with the current cost of a
150-file scan; keep the dream fast). `pretraining/` must be reached even when
`fine-tuning/` is larger than 150 files.

Keep `_MAX_HITS = 50` and the index pack cap (`_PACK_MAX = 5`,
`_PACK_TOKEN_MAX = 150`). New hits use the same pack ranking: reversal, then
numeric, then replacement, then polarity.

## Files

- `src/memory_fabric/storage/contradictions.py` — claim split, triple extract,
  polarity cues, topic gate, replacement kind, per-category scan.
- `tests/test_contradictions.py` — the cases below. Extend this file; do not
  add a dependency.

Reuse `ranking.tokenize`. Do not import fastembed.

## Tests

Each test builds a tiny store with `tmp_path` and calls `detect_contradictions`.

1. Two similar notes in `fine-tuning/` with unrelated numbers (a date in one,
   a port in the other) produce no numeric hit.
2. `refusal 0.46` and `refusal 0.44` in two fine-tuning notes produce one
   numeric hit.
3. `não usar LoRA nos embeddings` and `usar LoRA nos embeddings` produce one
   polarity hit. The same pair written as `do not use` / `use` still hits.
4. Two notes that only share the folder `fine-tuning/` and the generic word
   `lora`, with no other overlap, produce no hit.
5. A single posture file with two sections, "Next: RAG re-SFT" and a later
   "Next: OT fine-tune", produces an intra-file hit.
6. A store whose first 150 files are under `fine-tuning/` and whose later
   file is `pretraining/cpt-current.md` still reports a contradiction that
   lives only under `pretraining/`.
7. A claim `Superseded pointer: start at pretraining/next-session-cpt-improve`
   produces a `replacement` hit whose evidence is that path, and does not
   modify the target file.
8. Existing tests for successive-version numeric skip, bugs-vs-other polarity
   skip, pack cap of 5, and "never writes a winner" stay green.

## Done when

`pytest tests/test_contradictions.py` passes. `pyproject.toml` dependencies
are still empty. No import of `fastembed`, `torch`, or `transformers` was
added under `src/memory_fabric/storage/contradictions.py`.
