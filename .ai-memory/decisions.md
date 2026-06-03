---
section: decisions
summary: "Records key architectural decisions, implementation details, and technical rationale for the memory system's evolution."
priority: medium
tags: [decisions, adr]
schema_version: 1.3
last_updated: "2026-06-03T10:52:23-04:00"
summary_hash: 8f674f25b684be55c855eb0c0679093b
---

# Decisions

Record durable decisions and rationale here.

- Decided to implement the post-commit git hook as an opt-in hook script `.git/hooks/post-commit` calling `ai-memory dream --mode light --apply`.
- Added file permission checks, optional FastMCP checks, and index consistency verification to `doctor` command.
- Added byte size and token estimate metrics to `status` command.
- Decided to sanitize all Dreaming inputs and candidate markdown files, counting total redactions and returning them under `redactions` key.
- Decided to auto-detect memory files not updated in the last 30 days and mark them as stale by setting `review_status: stale` in metadata.

- Improved post-commit hooks installer to merge with existing post-commit hook instead of replacing it.
- Enhanced interactive sync-global command to safely handle target file collisions by prompting for overwrite, append/merge, or skip.
- Added directory permission verification checks to doctor command.
- Enriched dreaming git input ingestion to include both git diff HEAD and recent commit logs (git log).
- Optimized dreaming stale check to avoid writing metadata updates and warning logs for files already marked stale.

- Corrected write_local_memory to automatically extract and parse frontmatter delimiters from incoming payload content, merging metadata fields directly instead of polluting the body.
- Reinforced write_local_memory in append mode to filter out duplicate lines/bullets before writing, returning changed=False with a warning if no unique content is written.

- Decided to implement a zero-dependency LLM provider adapter in llm.py via standard library urllib.request to call Gemini, OpenAI, and Anthropic, keeping the memory fabric lightweight.
- Integrated qualitative reviews into eval.py to generate architectural recommendations.

- Decided to append `encoding="utf-8"` and `errors="replace"` to all git-related subprocess calls in storage.py to prevent UnicodeDecodeError crashes on Windows when processing files containing non-ASCII/UTF-8 characters.

- Decided to implement exponential backoff retry logic (up to 5 attempts) with jitter in `llm.py` for HTTP 429 (rate limits) and 5xx (transient errors) to handle Google Gemini / OpenAI / Anthropic API limit exceptions gracefully during Dreaming.

- Decided to optimize the `dream` summary generation by calculating a body md5 hash and storing it as `summary_hash` in the frontmatter of memory files. If the hash matches the body and a custom summary already exists, we skip calling the LLM entirely, saving redundant API requests.

- Decided to optimize LLM consolidation during `dream` by generating a combined `consolidation_hash` from the post-consolidation memory file contents and external inputs (git diffs, transcripts, tool logs), storing it in the index frontmatter metadata. Successive `dream` runs compare the state against this hash to skip the consolidation LLM call when nothing has changed.

- Decided to support local model options by adding the `"ollama"` LLM provider type in `llm.py` and `storage.py`, mapping requests to `/api/chat` using custom environment variables `OLLAMA_HOST` and `OLLAMA_MODEL`.

- Decided to centralize version definition in `version.py` (avoiding circular imports) and expose the version key inside the JSON result of the `status` command, allowing downstream packages to check for updates.

- **LLM Debug Logging**: Added the `--debug-llm` CLI option and `MEMORY_FABRIC_LLM_DEBUG` environment variable to enable request/response printing to stderr or file (e.g. `llm_debug.log`) with automatic authorization token redaction.
