# Roadmap — Capture Filter → Episodic Roll-up → Client Hooks → Proof

> Execution roadmap for closing ROADMAP.md Phase 3 (§5.2 client-hook enforcement) without
> inflating `episodic/` with noise. Ordering principle: **filter before enforcement**,
> because enforcement amplifies volume — once hooks guarantee a record per commit and a
> journal per session, every noise commit becomes permanent noise. Cut the noise first.

Status: All 4 stages done — 3 hook clients (claude-code + gemini-cli + codex), capture-rate proof measured (2026-07-16) · Created: 2026-07-16 · Total estimate: ~5–8 days of focused work

**Global exit criterion:** a 100% non-cooperative agent still produces a clean episodic
record per *relevant* commit plus a session journal per session, without inflating
`episodic/` with merge/bot/lockfile noise — and `ai-memory status` proves it locally.
**Met and measured** — see Stage 3's capture-rate benchmark (0% → 100% session journaling,
100% commit capture throughout).

---

## Stage 0 — Capture filter (~1 day) — ✅ done 2026-07-16

**File:** `src/memory_fabric/storage/capture.py`

> Shipped as planned, with two implementation notes: the elision list was hoisted
> into `storage/_shared.py` (finalize re-imports it, so its existing test imports
> still hold), and merge detection uses parent count (`%P`) in addition to the
> subject prefixes — a squash-merge is caught by subject, a custom-message true
> merge by parent count. Skips are counted in a `private/capture_skipped_count`
> marker surfaced as `commits_skipped` in `capture_stats` / `ai-memory status`.

The passive capture path (`capture_commit`) currently records *every* commit. Add
`_should_capture(subject, author, files)` called at the top of `capture_commit`, skipping:

- **Merge commits** — subject starts with `Merge branch` / `Merge pull request`.
- **Bot authors** — author name ends with `[bot]` (dependabot, renovate, github-actions).
- **Skippable conventional-commit prefixes** — `chore:`, `style:`, `ci:`, `build(deps)`.
- **Noise-only commits** — every changed file matches the diff-elision rules. **Reuse,
  don't duplicate:** the list already exists in `storage/finalize.py`
  (`_DIFF_SKIP_BASENAMES` / `_DIFF_SKIP_SUFFIXES` / `_DIFF_SKIP_DIRS` +
  `_should_skip_diff_path`) — import it or hoist it into `storage/_shared.py` so the two
  call sites cannot drift.

Design rules (all consistent with existing patterns in this repo):

1. **A skipped commit is not silence** (per the Q6 audible-failure standard): return
   `captured: False` with a `skipped_reason` entry in `warnings`, and count skips in
   `capture_stats` so `ai-memory status` shows filter activity.
2. **Opt-out, not imposition:** `--no-filter` flag on `ai-memory capture` preserves
   completeness-by-default as a choice. Filter on by default.
3. **Idempotency unchanged** — the per-commit-hash dedup check stays exactly as is.

**Tests** (`tests/test_capture.py`): one case per rule (merge, bot, prefix, lockfile-only),
one `--no-filter` case, one asserting idempotency still holds, one asserting the skip is
audible in the result dict and in `capture_stats`.

**Exit:** a `chore: bump deps` commit by `dependabot[bot]` touching only `uv.lock`
produces no episodic entry, a visible `skipped_reason`, and a stats counter increment.

---

## Stage 1 — Episodic roll-up in Dreaming (~1–2 days) — ✅ done 2026-07-16

**Files:** `src/memory_fabric/storage/consolidation.py`, `storage/dream.py`

> Shipped as planned. `_roll_up_episodic_commits(candidate_root, cutoff_days=14, now=None)`
> lives in `consolidation.py` next to the other candidate-store mechanics; `dream()` and
> `prepare_dream_payload()` both call it right after `_create_candidate_store`, gated on
> `mode == "deep"` — before `regenerate_maps`, so folded content is reflected in the same
> run's maps/index/consolidated_memory.md. Weekly files are named
> `episodic/commits/week-<iso-year>-w<ww>.md` (ISO calendar week) and daily files are
> deleted only after their content is successfully appended, so a parse failure leaves the
> daily file in place for a future retry instead of losing it. A snapshot of the whole
> store already precedes candidate creation (existing infra), so no separate snapshot step
> was needed. Verified end-to-end via the real CLI: `ai-memory capture` → `ai-memory dream
> --mode deep --apply` correctly rolled a dated daily file into a weekly summary with
> `review_status: consolidated` and removed the daily file; a `--mode light` dream in
> between left it untouched, confirming the roll-up is deep-only.

