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
