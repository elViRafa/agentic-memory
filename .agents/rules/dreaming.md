---
trigger: always_on
---

## Memory Fabric — Dreaming Process Instructions

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
