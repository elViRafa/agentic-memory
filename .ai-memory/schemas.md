---
section: schemas
summary: "Defines YAML frontmatter schemas and Python `TypedDict` contracts for memory metadata, tool responses, and system status."
priority: high
tags: [schemas, contracts, frontmatter, json]
schema_version: 1.3
last_updated: "2026-06-03T08:27:58-04:00"
summary_hash: 9cc3ef55405367bd4e51470456a6a789
---

# Schemas

Memory Fabric utilizes structured contracts for file frontmatter metadata and tool/CLI command response formats.

## 1. Markdown Frontmatter Schema

Every memory section (except `index.md` in some contexts, though it can have it too) begins with a YAML frontmatter block enclosed between `---` delimiters:

```yaml
section: <string>           # Name of the section (e.g. architecture, decisions)
summary: <string>           # A concise 1-sentence summary under 150 characters
priority: high|medium|low   # Priority for inclusion in context budget
tags: [<list of strings>]   # Categorization tags (e.g. [api, auth])
schema_version: "1.3"       # Memory structure version compatibility
last_updated: <iso-8601>    # ISO-8601 timestamp of last update
review_status: stale        # (Optional) set to 'stale' if not updated in 30 days
summary_hash: <md5-hash>    # (Optional) md5 hash of the file body to avoid redundant LLM summarization
```

## 2. API & Tool Contracts (TypedDict)

Below are the Python `TypedDict` models defined in `src/memory_fabric/contracts.py` that govern API responses:

### Context & Initialization

#### `InitResult`
```python
class InitResult(TypedDict):
    created: bool
    memory_dir: str
    files_created: list[str]
    warnings: list[str]
```

#### `ContextBundle` (returned by `read_combined_context_tool`)
```python
class ContextBundle(TypedDict):
    text: str
    included_sections: list[str]
    omitted_sections: list[str]
    token_budget: int
    estimated_tokens: int
    warnings: list[str]
```

#### `MemorySection` (returned by `read_section_tool`)
```python
class MemorySection(TypedDict):
    section: str
    path: str
    text: str
    metadata: dict[str, Any]
    truncated: bool
    warnings: list[str]
```

### Search & Write Operations

#### `SearchResult` (returned by `keyword_search_tool`)
```python
class SearchResult(TypedDict):
    section: str
    path: str
    line: int
    snippet: str
```

#### `WriteResult` (returned by `write_local_memory_tool` / `rollback`)
```python
class WriteResult(TypedDict):
    changed: bool
    path: str
    redactions: int
    warnings: list[str]
```

#### `PatchPreview` (returned by `propose_memory_patch_tool`)
```python
class PatchPreview(TypedDict):
    patch: str
    affected_files: list[str]
    redactions: int
    warnings: list[str]
```

### Diagnostic & Status

#### `DoctorResult`
```python
class DoctorResult(TypedDict):
    ok: bool
    errors: list[str]
    warnings: list[str]
    checked_files: list[str]
```

#### `StatusResult`
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

### Dreaming & Maintenance

#### `DreamResult`
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

#### `DreamConsolidation`
```python
class DreamConsolidation(TypedDict):
    duplicates_found: int
    lines_removed: int
    files_touched: list[str]
```

#### `DreamRewriteTask`
```python
class DreamRewriteTask(TypedDict):
    section: str
    reason: str
    instruction: str
```

### Evaluation Metrics

#### `EvalCheck`
```python
class EvalCheck(TypedDict):
    id: str
    status: Literal["pass", "warn", "fail"]
    severity: Literal["info", "low", "medium", "high"]
    message: str
    recommendation: str
    command: NotRequired[str]
```

#### `EvalCategory`
```python
class EvalCategory(TypedDict):
    name: str
    score: int
    weight: int
    checks: list[EvalCheck]
```

#### `EvalResult`
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

#### `DreamEvalResult`
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
