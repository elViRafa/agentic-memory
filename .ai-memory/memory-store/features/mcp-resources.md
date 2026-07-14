---
store_path: features/mcp-resources
title: "MCP Resources: Automatic Context Delivery"
summary: "MCP Resources: Automatic Context Delivery"
priority: high
tags: [mcp, resources, auto-fetch, context]
schema_version: 1.3
last_updated: "2026-06-22T09:09:32-04:00"
---

# MCP Resources: Automatic Context Delivery

Added two MCP Resource Template registrations to `server.py` that allow clients supporting the MCP Resources primitive to auto-fetch memory context at session start — without any agent tool call.

## Resources registered

| URI Template | Content | MIME |
|---|---|---|
| `memory-fabric://context/{encoded_cwd}` | Full assembled context bundle (same as `read_combined_context_tool`) | `text/plain` |
| `memory-fabric://index/{encoded_cwd}` | Only `index.md` (lightweight section map) | `text/plain` |

## URL encoding
- `cwd` is encoded with `urllib.parse.quote(cwd, safe="")` before embedding in URI.
- Decoded with `urllib.parse.unquote(encoded_cwd)` on the server side.
- This handles Windows paths (backslashes, colons in drive letters) safely.

## Graceful degradation
- If `.ai-memory/` is not initialized, resource returns an advisory string instead of raising.
- If `cwd` is invalid (dangerous path, non-existent), returns advisory string.

## InitResult.resource_uris
- `initialize_memory_fabric_tool` now returns `resource_uris` in its result — a list of the two resource URIs for the initialized project. Clients can bookmark these.

## Client compatibility
- Claude Desktop: auto-fetches resources before first message ✓
- Claude Code CLI: depends on version (auto-fetch not guaranteed)
- Resources are additive — tool-based workflow unchanged.

## Files changed
- `src/memory_fabric/server.py` — resources + updated init tool
- `src/memory_fabric/contracts.py` — `resource_uris: NotRequired[list[str]]` in `InitResult`
- `src/memory_fabric/templates.py` — note about Resources alternative in `MEMORY_INSTRUCTIONS`
- `tests/test_resources.py` — 11 new tests, all passing
