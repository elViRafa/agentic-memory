---
store_path: schemas/mcp-contracts
section: mcp-contracts
summary: "TypedDict contracts governing the MCP Server tool requests and JSON-RPC responses."
priority: high
tags: [schemas, contracts, mcp, typeddict]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# MCP Server API Contracts

Below are the Python `TypedDict` models defined in `src/memory_fabric/contracts.py` that govern MCP Server tool responses.

## Context & Initialization

### `InitResult`
```python
class InitResult(TypedDict):
    created: bool
    memory_dir: str
    files_created: list[str]
    warnings: list[str]
```

### `ContextBundle` (returned by `read_combined_context_tool`)
```python
class ContextBundle(TypedDict):
    text: str
    included_sections: list[str]
    omitted_sections: list[str]
    token_budget: int
    estimated_tokens: int
    warnings: list[str]
```

### `MemorySection` (returned by `read_section_tool`)
```python
class MemorySection(TypedDict):
    section: str
    path: str
    text: str
    metadata: dict[str, Any]
    truncated: bool
    warnings: list[str]
```

## Search & Write Operations

### `SearchResult` (returned by `keyword_search_tool`)
```python
class SearchResult(TypedDict):
    section: str
    path: str
    line: int
    snippet: str
```

### `WriteResult` (returned by `write_local_memory_tool` / `rollback`)
```python
class WriteResult(TypedDict):
    changed: bool
    path: str
    redactions: int
    warnings: list[str]
```

### `PatchPreview` (returned by `propose_memory_patch_tool`)
```python
class PatchPreview(TypedDict):
    patch: str
    affected_files: list[str]
    redactions: int
    warnings: list[str]
```
