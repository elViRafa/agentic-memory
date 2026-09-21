# TEST PLAN — Almost-real field pack usage (U1–U5)

**Audience:** another agent/model that will *implement and run* the almost-real usage smoke.  
**Repo:** `agentic-memory` (memory-fabric).  
**Do not** re-implement U1–U5 product code — it already shipped. This plan is about **testing** that packing, ranking, dreaming, doctor, and eval behave under a search-sermons-*shaped* store.

**Related (do not edit):** Cursor plan `field_pack_test_plan_*.plan.md` (optional). Product fixes: `CHANGELOG.md` Unreleased / `debt/field-pack-precision-2026-09`.

---

## 0. Mission for the implementing agent

Build and run an **agent-session-shaped** smoke path:

1. Seed (or open) a large diary-like `.ai-memory/` store.
2. Act like an agent: write a live handoff → startup pack → task pack → light dream → light dream again → doctor → eval.
3. Fail hard if any **gate** below fails.
4. Never copy Spurgeon / CPT / Vultr / real project domain text into this repo. Use **generic** vocabulary (`wave`, `handoff`, `legacy model`, `training volume`, `adapter`).

### Deliverables you must create

| File | Role |
| --- | --- |
| `scripts/field_pack_usage_smoke.py` | Runnable smoke (synthetic default; `--cwd` for live project) |
| `tests/test_field_pack_usage_smoke.py` | CI wrapper: synthetic mode in a tempfile, assert exit code 0 |

This markdown file is the spec. Keep it updated if gates change.

---

## 1. Prerequisites

```powershell
cd C:\Users\rafael\Projetos\agentic-memory
$env:PYTHONPATH = "src"
python -c "import memory_fabric; print(memory_fabric.__file__)"
```

Must resolve to this repo’s `src/`, not an older installed wheel.

Optional live dogfood project (gold check, do not seed):

`C:\Users\rafael\Projetos\search-sermons`

---

## 2. What already shipped (context only)

| Wave | Behavior to verify |
| --- | --- |
| U1 | Contradiction pack in `index.md` ≤ 5; full list in `evals/contradictions.json`; IDF / same-topic / successive-version / bugs-skip |
| U2 | `review_status: stale\|broken-evidence` omitted from task packs; `superseded_by` hard-downranks |
| U3 | Eval `contradiction_pack_hygiene`; retrieval fixtures can use `must_include` / `must_exclude`; empty UL fails coding usefulness |
| U4 | Light-dream cooldown via store fingerprint (`MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES`); apply prunes candidates (`keep_candidates=0`); no-op discards snapshot |
| U5 | Doctor: placeholder steering, stale-only `decisions/`, off-topic failures, ADR-under-diary hints |

Deep dreams are **exempt** from cooldown (episodic rollup must still run).

---

## 3. Almost-real session (required flow)

```text
seed → write live handoff → read_combined_context
     → context_for_task → dream(light, apply) → dream(light, apply)
     → doctor → evaluate_memory_fabric
```

### 3.1 Seed shape (synthetic mode only)

Create via `initialize_memory_fabric(cwd)` then write files under `.ai-memory/memory-store/`. Prefer mostly `priority: high`.

| Bucket | Count (approx) | Notes |
| --- | --- | --- |
| `pretraining/wave-NN-complete` | 40 | Finished waves; bodies say DONE / do not re-run |
| `pretraining/wave-s2-handoff`, `…-s3-handoff`, `…-s4-handoff` | 3 | Successive versions with **different numbers** (must NOT be treated as contradictions) |
| `fine-tuning/*` | ~15 | Mix of notes + older handoffs |
| `fine-tuning/next-session-handoff` | 1 | **Live** handoff; recent `last_updated`; body mentions “next session handoff” |
| `architecture/serving-boundaries` | 1 | “Must not mount the training volume on the serving pod” (negation + shared vocab) |
| `bugs/adapter-frozen-weights` | 1 | “Do not use adapter tuning on frozen embeddings” (opposite polarity vs training notes) |
| `pretraining/*` notes mentioning adapters positively | several | Same-prefix training diary |
| `decisions/legacy-model-finetuning` | 1 | `review_status: stale`; body **also** says “next session handoff” so BM25 can match — must still lose |
| `failures/opc-type-mismatch-sim` | 1–2 | Off-topic industrial/OPC nonsense tokens |
| Root `ubiquitous-language.md` | 1 | Leave / reset to starter: “Record project terminology here.” |

Mirror helpers in `tests/test_field_topology.py` (`_write_store_file`, dump_frontmatter). Do **not** import domain text from search-sermons.

### 3.2 Session steps and hard gates

| Step | Action | APIs | Pass if (hard fail otherwise) |
| --- | --- | --- | --- |
| A | Seed (+ optional `write_memory_store` refreshing live handoff) | `initialize_memory_fabric`, `write_memory_store` | Store paths exist |
| B | Startup pack | `read_combined_context(cwd)` | `estimated_tokens <= token_budget`; packed `text` does **not** contain a 50-item contradiction wall (after dream, index pack ≤5 — see D) |
| C | Task pack | `context_for_task(cwd, "continue next session handoff for fine-tuning")` | `included_sections` contains `store/fine-tuning/next-session-handoff`; does **not** contain `store/decisions/legacy-model-finetuning` |
| D | First light dream | `asyncio.run(dream(cwd, mode="light", apply=True))` | `index.md` frontmatter `len(contradictions) <= 5`; `contradiction_count` present; `.ai-memory/evals/contradictions.json` exists; after apply, `candidates/` has **0** dirs |
| E | Second light dream | same, with cooldown enabled | `changed is False` **or** warning mentions cooldown/skipped/discarded; snapshot dir count does **not** increase vs post-D |
| F | Doctor | `doctor(cwd, check_network=False)` | At least one warning about placeholder / ubiquitous-language / steering |
| G | Eval | `asyncio.run(evaluate_memory_fabric(cwd, save_report=False))` | Category/check `contradiction_pack_hygiene` is not `fail`; empty UL is `fail` or `warn` on placeholder (document which) |

