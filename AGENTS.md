# Agent Instructions — Memory Fabric

This file is read automatically by Claude Code, Gemini CLI, and other MCP-aware AI agents.
GitHub Copilot reads `.github/copilot-instructions.md` instead.

---

## Memory Fabric — Semantic Store Agent Instructions

Use `memory-fabric` MCP tools for all project memory operations. Do not read or write `.ai-memory/` files using raw file-system tools.

### 1. Active Retrieval Workflow
- **Startup:** MUST call `read_combined_context_tool(cwd="<project_root>")` at session start.
- **Search:** Use `keyword_search_tool(cwd, query)` to find specific documented topics.
- **Deep Dive:** Use `read_memory_store_tool(cwd, store_path)` or `read_section(cwd, section)` for detailed content.

### 2. Store Writes & Rules
Use `write_memory_store_tool` to register standalone memories.
- **`store_path` Rules:** Must be lowercase, alphanumeric segments separated by slashes. No spaces, capitals, or `.md` extension (e.g., `architecture/decisions/jwt-auth`). Max 5 levels of nesting.
- **Parameters:** `cwd`, `store_path`, `content`, `title` (optional), `tags` (optional), `priority` (`high`/`medium`/`low`), `mode` (`replace`/`append`).

### 3. Legacy Section Writes
For legacy flat section files (e.g. `debt`), call `write_local_memory_tool(cwd, section, content, mode="append")`.

### 4. Security & Maintenance
- **Security:** Do NOT store credentials, tokens, or passwords.
- **Dreaming:** Use `dream_tool` for consolidation. Refer to `.agents/rules/dreaming.md` for guidelines.

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
| `src/memory_fabric/templates.py` | Starter-file scaffolding & agent instruction templates |

Run tests: `pytest tests/`
