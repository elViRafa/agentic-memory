# Changelog

All notable changes to **memory-fabric** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(0.x: minor versions may contain breaking changes, called out explicitly below).

## [Unreleased]

## [1.2.0] — 2026-07-29

> Memory that survives a team. Reported from a multi-developer project: every
> merge produced conflicts in `.ai-memory/` — `failures.md`, `index.md`, and the
> episodic day file both developers had journaled into.

### Added

- **`ai-memory resolve-conflicts`** — resolves the conflicted `.ai-memory` files
  of an *in-progress* merge and stages them, reading the three sides from the
  index stages git already recorded. The merge driver only helps people who
  registered it *before* merging; this is the way out for a team that is already
  sitting in a conflicted merge, with no need to redo it. Files that need a human
  are left untouched, reported, and make the command exit non-zero.
- **`ai-memory doctor` now warns when the merge driver is half-installed.**
  `.gitattributes` is committed and shared, the driver command is per-clone by
  git's design — so a teammate's fresh clone silently falls back to textual
  merges. Doctor names the gap and the fix in both directions (declared but not
  registered, registered but not declared).
- **Any `ai-memory init` registers the driver in a clone that already declares
  it.** Closes the same gap from the other side: the person who ran
  `init --merge-driver` commits `.gitattributes`, and everyone else picks up the
  local half without having to know it exists.

### Changed

- **Generated views never conflict.** The root maps (`generated: true`) and the
  two discovery indexes are derived from `memory-store/` and rebuilt on every
  Dreaming run, so a textual conflict in one was never worth a human's attention.
  They now union-merge. The merged file is re-stamped (`body_hash` recomputed,
  `store_fingerprint` blanked) so the next `regenerate_maps` rebuilds it from the
  store instead of mistaking the merge for a hand edit and folding the union into
  `memory-store/` as a permanent memory.
- **Store entries merge block by block.** The driver previously required both
  sides to be pure appends onto a shared prefix, and deferred everything else to
  a textual conflict. It now merges per `##` entry, which covers the shape two
  agents produce on a shared branch: separate new session entries in the same
  episodic day file, plus an edit to an older entry. Only a single entry rewritten
  on *both* sides — a real disagreement — still goes to git's textual merge.
- The driver is now registered with git's `%P` placeholder, so it knows the real
  pathname being merged. Clones registered before this keep working; `index.md` is
  recognized from its frontmatter as well as its path.

## [1.1.2] — 2026-07-27

> Graceful degradation: an agent that cannot reach the MCP tools now has a
> sanctioned way to skip the memory protocol without discarding the project
> rules that ship in the same file.

### Fixed

