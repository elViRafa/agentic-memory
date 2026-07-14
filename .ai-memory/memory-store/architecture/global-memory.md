---
store_path: architecture/global-memory
title: "Global Memory"
summary: "Global Memory"
priority: high
tags: [architecture, design, overview, migrated]
schema_version: 1.3
last_updated: "2026-07-13T21:22:38-04:00"
---

Developer-level preferences that apply across all projects are stored in:
- Windows: `%APPDATA%\memory-fabric\global\`
- macOS: `~/Library/Application Support/memory-fabric/global/`
- Linux: `$XDG_CONFIG_HOME/memory-fabric/global/`

The `global/directives.md` file acts as **Tier 0**: it is always loaded fully, bypassing token budgeting.

The memory-fabric-mcp server CLI has been extended to support Server-Sent Events (SSE) transport alongside the default stdio transport. It supports `--transport sse`, `--host <host>`, `--port <port>`, and `--allow-all-origins` to ease CORS policies and DNS rebinding protections when connecting external clients like Open WebUI.
