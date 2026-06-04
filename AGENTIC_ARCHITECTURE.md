# Agentic Architecture & Rule Registry

## 1. Overview
Memory Fabric operates as an MCP (Model Context Protocol) server. While the server itself exposes tools (like `read_memory_store_tool`, `keyword_search_tool`, and `dream_tool`), AI agents still need to be taught *when* and *how* to use those tools. 

We achieve this through a series of markdown-based instruction files (rules). Because different AI agents (e.g., GitHub Copilot, Claude Code, Cursor, Windsurf, Codex, Antigravity) look for instructions in different places, Memory Fabric maintains a diverse set of rule bindings to ensure universal compatibility.

This document serves as the central registry for understanding how these rule files are structured and deployed.

---

## 2. Canonical Content Blocks (The Single Source of Truth)

All platform-specific files are generated from exactly **two** canonical content blocks defined in `src/memory_fabric/templates.py`:

| Block | Purpose |
|:---|:---|
| `MEMORY_INSTRUCTIONS` | Core workflow: how to read, write, and search project memory via MCP tools. Includes security best practices and a pointer to the dreaming rules. |
| `DREAMING_INSTRUCTIONS` | Specialized instructions for the `dream_tool` — parameters, modes, and when to trigger background memory maintenance. |

These blocks contain **pure content** with no platform-specific formatting. Each target file is assembled by wrapping them with the appropriate headers and frontmatter.

---

## 3. The Rule Files Registry

The following files are deployed into target repositories when a user runs `ai-memory init`:

| File Path | Target Agent(s) | Content | Format |
| :--- | :--- | :--- | :--- |
| **`AGENTS.md`** | Gemini CLI, Codex, Antigravity | Memory instructions | Root markdown with header |
| **`.agents/rules/memory-store.md`** | Cline, generic IDE agents | Memory instructions | YAML frontmatter (`trigger: always_on`) |
| **`.agents/rules/dreaming.md`** | Cline, generic IDE agents | Dreaming instructions | YAML frontmatter (`trigger: always_on`) |
| **`.cursor/rules/memory-fabric.mdc`** | Cursor IDE | Memory + Dreaming (combined) | MDC frontmatter (`alwaysApply: true`) |
| **`.windsurf/rules/memory-fabric.md`** | Windsurf IDE | Memory + Dreaming (combined) | Plain markdown |
| **`CLAUDE.md`** | Claude Code | Memory + Dreaming (combined) | Root markdown (created or appended) |
| **`.github/copilot-instructions.md`** | GitHub Copilot | Memory + Dreaming (combined) | GitHub directory (created or appended) |

> **Note:** For Cursor and Windsurf, both the memory and dreaming instructions are combined into a single file to minimize rule count and context switching. For the `.agents/rules/` convention, they are kept separate since those agents support modular rule loading.

---

## 4. Deployment Strategy

### Initial Deployment (`ai-memory init`)
When a user runs the `initialize_memory_fabric()` function (via `ai-memory init`) inside a new target repository, the CLI automatically deploys all files from the registry above. For `CLAUDE.md` and `.github/copilot-instructions.md`, if the file already exists, the Memory Fabric instructions are **appended** (not overwritten) to preserve any existing content.

### Synchronization (`ai-memory sync-agents`)
The `sync_agent_rules()` function **regenerates** all platform-specific files directly from the canonical templates in `templates.py`. This approach:
- Guarantees **perfect consistency** across all files
- Leaves `AGENTS.md` untouched — users can add project-specific context (build commands, architecture notes) without it leaking into IDE rule files
- Only writes files that have actually changed (diff-aware)

### Automated Sync (Git Pre-Commit Hook)
When `ai-memory init --install-hooks` is used, a `pre-commit` hook is installed that:
1. Runs `ai-memory sync-agents` silently
2. Stages all modified platform files via `git add`
3. Ensures every commit has perfectly synchronized agent instructions

---

## 5. How to Add New Rules

If you are developing a new MCP tool for Memory Fabric:

1. **Add to canonical blocks:** Update `MEMORY_INSTRUCTIONS` or `DREAMING_INSTRUCTIONS` in `src/memory_fabric/templates.py` with the new tool's usage instructions.
2. **All files update automatically:** Since every platform file is generated from these blocks, a single edit propagates everywhere.
3. **For complex tools:** If the new tool needs extensive documentation, consider creating a new canonical block (e.g., `VISUALIZATION_INSTRUCTIONS`) and adding it to the appropriate builder functions.
