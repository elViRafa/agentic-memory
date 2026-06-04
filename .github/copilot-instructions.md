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

## Memory Fabric — Dreaming Process Instructions

Memory Fabric includes an optional background maintenance process called "Dreaming." As an agent, you have access to the `dream_tool` to trigger this process.

### When to trigger Dreaming
You should trigger a dream after making significant architectural changes, resolving complex bugs, or accumulating multiple smaller updates in the memory store. It helps to consolidate the memory, refresh indices, and identify contradictions.

### How to use `dream_tool`
The `dream_tool` accepts several important parameters. You must configure them correctly to actually apply changes:

* `cwd`: Absolute path to the project root.
* `mode`: 
  * `"light"` (default): Fast refresh of the index, summaries, and stale markers.
  * `"deep"`: Comprehensive review of architecture, decisions, debt, and contradictions.
* `apply`: **CRITICAL.** Set to `True` if you want the dreaming process to actually save its generated updates and summaries. If `False` (default), it will only run in a dry-run "candidate" mode.
* `llm_rewrite`: Set to `True` if you want the LLM to actively propose rewrites or patches to the memory.
* `with_eval`: Set to `True` to run an evaluation on the dreaming quality. (Requires `apply=True`).

### Example
If you just finished a major refactoring and want to update the memory indices and summaries, call:
`dream_tool(cwd="<project-root>", mode="light", apply=True)`

### Client-Driven/Split-Tool Consolidation (Avoiding Deadlocks)
If no direct LLM provider is configured (or if MCP sampling timeouts occur due to client re-entrancy limitations), you MUST run dreaming using the following split-tool protocol to let your own client-side model perform the consolidation:
1. Call `prepare_dream_payload_tool(cwd="...", mode="deep")`.
2. If the response contains `"skip_required": true`, consolidation is up-to-date; skip the remaining steps.
3. If not skipped, pass the returned `consolidation_prompt` to your own LLM model context.
4. Execute the prompt and capture the LLM's raw JSON output.
5. Call `apply_dream_results_tool(cwd="...", candidate_store="...", llm_response="...")` with the `candidate_store` value from step 1 and the raw LLM JSON response to write and apply the consolidated files.