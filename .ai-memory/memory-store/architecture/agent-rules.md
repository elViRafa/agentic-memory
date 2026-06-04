---
store_path: architecture/agent-rules
title: "Agentic Architecture & Rule Registries"
summary: "Agentic Architecture & Rule Registries"
priority: high
tags: [architecture, agents, rules]
schema_version: 1.3
last_updated: "2026-06-03T19:37:24-04:00"
---

# Agentic Architecture
Memory Fabric operates as an MCP server. AI agents are taught how to use it through rule files:
- AGENTS.md: Universal instructions at project root.
- .agents/rules/memory-store.md: Core rules formatted for IDE auto-injection (Cursor/Cline).
- .agents/rules/dreaming.md: Specialized parameter rules for the dream_tool background process.
- CLAUDE.md & .github/copilot-instructions.md: Auto-generated for specific platforms.

These files are stored as templates in src/memory_fabric/templates.py and are automatically deployed to target repositories during the i-memory init command.
