---
section: ubiquitous-language
summary: "Defines domain terms and structures the local-first context memory using sections, frontmatter, and maintenance workflows."
priority: medium
tags: [domain, language, glossary, definitions]
schema_version: 1.3
last_updated: "2026-06-03T08:28:05-04:00"
summary_hash: 6efb9a96e28e10e10f2f2514a3a17e0f
---

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
