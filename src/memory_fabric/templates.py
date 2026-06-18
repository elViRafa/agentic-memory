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

🚨 **CRITICAL RULES - READ FIRST** 🚨
1. **NEVER use the native VS Code Copilot `memory` tool.** You MUST ONLY use the `memory-fabric` MCP tools (like `write_memory_store_tool`). The native `memory` tool writes to VS Code workspace storage, bypassing this project's memory system.
2. **NEVER use raw file system tools** (like `create_file`, `write_to_file`, `bash`, etc.) to read or write files inside the `.ai-memory/` directory. Doing so bypasses secret scanning, token budgeting, and the Dreaming system.
3. **MANDATORY STARTUP:** You MUST call `read_combined_context_tool(cwd="<absolute project root path>")` before doing anything else at the start of a session. No exceptions.

### 1. Active Retrieval Workflow
- **Search:** Use `keyword_search_tool(cwd, query)` to find specific documented topics.
- **Deep Dive:** Use `read_memory_store_tool(cwd, store_path)` or `read_section(cwd, section)` for detailed content.

### 2. Store Writes & Rules
Use `write_memory_store_tool` to register standalone memories.
- **`store_path` Rules:** Must be lowercase, alphanumeric segments separated by slashes. No spaces, capitals, or `.md` extension (e.g., `architecture/decisions/jwt-auth`). Max 5 levels of nesting.
- **Parameters:** `cwd`, `store_path`, `content`, `title` (optional), `tags` (optional), `priority` (`high`/`medium`/`low`), `mode` (`replace`/`append`).

### 3. Legacy Section Writes
For legacy flat section files (e.g. `debt`), call `write_local_memory_tool(cwd, section, content, mode="append")`.

### 4. Security & Maintenance
- **Security:** Do NOT store credentials, tokens, or passwords.
- **Dreaming:** Use `dream_tool` for consolidation. Refer to `.agents/rules/dreaming.md` for guidelines.
"""

DREAMING_INSTRUCTIONS = """## Memory Fabric — Dreaming Process Instructions

Trigger a dream after significant changes or bug fixes to refresh indices and resolve contradictions.

### 1. Direct Dreaming
Call `dream_tool` with parameters:
- `cwd`: Absolute path to project root.
- `mode`: `"light"` (index/summaries) or `"deep"` (comprehensive review).
- `apply`: Set `True` to persist updates; `False` runs dry-run/candidate mode.
- `llm_rewrite`: Set `True` to generate rewrite tasks.
- `with_eval`: Set `True` (with `apply=True`) to run quality evaluation.

### 2. Split-Tool Protocol (Avoiding Client Deadlocks)
If client-side LLM consolidation is needed (e.g., no direct LLM or to bypass JSON-RPC deadlocks):
1. Call `prepare_dream_payload_tool(cwd, mode="deep")`.
2. If response contains `"skip_required": true`, stop here.
3. Pass the returned `consolidation_prompt` to your LLM.
4. Call `apply_dream_results_tool(cwd, candidate_store, llm_response)` passing the LLM's raw JSON response and `candidate_store` value.
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
