---
store_path: architecture/system-flow-component-boundaries
title: "System Flow & Component Boundaries"
summary: "System Flow & Component Boundaries"
priority: high
tags: [architecture, design, overview, migrated]
schema_version: 1.3
last_updated: "2026-07-13T21:22:38-04:00"
---

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
