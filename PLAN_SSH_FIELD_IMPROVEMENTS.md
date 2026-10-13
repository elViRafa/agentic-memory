# Plan: improvements from the SSH field stores

Source measurements: [FIELD_SSH_2026-10.md](FIELD_SSH_2026-10.md).
Build this list in later sessions. Order is the order that changes the next
diary read on the remote SSH host.

Two SSH field workspaces (**A** and **B**). Cursor there calls pipx
`memory-fabric-mcp` **1.4.2**. Workspace B’s project virtualenv is still
**1.2.2**. Sentence `keyword_search` returned 0 hits.
`context_for_task` found the file. Eval scored 95 pass on that store.

Verified against this working tree on 2026-10-13. Each item below is what
that tree does today, then the change. Fixtures stay synthetic: do not copy
the Portuguese sentences from the field note into tests or eval.

## 0. Release what is already in this tree

Status: written, not installed. `memory_fabric.version.__version__` is still
`1.4.2`, so a host install of this tree would look identical to the build
that missed the sentences.

Already in the tree, listed under `[Unreleased]` in `CHANGELOG.md`:

- Token `keyword_search` in `src/memory_fabric/storage/search.py`. Covered by
  `TokenSearchTests` in `tests/test_retrieval.py` (sentence, single token,
  stopwords, phrase boost, accent folding, ripgrep token OR).
- Diary `search.run` counts: `token_n`, `content_token_n`, `candidate_n`,
  `phrase_hit`.
- `journal.written` from the journal writer. `checkpoint.session_end` stays
  on the stop hook (`guard_journal` in `src/memory_fabric/storage/capture.py`).
- Tool `error_code` for `cannot append` and `cwd does not exist`.
- Doctor warns when `.cursor/hooks.json` is absent
  (`_check_cursor_session_hooks` in `src/memory_fabric/storage/lifecycle.py`)
  and does not install it.

Build: cut a version above 1.4.2 before the host upgrade. Move the
Unreleased notes under that version. Install that build into pipx and into
both workspaces’ `./env` (workspace B is still on 1.2.2; workspace A is
already 1.4.2 and needs the same upgrade).

Acceptance: `ai-memory --version` on pipx and on both project venvs prints
the new version. Re-run the two sentence queries in FIELD_SSH_2026-10.md.
Each returns one hit, the store path recorded there.

## 1. Eval fails a sentence search miss

Status: search is tested; eval is not.

`_evaluate_retrieval_quality` in `src/memory_fabric/eval/memory_quality.py`
calls `keyword_search` only for cases in `.ai-memory/evals/retrieval.yaml`
(or `.json`) that are not pack cases. A store with no fixture file passes
`retrieval_fixtures_absent`. That is why workspace A scored
`retrieval_quality` 100 while sentence search returned nothing. Adding a
yaml only in this repo would leave the SSH eval green.

Build: inside `_evaluate_retrieval_quality`, always run one probe that does
not read the project's fixture file.

- Choose one store file whose body has two content tokens that are not
  adjacent (the field shape: words on separate lines, no phrase to match).
- Query is a short sentence that contains those tokens plus stopwords.
- Fail a `retrieval_quality` check when `keyword_search` does not return
  that store path.
- When no file has two non-adjacent content tokens, record a pass. Tiny
  stores stay green.
- Leave the fixture-file cases as they are. The single-token search test
  stays, and it is not this probe.

Tests, in the eval suite:

- A store with `dashboard` and `zones` on separate lines passes under the
  current token search.
- The same store fails the check when `keyword_search` is stubbed to return
  no hits. That is the field miss, without reverting search.

Acceptance: `ai-memory eval` on a store shaped like the field miss fails
`retrieval_quality` when search cannot see content words. The current
token-search implementation passes that store.

## 2. Sentence queries reach the search this version actually runs

Status: not started. Do this in the same release as item 0.

