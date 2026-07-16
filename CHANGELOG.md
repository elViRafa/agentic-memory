# Changelog

All notable changes to **memory-fabric** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(0.x: minor versions may contain breaking changes, called out explicitly below).

## [Unreleased]

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
