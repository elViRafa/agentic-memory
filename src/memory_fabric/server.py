"""MCP server entrypoint for Memory Fabric."""

from __future__ import annotations

from memory_fabric.eval import evaluate_dream_quality, evaluate_memory_fabric
from memory_fabric.storage import (
    initialize_memory_fabric,
    keyword_search,
    propose_memory_patch,
    read_combined_context,
    read_section,
    write_local_memory,
)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only when optional mcp is absent.
    FastMCP = None  # type: ignore[assignment]


if FastMCP is not None:
    mcp = FastMCP("Memory Fabric")

    @mcp.tool()
    def initialize_memory_fabric_tool(cwd: str):
        return initialize_memory_fabric(cwd)

    @mcp.tool()
    def read_combined_context_tool(cwd: str, max_tokens: int = 4000):
        return read_combined_context(cwd, max_tokens=max_tokens)

    @mcp.tool()
    def read_section_tool(cwd: str, section: str, max_tokens: int = 8000):
        return read_section(cwd, section=section, max_tokens=max_tokens)

    @mcp.tool()
    def keyword_search_tool(cwd: str, query: str, max_results: int = 10):
        return keyword_search(cwd, query=query, max_results=max_results)

    @mcp.tool()
    def write_local_memory_tool(cwd: str, section: str, content: str, mode: str = "append"):
        return write_local_memory(cwd, section=section, content=content, mode=mode)  # type: ignore[arg-type]

    @mcp.tool()
    def propose_memory_patch_tool(cwd: str, instructions: str):
        return propose_memory_patch(cwd, instructions=instructions)

    @mcp.tool()
    def evaluate_memory_fabric_tool(cwd: str, save_report: bool = False, llm_review: bool = False):
        return evaluate_memory_fabric(cwd, save_report=save_report, llm_review=llm_review)

    @mcp.tool()
    def evaluate_dream_quality_tool(
        cwd: str,
        snapshot: str,
        save_report: bool = False,
        llm_review: bool = False,
    ):
        return evaluate_dream_quality(cwd, snapshot=snapshot, save_report=save_report, llm_review=llm_review)
else:
    mcp = None


def main() -> int:
    if mcp is None:
        raise SystemExit("The optional `mcp` package is not installed. Install with: pipx inject memory-fabric mcp")
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
