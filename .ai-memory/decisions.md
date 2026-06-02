---
section: decisions
summary: "Architecture and product decisions with rationale."
priority: medium
tags: [decisions, adr]
schema_version: 1.3
last_updated: "2026-06-02T11:44:59-04:00"
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
