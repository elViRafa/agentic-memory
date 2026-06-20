---
store_path: rules/mcp-agent-instructions
section: mcp-agent-instructions
summary: "Crucial instructions for AI Agents interacting with the Memory Fabric via MCP Server tools."
priority: high
tags: [rules, agents, mcp, tools]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Agent Instructions

AI agents interacting with a Memory Fabric project must strictly adhere to the following rules to ensure memory integrity:

1. **Never write** `.ai-memory/` markdown files directly using standard OS filesystem tools (like `write_to_file` or `bash`).
2. **Always read** combined context at session start via the `read_combined_context_tool`.
3. **Search memory** before scanning the massive codebase by using `keyword_search_tool`.
4. **Persist learnings** via `write_memory_store_tool` for standalone semantic memories (e.g., bugs fixed, features built, architecture decisions). Use `write_local_memory_tool` only for updating existing flat section files.
5. **Preview updates** using `propose_memory_patch_tool` for any complex, multi-line changes.
6. **Never call `dream_tool` as a substitute for saving new knowledge.** You MUST call `write_memory_store_tool` first to capture specific, isolated knowledge from the current session before triggering any Dreaming consolidation. Dreaming consolidates existing memory — it does NOT capture new knowledge.
