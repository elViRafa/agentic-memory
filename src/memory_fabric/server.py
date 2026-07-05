"""MCP server entrypoint for Memory Fabric."""

from __future__ import annotations

import urllib.parse
from typing import Any

from memory_fabric.contracts import (
    ContextBundle,
    DreamEvalResult,
    DreamResult,
    EpisodicJournalResult,
    EvalResult,
    InitResult,
    MemorySection,
    PatchPreview,
    SearchResult,
    StoreListResult,
    StoreReadResult,
    StoreWriteResult,
    WriteResult,
)
from memory_fabric.eval import evaluate_dream_quality, evaluate_memory_fabric
from memory_fabric.paths import local_memory_dir, validate_cwd
from memory_fabric.storage import (
    delete_memory_store,
    dream,
    initialize_memory_fabric,
    keyword_search,
    list_memory_store,
    propose_memory_patch,
    read_combined_context,
    read_memory_store,
    read_section,
    write_local_memory,
    write_memory_store,
    write_session_journal,
    prepare_dream_payload,
    apply_dream_results,
)

try:
    from mcp.server.fastmcp import FastMCP, Context
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:  # pragma: no cover - exercised only when optional mcp is absent.
    FastMCP = None  # type: ignore[assignment, misc]
    Context = None  # type: ignore[assignment, misc]
    TransportSecuritySettings = None  # type: ignore[assignment, misc]


mcp: FastMCP[Any] | None

