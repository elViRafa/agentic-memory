---
store_path: architecture/grok-support
title: "Grok client support and integration"
summary: "Grok client support and integration"
priority: high
tags: [grok, agents, architecture, mcp, docs]
schema_version: 1.3
last_updated: "2026-06-05T09:42:41-04:00"
review_status: stale
---

## Grok Support Added (2026-06-05)

- Explicitly listed **Grok (TUI / Build / Agent harness)** in the Agentic Architecture table in README.md.
- Grok uses the standard `AGENTS.md` (universal), loads MCP servers from `~/.grok/config.toml` (global or project .grok/), and `.mcp.json` for compatibility.
- Full canonical docs can be installed into Grok's `~/.grok/docs/user-guide/13-memory-fabric.md` (as done for the search-sermons consuming project) so that Grok's help skill and agents have the complete reference.
- Integration tested: read_combined_context_tool, write_memory_store_tool, dream_tool etc. work from within a Grok session with the MCP registered.
- Windows dev note: editable install + full-path exe in config, use python -m memory_fabric.cli for scripts/hooks.

This makes Memory Fabric a first-class citizen inside Grok-based workflows.
