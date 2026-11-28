# Field report on recall in Memory Fabric 1.4.6

A task-context request for an invented identifier delivered 3 to 6 stored notes in each of three populated workspaces. Keyword search returned zero hits in all three. On two known-fix questions in the largest store, both interfaces missed the selected target. These are distinct failures for a coding agent. One supplies irrelevant context, while the other hides a potentially useful lead.

## Installation and sample

The November 27, 2026 audit found 13 sibling workspaces with Memory Fabric, including a linked worktree. Eleven had granular entries. The three probe stores below are distinct workspaces. Sizes count store entries as of the probe. The historical diary covered nine workspaces from August 22 through November 26. The cutoff excludes this audit's requests.

| Workspace | Entries | Version verification on the local Windows host |
| --- | ---: | --- |
| Small | 6 | Probed through the audited Codex MCP configuration. Its CLI and editor installations were outside the version check. |
| Medium | 111 | Both CLI executables on PATH returned 1.4.6. The servers selected by the user-level Cursor and VS Code configurations returned 1.4.6 at MCP initialization. |
| Large | 495 | Both CLI executables on PATH and the project virtual environment returned 1.4.6. The workspace MCP configurations selected that environment's executable, which reported 1.4.6 at initialization. |

The Codex user configuration pinned 1.4.6. A fresh initialization with that configuration returned `serverInfo.version` 1.4.6. Historical diary rows had an unknown client label in the medium and large workspaces, so editor attribution is unavailable. No remote host was measured in this November sample.

## Historical use

Across all nine workspaces, the diary contained 3,078 tool calls and 443 search events. One workspace contributed 417 of the searches across versions. The table uses only 1.4.6 events. All 87 searches in that cohort used the index. A search event can come from any instrumented caller, so it has a different denominator from direct MCP tool calls.

| 1.4.6 diary measure | Medium | Large | All participating workspaces |
| --- | ---: | ---: | ---: |
| Direct MCP tool calls | 255 | 339 | — |
| Direct keyword search calls | 7 | 64 | — |
| Direct task-context calls | 1 | 0 | — |
| Indexed searches | 20 | 64 | 87 |
| Searches with at least one hit | 20 | 63 | 83 |
| Search p95, nearest rank | 353 ms | 1,997 ms | 1,915 ms |

In the large workspace, 63 of 67 searches on 1.4.2 returned zero hits. On 1.4.6, 1 of 64 did. The versions saw different queries. These counts establish exposure to each version and how often a result appeared. Answer correctness requires a labeled target or inspection of the delivered passage.

## Controlled probes

Each store received two questions based on known entries and the same invented identifier. Keyword search used a top five. Task retrieval used its default limit of eight entries and a 4,000-token budget. Counts below come from section markers in the returned text. Token estimates include steering.

| Store | Known-item probes | Keyword hits for invented ID | Store entries delivered for invented ID | Total estimated tokens |
| --- | --- | ---: | ---: | ---: |
| Small | Both targets first in search and first among delivered store entries | 0 | 6 | 3,892 |
| Medium | Both targets first on both surfaces | 0 | 3 | 3,855 |
| Large | Neither target appeared in the first five search hits or in the delivered text | 0 | 5 | 3,905 |

The medium response listed four store entries as included while its text contained three. Both targets missed in the large store were directly readable, marked stale, and had no recorded successor. Their current validity was unknown. A source-labeled historical lead would let an agent check either fix before reusing it.

A second negative control asked about porcelain firing in English and Portuguese. All six task packs included store entries, and none contained the distinctive subject words for its question. English keyword search returned zero, three, and five hits in the small, medium, and large stores. Portuguese keyword search returned zero in each. This tests the harder case where an ordinary question shares incidental words with a project.

## How to reproduce

1. From the workspace being tested, run `ai-memory --version`. Record the resolved CLI path and check the workspace virtual environment separately if present. Read the client's effective MCP launch configuration, start that command, and record the engine version from the MCP `initialize` response. For historical counts, group the diary's `fabric_version` field by workspace and date.
2. For the usage table, filter diary events to August 22 through November 26 inclusive using the recorded local date. Count `tool.call` by name. Count `search.run` by workspace, `fabric_version`, and backend. A hit means `hit_n > 0`. For p95, sort the observed `ms` values and take the value at one-based position `ceil(0.95 × N)`. Pool individual events to calculate the all-workspace column.
3. Choose two existing entries and record their store paths as the expected targets before running any query. Ask one natural-language question per entry. Also run an invented identifier and a natural-language question outside the project domain. For counts independent of audit traffic, end the diary window before the probe date.
4. Run the paired commands below from a workspace with existing notes. Compare the top five search hits with the section markers and evidence passage in the task response's `text`. Compare those markers with `included_sections`. Keep raw project responses local.

```sh
ai-memory --json query qzxvplmoknundecidedxyz --max-results 5
ai-memory --json retrieve qzxvplmoknundecidedxyz --max-tokens 4000
ai-memory --json query "Which kiln temperature was approved for porcelain glazing?" --max-results 5
ai-memory --json retrieve "Which kiln temperature was approved for porcelain glazing?" --max-tokens 4000
ai-memory --json query "Qual temperatura foi aprovada para a queima de porcelana?" --max-results 5
ai-memory --json retrieve "Qual temperatura foi aprovada para a queima de porcelana?" --max-tokens 4000
```

On the 1.4.6 checkout, the four built-in benchmark tasks passed with memory-on recall 1.00 and memory-off recall 0.00. The benchmark unions search paths with the pack's inclusion list. The task packer can retain zero-score entries and can drop a final fragment after recording its inclusion. The diary analyzer also treats an indexed candidate count of at least 200 as a capped scan. In the 1.4.6 cohort, 64 indexed searches met that count. These observations motivate independent checks of evidence, reporting, and latency. [Benchmark scorer](../src/memory_fabric/eval/bench.py) · [Task packer](../src/memory_fabric/storage/retrieve.py) · [Diary analyzer](../src/memory_fabric/diary/analyze.py) · [Implementation checklist](recall-implementation.md)
