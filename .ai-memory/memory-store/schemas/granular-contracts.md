---
store_path: schemas/granular-contracts
title: "Granular Contracts"
summary: "Granular Contracts"
priority: high
tags: [schemas, contracts, map, migrated]
schema_version: 1.3
last_updated: "2026-07-13T21:22:38-04:00"
---

Detailed schema definitions and Python dictionary models are stored in the granular memory store. Please refer to the specific files below:

### Markdown Frontmatter
The required and optional metadata fields for every memory section.
👉 [View Frontmatter Schema](memory-store/schemas/frontmatter.md)

### MCP Server Contracts
The `TypedDict` definitions for the tools exposed to AI Agents (`InitResult`, `ContextBundle`, `MemorySection`, `SearchResult`, `WriteResult`, `PatchPreview`).
👉 [View MCP Contracts](memory-store/schemas/mcp-contracts.md)

### CLI & Dreaming Contracts
The `TypedDict` definitions for diagnostic commands and memory maintenance (`DoctorResult`, `StatusResult`, `DreamResult`, `DreamConsolidation`, `DreamRewriteTask`).
👉 [View CLI Contracts](memory-store/schemas/cli-contracts.md)

### Evaluation Contracts
The `TypedDict` definitions for the evaluation and scoring system (`EvalResult`, `DreamEvalResult`, `EvalCategory`, `EvalCheck`).
👉 [View Evaluation Contracts](memory-store/schemas/eval-contracts.md)
