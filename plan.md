# Architecture Specification: Universal Hybrid AI Memory System via MCP (Memory Fabric)

**Version: 1.3 (File-First, Local-First, Global-Ready)**

## 1. Overview

Memory Fabric is a portable memory system for any MCP-compatible coding assistant. It gives AI tools a consistent, project-aware, and developer-aware context layer without locking users into one model, editor, cloud provider, or operating system.

The system is designed for individual developers first, while keeping shared team use natural later. In v1, Memory Fabric is intentionally file-first: memory is stored as human-readable Markdown with YAML frontmatter, retrieved deterministically, and maintained through an MCP server plus an optional background maintenance process called Dreaming.

Memory Fabric does not require embeddings, vector databases, cloud sync, or an account for its core behavior. Those capabilities can be added later as optional extensions, but they are explicitly out of scope for v1.

## 2. Product Goals

Memory Fabric should make AI coding assistants feel less forgetful across sessions, projects, machines, and tools.

Primary goals:

- Provide one memory layer that works across MCP-compatible assistants such as Claude Code, Cursor, GitHub Copilot, Google Antigravity, and future clients.
- Keep memory inspectable, editable, reviewable, and portable by using ordinary files.
- Support private global preferences and commit-ready project memory without mixing the two.
- Work offline for core reads and writes.
- Be safe by default, with secret scanning before memory is written, summarized, or sent to any configured LLM provider.
- Support worldwide users through Unicode-safe Markdown, multilingual content, cross-platform paths, and timezone-safe timestamps.

Non-goals for v1:

- No vector database.
- No mandatory embedding pipeline.
- No cloud account or hosted sync service.
- No editor-specific implementation as the primary interface.
- No automatic exfiltration of project data to an LLM provider.

## 3. Design Principles

Memory Fabric v1 follows these principles:

- **MCP-native:** assistants interact with memory through standard MCP tools.
- **File-first:** Markdown files are the source of truth.
- **Local-first:** core memory features work on the user's machine without cloud infrastructure.
- **Provider-agnostic:** optional LLM maintenance supports user-configured providers instead of one hardcoded model.
- **Deterministic retrieval:** context assembly is predictable and debuggable.
- **Human-readable storage:** users can inspect, review, edit, and commit memory files.
- **Privacy by default:** global memory stays local, secrets are redacted, and outbound LLM use is explicit.
- **Graceful degradation:** if optional tools such as `rg`, git hooks, or Dreaming are unavailable, core memory reads and writes still work.

## 4. Architecture

Memory Fabric has three layers:

1. **Data Layer:** global and project memory stored as Markdown files.
2. **Integration Layer:** an MCP server exposing memory tools to AI assistants.
3. **Maintenance Layer:** optional Dreaming jobs that sanitize, summarize, re-index, and propose memory updates.

The architecture is optimized for trust. A user should always be able to answer: what memory exists, where it is stored, why it is being loaded, and what will be sent to an external model.

## 5. Data Layer

### 5.1 Global Memory

Global memory stores developer-level context that applies across projects:

- identity and communication preferences
- coding standards
- security rules
- testing expectations
- durable architectural preferences
- personal workflow conventions

Global memory is local to the developer's machine and is read-only during standard AI sessions unless the user explicitly promotes or edits global rules.

Memory Fabric must resolve global memory using OS-aware application directories:

| Platform | Directory |
| --- | --- |
| Windows | `%APPDATA%/memory-fabric/` |
| macOS | `~/Library/Application Support/memory-fabric/` |
| Linux | `$XDG_CONFIG_HOME/memory-fabric/` or `~/.config/memory-fabric/` |

Recommended global layout:

```text
memory-fabric/
|-- global/
|   |-- directives.md
|   |-- preferences.md
|   |-- coding-standards.md
|   |-- security.md
|   `-- index.md
|-- config.toml
`-- logs/
```

`global/directives.md` is Tier 0 memory. It contains short, immutable rules that must always be loaded fully, such as security practices or testing mandates. This file bypasses normal token budgeting.

### 5.2 Local Project Memory

Local memory lives in the project repository:

