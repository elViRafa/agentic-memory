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

### C1. `[ ]` Client registry module

New `src/memory_fabric/clients.py`: one declarative entry per client.

```python
@dataclass(frozen=True)
class ClientSpec:
    name: str                      # "vscode", "codex", ...
    config_path: Callable[[], Path]   # resolves per-OS location
    fmt: Literal["json", "toml"]
    root_key: str                  # "mcpServers" | "servers" | "mcp_servers"
    scope: Literal["global", "project"]
    entry: dict                    # the server block to insert
```

Canonical server entry (same everywhere):
`command: "uvx"`, `args: ["--from", "memory-fabric[mcp]", "memory-fabric-mcp"]`,
with a `pipx`/absolute-path fallback variant when `uv` is not on PATH (detect via `shutil.which`).

### C2. `[ ]` Config paths per client (verify each on first implementation)

| Client | Path | Notes |
|---|---|---|
| claude-code | project `.mcp.json`, or shell out to `claude mcp add memory-fabric -- uvx --from "memory-fabric[mcp]" memory-fabric-mcp` | prefer CLI when `claude` on PATH |
| claude-desktop | Win: `%APPDATA%\Claude\claude_desktop_config.json` · macOS: `~/Library/Application Support/Claude/claude_desktop_config.json` · Linux: `~/.config/Claude/claude_desktop_config.json` | key `mcpServers` |
| vscode | project `.vscode/mcp.json` (key `servers`, add `"type": "stdio"`); user scope via `code --add-mcp '<json>'` if available | Copilot agent mode |
| cursor | project `.cursor/mcp.json` or `~/.cursor/mcp.json` | key `mcpServers` |
| windsurf | `~/.codeium/windsurf/mcp_config.json` | key `mcpServers` |
| codex | `~/.codex/config.toml`, table `[mcp_servers.memory-fabric]`; project scope `.codex/config.toml` | TOML |
| antigravity | `~/.gemini/config/mcp_config.json` (Antigravity 2.0 IDE/CLI + Gemini CLI shared central config) | key `mcpServers` |
| gemini-cli | same central config; legacy fallback `~/.gemini/settings.json` `mcpServers` | detect which exists |
| cline | VS Code globalStorage `saoudrizwan.claude-dev/settings/cline_mcp_settings.json` (per-OS base) | key `mcpServers` |

### C3. `[ ]` Safe write engine

- JSON: parse → deep-merge only our key → write back preserving other entries.
  Never truncate on parse failure: back up the original to `<file>.bak-<ts>` first, abort with a clear message.
- TOML (Codex): read with stdlib `tomllib` to check existence; if absent, **append** a
  `[mcp_servers.memory-fabric]` text block at EOF (append preserves user formatting; no
  TOML-writer dependency — keeps `dependencies = []`).
- Flags: `--dry-run` (print unified diff, write nothing), `--uninstall` (remove our
  entry only), `--client all` (detect installed clients by config-dir existence and do each).

### C4. `[ ]` Tests

Temp-dir + monkeypatched `HOME`/`APPDATA` for every client spec: fresh install, second
run idempotent, merge with pre-existing user servers, uninstall leaves others intact,
malformed existing JSON → abort + `.bak` file created, TOML append + idempotence.

### C5. `[ ]` Wire into CLI + docs

`cli.py`: `ai-memory install --client <name|all> [--project] [--dry-run] [--uninstall]`.
README: replace the manual MCP JSON section with the per-client matrix (one command each).

Acceptance: on this Windows machine, run `ai-memory install --client all`; every client
you have installed (at minimum Claude Code, VS Code, Antigravity, Codex if present) lists
memory-fabric tools after restart.

---

## Milestone D — Registry, badges, one-click bundles

### D1. `[ ]` Official MCP Registry

1. Add the ownership marker to the PyPI package: line `mcp-name: io.github.elvirafa/memory-fabric`
   in README.md (registry validates PyPI ownership by finding this string on the PyPI page).
2. `mcp-publisher init` → craft `server.json` (name `io.github.elvirafa/memory-fabric`,
   package registry `pypi`, identifier `memory-fabric`, transport stdio).
3. `mcp-publisher login github` → `mcp-publisher publish`.
4. Append a registry-publish step to `release.yml` so every tag republishes the new version.

Acceptance: server visible at registry.modelcontextprotocol.io; appears in VS Code's MCP
server browsing and on Glama/PulseMCP within days (they index the registry).

### D2. `[ ]` One-click install badges in README

- VS Code: `vscode:mcp/install?<url-encoded server JSON>` badge (+ `vscode-insiders:` variant).
- Cursor: `cursor://anysphere.cursor-deeplink/mcp/install?name=memory-fabric&config=<base64>` badge.

Acceptance: clicking each badge on a machine with that editor opens its install flow.

### D3. `[ ]` MCPB bundle for Claude Desktop (stretch)

- `npx @anthropic-ai/mcpb init` → `manifest.json` (python server type; bundle deps per MCPB docs).
- Build `.mcpb` in `release.yml`, attach to the GitHub Release.
- Caution: Python-in-MCPB needs bundled deps/runtime testing on Win + macOS before advertising it.

Acceptance: drag-drop `.mcpb` into Claude Desktop → extension installs → memory tools available.

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
| 6 | C1 + C2 + C3 (install engine + 3 first clients: claude-code, vscode, antigravity) |
| 7 | C2/C3 remaining clients + C4 tests + C5 docs → **v0.5.0** |
| 8 | D1 registry + D2 badges → **v0.6.0**, then G3 + G2 + G4 = launch window |
| 9+ | E and F tracks, ordered by user feedback |

## Decisions log

- **Zero required deps stays.** Anything new is stdlib or an optional extra (`[mcp]`,
  `[semantic]`, `[test]`). TOML writes are done by append, not by adding a TOML writer.
- **`uvx` is the canonical install vector** in all generated configs; `pipx`/abs-path fallback when `uv` missing.
- **Config writers never destroy user data**: parse-failure → backup + abort; merge, never overwrite.
- **Windows is the primary dev/test OS** (this machine); CI matrix covers Linux/macOS.
- **Benchmarks framing**: honest on conversational benchmarks, category-defining on our own.
