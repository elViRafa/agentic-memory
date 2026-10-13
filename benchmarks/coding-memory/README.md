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

## Scoring

For each task the harness runs `keyword_search` and `context_for_task` at top-k
(default 5):

- **memory-on recall** — fraction of `expected_store_paths` that appear
- **memory-off recall** — the same queries against an empty initialized store
- **token hit** — all `expected_tokens` appear in the task pack
- **lift** — on-recall minus off-recall

The builtin fixture **passes** only when on-recall is 1.0, off-recall is 0.0,
every on-side token check hits, and lift is positive.

This is a retrieval proof, not a statistical study of live agent compliance.
An optional LLM answer pass can be layered later without changing the fixture.

## Extract as a standalone repo

Copy this directory, keep `run.py` and `tasks.yaml`, and depend on
`memory-fabric`. The runner imports `memory_fabric.eval.bench`; it does not
reimplement ranking.
