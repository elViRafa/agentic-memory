---
section: framework-rules
summary: "Map of project rules, CLI setup instructions, and testing conventions for Memory Fabric."
priority: medium
tags: [framework, rules, python, pytest, cli, commands, map]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Framework Rules Map

This section provides the high-level system requirements and CLI usage overview for the `memory-fabric` package.

## 1. System Requirements

- **Python Version**: `Python >= 3.11`
- **Core Dependencies**:
  - `mcp >= 1.0.0` (optional; required only if running as an MCP server).
  - `ripgrep` (`rg`): optional but highly recommended to speed up searches.

## 2. Installation Conventions

```sh
# CLI only
pip install "git+https://github.com/elViRafa/agentic-memory.git"

# CLI + MCP Server
pip install "memory-fabric[mcp] @ git+https://github.com/elViRafa/agentic-memory.git"
```

## 3. Command Line Interface (CLI)

The package installs a global executable `ai-memory`:
```sh
ai-memory [--cwd <path>] [--json] <command>
```

**Supported Commands Overview:**
- `init`, `status`, `doctor`, `eval`, `dream`, `query`, `sync-global`, `rollback`.

*(For detailed schemas returned by these CLI commands, see the [CLI Contracts Map](memory-store/schemas/cli-contracts.md))*

## 4. Testing Conventions
- Use standard `pytest` for all unit and integration testing. Run `pytest tests/` from the root directory.

## Granular Rules

Specific rule sets and agent instructions are stored in the granular memory store:

### MCP Agent Instructions
Strict rules on how AI Agents should interact with the `.ai-memory/` directory using MCP tools rather than standard OS filesystem tools.
👉 [View Agent Instructions](memory-store/rules/mcp-agent-instructions.md)
