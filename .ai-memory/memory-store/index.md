---
store_path: index
title: "Memory Store Index"
summary: "Index of all semantic memory store files."
priority: high
tags: [index, memory-store]
schema_version: 1.3
last_updated: "2026-07-13T21:22:39-04:00"
---

# Memory Store Index

Updated by Memory Fabric Dreaming mode `light`.

| Path | Priority | Summary | Key Topics | Tags |
| --- | --- | --- | --- | --- |
| `architecture/agent-rules` | high | Agentic Architecture & Rule Registries | • AGENTS.md: Universal instructions at project root.<br>• .agents/rules/memory-store.md: Core rules formatted for I...<br>• .agents/rules/dreaming.md: Specialized parameter rules fo... | architecture, agents, rules |
| `architecture/core-characteristics` | high | Core Characteristics | • **MCP-Native**: Exposes memory tools through the standard...<br>• **File-First**: Markdown files are the source of truth, i...<br>• **Local-First**: Core reads and writes work offline. | architecture, design, overview, migrated |
| `architecture/decisions/dream-store-sub-index` | high | Dream Store Sub Index | None recorded | dreaming, memory-store, architecture |
| `architecture/decisions/dream-store-subfolders` | high | Details hierarchical memory storage structure using `local/` and `store/` prefixes for accurate path preservation during consolidation. | None recorded | dreaming, memory-store, architecture |
| `architecture/global-memory` | high | Global Memory | • Windows: `%APPDATA%\memory-fabric\global\`<br>• macOS: `~/Library/Application Support/memory-fabric/global/`<br>• Linux: `$XDG_CONFIG_HOME/memory-fabric/global/` | architecture, design, overview, migrated |
| `architecture/granular-architecture-records` | high | Granular Architecture Records | None recorded | architecture, design, overview, migrated |
| `architecture/grok-support` | high | Grok client support and integration | • Grok Support Added (2026-06-05) | grok, agents, architecture, mcp, docs |
| `architecture/overview` | high | Architecture Overview | None recorded | architecture, design, overview, migrated |
| `architecture/project-memory-layout` | high | Project Memory Layout | None recorded | architecture, design, overview, migrated |
| `architecture/system-flow-component-boundaries` | high | System Flow & Component Boundaries | None recorded | architecture, design, overview, migrated |
| `architecture/tests/isolated-unit-tests` | low | Contains isolated unit tests for utility functions like frontmatter parsing and security checks, separating them from high-level integration tests. | • Extracted utility tests for frontmatter.py and security.p...<br>• Promoted isolated test cases for token signatures (ghp, A...<br>• Ensured high-level tests remain in test_memory_fabric.py,... | tests, frontmatter, security |
| `debt/debt-strategy` | low | Debt Strategy | None recorded | debt, risk, map, migrated |
| `debt/dreaming-roadmap` | low | Detailed roadmap and acceptance criteria for the dream_tool's consolidation and agent-assisted rewrite features. | • Current Limitations<br>• Planned Improvements<br>• Acceptance Criteria | debt, roadmap, dreaming, cli |
| `debt/granular-debt-records` | low | Granular Debt Records | None recorded | debt, risk, map, migrated |
| `debt/overview` | low | Debt Overview | None recorded | debt, risk, map, migrated |
| `decisions/cli-ux` | low | Decisions regarding the ai-memory CLI UX, outputs, and validation rules. | • Status and Doctor Commands<br>• Sync Command<br>• Diagnostic and Evaluation | decisions, cli, ux, commands |
| `decisions/core-storage` | medium | Decisions regarding markdown file storage, staleness, and memory deduplication. | • Staleness<br>• Write Integrity | decisions, storage, core, markdown |
| `decisions/engineering-philosophy` | high | Engineering Philosophy | None recorded | decisions, adr, map, migrated |
| `decisions/git-integration` | low | Decisions regarding Git hooks and subprocess integrations for memory maintenance. | • Post-Commit Hooks<br>• Ingestion & Subprocesses | decisions, git, hooks, subprocess |
| `decisions/granular-decisions-adr` | high | Granular Decisions (ADR) | None recorded | decisions, adr, map, migrated |
| `decisions/llm-infrastructure` | medium | Decisions regarding LLM providers, retry logic, sanitization, and optimization. | • Providers & Connectivity<br>• Optimization & Caching<br>• Security | decisions, llm, infrastructure, optimization |
| `decisions/overview` | high | Decisions Overview | None recorded | decisions, adr, map, migrated |
| `episodic/2026-07-07` | low | Episodic Journal — 2026-07-07 | • store-first-v06 | episodic, session-journal |
| `features/mcp-resources` | high | MCP Resources: Automatic Context Delivery | • Resources registered<br>• URL encoding<br>• Graceful degradation<br>• InitResult.resource_uris<br>• Client compatibility<br>• Files changed | mcp, resources, auto-fetch, context |
| `rules/mcp-agent-instructions` | high | Crucial instructions for AI Agents interacting with the Memory Fabric via MCP Server tools. | None recorded | rules, agents, mcp, tools |
| `schemas/cli-contracts` | medium | TypedDict contracts governing the CLI diagnostic, status, and dreaming commands. | • Diagnostic & Status<br>• Dreaming & Maintenance | schemas, contracts, cli, dreaming |
| `schemas/design-philosophy` | high | Design Philosophy | None recorded | schemas, contracts, map, migrated |
| `schemas/eval-contracts` | low | TypedDict contracts governing the memory and dreaming evaluation results. | None recorded | schemas, contracts, eval |
| `schemas/frontmatter` | high | Schema definition for the YAML frontmatter used across Memory Fabric markdown files. | None recorded | schemas, frontmatter, yaml |
| `schemas/granular-contracts` | high | Granular Contracts | None recorded | schemas, contracts, map, migrated |
| `schemas/mcp-contracts` | high | TypedDict contracts governing the MCP Server tool requests and JSON-RPC responses. | • Context & Initialization<br>• Search & Write Operations | schemas, contracts, mcp, typeddict |
| `schemas/overview` | high | Schemas Overview | None recorded | schemas, contracts, map, migrated |
