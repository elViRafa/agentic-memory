# Roadmap — Capture Filter → Episodic Roll-up → Client Hooks → Proof

> Execution roadmap for closing ROADMAP.md Phase 3 (§5.2 client-hook enforcement) without
> inflating `episodic/` with noise. Ordering principle: **filter before enforcement**,
> because enforcement amplifies volume — once hooks guarantee a record per commit and a
> journal per session, every noise commit becomes permanent noise. Cut the noise first.

Status: planned · Created: 2026-07-16 · Total estimate: ~5–8 days of focused work

**Global exit criterion:** a 100% non-cooperative agent still produces a clean episodic
record per *relevant* commit plus a session journal per session, without inflating
`episodic/` with merge/bot/lockfile noise — and `ai-memory status` proves it locally.

---

## Stage 0 — Capture filter (~1 day)

**File:** `src/memory_fabric/storage/capture.py`

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

## Stage 1 — Episodic roll-up in Dreaming (~1–2 days)

**Files:** `src/memory_fabric/storage/consolidation.py`, `storage/dream.py`

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

## Stage 2 — Claude Code hooks writer (the main item, ~3–5 days)

**Files:** `src/memory_fabric/installer.py`, `cli.py` · Closes ROADMAP.md §5.2's open items.

**Step 1 — verify before writing (risk item, do first):** check the live Claude Code hooks
schema (SessionStart / Stop / PreCompact event names, settings.json shape, exit-code 2
blocking semantics) against current official docs. ROADMAP.md already mandates this
("deferred rather than guessed") — it is the one part with real staleness risk, and the
same class of drift Milestone C caught for VS Code/Antigravity paths.

**Step 2 — the writer:** `ai-memory install --client claude-code --with-hooks` writes:

| Hook | Command | Purpose |
|---|---|---|
| SessionStart | `ai-memory session-start` + context injection | mark session, load memory |
| Stop | `ai-memory guard-journal` | already exits 2 with a reason — blocks unjournaled session end |
| PreCompact | journal checkpoint | knowledge survives context compression |

Follow `installer.py`'s existing safe-write pattern exactly: backup before write,
non-destructive merge (never clobber existing hooks), `ConfigParseError` on unparseable
config, `--dry-run` prints the diff, `--uninstall` removes cleanly.

**Step 3 — prove it:** e2e test in the mold of `tests/test_hooks_e2e.py` (real settings
file, real CLI invocations), plus a **real-session smoke test before release** — the
field-test lesson stands: both critical bugs lived in layers the suite doesn't reach.

**Exit:** fresh install on a real Claude Code session → session start is marked, ending
without a journal is blocked with the guard's reason, journal write unblocks, existing
user hooks in settings.json are untouched.

---

## Stage 3 — Close the proof loop (post-ship)

- **Capture-rate metric:** scripted sessions, instructions-only vs hooks-enabled — % of
  sessions whose knowledge survives into the next session. Feeds directly into ROADMAP.md
  Phase 5 (§8) and becomes the launch number for the §10 capture-rate metric row.
- **Demo/README:** "commit → the project brain updates itself; session without a journal
  → blocked." The two-line pitch that makes enforcement legible.

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
