---
store_path: debt/dreaming-roadmap
section: dreaming-roadmap
summary: "Detailed roadmap and acceptance criteria for the dream_tool's consolidation and agent-assisted rewrite features."
priority: low
tags: [debt, roadmap, dreaming, cli]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Dreaming Roadmap: Consolidation, Non-Destructive Output, and Agent-Assisted Rewrite

**Component Focus:** CLI (`dream` command)

## Current Limitations
The `dream_tool` currently creates a snapshot and regenerates `index.md`, but it does not consolidate redundant memory, produce a separate candidate output store, or invoke an LLM/agent rewrite path.

## Planned Improvements

- **Deduplication / Consolidation:** Scan memory sections for repeated or overlapping entries, group related notes, and produce condensed candidate content that preserves provenance and avoids unbounded memory growth.
- **Non-destructive Cloning:** Run Dreaming against a separate candidate memory store created from the latest snapshot, not directly against the live `.ai-memory` files. Promotion to live memory should require an explicit apply/promote step and should keep rollback snapshots available.
- **Agent-assisted LLM Rewriting:** Do not rely only on `MEMORY_FABRIC_LLM_PROVIDER`. Add a workflow where `dream_tool` can return structured rewrite tasks, diffs, or prompts for the host agent to execute with its own available tools, then validate and apply the resulting patch through Memory Fabric write paths.
- **Search Index Upgrade:** Regenerate `index.md` as a navigable map with stable slugs pointing to sections and important entries, so future agents can read the index first before broad keyword search.

## Acceptance Criteria

- Dreaming has a dry-run or candidate-output mode that never mutates live memory before explicit promotion.
- Tests prove live memory remains unchanged when candidate generation fails.
- Consolidation detects duplicate bullets or near-identical saved notes and proposes a merged result.
- Agent-assisted rewriting produces inspectable diffs and still passes secret redaction before write.
- Dreaming evaluation compares pre-dream snapshot, candidate output, and promoted output.
