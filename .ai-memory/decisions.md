---
section: decisions
summary: "Map of key architectural decisions, philosophies, and rationales for the memory system's evolution."
priority: high
tags: [decisions, adr, map]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Architecture Decisions Map

This section acts as an executive summary of the foundational engineering philosophies guiding the Memory Fabric project.

## Engineering Philosophy

1. **Zero-Dependency Core:** We favor standard library implementations (e.g., `urllib.request` over `requests`) to keep the MCP Server and CLI lightweight and easy to distribute.
2. **Resilience First:** The system relies on exponential backoffs and sanitization to handle external LLM API rate limits gracefully, ensuring the AI agent's memory maintenance never crashes the main developer workflow.
3. **Opt-In Automation:** Features like Git post-commit hooks must be opt-in, non-destructive, and merge smoothly with existing user configurations.

## Granular Decisions (ADR)

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
