---
name: agent-router
description: When to use guidelines, memory-fabric, code-graph tools, or skills.
---

# Agent router

Use the cheapest channel that answers the question.

| Question | Where |
|---|---|
| What is the golden rule / naming / test layout? | Project directives (always-on) and `docs/guidelines/` |
| Why did we choose this? ADR, reversal, known failure | `keyword_search_tool` / `context_for_task_tool` / `read_memory_store_tool` |
| How does this function run? call graph | Code-graph / repo search tools — not memory |
| How do I perform a named workflow? | `.agents/skills/` (see `INDEX.md`) |

Do not dump `read_combined_context_tool` mid-session. Do not write `.ai-memory/` with file tools.
