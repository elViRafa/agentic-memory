# Roadmap — Closing the Real-Usage Gaps

> Source: [`Z_REPORT_REAL_USAGE_ANALYSYS.md`](Z_REPORT_REAL_USAGE_ANALYSYS.md) — a field
> evaluation of Memory Fabric 1.2.0 dogfooded in a real project (`gerenciador-eleicao`,
> ~151 store files, Cursor-first team).
>
> Companion to [`ROADMAP.md`](ROADMAP.md). That document plans the product; this one plans
> the repairs the field report demands, with each item traced to the code that causes it.

Written: 2026-08-15 · Against version 1.2.0 · Scope: read path, freshness automation,
Cursor enforcement, capture quality, retrieval measurement.

---

## 1. The finding, restated in code terms

The report's verdict — *write path B+, read path D* — is accurate, and the causes are
specific defects rather than a missing feature. Every claim below was verified against
`src/` before being planned.

**The read path is the product gap.** `read_combined_context` is the one function every
agent calls at session start, and it currently:

- goes **over its own budget** (this session: budget 4000, `estimated_tokens` 6065 — 52%
  over, 11 sections included, 37 omitted);
- **discards priority entirely** when a query is given
  (`context.py:208-209` sorts on score alone);
- **scores with no IDF**, so term frequency in a long journal beats a short architecture
  map (`_score_section_relevance`, `context.py:29-56`);
- **reads and frontmatter-parses every file** before trimming (`context.py:183-205`) —
  the measured p95 of ~390 ms at 500 files / ~740 ms at 1000 (ROADMAP.md §2.1 Q10);
- **spends budget on the omission notices themselves** (`context.py:229`), producing the
  "wall of `omitted … Summary:`" the report describes.

**There is no BM25 anywhere.** This sharpens the report's "BM25 here has no IDF":
`keyword_search` (`search.py:15-36`) does **no ranking at all** — ripgrep or a Python
substring scan, first ten matches win, in filesystem order. The `keyword_search_tool`
docstring's promise of "ranked results" (`server.py:143`) is not implemented. So the fix
is not "add IDF to BM25"; it is "build the ranker that was assumed to exist."

**Cursor enforcement is now unblocked.** The report treats Cursor lifecycle hooks as
`held` on an upstream SessionStart bug, matching `client_hooks.py`'s docstring and
`ROADMAP_CAPTURE_HOOKS.md` §2.1. That is stale: Cursor now ships a stable
`.cursor/hooks.json` (schema `version: 1`) with `sessionStart`, `sessionEnd`, `stop`
(with `loop_limit`), `preCompact`, `preToolUse`, `beforeReadFile`, `afterFileEdit`, and
`beforeMCPExecution`. This is a bigger opening than the report assumed — see R2, which
can enforce the `.ai-memory/` write ban *mechanically* instead of by instruction.

Two problems the report names are **not** in the code at all, and need building from
zero rather than fixing: `MEMORY_FABRIC_SKIP_STARTUP_DUMP` (referenced by the protocol
text, never implemented) and any consumer of `review_status: pending` outside the
14-day deep-dream rollup (`consolidation.py:413-421`).

### Why `eval` says 88/100 while retrieval fails

`ai-memory eval` scores **store hygiene** — map freshness, metadata, coverage. Nothing in
`eval/memory_quality.py` asks *"given a realistic task query, does the right memory reach
the agent?"* A store can score 88 and still hand the agent a truncated dump. Until that
metric exists (R6), every fix below is unfalsifiable. **R6 is therefore not last in
importance, only in dependency order** — build the harness early, even if the target
numbers land later.

---

## 2. Phase R0 — Make the budget honest (small, immediate, no new concepts)

The cheapest wins in the whole plan. All five items are localized to `context.py` and
`search.py`, need no new dependencies or file formats, and each is independently
shippable. Target: **1.2.1**, together.

