---
store_path: schemas/design-philosophy
title: "Design Philosophy"
summary: "Design Philosophy"
priority: high
tags: [schemas, contracts, map, migrated]
schema_version: 1.3
last_updated: "2026-07-13T21:22:38-04:00"
---

The project utilizes two main contract types:
1. **YAML Frontmatter:** Used exclusively to structure the Markdown files on disk.
2. **Python `TypedDict`:** Used to enforce JSON-RPC responses for the MCP Server tools, and JSON output formatting for the CLI commands.
