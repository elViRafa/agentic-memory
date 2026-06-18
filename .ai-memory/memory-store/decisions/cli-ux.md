---
store_path: decisions/cli-ux
section: cli-ux
summary: "Decisions regarding the ai-memory CLI UX, outputs, and validation rules."
priority: low
tags: [decisions, cli, ux, commands]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# CLI & UX Decisions

This document records the granular architectural and product decisions made for the CLI components of Memory Fabric.

## Status and Doctor Commands
- Added file permission checks, optional FastMCP checks, and index consistency verification to `doctor` command.
- Added directory permission verification checks to `doctor` command.
- Added byte size and token estimate metrics to `status` command.
- Decided to centralize version definition in `version.py` (avoiding circular imports) and expose the version key inside the JSON result of the `status` command, allowing downstream packages to check for updates.

## Sync Command
- Enhanced interactive `sync-global` command to safely handle target file collisions by prompting for overwrite, append/merge, or skip.

## Diagnostic and Evaluation
- **LLM Debug Logging**: Added the `--debug-llm` CLI option and `MEMORY_FABRIC_LLM_DEBUG` environment variable to enable request/response printing to stderr or file (e.g. `llm_debug.log`) with automatic authorization token redaction.
- Integrated qualitative reviews into `eval.py` to generate architectural recommendations.
