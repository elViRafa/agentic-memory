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
