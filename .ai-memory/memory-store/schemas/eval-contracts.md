---
store_path: schemas/eval-contracts
section: eval-contracts
summary: "TypedDict contracts governing the memory and dreaming evaluation results."
priority: low
tags: [schemas, contracts, eval]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Evaluation API Contracts

Below are the Python `TypedDict` models defined in `src/memory_fabric/contracts.py` that govern the Eval module outputs.

### `EvalCheck`
```python
class EvalCheck(TypedDict):
    id: str
    status: Literal["pass", "warn", "fail"]
    severity: Literal["info", "low", "medium", "high"]
    message: str
    recommendation: str
    command: NotRequired[str]
```

### `EvalCategory`
```python
class EvalCategory(TypedDict):
    name: str
    score: int
    weight: int
    checks: list[EvalCheck]
```

### `EvalResult`
```python
class EvalResult(TypedDict):
    kind: Literal["memory"]
    generated_at: str
    cwd: str
    memory_dir: str
    score: int
    categories: list[EvalCategory]
    recommendations: list[str]
    report_paths: list[str]
    warnings: list[str]
    llm_notes: list[str]
```

### `DreamEvalResult`
```python
class DreamEvalResult(TypedDict):
    kind: Literal["dream"]
    generated_at: str
    cwd: str
    memory_dir: str
    baseline_snapshot: str
    before_score: int
    after_score: int
    delta: int
    score: int
    changed_files: list[str]
    improvements: list[str]
    regressions: list[str]
    report_paths: list[str]
    warnings: list[str]
    llm_notes: list[str]
```