No filter catches everything; residual accumulation in `episodic/commits/` needs a real
destination — today `review_status: pending` is intention with no consumer.

- In **deep dream** mode, consolidate `episodic/commits/` files older than N days
  (default: 14) into weekly summary files, marked `review_status: consolidated`.
- Reuse the existing consolidation infrastructure in `consolidation.py` — this is a new
  scan/rewrite pass, not a new subsystem. Follow the established catch-narrow-and-warn
  pattern for malformed files (same as `_regenerate_index_root`).
- Roll-up must be **idempotent and lossless-by-default**: original daily files are removed
  only after the weekly summary is written; a snapshot precedes the pass (existing
  `snapshots.py` infra), consistent with the "never delete user content" invariant.

**Tests:** roll-up groups by ISO week; files younger than N days untouched; re-running is
a no-op; malformed file skipped with a warning, not a crash.

**Exit:** after a deep dream on a store with 30 days of commit captures, `episodic/commits/`
contains weekly summaries + only the recent daily files, and nothing was silently lost.

---

## Stage 2 — Client lifecycle-hooks writer (the main item, ~3–5 days) — ✅ done 2026-07-16

**Files:** `src/memory_fabric/client_hooks.py` (new), `clients.py`, `contracts.py`, `cli.py`
· Closes ROADMAP.md §5.2's open items for Claude Code.

**Scope change from the original plan, decided before writing code:** the settings.json
hook mechanism (SessionStart/Stop/PreCompact) is Claude-Code-specific by construction — no
other client shares that schema (Cursor's hooks beta, Codex's `notify`, Gemini CLI all
differ or don't exist yet). Rather than hard-wiring a single Claude Code writer into
`installer.py`, the client-agnostic and client-specific parts were split:

- **`client_hooks.py`** (new module): a generalized `HOOK_ADAPTERS` registry +
  `install_hooks(cwd, client, ...)` dispatcher, parallel to `clients.py`/`installer.py`'s
  MCP-config registry but *not* sharing its json/toml/cli engine — each client's hook event
  model is different enough that a shared format engine doesn't fit. A client with no
  registered adapter gets a plain, honest `supported: False` result naming which clients
  **are** supported today, instead of a silent no-op — same audible-not-silent standard as
  Stage 0's capture filter. Adding Cursor/Codex/Gemini CLI later (ROADMAP.md §5.2's "Client
  capability survey") means registering one more adapter, not touching this dispatcher.
- **claude-code adapter** (in the same file): the only implemented adapter today.

**Step 1 — verify before writing (risk item, done first):** checked the live Claude Code
hooks schema against current official docs (`code.claude.com/docs/en/hooks.md` and
`hooks-guide.md`) via three rounds of targeted verification, not training-data guesses:
- settings.json shape: `hooks.<Event>` is an array of `{"matcher": ..., "hooks": [{"type":
  "command", "command": ...}]}` blocks. `Stop` has no matcher concept (always fires,
  `matcher: ""`); `SessionStart` matchers are `startup`/`resume`/`clear`/`compact`;
  `PreCompact` matchers are `manual`/`auto`.
- **Real finding, not a false alarm:** exit code 2 feedback is read from **stderr only**,
  never stdout — confirmed against `hooks-guide.md`'s explicit wording ("Write a reason to
  stderr, and Claude receives it as feedback"). `ai-memory guard-journal` was printing its
  JSON result (including the block reason) to stdout only, then exiting 2 — a Stop hook
  built on it as originally shipped would have blocked silently, with the agent never
  seeing *why*. Fixed in `cli.py`: on a block, the reason is now also written to stderr
  (kept the stdout JSON too, for interactive/programmatic callers).
- Matcher-value syntax confirmed NOT to reliably support combining values in one string for
  session-source matchers (pipe-syntax is only documented for tool-name matchers elsewhere)
  — so SessionStart registers two separate block entries (`startup`, `resume`), not one
  combined matcher string, avoiding undocumented syntax.
- **Design finding that changed the PreCompact plan:** PreCompact's block/exit-2 path gives
  **no stderr feedback to Claude** (unlike Stop) — blocking compaction to force a journal
  write would strand the agent with no explanation of why it's stuck. So PreCompact does
  **not** block; it runs a non-blocking, always-`|| true` `dream --mode light --apply`
  (best-effort local consolidation checkpoint) instead of attempting journal enforcement a
  second way. SessionStart's `compact` matcher was deliberately left unused (only
  `startup`/`resume`) so a mid-session compaction doesn't reset the guard-journal window.