- **The memory protocol now yields cleanly when the MCP server is absent.**
  Reported from a consumer project running 1.1.1: on a machine where the
  memory-fabric MCP server was never configured, agents read the generated
  instruction file, hit *"MANDATORY STARTUP: You MUST call
  `read_combined_context_tool` … No exceptions"*, could not comply, and
  fixated on the missing server — one concluded the entire file was
  inapplicable and fell back to its own native memory, taking the project
  directives in that same file down with it. `MEMORY_INSTRUCTIONS` now opens
  with rule 0: if the tools are not available, skip the memory protocol
  entirely, do **not** substitute another memory system, and keep obeying the
  Project Directives regardless. It reaches every generated artifact —
  `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
  `.agents/rules/memory-store.md`, `.cursor/rules/memory-fabric.mdc`,
  `.windsurf/rules/memory-fabric.md` — because they all compose the same
  constant, and `sync-agents` refreshes marker-managed blocks in place, so
  files written by 1.1.x pick the clause up on the next sync. The startup
  rule's "No exceptions" — the exact sentence the agent got stuck on — now
  names rule 0 as the one sanctioned way out, so the two rules don't have to
  be adjudicated by the reader.
- **`doctor` no longer nags about an empty legacy root map.** A map section
  without `generated: true` was flagged as legacy hand-written content on
  every run, even when the file was an empty stub or the untouched init
  starter template (reported for `decisions.md` with an empty
  `memory-store/decisions/`). `ai-memory migrate` skips exactly those files,
  so no command could ever clear the warning. Doctor now mirrors migrate's own
  skip rules and flags only bodies migrate would actually extract from; the
  next Dream stamps the stub `generated: true` on its own.

### Added

- **`doctor` warns when generated agent files are gitignored.** The generated
  files are the entire delivery mechanism — ignored and untracked, they are
  regenerated locally forever while teammates, CI agents, and Copilot on
  another checkout receive neither the memory protocol nor the project
  directives, with nothing in the system noticing. `git check-ignore` (index
  aware, so force-added files are correctly treated as delivered) now reports
  the affected paths. Silent outside a git repo and when git is unavailable.
- **Project directives lead the shared user files.** A directives block that
  is not yet present in `AGENTS.md` / `CLAUDE.md` /
  `.github/copilot-instructions.md` is inserted *above* the
  memory-fabric:instructions block, so an agent that legitimately skips the
  memory protocol has already read the project rules. Blocks that already
  exist are never relocated — sync keeps rewriting them where the file has
  them, so existing installs see no reordering.

### Changed

- **`--json` is accepted after the subcommand.** `ai-memory doctor --json` was
  a parse error; only the global position (`ai-memory --json doctor`) worked.
  Both forms now work, including nested store commands
  (`ai-memory store list --json`). The global form is unaffected — the
  subcommand flag uses a suppressed default so it cannot reset it.

### Notes

- Sync/context routing semantics are untouched.
- Marker-block round-tripping stays byte-stable for content outside the
  markers, in both insertion positions: the blank-line separator is stripped
  from whichever side it was added to, so insert → remove → re-insert restores
  the file exactly.
- The clause reads "Any Project Directives block (in this file, or in a
  generated `project-directives` rule file)" rather than "below", since the
  directives block now leads the shared files and lives in a separate file for
  the Cursor/Windsurf/`.agents` rule sets.

## [1.1.1] — 2026-07-24

First published release of the 1.1 line. 1.1.0 was tagged but never
published — its release run failed on a test that compared a raw temporary
path against the canonical one storage returns, so every macOS and Windows
job failed and the publish steps were skipped. The tag could not be moved,
so the fixed tree ships as 1.1.1. **The user-facing feature set is exactly
the 1.1.0 entry below**; nothing was added or removed.

### Fixed

- **Path canonicalization in the `sync-agents` test suite.** The suite
  compared `would_change` paths against an unresolved `tempfile` root, which
  only matches where the temp root has no alias — it broke on macOS
  (`/var` → `/private/var`) and Windows (8.3 short name `RUNNER~1` vs
  `runneradmin`). The temp root is now resolved once in the shared `setUp`.
- **`ruff format` compliance for Markdown code blocks.** ruff 0.16 formats
  Python blocks embedded in `.md` files, so the repo-wide format check began
  failing on fenced examples in `plan.md`. Reformatted; no content change.
- **Temp-directory teardown race in the merge-driver integration test.** Git
  could still be writing `.git/objects` when the temp tree was removed,
  surfacing on macOS as `OSError: [Errno 66] Directory not empty`. Auto-gc is
  disabled in the test repo and a lost cleanup race no longer fails the test.

No source changes — `src/` is byte-identical to 1.1.0 apart from the version
string.

## [1.1.0] — 2026-07-24

> Project directives: user-created, hand-curated development guidelines that
> `sync-agents` distributes to every agent vendor as plain committed files.

### Added

- **Routing frontmatter on steering sections.** Two optional boolean keys:
  `sync` (include the directive in the per-tool files generated by
  `sync-agents`; default `true`) and `context` (inject as Tier 0 into
  `read_combined_context`; default `true` only for the built-ins
  `framework-rules`/`ubiquitous-language`, `false` for user directives —
  file-reading agents already receive the synced copy, so double-injection
  would waste context). Schema version stays `1.3` (additive optional keys);
  `doctor` and the write path reject non-boolean values.
- **`sync-agents` composes project directives into per-tool files.** All
  `sync: true` steering sections (frontmatter stripped; built-ins first, then
  alphabetical) are assembled into one document written as
  `.agents/rules/project-directives.md`, `.cursor/rules/project-directives.mdc`,
  and `.windsurf/rules/project-directives.md`, plus a marker-managed block in
  `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` — so
  AGENTS.md-only readers (Codex, OpenCode, Gemini) finally get the project
  directives. Deleting the last `sync: true` directive removes the generated
  files and marker blocks again (clean teardown). The result dict gains
  `directives_synced`.
- **`sync-agents --check` (CI drift gate).** Computes every target's would-be
  content, writes nothing, and exits 1 listing the out-of-sync paths (honors
  `--json`); exit 0 when clean. The pre-commit hook keeps running the writing
  sync.
- **`doctor` guardrails for the directive tier.** (1) Warns when the
  always-loaded context surface (global Tier 0 file + all `context: true`
  steering sections) exceeds a token budget (default 3000, overridable via
  `MEMORY_FABRIC_DIRECTIVE_BUDGET`), sizing the `sync: true` block separately.
  (2) Detect-only secret scan over hand-curated steering files (hand edits
  bypass write-path redaction) — warns, never rewrites. (3) Flags fabric
  headings outside the managed markers in `AGENTS.md`/`CLAUDE.md`/copilot as
  stale pre-1.1 blocks to delete by hand.
- **Project directives exception in the agent instructions.** `role: steering`
  files in `.ai-memory/` are hand-curated policy that humans and agents MAY
  edit directly with file tools (review via MR); everything else in
  `.ai-memory/` remains MCP-tools-only. After editing, run
  `ai-memory sync-agents` (or rely on the pre-commit hook).
- **CLI demo GIF** (`docs/demo-cli.gif`), rendered from a real `ai-memory` session
  (init → write a memory → commit auto-captures → status) and embedded in the README.

### Changed

- **Shared user files are now managed via marker blocks.** The fabric protocol
  content in `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md`
  lives between `<!-- >>> memory-fabric:instructions >>> -->`-style markers
  (same pattern as the installer's TOML blocks); `sync-agents` replaces only
  the content inside its markers and preserves everything outside them
  byte-for-byte — fixing the pre-1.1 bug where the heading-to-EOF regex
  clobbered user content below the fabric block. Legacy unmarked blocks in
  `CLAUDE.md`/copilot are wrapped in markers once on the next sync; a stale
  unmarked block in `AGENTS.md` is never rewritten (doctor flags it instead).
- The pre-commit hook's `git add` list now covers the project-directives
  outputs and `AGENTS.md`, and stages deletions (`git add -A`) so teardowns
  are committed too.

## [1.0.0] — 2026-07-17

> Store-first model finalized. This release removes the hand-write path for
> fact/map sections — **breaking** for any client that wrote facts to flat root
> sections; migrate that content with `ai-memory migrate`.

### Added

- **Launch-prep community files (ROADMAP Phase 6):** `LICENSE` (MIT — the file was
  missing even though `pyproject.toml` and the README declared MIT), `CONTRIBUTING.md`,
  `SECURITY.md`, GitHub issue templates and a pull-request template, a `DEMO.md`
  storyboard for the 90-second cross-tool demo, and an explicit "no telemetry"
  guarantee in the README, `SECURITY.md`, and `CONTRIBUTING.md`.
- **`ai-memory doctor` flags legacy hand-written root sections.** A map-category
  file without `generated: true` frontmatter (pre-migration hand-written content)
  now produces a warning pointing to `ai-memory migrate`. Clean on a fresh `init`
  and on a migrated store.

### Changed

- **Store-first flat write path narrowed to the directive tier (ROADMAP Phase 2.3,
  v1.0).** `write_local_memory_tool` now rejects writes to the generated root map
  sections (`index`, `architecture`, `decisions`, `debt`, `schemas`) and to
  arbitrary fact sections, pointing the caller at `write_memory_store_tool` (then
  `dream_tool` to rebuild the maps). Only steering sections — `framework-rules`,
  `ubiquitous-language`, or content/files declaring `role: steering` — remain
  writable through this tool. This closes the last hand-write path that let
  generated maps rot. The internal `write_local_memory` engine is unchanged (map
  regeneration and `ai-memory migrate` still use it); enforcement is at the MCP
  tool boundary, its only production caller. **Breaking for any client or agent
  that wrote facts to flat map sections** — migrate that content with
  `ai-memory migrate` and write new facts with `write_memory_store_tool`.

### Fixed

- **Post-commit hook no longer traps the working tree in a capture loop**
  (`storage/capture.py`, issue #5). The post-commit hook writes an episodic
  record for each commit, which dirties the tree; committing that memory used to
  be captured in turn, re-dirtying the tree, so no follow-up commit ever reached
  a clean state and a push stayed blocked behind it. `capture_commit` now skips
  commits whose files are entirely under `.ai-memory/` (`skipped_reason:
  "memory-store bookkeeping commit"`), so a single commit of the captured memory
  reaches a clean tree. Commits that mix code and memory changes are still
  captured — only pure memory-bookkeeping commits are skipped.

## [0.8.2] — 2026-07-16

### Added

- **Capture filter** (`storage/capture.py`) — `capture_commit` skips noise commits by
  default (merges, `[bot]` authors, `chore:`/`style:`/`ci:`/`build(deps)` prefixes,
  lockfile-only changes), audibly: a `skipped_reason`, a warning, and a
  `commits_skipped` counter in `ai-memory status`, never a silent no-op.
  `ai-memory capture --no-filter` opts back into capturing everything.
- **Episodic roll-up** (`storage/consolidation.py`) — `ai-memory dream --mode deep` folds
  `episodic/commits/` daily files older than 14 days into weekly
  `week-<iso-year>-w<ww>.md` summaries (`review_status: consolidated`), so passive
  capture's residual accumulation has a real destination instead of growing forever.
- **Client lifecycle-hooks writer** (`client_hooks.py`, new) — `ai-memory install
  --client <claude-code|gemini-cli|codex> --with-hooks` wires SessionStart (marks the
  session, injects a short context reminder), Stop (`guard-journal`, blocking), and a
  pre-compaction checkpoint (non-blocking `dream --mode light --apply`) into each
  client's own hook config. Each client's schema was verified directly (official docs
  for Gemini CLI, source code for Codex CLI since its docs 403'd on every fetch) rather
  than assumed from Claude Code's shape, even where they turned out to match. Found and
  fixed along the way: `guard-journal` was printing its block reason to stdout only, but
  every client reads the exit-2 feedback from stderr exclusively.
- **Capture-rate benchmark** (`scripts/capture_rate_benchmark.py`) — scripts a
  non-cooperative simulated agent through 20 sessions per mode: 0% session-journal rate
  with no enforcement, 100% with the Stop hook wired in, commit capture steady at 100%
  either way (it's unconditional on the git hook, not the client-side session hooks).
  Regression-guarded in `tests/test_capture_rate_benchmark.py`.

See [`ROADMAP_CAPTURE_HOOKS.md`](ROADMAP_CAPTURE_HOOKS.md) for the full design record.

## [0.8.1] — 2026-07-14

> `v0.8.0` was tagged and pushed but never published: its release CI caught a
> pre-existing test bug before the publish step ran (same class the project
> has hit before — a test asserted an app-returned resolved path against a
> raw, unresolved temp path; failed only on the Windows runner's 8.3 short
> name). Per the `v0.4.0`→`v0.4.1` precedent below, the tag isn't force-moved;
> `v0.8.1` carries the same migration-tooling changes plus the fix.

### Fixed

- `tests/test_migrate.py::InitScaffoldTests::test_init_scaffolds_store_categories`
  compared `initialize_memory_fabric`'s resolved `files_created` paths against
  an unresolved temp path — passed locally, failed on Windows CI.

### Added

- **`ai-memory migrate`** — one-shot, human-supervised conversion of legacy
  hand-written flat sections (`architecture.md`, `decisions.md`, …) into
  granular `memory-store/` entries (ROADMAP Phase 2.2, the last v1.0 blocker).
  - Heading-based heuristic split: chunks are verbatim source text — nothing
    is rephrased or dropped, by construction. Fence-aware (a `## ` inside a
    code block is content, not a boundary).
  - LLM-assisted *naming only* (store_path/title/tags) when a provider is
    configured; any LLM failure falls back to deterministic heuristic names
    and the migration proceeds.
  - `--dry-run` prints the full plan without writing anything; `--section`
    restricts scope; `--no-llm` forces heuristic names.
  - A snapshot is taken before any write; `ai-memory rollback --to <name>`
    restores the flat sections (see the migration guide below).
  - Re-runs are resumable: entries already on disk with identical content are
    recognized (`already-migrated`) instead of duplicated; conflicting names
    get a `-migrated` suffix so existing granular memories are never clobbered.
  - After a section's entries land, the flat file flips to a
    `generated: true` map — the same view Dreaming rebuilds — so maps can no
    longer rot.
