# Agent Instructions — Memory Fabric

This file is read automatically by Claude Code, Gemini CLI, Codex, Antigravity, and other MCP-aware AI agents.
GitHub Copilot reads `.github/copilot-instructions.md` instead.

---

## Memory Fabric — Semantic Store Agent Instructions

🚨 **CRITICAL RULES - READ FIRST** 🚨
1. **NEVER use the native VS Code Copilot `memory` tool.** You MUST ONLY use the `memory-fabric` MCP tools (like `write_memory_store_tool`). The native `memory` tool writes to VS Code workspace storage, bypassing this project's memory system.
2. **NEVER use raw file system tools** (like `create_file`, `write_to_file`, `bash`, etc.) to read or write files inside the `.ai-memory/` directory. Doing so bypasses secret scanning, token budgeting, and the Dreaming system.
3. **MANDATORY STARTUP:** You MUST call `read_combined_context_tool(cwd="<absolute project root path>")` before doing anything else at the start of a session. No exceptions.
   > **MCP Resources alternative:** If your client supports MCP Resources and has auto-fetched `memory-fabric://context/<encoded-cwd>`, that context is already in your system prompt — skip the tool call.
4. **NEVER call `dream_tool` as a substitute for saving new knowledge.** Before triggering any Dream tool, you MUST first call `write_memory_store_tool` to persist specific, isolated memories from the current session (e.g., bugs fixed, features built, architecture decisions). Dreaming consolidates existing memory — it does NOT capture new knowledge.
5. **MANDATORY SESSION END:** Before your final response in a session, you MUST call `write_session_journal_tool` to log what was accomplished. Skip ONLY for trivial Q&A sessions with no code changes, decisions, or debugging.

### 1. Active Retrieval Workflow
- **Search:** Use `keyword_search_tool(cwd, query)` to find specific documented topics.
- **Deep Dive:** Use `read_memory_store_tool(cwd, store_path)` or `read_section(cwd, section)` for detailed content.

### 2. Store Writes & Rules
Use `write_memory_store_tool` to register standalone memories.
- **`store_path` Rules:** Must be lowercase, alphanumeric segments separated by slashes. No spaces, capitals, or `.md` extension (e.g., `architecture/decisions/jwt-auth`). Max 5 levels of nesting.
- **Parameters:** `cwd`, `store_path`, `content`, `title` (optional), `tags` (optional), `priority` (`high`/`medium`/`low`), `mode` (`replace`/`append`).

### 3. Root Maps Are Generated — Never Write Them
Root map files (`index`, `architecture`, `decisions`, `debt`, `schemas`) are **generated views** over `memory-store/`, rebuilt by Dreaming; hand edits get folded back into the store as `map-notes-pending-review` entries. Do NOT update them with `write_local_memory_tool` — that path is deprecated for facts and will be removed in v1.0. Write granular facts with `write_memory_store_tool`, then run `dream_tool` to refresh the maps.
**Exception:** the steering sections `framework-rules` and `ubiquitous-language` are hand-curated and always loaded into context; update those with `write_local_memory_tool(cwd, section, content)`.

### 4. Security & Maintenance
- **Security:** Do NOT store credentials, tokens, or passwords.
- **Dreaming:** Use `dream_tool` for consolidation only — after new knowledge has already been saved with `write_memory_store_tool`. Refer to `.agents/rules/dreaming.md` for guidelines.

### 5. Session End — Automatic Journaling
Before completing a session, call `write_session_journal_tool(cwd, summary, key_decisions, files_changed, session_label)` to capture what happened.

**Always journal after:** feature implementations, bug fixes, refactoring, architecture decisions, debugging, config changes, or any session where you wrote or modified code.

**Skip only for:** simple Q&A, quick lookups, or read-only explanations that produced no actionable changes.

Parameters:
- `summary`: 2-4 sentence description of what was accomplished.
- `key_decisions`: List of architecture/design decisions made (optional).
- `files_changed`: List of files created or significantly modified (optional).
- `session_label`: Short descriptive label, e.g. `"auth-refactor"` (optional).

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
