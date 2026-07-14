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
        "frontmatter": {"generated": True},
        "body": "# Project Memory Index\n\nGenerated discovery index — rebuilt by Dreaming. Root maps are generated views over `memory-store/`; granular files are indexed in `memory-store/index.md`.\n",
    },
    "architecture": {
        "priority": "high",
        "summary": "Generated map of memory-store/architecture/ (empty until first Dream).",
        "tags": ["architecture"],
        "frontmatter": {"generated": True, "generated_from": "memory-store/architecture"},
        "body": "# Architecture Map\n\nGenerated view over `memory-store/architecture/` — rebuilt by Dreaming; do not edit by hand. Write granular architecture facts with `write_memory_store_tool`.\n",
    },
    "schemas": {
        "priority": "high",
        "summary": "Generated map of memory-store/schemas/ (empty until first Dream).",
        "tags": ["schemas", "contracts"],
        "frontmatter": {"generated": True, "generated_from": "memory-store/schemas"},
        "body": "# Schemas Map\n\nGenerated view over `memory-store/schemas/` — rebuilt by Dreaming; do not edit by hand. Write granular data contracts with `write_memory_store_tool`.\n",
    },
    "decisions": {
        "priority": "high",
        "summary": "Generated map of memory-store/decisions/ (empty until first Dream).",
        "tags": ["decisions", "adr"],
        "frontmatter": {"generated": True, "generated_from": "memory-store/decisions"},
        "body": "# Decisions Map\n\nGenerated view over `memory-store/decisions/` — rebuilt by Dreaming; do not edit by hand. Write granular decisions and ADRs with `write_memory_store_tool`.\n",
    },
    "debt": {
        "priority": "low",
        "summary": "Generated map of memory-store/debt/ (empty until first Dream).",
        "tags": ["debt", "risk"],
        "frontmatter": {"generated": True, "generated_from": "memory-store/debt"},
        "body": "# Technical Debt Map\n\nGenerated view over `memory-store/debt/` — rebuilt by Dreaming; do not edit by hand. Write granular debt items with `write_memory_store_tool`.\n",
    },
    "ubiquitous-language": {
        "priority": "medium",
        "summary": "Always-loaded steering: project-specific vocabulary and domain terms.",
        "tags": ["domain", "language", "steering"],
        "frontmatter": {"role": "steering"},
        "body": "# Ubiquitous Language\n\nHand-curated steering section, always loaded into context (never evicted by the token budget). Keep entries short: `term — meaning`. Granular term histories belong in `memory-store/ubiquitous-language/`.\n",
    },
    "framework-rules": {
        "priority": "medium",
        "summary": "Always-loaded steering: framework conventions and constraints.",
        "tags": ["framework", "rules", "steering"],
        "frontmatter": {"role": "steering"},
        "body": "# Framework Rules\n\nHand-curated steering section, always loaded into context (never evicted by the token budget). Keep this file short and universally applicable. Granular rule records belong in `memory-store/rules/`.\n",
    },
}

# Store categories pre-scaffolded by `ai-memory init` (ROADMAP Phase 2.2).
# The map categories are derived from SECTION_TEMPLATES' `generated_from` so
# the two can't drift; episodic/failures/rules are the categories written by
# session journaling, failure memory, and the steering templates' granular-
# record pointers respectively.
STORE_CATEGORY_SCAFFOLD: tuple[str, ...] = tuple(
    sorted(
        {
            str(template["frontmatter"]["generated_from"]).split("/", 1)[1]
            for template in SECTION_TEMPLATES.values()
            if "generated_from" in template.get("frontmatter", {})
        }
        | {"episodic", "failures", "rules"}
    )
)

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
- **Bug fixes:** Call `write_failure_memory_tool(cwd, error_summary, fix_summary)` right after fixing a bug. Repeat occurrences of the same error accumulate onto one entry instead of scattering — this is the highest-value memory category for future debugging.

### 5. Session End — Automatic Journaling
Before completing a session, call `write_session_journal_tool(cwd, summary, key_decisions, files_changed, session_label)` to capture what happened.

**Always journal after:** feature implementations, bug fixes, refactoring, architecture decisions, debugging, config changes, or any session where you wrote or modified code.

**Skip only for:** simple Q&A, quick lookups, or read-only explanations that produced no actionable changes.

Parameters:
- `summary`: 2-4 sentence description of what was accomplished.
- `key_decisions`: List of architecture/design decisions made (optional).
- `files_changed`: List of files created or significantly modified (optional).
- `session_label`: Short descriptive label, e.g. `"auth-refactor"` (optional).
"""

DREAMING_INSTRUCTIONS = """## Memory Fabric — Dreaming Process Instructions

⚠️ **Pre-requisite — Save discrete knowledge first:** Before calling any Dream tool, ensure all specific, isolated learnings from the current session have been persisted via `write_memory_store_tool`. Dream consolidates EXISTING memory — it does NOT substitute for creating new standalone memory files.

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
        "---\n\n" + MEMORY_INSTRUCTIONS
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
        "---\n\n" + MEMORY_INSTRUCTIONS + "\n" + DREAMING_INSTRUCTIONS
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
    # Extra frontmatter carried by the template (e.g. `generated`/`role` markers).
    metadata.update(template.get("frontmatter", {}))
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