- **`ai-memory init` pre-scaffolds store categories** — `memory-store/` now
  starts with `architecture/`, `decisions/`, `schemas/`, `debt/`, `episodic/`,
  `failures/`, and `rules/` (each with a `.gitkeep`), steering an agent's first
  writes toward the right category instead of inventing one.
- This `CHANGELOG.md`.

### Fixed

- Two eval bugs surfaced by running the migration on this repository's own
  memory (both pre-dated the migration):
  - `metadata_quality` required a `section` frontmatter field on *every* file,
    including `memory-store/` entries — whose canonical write path
    (`write_memory_store`) produces `store_path`, never `section`. Store files
    are now checked for `store_path`, the same local-vs-store split
    `ai-memory doctor` already applied.
  - The eval scored `consolidated_memory.md` (the compiled Dreaming artifact,
    which has no frontmatter by design) because its ignore rule was a
    hand-copied variant that had drifted from the storage layer's; it now
    delegates to the same rule everything else uses.
- The hooks end-to-end test asserted the episodic capture filename using UTC
  "today" while capture names files after the commit's author date (local
  timezone) — the test failed every day during the hours where the two clocks
  disagree on the date (20:00–24:00 in UTC-4). It now derives the expected
  name from the commit itself.

### Migration guide — store-first (v0.8)