- [x] **R0-1 — Never exceed the stated budget.** Steering and Tier 0 subtract from
      `remaining` (`context.py:147,163,179`) but nothing stops the section loop from
      appending once `remaining` goes negative, because omission placeholders are emitted
      unconditionally and *also* charged (`context.py:221-229`). Fix: once the budget is
      exhausted, stop emitting per-section placeholders and append a **single** compact
      line — `N more sections omitted; search with keyword_search_tool or read
      memory-store/index.md`. Keep the full list in the structured
      `omitted_sections` field, where it costs the agent no tokens.
      *Acceptance:* `estimated_tokens <= token_budget` for every call, asserted as a
      property test over stores of 10/150/1000 files. This session's own bundle
      (6065/4000) becomes a regression fixture.
      *Effort:* S.

- [x] **R0-2 — Warn, loudly, when steering alone eats the budget.** If Tier 0 + steering
      exceed ~50% of `max_tokens`, emit a warning naming the offending files and their
      token counts. `doctor`'s `_check_directive_budget` (`lifecycle.py:853-895`) already
      knows how to compute this at 3000 tokens; the read path should say it too, at the
      moment it actually hurts.
      *Acceptance:* a 3500-token steering file against a 4000 budget produces a warning
      that names the file. *Effort:* S.

- [x] **R0-3 — Keep priority in the ranking.** Replace the score-only sort
      (`context.py:208-209`) with a blended key: `score × priority_weight ×
      recency_weight`, where `high/medium/low` map to something like `1.0/0.6/0.3` and
      recency decays on `last_updated`. A `low`-priority resolved-debt entry must not
      outrank a `high` architecture map on one keyword hit. This is the smallest possible
      down payment on R1's ranker and can ship without it.
      *Acceptance:* a fixture where a low-priority file has a higher raw keyword score
      than a high-priority file still ranks the high-priority file first. *Effort:* S.

- [x] **R0-4 — Cap any single file's share of the budget.** The report's root cause for
      this session's collapse was one 8k-token journal. No single non-steering file should
      claim more than ~25% of `max_tokens` (env-tunable, e.g.
      `MEMORY_FABRIC_FILE_SHARE_CAP`); beyond that, include its summary plus leading body
      and mark it truncated. This deliberately breaks the "never slice a file
      mid-document" invariant (ROADMAP.md §4) **for oversized episodic files only** — the
      invariant was protecting prose coherence, and a journal that silently evicts the
      architecture map is the worse failure. Record it as an ADR, don't do it quietly.
      *Acceptance:* one 20k-token journal in a 150-file store cannot reduce the count of
      other included sections by more than one. *Effort:* M.

- [x] **R0-5 — Exclude `candidates/`, `snapshots/`, `private/`, `evals/` from search.**
      `keyword_search` calls bare `_iter_markdown_files` (`search.py:88`) and never applies
      `_is_ignored_local_memory_path` (`_shared.py:230-237`), which the context path does
      apply. Today the only protection is `.ai-memory/.gitignore` honored by ripgrep —
      which is why the field report still saw hits on
      `candidates/.../consolidated_memory.md`, and why the Python fallback has no
      protection at all. Filter in code, in both backends. Also exclude
      `memory-store/index.md`, a generated view that pollutes results with its own table
      of contents. Fix the cache-staleness scan (`context.py:103-107`) the same way: it
      currently lets a touch inside `candidates/` invalidate a valid cache.
      *Acceptance:* a query matching text present only in `candidates/` returns zero
      results on both backends. *Effort:* S.

**Exit criteria for R0:** the bundle never exceeds its budget; priority survives a query;
no single file can monopolize the budget; search never returns candidate noise. All
provable by unit test — no LLM, no benchmark, no new storage.

---

## 3. Phase R1 — A read path that scales (ROADMAP.md Phase 4, made concrete)

This is the report's P0 and ROADMAP.md Phase 4's still-unchecked first bullet. R0 makes
the current path honest; R1 makes it fast and actually selective.