```text
.ai-memory/
|-- index.md
|-- architecture.md
|-- schemas.md
|-- decisions.md
|-- debt.md
|-- ubiquitous-language.md
|-- framework-rules.md
`-- .gitignore
```

Project memory is commit-ready by default. It should be treated as reviewable project documentation that helps humans and AI assistants share context.

The generated `.ai-memory/.gitignore` must ignore transient or sensitive implementation artifacts:

```gitignore
*.patch
*.tmp
*.log
snapshots/
private/
.DS_Store
Thumbs.db
```

Teams that need private local notes can use `.ai-memory/private/`, which is ignored by default. Shared memory remains in the top-level `.ai-memory/*.md` files.

### 5.3 File Metadata

Every memory Markdown file uses YAML frontmatter.

Required fields:

```yaml
---
section: architecture
summary: "One-line summary used when the full file cannot fit in context."
priority: high
tags: [api, auth, database]
schema_version: 1.3
last_updated: 2026-06-01T13:00:00-04:00
---
```

Required metadata:

- `section`: stable section identifier.
- `summary`: concise fallback text for token-limited retrieval.
- `priority`: one of `high`, `medium`, or `low`.
- `tags`: list of searchable topic labels.
- `schema_version`: Memory Fabric metadata schema version.
- `last_updated`: timezone-aware ISO 8601 timestamp.

Optional metadata:

- `language`: BCP 47 language tag such as `en`, `pt-BR`, or `es`.
- `owner`: person or team responsible for the memory section.
- `review_status`: one of `draft`, `reviewed`, or `stale`.

Memory content may be written in any human language. Tooling must preserve Unicode text and must not assume English-only content.

## 6. Integration Layer: MCP Server

Memory Fabric ships an MCP server built with the official Python MCP SDK. The primary transport is `stdio`; HTTP/SSE can be added for clients that need daemon-style operation.

Each MCP call receives the project working directory explicitly through `cwd`. The server must not infer the active project from process-global state when the client can provide `cwd`.

### 6.1 MCP Tool Interfaces

```python
@mcp.tool()
def initialize_memory_fabric(cwd: str) -> InitResult:
    """
    Create .ai-memory/ scaffolding, write starter Markdown files with valid
    frontmatter, and generate .ai-memory/.gitignore for transient artifacts.
    """

@mcp.tool()
def read_combined_context(cwd: str, max_tokens: int = 4000) -> ContextBundle:
    """
    Return Tier 0 directives plus prioritized global and local memory within
    the token budget. Files that cannot fit are represented by their summary
    and an omission notice instead of partial broken Markdown.
    """

@mcp.tool()
def read_section(cwd: str, section: str, max_tokens: int = 8000) -> MemorySection:
    """
    Return one memory section by stable section name, respecting token limits.
    """

@mcp.tool()
def keyword_search(cwd: str, query: str, max_results: int = 10) -> list[SearchResult]:
    """
    Search global and local memory with ripgrep when available, falling back to
    pure Python text matching when rg is missing.
    """

@mcp.tool()
def write_local_memory(
    cwd: str,
    section: str,
    content: str,
    mode: str = "append",
) -> WriteResult:
    """
    Append to or replace a project memory section after validation,
    sanitization, and file locking.
    """

@mcp.tool()
def propose_memory_patch(cwd: str, instructions: str) -> PatchPreview:
    """
    Generate a reviewable patch preview for memory changes without applying it.
    """
```

### 6.2 Result Types

The implementation should use structured result objects instead of raw booleans or plain strings.

```python
class InitResult(TypedDict):
    created: bool
    memory_dir: str
    files_created: list[str]
    warnings: list[str]

class ContextBundle(TypedDict):
    text: str
    included_sections: list[str]
    omitted_sections: list[str]
    token_budget: int
    estimated_tokens: int
    warnings: list[str]

class MemorySection(TypedDict):
    section: str
    path: str
    text: str
    metadata: dict
    truncated: bool
    warnings: list[str]

class SearchResult(TypedDict):
    section: str
    path: str
    line: int
    snippet: str

class WriteResult(TypedDict):
    changed: bool
    path: str
    redactions: int
    warnings: list[str]

class PatchPreview(TypedDict):
    patch: str
    affected_files: list[str]
    redactions: int
    warnings: list[str]
```

### 6.3 Retrieval Priority

Context retrieval uses a strict priority order:

| Priority | Source | Policy |
| --- | --- | --- |
| 1 | `global/directives.md` | Always include fully. |
| 2 | Local memory with `priority: high` | Include if possible; otherwise use summary. |
| 3 | Local memory with `priority: medium` | Include if possible; otherwise use summary. |
| 4 | Global memory except Tier 0 | Include if possible; otherwise use summary. |
| 5 | Local memory with `priority: low` | Include if possible; otherwise use summary. |

If a file exceeds the remaining token budget, Memory Fabric must not slice the file mid-document. It should include the file summary, metadata, and a clear omission notice.

## 7. Write Safety and Privacy

All write paths must protect users from accidental sensitive-data capture.

Required safeguards:

- Run secret detection before writing new memory, creating Dreaming inputs, or sending text to an LLM provider.
- Redact detected secrets as `[REDACTED_SECRET]`.
- Return warnings when redaction occurs.
- Use file locks for concurrent writes.
- Preserve valid YAML frontmatter.
- Write UTF-8 without corrupting multilingual content.
- Never write to global memory from ordinary assistant sessions.

Recommended secret detection:

- Use `detect-secrets` or equivalent regex and entropy checks.
- Include provider-specific patterns for common API keys.
- Allow users to add local ignore rules for false positives.

## 8. Maintenance Layer: Dreaming

Dreaming is an optional background process that keeps memory useful over time. It is not required for basic MCP reads or writes.

Dreaming may:

- update `index.md`
- refresh summaries
- identify stale sections
- propose cleanups
- summarize recent project changes
- detect contradictions between memory files
- propose local-to-global rule promotions

Dreaming input sources:

1. User-approved session transcript snippets.
2. Memory Fabric MCP tool-call logs.
3. Git diff since the last Dreaming run.
4. Existing `.ai-memory/*.md` files.

Dreaming must sanitize all inputs before any provider call. If no provider is configured, Dreaming can still run local checks such as frontmatter validation, index consistency, and stale-file detection.

Dreaming writes should use a patch-preview flow:

1. Gather and sanitize inputs.
2. Compute proposed changes outside the write lock.
3. Generate a reviewable patch.
4. Acquire a file lock.
5. Apply the accepted patch.
6. Release the lock.
7. Save a rollback snapshot.

## 9. Dreaming Triggers

Dreaming can be triggered in three ways:

1. **Manual:** `ai-memory dream --mode light|deep`
2. **Git hook:** optional post-commit hook installed by `ai-memory init --install-hooks`
3. **Client lifecycle:** optional IDE or assistant events such as idle time or explicit chat clearing

Git hooks must be opt-in. The default setup should not silently install hooks without user consent.

Dreaming modes:

- `light`: refresh index, summaries, metadata, and stale markers.
- `deep`: perform a broader review of architecture, decisions, debt, schemas, and contradictions.

## 10. CLI Workflow

Memory Fabric is distributed as a Python package with the `ai-memory` command, installable with `pipx` or `uvx`.

Primary commands:

```text
ai-memory init
ai-memory status
ai-memory doctor
ai-memory dream --mode light|deep
ai-memory query "search term"
ai-memory sync-global
ai-memory rollback --to <snapshot>
```

Command behavior:

- `ai-memory init`: creates `.ai-memory/` templates and `.ai-memory/.gitignore`.
- `ai-memory status`: shows active project path, global memory path, memory sizes, and provider status.
- `ai-memory doctor`: validates frontmatter, file permissions, secret-scan configuration, MCP availability, and index consistency.
- `ai-memory dream --mode light|deep`: runs optional maintenance and reports redactions or proposed patches.
- `ai-memory query "search term"`: searches local and global memory from the terminal.
- `ai-memory sync-global`: interactively promotes durable local rules into global memory.
- `ai-memory rollback --to <snapshot>`: restores project memory from a saved snapshot.

## 11. Packaging and Installation

Initial distribution:

```text
pipx install memory-fabric
```

or:

```text
uvx memory-fabric
```

The package should include:

- `ai-memory` CLI
- MCP server entrypoint
- scaffolding templates
- frontmatter validation
- secret scanning integration
- file locking support
- basic Dreaming runner

The package should run on Windows, macOS, and Linux. Platform-specific path handling must be covered by tests.

## 12. Worldwide Readiness

Memory Fabric is intended for developers in all regions and languages.

Requirements:

- Store all files as UTF-8.
- Preserve multilingual Markdown content.
- Support BCP 47 language metadata.
- Use timezone-aware ISO 8601 timestamps.
- Avoid assumptions about US-only paths, date formats, shells, or editor choices.
- Keep core operation offline.
- Avoid requiring a cloud account.
- Make LLM provider use explicit and configurable.
- Keep error messages clear enough for non-native English speakers.

## 13. Security Model

Memory Fabric should assume that memory can accidentally capture sensitive context unless guarded.

Security rules:

- Global memory is local and private by default.
- Project memory is commit-ready but must be secret-scanned.
- Dreaming must sanitize before provider calls.
- MCP tools must validate `cwd` and prevent path traversal outside the intended project/global memory roots.
- Write operations must use file locks.
- Patch previews should be reviewable before automated application.
- Logs must not store raw secrets.

## 14. Testing and Acceptance Criteria

Required test scenarios:

- Scaffolding creates all expected `.ai-memory/` files with valid frontmatter.
- `read_combined_context` always includes Tier 0 directives.
- Token budgeting uses summaries instead of partial Markdown truncation.
- Secret redaction occurs before writes, Dreaming inputs, and provider calls.
- Global memory paths resolve correctly on Windows, macOS, and Linux.
- Keyword search works with `rg` installed and with Python fallback.
- Unicode and multilingual Markdown are preserved.
- Concurrent writes are protected by file locking.
- Rollback restores a snapshot after a failed Dreaming patch.
- `ai-memory doctor` reports invalid frontmatter, stale index data, and missing optional dependencies.

Definition of done for v1:

- A user can install the package, initialize project memory, connect an MCP-compatible assistant, read combined context, write local memory, search memory, and run health checks without configuring cloud services.
- Dreaming remains optional and never sends content to an LLM provider unless the user configures one.
- Project memory is useful as ordinary documentation even without the MCP server.

## 15. Future Extensions

Possible post-v1 extensions:

- Optional embedding search.
- Optional local vector index.
- Optional encrypted cloud sync.
- Team policy packs.
- IDE extensions.
- Memory review UI.
- Enterprise audit logs.
- Organization-managed global directives.

These extensions must not break the v1 file-first contract.
