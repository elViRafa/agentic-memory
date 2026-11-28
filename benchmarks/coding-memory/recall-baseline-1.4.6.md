# Recall benchmark baseline for Memory Fabric 1.4.6

Measured on November 27, 2026 with Windows and Python 3.14.0. Both the
workspace virtual environment's `ai-memory --version` and the benchmark's
`engine_version` reported **1.4.6**. Before the benchmark edits, the checkout's
engine source matched tag `v1.4.6` at `fa7dd184`. An isolated copy of the tag
with the benchmark changes applied reproduced the per-case results. The runs
used an empty `MEMORY_FABRIC_HOME`, `MEMORY_FABRIC_SEMANTIC=0`, and the default
per-file share cap.

```sh
ai-memory --version
ai-memory bench --fixture builtin --json
ai-memory bench --fixture recall --json
```

Both fixtures used `--k 5` and the default 4,000-token task budget unless
specified below. All memory-off packs delivered zero evidence fragments.

## Original fixture

**4 of 4 passed** on both memory-on surfaces. Legacy memory-on recall was 1.00,
memory-off recall was 0.00, and the command exited with code 0.

| Case | First correct search rank | Recall@5 | Delivered answer |
| --- | ---: | ---: | --- |
| `tot-local-columns` | 1 | 1.00 | Pass |
| `test-file-naming` | 1 | 1.00 | Pass |
| `no-drf` | 1 | 1.00 | Pass |
| `urnas-reversal` | 1 | 1.00 | Pass |

## Synthetic recall fixture

**2 of 10 passed** overall. Keyword recall at five was **2/5 (0.40)** across
cases with keyword-search targets. The open-file case has a task-context
target and expects zero keyword hits. The command exited with code 1.

| Case | First correct search rank | Recall@5 | Keyword hits | Evidence fragments | Failed checks |
| --- | ---: | ---: | ---: | ---: | --- |
| `current-decision` | 1 | 1.00 | 2 | 5 | — |
| `open-file-failure` | — | — | 0 | 5 | — |
| `stale-relay-fix` | — | 0.00 | 0 | 5 | Search and delivered evidence |
| `stale-cache-fix` | — | 0.00 | 0 | 5 | Search and delivered evidence |
| `closed-predecessor` | — | 0.00 | 1 | 5 | Search |
| `late-section` | 1 | 1.00 | 1 | 5 | Delivered evidence |
| `invented-identifier` | — | — | 0 | 5 | Delivered evidence |
| `incidental-overlap-en` | — | — | 1 | 5 | Search and delivered evidence |
| `incidental-overlap-pt` | — | — | 1 | 5 | Search and delivered evidence |
| `inclusion-at-budget` | — | — | 0 | 0 | Inclusion agreement |

- Removing `src/frame_reader.py` from the open-file probe dropped the expected
  failure from the rendered pack for that query.
- Search returned the closed predecessor as a successor pointer. The task pack
  delivered the expected phrase from the current successor.
- The 1,200-token late-section pack rendered the runbook's source marker but
  clipped the section containing the answer.
- The 320-token inclusion probe rendered only steering.
  `included_sections` also listed `store/decisions/arquivo-anterior`.