- [x] **R1-1 — Frontmatter index with lazy body loads.** Build
      `.ai-memory/private/index.db` (SQLite, stdlib `sqlite3` — no new dependency,
      gitignored, rebuildable) holding one row per memory file: path, store_path,
      priority, title, summary, tags, `last_updated`, body token estimate, content hash.
      Ranking runs entirely on the index; **only the files that win a budget slot get
      their bodies read.** Invalidate per-file by mtime + hash, with a full rebuild on
      schema change and a graceful fallback to today's full-scan path when the index is
      missing or corrupt (same degradation contract already used for `rg` and LLM
      providers).
      *Acceptance:* p95 `read_combined_context` **< 150 ms at 1000 files** — the target
      ROADMAP.md §2.1 Q10 measured as unmet at ~740 ms; the existing loose 3000 ms
      regression guard tightens to the real number. Deleting the index changes results
      not at all, only latency. *Effort:* L.

- [x] **R1-2 — Real BM25 over the index.** Implement Okapi BM25 properly: IDF from index
      document frequencies, `k1≈1.2`, `b≈0.75` length normalization, then blend priority
      and recency as in R0-3. Tokenize with a Unicode-aware pattern (`\w+` with
      `re.UNICODE`, casefolded, NFKD-normalized) so Portuguese and other accented
      languages rank at all — the same defect class as R3-1's slugs, and a direct
      requirement of the project's Unicode-safe claim (`architecture/core-characteristics`).
      Use one shared ranker for **both** `read_combined_context` and `keyword_search`, so
      the two "relevance" systems stop disagreeing, and make `keyword_search` return its
      score so callers can threshold.
      *Acceptance:* on a fixture store, a query matching a rare term in a small ADR ranks
      it above a long journal that repeats a common term; `search` results are
      score-ordered and the `server.py:143` "ranked results" docstring becomes true.
      *Effort:* M.

- [x] **R1-3 — Maps-first startup context (inverted default).** Today maps are generated
      and then omitted for budget — the report's sharpest observation, and exactly
      backwards, since maps *are* the table of contents. New default for a no-query call:
      steering + Tier 0 + all generated maps + `memory-store/index.md`, and **no granular
      store bodies**. Granular files arrive via `keyword_search` / `read_memory_store` /
      R1-4. Keep the old behavior behind `MEMORY_FABRIC_STARTUP_MODE=full` for anyone
      depending on it.
      *Acceptance:* on the 151-file dogfood store, a no-query startup call includes every
      map in full, fits the 4000-token budget, and lists zero surprise omissions.
      *Effort:* M.

- [x] **R1-4 — `context_for_task(query, files_open)` MCP tool + `ai-memory retrieve`.**
      The report's headline new tool. Returns a task-scoped pack: steering, top-k ranked
      store entries at full length, matching guideline pointers, and any `failures/`
      entry whose signature relates to the open files. This is what agents should call
      mid-session instead of re-dumping context, and it's the natural place to spend a
      *larger* budget usefully because the selection is narrow.
      *Acceptance:* for "why did we choose MERGE-by-CPF?" the relevant ADR is in the pack
      at full length, within budget, on the dogfood store. *Effort:* M.

- [x] **R1-5 — Make no-query packing refuse to dump.** With R1-3 shipped, a no-query call
      never reaches journals, so the report's "query required for store packing" ask is
      satisfied without a breaking API change. Additionally deprioritize
      `episodic/commits/**` below every other category in ranking regardless of query:
      per-commit captures are raw material for dreaming, not answers.
      *Acceptance:* no `episodic/commits/**` file is ever included in a no-query bundle.
      *Effort:* S.

**Exit criteria for R1:** p95 < 150 ms at 1000 files; one shared Unicode-aware BM25
ranker serving both read tools; startup context is maps + steering and fits budget;
`context_for_task` ships. **This is the phase that moves the read path from D to B.**

---

## 4. Phase R2 — Cursor enforcement (the block is gone; take the opening)

The report's second P0. Capture rate is a measured 100% on Claude Code / Codex /
Gemini CLI (`scripts/capture_rate_benchmark.py`) and effectively instruction-only on
Cursor, which is the field team's daily driver. `client_hooks.py`'s `HOOK_ADAPTERS`
registry (lines 329, 461, 585) makes adding a fourth client a contained change: one
`HookAdapter` (`client_hooks.py:46-49`), one installer with Cursor's JSON shape, one new
`--hook-format cursor` branch in `session-start` (`cli.py:584-585`).

