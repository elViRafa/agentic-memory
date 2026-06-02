# GitHub Copilot Instructions — Memory Fabric

## Memory Fabric MCP Tools

This project exposes a `memory-fabric` MCP server. Use its tools for all memory
operations rather than reading or writing `.ai-memory/` files directly.

### Mandatory session workflow

**Step 1 — Load context at session start**

Call `read_combined_context_tool` before answering questions or making changes:
```
read_combined_context_tool(cwd="<absolute path to project root>")
```
If `.ai-memory/` does not exist, call `initialize_memory_fabric_tool(cwd=...)` first.

**Step 2 — Search memory before searching the codebase**

```
keyword_search_tool(cwd="...", query="<topic>")
```

**Step 3 — Save knowledge after meaningful work**

After decisions, architecture changes, or pattern discoveries:
```
write_local_memory_tool(cwd="...", section="decisions", content="...", mode="append")
```

Common sections: `decisions`, `architecture`, `debt`, `schemas`,
`ubiquitous-language`, `framework-rules`.

### When to write memory

| Situation | Section |
|---|---|
| Design decision made with rationale | `decisions` |
| Component or data flow added/changed | `architecture` |
| Known shortcut or issue accepted | `debt` |
| Domain term defined or redefined | `ubiquitous-language` |
| Library pattern or rule agreed | `framework-rules` |
| Data model or API contract changed | `schemas` |

### Rules

- Never write to `.ai-memory/` directly with file tools.
- Always load context with `read_combined_context_tool` at session start.
- Never store credentials or tokens in memory content.

---

## Project overview

Memory Fabric is the MCP server itself. Key files:

- `src/memory_fabric/server.py` — MCP tool registration
- `src/memory_fabric/storage.py` — Core read/write/dream/search logic
- `src/memory_fabric/eval.py` — Quality scoring
- `src/memory_fabric/cli.py` — `ai-memory` CLI
- `src/memory_fabric/security.py` — Secret detection and redaction

Run tests: `pytest tests/`
