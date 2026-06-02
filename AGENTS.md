# Agent Instructions — Memory Fabric

This file is read automatically by Claude Code, Gemini CLI, and other MCP-aware AI agents.
GitHub Copilot reads `.github/copilot-instructions.md` instead.

---

## Memory Fabric MCP Tools

This project exposes a `memory-fabric` MCP server. **You must use it** for all memory
operations instead of reading or writing `.ai-memory/` files directly.

### Mandatory session workflow

1. **At the start of every session**, call `read_combined_context_tool` with the project cwd
   to load prior context before answering or making changes:
   ```
   read_combined_context_tool(cwd="<absolute path to project root>")
   ```
   If the call fails because `.ai-memory/` does not exist, call
   `initialize_memory_fabric_tool(cwd=...)` first, then retry.

2. **Before searching the codebase**, call `keyword_search_tool` to check what is already
   documented in memory:
   ```
   keyword_search_tool(cwd="...", query="<topic>")
   ```

3. **After completing meaningful work** (decisions made, architecture clarified, bugs found,
   patterns established), persist the knowledge with `write_local_memory_tool`:
   ```
   write_local_memory_tool(cwd="...", section="decisions", content="...", mode="append")
   ```
   Common sections: `decisions`, `architecture`, `debt`, `schemas`, `ubiquitous-language`,
   `framework-rules`.

4. **Before writing to memory**, preview changes with `propose_memory_patch_tool` when the
   update is complex or affects multiple sections.

### When to write memory

| Situation | Section |
|---|---|
| A design decision was made and rationale agreed | `decisions` |
| A new component, layer, or data flow was added/changed | `architecture` |
| A known shortcut or issue was accepted | `debt` |
| A domain term was defined or redefined | `ubiquitous-language` |
| A library-specific rule or pattern was agreed | `framework-rules` |
| A data model or API contract was changed | `schemas` |

### Do NOT

- Write markdown files inside `.ai-memory/` directly using file-system tools.
- Skip `read_combined_context_tool` at session start; prior context matters.
- Store credentials, tokens, or passwords in memory — the server redacts them, but avoid
  writing them in the first place.

---

## Project overview

Memory Fabric is the MCP server itself. Core modules:

| File | Purpose |
|---|---|
| `src/memory_fabric/server.py` | MCP tool registration via FastMCP |
| `src/memory_fabric/storage.py` | Read/write/dream/search logic |
| `src/memory_fabric/eval.py` | Quality scoring for memory and Dreaming runs |
| `src/memory_fabric/cli.py` | `ai-memory` CLI entrypoint |
| `src/memory_fabric/security.py` | Secret detection and redaction |
| `src/memory_fabric/paths.py` | Cross-platform path helpers |
| `src/memory_fabric/frontmatter.py` | YAML frontmatter parsing/writing |
| `src/memory_fabric/locking.py` | File-level write locking |
| `src/memory_fabric/contracts.py` | Shared types and constants |
| `src/memory_fabric/templates.py` | Starter-file scaffolding |

Run tests: `pytest tests/`
