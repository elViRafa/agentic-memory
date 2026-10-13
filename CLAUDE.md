<!-- >>> memory-fabric:project-directives (managed block; edit .ai-memory steering files instead) >>> -->
## Project Directives — Memory Fabric

Hand-curated development guidelines shared by every AI agent working on this repo.
Source of truth: the `role: steering` section files in `.ai-memory/`. Edit those
files (review via MR), then run `ai-memory sync-agents` — never edit this
generated copy in place.

<!-- directive: framework-rules -->
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

<!-- directive: ubiquitous-language -->
# Ubiquitous Language

A shared glossary of domain terms utilized in the development, testing, and operation of Memory Fabric.

## Core Concepts

### Memory Fabric
The local-first, file-first memory layer system. It provides a standardized way for AI assistants to read, write, evaluate, and maintain context across coding sessions.

### Memory Section
A specific Markdown file (e.g. `architecture.md`, `decisions.md`) stored inside the `.ai-memory/` directory. Each section represents a distinct category of project context.

### Frontmatter (YAML)
Metadata blocks defined at the beginning of each Memory Section, delimited by `---`. It contains properties such as `section`, `summary`, `priority`, `tags`, `schema_version`, and `last_updated`.

### Index File (`index.md`)
A specialized section file that serves as a directory index of all available memory sections, including their priority, tags, custom summaries, and recent maintenance logs.

---

## Maintenance & Synthesis

### Dreaming (Dream)
The maintenance and consolidation workflow for memory sections. Dreaming runs:
- Ingests recent external contexts (Git logs, session transcripts, tool calls).
- Identifies and merges duplicate entries or redundant lines.
- Refreshes section summaries via an LLM.
- Scans files for potential secret leaks.
- Flags contradiction warnings.
- Regenerates `index.md`.

Modes:
- **Light Mode**: Runs quick, structural maintenance.
- **Deep Mode**: Performs comprehensive, LLM-based context consolidation.

### Consolidation
The process during Dreaming of resolving overlapping or redundant points, deduplicating lists, and merging historical notes to prevent unbounded context growth.

### Snapshot
A point-in-time backup of the active `.ai-memory/` folder, saved under `.ai-memory/snapshots/`. Snapshots are used to restore memory to a known good state via the `rollback` command.

### Candidate Store
A temporary directory created during Dreaming to generate and preview changes non-destructively. Changes are only copied to the live `.ai-memory/` folder if the `apply` parameter is set.

---

## Security & Scoping

### Secret Redaction
An automated scanning process that detects potential API keys, passwords, and tokens, replacing them with `[REDACTED_SECRET]` before writing to disk.

### Global Memory
Developer-level settings and preferences shared across all projects. Located in user AppData/Application Support/Config directories.

### Tier 0 (Directives)
A special global configuration file (`global/directives.md`) containing instructions that are always prepended in full to any context bundle, bypassing the token budget constraint.

### Token Budget
The token limitation (e.g. 4,000 tokens) within which the context bundle must be compiled. Priority configurations determine which section contents are fully loaded vs. summarized when limits are exceeded.

---

## Diagnostics

### Doctor
A utility command that inspects the workspace, validates frontmatter structure, verifies directory permissions, and checks for index consistency.

### Evaluation (Eval)
The scoring engine that assesses memory files or dreaming quality (delta reports) based on criteria like coverage, starters, metadata correctness, and secret risks.
<!-- <<< memory-fabric:project-directives <<< -->
