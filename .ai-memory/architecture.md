---
section: architecture
summary: "Defines the local, file-first memory layer structure for MCP AI assistants using Markdown files as truth."
priority: high
tags: [architecture, design, overview]
schema_version: 1.3
last_updated: "2026-06-03T09:52:04-04:00"
summary_hash: ad713ac871aff4dc95a9e560937fd6ad
---

# Architecture

Memory Fabric is a file-first, local-first memory layer for MCP-compatible AI coding assistants. It exposes memory tools through the standard Model Context Protocol (MCP) and uses local Markdown files as the source of truth.

## Core Characteristics

- **MCP-Native**: Exposes memory tools through the standard Model Context Protocol.
- **File-First**: Markdown files are the source of truth, inspectable and commit-ready.
- **Local-First**: Core reads and writes work offline.
- **Secret-Safe**: API keys and credentials are redacted before writing.
- **Token-Budget Aware**: Assembles context within limits; never slices files mid-document.
- **Quality Eval**: Scores memory usefulness and Dreaming before/after results locally.
- **Unicode-Safe**: Works with any human language.
- **Graceful Degradation**: Works without `rg`, git hooks, or Dreaming configured.

## Project Memory Layout

Shared memory files are stored in `.ai-memory/` in the project root:

```text
.ai-memory/
|-- index.md
|-- architecture.md
|-- schemas.md
|-- decisions.md
|-- debt.md
|-- ubiquitous-language.md
|-- framework-rules.md
|-- evals/       # ignored local quality reports
|-- snapshots/   # ignored rollback baselines
|-- private/     # ignored personal notes
`-- .gitignore
```

All shared memory files use YAML frontmatter for metadata.

## System Flow & Component Boundaries

The project consists of the following key modules:

| File | Purpose |
|---|---|
| `src/memory_fabric/server.py` | MCP tool registration via FastMCP |
| `src/memory_fabric/storage.py` | Core read/write/dream/search logic |
| `src/memory_fabric/eval.py` | Quality scoring for memory and Dreaming runs |
| `src/memory_fabric/cli.py` | `ai-memory` CLI entrypoint |
| `src/memory_fabric/security.py` | Secret detection and redaction |
| `src/memory_fabric/paths.py` | Cross-platform path helpers |
| `src/memory_fabric/frontmatter.py` | YAML frontmatter parsing/writing |
| `src/memory_fabric/locking.py` | File-level write locking |
| `src/memory_fabric/contracts.py` | Shared types and constants |
| `src/memory_fabric/templates.py` | Starter-file scaffolding |

## Global Memory

Developer-level preferences that apply across all projects are stored in:
- Windows: `%APPDATA%\memory-fabric\global\`
- macOS: `~/Library/Application Support/memory-fabric/global/`
- Linux: `$XDG_CONFIG_HOME/memory-fabric/global/`

The `global/directives.md` file acts as **Tier 0**: it is always loaded fully, bypassing token budgeting.

The memory-fabric-mcp server CLI has been extended to support Server-Sent Events (SSE) transport alongside the default stdio transport. It supports `--transport sse`, `--host <host>`, `--port <port>`, and `--allow-all-origins` to ease CORS policies and DNS rebinding protections when connecting external clients like Open WebUI.