Applies to projects initialized before v0.6 whose root sections
(`architecture.md`, `decisions.md`, `debt.md`, `schemas.md`, or custom ones)
still contain hand-written long-form content. Fresh `init`s and already-
migrated projects need none of this.

1. **Review what would happen:**
   ```sh
   ai-memory migrate --dry-run
   ```
   Every legacy section is listed with the exact store entries it will become.
   Steering sections (`framework-rules`, `ubiquitous-language`, or any section
   with `role: steering`), generated maps, and `index.md` are never touched.
2. **Run it:**
   ```sh
   ai-memory migrate            # uses the configured LLM for naming, if any
   ai-memory migrate --no-llm   # deterministic heading-based names
   ```
   A snapshot is created first; the result reports its name.
3. **Refresh the discovery indexes:**
   ```sh
   ai-memory dream --mode light --apply
   ```
4. **Verify:** `ai-memory eval` — scores should hold or improve (see the
   reference case below); `ai-memory status` shows the new store entries.
5. **Rolling back:** `ai-memory rollback --to <snapshot>` restores the flat
   sections. Note that rollback restores overwritten files but does not delete
   the new store entries; if `.ai-memory/` is committed to git (recommended),
   `git restore .ai-memory` / reverting the migration commit is the cleanest
   full undo.

