---
store_path: decisions/engineering-philosophy
title: "Engineering Philosophy"
summary: "Engineering Philosophy"
priority: high
tags: [decisions, adr, map, migrated]
schema_version: 1.3
last_updated: "2026-07-13T21:22:38-04:00"
---

1. **Zero-Dependency Core:** We favor standard library implementations (e.g., `urllib.request` over `requests`) to keep the MCP Server and CLI lightweight and easy to distribute.
2. **Resilience First:** The system relies on exponential backoffs and sanitization to handle external LLM API rate limits gracefully, ensuring the AI agent's memory maintenance never crashes the main developer workflow.
3. **Opt-In Automation:** Features like Git post-commit hooks must be opt-in, non-destructive, and merge smoothly with existing user configurations.
