---
trigger: always_on
---

## Memory Fabric — Semantic Store Agent Instructions

🚨 **CRITICAL RULES - READ FIRST** 🚨
1. **NEVER use the native VS Code Copilot `memory` tool.** You MUST ONLY use the `memory-fabric` MCP tools (like `write_memory_store_tool`). The native `memory` tool writes to VS Code workspace storage, bypassing this project's memory system.
2. **NEVER use raw file system tools** (like `create_file`, `write_to_file`, `bash`, etc.) to read or write files inside the `.ai-memory/` directory. Doing so bypasses secret scanning, token budgeting, and the Dreaming system.
3. **MANDATORY STARTUP:** You MUST call `read_combined_context_tool(cwd="<absolute project root path>")` before doing anything else at the start of a session. No exceptions.
4. **NEVER call `dream_tool` as a substitute for saving new knowledge.** Before triggering any Dream tool, you MUST first call `write_memory_store_tool` to persist specific, isolated memories from the current session (e.g., bugs fixed, features built, architecture decisions). Dreaming consolidates existing memory — it does NOT capture new knowledge.

### 1. Active Retrieval Workflow
- **Search:** Use `keyword_search_tool(cwd, query)` to find specific documented topics.
- **Deep Dive:** Use `read_memory_store_tool(cwd, store_path)` or `read_section(cwd, section)` for detailed content.

### 2. Store Writes & Rules
Use `write_memory_store_tool` to register standalone memories.
- **`store_path` Rules:** Must be lowercase, alphanumeric segments separated by slashes. No spaces, capitals, or `.md` extension (e.g., `architecture/decisions/jwt-auth`). Max 5 levels of nesting.
- **Parameters:** `cwd`, `store_path`, `content`, `title` (optional), `tags` (optional), `priority` (`high`/`medium`/`low`), `mode` (`replace`/`append`).

### 3. Executive Map Updates
For updating root map files (e.g., `debt`, `architecture`), call `write_local_memory_tool(cwd, section, content, mode="replace")`.

### 4. Security & Maintenance
- **Security:** Do NOT store credentials, tokens, or passwords.
- **Dreaming:** Use `dream_tool` for consolidation only — after new knowledge has already been saved with `write_memory_store_tool`. Refer to `.agents/rules/dreaming.md` for guidelines.
