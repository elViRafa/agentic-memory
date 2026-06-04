"""Generated project memory templates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memory_fabric.frontmatter import dump_frontmatter


SCHEMA_VERSION = "1.3"

SECTION_TEMPLATES: dict[str, dict[str, Any]] = {
    "index": {
        "priority": "high",
        "summary": "Map of available project memory sections.",
        "tags": ["index", "memory"],
        "body": "# Project Memory Index\n\nThis file summarizes the memory sections available for this project.\n",
    },
    "architecture": {
        "priority": "high",
        "summary": "Project architecture, boundaries, and important system flows.",
        "tags": ["architecture"],
        "body": "# Architecture\n\nRecord durable architecture context here.\n",
    },
    "schemas": {
        "priority": "high",
        "summary": "Important data models, schemas, and contracts.",
        "tags": ["schemas", "contracts"],
        "body": "# Schemas\n\nRecord important data contracts here.\n",
    },
    "decisions": {
        "priority": "medium",
        "summary": "Architecture and product decisions with rationale.",
        "tags": ["decisions", "adr"],
        "body": "# Decisions\n\nRecord durable decisions and rationale here.\n",
    },
    "debt": {
        "priority": "low",
        "summary": "Known technical debt, risks, and cleanup targets.",
        "tags": ["debt", "risk"],
        "body": "# Technical Debt\n\nRecord known risks and cleanup opportunities here.\n",
    },
    "ubiquitous-language": {
        "priority": "medium",
        "summary": "Project-specific vocabulary and domain terms.",
        "tags": ["domain", "language"],
        "body": "# Ubiquitous Language\n\nRecord project terminology here.\n",
    },
    "framework-rules": {
        "priority": "medium",
        "summary": "Framework-specific conventions and constraints.",
        "tags": ["framework", "rules"],
        "body": "# Framework Rules\n\nRecord framework conventions here.\n",
    },
}

LOCAL_GITIGNORE = """*.patch
*.tmp
*.log
*.lock
consolidated_memory.md
evals/
snapshots/
candidates/
private/
.DS_Store
Thumbs.db
"""

# ---------------------------------------------------------------------------
# Canonical Content Blocks — THE single source of truth for agent instructions.
# All platform-specific files are generated from these two blocks.
# ---------------------------------------------------------------------------

MEMORY_INSTRUCTIONS = """## Memory Fabric — Semantic Store Agent Instructions

You must use the `memory-fabric` MCP tools for all project memory operations. Do not read or write `.ai-memory/` files using raw file-system tools.

### 1. Startup & Retrieval (The Active Memory Workflow)
Accessing the Memory Store is an active process driven by the agent using the following tools:

1. **Session Map:** At session start, you MUST call `read_combined_context_tool(cwd="<absolute project root path>")`. This serves as your index map to quickly grasp what is stored, load directives, and active session steering prompts.
2. **Search & Target:** To find specific information without reading everything, use `keyword_search_tool(cwd="...", query="<keyword>")` to look for relevant topics already documented in memory.
3. **Deep Dive:** After locating a reference via the index or keyword search, go straight to the necessary file by calling `read_memory_store_tool` (for semantic paths) or `read_section` (for legacy sections) to extract the full context needed for your answer.

### 2. Registering Memory in the Store
After completing a task (e.g., a design decision, a bug fix, schema creation, or refactoring), persist this knowledge.

Use `write_memory_store_tool` to register small, standalone memory files.

**Strict Semantic Store Rules:**
1. **`store_path` formatting:** Must be lowercase, alphanumeric segments separated by slashes. No spaces, no capital letters, and **no `.md` extension** (e.g., `architecture/decisions/jwt-auth` or `bugs/auth-redirect-fix`).
2. **Path Nesting:** Max 5 levels of directory nesting.
3. **Duplicate Prevention:** The tool automatically strips out duplicate bullet points or lines when appending.

**Tool Parameters:**
* `cwd`: Absolute path to project root.
* `store_path`: The semantic path (e.g., `architecture/decisions/auth-service`).
* `content`: The markdown text body of the memory.
* `title`: (Optional) Human-readable title.
* `tags`: (Optional) Comma-separated tags (e.g., `auth,security`).
* `priority`: (Optional) `high`, `medium`, or `low` (default: `medium`).
* `mode`: (Optional) `replace` to overwrite, or `append` to add to the end (default: `replace`).

### 3. Legacy Section Writes
If you are updating a legacy flat section file (e.g., updating a list of risks in `debt`), call `write_local_memory_tool(cwd="...", section="debt", content="...", mode="append")`. Prefer `write_memory_store_tool` for new standalone topics.

### 4. Security & Best Practices
* **Do NOT** store credentials, tokens, or passwords in memory — the server redacts them, but avoid writing them in the first place.

