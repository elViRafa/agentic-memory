---
section: framework-rules
summary: "Defines project rules, setup instructions (pip), CLI commands (`ai-memory`), and testing conventions for Memory Fabric."
priority: medium
tags: [framework, rules, python, pytest, cli, commands]
schema_version: 1.3
last_updated: "2026-06-03T08:28:01-04:00"
summary_hash: 0f7d35614e1754f9a105dd34542eb614
---

# Framework Rules

Code quality and integration rules for the Memory Fabric project.

## 1. System Requirements

- **Python Version**: `Python >= 3.11` (enforced across imports and types).
- **Core Dependencies**:
  - `mcp >= 1.0.0` (optional; required only if running as an MCP server).
  - `ripgrep` (`rg`): optional but highly recommended to speed up searches (falls back to Python's built-in file scanner if absent).

## 2. Installation Conventions

During development and local setup, use standard installation methods:

```sh
# CLI only
pip install "git+https://github.com/elViRafa/agentic-memory.git"

# CLI + MCP Server
pip install "memory-fabric[mcp] @ git+https://github.com/elViRafa/agentic-memory.git"
```

For editable local development:
```sh
pip install -e .          # CLI only
pip install -e ".[mcp]"   # CLI + MCP server
```

## 3. Command Line Interface (CLI)

The package installs a global executable `ai-memory` with the following signature:

```sh
ai-memory [--cwd <path>] [--json] <command>
```

### Supported Commands

- `init`: Create `.ai-memory/` directory scaffolding.
- `status`: Display memory status, file sizes, and version.
- `doctor`: Validate YAML frontmatter, directory permissions, and configuration.
- `eval`: Evaluate memory content quality and Dreaming outcomes.
- `dream`: Run background memory maintenance, consolidation, and summaries.
- `query`: Run keyword-based searches against the memory database.
- `sync-global`: Preview and promote local configurations to global preferences.
- `rollback`: Restore the memory store from a baseline snapshot.

## 4. Testing Conventions

- **Framework**: Use standard `pytest` for all unit and integration testing.
- **Run Tests**: Execute `pytest tests/` from the root directory.
- Ensure any new MCP tool or CLI functionality is fully covered by tests in the `tests/` directory.

## 5. Agent Instructions

AI agents interacting with a Memory Fabric project must adhere to `AGENTS.md` rules:
- **Never write** `.ai-memory/` markdown files directly using filesystem tools.
- **Always read** combined context at session start via `read_combined_context_tool`.
- **Search memory** before scanning the codebase using `keyword_search_tool`.
- **Persist learnings** via `write_local_memory_tool` using the appropriate section.
- **Preview updates** using `propose_memory_patch_tool` for complex changes.
