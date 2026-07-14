---
store_path: decisions/granular-decisions-adr
title: "Granular Decisions (ADR)"
summary: "Granular Decisions (ADR)"
priority: high
tags: [decisions, adr, map, migrated]
schema_version: 1.3
last_updated: "2026-07-13T21:22:38-04:00"
---

Detailed Architectural Decision Records (ADRs) are categorized by component and stored in the granular memory store. Please refer to the specific files below for detailed logs and implementation rationales:

### CLI & User Experience
Decisions concerning terminal outputs, the `doctor` command, the `status` command, and file permission checks.
👉 [View CLI & UX Decisions](memory-store/decisions/cli-ux.md)

### LLM Infrastructure
Decisions regarding LLM provider integrations (OpenAI, Anthropic, Gemini, Ollama), retry logic, and token optimization.
👉 [View LLM Infrastructure Decisions](memory-store/decisions/llm-infrastructure.md)

### Git Integration
Decisions concerning Git hooks (`post-commit`), subprocess calls, UTF-8 encoding, and context ingestion from `git diff`.
👉 [View Git Integration Decisions](memory-store/decisions/git-integration.md)

### Core Storage & Memory Deduplication
Decisions regarding Markdown file storage, YAML frontmatter parsing, duplicate line filtering, and staleness detection.
👉 [View Core Storage Decisions](memory-store/decisions/core-storage.md)