**Step 2 — the writer** (matches the table below, all in `.claude/settings.json`):

| Hook | Matcher(s) | Command | Purpose |
|---|---|---|---|
| SessionStart | `startup`, `resume` | `ai-memory session-start --hook-format claude-code` | marks session start + injects a short `additionalContext` reminder |
| Stop | `""` (always) | `ai-memory guard-journal` | exits 2 + stderr reason — blocks an unjournaled session end |
| PreCompact | `manual`, `auto` | `ai-memory dream --mode light --apply \|\| true` | non-blocking consolidation checkpoint before context is compacted |

Every command carries a trailing `# memory-fabric-managed` shell-comment marker (JSON has
no comment syntax, so this is the update/remove identification tag — same spirit as
`installer.py`'s TOML sentinel markers). Merge logic updates/removes only entries carrying
that marker; any hook a user added by hand to the same event+matcher is left untouched.
`--dry-run` prints a unified diff without writing; `--uninstall` removes managed entries
and drops now-empty matcher blocks/events, never touching unrelated settings.json content;
malformed existing JSON is backed up and the write aborted (mirrors `installer.py`'s
`_install_json`/`ConfigParseError` pattern exactly, reusing its `_backup_file`/
`_unified_diff` helpers directly rather than duplicating them). CLI: `ai-memory install
--client claude-code --with-hooks` (also `--dry-run`/`--uninstall`); `--client all
--with-hooks` is explicitly out of scope for now (warns plainly) since hooks are still a
single-client feature.

**Step 3 — prove it:** 10 tests in `tests/test_client_hooks.py` — fresh install produces
all three events with the right matchers, byte-stable no-op re-install, preserves unrelated
settings.json content and a user's own hand-added Stop hook, dry-run writes nothing,
uninstall removes only managed entries (and correctly drops SessionStart/PreCompact
entirely while leaving Stop with the user's surviving entry), clean no-op uninstall,
malformed-JSON backup-and-abort, unsupported-client plain reporting, and two CLI-level
tests. Plus a real end-to-end smoke test: ran the actual generated `Stop` and `PreCompact`
command strings through `sh -c` (not just calling the Python functions directly) —
confirmed the Stop command exits 2 with the reason on stderr and the PreCompact command
runs a real light dream and exits 0.

**Exit:** fresh install on a real Claude Code session → session start is marked, ending
without a journal is blocked with the guard's reason **on stderr**, journal write unblocks,
existing user hooks in settings.json are untouched. Met.

### 2.1 Extending beyond Claude Code — client capability survey (2026-07-16)

The generalized `HOOK_ADAPTERS` registry (above) exists precisely so this doesn't require
touching the dispatcher — each entry below is "register one more adapter" or "not possible
yet," never a rewrite. Researched against current official docs (primary-source-verified
where fetchable; secondary-corroborated where a doc domain 403'd the fetch — flagged per
client):

| Client | Mechanism | SessionStart-equivalent | Stop-equivalent (real block) | Compaction signal | Verdict |
|---|---|---|---|---|---|
| **Gemini CLI** | Hooks (`SessionStart`/`AfterAgent`/`PreCompress`) | ✅ works | ✅ exit 2 + stderr, same contract as ours | ⚠️ advisory-only (matches our own PreCompact) | **Implemented** — see below. Primary docs verified directly. |
| **Codex CLI** | Hooks framework (distinct from the older `notify`) | ✅ works | ✅ exit 2 + stderr, same contract as ours (confirmed from source, not docs) | ⚠️ schema *can* set `continue: false` but we don't use it — same non-blocking design as the others | **Implemented** — see below. Verified straight from Rust source, doc pages all 403'd. |
| **Cursor** | Agent Hooks (`hooks.json`) | ⚠️ documented but **open upstream bug**: `additional_context` reportedly not reaching the agent (2 forum threads) | ✅ solid | ⚠️ advisory-only | Hold — verify the injection bug is fixed first |
| **VS Code + Copilot** | Agent Hooks | ✅ works, modeled on Claude Code's schema | ✅ exit 2 + stderr (same channel we already learned about the hard way) | ❓ blocking semantics unconfirmed | Hold — feature is explicitly labeled Preview |
| **Windsurf** | Cascade Hooks | ❌ no session-lifecycle hook exists at all — only per-action pre/post hooks | ❌ none | ❌ none | Not viable — missing mechanism entirely |
| **Cline** | Hooks (`TaskStart`/`TaskComplete`) | ✅ works | ⚠️ `cancel` aborts the task rather than requesting a correction; open bug report of getting stuck | ❌ none | Not viable yet — wrong enforcement primitive, no compaction hook |

**Implemented: gemini-cli adapter**, following straight from the highest-confidence
finding. `client_hooks.py` gained `_install_gemini_cli_hooks` writing
`.gemini/settings.json`, verified directly against `geminicli.com/docs/hooks/reference.md`
and `.../hooks/index.md` (fetched as raw GitHub markdown, not training-data recall):

- **Structurally different from Claude Code, confirmed before writing merge logic**:
  lifecycle hooks (`SessionStart`/`SessionEnd`/`Notification`/`PreCompress`) are **not**
  matcher-based on Gemini CLI — only tool hooks (`BeforeTool`/`AfterTool`) use `matcher` —
  so each event's array holds hook-definition objects directly
  (`{"type": "command", "command": ...}`), not the `{"matcher": ..., "hooks": [...]}` block
  wrapper Claude Code uses. This needed its own merge/remove functions
  (`_merge_gemini_cli_managed_hooks`/`_remove_gemini_cli_managed_hooks`), not a reuse of the
  claude-code ones — confirming the "no shared format engine" call made when this registry
  was first designed.
- **`AfterAgent` (the Stop-analog) needed zero changes to `guard-journal`**: its docs state
  exit code 2 "rejects the response and triggers an automatic retry turn using stderr as
  the feedback prompt" — the identical plain-exit-2-plus-stderr contract already
  implemented for Claude Code's Stop, reused unchanged.
- **`PreCompress` is confirmed "Advisory Only... cannot block or modify the compression
  process"** — the same constraint accepted for Claude Code's PreCompact, so it gets the
  same non-blocking `dream --mode light --apply || true` checkpoint, unchanged in design.
- One flagged-not-guessed gap: the docs don't show a complete `SessionStart` stdout
  example, so whether `hookSpecificOutput.hookEventName` is required alongside
  `additionalContext` is unverified — included anyway (harmless if the field is ignored,
  and Gemini CLI's schema is explicitly modeled on Claude Code's), and noted in the code
  comment rather than silently assumed.
- Refactored `client_hooks.py` to extract the truly shared JSON safe-write scaffolding
  (`_read_config_or_backup` / `_finalize_hook_write` — read+parse+backup-on-malformed-JSON,
  and dry-run-diff+write-if-changed) so a third adapter doesn't triple this logic; the
  merge/remove logic itself stays adapter-specific since the shapes genuinely differ.
- **Tests**: 8 new cases mirroring the claude-code suite (fresh install produces the flat
  no-matcher shape, byte-stable reinstall, preserves unrelated settings.json content and a
  user's own `AfterAgent` hook, dry-run, uninstall removes only managed entries, clean no-op
  uninstall, malformed-JSON backup-and-abort) plus a CLI-level `session-start --hook-format
  gemini-cli` test. **One CLI-level test deliberately not written**: unlike claude-code
  (`fmt="cli"`, mockable subprocess), gemini-cli's MCP-config install is `fmt="json"` at
  **global** scope (`~/.gemini/...`) with no `home`/`env` override exposed through `main()`
  — a `main()`-driven test would write to the real machine's actual global config, the same
  class of hazard the claude-code test avoids by mocking `subprocess.run`. Covered instead
  by direct `install_hooks()` tests (project-scoped, safe) plus the project-scoped
  `session-start` CLI test.
- **Real end-to-end smoke test**: ran the actual generated `AfterAgent` and `PreCompress`
  command strings through `sh -c` — confirmed exit 2 + stderr reason and a real light dream
  exiting 0, same verification standard as the claude-code adapter.

**Implemented: codex adapter.** Every official doc URL for Codex hooks (`developers.
openai.com/codex/hooks`, `.../config-reference`) 403'd on every fetch attempt, same as the
first survey found — so this went one level deeper than doc-page verification: straight to
Codex's own Rust source (`openai/codex` on GitHub, fetched as raw files), which is more
authoritative than any doc page could be. Read `codex-rs/hooks/src/lib.rs` (event names,
which events have meaningful matchers), `codex-rs/config/src/hook_config.rs`
(`HooksFile`/`HookEventsToml`/`MatcherGroup`/`HookHandlerConfig` — the literal wire schema),
`codex-rs/hooks/src/events/common.rs` (matcher-matching semantics), and the
`session_start.rs`/`stop.rs`/`compact.rs` test suites (exact I/O behavior, quoted from
actual test names and assertions, not paraphrased).

- **Turned out structurally identical to Claude Code, confirmed from struct definitions**:
  `hooks.json`'s shape is the same `{"hooks": {"Event": [{"matcher": ..., "hooks": [{"type":
  "command", "command": ...}]}]}}` block wrapper — so `_install_codex_hooks` reuses the
  claude-code adapter's merge/remove logic directly. Refactored those two functions out of
  the `claude-code` section into shared `_merge_matcher_block_hooks`/
  `_remove_matcher_block_hooks` (parametrized on the managed-events tuple) rather than
  duplicating them a second time — the "share only where the shape truly matches" principle
  paying off concretely, not just in theory.
- **One config-shape refinement matchers make possible**: `events/common.rs::matches_matcher`
  showed matcher strings made only of alphanumeric/underscore/`|` chars are treated as an
  **exact-set match** (split on `|`, equality per candidate) — not a Claude-Code-style single
  literal each. So `"startup|resume"` and `"manual|auto"` each cover both sources in **one**
  block, where Claude Code needs two. `Stop` is confirmed absent from
  `HOOK_EVENT_NAMES_WITH_MATCHERS` (its matcher is accepted but ignored at dispatch), so it
  keeps the same `""` match-all convention as Claude Code's Stop block.
- **`Stop`'s exit-2 contract confirmed byte-for-byte identical** to Claude Code's, straight
  from a test literally named `exit_code_two_uses_stderr_feedback_only` in `events/stop.rs`:
  non-empty stderr on exit 2 blocks with that text as the reason. `guard-journal` needed zero
  changes. A real trap surfaced by another test, `exit_code_two_without_stderr_does_not_
  block`: exit 2 with *empty* stderr is silently ignored, not a concern here since
  `guard_journal()`'s `reason` string is never empty when it actually blocks.
- **`PreCompact`'s output wire type (`PreCompactCommandOutputWire`) carries only the
  universal `continue`/`stopReason`/`suppressOutput`/`systemMessage` fields** — no
  context-injection field, and while `continue: false` is schema-legal there, our adapter
  never sets it, keeping the same non-blocking `dream --mode light --apply || true`
  checkpoint design used for the other two clients.
- **New finding this survey didn't anticipate, source-confirmed and NOT silently
  worked around**: Codex gates hooks behind a hash-based trust check
  (`hook_trust_status` in `discovery.rs`) — a newly added or modified hook is discovered
  but **not added to the active handler set** (and therefore doesn't run) until trusted.
  The exact end-user trust command wasn't found in the portion of the CLI source
  checked, so rather than assert a guessed command name, `_install_codex_hooks` appends
  an explicit warning on every install that changes the file: check Codex CLI's
  hook-trust command/UI, or the hooks won't actually execute. This is the same
  "audible, not silent" standard the whole roadmap has followed since Stage 0's capture
  filter, applied to an unresolved-but-real gap instead of a code path.
- **Config-path confidence note**: `.codex/hooks.json` for the project scope is inferred
  from the `ConfigLayerSource::Project { dot_codex_folder }` variant (the project layer's
  hook folder defaults to that directory) and matches this repo's own existing
  project-scoped MCP path for codex (`.codex/config.toml`) — high confidence, but the one
  piece of this adapter not read from a literal "hooks.json lives here" line in the source.
- **Tests**: 8 new cases mirroring the claude-code/gemini-cli suites (fresh install
  produces the single-block-per-event shape confirming the pipe-matcher simplification,
  byte-stable reinstall with the trust warning correctly absent on a no-op re-run,
  preserves unrelated `description`/Stop-hook content, dry-run, uninstall removes only
  managed entries, clean no-op uninstall, malformed-JSON backup-and-abort) plus a
  project-scoped `session-start --hook-format codex` CLI test. Same CLI-test carve-out as
  gemini-cli: codex's MCP-config install also defaults to a real **global**
  `~/.codex/config.toml` with no `home`/`env` override through `main()`, so no combined
  `install --with-hooks` test was written for it either.
- **Real end-to-end smoke test**: ran the actual generated `Stop` and `PreCompact` command
  strings through `sh -c` — confirmed exit 2 + stderr reason and a real light dream exiting
  0, plus the trust warning appearing in the install result.

**Not implemented this round**: Cursor (open upstream bug on context injection), VS Code
Copilot Hooks (labeled Preview), Windsurf and Cline (missing mechanism/wrong primitive) —
held per the table above pending upstream fixes or better verification.

---

## Stage 3 — Close the proof loop (post-ship) — ✅ done 2026-07-16

- **Capture-rate metric:** `scripts/capture_rate_benchmark.py` scripts a fully
  non-cooperative simulated agent (never voluntarily calls
  `write_session_journal_tool`) through 20 sessions per mode:

  | Mode | Sessions journaled | Commit capture rate |
  |---|---|---|
  | Instructions-only (no hooks) | 0 / 20 (0%) | 20 / 20 (100%) |
  | Hooks enabled (`guard-journal` enforced) | 20 / 20 (100%) | 20 / 20 (100%) |

  Commit capture is unconditional in both modes (it runs off the git post-commit hook —
  Stage 0/1 — not the client-side session hooks from Stage 2); session journaling goes
  from 0% to 100% only once the Stop hook is wired in. This is a **mechanism proof** — it
  demonstrates the enforcement primitive (`guard_journal`, checked and re-checked exactly
  the way a real Stop hook would) cannot be silently bypassed by a caller that never
  intends to comply — not a statistical study of real-world agent behavior, which stays
  Phase 5's separate, larger benchmark work (ROADMAP.md §8). Regression-guarded in
  `tests/test_capture_rate_benchmark.py` (3 tests) so the number can't silently drift.
  Feeds directly into ROADMAP.md Phase 5 (§8) and is now the measured number in the §10
  capture-rate metric row and the §5.3 exit criteria.
- **Demo/README:** done — README's Capture Reliability section now opens with "commit →
  the project brain updates itself; end a session without a journal, and the Stop hook
  blocks it," followed by the benchmark table above and the reproduction command.

**Exit:** the capture-rate number is measured, reproducible, and regression-guarded, not
just an aspirational bullet — met.

---

## Sequencing and dependencies

| Stage | Depends on | Why this order |
|---|---|---|
| 0 — filter | nothing | enforcement amplifies volume; filter must exist first |
| 1 — roll-up | 0 (reduced inflow) | catches what no filter can; gives `pending` a destination |
| 2 — hooks writer | 0 shipped | safe to guarantee volume once volume is clean |
| 3 — proof | 2 shipped | you can only measure a mechanism that exists |

Stages 0 and 1 are independent of each other in code and could land in either order,
but 0 first shrinks the backlog 1 has to consolidate.
