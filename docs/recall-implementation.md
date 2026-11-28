# Reliable recall implementation checklist

A coding agent needs to recover a current decision, recognize a historical lead, and tell when project memory has no evidence. Start with the retrieval surfaces that agents already call. In the largest audited workspace, 1.4.6 recorded 64 direct keyword searches and no direct task-context calls during the historical window. The task pack also matters to callers that consume its text without inspecting the search results. [Field report and methodology](field-recall-2026-11.md)

## 1. Measure search and delivered evidence independently

- [x] Extend `ai-memory bench` with synthetic English and Portuguese cases derived from the observed patterns. Include a current decision, an open-file failure, a stale fix without a successor, a closed predecessor with a current successor, an answer in the final section of a long note, an invented identifier, and a question with incidental word overlap. Record the expected source, answer phrase, and status before tuning ranking.
- [x] Report the first correct search rank and recall at five. For the task pack, parse the section markers in the returned text and check the expected phrase **inside the expected source fragment**. Score unanswerable cases by counting retrieved evidence fragments. Steering alone is a valid response to these queries.
- [x] Keep existing suite files and JSON fields readable. Add separate results for the two surfaces to the CLI report. Add a regression where the target appears only in search and one where it appears only in the inclusion metadata. Both must fail the delivered-evidence check.

**Exit check.** Run the suite against 1.4.6 before changing ranking. Save the per-case baseline, including failures. The four existing fixture cases remain reproducible. The new suite detects irrelevant notes and the inclusion mismatch independently. [Benchmark implementation](../src/memory_fabric/eval/bench.py) · [Current fixture](../benchmarks/coding-memory/README.md)

**Recorded baseline.** The original fixture passed 4/4 cases. The synthetic recall fixture passed 2/10 cases, with search recall at five of 2/5. [Per-case 1.4.6 results](../benchmarks/coding-memory/recall-baseline-1.4.6.md)

## 2. Deliver relevant passages and make misses explicit

- [x] In `context_for_task`, require a query match or a supported open-file match before admitting a retrieved note. Preserve the existing always-on steering policy. For ordinary questions, test topical terms after removing English and Portuguese function words. Calibrate against the positive and incidental-overlap cases from step 1. A successor pointer also needs a relevant predecessor match.
- [x] Add an optional `retrieval_status` output to queried task packs on both CLI and MCP. Use `matched` for delivered current evidence, `historical_only` when the delivered leads are all historical, `no_match` when no evidence qualifies, and `budget_limited` when eligible evidence exists but none fits. Build inclusion, omission and token statistics from the fragments that remain after final trimming.
- [x] Give long notes a query-centered excerpt with the heading or line location and store path under the existing per-file cap. For an exact topical match to a stale, unclosed fix, return a separately labeled historical lead and its source in search and task context. Preserve current status for standing decisions under the existing lifecycle rules. On a closed match, show the successor link and use an eligible successor for current guidance. Keep broken evidence out of current guidance.
- [x] Apply lifecycle checks to indexed search, scan fallback, task packing, and optional semantic candidates. Test semantic cases with the injected embedder already used in CI. Make exact-identifier and open-file tests pass with the default local installation.

**Exit check.** Deliver the expected phrase from a late section in a 1,200-token fixture with room for evidence. Deliver zero stored evidence for the negative cases and preserve required steering. Verify the listed sections equal the rendered sections for an exact-fit budget and when a final fragment is dropped. A historical result always carries its status in the text an agent reads. [Task retrieval](../src/memory_fabric/storage/retrieve.py) · [Search](../src/memory_fabric/storage/search.py) · [Public contracts](../src/memory_fabric/contracts.py)

**Recorded result.** Both fixtures passed (4/4 original and 10/10 recall). The late answer was delivered in a 345-token pack, and all four miss cases preserved steering with zero stored evidence. [Per-case results against 1.4.6](../benchmarks/coding-memory/recall-step-2.md)

## 3. Measure and reduce query latency

