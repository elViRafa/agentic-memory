---
trigger: always_on
---

## Memory Fabric — Dreaming Process Instructions

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
