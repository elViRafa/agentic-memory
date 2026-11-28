# coding-memory-bench

A small, extractable benchmark for **project memory in coding agents**.

Later sessions must recover decisions recorded in earlier ones. The score is
**memory-on vs memory-off retrieval** — no LLM is required for the default
number, so CI can fail a ranking regression.

This directory is the Phase 5 / R6-3 fixture. It can live inside Memory Fabric
or be copied out as its own repo that depends on `memory-fabric`.

## Recall targets

The built-in fixture is modeled on the field report
(`Z_REPORT_REAL_USAGE_ANALYSYS.md`):

| Later-session question | Expected memory |
|---|---|
| Should `TOT_LOCAL` use CAD or system columns? | CAD columns, not system columns |
| What should a new Python test file be named? | `test_*.py` (not `tests_*.py`) |
| Can we use Django REST Framework? | No DRF |
| Is `urnas_add_pos_calc` still in the schema? | PRD 0009 reversed PRD 0008 |

A long low-priority journal mentions some of the same words so a broken ranker
can fail by promoting noise.

## Reproduce

From the Memory Fabric repo (after `pip install -e .` or `PYTHONPATH=src`):

```sh
ai-memory bench
ai-memory bench --json
ai-memory bench --fixture recall
ai-memory bench --fixture recall --json
python benchmarks/coding-memory/run.py
```

Against your own store:

```sh
ai-memory bench --fixture . --suite .ai-memory/evals/bench.yaml
```

A suite file is a YAML/JSON list of:

```yaml
- id: auth-choice
  query: which auth approach did we pick and why?
  expected_store_paths:
    - decisions/auth-jwt
  expected_tokens:
    - JWT refresh
```

## Field-report cases

The `recall` fixture uses synthetic English and Portuguese questions in a
temporary store. It covers a current decision, an open-file failure, two stale
fixes, a closed decision with a successor, a late answer in a long note, and
questions with no stored answer. The 320-token probe isolates a disagreement
between the inclusion list and the rendered text. [1.4.6 baseline](recall-baseline-1.4.6.md) ·
[Step 2 results](recall-step-2.md)

The case definitions record each expected path, phrase, and status. Custom
YAML and JSON suites can opt in to the same checks by adding `expected_status`.
Use `matched` for current guidance, `historical_only` for a historical lead,
or `no_match` for an unanswerable query. The report compares the expected
status with the task pack's `retrieval_status` and checks the delivered
source and phrase.
Optional `files_open` and `max_tokens` configure task context. The
`search_expected_store_paths` override can specify a separate search target or
an empty list for an open-file case that expects zero keyword hits.

## Scoring

- **Keyword search** reports the one-based rank of the first expected source
  among all hits and the fraction of expected sources in the first five.
  Queries with zero expected hits pass this check when search returns zero hits.
- **Task context** reads section markers in the returned text and checks each
  expected phrase within the expected source fragments. Unanswerable queries
  pass the evidence check when the text contains zero evidence fragments.
  Steering can still appear. The report compares rendered section keys with
  `included_sections` independently.
- **Memory-off control** uses an empty initialized store. The original fixture
  and cases with `expected_status` require both memory-on checks to pass,
  agreement between rendered and listed sections, and absence of the expected
  evidence in the control.

`--k` sets the task pack limit and the legacy search cutoff. The search
recall-at-five measurement always checks the first five results. The original
JSON fields remain available. Legacy recall uses the union of search paths
and inclusion metadata, legacy token hits inspect the whole pack, and lift is
memory-on recall minus memory-off recall. Existing custom suites that omit
`expected_status` retain their legacy pass criteria and also report the new
measurements.

## Search latency

Run `python benchmarks/coding-memory/search_latency.py --engine-src src` from
the repository root to measure cold indexed search and warm p95 on 500
deterministic notes. The [Step 3 report](recall-step-3.md) includes the
comparison against 1.4.6 and the separate embedding measurement.

## Paired agent outcomes

Step 4 runs four synthetic tasks in fresh Codex sessions with Memory Fabric on
and off. The outcome scorer uses workspace changes, tool evidence, and the
agent's final report. [Fixtures, results, and reproduction](recall-step-4.md)

## Extract as a standalone repo

Copy this directory, keep `run.py` and `tasks.yaml`, and depend on
`memory-fabric`. The runner imports `memory_fabric.eval.bench`; it does not
reimplement ranking.