`MEMORY_INSTRUCTIONS`, `THIN_CURSOR_RULE`, and `build_agent_router_skill` in
`src/memory_fabric/templates.py` name `keyword_search_tool` first. Agents
followed that, and on installed 1.4.2 the sentence missed. This tree's
search matches content words, so the instructions that ship with it keep
search first.

Build: in those three templates, state that a sentence is a normal
`keyword_search_tool` query (content words, one hit per file) and that
`context_for_task_tool` is the call that packs a file into a token budget.
Generated copies (`AGENTS.md`, `.cursor/rules/memory-fabric.mdc`,
`.agents/skills/agent-router/SKILL.md`) come from `ai-memory init` /
`sync-agents`. Edit the templates, then regenerate.

Acceptance: a fresh `init` / `sync-agents` from this version writes
instructions that tell a sentence query to use `keyword_search_tool`. The
text matches `keyword_search` in the same version.

## 3. MCP serverInfo is the fabric version

Status: not started.

`ai-memory --version` prints `memory_fabric.version.__version__`
(`src/memory_fabric/cli.py`). `FastMCP("Memory Fabric")` in
`src/memory_fabric/server.py` passes no version, so initialize reports the
MCP SDK version. The live handshake said `1.30.0`. The dependency is
`mcp>=1.0.0,<2`.

Build: pass `version=__version__` into `FastMCP`. If the installed SDK
rejects that keyword, set the version on the low-level server object before
`run`, so initialize still reports the fabric version.

Acceptance: an initialize response reports the same version as
`ai-memory --version`.

## 4. Startup maps keep up with the store

Status: not started. The count cap is already in dream; the eval token cap
and the doctor noise are not.

Doctor (`run_doctor` in `src/memory_fabric/storage/lifecycle.py`) appends one
warning per missing path: local sections around the `index.md` scan, store
files in the `memory-store/index.md` scan. The field run was 45 and 68 of
those lines. `_check_weak_store_summaries` already collapses after five
samples. The index warnings do not.

Cursor hooks today (`_build_cursor_managed_hooks` in
`src/memory_fabric/client_hooks.py`):

- `sessionStart` → `session-start`
- `stop` → `guard-journal` (session end, `journaled: false` when nothing
  was journaled)
- `preCompact` → `dream --mode light --apply`

`preCompact` does not run every session, so the index stays behind. A light
dream already calls `pack_contradiction_messages` (`_PACK_MAX = 5` in
`src/memory_fabric/storage/contradictions.py`, applied from
`src/memory_fabric/storage/finalize.py`). Eval
`_contradiction_pack_hygiene_checks` fails when `index.md` has more than 8
strings **or** more than about 150 tokens. Five long strings still fail.
That token mass is why workspace B's `retrieval_quality` was 0.
`_dream_cooldown_reason` skips a light apply when the store fingerprint is
unchanged. The fingerprint hashes store bodies and skips `index.md`, so a
stale index looks unchanged and the rebuild is the thing that gets skipped.

Build:

- One doctor warning per index (local, store) with the missing count and up
  to five sample paths.
- `stop` still runs `guard-journal`. When store paths are missing from
  `memory-store/index.md`, it also runs a light dream. That run rebuilds
  the index even if the cooldown would skip an unchanged store.
- `pack_contradiction_messages` keeps the pack under both eval limits:
  at most 5 entries and at most 150 estimated tokens. Drop or shorten
  strings until both hold. Full hits stay in `evals/contradictions.json`.

Tests:

- Doctor on a store with many unindexed files emits one missing-index
  warning that contains the count, not one line per file.
- A light dream whose pack strings are long enough to exceed 150 tokens
  leaves `contradiction_pack_hygiene` passing.
- A stop-hook command list still contains `guard-journal`, and contains the
  light dream when the index is behind.

Acceptance: after new store writes and a stop-hook dream, doctor does not
list dozens of missing index paths. Eval `contradiction_pack_hygiene` passes
on a store whose `index.md` previously shipped a long contradiction pack.

