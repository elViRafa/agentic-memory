# Memory Fabric — Roadmap to Best-in-Class

> Goal: make Memory Fabric the best memory layer for AI coding assistants — installable in
> one command in VS Code, Claude (Code + Desktop), Codex, Antigravity, Cursor, Windsurf,
> Gemini CLI, Cline, and anything MCP-compatible.

Last updated: 2026-07-14 · Current version: 0.8.1 ([live on PyPI](https://pypi.org/project/memory-fabric/)) · Tests: 288 passing (+73 subtests, +1 skipped on Windows by design) · Coverage: 85.9% (gate: 82%) · Lint: ruff (E4,E7,E9,F,I,B,UP,SIM,RUF,BLE001,S110,S112) + mypy clean · No `src/` file >25 KB except 4 tracked borderline files · Phase 0 exit criteria met · Phase 2.2 migration tooling shipped

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
      `memory_fabric.storage`. `eval.py` (48 KB, grown from ~41 KB) was the one file
      still over the bar — split into `eval/` (5 files, largest 23.7 KB) 2026-07-13,
      see Q5. Four still-borderline files tracked there, deferred by design.
- [x] **CI matrix.** GitHub Actions: {windows, macos, ubuntu} × {3.11, 3.12, 3.13, 3.14},
      `pytest`, `ruff check`, `ruff format --check`, `mypy` (the package ships `py.typed`
      — enforce it). Badge in README. Confirmed green on GitHub 2026-07-05.
- [x] **Coverage gate** — Done 2026-07-13 (Q3 below). Baseline measured 2026-07-12:
      **83%** overall (win/py3.14); `--cov-fail-under=82` is on in CI, passing at 85.5%
      after this round's new tests. Lowest modules at baseline, in priority order
      (weakest layer = highest product risk): `storage/search.py` 56% (BM25 retrieval —
      the core read path; still open, next ratchet target), `cli.py` 61%, `server.py`
      67%→96% (the MCP boundary, where P-13 hid — see Q1), `storage/patch.py` 68%
      (where P-06 hid), `storage/journal.py` 69%, `locking.py` 74%, `storage/lifecycle.py`
      77%.
- [x] **Docs truth pass.** Done 2026-07-13 (Q2 below) — the durable fix, since manual
      passes don't hold: the 0.1.0/0.3.0 drift was fixed, then on 2026-07-12 README and
      this file still claimed 0.7.1 one release into 0.7.2. `tests/test_version_truth.py`
      now asserts README/ROADMAP/server.json all agree with `memory_fabric.version`, in
      every CI job, so this specific rot class can't recur silently again.
- [x] **Concurrency & corruption tests.** Done 2026-07-13 (Q4 below,
      `test_cross_process.py`). `test_robustness.py` already had the thread-level
      half (concurrent writers, lock release after exception, lock-sidecar crash
      leak, malformed-file skip, scale smoke tests); Q4 added the process-level
      half this item was really asking for — and found a real Windows-only race in
      `locking.py` that the thread-level tests never could have caught, because it
      only reproduces under separate-process contention. These are the bugs that
      kill trust, and this is exactly the class of bug that was still hiding.

Exit criteria: green CI badge on all three OSes, no file >25 KB in `src/`, coverage gate on.
**Met as of 2026-07-13**, with one explicit, tracked exception: 4 files (`finalize.py`,
`server.py`, `lifecycle.py`, `cli.py`) remain over 25 KB by design — deferred to be
split opportunistically when next touched, not silently ignored (see Q5).

### 2.1 Quality analysis 2026-07-12 — plan for the next hardening round

State of the repo at v0.7.2 (`5db094b`): 227 tests + 67 subtests green locally; CI
matrix (3 OS × py3.11–3.14) + ruff + `ruff format` + mypy enforced; zero TODO/FIXME
markers in `src/`; all 15 field-test findings fixed and confirmed in a directed retest
(15/15, including live-Ollama revalidation of P-09/P-10); PyPI, MCP registry, tags all
current at 0.7.2. The field test's deepest lesson drives this plan: **both critical
bugs (P-13, P-04) lived in layers the test suite doesn't reach** — the MCP response
boundary and the installed-hook runtime environment — not in the storage core, which
is well covered. Harden those seams before growing more surface.

Priority order: Q1–Q3 before v0.8 migration work starts; Q4–Q10 interleave with it.

- [x] **Q1 — MCP-boundary contract tests.** Done 2026-07-13
      (`tests/test_mcp_contract.py`, `tests/test_hooks_e2e.py`). Added an in-process
      `ClientSession` fixture (`mcp.shared.memory.create_connected_server_and_client_session`)
      and, for every one of the 17 tools, a happy-path and an error-path call asserting
      the response validates against its contract and `isError` is truthful; the
      split-tool dream protocol (`prepare_dream_payload_tool` → `apply_dream_results_tool`)
      is covered by a full round trip. `server.py` coverage: 67% → **96%**.
      Also added one true end-to-end hook test: real `git init` + `initialize_memory_fabric(...,
      install_hooks=True)` + real `git commit` → asserts the episodic capture record
      actually lands on disk and the commit output carries none of P-04's failure
      strings — passed first try, confirming that fix holds under a real commit.
      **This is exactly the layer that found a live bug the 2026-07-08 retest's
      direct-TypeAdapter check had certified fixed**: `dream_tool`/`apply_dream_results_tool`
      still returned `isError: True` on `apply=True` with the default `with_eval=False`.
      Root cause (in the `mcp` SDK, not this repo): FastMCP converts a tool's
      *top-level* return TypedDict into a hand-built `BaseModel`
      (`_create_model_from_typeddict`) that gives every `NotRequired` field
      `default=None` while keeping its original non-nullable annotation, then serializes
      with `model_dump()` and no `exclude_unset` — the SDK's own code comment even
      says dumping needs `exclude_unset=True` for correct TypedDict semantics, but the
      call site doesn't pass it. An omitted `evaluation` therefore hit the wire as an
      explicit `null`, which its non-nullable `object` schema rejected. Nested
      TypedDicts (e.g. `DreamConsolidation.warnings`) are unaffected — pydantic's
      native TypedDict validation handles those correctly; only each tool's outermost
      return type goes through the buggy hand-built conversion. Fixed in this repo by
      widening `DreamResult.evaluation` and `InitResult.resource_uris` (same shape,
      currently dormant since `server.py` always populates it) to `NotRequired[X | None]`
      — the same pattern already used for `snapshot: str | None` — so the schema accepts
      the `null` the SDK always sends for an unset optional field. `tests/test_contracts.py`
      is still valuable (guards the PEP 563 regression) but now says explicitly that its
      `TypeAdapter` check is necessary, not sufficient, and points here.
- [x] **Q2 — Version-truth CI check.** Done 2026-07-13 (`tests/test_version_truth.py`).
      README and this file claimed 0.7.1 while PyPI, the registry, `server.json`, and
      the git tag were at 0.7.2 — the exact rot class this product exists to prevent,
      recurred days after a manual docs-sync commit (`9d21bb2`); fixed both in the same
      pass. A normal pytest test now asserts `memory_fabric.version.__version__`
      matches the README status line, this file's header, and both `server.json`
      version fields — it runs in every CI job (full OS/Python matrix), not just lint,
      since it's just another test in `tests/`. `mcpb/manifest.json`'s in-repo 0.4.1 is
      left alone; the test instead asserts release.yml's "Sync manifest version to
      release tag" rewrite step still exists, so a future edit can't silently drop it.
- [x] **Q3 — Coverage gate on.** Done 2026-07-13. `pytest-cov` added to the `test`
      extra; `[tool.coverage.report] fail_under = 82` in `pyproject.toml` (statement
      coverage, matching the measured baseline — branch coverage was tried first but
      reports a different, stricter number, 80.57% vs 83%, and silently changing the
      baseline definition mid-gate would be its own small version of Q2's problem);
      CI's test step now runs `--cov=memory_fabric --cov-report=term-missing`. Passes
      at 85.12% after Q1/Q6's new tests. Next ratchet: 83%.
- [x] **Q4 — Cross-process corruption suite.** Done 2026-07-13
      (`tests/test_cross_process.py`, `tests/_cross_process_helpers.py`). All six
      scenarios from this item's original scope, each using real `subprocess.Popen`
      processes (not threads) where the scenario calls for concurrency:
      - Two `ai-memory` writer processes appending to one store file: no lost writes,
        file stays parseable.
      - A writer killed mid-write (`proc.kill()` after it signals it holds the lock):
        a fresh writer must not hang on a lock nobody holds anymore.
      - 10 MB store file: write/read/list/append all still work.
      - Non-UTF-8 bytes in an *existing* store file: see the crash found below.
      - Symlinked `.ai-memory`: skipped on Windows (needs admin/Developer Mode to
        create a symlink at all — not what this test is about), runs for real on
        Linux/macOS in CI.
      - Read-only target: **not** a read-only *directory* — verified empirically
        first that `chmod`/`os.chmod` on a directory doesn't block file creation on
        NTFS at all (Windows ignores POSIX directory permission bits for this), so
        that scenario would have silently tested nothing on Windows. Used a
        read-only *file* instead — enforced identically on both platforms — which
        is the more realistic failure mode anyway (a memory file locked by an AV
        scanner, backup tool, or an accidental chmod) and the thing that's actually
        exercised: a write hitting a permission error must fail cleanly, not crash
        or corrupt the original content.

      **This basket surfaced two real, independent bugs — this was the highest-yield
      item in the whole round, exactly the "process-level, not thread-level" premise
      it was written on.**

      1. **A genuine race in `locking.py` itself**, found by the first test
         (concurrent writers) failing intermittently (~20-33% of runs) with
         `PermissionError` raised directly out of `lock_path.open("a+b")` — a
         failure mode `_acquire_lock`'s existing retry loop didn't cover, because
         that loop only retries *after* a successful open (on inode-identity
         mismatch), not on the open itself failing. Root cause, Windows-only:
         `locked_file()`'s cleanup unlinks the `.lock` sidecar after unlocking, and
         Windows leaves a brief pending-delete window where a *different process*
         concurrently opening that same path gets `PermissionError` instead of
         succeeding or a clean not-found. Never reproducible with same-process
         threads (confirmed — the existing `test_robustness.py::ConcurrentWriteTests`
         thread-based tests have run clean throughout this entire session); only
         showed up under genuine separate-process contention, which is exactly this
         item's premise and exactly why it's worth having process-level tests at
         all. Fixed with a bounded retry (200 attempts × 5 ms, Windows-only — a real
         permissions problem, e.g. an actually read-only file, still fails every
         attempt and correctly surfaces) around the `open()` call in `_acquire_lock`.
         Stress-verified: 20 consecutive clean runs after the fix (0 failures),
         versus roughly 1-in-3 to 1-in-5 before it. The concurrent-writer test *is*
         the regression test — no separate unit test added, since reproducing this
         race needs the real subprocess setup that test already builds.
      2. **`write_memory_store` / `write_local_memory` / `read_section` all crashed
         with an uncaught `UnicodeDecodeError`** if the *existing* target file had
         invalid UTF-8 bytes (e.g. corrupted by some other tool) — including
         `mode="replace"`, whose entire point is to overwrite what's there, and
         which therefore should never have been blocked by unreadable prior
         content. Fixed in `store.py` and `sections.py`: `append` mode now refuses
         with a clean, actionable `ValueError` ("existing file is unreadable... use
         mode='replace'") instead of crashing; `replace` mode now recovers by
         treating the corrupted file as fresh and reports a `warnings` entry
         ("existing X could not be read and was fully replaced"); `read_section`
         raises a clean `ValueError` instead of a raw `UnicodeDecodeError`. Same
         narrow-and-warn pattern as Q6's `consolidation.py` fix, applied to the
         write path this time instead of the dream/index-regeneration path.
         Regression tests: `NonUtf8ExistingFileTests` in the new suite.

      Closes the Phase 0 checklist's concurrency item — it explicitly called for
      *process*-level tests, and thread-level ones (already in `test_robustness.py`)
      turned out not to be sufficient, concretely, not just in principle.
- [x] **Q5 — Module-size bar, round 2.** Done 2026-07-13 for `eval.py`, the one
      required part of this item (48 KB, the single largest module in `src/`).
      Split into `src/memory_fabric/eval/`: `_shared.py` (constants + scoring
      primitives + section-loading helpers, 9.4 KB), `reports.py` (markdown
      rendering + on-disk persistence, 5.0 KB — turned out fully independent of
      `_shared`, since it only ever reads an already-built `EvalResult`/
      `DreamEvalResult`), `memory_quality.py` (`evaluate_memory_fabric` +
      its 4 category scorers, 23.7 KB — the largest piece, right at the bar),
      `dream_quality.py` (`evaluate_dream_quality` + its 4 category scorers +
      before/after diff helpers, 11.7 KB — depends one-directionally on
      `memory_quality.py`, e.g. `evaluate_dream_quality` calls
      `evaluate_memory_quality`/`evaluate_memory_fabric` to score the "after"
      state; not circular), `__init__.py` re-exporting the 4 names anything
      outside `eval/` actually imports (`evaluate_memory_fabric`,
      `evaluate_memory_quality`, `evaluate_dream_quality`, `latest_snapshot` —
      confirmed by grepping every `from memory_fabric.eval import` in the repo
      before splitting, so internal helpers were free to move without
      preserving a compatibility surface for them). No logic changed — this
      was a pure mechanical split; full suite (249 tests) and coverage
      (85.4%) confirm behavior is identical, ruff/mypy clean.
      The four originally-borderline files are **unchanged in scope**, per the
      original "split opportunistically when next touched" plan — this pass
      touched `finalize.py` and `lifecycle.py` for Q6 fixes (small, targeted
      edits, not restructuring) and left `server.py`/`cli.py` alone entirely.
      Current sizes for the next pass: `finalize.py` 28.4 KB, `server.py`
      27.4 KB, `lifecycle.py` 26.3 KB, `cli.py` 25.4 KB — all four still open.
- [x] **Q6 — Silent-failure audit.** Done 2026-07-13. Went through all 52 broad
      `except Exception` sites in `src/`; 21 remain, each either already audible
      (`as exc:` feeding a `warnings`/`errors` list, a re-raise, or a printed CLI
      error) or a deliberately broad catch-all with its own justifying comment (e.g.
      `finalize.py`'s "an applied dream must never fail over cleanup", now also made
      audible via a warning without loosening the catch). The other 31 were narrowed
      to the exceptions the operation can actually raise (`OSError`,
      `UnicodeDecodeError`, `FrontmatterError`, `subprocess.SubprocessError` —
      matching the precedent in `capture.py`'s `_git()` and `commit 7ee983a`) and,
      wherever a `warnings`/`errors` list was already in scope but unused, wired up to
      it (`consolidation.py`, `maps.py`, `finalize.py`'s stale-check and
      secret-redaction loops — the latter is security-relevant: a file that fails the
      redaction pass used to keep its secrets with zero signal).
      **Found a live crash in the process, not just silence**: `consolidation.py`'s
      `_regenerate_index_root` flat-section loop had *no* exception handling at all —
      the one scan loop 7ee983a's malformed-frontmatter fix didn't cover. Any malformed
      `architecture.md`/`decisions.md`/etc. still crashed `ai-memory dream` in *both*
      light and deep mode (light is the default and what the post-commit hook runs
      after every commit), the same failure mode v0.7.2 shipped believing was fully
      closed. Fixed with the same catch-narrow-and-warn pattern already used
      elsewhere in that file; regression test added
      (`test_dream_skips_malformed_flat_section_instead_of_crashing`).
      Also deduplicated `dream.py`'s 9 sites, 8 of which were 2 patterns copy-pasted
      3× each (`_read_optional_text`, `_read_previous_consolidation_metadata`) — down
      to 166 statements from 201, 90% covered, one `except Exception` left (the
      already-correct LLM-fallback path). New guardrail for future sites: **Q7**.
- [x] **Q7 — Lint/type ratchet.** Done 2026-07-13. `select` in `pyproject.toml`
      widened from `E4,E7,E9,F` to add `I` (import order), `B` (bugbear), `UP`
      (pyupgrade), `SIM` (flake8-simplify), `RUF` (ruff-specific), `BLE001`
      (blind-except — the actual Q6 guardrail), and `S110`/`S112` cherry-picked
      from flake8-bandit (try/except/continue-pass) rather than the full `S`
      family, which is unreviewed and out of scope for this pass. 107 findings;
      59 autofixed safely (import sorting, `datetime.UTC`, etc.), the remaining
      48 by hand: every still-broad `except Exception` from Q6 got a one-line
      `# noqa: BLE001 - <reason>` (16 sites; 3 more were narrowed to a specific
      subprocess exception type instead of suppressed, since that's strictly
      better); 4 `raise ... from exc` added in `llm.py` so a provider parsing
      failure keeps its original traceback; the rest (unused unpacked
      variables, collection-literal-concatenation, if/else-to-ternary,
      `try/except/pass`-to-`contextlib.suppress`, `enumerate()`, one
      `ClassVar` annotation) were mechanical cleanups with no behavior change.
      **Process note for next time**: running `ruff check --select <subset> --fix`
      with a subset that excludes `F` will strip a pre-existing `# noqa: F401`
      as "unused" (RUF100 only looks at the active `--select`, not the full
      config) — this happened once here (`lifecycle.py`'s deliberate
      `from mcp.server.fastmcp import FastMCP  # noqa: F401` availability
      probe) and was caught by diffing against HEAD before finishing, not by
      the tool itself. Always re-run the full, unscoped `ruff check .` as the
      final step, not just the subset being actively fixed.
      mypy: `type: ignore` count held at 7 (unchanged); moving toward `strict`
      flag-by-flag is still open — deferred, lower value than the above given
      `disallow_untyped_defs` is already on and mypy is already clean.
      Verified: `ruff check .`, `ruff format --check .`, and `mypy
      src/memory_fabric` all clean; full suite still 249 passed, coverage
      85.32%.
- [x] **Q8 — Repo & dogfood hygiene.** Stray patch file deleted, `scratch/`
      gitignored, and the broken `~~mory-fabric` venv dist-info cleaned on 2026-07-13
      (first round). The last sub-item — committing the untracked
      `.ai-memory/memory-store/features/` entries — lands with the v0.8 migration
      commit, which touches the same dogfood store (the 2026-07-13 migration run
      rewrote its maps and added 15 granular entries; committing `features/` separately
      mid-review would just split one logical change in two).
- [x] **Q9 — Provider preflight UX** (field-test finding AV-2). Done 2026-07-13.
      Added `_check_llm_provider` to `doctor()` in `lifecycle.py`: for
      `gemini`/`openai`/`anthropic`, a pure env-var check that the matching
      API key is set (mirroring `_call_openai`'s own custom-base-url-needs-no-key
      logic, not a naive duplicate of it); for `ollama`, a real `GET /api/tags`
      against `OLLAMA_HOST` that reports either "not reachable" or, if reachable,
      whether `OLLAMA_MODEL` is actually installed — the exact AV-2 ask, now
      surfaced proactively in `doctor` instead of only reactively as a raw HTTP
      error mid-Dream. The network call follows the same opt-out-via-`--offline`
      convention as the existing PyPI drift check, so the `doctor()` parameter
      previously named `check_pypi` (now genuinely used by two checks) was
      renamed `check_network`; its one call site in `cli.py` updated to match.
      8 new unit tests (mocked `urlopen`, matching the existing PyPI-check test's
      pattern) plus a real end-to-end smoke test against this machine's actual
      local Ollama instance: `doctor --offline` with a bogus `OLLAMA_MODEL`
      stays silent on the provider; `doctor` (network on by default) correctly
      reported: "Ollama is reachable at http://localhost:11434 but model
      totally-bogus-model is not installed. Run `ollama pull totally-bogus-model`
      or `ollama list`...".
- [x] **Q10 — Promote the perf smoke tests to a budget.** Done 2026-07-13
      (`test_read_combined_context_p95_latency_budget` in `test_robustness.py`,
      reusing the class's existing 1000-file `_seed_large_store` fixture — already
      above the 500-file ask). **Honest finding, not the one hoped for**: real p95
      measured on this machine is **~390 ms at 500 files, ~740 ms at 1000** — 2-5x
      over the Phase 4 aspirational 150 ms target, not close to it. Root cause:
      `read_combined_context` reads and frontmatter-parses every store file up
      front, then ranks/trims to the token budget — confirmed by timing being
      statistically identical with a tiny default budget, a 200k-token budget,
      and with/without a BM25 query, i.e. the cost is all in the unconditional
      full-store read, not the ranking step. That's real, currently-unscoped
      Phase 4 work (a lazy/indexed read path that stops once the budget fills),
      not a test tuning problem — so the new test does not assert the unmet 150 ms
      figure. It asserts a regression guard instead (p95 < 3000 ms, ~4x today's
      measured value: loose enough for a slower CI runner, tight enough to catch
      an accidental O(n²)-shaped regression) and documents the real numbers in
      its docstring for whoever picks up Phase 4 retrieval work next.
      **Phase 4's own "Latency budget" bullet below is updated to reflect this** —
      it was written as an untested aspiration; it now has a measured starting
      line, and the gap itself is now the work item, not just hitting a number.

Exit criteria for this round: Q1–Q4 all merged (coverage gate red-lines a regression,
an MCP-contract or cross-process failure is a failing test, a stale version string
fails CI), `server.py` ≥90% covered, and the Phase 0 checklist above fully checked.
**Status 2026-07-13: all ten items (Q1-Q10) done — this round's exit criteria are
fully met.** Coverage gate at 82% (passing at 85.5%), MCP-contract tests and
cross-process tests are both merged and green, the version-truth check is merged,
`server.py` is at 96% (target ≥90%), and the Phase 0 checklist above is fully
checked. Net result of the round: 227→264 tests (+1 skipped on Windows by design),
coverage 83%→85.5%, 4 real bugs found and fixed (an MCP output-validation gap in
`dream_tool`/`apply_dream_results_tool`, a crash-on-malformed-flat-section in
Dreaming, a non-UTF-8-existing-file crash across both write paths, and a genuine
Windows-only cross-process race in the core file lock), `eval.py` split from the
single largest module in the repo (48 KB) into a 5-file package, 52→21 broad
`except Exception` sites (the rest narrowed or justified), lint ruleset widened
and clean, repo hygiene cleaned up. Phase 2.2 migration tooling (v0.8) followed
on 2026-07-13 — see §4.2. Next: v0.8 release (bump + tag), then v1.0 launch
prep (execution-order item 8) with Phase 2.3's flat-write removal as the one
remaining model change.

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

- [x] Create `server.json`, publish via `mcp-publisher` under the
      `io.github.elViRafa/memory-fabric` namespace (case-preserving — not lowercase) to
      registry.modelcontextprotocol.io. Done 2026-07-05 (Milestone D); republish is
      automated in the release workflow. Verified live 2026-07-12: the registry API
      returns every version through 0.7.2, pointing at the PyPI package.
- [x] This feeds the VS Code MCP store, Cursor's directory, Glama/PulseMCP/mcp.so
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
- [x] `ai-memory migrate`: split legacy hand-written sections into store entries.
      Done 2026-07-13 (`storage/migrate.py`, see `z_PLAN.md` Milestone H). One design
      sharpening over this item's original wording: the heading-based heuristic split is
      *always* the content pipeline (chunks are verbatim source, so "never delete user
      content" holds by construction); a configured LLM improves only the *names*
      (store_path/title/tags) of those chunks and degrades to heuristic names on any
      failure. Snapshot first, `--dry-run` prints the full plan, `rollback --to` restores
      the flat sections; re-runs are resumable (identical entries recognized, conflicting
      names get a `-migrated` suffix). After a section's entries land, the flat file is
      rewritten as a `generated: true` map directly — deliberately bypassing the Dream
      fold, which would re-blob the just-granularized body into pending-review.
- [x] `ai-memory init` pre-scaffolds empty store category directories. Done 2026-07-13:
      the four map categories (derived from `SECTION_TEMPLATES`, so they can't drift)
      plus `episodic`/`failures`/`rules`, each with `.gitkeep`. Empty dirs are invisible
      to map regeneration until a first entry lands, so nothing else changes.
- [x] Migration guide in `CHANGELOG.md`. Done 2026-07-13 — `CHANGELOG.md` created
      (keep-a-changelog, 0.4.0→0.7.3 backfilled from tags) with the step-by-step guide
      under `[Unreleased]`.
- [x] Run the migration on this repo's own `.ai-memory/` and record before/after eval
      scores as the reference case. Done 2026-07-13: **85/100 → 96/100, zero failing
      checks** (section_coverage 65→100, metadata_quality 73→100). Full numbers in the
      CHANGELOG migration guide. The run surfaced two pre-existing eval bugs (store files
      scored for a `section` field the canonical write path never produces — the same
      local-vs-store split doctor was already fixed for; and `consolidated_memory.md`
      scored despite being ignored by every other subsystem via a drifted hand-copied
      ignore rule) — both fixed with regression tests, which is exactly the kind of
      finding this dogfood step existed to produce. Bonus find while running the suite at
      night: `test_hooks_e2e` asserted the capture filename with UTC "today" while capture
      names files after the commit's local-timezone author date, so it failed every day
      from 20:00 to midnight in UTC-4 — fixed by deriving the expected name from the
      commit itself.

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
- [ ] **Latency budget.** Measured 2026-07-13 (§2.1 Q10, `test_robustness.py`):
      p95 is **~390 ms at 500 files, ~740 ms at 1000** — 2-5x over the 150 ms target
      here, and the gap is structural, not incidental: `read_combined_context`
      reads and parses every store file before ranking/trimming to the token
      budget, so cost scales with total store size regardless of the budget or
      whether a query is given. Hitting 150 ms needs a read path that stops once
      the budget is full (an on-disk index of frontmatter — priority/summary/tags
      — read first, full file bodies only pulled for what actually makes the cut)
      — this is now the concrete first task of this bullet, not "add a perf test",
      which is already done and passing as a regression guard (not yet the target).

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
   (v0.7 shipped 2026-07-07. v0.7.1 hardening shipped 2026-07-08: all 15 findings from
   the first realistic end-to-end test campaign fixed — MCP dream results no longer
   report isError on success, git hooks pin their CLI and fail audibly, failure-memory
   dedup survives reworded errors, installer is local-first with a pinned uvx fallback,
   append preserves priority, verify clears stale markers, no-op dreams keep the git
   tree clean, snapshot retention + `rollback --list` + `clean`, doctor-clean init,
   UTF-8 CLI output, accurate provider warnings, valid diff headers, and a
   deterministic contradiction net. v0.7.2 shipped 2026-07-09: a malformed
   memory-store file's YAML frontmatter no longer crashes `ai-memory dream` —
   the consolidation, hash-recalculation, and rewrite-task scans now skip the
   bad file and surface a warning instead of aborting the whole command.)
6. **Phase 0 completion — quality hardening Q1–Q10 (§2.1, analysis of 2026-07-12)** —
   Q1 MCP-boundary tests, Q2 version-truth check, and Q3 coverage gate land before v0.8
   starts; Q4–Q10 interleave with it. Rationale: both field-test criticals lived in
   layers the suite doesn't reach — close that bug class before building more surface.
7. **Phase 2.2 migration tooling (v0.8)** — done 2026-07-13 (`ai-memory migrate`, init
   store scaffolding, CHANGELOG + migration guide, dogfood reference case 85→96; see
   §4.2). Release tag pending, per the separate-release-step convention.
8. **Launch v1.0** (Phase 6 demo + announcements) on the strength of distribution and
   the clean store-first model.
9. **Phase 3.2–3.3 client-hook enforcement + capture stats** — post-launch, guided by
   which clients real users actually run.
10. **Phase 4 retrieval quality** — you can only rank what was captured; capture first.
11. **Phase 5 benchmarks** — publish numbers; the coding-memory benchmark is the moat,
    and it doubles as the proof for Phase 3's capture-rate claim.
