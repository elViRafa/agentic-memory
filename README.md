# Memory Fabric

**File-first, local-first memory layer for MCP-compatible AI coding assistants.**

Memory Fabric gives AI tools like Claude Code, Cursor, and GitHub Copilot a consistent, project-aware context layer without locking you into one model, editor, cloud provider, or operating system.

Memory is stored as human-readable Markdown with YAML frontmatter. No vector database. No cloud account. No embeddings required.

---

## Features

- **MCP-native**: exposes memory tools through the standard Model Context Protocol
- **File-first**: Markdown files are the source of truth, inspectable and commit-ready
- **Local-first**: core reads and writes work offline
- **Secret-safe**: API keys and credentials are redacted before writing
- **Token-budget aware**: assembles context within limits; never slices files mid-document
- **Quality eval**: scores memory usefulness and Dreaming before/after results locally
- **Unicode-safe**: works with any human language
- **Graceful degradation**: works without `rg`, git hooks, or Dreaming configured

---

## Status

**v0.1.0 — functional, not yet published to PyPI.**
Install directly from GitHub (see below). Core CLI and MCP tools work end-to-end.

---

## Installation

### From GitHub (current)

Requires Python ≥ 3.11 and [`pipx`](https://pipx.pypa.io/) or `pip`.

```sh
# CLI only
pipx install "git+https://github.com/elViRafa/agentic-memory.git"

# CLI + MCP server
pipx install "memory-fabric[mcp] @ git+https://github.com/elViRafa/agentic-memory.git"
```

Or with plain `pip` (inside a virtual environment):

```sh
pip install "git+https://github.com/elViRafa/agentic-memory.git"          # CLI only
pip install "memory-fabric[mcp] @ git+https://github.com/elViRafa/agentic-memory.git"  # + MCP
```

Or clone and install in editable mode for local development:

```sh
git clone https://github.com/elViRafa/agentic-memory.git
cd agentic-memory
pip install -e .          # CLI only
pip install -e ".[mcp]"   # CLI + MCP server
```

### From PyPI (coming soon)

Once published, you will be able to install with:

```sh
pipx install memory-fabric          # CLI only
pipx install "memory-fabric[mcp]"   # CLI + MCP server
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

### 3. Evaluate memory quality

```sh
ai-memory eval
ai-memory eval --json
```

`eval` scores whether memories are useful for coding assistants. It checks section coverage, starter-template content, summary quality, metadata, retrieval readiness, and likely secrets.

If `.ai-memory/` exists, reports are saved under ignored local files:

```text
.ai-memory/evals/latest.json
.ai-memory/evals/latest.md
.ai-memory/evals/<timestamp>-memory.json
.ai-memory/evals/<timestamp>-memory.md
```

If `.ai-memory/` does not exist yet, eval prints a pre-init report only and creates no files.

### 4. Query memory

```sh
ai-memory query "authentication"
```

### 5. Run maintenance (Dreaming)

```sh
ai-memory dream --mode light
ai-memory dream --mode deep
```

Dreaming creates a snapshot before maintenance. You can evaluate whether a Dreaming run improved memory quality:

```sh
ai-memory eval --dream latest
ai-memory dream --mode light --eval
```

Dream eval compares the pre-dream snapshot to current memory and reports score delta, changed files, improvements, and regressions.

---

## MCP Server

Add to your MCP client configuration (for example Claude Code or Cursor):

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
| `initialize_memory_fabric_tool` | Create `.ai-memory/` scaffolding in a project |
| `read_combined_context_tool` | Load Tier 0 directives + prioritized memory within token budget |
| `read_section_tool` | Read a single memory section by name |
| `keyword_search_tool` | Search memory with ripgrep or Python fallback |
| `write_local_memory_tool` | Append or replace a section with secret scanning |
| `propose_memory_patch_tool` | Preview proposed memory changes without applying |
| `evaluate_memory_fabric_tool` | Evaluate local memory quality |
| `evaluate_dream_quality_tool` | Evaluate a Dreaming run against a snapshot |

---

## Agent Integration (making agents use Memory Fabric automatically)

Registering the MCP server is necessary but not sufficient — AI agents will not use its
tools unless explicitly instructed to do so. You must add agent instruction files to your
project that mandate the workflow described below.

### Step 1 — Add instruction files to your project

**For Claude Code, Gemini CLI, and most modern agents — create `AGENTS.md` in the
project root:**

```markdown
## Memory Fabric

Use the `memory-fabric` MCP tools for all memory operations — never write `.ai-memory/`
files directly.

- At session start: call `read_combined_context_tool(cwd="<project root>")`
  (if `.ai-memory/` is missing, call `initialize_memory_fabric_tool(cwd=...)` first)
- Before searching the codebase: call `keyword_search_tool(cwd="...", query="<topic>")`
- After meaningful work: call `write_local_memory_tool(cwd="...", section="...", content="...", mode="append")`

Sections: `decisions`, `architecture`, `debt`, `schemas`, `ubiquitous-language`, `framework-rules`
```

**For GitHub Copilot — create `.github/copilot-instructions.md` with the same content.**

### Step 2 — Verify the MCP server is running

The instruction files only work when the `memory-fabric` MCP server is reachable.
Run `ai-memory doctor` in the project to confirm.

### Why this matters

Without these files, agents will:
- Explain they "don't use MCP tools automatically"
- Write markdown files directly using file-system tools, bypassing secret scanning,
  token budgeting, and frontmatter management

The instruction files are the authoritative mechanism to change this behaviour across
Claude Code, Cursor, GitHub Copilot, and any other MCP-aware agent.

---

## Project Memory Layout

```text
.ai-memory/
|-- index.md
|-- architecture.md
|-- schemas.md
|-- decisions.md
|-- debt.md
|-- ubiquitous-language.md
|-- framework-rules.md
|-- evals/       # ignored local quality reports
|-- snapshots/   # ignored rollback baselines
|-- private/     # ignored personal notes
`-- .gitignore
```

All shared memory files use YAML frontmatter:

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

`global/directives.md` is **Tier 0**: it is always loaded fully, bypassing token budgeting.

---

## CLI Reference

```text
ai-memory [--cwd <path>] [--json] <command>

Commands:
  init            Create .ai-memory/ scaffolding
  status          Show memory status
  doctor          Validate memory files and environment
  eval            Score memory quality or Dreaming quality
  dream           Run memory maintenance (--mode light|deep)
  query           Search memory
  sync-global     Preview local-to-global promotions
  rollback        Restore from a snapshot
```

Eval examples:

```sh
ai-memory eval
ai-memory eval --json
ai-memory eval --llm-review
ai-memory eval --dream latest
ai-memory eval --dream memory-20260601T140000_0400
```

Optional LLM review is never enabled by default. When requested, deterministic local scores remain the source of truth; LLM notes are secondary and inputs are sanitized before review.

---

## Write Safety

Every write path runs secret detection before saving. Detected secrets are replaced with `[REDACTED_SECRET]` and returned in the `redactions` field of the response. File locking prevents concurrent write corruption.

Eval scans existing memories for likely secrets but does not rewrite existing files. It reports what needs manual review.

---

## Requirements

- Python >= 3.11
- `mcp >= 1.0.0` (optional, required for MCP server only)
- `rg` (optional; ripgrep speeds up keyword search, Python fallback used when absent)

---

## License

MIT
