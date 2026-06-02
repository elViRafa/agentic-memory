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
evals/
snapshots/
candidates/
private/
.DS_Store
Thumbs.db
"""


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
