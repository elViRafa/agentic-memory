---
section: debt
summary: "Executive summary map of technical debt and roadmap priorities across the MCP Server and CLI."
priority: low
tags: [debt, risk, map]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Technical Debt & Roadmap Map

This section acts as a high-level executive summary of known technical debt, risks, and major planned improvements across the Memory Fabric ecosystem.

## Debt Strategy

We prioritize debt that impacts **Agent Autonomy** (how well the MCP Server tools serve an LLM) and **Memory Integrity** (how safely the CLI modifies Markdown files without causing data loss).

## Granular Debt Records

Detailed technical debt tickets and roadmaps are stored in the granular memory store. Please refer to the specific files below:

### CLI: Dreaming & Consolidation
Roadmap for upgrading the `dream` command to support candidate stores, dry-runs, and deduplication of redundant memory entries.
👉 [View Dreaming Roadmap](memory-store/debt/dreaming-roadmap.md)

### MCP Server: Tool Limitations (Placeholder)
*(Currently no open major debt tickets for the MCP server tool bindings. Future performance bottlenecks or context-window optimizations will be mapped here).*
