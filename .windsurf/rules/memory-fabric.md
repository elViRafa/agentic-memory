## Memory Fabric — Semantic Store Agent Instructions

🚨 **CRITICAL RULES - READ FIRST** 🚨
1. **NEVER use the native VS Code Copilot `memory` tool.** You MUST ONLY use the `memory-fabric` MCP tools (like `write_memory_store_tool`). The native `memory` tool writes to VS Code workspace storage, bypassing this project's memory system.
2. **NEVER use raw file system tools** (like `create_file`, `write_to_file`, `bash`, etc.) to read or write files inside the `.ai-memory/` directory. Doing so bypasses secret scanning, token budgeting, and the Dreaming system.
3. **MANDATORY STARTUP:** You MUST call `read_combined_context_tool(cwd="<absolute project root path>")` before doing anything else at the start of a session. No exceptions.

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
- **Dreaming:** Use `dream_tool` for consolidation. Refer to `.agents/rules/dreaming.md` for guidelines.

## Memory Fabric — Dreaming Process Instructions

Trigger a dream after significant changes or bug fixes to refresh indices and resolve contradictions.

### 1. Direct Dreaming
Call `dream_tool` with parameters:
- `cwd`: Absolute path to project root.
- `mode`: `"light"` (index/summaries) or `"deep"` (comprehensive review).
- `apply`: Set `True` to persist updates; `False` runs dry-run/candidate mode.
- `llm_rewrite`: Set `True` to generate rewrite tasks.
- `with_eval`: Set `True` (with `apply=True`) to run quality evaluation.

### 2. Split-Tool Protocol (Avoiding Client Deadlocks)
If client-side LLM consolidation is needed (e.g., no direct LLM or to bypass JSON-RPC deadlocks):
1. Call `prepare_dream_payload_tool(cwd, mode="deep")`.
2. If response contains `"skip_required": true`, stop here.
3. Pass the returned `consolidation_prompt` to your LLM.
4. Call `apply_dream_results_tool(cwd, candidate_store, llm_response)` passing the LLM's raw JSON response and `candidate_store` value.
