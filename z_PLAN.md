# z_PLAN.md — Execution Plan for Memory Fabric

> Companion to `ROADMAP.md` (strategy) and `plan.md` (v1.3 architecture spec).
> This file is the concrete, task-by-task execution plan: what to build, in which files,
> with acceptance criteria. Work top-to-bottom; each task is sized for one focused session.
> Check off tasks as they land. Update this file at the end of every session.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Milestone A — Ship to PyPI with green CI (unblocks everything)

Target: `pip install memory-fabric` works worldwide; CI proves it on 3 OSes.

### A1. `[x]` CI workflow — DONE

`.github/workflows/ci.yml` matches the spec: matrix `{ubuntu,windows,macos} x
{3.11,3.12,3.13,3.14}`, `pip install -e ".[mcp,test]"` → `pytest tests/ -v`, plus an
entry-point sanity check (`which`/`where memory-fabric-mcp`). Separate `lint` job runs
`ruff check .`, `ruff format --check .`, `mypy src/memory_fabric`. CI badge already in
README. Not yet confirmed green on GitHub itself (no `gh auth` in this session) — confirm
after the next push.

### A2. `[x]` Lint/type config — DONE (2026-07-04)

`[tool.ruff]` (line-length 100, target-version py311) and `[tool.mypy]`
(`disallow_untyped_defs`, `warn_unused_ignores`, `warn_redundant_casts`) were already in
`pyproject.toml`. Verification found 2 real gaps the checkboxes hadn't caught yet:

1. `ruff format --check .` failed on `llm.py` and `test_frontmatter.py` — implicit
   string-literal concatenation (`"a\n" "b\n"`) that `ruff format` collapses to one string.
   Cosmetic; fixed by running `ruff format`.
2. `mypy src/memory_fabric` failed at `server.py:509`: the module-level `mcp` name is
   assigned `FastMCP("Memory Fabric")` in the `if FastMCP is not None:` branch and `None`
   in the `else:` branch; mypy infers `FastMCP[Any]` from the first assignment and rejects
   the second. Fixed with an explicit `mcp: FastMCP[Any] | None` annotation before the
   branch — matches how `main()` already treats `mcp` as Optional at runtime.

`ruff check .`, `ruff format --check .`, and `mypy src/memory_fabric` all exit 0 now.

### A3. `[x]` Single-source the version — DONE

Already wired: `pyproject.toml` has `dynamic = ["version"]` +
`[tool.setuptools.dynamic] version = { attr = "memory_fabric.version.__version__" }`, and
`cli.py` has `--version`. Verified: `import memory_fabric; memory_fabric.__version__` and
`ai-memory --version` both print `0.3.0`, matching `version.py`.

### A4. `[x]` README truth pass — DONE

Version claim was already accurate ("v0.3.0 — functional, not yet published to PyPI"), not
the stale "v0.1.0" the roadmap flagged — no change needed there. CI badge present.
Verified every Quick Start command actually runs end-to-end against a fresh `.ai-memory/`
in a scratch dir: `init`, `doctor`, `eval`, `query`, `dream --mode light`, `status` all
succeed.

### A5. `[ ]` PyPI trusted publishing

1. On pypi.org → your account → Publishing → **add pending publisher**:
   project `memory-fabric`, owner `elViRafa`, repo `agentic-memory`,
   workflow `release.yml`, environment `pypi`.
2. Create `.github/workflows/release.yml`:
   - Trigger: `push: tags: ["v*"]`.
   - Job 1 `build`: `python -m build`, upload `dist/*` as artifact.
   - Job 2 `publish`: environment `pypi`, `permissions: id-token: write`,
     `pypa/gh-action-pypi-publish@release/v1`. No API tokens anywhere.
3. Bump `version.py` to `0.4.0`, tag `v0.4.0`, push tag.

**`release.yml` already exists and exceeds the spec** (2026-07-04): `test` (full OS×Python
matrix, mirrors CI) → `build` (also asserts the git tag matches `version.py`, fails loudly
on mismatch instead of publishing the wrong version) → `publish` (OIDC trusted publishing,
no tokens, exactly as specced) → `github-release` (auto-creates the GitHub Release with
`gh release create --generate-notes`, attaching the built artifacts). Still outstanding,
in order:

- [ ] Step 1 above (pending-publisher registration) — **requires the repo owner's own
      pypi.org login; cannot be done by an agent.**
- [x] Bump `version.py` 0.3.0 → 0.4.0 (`0c8f535`), tag `v0.4.0`, push tag — done
      2026-07-05. **Discovered CI is not actually green on GitHub** (see below) — the
      publish did not go through, safely.

