---
store_path: decisions/llm-infrastructure
section: llm-infrastructure
summary: "Decisions regarding LLM providers, retry logic, sanitization, and optimization."
priority: medium
tags: [decisions, llm, infrastructure, optimization]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# LLM Infrastructure Decisions

This document records the granular decisions made for the LLM interaction layer in Memory Fabric.

## Providers & Connectivity
- Decided to implement a zero-dependency LLM provider adapter in `llm.py` via standard library `urllib.request` to call Gemini, OpenAI, and Anthropic, keeping the memory fabric lightweight.
- Decided to support local model options by adding the `"ollama"` LLM provider type in `llm.py` and `storage.py`, mapping requests to `/api/chat` using custom environment variables `OLLAMA_HOST` and `OLLAMA_MODEL`.
- Decided to implement exponential backoff retry logic (up to 5 attempts) with jitter in `llm.py` for HTTP 429 (rate limits) and 5xx (transient errors) to handle Google Gemini / OpenAI / Anthropic API limit exceptions gracefully during Dreaming.

## Optimization & Caching
- Decided to optimize the `dream` summary generation by calculating a body md5 hash and storing it as `summary_hash` in the frontmatter of memory files. If the hash matches the body and a custom summary already exists, we skip calling the LLM entirely, saving redundant API requests.
- Decided to optimize LLM consolidation during `dream` by generating a combined `consolidation_hash` from the post-consolidation memory file contents and external inputs (git diffs, transcripts, tool logs), storing it in the index frontmatter metadata. Successive `dream` runs compare the state against this hash to skip the consolidation LLM call when nothing has changed.

## Security
- Decided to sanitize all Dreaming inputs and candidate markdown files, counting total redactions and returning them under the `redactions` key.