Cursor's hook surface is richer than the three shipped clients', so this phase gets
capabilities the others cannot have:

- [x] **R2-1 — `sessionStart` + `stop` parity.** `sessionStart` runs
      `ai-memory session-start` (writes the marker and injects context); `stop` runs
      `ai-memory guard-journal`, which already exits 2 with a stderr reason
      (hardened 2026-07-16, ROADMAP.md §5.2) — precisely Cursor's block contract. Set a
      small `loop_limit` so a stubborn agent cannot be trapped in a journal loop.
      *Acceptance:* the existing capture-rate benchmark, extended with a `cursor` mode,
      measures 0% journaling unenforced and 100% with hooks wired. *Effort:* M.

- [x] **R2-2 — `preToolUse` / `beforeReadFile` guard on `.ai-memory/` — the real fix for
      protocol violation.** The report's problem D is that agents keep writing
      `.ai-memory/` with raw file tools, and that instruction-only bans erode under
      context compression exactly as Phase 3 predicted. Cursor's `preToolUse` (matching
      `Write`) and `beforeReadFile` can **deny the call and explain why** via
      `agent_message`, redirecting to `write_memory_store_tool`. This converts the loudest
      🚨 rule in every rules file into a mechanism — the same instructions-to-mechanisms
      move Phase 3.2 made for journaling, applied to writes. Fail **open** on hook error
      (never wedge a session over memory bookkeeping), and scope the matcher narrowly to
      `.ai-memory/` paths, excluding the steering files a human may legitimately hand-edit.
      *Acceptance:* an agent instructed to `Write` into `.ai-memory/memory-store/` is
      denied, receives the redirect message, and the subsequent MCP write succeeds.
      **This is the highest-leverage single item in R2** — it removes a whole class of
      instruction-compliance failure. *Effort:* M.

- [x] **R2-3 — `preCompact` checkpoint.** Non-blocking `dream --mode light --apply`, the
      same advisory pattern already chosen for the three shipped clients. *Effort:* S.

- [x] **R2-4 — Correct the record.** `client_hooks.py`'s docstring (lines 12-23) and
      `ROADMAP_CAPTURE_HOOKS.md` §2.1 both still cite the upstream SessionStart bug as
      the reason Cursor is held. Update both with the verified current schema, and note
      VS Code Copilot Hooks as the next candidate. Stale capability notes are the same rot
      class `ai-memory verify` exists to catch. *Effort:* S.

**Exit criteria for R2:** `ai-memory install --client cursor --with-hooks` produces a
working `.cursor/hooks.json`; a non-cooperative Cursor agent still yields a journal per
session and a capture per commit; raw file writes into `.ai-memory/` are refused with a
useful message.

---

## 5. Phase R3 — Freshness without a human in the loop

Report section B: maps and citations rot between dreams. The mechanism is understood —
`regenerate_maps` runs only from dreaming (`dream.py:106`, `finalize.py:510`), migration,
and never from `write_memory_store`. Any agent that writes memory and does not dream
leaves stale maps, and R1-3 makes maps the *primary* context surface, which raises stale
maps from cosmetic to load-bearing.

- [x] **R3-1 — Regenerate the touched map on store write.** `write_memory_store` should
      refresh the one affected category map. `store_fingerprint` (`maps.py:89-100`) already
      makes this cheap and idempotent: unchanged fingerprint means no rewrite, no churn.
      Guard against write storms with a debounce and an opt-out
      (`MEMORY_FABRIC_MAP_AUTOREGEN=0`), since this touches the hot write path.
      *Acceptance:* a single `write_memory_store` call leaves `eval`'s map-freshness check
      passing with no dream. *Effort:* M.

