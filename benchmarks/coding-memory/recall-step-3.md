# Query latency on the 500-note fixture

Measured on November 28, 2026 using Windows 11, an Intel Core i7-10750H,
Python 3.14.0, and SQLite 3.50.4. The release baseline is tag `v1.4.6`
at `fa7dd184`. The same interpreter and [fixture runner](search_latency.py)
ran both engines sequentially against fresh copies of the same synthetic
corpus. The SQLite index was the search backend and the global memory
directory was empty. Diary recording and semantic search were disabled.

The fixture contains 32 decision notes and 468 journals with overlapping
terms. The 20 queries include English and Portuguese questions, three known
identifiers, and one invented identifier. The cold measurement is the first
search in a new process with no index database. After one warm-up sequence,
the runner measures five repetitions of the same queries. Warm p95 is the
95th observation in the sorted set of 100 latencies. Both measurements
time the search call inside the process.

| Version | First cold search | Warm p95 |
| --- | ---: | ---: |
| 1.4.6 release | 517.2 ms | 293.8 ms |
| Step 3 candidate | 417.0 ms | 65.1 ms |
| Reduction | 19.4% | **77.8%** |

The initial pass measured 361.5 ms warm p95 for 1.4.6 and 256.7 ms for the
Step 2 search before optimization. The table uses the release rerun
immediately preceding the final candidate.

## Warm search profile

The phase times are means over a separate instrumented 20-query sequence.
The scoring phase includes phrase matching and ranking. The snippets phase
includes reading and selecting the displayed passage.

| Phase | 1.4.6 release | Step 2 before optimization | Step 3 candidate |
| --- | ---: | ---: | ---: |
| Index synchronization | 76.136 ms | 81.037 ms | 14.970 ms |
| SQLite row loading | 6.811 ms | 7.813 ms | 6.495 ms |
| Tokenization | 79.449 ms | 84.161 ms | 0.012 ms |
| Scoring | 28.966 ms | 33.348 ms | 14.977 ms |
| Snippets | 0.606 ms | 1.918 ms | 1.792 ms |
| Other work | 23.088 ms | 20.333 ms | 17.590 ms |

Index refresh now uses directory-entry metadata and parses changed files from
the same read used to hash them. It checks disk on each search, so edits and
deletions take effect on the next call. Search reuses tokens and normalized
phrase text in bounded, process-local caches keyed by text. Corpus-wide BM25
and the Step 2 evidence eligibility rules still apply.

## Optional embeddings

The model files for `sentence-transformers/all-MiniLM-L6-v2` were downloaded
before timing. Both runs used FastEmbed 0.9.1 on CPU and started with the
model unloaded in a fresh process and no index. Warm samples repeat the
first English query three times with the model loaded. This separate
measurement uses the same 500 notes.

| Version | Cold | Warm samples, in order |
| --- | ---: | --- |
| 1.4.6 release | 15.09 s | 15.28 s, 18.30 s, 26.18 s |
| Step 3 candidate | 13.84 s | 14.69 s, 12.76 s, 14.08 s |

## Verification

- Both labeled fixtures passed after each search optimization. The original
  fixture passed 4 of 4 cases and the recall fixture passed 10 of 10.
- The existing maps-first startup check passed its 150 ms p95 limit on a
  1,000-file store.
- The full test suite finished with 553 passed and one skipped.
- Five indexed searches each reported 495 candidates and produced zero
  confirmed cap hits in the exported diary pack. Adding five forced Python
  fallback searches recorded five confirmed caps and failed the gate at
  a 50% confirmed cap rate.
- Older fallback rows at the historical cap contribute to
  `inferred_cap_n` and `inferred_cap_rate`. The confirmed cap gate uses
  `cap_n` and `cap_rate`. Zero-hit counts and rates remain descriptive.

## Reproduce

```sh
git worktree add --detach ../memory-fabric-1.4.6 v1.4.6
python benchmarks/coding-memory/search_latency.py --engine-src ../memory-fabric-1.4.6/src
python benchmarks/coding-memory/search_latency.py --engine-src src
```

With the semantic extra installed and the model already cached, append
`--semantic` to each command to repeat the embedding measurement.
