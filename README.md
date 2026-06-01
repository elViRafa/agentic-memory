# Memory Fabric

**File-first, local-first memory layer for MCP-compatible AI coding assistants.**

Memory Fabric gives AI tools like Claude Code, Cursor, and GitHub Copilot a consistent, project-aware context layer — without locking you into one model, editor, cloud provider, or operating system.

Memory is stored as human-readable Markdown with YAML frontmatter. No vector database. No cloud account. No embeddings required.

---

## Features

- **MCP-native** — exposes memory tools through the standard Model Context Protocol
- **File-first** — Markdown files are the source of truth, inspectable and commit-ready
- **Local-first** — core reads and writes work offline
- **Secret-safe** — API keys and credentials are redacted before writing
- **Token-budget aware** — assembles context within limits; never slices files mid-document
- **Unicode-safe** — works with any human language
- **Graceful degradation** — works without `rg`, git hooks, or Dreaming configured

---

## Installation

```sh
pipx install memory-fabric          # CLI only
pipx install "memory-fabric[mcp]"   # CLI + MCP server
```

Or with `uvx`:

```sh
uvx memory-fabric init
```

---

## Quick Start

### 1. Initialize a project

```sh
ai-memory init
```

Creates `.ai-memory/` in the current directory with starter sections and a `.gitignore`.

### 2. Check health

```sh
ai-memory doctor
```

### 3. Query memory

```sh
ai-memory query "authentication"
```

### 4. Run maintenance (Dreaming)

```sh
ai-memory dream --mode light   # refresh index and summaries
ai-memory dream --mode deep    # full review of all sections
```

---

## MCP Server

Add to your MCP client configuration (e.g. Claude Code, Cursor):

```json
{
  "mcpServers": {
    "memory-fabric": {
      "command": "memory-fabric-mcp"
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|---|---|
| `initialize_memory_fabric` | Create `.ai-memory/` scaffolding in a project |
| `read_combined_context` | Load Tier 0 directives + prioritized memory within token budget |
| `read_section` | Read a single memory section by name |
| `keyword_search` | Search memory with ripgrep or Python fallback |
| `write_local_memory` | Append or replace a section with secret scanning |
| `propose_memory_patch` | Preview proposed memory changes without applying |

---

## Project Memory Layout

```
.ai-memory/
├── index.md              # Section index and summary
├── architecture.md       # System design decisions
├── schemas.md            # Data models and contracts
├── decisions.md          # ADRs and trade-off notes
├── debt.md               # Known tech debt
├── ubiquitous-language.md # Domain vocabulary
├── framework-rules.md    # Framework-specific conventions
└── .gitignore            # Excludes snapshots/, private/, logs
```

All files use YAML frontmatter:

```markdown
---
section: architecture
summary: "One-line fallback used when the file exceeds the token budget."
priority: high
tags: [api, auth]
schema_version: "1.3"
last_updated: 2026-06-01T12:00:00-04:00
---

Your memory content here.
```

---

## Global Memory

Developer-level preferences that apply across all projects are stored at:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\memory-fabric\global\` |
| macOS | `~/Library/Application Support/memory-fabric/global/` |
| Linux | `$XDG_CONFIG_HOME/memory-fabric/global/` |

`global/directives.md` is **Tier 0** — it is always loaded fully, bypassing token budgeting.

---

## CLI Reference

```
ai-memory [--cwd <path>] [--json] <command>

Commands:
  init            Create .ai-memory/ scaffolding
  status          Show memory status
  doctor          Validate memory files and environment
  dream           Run memory maintenance (--mode light|deep)
  query           Search memory
  sync-global     Preview local-to-global promotions
  rollback        Restore from a snapshot
```

---

## Write Safety

Every write path runs secret detection before saving. Detected secrets are replaced with `[REDACTED_SECRET]` and returned in the `redactions` field of the response. File locking prevents concurrent write corruption.

---

## Requirements

- Python ≥ 3.11
- `mcp >= 1.0.0` (optional, required for MCP server only)
- `rg` (optional — ripgrep speeds up keyword search; Python fallback used when absent)

---

## License

MIT
