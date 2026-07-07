## Memory Fabric — Semantic Store Agent Instructions

🚨 **CRITICAL RULES - READ FIRST** 🚨
1. **NEVER use the native VS Code Copilot `memory` tool.** You MUST ONLY use the `memory-fabric` MCP tools (like `write_memory_store_tool`). The native `memory` tool writes to VS Code workspace storage, bypassing this project's memory system.
2. **NEVER use raw file system tools** (like `create_file`, `write_to_file`, `bash`, etc.) to read or write files inside the `.ai-memory/` directory. Doing so bypasses secret scanning, token budgeting, and the Dreaming system.
3. **MANDATORY STARTUP:** You MUST call `read_combined_context_tool(cwd="<absolute project root path>")` before doing anything else at the start of a session. No exceptions.
   > **MCP Resources alternative:** If your client supports MCP Resources and has auto-fetched `memory-fabric://context/<encoded-cwd>`, that context is already in your system prompt — skip the tool call.
4. **NEVER call `dream_tool` as a substitute for saving new knowledge.** Before triggering any Dream tool, you MUST first call `write_memory_store_tool` to persist specific, isolated memories from the current session (e.g., bugs fixed, features built, architecture decisions). Dreaming consolidates existing memory — it does NOT capture new knowledge.
5. **MANDATORY SESSION END:** Before your final response in a session, you MUST call `write_session_journal_tool` to log what was accomplished. Skip ONLY for trivial Q&A sessions with no code changes, decisions, or debugging.

### 1. Active Retrieval Workflow
- **Search:** Use `keyword_search_tool(cwd, query)` to find specific documented topics.
- **Deep Dive:** Use `read_memory_store_tool(cwd, store_path)` or `read_section(cwd, section)` for detailed content.

### 2. Store Writes & Rules
Use `write_memory_store_tool` to register standalone memories.
- **`store_path` Rules:** Must be lowercase, alphanumeric segments separated by slashes. No spaces, capitals, or `.md` extension (e.g., `architecture/decisions/jwt-auth`). Max 5 levels of nesting.
- **Parameters:** `cwd`, `store_path`, `content`, `title` (optional), `tags` (optional), `priority` (`high`/`medium`/`low`), `mode` (`replace`/`append`).

### 3. Root Maps Are Generated — Never Write Them
Root map files (`index`, `architecture`, `decisions`, `debt`, `schemas`) are **generated views** over `memory-store/`, rebuilt by Dreaming; hand edits get folded back into the store as `map-notes-pending-review` entries. Do NOT update them with `write_local_memory_tool` — that path is deprecated for facts and will be removed in v1.0. Write granular facts with `write_memory_store_tool`, then run `dream_tool` to refresh the maps.
**Exception:** the steering sections `framework-rules` and `ubiquitous-language` are hand-curated and always loaded into context; update those with `write_local_memory_tool(cwd, section, content)`.

### 4. Security & Maintenance
- **Security:** Do NOT store credentials, tokens, or passwords.
- **Dreaming:** Use `dream_tool` for consolidation only — after new knowledge has already been saved with `write_memory_store_tool`. Refer to `.agents/rules/dreaming.md` for guidelines.

### 5. Session End — Automatic Journaling
Before completing a session, call `write_session_journal_tool(cwd, summary, key_decisions, files_changed, session_label)` to capture what happened.

**Always journal after:** feature implementations, bug fixes, refactoring, architecture decisions, debugging, config changes, or any session where you wrote or modified code.

**Skip only for:** simple Q&A, quick lookups, or read-only explanations that produced no actionable changes.

Parameters:
- `summary`: 2-4 sentence description of what was accomplished.
- `key_decisions`: List of architecture/design decisions made (optional).
- `files_changed`: List of files created or significantly modified (optional).
- `session_label`: Short descriptive label, e.g. `"auth-refactor"` (optional).

## Memory Fabric — Dreaming Process Instructions

⚠️ **Pre-requisite — Save discrete knowledge first:** Before calling any Dream tool, ensure all specific, isolated learnings from the current session have been persisted via `write_memory_store_tool`. Dream consolidates EXISTING memory — it does NOT substitute for creating new standalone memory files.

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