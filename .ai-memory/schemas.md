---
section: schemas
summary: "Map of YAML frontmatter schemas and Python `TypedDict` contracts for the MCP Server and CLI."
priority: high
tags: [schemas, contracts, map]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Data Schemas & Contracts Map

This section acts as a high-level map of the data structures utilized by Memory Fabric. 

## Design Philosophy

The project utilizes two main contract types:
1. **YAML Frontmatter:** Used exclusively to structure the Markdown files on disk.
2. **Python `TypedDict`:** Used to enforce JSON-RPC responses for the MCP Server tools, and JSON output formatting for the CLI commands.

## Granular Contracts

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