- [x] **R3-2 — `ai-memory verify` in CI.** Mirror the `sync-agents --check` pattern the
      report grades **A** and explicitly recommends copying: a `memory-drift` job failing
      on `broken-evidence` for in-repo paths. Add a `repo:<name>:<path>` citation prefix
      so cross-repo evidence (the field report's `agregacao/` case, 4 broken files) is
      recorded as deliberately unverifiable rather than broken — today the local-first
      rule means such refs can only fail or be silently skipped.
      *Acceptance:* a citation to a deleted in-repo file fails CI; a `repo:` citation is
      reported as skipped, not broken. *Effort:* S.

- [x] **R3-3 — Doctor warns on the two rot signals the field hit.** Extend `doctor`
      (`lifecycle.py:626-791`) with: last deep dream older than N days, and
      `review_status: pending` / `needs-review` count above a threshold (the field store
      had ~75 episodic entries, most unreviewed). Both thresholds env-tunable, both
      warnings not errors.
      *Acceptance:* a store with 50 pending captures and no dream in 30 days produces two
      named warnings. *Effort:* S.

- [x] **R3-4 — Ban empty and generic summaries at the write boundary.** With R1-3, a
      summary *is* what most agents see, so `"Contexto"` (two files in the field store)
      is now a retrieval bug, not a style nit. `eval/_bad_summary()`
      (`memory_quality.py:172-182`) already encodes the rule but is applied only to
      required root sections. Apply the same check inside `write_memory_store` — reject or
      auto-derive on `""`, `"Contexto"`, `"Memory: <title>."`, or a summary equal to the
      first heading (which `store.py:171-180` currently *produces* by design).
      *Acceptance:* writing a store entry with summary `"Contexto"` either fails with a
      clear message or lands with a derived one-sentence summary. *Effort:* S.

**Exit criteria for R3:** maps cannot be stale after a write; broken in-repo citations
fail CI; doctor names an unconsolidated store; no new entry can carry a useless summary.

---

## 6. Phase R4 — Capture quality (report section E)

Capture *rate* is solved and measured. Capture *quality* has four defects that make
captured knowledge hard to retrieve later — which is why they belong on the same roadmap
as retrieval.

- [x] **R4-1 — Unicode-safe slugs.** `_slugify` (`migrate.py:45-48`) applies
      `re.sub(r"[^a-z0-9]+", "-", …)` after a plain `.lower()`, so `seção` → `se-o`,
      `importação` → `importa-o`, `gráfico` → `gr-fico`. `unicodedata.normalize("NFKD")`
      appears **nowhere** in the repo. Transliterate before stripping (NFKD, drop
      combining marks, then the existing filter), keeping the validated store-path charset
      (`_shared.py:21`) unchanged. `_hint_for` (`failures.py:65-67`) has the identical bug
      via `re.findall(r"[a-z0-9]+", …)`, which collapses Portuguese-only errors to the
      hint `error`, so fix both with one shared helper. Existing mangled slugs need a
      migration path, not a silent rename — a `doctor` warning plus an opt-in
      `ai-memory migrate --fix-slugs`.
      *Acceptance:* `seção de importação` → `secao-de-importacao`; a Portuguese-only error
      produces a readable hint. *Effort:* M.

- [x] **R4-2 — Failure signatures that actually collapse.** The field store shows
      `occurrences: 1` almost everywhere, defeating the "highest-ROI category" claim.
      Six distinct causes were traced (`failures.py:118-140`); the dominant two are the
      `_hint_for` prefix filter (line 89 — a differing first-four-words prefix means the
      similar-file scan never even *looks* at the right file) and Jaccard's ≥3-long-words
      floor (`_shared.py:395-396`), which short errors can never clear. Fix by extracting
      a structured signature — exception class, error code, framework/tool name — and
      matching on that first, with prose Jaccard as the fallback rather than the primary.
      Widen the candidate scan beyond the hint prefix.
      *Acceptance:* the same `IntegrityError` reported in Portuguese and English, at two
      call sites, collapses onto one entry with `occurrences: 2`. *Effort:* M.

- [x] **R4-3 — `ai-memory review` — drain the pending queue.** `review_status: pending`
      is written by every commit capture (`capture.py:260`) and consumed only by the
      14-day deep-dream rollup (`consolidation.py:413-421`), which the field report
      documents as barely running. Ship a CLI + MCP review queue that lists pending
      captures, shows the diff/body, and promotes an entry into `architecture/`,
      `decisions/`, or `failures/` (or drops it) — the step that turns a commit log into
      the "project brain" the roadmap claims. Make it agent-callable so it can run inside
      a session, not just as a human chore.
      *Acceptance:* on the dogfood store, `ai-memory review --list` shows the pending set
      and promoting one entry moves it out with provenance preserved. *Effort:* M.

- [x] **R4-4 — Compile a skills index into the always-on core.** `.agents/skills/` is a
      third instruction channel that `sync-agents` does not touch, free to drift from
      `docs/guidelines/`. Have `sync-agents` emit a short generated "available skills"
      list (names + one line + path, not bodies) so agents know the channel exists at a
      cost of a few dozen tokens.
      *Acceptance:* `sync-agents --check` fails when a skill is added and the index is not
      regenerated. *Effort:* S.

---

## 7. Phase R5 — Stop paying twice for the same instructions

Report section D: the Cursor surface carries the full protocol two to four times, and
the report's own token accounting is the argument. Verified: `build_cursor_rule`
(`templates.py:333`) writes `MEMORY_INSTRUCTIONS + DREAMING_INSTRUCTIONS` into
`.cursor/rules/memory-fabric.mdc`, `build_cursor_directives` writes a second always-on
`.cursor/rules/project-directives.mdc`, and `CLAUDE.md` / `AGENTS.md` /
`copilot-instructions.md` carry the same protocol again for any agent that reads them.
Then `read_combined_context` adds ~4k more.

- [x] **R5-1 — One thin Cursor rule.** Emit a compact `memory-fabric.mdc` — Rule 0,
      the startup call, the write-target rule, and pointers — instead of the full
      protocol, with the long form living in `.agents/rules/memory-store.md` for agents
      that fetch on demand. Dreaming parameter detail (`DREAMING_INSTRUCTIONS`) does not
      need to be always-on in an IDE rule at all.
      *Acceptance:* always-on Cursor rule tokens drop by more than half with no loss of
      Rule 0 or the startup contract; `doctor`'s directive-budget check confirms it.
      *Effort:* S.

- [x] **R5-2 — Implement `MEMORY_FABRIC_SKIP_STARTUP_DUMP`.** The protocol text already
      tells agents this exists; `src/` never implements it. Wire it, and **default it on
      when the MCP Resource `memory-fabric://context/<cwd>` has been served in this
      session** — paying twice for identical context is pure waste. Requires tracking
      resource-fetch state in `server.py`.
      *Acceptance:* with the resource auto-fetched, `read_combined_context_tool` returns a
      short pointer instead of the full bundle, and says why. *Effort:* M.

- [x] **R5-3 — Ship the agent router as generated content.** The report asks for a
      one-page router (guidelines vs memory vs code-graph tools vs skills) and correctly
      insists it not become more always-on tokens. Generate it as a skill/deep-dive that
      `sync-agents` maintains, referenced in one line from the core.
      *Effort:* S.

---

## 8. Phase R6 — Measure retrieval, or none of the above is provable

Deliberately placed after the fixes in dependency order, but **start it first** — it is
the only thing that can tell whether R0-R1 worked. `eval` today cannot fail on a
retrieval regression, which is why the field store scores 88 while agents get truncated
dumps.

- [x] **R6-1 — `retrieval_quality` eval category.** Add a scored category driven by a
      repo-local `.ai-memory/evals/retrieval.yaml` of `{query, expected_store_paths}`
      pairs. Score precision@k / recall@k / "did it fit the budget" — no LLM required, so
      it runs in CI like every other check. This is the metric that makes "read path D"
      a number instead of a judgment.
      *Acceptance:* an intentional ranking regression drops the score and fails CI.
      *Effort:* M.

- [x] **R6-2 — Guideline canary.** A scripted prompt against a cheap model asserting a
      known-contradictory convention (the field report's example: new test files are
      `test_*.py`, not `tests_*.py`). Catches instruction-load failures that
      `sync-agents --check` structurally cannot see — it verifies files match sources, not
      that the agent read them. Opt-in in CI (needs a provider), skipped cleanly without
      one.
      *Effort:* M.

- [x] **R6-3 — Coding-memory benchmark fixture.** ROADMAP.md Phase 5's benchmark now has
      a real fixture available: the field project, with concrete recall targets (CAD vs
      system columns, `test_*.py`, no DRF). Land it as the standalone repo Phase 5
      describes, with memory-on vs memory-off numbers. **Gate this on R0-R1** — publishing
      a benchmark against today's read path would measure the bug, not the design.
      *Effort:* L. Shipped as `ai-memory bench` + `benchmarks/coding-memory/`.

---

## 9. Phase R7 — Longer-horizon items the field confirmed

Real pain, but each is blocked behind or lower-value than the above.

- [x] **R7-1 — Dreaming that runs unattended.** The field project's deep dreams failed on
      an LM Studio 600s-vs-180s timeout, `n_keep >= n_ctx`, and the MCP sampling deadlock
      that motivated the split-tool protocol. Default deep dream to split-tool when no
      healthy LLM is detected — `doctor`'s `_check_llm_provider`
      (`lifecycle.py:1056-1116`) already performs exactly that detection — instead of
      hanging for 180s. *Effort:* M.

- [x] **R7-2 — Candidate store TTL.** `MEMORY_FABRIC_KEEP_CANDIDATES` (default 3) prunes
      by count, not age, so the field store still held August candidates. Add age-based
      pruning and a `doctor` "stale candidates" warning. Complements R0-5: excluded from
      search *and* eventually deleted. *Effort:* S.

- [x] **R7-3 — Contradiction detection.** ROADMAP.md Phase 4. The field store already has
      a documented reversal (`urnas_add_pos_calc` PRD 0008 vs 0009) as a ready test case.
      *Effort:* L. Deterministic polarity + reversal net; doctor warns; LLM enrich on
      deep dream. Still does not pick a winner.

- [x] **R7-4 — Temporal facts and lifecycle decay.** (interim mitigation shipped:
      `doctor` flags `high`-priority entries whose bodies declare themselves resolved.
      Full `valid_from` / `superseded_by` / access-count decay remains future work.)

**Explicitly not doing:** a second AGENTS.md generator (would fight `sync-agents` and the
pre-commit hook — decided 2026-07-24), and merging a code-graph tool into memory-fabric.
Code graph answers *"how does this run?"*; memory answers *"why did we choose this?"*
A router (R5-3) is the right coupling; a shared database is not.

---

## 10. Execution order and sequencing rationale

| Order | Phase | Why here |
|---|---|---|
| 1 | **R0** (+ R6-1 harness) | Days of work, fixes the over-budget bug agents hit every session. Build the metric alongside so R1 is measurable. |
| 2 | **R2** | Independent of all retrieval work, unblocked by Cursor's current schema, and R2-2 closes the write-protocol violation class outright. |
| 3 | **R1** | The real fix, and the largest. R1-3 depends on R3-1 landing first or maps go stale as they become load-bearing. |
| 4 | **R3** | R3-1 must precede or ship with R1-3. R3-2/R3-4 are small and independent. |
| 5 | **R4** | Improves what future retrieval can find; no dependency on R1. |
| 6 | **R5** | Token hygiene; R5-2 is most valuable after R1-3 shrinks the startup bundle. |
| 7 | **R6-2/R6-3, R7** | Publish numbers only once the read path is fixed. |

**Suggested releases:** `1.2.1` = R0 + R2-4 + R3-2 + R3-4 (bug-fix shaped, no model
change). `1.3.0` = R2 Cursor hooks + R3-1 + R4-1/R4-2 + R5-1. `1.4.0` = R1 indexed read
path + `context_for_task` + R6-1 — the release that earns a read-path regrade.

### The one-line version

The field report's closing advice — *treat memory as a searchable wiki agents must query,
not as automatically loaded wisdom* — is the correct **interim** operating procedure, and
R1-3 plus R1-4 are what make it the **default** rather than a workaround. Everything else
here protects that: R0 so the budget is not a lie, R2 so knowledge gets captured on the
tool the team actually uses, R3 so the maps agents now depend on cannot rot, R4 so what
was captured can be found, and R6 so the next report can be a number instead of a grade.
