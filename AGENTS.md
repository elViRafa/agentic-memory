# Agent Instructions — Memory Fabric

This file is read automatically by Claude Code, Gemini CLI, and other MCP-aware AI agents.
GitHub Copilot reads `.github/copilot-instructions.md` instead.

---

## Memory Fabric — Semantic Store Agent Instructions

You must use the `memory-fabric` MCP tools for all project memory operations. Do not read or write `.ai-memory/` files using raw file-system tools.

### 1. Startup & Retrieval (The Active Memory Workflow)
Accessing the Memory Store is an active process driven by the agent using the following tools:

1. **Session Map:** At session start, you MUST call `read_combined_context_tool(cwd="<absolute project root path>")`. This serves as your index map to quickly grasp what is stored, load directives, and active session steering prompts.
2. **Search & Target:** To find specific information without reading everything, use `keyword_search_tool(cwd="...", query="<keyword>")` to look for relevant topics already documented in memory.
3. **Deep Dive:** After locating a reference via the index or keyword search, go straight to the necessary file by calling `read_memory_store_tool` (for semantic paths) or `read_section` (for legacy sections) to extract the full context needed for your answer.

### 2. Registering Memory in the Store
After completing a task (e.g., a design decision, a bug fix, schema creation, or refactoring), persist this knowledge.

Use `write_memory_store_tool` to register small, standalone memory files.

**Strict Semantic Store Rules:**
1. **`store_path` formatting:** Must be lowercase, alphanumeric segments separated by slashes. No spaces, no capital letters, and **no `.md` extension** (e.g., `architecture/decisions/jwt-auth` or `bugs/auth-redirect-fix`).
2. **Path Nesting:** Max 5 levels of directory nesting.
3. **Duplicate Prevention:** The tool automatically strips out duplicate bullet points or lines when appending.

**Tool Parameters:**
* `cwd`: Absolute path to project root.
* `store_path`: The semantic path (e.g., `architecture/decisions/auth-service`).
* `content`: The markdown text body of the memory.
* `title`: (Optional) Human-readable title.
* `tags`: (Optional) Comma-separated tags (e.g., `auth,security`).
* `priority`: (Optional) `high`, `medium`, or `low` (default: `medium`).
* `mode`: (Optional) `replace` to overwrite, or `append` to add to the end (default: `replace`).

### 3. Legacy Section Writes
If you are updating a legacy flat section file (e.g., updating a list of risks in `debt`), call `write_local_memory_tool(cwd="...", section="debt", content="...", mode="append")`. Prefer `write_memory_store_tool` for new standalone topics.

### 4. Security & Best Practices
* **Do NOT** store credentials, tokens, or passwords in memory — the server redacts them, but avoid writing them in the first place.

### 5. Memory Maintenance (Dreaming)
To consolidate memory, check for contradictions, or refresh the index, you can use the `dream_tool`. For detailed instructions on parameters (like `mode` and `apply`) and when to trigger a dream, refer to `.agents/rules/dreaming.md`.

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
