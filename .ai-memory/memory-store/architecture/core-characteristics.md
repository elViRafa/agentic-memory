---
store_path: architecture/core-characteristics
title: "Core Characteristics"
summary: "Core Characteristics"
priority: high
tags: [architecture, design, overview, migrated]
schema_version: 1.3
last_updated: "2026-07-13T21:22:38-04:00"
---

- **MCP-Native**: Exposes memory tools through the standard Model Context Protocol.
- **File-First**: Markdown files are the source of truth, inspectable and commit-ready.
- **Local-First**: Core reads and writes work offline.
- **Secret-Safe**: API keys and credentials are redacted before writing.
- **Token-Budget Aware**: Assembles context within limits; never slices files mid-document.
- **Quality Eval**: Scores memory usefulness and Dreaming before/after results locally.
- **Unicode-Safe**: Works with any human language.
- **Graceful Degradation**: Works without `rg`, git hooks, or Dreaming configured.