Reference case (this repository's own `.ai-memory/`, 2026-07-13): baseline
`ai-memory eval` scored **85/100** (section_coverage 65, metadata_quality 73).
`ai-memory migrate --no-llm` converted 4 legacy sections (architecture,
decisions, debt, schemas) into 15 granular store entries; after the follow-up
light dream the score was **91/100** with section_coverage at 100. The
temporary metadata_quality dip (73 → 65) turned out to be two pre-existing
eval bugs the new entries amplified, not a migration defect (see Fixed above);
with those fixed the final score is **96/100 with zero failing checks**
(section_coverage 100, metadata_quality 100).

## [0.7.3] — 2026-07-13

### Fixed

- Phase 0 hardening round (ROADMAP §2.1 Q1–Q10) — four real bugs found by
  closing the gap between "tested" and "tested at the real boundary":
  - `dream_tool`/`apply_dream_results_tool` returned `isError: True` over a
    real MCP connection when `apply=True` ran without evaluation (FastMCP
    serializes omitted `NotRequired` fields as explicit `null`); contracts
    widened to accept it, caught by new in-process MCP client contract tests.
  - A malformed flat section crashed `ai-memory dream` in both modes via the
    one index-regeneration scan loop the 0.7.2 fix didn't cover.
  - Writes crashed on existing files containing invalid UTF-8 — including
    `mode="replace"`, whose whole point is overwriting; `append` now refuses
    cleanly, `replace` recovers and warns.
  - A Windows-only cross-process race in `locking.py`: the `.lock` sidecar's
    pending-delete window made a concurrent `open()` in another process raise
    `PermissionError`; fixed with a bounded retry, verified by stress runs.

### Added

- MCP-boundary contract tests for all 17 tools; version-truth CI check;
  coverage gate (82%); cross-process corruption suite; provider preflight in
  `ai-memory doctor`; measured retrieval-latency regression budget.

### Changed

- `eval.py` (48 KB, largest module) split into the `eval/` package; broad
  `except Exception` sites reduced 52 → 21; ruff ruleset widened
  (I, B, UP, SIM, RUF, BLE001, S110, S112).

## [0.7.2] — 2026-07-09

### Fixed

- A memory-store file with malformed YAML frontmatter no longer crashes
  `ai-memory dream`: consolidation, hash-recalculation, and rewrite-task scans
  skip the bad file and surface a warning instead of aborting.

## [0.7.1] — 2026-07-08

### Fixed

- All 15 findings from the first realistic end-to-end test campaign, notably:
  MCP dream results no longer report `isError` on success (P-13, first fix);
  git hooks pin the absolute CLI path and fail audibly instead of silently
  no-oping on unactivated venvs (P-04); failure-memory dedup survives reworded
  errors; installer prefers local binaries with a pinned-uvx fallback; append
  preserves priority; `verify` clears stale markers; no-op dreams keep the git
  tree clean; UTF-8 CLI output on legacy Windows consoles; accurate provider
  warnings; valid diff headers; deterministic contradiction net.

### Added

- Snapshot retention (`ai-memory clean`), `rollback --list`, doctor-clean init.

## [0.7.0] — 2026-07-07

### Added

- **Passive capture** (Phase 3.1): the post-commit hook records every commit
  as episodic memory (`ai-memory capture`) with zero agent cooperation — pure
  Python, no LLM required.
- **Git-native trust** (Phase 3.5): semantic merge driver
  (`ai-memory init --merge-driver`) — two branches appending different facts
  to the same store file merge with zero conflict markers; self-verifying
  `evidence` citations (`ai-memory verify`); failure memory
  (`write_failure_memory_tool`) with occurrence-counted deduplication.
- Session enforcement primitives: `session-start`, `guard-journal`, capture
  stats in `ai-memory status`.

## [0.6.0] — 2026-07-06

### Changed

- **Store-first memory model** (Phase 2, v0.6 — non-breaking): root maps
  (`architecture.md`, `decisions.md`, …) became generated views over
  `memory-store/` categories, rebuilt by Dreaming; hand edits are folded into
  reviewable store entries, never destroyed. `write_local_memory_tool` is
  deprecated for facts (steering sections excepted). Context assembly
  interleaves store and flat files strictly by priority; steering sections are
  always loaded.

## [0.5.0] — 2026-07-06

### Added

- **`ai-memory install`** — one-command MCP client setup for 9 clients
  (claude-code, claude-desktop, vscode, cursor, windsurf, codex, antigravity,
  gemini-cli, cline), with detection, JSON/TOML merge-not-overwrite writes,
  `--dry-run`, and `--uninstall`.
- Official MCP Registry entry (`io.github.elViRafa/memory-fabric`), VS Code /
  Cursor one-click install badges, MCPB bundle for Claude Desktop.

## [0.4.1] — 2026-07-04

### Fixed

- First release with CI green on all three OSes: platform-conditional locking
  stubs (mypy), path-canonicalization test bugs (Windows 8.3 short names,
  macOS `/var` symlink), stdlib `TypedDict` rejected by pydantic on
  Python 3.11, and a real POSIX TOCTOU race in `locking.py`'s
  unlink-after-unlock pattern.

## [0.4.0] — 2026-07-04

### Added

- PyPI packaging with trusted publishing (OIDC) on tag push; CI matrix
  {ubuntu, windows, macos} × {3.11–3.14}; `storage/_core.py` god module split
  into 12 focused modules.

[Unreleased]: https://github.com/elViRafa/agentic-memory/compare/v0.8.1...HEAD
[0.8.1]: https://github.com/elViRafa/agentic-memory/compare/v0.7.3...v0.8.1
[0.7.3]: https://github.com/elViRafa/agentic-memory/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/elViRafa/agentic-memory/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/elViRafa/agentic-memory/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/elViRafa/agentic-memory/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/elViRafa/agentic-memory/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/elViRafa/agentic-memory/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/elViRafa/agentic-memory/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/elViRafa/agentic-memory/releases/tag/v0.4.0