Print a JSON summary to stdout, e.g.:

```json
{
  "ok": true,
  "cwd": "...",
  "mode": "synthetic",
  "gates": {"A": "pass", "B": "pass", "...": "..."},
  "metrics": {
    "contradiction_pack_len": 3,
    "contradiction_count": 12,
    "snapshots_after_d": 1,
    "snapshots_after_e": 1,
    "candidates_after_d": 0
  }
}
```

Exit code `0` only if all hard gates pass; otherwise `1`.

### 3.3 Cooldown determinism (step E)

Light-dream cooldown uses a **store fingerprint** in `.ai-memory/private/last_dream_apply` (ISO timestamp + hash), env `MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES` (default 5).

For CI:

- Leave default cooldown **or** set `MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES=30` after step D so E cannot apply again without store writes.
- Do not set cooldown to `0` for step E (that disables the gate).

Deep mode must remain usable without cooldown blocking (not required in this smoke).

---

## 4. CLI / how to run

### Synthetic (CI / local)

```powershell
cd C:\Users\rafael\Projetos\agentic-memory
$env:PYTHONPATH = "src"
python scripts/field_pack_usage_smoke.py
# optional:
python scripts/field_pack_usage_smoke.py --tmpdir $env:TEMP\mf-field-smoke
```

### Live dogfood (search-sermons)

```powershell
$env:PYTHONPATH = "src"
python scripts/field_pack_usage_smoke.py --cwd C:\Users\rafael\Projetos\search-sermons
```

Live mode: **skip seed**; run B–G only. Same hard gates. Query text for C may be adjusted to a live handoff key if needed, but prefer a query that still targets `*next-session-handoff*` / current handoff without pasting proprietary notes into the script.

### Pytest wrapper

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_field_pack_usage_smoke.py -q
```

Wrapper must not require search-sermons on disk.

---

## 5. Implementation sketch for `scripts/field_pack_usage_smoke.py`

Suggested structure (implementing agent may refine):

```text
main(argv):
  parse --cwd | --tmpdir
  if cwd is None: create temp, seed_store(cwd), mode=synthetic
  else: mode=live
  gates = {}
  run A..G, record pass/fail
  print JSON
  sys.exit(0 if all hard else 1)

seed_store(cwd):
  initialize_memory_fabric(cwd)
  write many files via dump_frontmatter / write_memory_store
  ensure UL placeholder body
```

Imports (from this package):

- `memory_fabric.storage`: `initialize_memory_fabric`, `write_memory_store`, `read_combined_context`, `context_for_task`, `dream`, `doctor`
- `memory_fabric.eval.memory_quality.evaluate_memory_fabric` (async)
- `memory_fabric.frontmatter.parse_frontmatter`
- `memory_fabric.paths.local_memory_dir`

Reference style: `scripts/capture_rate_benchmark.py`, `tests/test_field_topology.py`.

---

## 6. Existing unit tests (reference only — not a substitute)

Run for regression after smoke:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_contradictions.py tests/test_field_topology.py -q
```

Notable node ids:

- `ContradictionPrecisionTests::test_field_false_polarity_across_categories_is_suppressed`
- `ContradictionPrecisionTests::test_successive_handoff_numeric_clash_is_skipped`
- `ContradictionPrecisionTests::test_pack_surface_caps_index_and_writes_report`
- `StaleSupersededRankingTests::test_stale_and_superseded_lose_to_live_handoff`
- `DreamChurnTests::test_second_apply_on_quiet_tree_is_cooldown_noop`

---

## 7. Soft warnings (do not fail the smoke)

These are expected under field-shaped stores:

- High-priority inflation warnings from write/doctor
- Weak / timestamp summary warnings on some seeded files
- Doctor listing a few real contradictions (advisory) while pack stays ≤5

---

## 8. Out of scope

- Cleaning Gemma / asyncua files inside search-sermons
- Hybrid embeddings, link graph, LongMemEval
- Reverting or rewriting U1–U5 product logic
- Editing Cursor `.cursor/plans/*` files
- Calling `dream_tool` as a substitute for writing facts (protocol: write first, then dream)

---

## 9. Definition of done

- [ ] `scripts/field_pack_usage_smoke.py` exists and exits 0 on synthetic seed
- [ ] `tests/test_field_pack_usage_smoke.py` exists and passes under `PYTHONPATH=src`
- [ ] Live run documented; optional manual: smoke against search-sermons exits 0 after local install
- [ ] No domain facts from search-sermons copied into seed bodies
- [ ] This file remains the handoff spec for future agents

---

## 10. Handoff prompt (copy to the other agent)

```text
Read TEST_PLAN_FIELD_PACK_PRECISION.md in the agentic-memory repo root.
Implement scripts/field_pack_usage_smoke.py and tests/test_field_pack_usage_smoke.py
exactly as specified. Use PYTHONPATH=src. Do not copy search-sermons domain text.
Run the synthetic smoke and the pytest wrapper; fix until exit 0 / tests pass.
Optionally document the live --cwd search-sermons command in a short note at the
bottom of the test plan if anything differed in practice.
```