### 5. Memory Maintenance (Dreaming)
To consolidate memory, check for contradictions, or refresh the index, you can use the `dream_tool`. For detailed instructions on parameters (like `mode` and `apply`) and when to trigger a dream, refer to `.agents/rules/dreaming.md`.
"""

DREAMING_INSTRUCTIONS = """## Memory Fabric — Dreaming Process Instructions

Memory Fabric includes an optional background maintenance process called "Dreaming." As an agent, you have access to the `dream_tool` to trigger this process.

### When to trigger Dreaming
You should trigger a dream after making significant architectural changes, resolving complex bugs, or accumulating multiple smaller updates in the memory store. It helps to consolidate the memory, refresh indices, and identify contradictions.

### How to use `dream_tool`
The `dream_tool` accepts several important parameters. You must configure them correctly to actually apply changes:

* `cwd`: Absolute path to the project root.
* `mode`: 
  * `"light"` (default): Fast refresh of the index, summaries, and stale markers.
  * `"deep"`: Comprehensive review of architecture, decisions, debt, and contradictions.
* `apply`: **CRITICAL.** Set to `True` if you want the dreaming process to actually save its generated updates and summaries. If `False` (default), it will only run in a dry-run "candidate" mode.
* `llm_rewrite`: Set to `True` if you want the LLM to actively propose rewrites or patches to the memory.
* `with_eval`: Set to `True` to run an evaluation on the dreaming quality. (Requires `apply=True`).

### Example
If you just finished a major refactoring and want to update the memory indices and summaries, call:
`dream_tool(cwd="<project-root>", mode="light", apply=True)`
"""

# ---------------------------------------------------------------------------
# Platform-specific builder functions
# ---------------------------------------------------------------------------


def build_agents_md() -> str:
    """Build AGENTS.md — universal fallback for Gemini CLI, Codex, Antigravity, etc."""
    return (
        "# Agent Instructions — Memory Fabric\n\n"
        "This file is read automatically by Claude Code, Gemini CLI, Codex, Antigravity, and other MCP-aware AI agents.\n"
        "GitHub Copilot reads `.github/copilot-instructions.md` instead.\n\n"
        "---\n\n"
        + MEMORY_INSTRUCTIONS
    )


def build_agents_rule_memory() -> str:
    """Build .agents/rules/memory-store.md — generic IDE rule with YAML trigger."""
    return "---\ntrigger: always_on\n---\n\n" + MEMORY_INSTRUCTIONS


def build_agents_rule_dreaming() -> str:
    """Build .agents/rules/dreaming.md — generic IDE rule with YAML trigger."""
    return "---\ntrigger: always_on\n---\n\n" + DREAMING_INSTRUCTIONS


def build_cursor_rule() -> str:
    """Build .cursor/rules/memory-fabric.mdc — Cursor IDE rule with MDC frontmatter."""
    return (
        "---\n"
        "description: Memory Fabric — project memory management via MCP tools\n"
        "alwaysApply: true\n"
        "---\n\n"
        + MEMORY_INSTRUCTIONS
        + "\n"
        + DREAMING_INSTRUCTIONS
    )


def build_windsurf_rule() -> str:
    """Build .windsurf/rules/memory-fabric.md — Windsurf IDE rule."""
    return MEMORY_INSTRUCTIONS + "\n" + DREAMING_INSTRUCTIONS


def build_claude_md() -> str:
    """Build standalone CLAUDE.md content for Claude Code."""
    return MEMORY_INSTRUCTIONS + "\n" + DREAMING_INSTRUCTIONS


def build_copilot_md() -> str:
    """Build standalone .github/copilot-instructions.md content for GitHub Copilot."""
    return MEMORY_INSTRUCTIONS + "\n" + DREAMING_INSTRUCTIONS


# Legacy aliases kept for backward compatibility in imports
AGENT_INSTRUCTIONS_TEMPLATE = build_agents_md()
MEMORY_STORE_RULE_TEMPLATE = build_agents_rule_memory()
DREAMING_RULE_TEMPLATE = build_agents_rule_dreaming()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_memory_file(section: str) -> str:
    template = SECTION_TEMPLATES[section]
    metadata = {
        "section": section,
        "summary": template["summary"],
        "priority": template["priority"],
        "tags": template["tags"],
        "schema_version": SCHEMA_VERSION,
        "last_updated": now_iso(),
    }
    return dump_frontmatter(metadata, template["body"])


def build_empty_section(section: str, body: str = "") -> str:
    metadata = {
        "section": section,
        "summary": f"Project memory section for {section}.",
        "priority": "medium",
        "tags": [section],
        "schema_version": SCHEMA_VERSION,
        "last_updated": now_iso(),
    }
    return dump_frontmatter(metadata, body or f"# {section.replace('-', ' ').title()}\n")