## 5. Real session boundaries on the SSH projects

Status: the doctor warning is in this tree. Hooks are not installed on the
host. No further product change.

Both projects have `AGENTS.md` and no `.cursor/hooks.json`. Session start
was recorded 0 times. Every session end was a journal write. Client was
always `unknown`.

Build: after item 0 is installed, run
`ai-memory install --client cursor --with-hooks` in both SSH projects.

Acceptance: the next diary contains `checkpoint.session_start`, a client
other than `unknown`, and `checkpoint.session_end` only from the stop hook.
A session that never journaled shows `journaled: false`.

## 6. Query packs stop spending the budget on one file

Status: not started. Do this after item 0 is on the host.

`_FILE_SHARE_CAP_DEFAULT` in `src/memory_fabric/storage/context.py` is 0.25.
`_pack_sections` applies it to every file. A query lowers that cap only for
`classify_role(key) == "map"` (`MAP_QUERY_CAP_TOKENS` is 120). An episodic
journal and a frontend note still get a quarter of the budget.
`test_file_share_cap_stops_one_journal_monopolizing` checks that a giant
journal leaves room for two architecture files on a 2000-token pack. It
does not check the quarter.

`high_priority_inflation` in `src/memory_fabric/storage/hygiene.py` warns
when at least 8 files are high and high is at least half the store.
Doctor and eval both call it. The field stores were 23–28% high, so the
warning never fired, while high sections were omitted more often than they
were included. Across 65 context packs, one exceeded the 4000-token budget
and `file_share_capped` fired on 54.

Build:

- On a query pack, an `episodic` file and a single large non-map note get a
  share below a quarter of the budget. A 10k-token journal then stays under
  1000 tokens of a 4000-token pack. Startup packs (no query) keep the
  current cap.
- Keep the 50% inflation check. Add an absolute count next to
  `HIGH_PRIORITY_WARN_MIN_FILES`, high enough that a store under 8 files
  stays quiet, and low enough that 23% of a 128-file store warns. Doctor
  and eval share that helper.

Tests, beside the existing journal test:

- A query pack of many medium high notes includes more than a handful.
- A query pack whose journal is about 10k tokens gives that journal less
  than a quarter of the budget, and `estimated_tokens` stays within
  `token_budget`.
- Doctor warns on a store at the field ratio and stays quiet on a small
  store with a few high files.

Acceptance: those three tests pass.

## 7. One CLI version per machine

Status: not started.

`_check_install_drift` compares the directory of `ai-memory` on `PATH` with
the directory of the running interpreter. It does not read versions, and it
does not look at `./env/bin/ai-memory` or the MCP command. A project venv
at 1.2.2 writes older files next to the pipx 1.4.2 server.

Build: when doctor runs, compare versions of:

- the `ai-memory` implementing this doctor (`__version__`)
- `ai-memory` on `PATH`, when it exists
- `./env/bin/ai-memory` (and `./.venv/bin/ai-memory` if that is the one
  present)
- the `memory-fabric-mcp` command named in `.cursor/mcp.json`, when the
  command is that binary

If any of those versions is older than the doctor, one warning names each
version. Resolve only binaries named `ai-memory` or `memory-fabric-mcp`.

Acceptance: doctor on a tree whose `./env/bin/ai-memory` is 1.2.2 and whose
MCP server is 1.4.2 names both versions in one warning.

## Session order

1. Item 0. Bump the version, then upgrade pipx and both SSH venvs.
2. Items 1 and 3. Eval sentence probe and MCP version. Small, testable,
   independent of the host.
3. Item 2 in the same release as item 0, so the generated instructions
   describe the search that release runs.
4. Item 5 on the host, then item 4 (hooks installed, then index rebuild on
   stop).
5. Items 6 and 7 after the next diary shows sentence search returning hits.
