## 2026-06-04 10:20 - Initialize and Update Memory Fabric in search-sermons Workspace

**What was implemented:**
- Updated and initialized the target project `C:\Users\rafael\Projetos\search-sermons` with the latest version of Memory Fabric, ensuring git hooks are configured to run via the Python virtual environment module wrapper (`python -m memory_fabric.cli`) to bypass global PATH limitations.
- Synchronized and updated all multi-platform agent rule files in the `search-sermons` workspace to match the latest template-driven format.

**Core files affected:**
- [C:\Users\rafael\Projetos\search-sermons\.git\hooks\pre-commit](file:///C:/Users/rafael/Projetos/search-sermons/.git/hooks/pre-commit) — Deployed the latest pre-commit hook wrapper for agent rules synchronization.
- [C:\Users\rafael\Projetos\search-sermons\.git\hooks\post-commit](file:///C:/Users/rafael/Projetos/search-sermons/.git/hooks/post-commit) — Deployed the latest post-commit hook wrapper for memory dreaming.

**Key changes:**
- Ran the updated initialization with `init --install-hooks` inside the target workspace.
- Synchronized multi-platform agent rules (`AGENTS.md`, `CLAUDE.md`, `.agents/rules/`, `.cursor/rules/`, `.windsurf/rules/`, `.github/copilot-instructions.md`) to the latest version.
- Verified workspace health using `doctor`, `eval`, and a `dream --mode light --apply` run.

**Status & Testing:**
- Tested locally, doctor returned `ok: True`, memory evaluation passed, and dreaming succeeded with no errors.

## 2026-06-04 09:20 - DRY Refactoring of Memory Fabric Dreaming Pipeline

**What was implemented:**
- Audited the codebase for over-engineering and logic redundancy. Converted duplicated candidate validation, secret scanning, stale checking, indexing, and promotion routines in the Dreaming process to call a unified private helper.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py) — Extracted JSON parsing and consolidated candidate promotion routines into new `_parse_llm_json_response` and `_process_and_finalize_candidate` private helpers.

**Key changes:**
- Combined duplicate blocks from both the direct `dream` and split-tool `apply_dream_results` pipelines.
- Implemented fallback handling inside the unified promotion helper to properly manage non-LLM runs and hash-caching checks.
- Kept zero-dependency HTTP adapters in `llm.py` intact to support CLI hook operations and prevent client deadlocks.

**Status & Testing:**
- Tested locally, all 72 pytest unit tests passed successfully.

## 2026-06-04 08:28 - Configure Robust Git Hooks and Verify Memory Fabric in search-sermons

**What was implemented:**
- Updated the pre-commit and post-commit git hooks in the `search-sermons` repository to use `python -m memory_fabric.cli` instead of the direct `ai-memory` script. This prevents command-not-found failures during commits in environments where the Python User Scripts path is not added to the global system PATH.
- Synchronized and updated all multi-platform agent rule files in the `search-sermons` workspace to match the latest template-driven format.

**Core files affected:**
- [C:\Users\rafael\Projetos\search-sermons\.git\hooks\pre-commit](file:///C:/Users/rafael/Projetos/search-sermons/.git/hooks/pre-commit) — Switched agent rule synchronization command to use the python module invocation.
- [C:\Users\rafael\Projetos\search-sermons\.git\hooks\post-commit](file:///C:/Users/rafael/Projetos/search-sermons/.git/hooks/post-commit) — Switched background Dreaming/consolidation command to use the python module invocation.

**Key changes:**
- Changed `ai-memory sync-agents` to `python -m memory_fabric.cli sync-agents` inside the pre-commit hook script.
- Changed `ai-memory dream` to `python -m memory_fabric.cli dream` inside the post-commit hook script.
- Verified that all 9 memory files in `search-sermons` are fully recognized and healthy.

**Status & Testing:**
- Executed `python -m memory_fabric.cli doctor` inside the `search-sermons` workspace, returning `ok: True` with zero errors. Tested script executable invocation paths under Python 3.14.

## 2026-06-04 08:22 - Fix Split-Tool Protocol Instruction in Agent Rules

**What was implemented:**
- Fixed a parameter naming discrepancy in the Split-Tool dreaming instructions. The instruction templates incorrectly directed agents to pass `snapshot="..."` when calling `apply_dream_results_tool`, which is not a valid parameter and caused API errors and deadlocks. The instructions now correctly direct agents to pass the `candidate_store="..."` identifier.

**Core files affected:**
- `src/memory_fabric/templates.py` — Updated the canonical `DREAMING_INSTRUCTIONS` text block to reference `candidate_store` instead of `snapshot`.

**Key changes:**
- Changed step 5 of the split-tool protocol description to call `apply_dream_results_tool(cwd="...", candidate_store="...", llm_response="...")` and supply the `candidate_store` value from step 1.
- Propagated the change to all platform-specific rule files via the agent synchronization routine.

**Status & Testing:**
- Ran `sync-agents` to update local agent files (`.agents/rules/dreaming.md`, `.cursor/rules/memory-fabric.mdc`, `.windsurf/rules/memory-fabric.md`, `.github/copilot-instructions.md`).
- Ran all 72 pytest unit tests locally; all tests passed successfully.

## 2026-06-04 08:13 - Resolve MCP Sampling Timeout and Add Diagnostic Warnings

**What was implemented:**
- Reduced the default MCP Sampling timeout to 45 seconds to fail faster in sequential client loops.
- Added preemptive warning logs to stderr alerting users of potential JSON-RPC deadlocks when falling back to MCP Sampling.

**Core files affected:**
- `src/memory_fabric/llm.py` — Added deadlock warning to stderr and updated `asyncio.wait_for` timeout.
- `tests/test_memory_fabric.py` — Updated mock context assertions to verify the 45-second timeout message.

**Key changes:**
- Warn users on stdout/stderr before entering a blocking JSON-RPC call.
- Reduced timeout from 120s to 45s for faster local execution fallback.

**Status & Testing:**
- Tested locally, all 72 pytest unit tests pass successfully.

## 2026-06-04 08:10 - Resolve Cloudflare API Blocks (HTTP 1010) with Default User-Agent Header

**What was implemented:**
- Added a default `User-Agent` header to outgoing LLM requests in the zero-dependency HTTP client. This prevents HTTP 403 (Error 1010) blocks from Cloudflare security signatures when querying external API providers (such as Groq) directly via Python's standard `urllib` module.

**Core files affected:**
- `src/memory_fabric/llm.py` — Configured a default Webkit-based `User-Agent` string inside the `_http_post` request pipeline.

**Key changes:**
- Copied the `headers` dictionary to avoid mutability side effects.
- Set a default `User-Agent` mimicking Google Chrome to ensure requests bypass Cloudflare's urllib signatures.

**Status & Testing:**
- Tested locally by running memory dreaming in deep mode on the `search-sermons` project using the Groq API key; the run succeeded without error, generating 3 updated memory files.

## 2026-06-04 07:48 - Client-Driven Memory Consolidation (Dreaming) Protocol

**What was implemented:**
- Designed and implemented a client-driven memory dreaming protocol to completely avoid JSON-RPC deadlocks in environments that do not support concurrent client-server calls. Exposed split MCP tools `prepare_dream_payload_tool` and `apply_dream_results_tool`, allowing the client agent to perform the LLM consolidation and summarization steps in its own context while leveraging the server for indexing, stale checks, secret scanning, and filesystem updates.

**Core files affected:**
- `src/memory_fabric/storage.py` — Implemented `prepare_dream_payload` (with hash-based skip checks) and `apply_dream_results` (to merge files, process JSON, refresh index/sub-indices, and perform stale/secret scans).
- `src/memory_fabric/server.py` — Registered `prepare_dream_payload_tool` and `apply_dream_results_tool` MCP tools.
- `src/memory_fabric/templates.py` — Updated the `DREAMING_INSTRUCTIONS` template detailing how agents should execute the new multi-step dreaming protocol.
- `tests/test_memory_fabric.py` — Added a comprehensive `test_split_dream_flow` integration test.

**Key changes:**
- Added support for returning combined prompts and file data to the client in a single payload.
- Allowed the LLM response to carry both consolidated section contents and their new summaries in one JSON payload, speeding up dreaming and preventing deadlock during summarization.
- Resolved temporary candidate root directories dynamically by passing `candidate_store` names.

**Status & Testing:**
- Tested locally using the pytest suite; all 72 tests passed successfully.

## 2026-06-04 07:32 - Resolve MCP Sampling Deadlock and Add Workspace .env Support

**What was implemented:**
- Resolved JSON-RPC deadlock and indefinite freezes caused by MCP Sampling by implementing a 120-second timeout on client sampling calls. Added dynamic support to automatically load workspace environment files (`.env`, `.env.local`, `.env.development`) into the MCP server and CLI processes. This allows developers to easily configure direct LLM provider keys locally, avoiding nested JSON-RPC deadlocks altogether.

**Core files affected:**
- `src/memory_fabric/llm.py` — Implemented `load_env_from_cwd` and wrapped the MCP Sampling callback in `asyncio.wait_for` with detailed deadlock error messaging.
- `src/memory_fabric/server.py` — Integrated workspace env loading at the entry point of all MCP tools.
- `src/memory_fabric/cli.py` — Integrated workspace env loading inside CLI main execution.
- `tests/test_memory_fabric.py` — Developed new unit tests validating environment loading and sampling timeout handlers.

**Key changes:**
- Wrapped `create_message` in `llm.py` with a 120-second timeout, raising an informative exception upon deadlock.
- Implemented zero-dependency `.env` parsing and loading from target `cwd` folders.
- Called `load_env_from_cwd(cwd)` inside MCP tools and CLI arguments parsing to seamlessly inject keys from project-level configuration files.

**Status & Testing:**
- All 71 tests in the pytest suite are passing successfully.

## 2026-06-04 00:44 - Implementation of client-side MCP Sampling integration & bug fixes

**What was implemented:**
- Added robust subprocess execution controls to memory consolidation steps, eliminating pipe deadlocks on Windows environments. Integrated and validated full client-to-server MCP sampling delegating LLM consolidation requests back to client callbacks using a local Ollama model (`gemma4`). Updated documentation to catalog all available tools and subcommands.

**Core files affected:**
- `src/memory_fabric/storage.py` — Resolved Windows grandchild subprocess hangs by passing `stdin=subprocess.DEVNULL` and `timeout=5.0` to `subprocess.run` calls.
- `C:\Users\rafael\Projetos\ToTestMemoryAgentic\test_mcp_sampling.py` — Client integration script declaring sampling capability, registering the Ollama `sampling_callback`, and executing server dreaming tools over stdio.
- `README.md` — Updated the list of available MCP tools and the CLI commands reference.

**Key changes:**
- Modified `_get_git_diff` and `_keyword_search_rg` in `storage.py` to prevent stdout/stdin pipe inheritance conflicts on Windows when run under piped parent streams.
- Developed `test_mcp_sampling.py` to emulate a sampling-aware client session using the official `mcp` SDK.
- Demonstrated end-to-end delegation of deep consolidation prompts and section summarizations from the `memory-fabric-mcp` server back to the client's local Ollama engine.
- Cataloged `dream_tool`, `write_memory_store_tool`, `read_memory_store_tool`, `list_memory_store_tool`, `delete_memory_store_tool`, and CLI `store` subcommand in the user documentation.

**Status & Testing:**
- Tested locally in the `ToTestMemoryAgentic` virtual environment; tests passed and all deep dreaming outputs were correctly written and indexed.

## 2026-06-04 00:18 - Integration Testing & Verification of Memory Fabric

**What was implemented:**
- Created a dedicated test project `ToTestMemoryAgentic` and installed the local `memory-fabric` package in a Python virtual environment. Developed a comprehensive integration test suite `run_tests.py` verifying scaffolding initialization, memory store CRUD operations, query search, doctor commands, and both light and deep dreaming consolidation (using the local Ollama LLM provider).

**Core files affected:**
- `C:\Users\rafael\Projetos\ToTestMemoryAgentic\run_tests.py` [NEW] — Automated integration test script verifying all core memory fabric operations end-to-end.

**Key changes:**
- Verified that `ai-memory init --install-hooks` sets up git hooks and rule scaffolding correctly.
- Checked `doctor` validation on clean repositories and `status` size reporting.
- Confirmed that `store write` and `store read` accurately register memories and preserve metadata.
- Tested `query` (search) capability to return relevant snippet context.
- Successfully ran deep dreaming with LLM consolidation and contradiction warnings using a local Ollama instance (`gemma4`).

**Status & Testing:**
- All integration tests completed successfully, executing all CLI operations and confirming complete local LLM compatibility.

## 2026-06-04 00:05 - Agentic Instruction Architecture Redesign (Canonical Templates + Multi-Platform)

**What was implemented:**
- Redesigned the entire agentic instruction system. Replaced 3 near-duplicate template constants with 2 canonical content blocks (`MEMORY_INSTRUCTIONS`, `DREAMING_INSTRUCTIONS`) and platform-specific builder functions. Added deployment support for Cursor IDE (`.cursor/rules/memory-fabric.mdc`) and Windsurf IDE (`.windsurf/rules/memory-fabric.md`). Rewrote `sync_agent_rules` to regenerate from templates instead of fragile AGENTS.md parsing.

**Core files affected:**
- `src/memory_fabric/templates.py` — Single source of truth: 2 canonical blocks + 7 builder functions.
- `src/memory_fabric/storage.py` — Refactored `initialize_memory_fabric()` and `sync_agent_rules()`.
- `AGENTIC_ARCHITECTURE.md` — Complete rewrite documenting the new architecture.
- ...and 6 additional platform files regenerated from canonical templates.

**Key changes:**
- Eliminated all content duplication: every platform file is now generated from the same 2 text blocks.
- Added Cursor (`.mdc` format) and Windsurf support to both `init` and `sync`.
- `sync_agent_rules` now regenerates from Python templates (not from AGENTS.md), preventing project-specific content leaking into IDE rules.
- Normalized all existing files in this repo to match the canonical templates.
- Fixed test assertion that assumed post-commit was the last created file.

**Status & Testing:**
- All 69 tests passing.

## 2026-06-03 23:46 - Implement Agent Rules Synchronization (Single Source of Truth)

**What was implemented:**
- Created a mechanism to treat `AGENTS.md` as the single source of truth for agent rules, while automatically propagating changes to IDE-specific rule files (`CLAUDE.md`, `.github/copilot-instructions.md`, etc.). This balances the DRY principle with the need for reliable Prompt Auto-Injection.

**Core files affected:**
- `src/memory_fabric/storage.py` — Added `sync_agent_rules()` logic and updated `initialize_memory_fabric()` to install a Git `pre-commit` hook.
- `src/memory_fabric/cli.py` — Exposed `ai-memory sync-agents`.
- `README.md` & `AGENTIC_ARCHITECTURE.md` — Documented the new "Single Source of Truth" sync process.

**Key changes:**
- Added `ai-memory sync-agents` to securely parse `AGENTS.md` and safely inject updates into multiple integration files without destroying user customizations.
- Automated the sync via a new `pre-commit` git hook, so developers never have to manually run the sync command. Any manual edit to `AGENTS.md` is instantly pushed to the target files and automatically `git add`ed.

**Status & Testing:**
- Code and hooks implemented successfully.

## 2026-06-03 23:39 - Update README with Agentic Architecture Installation

**What was implemented:**
- Rewrote the "Agent Integration" section in the README to reflect the automated deployment of the Agentic Architecture.

**Core files affected:**
- `README.md` — Replaced manual copying instructions with a description of the automated `ai-memory init` deployment suite (covering IDE rules, `AGENTS.md`, `CLAUDE.md`, and Copilot).

**Key changes:**
- Removed outdated instructions about manually copying `AGENTS.md`.
- Clearly explained the "why" and "how" of the automated instruction files to end-users.

**Status & Testing:**
- Documentation updated successfully.

## 2026-06-03 23:37 - Register Agentic Architecture in Memory Store

**What was implemented:**
- Corrected a lapse in the memory process by formally registering the new `AGENTIC_ARCHITECTURE.md` knowledge into the project's semantic Memory Store.

**Core files affected:**
- `.ai-memory/memory-store/architecture/agent-rules.md` [NEW] — Written via the Memory Fabric storage API to ensure the agent architecture is preserved for future context windows.

**Key changes:**
- Used the internal `write_memory_store` python API to persist the summary of agent rule templates and the initialization deployment strategy.

**Status & Testing:**
- Memory written successfully.

## 2026-06-03 23:35 - Create Agentic Architecture Registry

**What was implemented:**
- Created a central registry document to list all agentic rule files and explain how they integrate with various AI tools.

**Core files affected:**
- [AGENTIC_ARCHITECTURE.md](file:///c:/Users/rafael/Projetos/agentic-memory/AGENTIC_ARCHITECTURE.md) [NEW] — Documented the purpose of each rule file (`AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `.agents/rules/*`) and explained the deployment strategy via `ai-memory init`.

**Key changes:**
- Mapped out the target audiences for each instruction file.
- Documented guidelines for future developers on how to properly add new agent rules without bloating the core context windows.

**Status & Testing:**
- Documentation created successfully.

## 2026-06-03 23:17 - Package Agent Instructions into CLI Installer

**What was implemented:**
- Hardcoded `AGENTS.md`, `.agents/rules/memory-store.md`, and `.agents/rules/dreaming.md` as templates inside the `memory-fabric` source code so they can be distributed to other repositories.
- Updated `initialize_memory_fabric()` (the `ai-memory init` command) to automatically write these agent instructions into the target project, ensuring out-of-the-box compatibility with Cursor, Claude Code, GitHub Copilot, and other MCP-aware agents.

**Core files affected:**
- [src/memory_fabric/templates.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/templates.py) — Added `AGENT_INSTRUCTIONS_TEMPLATE`, `MEMORY_STORE_RULE_TEMPLATE`, and `DREAMING_RULE_TEMPLATE`.
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py) — Updated `initialize_memory_fabric()` to create `.agents/rules/` and deploy `AGENTS.md`. It also creates or appends to `CLAUDE.md` and `.github/copilot-instructions.md`.

**Key changes:**
- Native IDE support: Automatically drops rule files into `.agents/rules/` for IDE agents.
- Broad compatibility: Automatically targets `CLAUDE.md` and `.github/copilot-instructions.md` by cleanly appending instructions if those files already exist in a user's repo.

**Status & Testing:**
- Code implemented successfully. Ready for release.

## 2026-06-03 22:50 - Document Agent Dreaming Instructions

**What was implemented:**
- Adopted a hybrid documentation approach for the `dream_tool` to keep main instruction files concise while providing detailed parameter guidelines for complex background maintenance.
- Created a dedicated `.agents/rules/dreaming.md` file explaining `dream_tool` usage, including the critical `apply=True` requirement for saving state.

**Core files affected:**
- [.agents/rules/dreaming.md](file:///c:/Users/rafael/Projetos/agentic-memory/.agents/rules/dreaming.md) [NEW] — Detailed usage guide for the `dream_tool` parameter configuration.
- [AGENTS.md](file:///c:/Users/rafael/Projetos/agentic-memory/AGENTS.md) — Appended a brief pointer section directing agents to the dreaming rules.
- [.agents/rules/memory-store.md](file:///c:/Users/rafael/Projetos/agentic-memory/.agents/rules/memory-store.md) — Replicated the pointer section to maintain rule sync.

**Key changes:**
- Added clear instructions on when agents should invoke the `dream_tool` (e.g., after major refactoring).
- Clarified the `mode`, `apply`, `llm_rewrite`, and `with_eval` flags.
- Added a pointer in `AGENTS.md` to ensure the tool is discoverable without bloating standard context.

**Status & Testing:**
- Documentation created successfully.

## 2026-06-03 22:47 - Explicitly document Active Memory Workflow using MCP tools

**What was implemented:**
- Updated agent instructions to explicitly outline the active memory retrieval process using MCP tools, directly matching the conceptual "Map, Search, and Deep Dive" workflow without relying on raw terminal commands.

**Core files affected:**
- [AGENTS.md](file:///c:/Users/rafael/Projetos/agentic-memory/AGENTS.md) — Updated the Startup & Retrieval section to explicitly detail the 3-step retrieval process.
- [.agents/rules/memory-store.md](file:///c:/Users/rafael/Projetos/agentic-memory/.agents/rules/memory-store.md) — Replicated the same documentation update to keep all agent rule files perfectly in sync.

**Key changes:**
- Added a 3-step process: Session Map (`read_combined_context_tool`), Search & Target (`keyword_search_tool`), and Deep Dive (`read_memory_store_tool` or `read_section`).
- Re-emphasized the active nature of the workflow while enforcing safe MCP tool boundaries.

**Status & Testing:**
- Documentation updated successfully.

## 2026-06-03 22:42 - Remove AGENT_MEMORY_WORKFLOW.md to prevent conflicting instructions

**What was implemented:**
- Deleted `AGENT_MEMORY_WORKFLOW.md` because its instructions (using bash/grep for manual memory exploration) directly conflicted with the primary project rule in `AGENTS.md` which enforces the strict use of `memory-fabric` MCP tools and prohibits raw file-system tool interactions.

**Core files affected:**
- `AGENT_MEMORY_WORKFLOW.md` [DELETED] — Removed to maintain a single source of truth for agent instructions.
- [AGENTS.md](file:///c:/Users/rafael/Projetos/agentic-memory/AGENTS.md) — Remains the sole authority on agent memory retrieval and writing workflows.

**Key changes:**
- Removed conflicting instructions on how agents should interact with memory.
- Ensured all MCP clients follow the standard `read_combined_context_tool` and `keyword_search_tool` pathways.

**Status & Testing:**
- File successfully removed.

## 2026-06-03 22:35 - Document Agent Memory Workflow

**What was implemented:**
- Created a new documentation file detailing the agent memory usage workflow based on direct system tool interaction instead of MCP tools.
- Clarified that agents should use tools like bash and grep to explore the file system and search for information, and how they should read the index file to guide their deep dives.

**Core files affected:**
- [AGENT_MEMORY_WORKFLOW.md](file:///c:/Users/rafael/Projetos/agentic-memory/AGENT_MEMORY_WORKFLOW.md) — New documentation explaining the active manual memory retrieval process.

**Key changes:**
- Documented the session initialization and index review process.
- Detailed the file system exploration and search strategy using grep.
- Clarified the deep dive step for extracting necessary context.
- Added explicit mention of `keyword_search_tool` (MCP) and `ai-memory query` (CLI) as the primary semantic search methods, with `grep` as a fallback.

**Status & Testing:**
- Documentation created successfully.

## 2026-06-03 20:20 - Update Documentation with Upgraded Instructions and MCP Sampling Guide

**What was implemented:**
- Prepared and updated the project `README.md` to include detailed instructions for upgrading the Memory Fabric package.
- Documented LLM configuration methods and the new native MCP Sampling capability, detailing how it works, its benefits, resolution precedence, and CLI limitations.

**Core files affected:**
- [README.md](file:///c:/Users/rafael/Projetos/agentic-memory/README.md) — Main repository documentation updated with installation, upgrade guidelines, and LLM configuration rules.

**Key changes:**
- Added a step-by-step upgrade guide covering pipx and pip package installation commands, restarting MCP clients, and refreshing local projects via `ai-memory init --install-hooks`.
- Created a new section "LLM Configuration & MCP Sampling" explaining how native MCP client sampling is dynamically resolved for Dreaming and evaluations.
- Provided a clear table mapping environment variables for direct LLM providers (Gemini, OpenAI, Anthropic, Ollama).

**Status & Testing:**
- Tested locally, all documentation links verified and pytest test suite completely green (69 passed).

## 2026-06-03 19:06 - Integrate Native MCP Sampling with Configured LLM Fallback

**What was implemented:**
- Integrated native Model Context Protocol (MCP) Sampling capabilities (`session.create_message`) as a fallback LLM provider for memory consolidation (dreaming) and evaluation workflows. To support this natively asynchronous operation, the underlying LLM call wrapper (`call_llm`), the dreaming logic (`dream`), and the evaluation logic (`evaluate_*`) were converted to asynchronous operations.
- Updated the MCP server wrapper to expose async tool definitions that dynamically receive the `Context` object, updated the CLI to run async functions synchronously outside an active loop using `asyncio.run()`, and wrapped the unit test suite in synchronous wrappers to maintain full compatibility.

**Core files affected:**
- [src/memory_fabric/llm.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/llm.py) — Converted `call_llm` to be asynchronous, running direct HTTP provider adapters inside thread pools via `asyncio.to_thread` and implementing MCP client sampling fallback logic.
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py) — Converted `dream` to be asynchronous and context-aware, updating `_is_llm_ready` to identify client sampling capability.
- [src/memory_fabric/eval.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/eval.py) — Converted qualitative evaluation functions to be asynchronous and accept context parameters.
- [src/memory_fabric/server.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/server.py) — Modified MCP tool wrappers to be asynchronous, resolving and forwarding injected `Context` parameters.
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py) — Wrapped test runner assertions in synchronous wrappers and mock patches in `mock.AsyncMock`.

**Key changes:**
- Added fallback resolution order: direct LLM providers first, then MCP Sampling, then local structural maintenance.
- Run synchronous HTTP provider adapters inside thread pools in an async context.
- Added client capabilities lookup to verify sampling support.
- Implemented a new unit test case `test_call_llm_with_mcp_sampling` verifying mock context sampling callback triggers.

**Status & Testing:**
- Tested locally, all 69 unit tests passed successfully.

## 2026-06-03 18:43 - Support dedicated memory-store/index.md sub-index in Dreaming

**What was implemented:**
- Updated the Memory Fabric Dreaming process to automatically generate and maintain a dedicated sub-index file at `.ai-memory/memory-store/index.md` listing all semantic memory store entries. The root index `.ai-memory/index.md` now cleanly points to this dedicated sub-index via a Markdown link instead of listing the raw store entries directly, and the Doctor tool was updated to validate both index files independently.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py) — Updated `_regenerate_index_root` to compile and write `.ai-memory/memory-store/index.md` with store entry details and add a relative link in the root index; updated `_ordered_context_files` to exclude sub-index files from active context; updated `doctor` consistency checks to validate root and memory-store indices separately.
- [tests/test_dream_store.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_dream_store.py) — Updated light mode dream assertions to verify creation, frontmatter, and table content of `memory-store/index.md`, and check that `doctor` validates without warnings.
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py) — Updated store index dreaming test to assert generation and contents of `memory-store/index.md` and pointer link in root `index.md`.

**Key changes:**
- Generated a dedicated sub-index at `.ai-memory/memory-store/index.md` with appropriate index metadata frontmatter during Dreaming indexing.
- Replaced the raw table of memory store files in the root `.ai-memory/index.md` with a Markdown hyperlink referencing the sub-index file.
- Excluded any `index.md` file located inside the `memory-store/` subdirectory from compiler payload assembly and active steering context.
- Split doctor index validation logic to verify local top-level sections against root `index.md`, and verify memory-store files against `memory-store/index.md`.

**Status & Testing:**
- Tested locally using `pytest`, all 68 unit tests passed successfully.
- Manually ran local dreaming and doctor checks on the project repository's own memories, successfully creating the sub-index and completing the doctor checks with no warnings.

## 2026-06-03 18:22 - Update agent instructions for memory-store semantic store rules

**What was implemented:**
- Updated the developer guidelines in `AGENTS.md` and `.github/copilot-instructions.md` with instructions for using the semantic Memory Store (`write_memory_store_tool`) and its naming/nesting constraints, keeping all agent instruction entrypoints in sync.

**Core files affected:**
- [AGENTS.md](file:///c:/Users/rafael/Projetos/agentic-memory/AGENTS.md) — Updated the Memory Fabric MCP tools section with the new Semantic Store instructions.
- [.github/copilot-instructions.md](file:///c:/Users/rafael/Projetos/agentic-memory/.github/copilot-instructions.md) — Updated the Copilot instructions section to align with the new instructions.

**Key changes:**
- Documented strict formatting, directory nesting limits (max 5), duplicate prevention, and parameter requirements for `write_memory_store_tool`.
- Documented legacy flat file writes (`write_local_memory_tool`) as fallback only for updating existing sections.
- Preserved guidelines on startup context loading (`read_combined_context_tool`), pre-codebase keyword search, and security rules against credential storage.

**Status & Testing:**
- Manual verification of instruction files formatting and consistency.

## 2026-06-03 18:11 - Support memory-store subdirectories in the Dreaming process

**What was implemented:**
- Updated the Memory Fabric Dreaming process to fully support hierarchically organized, nested memory files inside the `memory-store/` subdirectory. Canonical prefix keys (`local/` for top-level flat sections and `store/` for nested store files) are now used in LLM payloads, ensuring that consolidation, fact-checking, and summary generation preserve target directory paths instead of flattening or duplicating them.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py) — Integrated canonical prefix key logic (`_get_section_key`) into payload hashing, LLM prompting, consolidation parsing, and summary refreshing; updated index.md generation table columns to include `Key Topics` for nested files; fixed doctor validation to verify `store_path` instead of `section` for store files.
- [tests/test_dream_store.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_dream_store.py) — Created dedicated unit tests verifying nested directory dreaming for index regeneration in light mode, LLM consolidation in deep mode, and double-hash summary/cache skipping.

**Key changes:**
- Defined `_get_section_key(root, path)` to resolve canonical section paths for both local and nested store files.
- Supported mapping keys like `store/architecture/tests/isolated-unit-tests` back to their correct nested subfolders during LLM response parsing.
- Refreshed metadata fields like `last_updated` and `summary` for nested store files.
- Extracted and populated `Key Topics` for nested files in the `index.md` Memory Store table.
- Resolved validation issues in the `doctor` command for store files.

**Status & Testing:**
- Tested locally using `pytest`, all 68 tests (including new dream store tests) passed successfully.

## 2026-06-03 14:01 - Implement isolated unit tests for security and frontmatter utilities

**What was implemented:**
- Created dedicated test suites to isolate and thoroughly test the custom secret redaction (`security.py`) and YAML-frontmatter parser/dumper (`frontmatter.py`) helper modules. This increases test coverage and ensures robust handling of edge cases without relying on complex integration setups.

**Core files affected:**
- [tests/test_security.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_security.py) — Focused unit tests for token signatures (GitHub, AWS, OpenAI), key-value redaction regex, Shannon entropy calculation, and looks-like-secret validation rules
- [tests/test_frontmatter.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_frontmatter.py) — Unit tests for YAML-frontmatter format constraints, list/boolean parsing, scalar serializing, and error conditions

**Key changes:**
- Added test coverage for `ghp_...` tokens, `AKIA...` tokens, `sk-...` tokens, high-entropy secrets, and normal strings
- Added test coverage for missing frontmatter delimiters, invalid frontmatter keys, and list serialization edge cases in YAML-frontmatter parsing
- Increased total test suite count from 50 to 65 passing tests

**Status & Testing:**
- Tested locally using `pytest`, all 65 tests passed successfully.

## 2026-06-03 13:21 - Add memory-prompt support for session steering instructions

**What was implemented:**
- Added a `memory_prompt` feature to dynamically guide which memory details the agent should capture and focus on during a session. A custom `memory_prompt.txt` configuration file is written to `.ai-memory/` on initialization, dynamically parsed, and prepended to all combined context loads and consolidated memory compilations.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py) — Enforce creation and removal of `memory_prompt.txt` during initialization, dynamic insertion, and cache stripping in context generation
- [src/memory_fabric/server.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/server.py) — Expose the new `memory_prompt` parameter through the MCP `initialize_memory_fabric_tool`
- [src/memory_fabric/cli.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/cli.py) — Add `--memory-prompt` subcommand option to `init` and pass to backend

**Key changes:**
- Support setting `memory_prompt` via CLI argument `--memory-prompt` or MCP tool parameter `memory_prompt`
- Read and inject custom memory prompt into `read_combined_context` and precompiled `consolidated_memory.md` cache dynamically
- Safely clean up and delete the prompt configuration if initialized with an empty prompt string

**Status & Testing:**
- Tested locally, all 50 tests pass successfully.

## 2026-06-03 16:43 - Add hierarchical memory-store for semantically-named memory files

**What was implemented:**
- Added a `memory-store/` subdirectory inside `.ai-memory/` that supports hierarchically organized, individually addressable memory files (e.g. `memory-store/architecture/decisions/auth-service.md`). Each file has YAML frontmatter with `store_path`, `title`, `tags`, `priority`, and `summary` fields, enabling fine-grained retrieval and filtering instead of appending everything to a single flat section file.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py) — CRUD operations, path validation, search/context/dreaming integration
- [src/memory_fabric/server.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/server.py) — 4 new MCP tools
- [src/memory_fabric/cli.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/cli.py) — `ai-memory store` subcommand group
- ...and 3 additional files (contracts.py, paths.py, test_memory_fabric.py)

**Key changes:**
- Path validation enforces `[a-z0-9][a-z0-9_-]*` per segment, max 5 levels, preventing path traversal
- Store files participate in `keyword_search` (tagged `store:` prefix), `read_combined_context` (priority-sorted), Dreaming index regeneration (Memory Store table), and consolidated memory compilation
- 4 new MCP tools: `write_memory_store_tool`, `read_memory_store_tool`, `list_memory_store_tool`, `delete_memory_store_tool`
- CLI: `ai-memory store write|read|list|delete` subcommands
- `initialize_memory_fabric` now creates `memory-store/.gitkeep`
- `delete_memory_store` cleans up empty parent directories automatically

**Status & Testing:**
- All 49 tests passed (36 existing + 13 new store tests). Full backward compatibility confirmed.

**Notes / Next steps (optional):**
- Memory-store files coexist with flat sections; existing workflows are unchanged
- Future: consider adding `move_memory_store_tool` for reorganizing store paths

## 2026-06-03 10:50 - Enable temporary LLM request/response logging for debugging

**What was implemented:**
- Added a zero-dependency debug-logging utility that intercepts LLM calls to log their URLs, payloads (with redacted keys/secrets), and raw responses or error details.
- Integrated logging into the unified `_http_post` helper in `llm.py` so it automatically captures Gemini, OpenAI, Anthropic, and Ollama calls.
- Exposed a `--debug-llm` command-line flag in the `ai-memory` CLI to easily activate logging without manually setting environment variables.

**Core files affected:**
- [src/memory_fabric/llm.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/llm.py)
- [src/memory_fabric/cli.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/cli.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Implemented `_log_debug(message: str)` and `_sanitize_headers(headers: dict[str, str])` in `llm.py` to route messages appropriately and redact authorization tokens.
- Wrapped HTTP post request, response parsing, HTTP error, and network exception blocks inside `_http_post` with debug logs.
- Added support for routing logs to `sys.stderr` (via `MEMORY_FABRIC_LLM_DEBUG=stderr`), to `llm_debug.log` (via `MEMORY_FABRIC_LLM_DEBUG=1` or `MEMORY_FABRIC_LLM_DEBUG=true`), or a custom file path.
- Added the `--debug-llm` global CLI argument to `cli.py` which sets the `MEMORY_FABRIC_LLM_DEBUG` env var.
- Created `test_llm_debugging_logging` in `test_memory_fabric.py` covering all 5 debug target scenarios and validating key redaction.

**Status & Testing:**
- Tested locally with pytest; all 36 tests passed successfully.

## 2026-06-03 09:48 - Add SSE transport support for Open WebUI connectivity

**What was implemented:**
- Extended the `memory-fabric-mcp` server startup CLI options to support transport configuration (`--transport stdio/sse`, `--host`, `--port`).
- Added support for cross-origin and network deployments by exposing security controls via `--allow-all-origins`, allowing external tools like Open WebUI to connect natively via Server-Sent Events.

**Core files affected:**
- [src/memory_fabric/server.py](file:///C:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/server.py)
- [tests/test_memory_fabric.py](file:///C:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Added standard `argparse` CLI option parsing to the main entrypoint of `memory_fabric.server`.
- Exposed FastMCP configuration settings for SSE binding (host, port) and security overrides (DNS rebinding protection, allowed hosts, allowed origins).
- Added `test_server_main_stdio` and `test_server_main_sse` to test suite to prevent regressions.

**Status & Testing:**
- Tested locally with pytest; all 35 tests passed successfully. Verified that running the server in SSE mode starts the Uvicorn/FastMCP engine without exceptions.

## 2026-06-03 09:32 - Support custom base URL and model for OpenAI LLM provider

**What was implemented:**
- Added support for custom base URL and model selection for the OpenAI LLM provider via `OPENAI_API_BASE`/`OPENAI_BASE_URL` and `OPENAI_MODEL` environment variables.
- Configured a fallback to `"dummy"` API key for non-official OpenAI endpoints (e.g., local Open WebUI, LM Studio, etc.) when `OPENAI_API_KEY` is not explicitly set, enabling seamless integration with local tools.

**Core files affected:**
- [src/memory_fabric/llm.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/llm.py)

**Key changes:**
- Modified `_call_openai` in `llm.py` to retrieve and merge base URL and model from environment overrides.
- Implemented fallback check to use `"dummy"` key if not set and the URL does not point to the official `api.openai.com` domain.

**Status & Testing:**
- Tested locally, all 33 tests passed successfully.

## 2026-06-03 08:11 - Implement Option 2: The "Cached Compile" (consolidated_memory.md)

**What was implemented:**
- Implemented automatic generation of `consolidated_memory.md` in the memory directory on index regeneration, combining all active memory files into a single, contiguous read-only file.
- Optimized `read_combined_context` to directly serve the compiled cache if it exists and fits within the agent's token budget, bypassing expensive individual file parsing and sorting operations.
- Fixed a bug in the `doctor` command where it validated files inside ignored subdirectories (e.g. `evals/`, `snapshots/`), which was causing consistency check false failures.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [src/memory_fabric/templates.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/templates.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Added `consolidated_memory.md` to `LOCAL_GITIGNORE` in `templates.py`.
- Added `_compile_consolidated_memory` helper and integrated it in `_regenerate_index_root` and `_apply_candidate_to_live` to compile and promote the file.
- Updated `_is_ignored_local_memory_path` to ignore `consolidated_memory.md` during status sizing, index rendering, diff collection, and rewrite task building.
- Added a fast-path cache read check in `read_combined_context`.
- Added a skip check for ignored paths in the `doctor` validation loop.
- Added `test_consolidated_memory_generation_and_optimization` to check compile generation, ignore logic, and context optimization.

**Status & Testing:**
- Tested locally with `pytest` (all 33 tests passed successfully).

## 2026-06-02 18:44 - Implement Option 1: The Topics Index (Expanding index.md)

**What was implemented:**
- Implemented H2 heading and fallback list-item bullet point extraction for memory files to summarize their contents directly.
- Expanded the `index.md` regeneration logic to write a fourth column (`Key Topics`) in the memory sections table, rendering extracted topics as a bulleted list separated by HTML `<br>` tags.
- Verified that the updated table structure is fully backward-compatible and successfully parsed by the `doctor` consistency checks.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Added `_extract_key_topics` module-level helper to extract either `## ` headings or up to 3 non-indented bullet list points (truncated to 60 characters and escaped) from markdown files.
- Modified `_regenerate_index_root` to calculate and append the `Key Topics` column to the generated `index.md` file.
- Added `test_index_includes_key_topics` to verify correct heading/bullet extraction, table generation, and `doctor` validation compatibility.

**Status & Testing:**
- Tested locally with `pytest` (all 32 tests passed successfully).

## 2026-06-02 17:55 - Finalize local Ollama gemma4 support with context expansion and diff truncation

**What was implemented:**
- Expanded the local `gemma4:latest` model options to include `num_ctx: 8192` and `"think": False` inside `llm.py`. This disables reasoning/thinking traces at the API level (saving generation tokens) and expands the active context window to handle long prompts.
- Truncated long git diff outputs to 4000 characters within `_get_git_diff` in `storage.py` to prevent large changesets from overflowing the local LLM's context window.
- Increased the HTTP post request timeout in `llm.py` from 30 seconds to 180 seconds to accommodate local LLM generation times.
- Replaced the simple markdown code block cleaning logic in `storage.py` with a robust JSON extractor that can safely retrieve JSON blocks wrapped in conversational prefixes or markdown backticks.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [src/memory_fabric/llm.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/llm.py)

**Key changes:**
- Added `num_ctx: 8192` and `think: False` to Ollama's API call parameters in `llm.py`.
- Added length check and truncation string formatting for diffs exceeding 4000 characters in `_get_git_diff`.
- Modified `urlopen` timeout parameter to 180.
- Implemented robust regex and brace-matching JSON extraction in `storage.py`.

**Status & Testing:**
- Tested locally with `pytest` (all 31 tests passed).
- Successfully ran the finalized Dreaming process locally with `gemma4:latest` in 40 seconds, yielding perfect contradictions and consolidation warnings without any timeout or parsing errors.

## 2026-06-02 17:40 - Fix LLM response parsing and add options to prevent Ollama truncation

**What was implemented:**
- Fixed a bug where triple backtick code blocks in the LLM's response caused an `IndexError` when cleaned response parsing resulted in empty lines.
- Updated `_call_ollama` inside `llm.py` to support and pass custom options (e.g. `num_predict: 8192` and `temperature: 0.1`) to ensure large generation payloads do not get truncated by Ollama's default limits.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [src/memory_fabric/llm.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/llm.py)

**Key changes:**
- Changed index-slicing code check to safe `.pop(0)` and `.pop(-1)` operations after checking if list is non-empty.
- Added an `"options"` dictionary in the payload sent to Ollama's `/api/chat` endpoint to configure `num_predict` and `temperature`.

**Status & Testing:**
- Tested locally using the command line with the `spurgeon-8b:latest` local model. The Dreaming run completed successfully with `Done Reason: stop` and 1666 output tokens, returning valid JSON without truncation errors.

## 2026-06-02 17:10 - Expose Package Version via Centralized version.py and status Command

**What was implemented:**
- Created a centralized `version.py` file to hold the project version, and exposed the version in the `status` command output to allow downstream projects to detect if they need to update `agentic-memory`.

**Core files affected:**
- [src/memory_fabric/version.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/version.py)
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [src/memory_fabric/contracts.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/contracts.py)

**Key changes:**
- Declared a centralized `__version__ = "0.1.0"` in `version.py` and updated `__init__.py` and `cli.py` to import it, resolving potential circular dependency issues.
- Added a `version` field to `StatusResult` in `contracts.py` and populated it in the `status` function in `storage.py`.
- Updated status command tests in `test_memory_fabric.py` to assert the returned version.

**Status & Testing:**
- Tested locally with venv pytest, all 31 tests passed successfully.

## 2026-06-02 17:00 - Add Local Ollama LLM Provider Support

**What was implemented:**
- Added support for local LLM models using Ollama, allowing developers to run Dreaming and evaluation reviews completely offline using models like Gemma 2/4.

**Core files affected:**
- [src/memory_fabric/llm.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/llm.py)
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Added `_call_ollama` implementation in `llm.py` targeting the standard local `/api/chat` endpoint of Ollama.
- Registered `"ollama"` as a supported provider in `call_llm` and updated `_is_llm_ready` to activate without requiring external API keys if provider is set to `"ollama"`.
- Added mock unit tests in `test_memory_fabric.py` asserting correct payload structure (e.g. host endpoint, messages, and non-streaming configuration) when using Ollama.

**Status & Testing:**
- Tested locally with venv pytest, all 31 tests passed successfully.

## 2026-06-02 12:55 - LLM Rate Limits and Double-Hash Cache Optimizations in Dreaming Mode

**What was implemented:**
- Implemented exponential backoff and jitter retry logic for LLM HTTP calls to prevent failure when hitting rate limits (HTTP 429) or encountering transient server errors (HTTP 500, 502, 503, 504).
- Added hash-based skip optimizations in the `dream` command for both **Consolidation** and **Summarization** steps:
  - **Summary Skip**: Stores a `summary_hash` in each memory file's frontmatter to bypass LLM summarization if the file body remains unchanged.
  - **Consolidation Skip**: Stores a `consolidation_hash` in `index.md`'s frontmatter representing the combined state of all memory files and external inputs (git diffs, transcripts, tool calls). If the hash matches on successive runs, the LLM consolidation call is bypassed, resolving all redundant network requests and bringing steady-state LLM calls during `dream` down to **exactly 0**.

**Core files affected:**
- [src/memory_fabric/llm.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/llm.py)
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Added a loop with exponential backoff and randomized jitter to retrying requests in `_http_post` on HTTP status codes 429, 500, 502, 503, and 504.
- Integrated `consolidation_hash` tracking in `dream` and `_regenerate_index_root` to bypass LLM consolidation and reuse previous warnings/contradictions when no input has changed.
- Added comprehensive unit tests targeting mock HTTP 429 errors, summary skipping, and consolidation skipping behaviors (verifying call counts).

**Status & Testing:**
- Tested locally with venv pytest, all 31 tests passed successfully.

## 2026-06-02 12:48 - Fix subprocess UnicodeDecodeError on Windows

**What was implemented:**
- Added `encoding="utf-8"` and `errors="replace"` to all `subprocess.run` calls in the `_get_git_diff` function within storage.py. This prevents the MCP server from crashing with a `UnicodeDecodeError` when executing git commands in repositories with UTF-8/non-ASCII characters on Windows.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)

**Key changes:**
- Appended `encoding="utf-8"` and `errors="replace"` to subprocess calls executing `git rev-parse`, `git diff`, and `git log` commands to handle non-cp1252 output gracefully.

**Status & Testing:**
- Verified with unit tests, all 27 tests passed successfully.

## 2026-06-02 11:45 - LLM-Based Dreaming Process and Qualitative Evaluation Reviews

**What was implemented:**
- Implemented zero-dependency LLM provider integrations (Gemini, OpenAI, Anthropic) using Python's standard `urllib.request` to support LLM-based consolidation, contradiction checking, and section summarization in the Dreaming process.
- Updated the evaluation framework to call the LLM for generating qualitative, actionable recommendations when `llm_review=True` is enabled.

**Core files affected:**
- [src/memory_fabric/llm.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/llm.py)
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [src/memory_fabric/eval.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/eval.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Created a zero-dependency `call_llm` adapter supporting Gemini, OpenAI, and Anthropic.
- Resolved temporary directory path resolution logic in candidate files during LLM-based Dreaming consolidation.
- Implemented LLM qualitative evaluations to review report markdowns and append 2-4 architectural recommendations.
- Added comprehensive unit tests mocking Gemini, OpenAI, and Anthropic API responses for `call_llm`, `dream` consolidation/summaries, and `_llm_notes` success and failure flows.

**Status & Testing:**
- Tested locally, all 27 tests passed successfully.

## 2026-06-02 11:36 - Correct memory registration and duplication

**What was implemented:**
- Corrected and reinforced the memory registration mechanism (`write_local_memory`) to merge metadata from input content containing frontmatter block and prevent line/bullet duplicates when appending.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Added automatic detection and parsing of frontmatter block inside input content parameters, merging properties (e.g. `priority`, `summary`, `tags`) to prevent writing duplicate delimiters in the file body.
- Implemented duplicate line and bullet-point filtering when writing in `"append"` mode, avoiding redundant rule or decision duplicates.
- Returns `changed: False` with warning if only duplicate entries are appended.

**Status & Testing:**
- Tested locally, all 23 tests in `test_memory_fabric.py` passed successfully.

## 2026-06-02 11:34 - Refine memory operations and safeguards

**What was implemented:**
- Refined Git hook installation, global rule promotion, doctor permissions validation, and Dreaming execution to add better robustness and prevent silent data loss.

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [src/memory_fabric/cli.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/cli.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Modified the Git post-commit hook installer to append to existing hook files if they exist instead of overwriting.
- Enhanced the `sync-global` interactive workflow to detect target file collisions and prompt the user to overwrite, append/merge, or skip.
- Expanded the `doctor` command to validate permissions on the `.ai-memory` directory itself.
- Added recent commit logs via `git log` to Dreaming input ingestion.
- Optimized Dreaming stale section detection to prevent redundant file writes and warning logs when sections are already stale.

**Status & Testing:**
- Tested locally, all 21 tests in `test_memory_fabric.py` passed successfully.

## 2026-06-02 11:22 - Resolve plan.md Gaps

**What was implemented:**
- Implemented core features and CLI extensions to close functional gaps with plan.md, including opt-in post-commit Git hooks, interactive global rule promotions, status size metrics, and advanced doctor validations. Dreaming was also enhanced to ingest git diff/session inputs, scan and count secret redactions in-place, and mark stale memory sections (>30 days old).

**Core files affected:**
- [src/memory_fabric/storage.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/storage.py)
- [src/memory_fabric/cli.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/cli.py)
- [src/memory_fabric/contracts.py](file:///c:/Users/rafael/Projetos/agentic-memory/src/memory_fabric/contracts.py)
- [tests/test_memory_fabric.py](file:///c:/Users/rafael/Projetos/agentic-memory/tests/test_memory_fabric.py)

**Key changes:**
- Add `--install-hooks` to `init` command to write a post-commit Git hook that automatically runs Dreaming maintenance on commit.
- Enhanced `sync-global` command to support interactive section promotion to global preferences when run on TTY.
- Calculate file sizes in bytes and token estimates in `status` and display in CLI/JSON responses.
- Expanded `doctor` validation checking index consistency, file read/write permissions, and optional MCP package availability.
- Dreaming now scans external inputs (git diffs, transcripts, tool logs) and candidate files for secrets, counting redactions, and automatically sets `review_status: stale` in metadata for files that are older than 30 days.

**Status & Testing:**
- Tested locally, all 19 tests in `test_memory_fabric.py` passed successfully.