- [x] Correct the `diary analyze` cap signal first. Index rows may legitimately report the entire searchable corpus. Record whether a fallback actually stopped at its limit, and keep older diary packs readable. For older scan events, report inferred cap hits separately from confirmed ones. Keep the existing zero-hit signal available as a descriptive measure.
- [x] Add a deterministic 500-entry corpus with English and Portuguese queries, exact identifiers, and journals that share common terms. On one host, use the same interpreter, backend, corpus and queries for baseline and candidate. Record the first cold call separately. For warm p95 use the nearest rank over five repetitions of the same 20-query sequence after one warm-up sequence. Disable diary recording for the timed run.
- [x] Profile index synchronization, tokenization, scoring, and snippet reads independently. Optimize the dominant measured cost. Run the optional embedding path separately, including model state in the report. Use the labeled suite from step 1 to catch ranking regressions after each optimization.

**Exit check.** Five indexed searches over 495 entries produce zero cap failures. Five confirmed capped fallback scans trigger the existing gate. Cut warm p95 on the controlled 500-entry lexical fixture by at least 50% relative to its measured 1.4.6 baseline, with all recall checks passing. Keep the existing 1,000-file no-query startup gate green. The field p95 below gives a point of reference for a later field replay. [Diary analyzer](../src/memory_fabric/diary/analyze.py) · [Index implementation](../src/memory_fabric/storage/index.py)

**Recorded result.** Warm p95 fell from 293.8 ms to 65.1 ms (77.8%). The diary cap checks, both recall fixtures, and the 1,000-file startup check passed. [Latency profile, embedding run, and reproduction commands](../benchmarks/coding-memory/recall-step-3.md)

## 4. Test agent outcomes across sessions

- [x] Author four synthetic paired tasks covering a current decision, a recorded failure, verification of an old fix, and a request for missing evidence. Freeze the answer keys and executable checks before running the trials.
- [x] Record each task's history in a seed session. Run each arm in a fresh session with matching workspace and prompt hashes, the same ordinary docs, model setting, tool permissions, and context budget. Enable Memory Fabric history lookup in one arm.
- [x] Save the fixtures and report paired outcomes, repeated mistakes, unnecessary changes, tokens, tool calls, versions, and unavailable runs. Rerun this comparison when default retrieval policy changes.

**Exit check.** Score each pair against its predeclared answer key and publish the numerator and denominator per outcome. Treat improvement in completed tasks as an empirical result. An increase in search hits alone cannot establish it.

**Recorded result.** Four pairs were scored. Memory Fabric on passed 3/4 answer keys and off passed 1/4. Both arms reproduced the old cache regression and made zero unnecessary changes on the unanswerable task. The initial eight sessions were unavailable because the client denied workspace tool calls. [Answer keys, per-task scores, usage, and reproduction](../benchmarks/coding-memory/recall-step-4.md)

## Results to record

| Measure | 1.4.6 baseline | Release criterion | Candidate result |
| --- | --- | --- | --- |
| Built-in coding-memory fixture | 4/4 passing | Preserve the four original cases | 4/4 passing |
| Invented identifier, stored entries in delivered text | 6, 3, 5 across three field stores | Zero on all unanswerable fixtures | Zero on all four miss cases |
| Medium-store inclusion metadata on that probe | 4 listed, 3 rendered | Exact agreement in every budget case | Zero disagreement at the fixture budget, at exact fit, and after dropping the final fragment |
| Two stale, unclosed field fixes | 0/2 selected targets in top five or delivered text | Return both synthetic equivalents as labeled leads | 2/2 synthetic leads labeled in search and packs |
| Indexed versus fallback cap signal | Five synthetic successful index events triggered a cap failure | Only confirmed capped fallback events trigger the new gate | Five indexed searches passed. Five confirmed caps tripped the gate. |
| Warm search p95, controlled 500-note corpus | 293.8 ms. Large-store field p95 was 1,997 ms. | At most half the controlled baseline, with recall preserved | 65.1 ms, a 77.8% reduction |
| Paired agent outcomes | No paired trial in the field audit | Report task results, tokens and sample sizes per arm | Memory on 3/4. Memory off 1/4. Four scored pairs. |
