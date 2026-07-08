# Memory Fabric — Roadmap to Best-in-Class

> Goal: make Memory Fabric the best memory layer for AI coding assistants — installable in
> one command in VS Code, Claude (Code + Desktop), Codex, Antigravity, Cursor, Windsurf,
> Gemini CLI, Cline, and anything MCP-compatible.

Last updated: 2026-07-07 · Current version: 0.7.0 ([live on PyPI](https://pypi.org/project/memory-fabric/)) · Tests: 190 passing

---

## 1. Positioning: what "best in the world" means for us

The memory market leaders (Mem0 ~47k stars, Zep/Graphiti, Letta) all compete on
**conversational user memory**: cloud services, vector/graph databases, personalization.
We do not out-spend them there. We win a different, underserved category:

**Project memory for coding agents — file-first, local-first, cross-tool.**

| | Mem0 / Zep / Letta | Memory Fabric |
|---|---|---|
| Storage | Vector DB / graph DB / cloud | Markdown + YAML in the repo |
| Ownership | Their infra or your DB | Your git history |
| Reviewable by humans | No (embeddings) | Yes (plain files, PR-diffable) |
| Team sharing | Per-account sync | `git pull` |
| Works offline / air-gapped | Mostly no | Yes |
| Same memory in every agent | Partial (OpenMemory MCP) | Core design goal |
| Secret redaction on write | No | Yes |
| Memory quality evals | No | Built-in (`ai-memory eval`) |

"Best in the world" = the definitive answer to *"my coding agents should share one
persistent, trustworthy, human-auditable project brain, in every tool I use."*
Every phase below either widens distribution, deepens quality, or proves the claim.

---

## 2. Phase 0 — Foundation hardening (trust before growth)

Before asking thousands of people to install it, make failure impossible to hide.

- [x] **Split the god module.** Done 2026-07-04 (Milestone B): `storage/_core.py` split into
      12 modules (`context.py`, `store.py`, `dream.py`, `journal.py`, `search.py`,
      `snapshots.py`, `sections.py`, `lifecycle.py`, `consolidation.py`, `finalize.py`,
      `patch.py`, `_shared.py`), all <25 KB, public API re-exported from
      `memory_fabric.storage`. (`eval.py` at ~41 KB still exceeds the 25 KB bar.)
- [x] **CI matrix.** GitHub Actions: {windows, macos, ubuntu} × {3.11, 3.12, 3.13, 3.14},
      `pytest`, `ruff check`, `ruff format --check`, `mypy` (the package ships `py.typed`
      — enforce it). Badge in README. Confirmed green on GitHub 2026-07-05.
- [ ] **Coverage gate** (start at current %, ratchet up; target ≥85%).
- [ ] **Docs truth pass.** README still says "v0.1.0" while `pyproject.toml` says 0.3.0;
      single-source the version and audit every README claim against behavior.
- [ ] **Concurrency & corruption tests.** Two writers, crashed process mid-write, huge
      files, non-UTF-8 bytes, symlinks. These are the bugs that kill trust.

Exit criteria: green CI badge on all three OSes, no file >25 KB in `src/`, coverage gate on.

## 3. Phase 1 — Install everywhere (distribution)

This phase is the direct answer to "usable in VS Code, Claude, Codex, Antigravity and others."

### 3.1 Publish to PyPI (unlocks everything else)

- [x] Reserve names `memory-fabric` on PyPI (published 2026-07-06; `agentic-memory` alias not taken).
- [x] GitHub Actions **trusted publishing** (OIDC, no API tokens) on tag push.
- [x] After this, the universal zero-install invocation becomes:
      `uvx --from "memory-fabric[mcp]" memory-fabric-mcp`
      (works on any machine with `uv`; document `pipx` fallback).

### 3.2 One-command client setup: `ai-memory install`

**Done (2026-07-05) — see `z_PLAN.md` Milestone C for the full implementation record,**
including two path/root-key corrections found by checking current docs instead of
relying on training-data knowledge for the fast-moving clients (VS Code, Antigravity).

New CLI command that detects/receives a client name and writes the right config,
idempotently, with `--dry-run` support:

| Client | What `ai-memory install --client <x>` writes |
|---|---|
| `claude-code` | Runs `claude mcp add memory-fabric -- uvx --from "memory-fabric[mcp]" memory-fabric-mcp`, or writes project `.mcp.json` |
| `claude-desktop` | Adds entry to `claude_desktop_config.json` (per-OS path) |
| `vscode` | Workspace `.vscode/mcp.json` or user-profile MCP config (Copilot agent mode) |
| `cursor` | `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global) |
| `windsurf` | `~/.codeium/windsurf/mcp_config.json` |
| `codex` | `[mcp_servers.memory-fabric]` table in `~/.codex/config.toml` (or `codex mcp add`); project-scoped `.codex/config.toml` supported |
| `antigravity` | `~/.gemini/config/mcp_config.json` (central config shared by Antigravity IDE/CLI and Gemini CLI) |
| `gemini-cli` | Same central config as Antigravity |
| `cline` | Cline MCP settings JSON |
| `all` | Detects installed clients and configures each |

Design rules: never clobber existing entries; JSON/TOML merge, not overwrite; print the
exact diff; `--uninstall` flag for clean removal.

### 3.3 Official MCP Registry

- [ ] Create `server.json`, publish via `mcp-publisher` under the
      `io.github.elvirafa/memory-fabric` namespace to registry.modelcontextprotocol.io.
- [ ] This feeds the VS Code MCP store, Cursor's directory, Glama/PulseMCP/mcp.so
      aggregators — free discovery in every client that browses the registry.

### 3.4 One-click installs

- [x] **VS Code / Cursor install badges** in README (deeplink `vscode:mcp/install` /
      `cursor://` URLs with the server config embedded). Done 2026-07-05 (Milestone D).
- [x] **MCPB bundle** (`.mcpb`) built in CI for drag-and-drop install into Claude Desktop.
      Done 2026-07-05 (Milestone D); live-tested on Windows — macOS test still pending.

### 3.5 README install matrix

- [ ] Rewrite the Installation section as a per-client table: one copy-paste command or
      badge per client, each verified by an integration smoke test in CI.

Exit criteria: a stranger on any OS gets from "found the repo" to "agent reads/writes
memory in their tool" in under 2 minutes, for all clients above.

## 4. Phase 2 — Store-first memory model (maps become views, not sources)

Decided 2026-07-06: hand-written long-form memory in flat root files does not survive
contact with real sessions. `memory-store/` becomes the only hand-written source of
truth for project facts; the flat root sections become **generated executive maps** —
compiled by Dreaming from their `memory-store/<category>/` subtree, a table of contents
with summaries rather than a place agents dump prose.

| File | Today | After |
|---|---|---|
| `architecture.md`, `decisions.md`, `debt.md`, `schemas.md` | writable long-form sections | generated maps (`generated: true`), rebuilt by Dreaming |
| `framework-rules.md`, `ubiquitous-language.md` | budget-competing sections | always-loaded local directives (steering, not memory) |
| `index.md` | hand-maintained | generated discovery index (kept) |
| `memory-store/**` | secondary granular store | the single write target for facts |

Why — all four problems observed in this repo's own dogfood `.ai-memory/`:

- **Rot.** Our `architecture.md` still described `storage.py` as a single module a month
  after the Milestone B split, and its layout diagram predates `memory-store/`. Views
  generated from the store cannot drift.
- **Budget starvation.** The seven flat sections total ~16 KB ≈ ~4k tokens (chars/4) —
  the entire default context budget — and context assembly orders local flat files ahead
  of store files at equal priority, so stale maps crowd out relevant granular memories.
- **All-or-nothing packing.** Assembly never slices a file mid-document; a long flat file
  either consumes a huge slice of the budget or collapses to a one-line summary. Small
  store files pack tightly under BM25 + priority ranking.
- **Phase 4 needs granularity.** Temporal facts, link graph, lifecycle, and contradiction
  detection are all per-fact frontmatter designs; long multi-topic files fight them.

The agent rules already steer fact writes to `write_memory_store_tool`, and the starter
templates already call the flat sections "executive maps" — this phase finishes that
thought and removes the write path that lets maps rot.

### 4.1 v0.6 — store-first by default (non-breaking)

**Implemented 2026-07-06** (`storage/maps.py` + hooks; 151 tests green). Hand edits are
folded into `memory-store/<category>/map-notes-pending-review.md` — a real store entry,
reviewable and git-tracked — at the start of every Dream, so folded content is
consolidated in that same run. Bonus fix: low-priority files were silently dropped from
context assembly (`>= 3` filter against the 0–2 priority scale).

- [x] Dreaming regenerates each root map from its `memory-store/<category>/` subtree;
      maps gain `generated: true` frontmatter. Regeneration never silently destroys
      hand edits — they are folded into the store as pending-review entries.
- [x] Deprecation warning on `write_local_memory_tool`; docs + agent rule files direct
      all fact writes to `write_memory_store_tool`.
- [x] Steering sections (`framework-rules`, `ubiquitous-language`, or any section with
      `role: steering`) are always-loaded local directives, never evicted by the budget.
- [x] Context assembly interleaves store and flat files strictly by priority (drop the
      flat-before-store bias in `_ordered_context_files`); generated maps get a compact
      token cap (`MEMORY_FABRIC_MAP_TOKEN_CAP`, default 600).
- [x] `ai-memory eval`: `section_coverage` rescored to store-structure coverage +
      generated-map freshness via `store_fingerprint` (a stale generated map fails).

### 4.2 v0.8 — migration tooling

**Relabeled 2026-07-07**: this milestone was originally called "v0.7" but the actual
v0.7.0 release shipped Phase 3 (capture reliability) + Phase 3.5 (git-native trust)
instead — those were higher-leverage and didn't block on this. Migration tooling moves to
v0.8, still unbuilt.

- [x] Starter templates already produce generated-map placeholders (`generated: true`,
      `role: steering`), not writable sections — this fell out of 4.1's work in
      `templates.py`, ahead of schedule.
- [x] README "Project Memory Layout" rewritten to describe the store-first model
      (`memory-store/` as source of truth, generated maps, steering sections, `evidence`
      citations, capture reliability, git-native trust). Done 2026-07-07.
- [ ] `ai-memory migrate`: split legacy hand-written sections into store entries
      (LLM-assisted when configured; heading-based heuristic fallback). Snapshot first,
      `--dry-run` prints the full plan, rollback restores the snapshot.
- [ ] `ai-memory init` pre-scaffolds empty store category directories (`memory-store/`
      currently only gets a `.gitkeep`; categories are created lazily on first write).
- [ ] Migration guide in `CHANGELOG.md` (the repo has no changelog yet — needs to exist
      before this can point to it; see Phase 6 community-hygiene item).
- [ ] Run the migration on this repo's own `.ai-memory/` and record before/after eval
      scores as the reference case.

### 4.3 v1.0 — flat write path removed

- [ ] `write_local_memory_tool` removed from the MCP surface (or narrowed to the
      directive tier only); `read_section_tool` stays — maps are still readable files.
- [ ] `ai-memory doctor` flags legacy hand-written root sections and points to `migrate`.
- [ ] `.ai-memory/` root contains only generated files (maps, `index.md`,
      `consolidated_memory.md` cache), directives, and the store/journal/snapshot dirs.

Invariants: never delete user content (migration copies + snapshots before rewriting);
generated maps must produce stable, PR-reviewable diffs; maps remain the human entry
point — generation is what keeps them trustworthy, not what demotes them.

Exit criteria: on a fresh `init` and on this repo's migrated store, every fact lives in
`memory-store/`, every root map carries `generated: true`, and `ai-memory eval` scores
at or above the pre-migration baseline.

## 5. Phase 3 — Capture reliability (memory that writes itself)

Instruction-only capture fails silently. The rules files get high compliance on the
session-start read, low compliance on mid-session writes, and medium compliance on the
end-of-session journal; context compression erodes the rules in exactly the long
sessions that produce the most knowledge; clients that never load rules files (Claude
Desktop, Open WebUI) run on tool docstrings alone. Today's only automation — the
post-commit Dream — consolidates what exists but captures nothing new: if the agent
skipped every write, the hook consolidates emptiness. Net effect: the most valuable
sessions are the most likely to lose their knowledge.

Two complementary mechanisms close the gap. Both are opt-in, per the project's
opt-in-automation rule (see `decisions.md` engineering philosophy).

### 5.1 Passive capture via git hook (any client, zero agent cooperation)

**Implemented 2026-07-07** (`storage/capture.py`, `finalize.build_consolidation_prompt`,
diff-budget rewrite; 15 new tests). The post-commit hook now runs `ai-memory capture`
before `dream`, so every commit is recorded with no agent cooperation.

- [x] **Extraction prompt.** The consolidation prompt (now a single shared builder,
      deduplicated from two copies) instructs the LLM to propose **new**
      `store/<category>/<slug>` entries from the diff/transcripts, not just edit existing
      sections.
- [x] **Provenance rails.** Passive captures live at `memory-store/episodic/commits/<date>`
      with `source: passive-capture` + `review_status: pending` frontmatter and the
      commit hash in the body; idempotent per commit hash. Kept separate from
      agent-written session journals so provenance stays clean.
- [x] **No-LLM fallback.** `capture_commit` is pure Python — records message, files, and
      diffstat with zero provider, giving the next LLM-assisted Dream raw material.
- [x] **Smarter diff budget.** `_summarize_diff` truncates per file (1.5 KB each, 6 KB
      total) and elides lock/vendored/generated files instead of one 4 KB global cut.

### 5.2 Enforcement via client hooks (instructions become mechanisms)

Primitives shipped 2026-07-07; the client-side settings.json writer is the remaining work.

- [x] **Session marker plumbing.** `write_session_journal` touches
      `.ai-memory/private/last_journal_at`; `ai-memory session-start` writes
      `session_started_at`. Pure Python, no transcript parsing.
- [x] **Stop-hook primitive.** `ai-memory guard-journal` exits 2 (blocking) with a reason
      when no journal was written since session start, exit 0 otherwise; fails open when
      there is no session marker. This is the command a Stop hook calls.
- [ ] **Claude Code settings.json writer.** `ai-memory install --client claude-code
      --with-hooks` wires SessionStart (inject context), Stop (`guard-journal`), and
      PreCompact (journal checkpoint) into the client's settings. **Needs the live
      Claude Code hook schema verified against current docs + a real-session smoke test
      before shipping** — deferred rather than guessed.
- [ ] **SessionStart context injection** and **PreCompact checkpoint** wiring (depend on
      the settings.json writer above).
- [ ] **Client capability survey.** Cursor hooks (beta), Codex `notify`, Gemini CLI:
      per-client enforcement matrix in the docs.

### 5.3 Prove capture actually happens

- [x] Local capture stats in `ai-memory status` (`capture` block): last journal, commit
      captures, episodic files, memories total + last-7-days. Local only — the
      no-telemetry guarantee stands.
- [ ] Capture-rate metric in the coding-memory benchmark (Phase 5): % of scripted
      sessions whose knowledge survives into the next session, instructions-only vs
      hooks-enabled.

Exit criteria: with hooks enabled, a fully non-compliant agent still produces (a) an
episodic record per commit and (b) a session journal per session, and `ai-memory status`
shows both. **(a) + the status surface are implemented and tested on `main`; (b) lands
with the settings.json writer (next release).** Passive capture (5.1) has no dependency
on the v1.0 gate.

## 6. Phase 3.5 — Git-native trust (the moat only a file-first, git-native design can dig)

**Implemented 2026-07-07** (`merge_driver.py`, `storage/verify.py`, `storage/failures.py`; 24
new tests, 190 total). Every one of these depends on being files inside a git repo — a
vector-DB competitor cannot copy any of them.

### 6.1 Semantic git merge driver — memory that merges with the code

Two branches that both append new facts to the same store file used to produce a textual
conflict on the shared `last_updated` line even though the actual content additions never
overlapped. `ai-memory init --merge-driver` registers a custom driver
(`.gitattributes` + local `git config merge.memory-fabric.driver`) that:

- [x] Merges cleanly when one side changed nothing, or both sides purely *appended* new
      content to a shared prefix — the common case for memory writes — deduping
      exact-duplicate lines the same way `write_memory_store`'s append mode does.
- [x] Reconciles frontmatter independently of the body: `tags` union, more-urgent
      `priority` wins, `last_updated` takes the later timestamp.
- [x] Falls back to `git merge-file` (git's own textual 3-way merge, conflict markers and
      all) for anything it doesn't understand — never worse than not having the driver.
      A generated map (`generated: true`) left with conflict markers self-heals: the next
      Dream fails to parse it, treats it as ungenerated, and fully regenerates it.
- [x] Verified with a real end-to-end test: two branches each append a different fact to
      the same store file, `git merge` resolves with zero conflict markers and both facts
      present.
- Known limitation, documented in the tool's own warning output: merge driver
  *registration* is per-clone by git's own design — `.gitattributes` is committed and
  shared, but `ai-memory init --merge-driver` must be re-run after every fresh clone.

### 6.2 Self-verifying citations — memory that can prove it's still true

An optional `evidence` frontmatter list (`write_memory_store_tool(..., evidence="src/auth.py:42,commit:abc123")`)
lets a memory cite what it depends on. `ai-memory verify`:

- [x] Checks each ref: file paths (existence), `path:line` (line count), `commit:<hash>`
      (via `git cat-file -e`). Unverifiable kinds (`pr:123`, URLs) are skipped rather than
      flagged — checking them would need a network call, which the local-first guarantee
      forbids.
- [x] Stamps `review_status: broken-evidence` on files whose citations no longer resolve
      (`--no-mark` for a read-only report).
- [x] Wired into `ai-memory eval`'s `metadata_quality` category as a read-only check
      (eval must not mutate files as a side effect of scoring — mutation is `verify`'s
      job, an explicit opt-in action).
- This is the structural answer to the store-first migration's original motivating bug:
  this repo's own `architecture.md` cited a module that had been split a month earlier,
  and nobody noticed until a human happened to read it. A cited-file rename now fails a
  machine check instead of waiting for a human.

### 6.3 Failure memory — the highest-ROI category for a coding agent

`write_failure_memory_tool(cwd, error_summary, fix_summary)`:

- [x] Normalizes the error text (paths and numbers stripped) into a stable signature, so
      the *same kind* of error seen at different call sites/line numbers collapses onto
      one growing `memory-store/failures/<slug>` entry instead of fragmenting.
- [x] Increments an `occurrences` counter on repeat hits and surfaces a warning
      ("occurred N times — consider a systemic fix") once a pattern repeats.
- [x] Immediately searchable via the existing `keyword_search_tool` — no new retrieval
      path needed.
- [x] A short, non-mandatory nudge was added to the canonical agent instructions
      (`templates.py`) so agents call it right after fixing a bug.
- Deliberately agent-invoked, not part of passive capture: there is no reliable
  cross-language way to detect "a bug was just fixed" from a git diff alone.

Exit criteria met: `ai-memory init --merge-driver` on a real repo produces a working
`.gitattributes` + git config; two branches appending different facts merge with zero
conflict markers; `ai-memory verify` flags a citation to a deleted file; two calls to
`write_failure_memory_tool` with the same normalized error collapse onto one file with
`occurrences: 2`.

## 7. Phase 4 — Retrieval quality (be the best, not just the most compatible)

Keep the zero-dependency, no-vector-DB default. Add optional layers that degrade gracefully
— the same pattern already used for `rg` and LLM providers.

- [ ] **Hybrid retrieval.** Keep BM25 (shipped). Add optional local embeddings via a
      small ONNX model (e.g. fastembed) + `sqlite-vec` stored inside `.ai-memory/` local
      (gitignored) cache. Blend scores: BM25 + cosine + priority + recency. No cloud calls.
- [ ] **Temporal facts.** Frontmatter gains optional `valid_from` / `superseded_by`.
      Dreaming marks contradicted facts as superseded instead of deleting — the agent can
      answer "when did we change X?" This is Zep's headline feature, done file-first.
- [ ] **Link graph.** `[[wiki-links]]` between memory files + a generated entity index.
      A cheap knowledge graph with zero database — retrieval follows links one hop out.
- [ ] **Memory lifecycle.** Provenance (`source_session`), access-count decay, confidence
      scores; Dreaming demotes stale/unused memories instead of letting them rot.
- [ ] **Contradiction detection** during Dreaming (LLM-assisted when available, Jaccard
      fallback), surfacing conflicts for human review rather than silently choosing.
- [ ] **Latency budget.** `read_combined_context` p95 under 150 ms on a 500-file store;
      add a perf test to CI.

## 8. Phase 5 — Prove it (benchmarks nobody can argue with)

Claims without numbers don't win "best in the world."

- [ ] **Run the standard benchmarks.** Build a small adapter that feeds LongMemEval (S,
      then M) and LoCoMo through Memory Fabric's store/retrieve loop; publish scores and
      the exact reproduction script. These are conversational benchmarks — expect strong
      but not chart-topping numbers; honesty here buys credibility.
- [ ] **Create the coding-memory benchmark.** There is no dominant benchmark for *project
      memory in coding agents*. Build one: N repos × M sessions of realistic tasks, where
      later tasks require decisions recorded in earlier sessions ("which auth approach did
      we pick and why?", "what's the deprecated API we must avoid?"). Score memory-on vs
      memory-off agents. Publish it as a standalone repo — owning the benchmark defines
      the category.
- [ ] **Ship `ai-memory bench`** so any user can run the suite against their own store.
- [ ] Results table in README with reproduction commands.

## 9. Phase 6 — Ecosystem & growth

- [ ] **Docs site** (mkdocs-material on GitHub Pages): quickstart per client, concepts
      (Tiers, Dreaming, store), MCP tool reference, benchmark methodology.
- [ ] **90-second demo** (GIF in README + video): init → agent writes memory in Claude
      Code → same memory read from VS Code and Codex. The cross-tool moment is the hook.
- [ ] **Launch sequence**: PyPI + registry live → Show HN → r/ClaudeAI, r/cursor,
      X/Twitter dev threads → submit to awesome-mcp-servers lists.
- [ ] **Community hygiene**: CONTRIBUTING.md, issue/PR templates, CHANGELOG (keep-a-changelog),
      semver discipline, GitHub Releases automated from tags.
- [ ] **Telemetry: none.** Make "no telemetry, no account, no cloud" a stated guarantee —
      it is a differentiator in this category.

## 10. Success metrics

| Metric | 3 months | 12 months |
|---|---|---|
| Install friction | ≤2 min on any listed client | one-click on all majors |
| PyPI downloads/month | 1k | 20k |
| GitHub stars | 500 | 5k |
| Benchmark | published LongMemEval score | top-3 on own coding-memory benchmark, cited by others |
| Clients verified in CI | 4 | 9+ |
| Capture rate (hooks on) | episodic record per commit, no agent cooperation | 100% of benchmark sessions journaled with a non-compliant agent |

## 11. Suggested execution order

1. **Phase 1.1 PyPI publish** — small effort, unblocks every install story. Do first.
2. **Phase 0 CI + module split** — in parallel; must be green before launch.
3. **Phase 1.2–1.5 install command + registry + badges + MCPB** — the "everywhere" ask.
4. **Phase 2 store-first memory model (v0.6)** — the breaking model change itself;
   migration tooling (v0.8) must still land **before** v1.0's stability promise, not
   after it. (v0.6 shipped 2026-07-06.)
5. **Phase 3.1 passive capture + Phase 3.5 git-native trust (v0.7)** — independent of the
   v1.0 gate and demo brilliantly ("commit, and the project brain updates itself"; "two
   branches merge their memory as cleanly as their code"); strong launch material.
   (v0.7 shipped 2026-07-07.)
6. **Phase 2.2 migration tooling (v0.8)** — still unbuilt; the last v1.0 blocker left
   from Phase 2. Do this before item 7.
7. **Launch v1.0** (Phase 6 demo + announcements) on the strength of distribution and
   the clean store-first model.
8. **Phase 3.2–3.3 client-hook enforcement + capture stats** — post-launch, guided by
   which clients real users actually run.
9. **Phase 4 retrieval quality** — you can only rank what was captured; capture first.
10. **Phase 5 benchmarks** — publish numbers; the coding-memory benchmark is the moat,
    and it doubles as the proof for Phase 3's capture-rate claim.
