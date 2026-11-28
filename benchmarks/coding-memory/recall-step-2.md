# Recall results after step 2

Measured on November 27, 2026, on Windows with Python 3.14.0 and the
workspace's editable installation. The build still reports 1.4.6. Both
commands used an empty `MEMORY_FABRIC_HOME`, the default per-file share cap,
and no embedding backend installed. Semantic lifecycle checks ran separately
with the CI embedder injected. [Released 1.4.6 baseline](recall-baseline-1.4.6.md)

```sh
ai-memory bench
ai-memory bench --fixture recall
```

Both commands exited with code 0. The original fixture held at 4/4. The recall
fixture rose from 2/10 to 10/10, and search recall at five rose from 2/5 to 5/5
across the cases with search targets. All memory-off packs delivered zero
evidence fragments.

## Original fixture

| Case | 1.4.6 → Step 2 first correct search rank | 1.4.6 → Step 2 delivered answer | Step 2 status |
| --- | --- | --- | --- |
| `tot-local-columns` | 1 → 1 | Pass → Pass | `matched` |
| `test-file-naming` | 1 → 1 | Pass → Pass | `matched` |
| `no-drf` | 1 → 1 | Pass → Pass | `matched` |
| `urnas-reversal` | 1 → 1 | Pass → Pass | `matched` |

## Synthetic recall fixture

| Case | 1.4.6 → Step 2 first correct search rank | 1.4.6 → Step 2 search hits | 1.4.6 → Step 2 delivered evidence fragments | Step 2 status | 1.4.6 → Step 2 case |
| --- | --- | --- | --- | --- | --- |
| `current-decision` | 1 → 1 | 2 → 1 | 5 → 1 | `matched` | Pass → Pass |
| `open-file-failure` | — | 0 → 0 | 5 → 1 | `matched` | Pass → Pass |
| `stale-relay-fix` | — → 1 | 0 → 1 | 5 → 1 | `historical_only` | Fail → Pass |
| `stale-cache-fix` | — → 1 | 0 → 1 | 5 → 1 | `historical_only` | Fail → Pass |
| `closed-predecessor` | — → 1 | 1 → 2 | 5 → 2 | `matched` | Fail → Pass |
| `late-section` | 1 → 1 | 1 → 1 | 5 → 1 | `matched` | Fail → Pass |
| `invented-identifier` | — | 0 → 0 | 5 → 0 | `no_match` | Fail → Pass |
| `incidental-overlap-en` | — | 1 → 0 | 5 → 0 | `no_match` | Fail → Pass |
| `incidental-overlap-pt` | — | 1 → 0 | 5 → 0 | `no_match` | Fail → Pass |
| `inclusion-at-budget` | — | 0 → 0 | 0 → 0 | `no_match` | Fail → Pass |

The late-section pack delivered the expected sentence from line 72 at an
estimated 345 tokens out of 1,200. The four miss cases kept the fixture
steering and delivered zero stored evidence. All cases had zero disagreement
between included and rendered sections.

Regression tests cover exact-fit inclusion, the omitted fragment and its
statistics one token below the full pack budget, and `budget_limited` when
only steering fits. They also check lifecycle handling in indexed and scan
retrieval and with the injected embedder. [Regression tests](../../tests/test_recall_delivery.py)