if FastMCP is not None:
    from memory_fabric.llm import load_env_from_cwd

    mcp = FastMCP("Memory Fabric")

    def _safe_cwd(cwd: str) -> str:
        """Validate the agent-supplied cwd and load .env before any tool call.

        Raises ValueError if cwd is empty, non-existent, or resolves to a
        dangerous system path (path traversal protection).
        """
        safe = validate_cwd(cwd)
        load_env_from_cwd(str(safe))
        return str(safe)

    @mcp.tool()
    def initialize_memory_fabric_tool(cwd: str, memory_prompt: str | None = None) -> InitResult:
        """Bootstrap Memory Fabric in the project at *cwd*.

        Creates the local `.ai-memory/` directory with starter section files
        (architecture, decisions, debt, etc.), the semantic `memory-store/`
        directory, a `.gitignore`, and deploys agent instruction files for all
        supported platforms (GitHub Copilot, Claude Code, Gemini CLI, etc.).
        Safe to call multiple times — missing files are created, and existing content is preserved (some files may be appended or updated).

        Also returns ``resource_uris`` with the MCP Resource URIs for this project.
        Clients that support MCP Resources can auto-fetch context from those URIs
        at session start without any explicit tool call.

        Args:
            cwd:           Absolute path to the project root.
            memory_prompt: Optional plain-text prompt to persist as
                           `memory_prompt.txt`, which agents prepend to every
                           context load.  Pass an empty string to delete an
                           existing prompt file.
        """
        safe = _safe_cwd(cwd)
        result = initialize_memory_fabric(safe, memory_prompt=memory_prompt)
        encoded = urllib.parse.quote(safe, safe="")
        result["resource_uris"] = [
            f"memory-fabric://context/{encoded}",
            f"memory-fabric://index/{encoded}",
        ]
        return result

    @mcp.tool()
    def read_combined_context_tool(
        cwd: str, max_tokens: int | None = None, query: str | None = None
    ) -> ContextBundle:
        """Load and assemble the full memory context for the project.

        Reads all local memory section files and memory-store entries, assembles
        them into a single ``ContextBundle``, and trims to the token budget.
        **Call this at the start of every session** before any other tool.

        Args:
            cwd:        Absolute path to the project root.
            max_tokens: Token budget for context assembly.  Defaults to the
                        ``MEMORY_FABRIC_TOKEN_BUDGET`` env var, or 4000 if
                        not set.
            query:      Optional natural-language query.  When provided,
                        sections are ranked by BM25-style keyword relevance so
                        the most relevant content is included first.  Bypasses
                        the result cache.
        """
        safe = _safe_cwd(cwd)
        return read_combined_context(safe, max_tokens=max_tokens, query=query)

    @mcp.tool()
    def read_section_tool(cwd: str, section: str, max_tokens: int = 8000) -> MemorySection:
        """Read a single flat memory section file by name.

        Flat sections live directly inside `.ai-memory/` (e.g. `architecture`,
        `decisions`, `debt`).  Use ``read_memory_store_tool`` instead for
        semantic store files under `memory-store/`.

        Args:
            cwd:        Absolute path to the project root.
            section:    Section name without the `.md` extension
                        (e.g. ``"architecture"``).
            max_tokens: Maximum tokens to return.  If the file exceeds this
                        limit only its frontmatter summary is returned.
        """
        safe = _safe_cwd(cwd)
        return read_section(safe, section=section, max_tokens=max_tokens)

    @mcp.tool()
    def keyword_search_tool(cwd: str, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search all memory files by keyword and return ranked results.

        Uses ripgrep when available, falling back to a pure-Python search.
        Results include both flat section files and semantic store files.
        Each result contains a ``backend`` field indicating the search engine
        used (``"ripgrep"`` or ``"python"``).

        Args:
            cwd:         Absolute path to the project root.
            query:       Keyword or phrase to search for.
            max_results: Maximum number of results to return (default 10).
        """
        safe = _safe_cwd(cwd)
        return keyword_search(safe, query=query, max_results=max_results)

    @mcp.tool()
    def write_local_memory_tool(
        cwd: str, section: str, content: str, mode: str = "append"
    ) -> WriteResult:
        """Write or append content to a flat memory section file.

        Flat sections live directly inside `.ai-memory/` (e.g. `architecture`,
        `decisions`, `debt`).  Duplicate lines are automatically filtered out
        when appending.  Secrets detected in ``content`` are redacted before
        writing.  Use ``write_memory_store_tool`` to write to a semantic
        store path instead.

        Args:
            cwd:     Absolute path to the project root.
            section: Target section name without `.md` (e.g. ``"decisions"``).
            content: Markdown content to write.
            mode:    ``"append"`` (default) adds content after existing text;
                     ``"replace"`` overwrites the section body entirely.
        """
        safe = _safe_cwd(cwd)
        return write_local_memory(safe, section=section, content=content, mode=mode)  # type: ignore[arg-type]

    @mcp.tool()
    def propose_memory_patch_tool(cwd: str, instructions: str) -> PatchPreview:
        """Preview a proposed memory update as a unified diff without writing to disk.

        Parses ``instructions`` to determine the target section or store path,
        applies the change in-memory, and returns a diff so it can be reviewed
        before committing.  The instructions string should begin with exactly
        one of the following mutually exclusive directive lines::

            section: <section_name>   # targets a flat .ai-memory/ section
            store: <store/path>       # targets a memory-store/ semantic path

        Followed by the proposed content.  If no directive is found the content
        is treated as an append to ``index.md``.

        Args:
            cwd:          Absolute path to the project root.
            instructions: Directive + content describing the proposed change.
        """
        safe = _safe_cwd(cwd)
        return propose_memory_patch(safe, instructions=instructions)

    @mcp.tool()
    async def dream_tool(
        cwd: str,
        mode: str = "light",
        apply: bool = False,
        llm_rewrite: bool = False,
        max_rewrite_tasks: int = 5,
        with_eval: bool = False,
        save_report: bool = False,
        llm_review: bool = False,
        context: Context | None = None,
    ) -> DreamResult:
        """Run the Dreaming consolidation pass over memory files.

        ⚠️  Do NOT use this tool as a substitute for saving new knowledge.
        Call ``write_memory_store_tool`` first to persist specific, isolated
        memories from the current session (e.g. bugs fixed, features built,
        architecture decisions).  Dreaming consolidates EXISTING memory — it
        does not capture new knowledge.

        Dreaming deduplicates, summarises, and optionally rewrites memory
        content in a candidate store, then applies the changes to live memory
        when ``apply=True``.  A snapshot is always created before any writes.

        Use ``prepare_dream_payload_tool`` + ``apply_dream_results_tool``
        instead if the MCP client's LLM should perform the consolidation step
        (split-tool protocol to avoid JSON-RPC deadlocks).

        Args:
            cwd:               Absolute path to the project root.
            mode:              ``"light"`` regenerates the index and summaries
                               only; ``"deep"`` performs full deduplication and
                               consolidation.
            apply:             Persist changes to live memory when ``True``.
                               Dry-run (candidate-only) when ``False``.
            llm_rewrite:       Ask the LLM to rewrite low-quality sections when
                               ``True`` (requires an LLM to be configured).
            max_rewrite_tasks: Maximum number of sections to rewrite per run.
            with_eval:         Run a quality evaluation after applying changes
                               (requires ``apply=True``).
            save_report:       Persist the evaluation report to disk.
            llm_review:        Include LLM commentary in the evaluation report.
        """
        safe = _safe_cwd(cwd)
        result = await dream(
            safe,
            mode=mode,
            apply=apply,
            llm_rewrite=llm_rewrite,
            max_rewrite_tasks=max_rewrite_tasks,
            context=context,
        )
        if with_eval and apply and result["snapshot"]:
            # NOTE: save_report and llm_review are now correctly forwarded (bug fix).
            result["evaluation"] = await evaluate_dream_quality(
                safe,
                snapshot=result["snapshot"],
                save_report=save_report,
                llm_review=llm_review,
                context=context,
            )
        elif with_eval and not apply:
            result["warnings"].append(
                "Dream evaluation requires apply=true because candidate mode does not mutate live memory."
            )
        return result

    @mcp.tool()
    def prepare_dream_payload_tool(cwd: str, mode: str = "light") -> dict[str, Any]:
        """Prepare prompt and payload for client-agent to perform consolidation."""
        safe = _safe_cwd(cwd)
        return prepare_dream_payload(safe, mode=mode)

    @mcp.tool()
    async def apply_dream_results_tool(
        cwd: str,
        candidate_store: str,
        llm_response: str,
        mode: str = "light",
        apply: bool = True,
        llm_rewrite: bool = False,
        max_rewrite_tasks: int = 5,
        context: Context | None = None,
    ) -> DreamResult:
        """Apply consolidation results generated by the client-agent's LLM run."""
        safe = _safe_cwd(cwd)
        return await apply_dream_results(
            safe,
            candidate_store=candidate_store,
            llm_response=llm_response,
            mode=mode,
            apply=apply,
            llm_rewrite=llm_rewrite,
            max_rewrite_tasks=max_rewrite_tasks,
            context=context,
        )

    @mcp.tool()
    async def evaluate_memory_fabric_tool(
        cwd: str,
        save_report: bool = False,
        llm_review: bool = False,
        context: Context | None = None,
    ) -> EvalResult:
        """Evaluate the overall quality of the Memory Fabric for this project.

        Scores multiple quality dimensions — section coverage, metadata
        completeness, retrieval readiness, and safety — and returns a
        structured ``EvalResult`` with per-category breakdowns, a composite
        score (0-100), and actionable recommendations.

        Args:
            cwd:         Absolute path to the project root.
            save_report: Persist the evaluation report as a Markdown file
                         inside `.ai-memory/` when ``True``.
            llm_review:  Append LLM-generated commentary to the report when
                         ``True`` (requires an LLM to be configured).
        """
        safe = _safe_cwd(cwd)
        return await evaluate_memory_fabric(
            safe, save_report=save_report, llm_review=llm_review, context=context
        )

    @mcp.tool()
    async def evaluate_dream_quality_tool(
        cwd: str,
        snapshot: str,
        save_report: bool = False,
        llm_review: bool = False,
        context: Context | None = None,
    ) -> DreamEvalResult:
        """Score the quality improvement produced by a Dream run.

        Compares memory state captured in ``snapshot`` against the current live
        memory to measure how much the Dreaming pass improved (or regressed)
        overall quality.  Returns a ``DreamEvalResult`` with score delta,
        per-category comparisons, and detected regressions.

        Args:
            cwd:         Absolute path to the project root.
            snapshot:    Snapshot name or ``"latest"`` as returned by
                         ``dream_tool`` or ``prepare_dream_payload_tool``.
            save_report: Persist the evaluation report to disk when ``True``.
            llm_review:  Include LLM commentary in the report when ``True``
                         (requires an LLM to be configured).
        """
        safe = _safe_cwd(cwd)
        return await evaluate_dream_quality(
            safe, snapshot=snapshot, save_report=save_report, llm_review=llm_review, context=context
        )

    @mcp.tool()
    def write_memory_store_tool(
        cwd: str,
        store_path: str,
        content: str,
        title: str = "",
        tags: str = "",
        priority: str = "medium",
        mode: str = "replace",
    ) -> StoreWriteResult:
        """Write a memory file to a semantic store path (e.g. 'architecture/decisions/auth-service')."""
        safe = _safe_cwd(cwd)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        return write_memory_store(
            safe,
            store_path=store_path,
            content=content,
            title=title,
            tags=tag_list,
            priority=priority,
            mode=mode,  # type: ignore[arg-type]
        )

    @mcp.tool()
    def read_memory_store_tool(
        cwd: str,
        store_path: str,
        max_tokens: int = 8000,
    ) -> StoreReadResult:
        """Read a single memory-store file by its semantic path."""
        safe = _safe_cwd(cwd)
        return read_memory_store(safe, store_path=store_path, max_tokens=max_tokens)

    @mcp.tool()
    def list_memory_store_tool(
        cwd: str,
        prefix: str = "",
        tags: str = "",
        max_results: int = 50,
    ) -> StoreListResult:
        """List files in the memory store, optionally filtered by prefix and/or tags."""
        safe = _safe_cwd(cwd)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        return list_memory_store(safe, prefix=prefix, tags=tag_list, max_results=max_results)

    @mcp.tool()
    def delete_memory_store_tool(
        cwd: str,
        store_path: str,
    ) -> WriteResult:
        """Remove a memory-store file by its semantic path."""
        safe = _safe_cwd(cwd)
        return delete_memory_store(safe, store_path=store_path)

    @mcp.tool()
    def write_session_journal_tool(
        cwd: str,
        summary: str,
        key_decisions: list[str] | None = None,
        files_changed: list[str] | None = None,
        session_label: str | None = None,
    ) -> EpisodicJournalResult:
        """Append a timestamped session journal to the episodic memory store.

        Creates or appends to an `episodic/YYYY-MM-DD` store entry that records
        what was accomplished this session. Multiple calls on the same day accumulate
        into a single dated journal file. Dreaming consolidates old entries (>7 days)
        into monthly summaries.

        Args:
            summary:        2-4 sentence description of what was done this session.
            key_decisions:  Optional list of architecture decisions or choices made.
            files_changed:  Optional list of files created or significantly modified.
            session_label:  Optional short label (e.g. 'auth-refactor'). Defaults to HH:MM UTC.
        """
        safe = _safe_cwd(cwd)
        return write_session_journal(
            safe,
            summary=summary,
            key_decisions=key_decisions,
            files_changed=files_changed,
            session_label=session_label,
        )

    # ------------------------------------------------------------------
    # MCP Resources — auto-fetched by supporting clients (e.g. Claude
    # Desktop) at session start without any agent tool call.
    # URI template: the client encodes the absolute project path with
    # urllib.parse.quote(cwd, safe="") and builds the URI.
    # ------------------------------------------------------------------

    @mcp.resource(
        "memory-fabric://context/{encoded_cwd}",
        name="memory-fabric-context",
        title="Memory Fabric — Project Context",
        description=(
            "Full assembled project memory context (same as read_combined_context_tool). "
            "Auto-fetched by MCP clients that support Resources at session start."
        ),
        mime_type="text/plain",
    )
    def memory_context_resource(encoded_cwd: str) -> str:
        """Return the full assembled memory context for the given project.

        The ``encoded_cwd`` path segment must be the project root encoded with
        ``urllib.parse.quote(cwd, safe="")``.  MCP clients that auto-fetch
        resources will call this before the first agent message, giving agents
        memory context without requiring any explicit tool invocation.

        If ``.ai-memory/`` has not been initialized, returns an advisory message
        instead of raising an error so that clients do not show error dialogs.
        """
        cwd = urllib.parse.unquote(encoded_cwd)
        try:
            safe = _safe_cwd(cwd)
        except ValueError as exc:
            return f"# Memory Fabric\n\nInvalid project path: {exc}"
        memory_dir = local_memory_dir(safe)
        if not memory_dir.exists():
            return (
                f"# Memory Fabric\n\n"
                f"No memory initialized at: `{safe}`\n\n"
                f"Run `ai-memory init` or call `initialize_memory_fabric_tool` to get started."
            )
        bundle = read_combined_context(safe)
        return bundle["text"]

    @mcp.resource(
        "memory-fabric://index/{encoded_cwd}",
        name="memory-fabric-index",
        title="Memory Fabric — Memory Index",
        description=(
            "Lightweight section index (index.md only). Use this for discovery — "
            "to know what memory sections exist before doing targeted reads."
        ),
        mime_type="text/plain",
    )
    def memory_index_resource(encoded_cwd: str) -> str:
        """Return the memory index file for the given project.

        Returns only ``index.md`` — a small section map that lets agents and
        users quickly see what memory categories exist without paying the token
        cost of loading the full context bundle.
        """
        cwd = urllib.parse.unquote(encoded_cwd)
        try:
            safe = _safe_cwd(cwd)
        except ValueError as exc:
            return f"# Memory Fabric Index\n\nInvalid project path: {exc}"
        memory_dir = local_memory_dir(safe)
        index_path = memory_dir / "index.md"
        if not index_path.exists():
            return (
                f"# Memory Fabric Index\n\n"
                f"No index found at: `{safe}`\n\n"
                f"Run `ai-memory init` or call `initialize_memory_fabric_tool` to create it."
            )
        return index_path.read_text(encoding="utf-8")

else:
    mcp = None


def main(argv: list[str] | None = None) -> int:
    if mcp is None:
        raise SystemExit(
            "The optional `mcp` package is not installed. Install with: pipx inject memory-fabric mcp"
        )

    import argparse

    parser = argparse.ArgumentParser(
        prog="memory-fabric-mcp", description="Memory Fabric MCP Server"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host address for SSE transport (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port for SSE transport (default: 8000)"
    )
    parser.add_argument(
        "--allow-all-origins",
        action="store_true",
        help="Allow all origins and disable DNS rebinding protection (useful for Open WebUI)",
    )

    args = parser.parse_args(argv)

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        if args.allow_all_origins:
            if mcp.settings.transport_security is None:
                mcp.settings.transport_security = TransportSecuritySettings()
            mcp.settings.transport_security.enable_dns_rebinding_protection = False
            mcp.settings.transport_security.allowed_hosts = ["*"]
            mcp.settings.transport_security.allowed_origins = ["*"]
        print(f"Starting Memory Fabric MCP server on sse://{args.host}:{args.port}")
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
