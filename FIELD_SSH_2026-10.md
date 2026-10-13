# SSH field check — 2026-10-13

Live check of the installs Cursor actually runs on a remote SSH host for two
field workspaces (**workspace A**, **workspace B**). Probes used
`MEMORY_FABRIC_DIARY=0` so they did not append diary events.

The token-search change in this working tree is **not** what those sessions
run. Both SSH workspaces were still on a phrase-only `keyword_search`.

## Installs

| Binary | Version | Role |
|---|---|---|
| `~/.local/share/pipx/venvs/memory-fabric/bin/memory-fabric-mcp` | 1.4.2 (Python 3.11) | Cursor MCP for both workspaces |
| workspace A `./env/bin/ai-memory` | 1.4.2 | Project venv |
| workspace B `./env/bin/ai-memory` | **1.2.2** | Project venv. A shell in this env is not the server Cursor calls. |

Neither workspace has `.cursor/hooks.json`. The host has no `rg`, so search uses
the Python backend. MCP `serverInfo.version` reported `1.30.0` (the SDK), not
fabric `1.4.2`.

## What worked

MCP stdio (`2024-11-05`) listed 21 tools. Expected tools were all present.

| Call | Result |
|---|---|
| `list_memory_store_tool` (prefix `frontend`, max 3) | 8 ms, `isError` false, 3 entries |
| `context_for_task_tool` | 60 ms, `isError` false |
| `ai-memory status`, `doctor` | exit 0, doctor `ok`, 0 errors |
| `ai-memory retrieve` on the sentence queries below | found the store file |

`ai-memory retrieve` / `context_for_task_tool` for the two sentences:

- workspace A, sentence query A — included `store/frontend/example-section` (4 store sections, 1199/1200 tokens, 323 ms).
- workspace B, sentence query B — included `store/glossary/example-term` (1 store section, 1148/1200 tokens, 371 ms).

## What failed

`keyword_search_tool` and `ai-memory query` returned **hit_n 0** for those same
sentences on pipx 1.4.2 and on both project venvs (MCP search 15 ms,
`isError` false). Single-word queries hit (`acesso`, `envelope`), and 1.4.2
repeated the same file once per matching line (five identical
`store:frontend/secoes-por-local-da-tiles` hits for `acesso`).

Doctor warnings, all “missing from the generated index”, no errors:

| Workspace | Warnings | Store files in status | Notes |
|---|---|---|---|
| A | 45 | 128 section files | Index lags files through 2026-10-07. `domain` section missing from `index.md`. |
| B | 68 | 265 section files | Index lags files through 2026-10-13. `features` section missing from `index.md`. |

`ai-memory eval --no-save` does **not** catch the sentence-search miss.

| Workspace | Score | Status | Time | Failures that matter |
|---|---|---|---|---|
| A | 95 | pass | 0.4 s | `ubiquitous-language_placeholder`. One broken evidence citation. One secret-like flag. `retrieval_quality` 100. |
| B | 78 | warn | 0.5 s | `retrieval_quality` **0** because `index.md` ships too many contradiction strings (`contradiction_pack_hygiene`). Three stale root maps (`architecture`, `frontend`, `rules`). Six broken evidence citations. 156 metadata warnings. |

## Future improvement

Already in this working tree, not installed on the SSH host:

- Token `keyword_search` (content words, accent folding, phrase boost, one hit per file).
- Diary counts on `search.run` (`token_n`, `content_token_n`, `candidate_n`, `phrase_hit`).
- `journal.written` instead of a fake `checkpoint.session_end`.
- Tool `error_code` for `cannot append` and `cwd does not exist`.
- Doctor warns when `.cursor/hooks.json` is absent. It does not install the file.

Ship and re-check on the host:

- Upgrade the pipx install and the workspace B venv off 1.2.2 to a release that contains the token search.
- Run `ai-memory install --client cursor --with-hooks` in both workspaces.
- Re-run the two sentence queries. They must return the store paths above, once each.
- Rebuild stale indexes (`ai-memory dream --mode light --apply`) so doctor’s “missing from index” pile drops. If a dream does not trim workspace B’s contradiction pack under the eval cap, that cap is not applied on rebuild.

Still open in the product:

- Eval passes while sentence search returns nothing. Add a `keyword_search` case whose query is a sentence, not a single token, and fail `retrieval_quality` when hit_n is 0.
- MCP `serverInfo.version` should be the fabric version, not the MCP SDK version.
- Query packs still slice large files (`file_share_capped` on 54 of 65 diary packs in the earlier diary read). Left out of the token-search change on purpose.
- High-priority omission on large stores (the 50% inflation warning never fired at 23–28% high). Same deferral.