**BLOCKER found 2026-07-05, unresolved:** pushing `v0.4.0` surfaced that CI has been
*failing* on GitHub across the last 3 pushes to `main` — including `4d59005`, the commit
*before* this session touched anything, so this predates Milestone A work and was never
actually caught (nobody had checked the Actions tab; local `pytest`/`ruff`/`mypy` were
genuinely green every time they were checked, which is what made the "not yet confirmed
green on GitHub" note above necessary in the first place).

Confirmed via the public `checks-runs`/`actions/runs` API (no `gh auth` in this session,
Chrome extension bridge also unreachable, and GitHub's job-log download endpoint requires
admin auth even for public repos, so only pass/fail + generic "exit code 1" annotations
were visible, not real tracebacks):

- Pattern: `ubuntu-latest` mostly passes (3.12/3.13 clean both runs; 3.11/3.14 inconsistent
  — *passed* in `release.yml`'s test job but *failed* in `ci.yml`'s test job for the exact
  same commit/SHA). `windows-latest` and `macos-latest` fail across all 4 Python versions,
  in both workflows. The `Lint & type-check` job (ubuntu-latest, single Python 3.12) also
  failed — same commands (`ruff check .`, `ruff format --check .`, `mypy src/memory_fabric`)
  pass clean locally.
- The same commit giving a different result across two workflow runs points at **flakiness**
  (timing/ordering-sensitive, not deterministic per-OS) rather than a pure platform bug —
  prime suspects are the concurrency/timeout-based tests in `test_robustness.py`
  (`ConcurrentWriteTests`, `LockReleaseTests`, `LargeStorePerformanceTests`'s 15s bound).
  Ran `test_robustness.py` 5x locally in a genuinely fresh venv (not the possibly-stale
  `.venv/` used for the "green locally" check earlier this session) — no failures, so it
  hasn't reproduced yet locally either. Doesn't rule out the Windows/macOS jobs being a
  separate, real, consistent bug rather than flakiness — the Lint job failing is the odd
  one out and doesn't fit the timing-test theory at all.
- **Confirmed safe**: `release.yml`'s `build` → `publish` → `github-release` jobs all show
  `conclusion: skipped` for the `v0.4.0` tag push (they `need: test`, which failed) — so
  no package was actually uploaded to PyPI. The tag itself is public on GitHub now, but
  that alone has no PyPI-side effect.
- **Next step needs either**: `gh auth login` (so `gh run view --log-failed` can pull the
  actual tracebacks) or working browser access to the Actions tab, or the repo owner
  pasting a failing step's log directly. Guessing at fixes blind, commit after commit,
  isn't worth the noise until the real error text is in hand.

**RESOLVED 2026-07-05.** User ran `gh auth login`; `gh run view <id> --log-failed` gave
real tracebacks. All 5 distinct root causes (not flakiness after all — every failure was
deterministic given the right OS/version/timing) found and fixed:

1. **`locking.py` mypy failure (the Lint job)**: `msvcrt.locking`/`LK_LOCK`/`LK_UNLCK` are
   gated behind `sys.platform == "win32"` inside typeshed's stub, so mypy only recognizes
   them when its *assumed* platform is win32 — which depends on the host mypy itself runs
   on, not the code's target. The lint job pins `ubuntu-latest`, so it always saw "Module
   has no attribute" on the msvcrt calls, while the paired `fcntl` calls' `# type:
   ignore[attr-defined]` (needed only when mypy assumes win32) flagged as unused. This is
   exactly why it passed clean every time it was checked locally on this Windows machine —
   never on Linux. Rewrote `_lock`/`_unlock` from `try/except ImportError` to
   `if sys.platform == "win32": ... else: ...`, the form mypy specifically recognizes for
   platform-conditional checking (skips the non-matching branch entirely — no ignores
   needed on either assumed platform). Verified with `mypy --platform {win32,linux,darwin}`,
   all clean — no Linux box needed to confirm.
2. **`test_initialized_eval_saves_reports_and_ignores_evals` (windows-latest, all versions;
   macos-latest, all versions)**: test built its expected path as
   `Path(temp) / ".ai-memory" / ...` (raw), while the app resolves `cwd` internally via
   `validate_cwd()` (`.resolve()`, a deliberate path-traversal guard, not a bug) before
   deriving report paths. Diverges textually whenever the OS's raw temp path isn't already
   canonical: Windows short-name form (`RUNNER~1` vs `runneradmin` — GitHub's Windows
   runner account name is long enough to need an 8.3 alias; this developer's own account
   name is short enough that it never happens locally) or macOS's `/var` → `/private/var`
   symlink. Fixed the test to `Path(temp).resolve()`, matching the app's own (correct)
   behavior.
3. **`NonUtf8FileTests::test_doctor_reports_error_but_does_not_raise`** (windows-latest, all
   versions): identical root cause to #2, same fix, in `_write_invalid_utf8_section`'s
   `memory_dir` construction.
4. **`ERROR tests/test_resources.py` collecting (Python 3.11, all 3 OSes)**:
   `pydantic.errors.PydanticUserError: Please use typing_extensions.TypedDict instead of
   typing.TypedDict on Python < 3.12.` `contracts.py` imported `TypedDict`/`NotRequired`
   from stdlib `typing` unconditionally; FastMCP's pydantic-based schema generation
   rejects stdlib `TypedDict` before 3.12. Fixed with a version-gated import in
   `contracts.py`: `typing_extensions` on <3.12 (present whenever `[mcp]` is installed —
   it's an unconditional pydantic dependency, confirmed via `pip show pydantic`), falling
   back to stdlib `typing` if `typing_extensions` isn't there at all (core-only install,
   no pydantic in play anyway) — keeps the zero-required-deps guarantee for core-only
   users.
5. **`ConcurrentWriteTests::test_concurrent_appends_all_survive_without_corruption`**
   (ubuntu-latest/3.14 in one run, not the other — the one that looked like flakiness):
   a real TOCTOU race in `locking.py`. `locked_file()` unlinks the `.lock` sidecar only
   *after* releasing the flock, so a new opener can create a fresh inode at the same path
   while an *earlier* waiter — blocked in `_lock()` on the original inode before the
   unlink happened — is still waiting. Once that waiter is finally granted its lock (on
   the now-orphaned inode), it and the new opener hold locks on two different inodes that
   merely share a path: no longer mutually exclusive, so both run their critical sections
   at once, and one can observe the other's torn write (missing frontmatter delimiter —
   exactly the error seen). Windows never hit this because `msvcrt`-locked files can't be
   deleted while another handle has them open (raises `PermissionError`, already handled),
   so the race window that exists on POSIX unlink doesn't exist there — consistent with
   this only ever showing up on `ubuntu-latest`. Fixed with the standard flock-plus-unlink
   pattern: after locking, re-`stat()` the path and compare identity
   (`os.path.samestat`) against the locked fd; retry (close, reopen, relock) on mismatch.
   Preserves the existing "no leaked `.lock` file after a crash" guarantee
   (`test_lock_sidecar_file_does_not_leak_after_crash`) rather than trading it away by
   just never unlinking. Stress-tested `test_robustness.py` 50 consecutive runs locally
   (up from the 5 that failed to reproduce it originally) with zero failures post-fix.

Version bumped again: `0.4.0`'s tag never actually published (build/publish/github-release
were skipped), so rather than force-move that tag, the next tag is `0.4.1`.

**CI confirmed green on GitHub itself for the first time** (`gh run watch 28728450615`):
all of `Lint & type-check` + `Test` × {ubuntu,windows,macos} × {3.11,3.12,3.13,3.14} passed
on push `7ef6d4e`. Tagged and pushed `v0.4.1` (`gh run watch 28728501482`): `Test before
release` (full matrix) and `Build distribution` both passed — confirms the fixes are real,
not a local-only artifact. `Publish to PyPI` then failed, exactly as expected since the
pending-publisher step hasn't been done yet:

```
Trusted publishing exchange failure: invalid-publisher (Publisher with matching
claims was not found)
sub: repo:elViRafa/agentic-memory:environment:pypi
workflow_ref: elViRafa/agentic-memory/.github/workflows/release.yml@refs/tags/v0.4.1
```

This is the expected, safe failure mode for an unregistered trusted publisher — no token
leakage, no partial publish. `Create GitHub Release` correctly never ran (`needs: publish`).
**Once the pending-publisher step (top of this section) is done, no new tag/version bump
is needed** — re-run only the failed `Publish to PyPI` job on the existing `v0.4.1` run
(`gh run rerun 28728501482 --failed`), which will pick up the already-built, already-tested
artifacts.

Acceptance: `memory-fabric` page live on PyPI; release created from tag.

### A6. `[ ]` Verify the universal install path

On a machine/venv WITHOUT the repo:

```sh
uvx --from "memory-fabric[mcp]" memory-fabric-mcp   # starts MCP server on stdio
pipx install "memory-fabric[mcp]" && ai-memory doctor
```

Acceptance: both work on Windows (this machine) — ask a friend or use a VM/GitHub codespace for Linux/macOS spot-check (CI matrix covers most of it).

---

## Milestone B — Split the god module (`storage/_core.py`, ~108 KB / 2840 lines)

Do AFTER A (so CI catches regressions), BEFORE new features pile on more code.

### B1. `[x]` Extraction plan — REVISED after reading the full file (2026-07-05)

The original 6-module table below was a guess made before reading `_core.py`. Having now
read all 2840 lines and traced every call site, two things were wrong with it: it omitted
`initialize_memory_fabric` / `sync_agent_rules` / `status` / `doctor` entirely (~385 lines,
no home in any of the 6 buckets), and it underestimated the dream/consolidation code by
roughly 2x — as one `dream.py` it would land at ~47 KB, blowing the 25 KB budget. Revised,
verified plan (11 files, all confirmed < 25 KB by line-count):

| New module | Moves from `_core.py` | Depends on | Est. size |
|---|---|---|---|
| `_shared.py` (renamed from `_core.py`) | Constants (`SECTION_PATTERN`, `STORE_PATH_SEGMENT`, `PRIORITY_ORDER`, `CURRENT_SCHEMA_VERSION`) + `_validate_store_path`, `_resolve_store_file`, `_path_to_store_path`, `_section_path`, `_migrate_frontmatter`, `_read_memory_path`, `_safe_parse_for_sort`, `_iter_markdown_files`, `_is_ignored_local_memory_path`, `_is_store_path`, `estimate_tokens`, `_jaccard_similar` | external only | ~8 KB |
| `lifecycle.py` | `initialize_memory_fabric`, `sync_agent_rules`, `status`, `doctor` | `_shared` | ~15 KB |
| `search.py` | `keyword_search`, `_keyword_search_rg`, `_keyword_search_python`, `_search_section_label` | `_shared` | ~5 KB |
| `sections.py` | `read_section`, `write_local_memory` (flat `.ai-memory/*.md` CRUD) | `_shared`, `lifecycle` | ~6 KB |
| `snapshots.py` | `create_snapshot`, `rollback` | `_shared` | ~2 KB |
| `store.py` | `write_memory_store`, `read_memory_store`, `list_memory_store`, `delete_memory_store` (semantic `memory-store/` CRUD) | `_shared` | ~10 KB |
| `journal.py` | `write_session_journal` | `store` | ~4 KB |
| `context.py` | `read_combined_context`, `_score_section_relevance`, `_ordered_context_files`, `_section_key`, `_format_fragment` | `_shared` | ~10 KB |
| `patch.py` | `propose_memory_patch` | `_shared` | ~7 KB |
| `consolidation.py` | `_create_candidate_store`, `_consolidate_candidate_memory`, `_normalize_dedupe_line`, `_diff_memory_roots`, `_relative_markdown_paths`, `_apply_candidate_to_live`, `_build_rewrite_tasks`, `_regenerate_index`, `_regenerate_index_root`, `_extract_key_topics`, `_compile_consolidated_memory` | `_shared` | ~15 KB |
| `dream.py` | `dream`, `prepare_dream_payload`, `apply_dream_results`, `_process_and_finalize_candidate`, `_get_git_diff`, `_is_llm_ready`, `_get_section_key`, `_parse_llm_json_response` | `_shared`, `lifecycle`, `snapshots`, `consolidation`, `llm.call_llm` | ~23 KB |

`_core.py` is deleted once empty (not kept as a re-export shim).

**Known gotcha (verified via grep, not guessed):** 8 test `mock.patch("memory_fabric.storage._core.call_llm"/"now_iso", ...)`
calls in `test_dream_store.py`/`test_memory_fabric.py` patch by dotted string path. Once
`dream()` moves to `storage/dream.py`, these must become
`mock.patch("memory_fabric.storage.dream.call_llm"/"now_iso", ...)` or the mocks silently
stop taking effect (tests would hit real LLM calls / real timestamps instead of failing loud).

**This gotcha bit earlier than expected, at the `snapshots.py` step (2026-07-05):**
`create_snapshot()` calls `now_iso()` too. All 3 tests that mock `now_iso` with an
incrementing `side_effect` (to give successive `dream()` calls unique snapshot names) only
patched `_core.now_iso` — once `create_snapshot` moved to `storage/snapshots.py` with its own
`now_iso` import, its calls used the *real* clock again, and two `dream()` calls landing in
the same wall-clock second produced identical snapshot dir names → `FileExistsError`. Fixed
by adding a second `@mock.patch("memory_fabric.storage.snapshots.now_iso")` decorator to each
of the 3 tests, sharing the *same* `increment_now_iso` closure/counter as the existing
`_core.now_iso` patch (two independent counters would still collide with each other).
**Lesson for the remaining steps:** any test mocking `now_iso` or `call_llm` needs one
`mock.patch` per module that ends up importing that name — check this after every extraction,
not just the final `dream.py` one.

**Third occurrence, at the `consolidation.py` step (2026-07-05):** `_regenerate_index_root`
(moved to `storage/consolidation.py`) also calls `now_iso()` to stamp the index file. Only
`test_dream_consolidation_skips_when_hash_matches` broke — its "skip" assertion checks
`affected_files == ["index.md"]`, which depends on the regenerated index differing from the
previous run's; with `consolidation.now_iso` unmocked, two `dream()` calls landing in the same
wall-clock second produced byte-identical index files, so nothing showed as changed. Fixed by
adding a third `@mock.patch("memory_fabric.storage.consolidation.now_iso")`, same shared
counter. The other two tests weren't affected — they assert on `call_llm.call_count` and
`summary_hash`, not `affected_files`, so they were never exposed to this specific gap. Not
adding defensive mocks to tests that aren't actually at risk — only the ones that broke or
provably could.

Rule: `memory_fabric/storage/__init__.py` re-exports the same public names after every
step — `server.py`, `cli.py`, and tests must not need import changes.

Extraction order (dependency-safe, tests green after each step):
`_shared` → `lifecycle` → `search` → `sections` → `snapshots` → `store` → `journal` →
`context` → `patch` → `consolidation` → `dream` → delete `_core.py` → fix the 8 mock.patch targets.

Acceptance per step: `pytest -q` green; no file in `src/` > 25 KB at the end.

### B1 — DONE (2026-07-05). Final module map (12 files, `_core.py` deleted):

`_shared.py` (8.8K) · `lifecycle.py` (17.7K) · `search.py` (3.9K) · `sections.py` (5.6K) ·
`snapshots.py` (2.1K) · `store.py` (9.6K) · `journal.py` (3.2K) · `context.py` (11.1K) ·
`patch.py` (6.2K) · `consolidation.py` (15.3K) · `finalize.py` (16.5K) · `dream.py` (15.9K).
All under the 25 KB target (largest is `finalize.py`).

**One more split than planned:** `dream.py` alone came out at ~31.6 KB (over budget) because
`dream()`/`prepare_dream_payload()`/`apply_dream_results()` all share a huge amount of logic
via `_process_and_finalize_candidate`. Split that shared internal (`_process_and_finalize_candidate`,
`_is_llm_ready`, `_parse_llm_json_response`, `_get_git_diff`) into `finalize.py`, leaving `dream.py`
as just the 3 public entry points. This revealed a second mocking subtlety: `call_llm` is now
called from *both* `dream.py` (consolidation prompt) and `finalize.py` (per-section summaries) as
independent imports — tests asserting `call_count` or relying on ordered `side_effect` lists need
`dream.call_llm` and `finalize.call_llm` to be *the same mock object*, not just two mocks with
matching behavior (unlike the `now_iso` fix, sharing a closure isn't enough here since `call_count`
is tracked per-mock-instance). Fixed via `mock.patch(A) as m` + `mock.patch(B, new=m)` in the 3
affected tests, using Python's parenthesized multi-context-manager `with (...)` syntax.

**Out of scope, noted for later:** `eval.py` (41.2 KB) and `server.py` (23.2 KB) are siblings of
`storage/`, not part of it — never in Milestone B's scope (which was specifically `storage/_core.py`).
`eval.py` in particular is now the single largest file in the package and a reasonable next
target if this kind of split continues.

### B2. `[x]` Add regression tests where extraction reveals gaps — DONE (2026-07-05)

New `tests/test_robustness.py`, 10 tests, all covered:

- **Concurrent writes** (`ConcurrentWriteTests`): N threads appending to the same flat
  section, and N threads writing distinct semantic-store paths, concurrently.
- **Crash mid-write / lock release** (`LockReleaseTests`): raise inside `with locked_file(...)`,
  verify a second acquisition doesn't hang (via a worker thread + timeout, so a real
  regression fails the test instead of freezing the suite) and the `.lock` sidecar is cleaned up.
- **Non-UTF-8 file** (`NonUtf8FileTests`): a `.md` file with invalid UTF-8 bytes must not crash
  `doctor`/`status`/`read_combined_context` — already handled by `_shared.py`'s
  `(OSError, UnicodeDecodeError, FrontmatterError)` catches; these tests lock that in.
- **1000-file store performance smoke** (`LargeStorePerformanceTests`): `list_memory_store`,
  `doctor`, `read_combined_context` against a 1000-file store, asserting correctness + a
  generous 15s bound (smoke, not a strict benchmark).

**Found and fixed two real, pre-existing concurrency bugs in `locking.py` while writing the
"concurrent writes" test** (not introduced by the Milestone B split — this file was untouched
by B1 — but never caught because nothing tested concurrent writers before):

1. `_lock()` used `msvcrt.LK_NBLCK` (non-blocking, fails immediately on contention) on Windows,
   while the POSIX path (`fcntl.flock`) already blocks by default. A second concurrent writer
   got a raw `PermissionError` instead of safely queuing. Fixed: `LK_NBLCK` → `LK_LOCK` (retries
   for ~10s before raising), matching POSIX's blocking behavior.
2. That fix exposed a second bug: the waiting thread's file handle stays open on the `.lock`
   sidecar while it retries, so when the first writer finishes and calls `lock_path.unlink()`,
   Windows raises `PermissionError` (can't delete a file with another open handle, unlike POSIX).
   Fixed: broadened the existing `except FileNotFoundError` to also catch `PermissionError` —
   the data file write already succeeded by that point; leaving the empty `.lock` sidecar behind
   is harmless housekeeping debt, not a correctness issue.

Verified with a standalone diagnostic (2 and 4 concurrent threads, several runs) before and
after each fix, then locked in via `test_robustness.py`. Flagged a follow-up background task for
deeper stress-testing (20-50 threads) since only light concurrency has been exercised so far.

One test-writing lesson worth keeping: the first version of the concurrent-append test used
content differing only by a trailing digit ("entry 0", "entry 1", ...) and 9/10 new tests passed
but this one failed — looked like a lost-update bug. It wasn't: `write_local_memory`'s Jaccard
near-duplicate filter strips words of length ≤ 2 before comparing, so "entry 0" and "entry 1"
reduce to the identical significant-word-set and get (correctly) deduplicated to one line. Fixed
the test to use genuinely distinct topics instead of relying on a numeric suffix.

---

## Milestone C — `ai-memory install` (one command per client)

The core deliverable for "usable in VS Code, Claude, Codex, Antigravity and others."

### C1. `[x]` Client registry module — DONE (2026-07-05)

`src/memory_fabric/clients.py` was built close to the original sketch, with three
changes made concrete once actual write logic needed to consume the registry:

- `entry: dict` became `build_entry(use_uvx: bool) -> dict`, a free function rather
  than a per-client static field — the uvx-vs-fallback choice is a single
  `shutil.which("uv")` check made once per install run, not something to duplicate
  across 9 dict literals.
- Added `supports_project: bool` / `supports_global: bool` flags (the original
  `scope: Literal["global", "project"]` single field can't represent a client that
  supports both, which turned out to be most of them). `--project` on a client with
  `supports_project=False` falls back to global with a warning instead of erroring.
- Added `extra_entry_keys: dict | None` (VS Code's `"type": "stdio"`) and
  `detect_installed: Callable[..., bool]` (for `--client all`).

`config_path` and `detect_installed` share one keyword-only signature across all 9
clients — `(*, project, cwd, platform_name=None, env=None, home=None)` — mirroring
the DI pattern already established by `paths.get_global_root()` (same optional
`platform_name`/`env`/`home` kwargs, tested the same way in
`tests/test_memory_fabric.py:137-150`). Most resolvers ignore most of these kwargs;
uniformity keeps the one call site in `installer.py` simple. A small private
`_os_app_config_dir(app_name, ...)` helper (the same Windows-`APPDATA`/macOS-`Library`/
Linux-`XDG_CONFIG_HOME` branch as `get_global_root`, parametrized on app name instead
of hardcoding `"memory-fabric"`) is shared by claude-desktop and VS Code/Cline's common
`.../Code/User` base — kept local to `clients.py` rather than merged into `paths.py`,
since `get_global_root` already ships a tested `MEMORY_FABRIC_HOME`-override contract
not relevant here.

### C2. `[x]` Config paths per client — DONE, verified against current docs (2026-07-05)

Two of the fast-moving/post-training-cutoff ones came back **different from the
original table above** after checking current documentation instead of trusting
memory (Antigravity ships after this assistant's training cutoff; VS Code's MCP
scheme evolves quickly):

- **VS Code does have a real global/user scope** — not just the project
  `.vscode/mcp.json` the original table implied. Confirmed via
  code.visualstudio.com: a genuine `mcp.json` lives at `<VSCodeUserDir>/mcp.json`
  (Win `%APPDATA%\Code\User\mcp.json`, mac `~/Library/Application Support/Code/User/mcp.json`,
  Linux `~/.config/Code/User/mcp.json`) — the exact same base directory Cline's
  `globalStorage` path descends from, so both resolvers share one helper.
- **VS Code's root key is `"servers"`, not `"mcpServers"`** — confirmed directly
  from VS Code's own MCP configuration reference page. Would have silently produced
  a config VS Code never reads if left as originally guessed.
- Codex's `command`/`args` TOML fields, Cline's path and `saoudrizwan.claude-dev`
  publisher id, Windsurf's `~/.codeium/windsurf/mcp_config.json` (no OS branching —
  same relative-to-home path on every OS, confirmed via Windsurf's own docs), Claude
  Code's `claude mcp add <name> [opts] -- <cmd> [args...]` / `claude mcp remove <name>`
  syntax, and Antigravity/Gemini CLI's shared `~/.gemini/config/mcp_config.json` (root
  key `mcpServers`) all came back matching the original table — confirmed anyway
  rather than assumed, since C2's own title says "verify each."
- `gemini-cli`'s legacy-fallback detection (`~/.gemini/settings.json` if the central
  `~/.gemini/config/` dir doesn't exist yet) implemented exactly as originally noted.

### C3. `[x]` Safe write engine — DONE (2026-07-05)

`src/memory_fabric/installer.py`. Notable deviations from the original one-line spec:

- "Deep-merge only our key" turned out to just mean a **targeted single-key merge**
  (`config[root_key]["memory-fabric"] = entry`) — there's no actual deep-merging
  logic needed since nothing else is ever touched; `json.loads`/`json.dumps`
  round-tripping keeps every other key, and their original insertion order,
  byte-for-identical for free.
- Backup (`<file>.bak-<ts>`) is created **only** on a parse failure, never on a
  normal write — the timestamp reuses the exact
  `now_iso().replace(":", "").replace("+", "_").replace("-", "")` sanitizing idiom
  `storage/snapshots.py:23-25` already established, rather than inventing a new one.
- TOML uninstall wasn't specified by the original one-liner ("append... if absent"
  only covers install). Implemented as a `# >>> memory-fabric install ... >>>` /
  `# <<< memory-fabric install <<<` marker-comment pair around the appended block;
  uninstall regex-slices between the exact markers and re-parses the remainder with
  `tomllib.loads()` before writing, aborting instead of writing if that fails (only
  possible if a user hand-edited between the markers in a file-breaking way).
- All writes (JSON and TOML) go through `locking.py`'s `locked_file()` — not
  required by the spec text, but free to reuse and already Windows-safe.
- `claude-code` prefers shelling out to `claude mcp add`/`claude mcp remove`
  (argv-list `subprocess.run`, no `shell=True`, 15s timeout, `stdin=DEVNULL`) when
  `claude` is on PATH, built from `build_entry(uv_available())` rather than a
  hardcoded `"uvx"` literal so it gets the same fallback as every other client;
  falls back to writing project `.mcp.json` directly via the JSON engine otherwise.
- **`install` is deliberately CLI-only, never an MCP tool** — every other MCP tool
  in `server.py` operates only inside the caller's own project `cwd`; this is the
  only feature that reaches into shared, machine-wide app config
  (`%APPDATA%\Claude\...`, `~/.cursor/mcp.json`, etc.), so it gets the same
  CLI-only treatment the codebase already gives `sync-global` for the same reason.

**One real bug found while writing tests (see C4):** the JSON engine's uninstall
path originally inferred `changed` by comparing serialized text
(`new_text != old_text`), which produced a false `changed=True` when uninstalling
against a config file that had never been created — `""` (the "no file" sentinel)
never equals any valid JSON serialization, even of an empty, unchanged `{}`. Fixed
by making the uninstall branch use `_remove_entry`'s own explicit `removed: bool`
return value directly instead of re-deriving it from text comparison — the TOML
engine's append/remove functions already returned an explicit `changed` boolean and
never had this bug.

### C4. `[x]` Tests — DONE (2026-07-05)

Two new files instead of one, matching the module split: `tests/test_clients.py`
(pure path-resolution correctness — one test per resolver per relevant OS, mirroring
`test_global_path_resolution_is_platform_aware`'s style) and `tests/test_installer.py`
(engine + orchestration — 29 tests covering fresh install, idempotence, merge-preserves-
others, uninstall (present and absent), malformed JSON/TOML → backup + abort, dry-run
diffs, TOML append/idempotence/uninstall, claude-code's subprocess argv and PATH
fallback, and `install_all`'s detection-gated dispatch). 47 tests total between the
two files; 140 pass repo-wide.

**Isolation approach diverges from the spec's literal wording** ("monkeypatched
`HOME`/`APPDATA`") **on purpose**: rather than mutating real `os.environ`/`Path.home`
for the duration of each test, `install()`/`install_all()`/`detect_installed_clients()`
all accept the same optional `platform_name`/`env`/`home` keyword overrides as the
`clients.py` resolvers, threaded straight through. This gets the same isolation
(tests never touch this machine's real Claude Desktop/VS Code/Cursor/etc. config)
without any risk of a failed test leaking a poisoned `APPDATA` into a later test — and
it's free, since the lower layer already needed these params for C1/C2's own testing.
One gotcha hit while writing the `install_all` detection tests: passing `home=<fake>`
alone is **not** sufficient isolation on Windows for the OS-branching clients
(claude-desktop, vscode, cline) — `_os_app_config_dir` checks the real `APPDATA` env
var first and only falls back to `home/AppData/Roaming` if it's unset, so a real
`APPDATA` on the test machine silently overrides a `home=`-only override. Tests that
need full isolation pass `env={}` alongside `home=`, exactly like
`test_global_path_resolution_is_platform_aware` already did for `get_global_root`.

### C5. `[x]` Wire into CLI + docs — DONE (2026-07-05)

`cli.py`: `ai-memory install --client <name|all> [--project] [--dry-run] [--uninstall]`,
`--client` choices generated from `CLIENTS.keys()` (plus `"all"`) rather than a second
hardcoded list, so the two can't drift. README: the old generic "add this JSON" snippet
under `## MCP Server` replaced with the per-client one-command table; `install` added
to the CLI Reference command list.

Verified end-to-end on this machine: `pytest -q` (140 passed), `ruff check .` /
`ruff format --check .` clean, `mypy src/memory_fabric` clean under the default
(win32) platform assumption **and** under `--platform linux` / `--platform darwin`
(Milestone A's lesson — mypy's platform-conditional typeshed stubs mean "passes
locally on Windows" doesn't prove Linux/macOS CI will agree — applied here even
though `installer.py`/`clients.py` don't touch `msvcrt`/`fcntl` themselves).
`ai-memory install --client vscode --project --dry-run` exercised through the real
CLI entry point (not just the Python API) end-to-end.

**Acceptance criterion run for real, with a check-in first** — same instinct as the
PyPI publish step in Milestone A (this is the first thing in the whole project that
writes to shared application state outside this repo, so implementation stopped short
of it until the repo owner confirmed). `ai-memory install --client all --dry-run` ran
first and surfaced a real finding worth having caught before writing anything: `uv`
was not on this machine's PATH, and 3 of the 8 detected clients (vscode, antigravity,
gemini-cli — the last two share one file) already had a **working** `memory-fabric`
entry pointing at a specific project's venv (`.../search-sermons/.venv/Scripts/memory-fabric-mcp.exe`,
`.../agentic-memory/.venv/Scripts/memory-fabric-mcp.exe`) rather than `uvx`. Without
`uv`, the install would have replaced those with a bare `memory-fabric-mcp` command
with no path to resolve against — a downgrade, not an upgrade, for those three. Fixed
by installing `uv` via `scoop install uv` (repo owner's explicit choice, matching the
project's own "`uvx` is the canonical install vector" decision), confirmed `uv`/`uvx`
resolve afterward, re-ran `--dry-run` to confirm every client now generates the
canonical `uvx --from "memory-fabric[mcp]" memory-fabric-mcp` entry, then ran the real
`ai-memory install --client all`. All 8 detected clients (`claude-code` was not
detected — `claude` isn't on this particular PATH) succeeded (`ok=True`); `gemini-cli`
correctly reported `changed=False` since it shares Antigravity's file and Antigravity's
write already landed the identical entry first. Spot-checked the real files afterward:
VS Code's other 10 servers and Antigravity/Gemini's other 5 (including one with
`"disabled": true`) are all still present with unchanged values; Codex's `config.toml`
(model, sandbox, 5 `[projects.*]` trust-level tables, a `[plugins.*]` table) is
untouched above the appended, clearly-marked block.

**One honest cosmetic side effect worth recording:** the JSON engine rewrites the
*entire* file through `json.dumps(..., indent=2)`, so a file that previously used tab
indentation (VS Code's `mcp.json` did) comes back 2-space-indented — a formatting
change to every line, not just the ones we touched. No data, keys, or values are lost
or altered (confirmed above), and every other JSON-writing tool in this ecosystem
reformats files it manages the same way, but it's not byte-for-byte "untouched" in the
way `--uninstall`'s more surgical description implies for our own key specifically —
worth knowing if a user diffs the file and is surprised by the whitespace churn.

---

## Milestone D — Registry, badges, one-click bundles

**Pre-work found while starting D (2026-07-05):** CI was red on `main` at `f788b9f`
(Milestone C's commit) across every OS/Python matrix cell — not caused by anything in D,
but blocking regardless since D1's own deliverable rides on `release.yml`'s `test` job.
Two deterministic, 100%-reproducible bugs, both pure test-fixture issues (no production
code touched):

1. `tests/test_clients.py::ConfigPathResolutionTests::{test_claude_desktop_path_per_os,
   test_os_app_config_dir_is_platform_aware}` — the tests hand-flattened their expected
   Windows path into one `Path(r"C:\Users\R\AppData\Roaming\Claude")` literal, but the
   actual code builds it as `Path(appdata) / "Claude"` (two joined segments). On a
   Windows test-runner both forms happen to produce the same `WindowsPath`, so this
   passed locally for months — but `Path(...)` is host-OS-bound, and on a POSIX CI
   runner it becomes `PosixPath`, which doesn't treat `\` as a separator, so the two
   forms stop being equal. Fixed by mirroring the implementation's own join boundary in
   the expected value (`Path(r"C:\Users\R\AppData\Roaming") / "Claude"`) instead of
   hand-flattening it — makes the assertion host-OS-independent without touching
   `clients.py` at all. (`test_memory_fabric.py`'s equivalent `get_global_root` test
   already dodges this by asserting a suffix instead of exact equality — good prior art,
   not applied to the newer `clients.py` tests when they were written.)
2. `tests/test_installer.py::ClaudeCodeCliTests::test_claude_not_on_path_falls_back_to_project_mcp_json` —
   the exact same not-`.resolve()`-d temp-dir bug Milestone A already fixed twice
   elsewhere (macOS `/var`→`/private/var`, Windows `RUNNER~1` short name), just missed in
   this newer test. One-line fix: `Path(temp)` → `Path(temp).resolve()`.

Pushed as its own `fix:` commit ahead of the Milestone D feature commit.
`ConcurrentWriteTests::test_concurrent_appends_all_survive_without_corruption` also
failed, but only once, only on `macos-latest`/Python 3.11 — not reproducible locally
(this dev machine structurally can't hit the POSIX-unlink race per `locking.py`'s own
docstring) and not deterministic across the matrix the way the two above are. Left
alone rather than guess-patched; flagged as a follow-up needing real macOS CI logs, same
discipline as the Milestone A CI blocker.

### D1. `[x]` Official MCP Registry — DONE (2026-07-05)

Researched against current official docs rather than training data (registry docs
reorganized since any likely training cutoff — the old `docs/guides/publishing/` path
from the original one-liner above 404s now; current path is
`docs/modelcontextprotocol-io/{quickstart,authentication,package-types,github-actions}.mdx`
+ `docs/reference/server-json/`, fetched via `gh api repos/modelcontextprotocol/registry/contents/...`
since raw.githubusercontent.com was flaky this session).

- **Namespace casing verified, not assumed — and it came back different from this
  plan's own text.** This file's step 1/2 above wrote `io.github.elvirafa` (lowercase).
  Ran the real `mcp-publisher login github` OAuth flow (device code, user completed it
  in-browser) and decoded the resulting token's own JWT claims (not the raw token —
  only the non-secret `permissions`/`sub` claims): the registry grants
  `io.github.elViRafa/*`, preserving GitHub's exact stored username case. Every registry
  doc example happens to use an already-lowercase username, so this distinction never
  surfaced in the docs — used `io.github.elViRafa/memory-fabric` in both `server.json`
  and the README marker.
- `mcp-name: io.github.elViRafa/memory-fabric` added to `README.md` as an HTML comment
  (boundary-safe per the spec: the token must be followed by newline/whitespace/tag/`-->`).
- `server.json` at repo root. `mcp-publisher` has no Go dependency — installed via the
  official prebuilt-binary one-liner. One real schema question the one-liner plan
  glossed over: this project's canonical invocation is
  `uvx --from "memory-fabric[mcp]" memory-fabric-mcp` (package name ≠ script name, plus
  an extra), while every documented `registryType: pypi` example assumes package name ==
  script name. Fetched the live `server.schema.json` directly: `identifier` must stay the
  bare PyPI project name (`memory-fabric`) since that's what ownership verification
  looks up on pypi.org; the `--from` flag and the differing entry-point name both belong
  in `runtimeArguments` (documented as "arguments passed to the package's *runtime*
  command", vs. `packageArguments` for the server binary itself) — one `named` (`--from`,
  `memory-fabric[mcp]`) plus one trailing `positional` (`memory-fabric-mcp`). Confirmed
  schema-valid via `mcp-publisher validate server.json`, which round-trips against the
  live registry (needs network, not auth) — passed clean on the first try after fixing
  an unrelated `description` length cap (≤100 chars) the validator caught.
- `mcp-publisher publish` **deliberately not run for real** — PyPI ownership verification
  fetches `pypi.org/pypi/memory-fabric/json`, still 404 (Milestone A's pending-publisher
  step, repo-owner-only, still outstanding). Same honest blocker, not a new one.
- `registry-publish` job appended to `release.yml`, `needs: publish` (must run after the
  PyPI job actually succeeds, since that's what makes the ownership check possible) using
  `mcp-publisher login github-oidc` (zero stored secrets, `id-token: write`) — the
  officially documented CI recipe. Also syncs `server.json`'s version to the release tag
  via `jq` before publishing, so it never needs manual re-syncing against `version.py`.

Acceptance (server visible at registry.modelcontextprotocol.io) is **not yet met** —
correctly blocked on the same PyPI step as Milestone A, not a new gap.

### D2. `[x]` One-click install badges in README — DONE (2026-07-05)

- VS Code / VS Code Insiders: `vscode:mcp/install?<url-encoded JSON>` /
  `vscode-insiders:mcp/install?<...>` with
  `{"name":"memory-fabric","command":"uvx","args":["--from","memory-fabric[mcp]","memory-fabric-mcp"]}`.
- Cursor: `cursor://anysphere.cursor-deeplink/mcp/install?name=memory-fabric&config=<base64>`,
  confirmed against Cursor's own docs (`cursor.com/docs/context/mcp/install-links`); badge
  image is Cursor's official asset (`cursor.com/deeplink/mcp-install-dark.svg`, confirmed
  live via a direct HTTP check rather than guessed).
- **Both badges click-tested for real on this machine** (both editors installed here),
  not just eyeballed: VS Code showed a correct install prompt. Cursor went further and
  actually attempted the `uv` resolution live, surfacing
  `No solution found... memory-fabric[mcp]` — i.e. the deeplink, JSON encoding, and
  Cursor's own parsing are all confirmed correct; the failure is the same PyPI blocker
  as everywhere else in this milestone, not a badge defect. VS Code Insiders wasn't
  independently click-tested (not installed here) but is byte-identical to the verified
  VS Code payload apart from the URI scheme.

Acceptance met for what's testable pre-PyPI-publish: badges open the correct install
flow with the correct command on both installed editors.

### D3. `[x]` MCPB bundle for Claude Desktop (stretch) — DONE (2026-07-05)

Real deviation from this plan's one-liner, found by reading the current MCPB spec
(`modelcontextprotocol/mcpb`'s `MANIFEST.md`) instead of assuming: `server.type: "python"`
was the original idea, but the docs explicitly warn it "cannot portably bundle compiled
dependencies (e.g., pydantic, which the MCP Python SDK requires)" — exactly the risk this
file's original caution line was worried about. Used `server.type: "uv"` (MCPB v0.4+)
instead, and further diverged from the one worked example available
(`examples/hello-world-uv`, which bundles the server's *own* source + `pyproject.toml`
and runs it via `uv run`): rather than duplicating this project's source into the bundle,
`mcpb/` is a **thin shim** — `mcpb/pyproject.toml` depends on `memory-fabric[mcp]` (from
PyPI, not bundled) and `mcpb/src/server.py` just imports and calls
`memory_fabric.server.main()`. This stays inside the documented uv-runtime contract
(bundle `pyproject.toml` + entry point, host manages the venv) while achieving the same
"fetch fresh from PyPI, no compiled deps in the archive" outcome as `uvx --from` does for
the CLI/badges — couldn't find a published registry example of this exact shim pattern,
so this is a reasoned construction against the spec's stated rules, not a copied example.

- `npm install -g @anthropic-ai/mcpb`, hand-wrote `mcpb/manifest.json` (repo root already
  has its own real `pyproject.toml` for the actual package build — the mcpb bundle's
  `pyproject.toml` has to live in a subdirectory, it can't share the root one).
  `mcpb validate manifest.json` clean; `mcpb pack mcpb/ ...` produced a 1.2 KB `.mcpb`
  (no bundled deps, as intended).
- **Live-tested twice on this machine**: opening the packed `.mcpb` directly didn't
  trigger a Windows file association (Claude Desktop apparently doesn't register one),
  but dragging it into Claude Desktop's Settings → Extensions worked as documented and
  reached the same real `uv` dependency-resolution step as the Cursor badge — same
  `memory-fabric[mcp]` PyPI 404, confirming the bundle itself is structurally correct.
  macOS install stays unverified (this machine is Windows-only), same asymmetry Milestone
  A already lives with for CI.
- `build-mcpb` job added to `release.yml` (`needs: test`, parallel to `build`/`publish`):
  Node setup, syncs `manifest.json`'s version to the tag via `jq`, packs, uploads as an
  artifact. `github-release` now also depends on `build-mcpb` and attaches the `.mcpb`
  alongside the wheel/sdist.

Acceptance met for what's testable pre-PyPI-publish: drag-drop installs the extension
and reaches real dependency resolution; full "tools become available" end-to-end is
blocked on the same PyPI step as D1/D2.

**What's left for D, all gated on the one Milestone-A blocker (PyPI pending-publisher
registration, repo-owner-only):** once that clears and a version actually publishes to
PyPI, `registry-publish` and `build-mcpb`/`github-release` on the next tag push will
exercise the full path for real — nothing else in D needs further code changes.

---

## Milestone H — v0.8 migration tooling (ROADMAP Phase 2.2 — last v1.0 blocker)

Planned 2026-07-13. Everything hand-written must survive; every write goes through the
existing `write_memory_store` path (locking + secret redaction); the flat file only
flips to a generated map after its granular entries are safely on disk.

### H1. `[x]` `storage/migrate.py` — plan + apply engine — DONE (2026-07-13)

`async def migrate_memory(cwd, dry_run=False, sections=None, use_llm=None) -> MigrateResult`
(async mirrors `dream()`; CLI bridges with `asyncio.run`).

- **Target selection**: flat `.ai-memory/*.md` files that are not `index`, not ignored
  (`_is_ignored_local_memory_path`), not steering (`_is_steering_file`), not
  `generated: true`, not a starter placeholder, and not empty. Hand-edited *generated*
  maps stay Dreaming's fold flow — migrate only owns the legacy (never-generated) files.
- **Heuristic split (always runs — it IS the content)**: split body on H2 headings,
  fence-aware (a `## ` inside a ``` code block is not a boundary). Preamble before the
  first H2 (minus a lone leading H1 title) → `<category>/overview`. Chunk content is
  verbatim source; the heading line moves into `title`. Empty-bodied headings are
  skipped with a warning. Slugs: lowercase, non-alnum → `-`, must match
  `STORE_PATH_SEGMENT`; empty slug → `part-N`; in-plan collisions get `-2`, `-3`.
- **LLM assist = naming only, never content**: one `call_llm` per section proposing
  `{index, store_path, title, summary, tags}` per chunk (JSON, parsed with
  `_parse_llm_json_response`). Validated per entry (`_validate_store_path`, forced
  `<category>/` prefix, index in range); any failure falls back to the heuristic name
  for that entry. No LLM configured → same pipeline, heuristic names. This keeps
  "never delete user content" true by construction instead of by prompt-engineering.
- **Existing-file collisions**: planned target exists with byte-identical (redacted,
  stripped) body → counted as already-migrated, no write (makes re-runs after a partial
  failure resumable without duplicating); exists with different content → `-migrated`
  suffix. Fresh paths write with `mode="replace"`.
- **Snapshot first** (`create_snapshot`, auto name) unless `--dry-run`; rollback is the
  existing `ai-memory rollback --to <name>`.
- **Map handoff**: after a section's entries land, build its generated map directly via
  a helper extracted from `regenerate_maps` (H2) — deliberately bypassing the fold,
  which would re-blob the just-granularized body into `map-notes-pending-review`.
- Idempotent end state: re-run finds no legacy sections, returns an empty plan.

### H2. `[x]` `maps.py` refactor — extract `_generate_category_map` — DONE (2026-07-13)

Pull the per-category "collect entries → fingerprint → build body → unchanged-check →
write" block out of `regenerate_maps` into a helper both it and `migrate_memory` call
(with optional pre-read `(old_meta, old_body)` so `regenerate_maps` doesn't parse
twice). Pure mechanical move; fold logic stays only in `regenerate_maps`.

### H3. `[x]` CLI + contracts — DONE (2026-07-13)

`ai-memory migrate [--dry-run] [--section <name>]... [--no-llm]` — CLI-only like
`install` (one-shot, human-supervised; also keeps `server.py`, already over the size
bar, untouched). `MigrateResult`/`MigrateSectionPlan`/`MigrateEntryPlan` TypedDicts in
`contracts.py` (total — no `NotRequired`, so the FastMCP null-vs-omitted trap can't
apply even if this ever becomes a tool).

### H4. `[x]` `init` pre-scaffolds store categories — DONE (2026-07-13)

Map categories derived from `SECTION_TEMPLATES` `generated_from` (architecture,
decisions, schemas, debt) + `episodic`, `failures`, `rules`, each with `.gitkeep`.
Empty dirs are invisible to `regenerate_maps` (`_category_entries` returns `[]` →
starter map left alone), so no behavior change until first write.

### H5. `[x]` CHANGELOG.md + migration guide — DONE (2026-07-13)

keep-a-changelog; backfill 0.4.1→0.7.3 from tags; `[Unreleased]` documents migrate +
init scaffolding + the store-first migration guide (ROADMAP 4.2's requirement). No
version bump in this session — tagging stays a separate, owner-driven step.

### H6. `[x]` Tests — DONE (2026-07-13; 288 total, was 264)

Heuristic split (fences, preamble, empty headings, slug collisions); dry-run writes
nothing; snapshot created on apply; rollback restores the pre-migration body; LLM
naming path with mocked `call_llm` (and its fallback on garbage JSON); steering/
generated/index files untouched; re-run is a no-op; secrets in a legacy section are
redacted in the store entries; init scaffolding present on fresh init.

### H7. `[x]` Dogfood on this repo + record before/after eval — DONE (2026-07-13)

`ai-memory eval` → `migrate --dry-run` (review) → `migrate` → `dream --apply` (refresh
indexes) → `eval`; record both scores in the CHANGELOG migration guide as the
reference case. Also closes §2.1 Q8's last sub-item (commit the untracked dogfood
store entries).

---

## Milestone E — Retrieval quality (post-launch, iterate with users)

Keep the invariant: **zero required dependencies; every new capability degrades gracefully.**

- E1. `[ ]` **Temporal facts.** Optional frontmatter `valid_from`, `superseded_by`.
  Dreaming marks contradicted facts superseded (never silent-delete). `read_combined_context`
  filters superseded by default; `include_history=true` to see evolution.
- E2. `[ ]` **Link graph.** Parse `[[wiki-links]]` in memory bodies; Dreaming maintains a
  generated `links.md` index; retrieval pulls 1-hop neighbors of top-scoring sections when
  budget allows.
- E3. `[ ]` **Optional local embeddings.** New extra `memory-fabric[semantic]`
  (fastembed ONNX + sqlite-vec). Index lives in `.ai-memory/cache/` (gitignored). Score
  blend: BM25 + cosine + priority + recency. Absent extra → current behavior, zero cloud calls.
- E4. `[ ]` **Lifecycle metadata.** `source_session`, access counts, staleness score;
  `dream --mode deep` proposes demotions for stale/unused memories.
- E5. `[ ]` **Perf gate in CI.** Generate a 500-file store fixture; assert
  `read_combined_context` p95 < 150 ms (skip on slow CI runners if flaky, keep locally).

Each E-task: implement → tests → one README paragraph → minor version bump.

## Milestone F — Prove it (benchmarks)

- F1. `[ ]` `ai-memory bench` subcommand: reproducible harness, JSON + markdown reports
  (reuse the eval report plumbing).
- F2. `[ ]` LongMemEval-S adapter: ingest sessions → memory writes; answer questions →
  retrieval + configured LLM. Publish score + exact reproduction script in `benchmarks/`.
  Then LoCoMo. Honest framing: these are conversational benchmarks, we're a project-memory
  system — publish numbers anyway.
- F3. `[ ]` **Own benchmark: `coding-memory-bench`** (separate repo). N repos × M sessions;
  later tasks depend on earlier decisions ("which auth approach did we choose and why?").
  Score agent-with-memory vs agent-without. This defines the category we claim to lead.
- F4. `[ ]` Results table + reproduction commands in README.

## Milestone G — Launch

- G1. `[ ]` Docs site: mkdocs-material, GitHub Pages. Pages: Quickstart-per-client,
  Concepts (tiers/dreaming/store), MCP tool reference, Benchmarks, FAQ.
- G2. `[ ]` 90-second demo GIF/video: `ai-memory init` → agent saves a decision in Claude
  Code → same memory answers a question in VS Code and Codex. Cross-tool is the money shot.
- G3. `[ ]` Community files: CONTRIBUTING.md, CHANGELOG.md (keep-a-changelog), issue/PR
  templates, `v1.0.0` tag when A–D are done.
- G4. `[ ]` Announce: Show HN, r/ClaudeAI, r/cursor, X thread, awesome-mcp-servers PRs.
  State the guarantee everywhere: **no telemetry, no account, no cloud, your files.**

---

## Session cadence (suggested)

| Session | Do |
|---|---|
| 1 | A1 + A2 (CI green, lint clean) |
| 2 | A3 + A4 + A5 + A6 → **v0.4.0 on PyPI** |
| 3–5 | B1 (one or two module extractions per session) + B2 |
| 6–7 | ~~C1 + C2 + C3 (install engine + 3 first clients) then remaining clients + C4 + C5~~ — done in one session instead of two (2026-07-05); all 9 clients + tests + docs landed together, including the live-machine acceptance run (see C5) — `uv` installed via scoop, then `ai-memory install --client all` run for real, all 8 detected clients succeeded. Still need a version bump + tag for **v0.5.0** — not done yet, deliberately left as a separate release step rather than bundled into this session. |
| 8 | ~~D1 registry + D2 badges~~ — D1 + D2 + D3 (MCPB, stretch) all landed together
(2026-07-05), plus an unplanned CI hotfix found while starting D (see Milestone D).
Still need version bumps + tags for **v0.5.0** (Milestone C, still pending from
session 6–7) and **v0.6.0** (Milestone D) — deliberately left as separate release
steps, same as before. G3 + G2 + G4 launch window still ahead. |
| 9+ | E and F tracks, ordered by user feedback |

## Decisions log

- **Zero required deps stays.** Anything new is stdlib or an optional extra (`[mcp]`,
  `[semantic]`, `[test]`). TOML writes are done by append, not by adding a TOML writer.
- **`uvx` is the canonical install vector** in all generated configs; `pipx`/abs-path fallback when `uv` missing.
- **Config writers never destroy user data**: parse-failure → backup + abort; merge, never overwrite.
- **Windows is the primary dev/test OS** (this machine); CI matrix covers Linux/macOS.
- **Benchmarks framing**: honest on conversational benchmarks, category-defining on our own.
