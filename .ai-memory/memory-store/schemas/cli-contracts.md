---
store_path: schemas/cli-contracts
section: cli-contracts
summary: "TypedDict contracts governing the CLI diagnostic, status, and dreaming commands."
priority: medium
tags: [schemas, contracts, cli, dreaming]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# CLI & Dreaming API Contracts

Below are the Python `TypedDict` models defined in `src/memory_fabric/contracts.py` that govern the CLI tool outputs (`status`, `doctor`, `dream`).

## Diagnostic & Status

### `DoctorResult`
```python
class DoctorResult(TypedDict):
    ok: bool
    errors: list[str]
    warnings: list[str]
    checked_files: list[str]
```

### `StatusResult`
```python
class StatusResult(TypedDict):
    cwd: str
    memory_dir: str
    memory_exists: bool
    global_dir: str
    provider_configured: bool
    local_files: list[str]
    memory_sizes: dict[str, dict[str, int]]  # Maps filename to {"bytes": int, "tokens": int}
    version: str
```

## Dreaming & Maintenance

### `DreamResult`
```python
class DreamResult(TypedDict):
    changed: bool
    snapshot: str | None
    warnings: list[str]
    candidate_store: str
    patch_preview: str
    consolidation: DreamConsolidation
    rewrite_tasks: list[DreamRewriteTask]
    apply_required: bool
    redactions: int
    evaluation: NotRequired[DreamEvalResult]
```

### `DreamConsolidation`
```python
class DreamConsolidation(TypedDict):
    duplicates_found: int
    lines_removed: int
    files_touched: list[str]
```

### `DreamRewriteTask`
```python
class DreamRewriteTask(TypedDict):
    section: str
    reason: str
    instruction: str
```
