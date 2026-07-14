"""Typed result contracts for Memory Fabric public APIs.

NOTE: this module must NOT use `from __future__ import annotations`. PEP 563
stringifies annotations, and the TypedDict metaclass cannot see `NotRequired[...]`
inside a string annotation — every key silently lands in `__required_keys__`,
and pydantic (via the `mcp` extra) then rejects tool results that legitimately
omit optional keys (e.g. `DreamResult` without `evaluation`). Classes are
ordered so no forward references are needed; `tests/test_contracts.py` guards
the required/optional key split.
"""

import sys
from typing import Any, Literal

# pydantic (pulled in by the optional `mcp` extra, to build tool schemas from these
# TypedDicts) rejects typing.TypedDict on Python < 3.12 in favor of typing_extensions'
# version. typing_extensions is only guaranteed present when `mcp` is installed (it's a
# transitive pydantic dependency) — core-only installs on 3.11 fall back to stdlib, which
# is fine there since pydantic never touches these types without the `mcp` extra.
if sys.version_info >= (3, 12):
    from typing import NotRequired, TypedDict
else:
    try:
        from typing import NotRequired

        from typing_extensions import TypedDict
    except ImportError:
        from typing import NotRequired, TypedDict


Priority = Literal["high", "medium", "low"]
WriteMode = Literal["append", "replace"]
DreamMode = Literal["light", "deep"]


class InitResult(TypedDict):
    created: bool
    memory_dir: str
    files_created: list[str]
    warnings: list[str]
    # `| None`: see the FastMCP output-validation note on DreamResult.evaluation
    # below. Currently always populated by initialize_memory_fabric_tool, so
    # dormant rather than live — kept nullable so it stays that way.
    resource_uris: NotRequired[list[str] | None]


class ContextBundle(TypedDict):
    text: str
    included_sections: list[str]
    omitted_sections: list[str]
    token_budget: int
    estimated_tokens: int
    warnings: list[str]


class MemorySection(TypedDict):
    section: str
    path: str
    text: str
    metadata: dict[str, Any]
    truncated: bool
    warnings: list[str]


class SearchResult(TypedDict):
    section: str
    path: str
    line: int
    snippet: str
    backend: NotRequired[str]  # 'ripgrep' | 'python' — which search backend was used


class WriteResult(TypedDict):
    changed: bool
    path: str
    redactions: int
    warnings: list[str]


class PatchPreview(TypedDict):
    patch: str
    affected_files: list[str]
    redactions: int
    warnings: list[str]


class EpisodicJournalResult(TypedDict):
    """Result returned by write_session_journal_tool."""

    changed: bool
    store_path: str
    path: str
    date: str
    redactions: int
    warnings: list[str]


class StoreWriteResult(TypedDict):
    changed: bool
    path: str
    store_path: str
    redactions: int
    warnings: list[str]


class StoreReadResult(TypedDict):
    store_path: str
    path: str
    text: str
    metadata: dict[str, Any]
    truncated: bool
    warnings: list[str]


class StoreEntry(TypedDict):
    store_path: str
    path: str
    summary: str
    priority: str
    tags: list[str]
    last_updated: str


class StoreListResult(TypedDict):
    entries: list[StoreEntry]
    total: int
    warnings: list[str]


class DoctorResult(TypedDict):
    ok: bool
    errors: list[str]
    warnings: list[str]
    checked_files: list[str]


class InstallResult(TypedDict):
    client: str
    scope: Literal["global", "project"]
    method: Literal["json-merge", "toml-append", "cli"]
    ok: bool
    changed: bool
    path: str
    diff: str
    backup_path: str
    command: str
    warnings: list[str]


class InstallAllResult(TypedDict):
    results: list[InstallResult]
    warnings: list[str]


class StatusResult(TypedDict):
    cwd: str
    memory_dir: str
    memory_exists: bool
    global_dir: str
    provider_configured: bool
    local_files: list[str]
    memory_sizes: dict[str, dict[str, int]]
    version: str
    capture: NotRequired[dict[str, Any]]
    snapshots: NotRequired[dict[str, Any]]
    candidates_count: NotRequired[int]


class MapsRegenResult(TypedDict):
    """Result of regenerating root map sections from the memory-store tree."""

    maps_written: list[str]
    legacy_folded: list[str]
    warnings: list[str]


class MigrateEntryPlan(TypedDict):
    """One store entry a migration will create from a legacy section chunk."""

    store_path: str
    title: str
    # Where the chunk came from: the H2 heading text, or "(preamble)".
    source: str
    chars: int
    # "planned" (dry-run) | "written" | "already-migrated" (identical entry
    # found on disk — makes re-runs after a partial failure resumable).
    status: str


class MigrateSectionPlan(TypedDict):
    """Migration plan for one legacy hand-written section."""

    section: str
    category: str
    # True when an LLM proposed the entry names/tags; content is always the
    # verbatim heuristic chunks either way.
    llm_named: bool
    entries: list[MigrateEntryPlan]


class MigrateResult(TypedDict):
    """Result of `ai-memory migrate` (store-first migration, ROADMAP Phase 2.2).

    Deliberately total (no NotRequired): this ships CLI-only, but if it ever
    becomes an MCP tool the FastMCP omitted-optional-becomes-null trap
    (see DreamResult.evaluation) can't apply to an all-required contract.
    """

    changed: bool
    dry_run: bool
    snapshot: str | None
    sections_migrated: list[str]
    entries_written: list[str]
    maps_written: list[str]
    plan: list[MigrateSectionPlan]
    redactions: int
    warnings: list[str]


class DreamConsolidation(TypedDict):
    duplicates_found: int
    lines_removed: int
    files_touched: list[str]
    warnings: NotRequired[list[str]]


class DreamRewriteTask(TypedDict):
    section: str
    reason: str
    instruction: str


class EvalCheck(TypedDict):
    id: str
    status: Literal["pass", "warn", "fail"]
    severity: Literal["info", "low", "medium", "high"]
    message: str
    recommendation: str
    command: NotRequired[str]


class EvalCategory(TypedDict):
    name: str
    score: int
    status: Literal["pass", "warn", "fail"]
    weight: int
    checks: list[EvalCheck]


class EvalResult(TypedDict):
    kind: Literal["memory"]
    generated_at: str
    cwd: str
    memory_dir: str
    score: int
    status: Literal["pass", "warn", "fail"]
    categories: list[EvalCategory]
    recommendations: list[str]
    report_paths: list[str]
    warnings: list[str]
    llm_notes: list[str]


class DreamEvalResult(TypedDict):
    kind: Literal["dream"]
    generated_at: str
    cwd: str
    memory_dir: str
    baseline_snapshot: str
    before_score: int
    after_score: int
    delta: int
    score: int
    status: Literal["pass", "warn", "fail"]
    changed_files: list[str]
    improvements: list[str]
    regressions: list[str]
    categories: list[EvalCategory]
    recommendations: list[str]
    report_paths: list[str]
    warnings: list[str]
    llm_notes: list[str]


class DreamResult(TypedDict):
    changed: bool
    snapshot: str | None
    warnings: list[str]
    checked_files: list[str]
    candidate_store: str
    patch_preview: str
    affected_files: list[str]
    consolidation: DreamConsolidation
    rewrite_tasks: list[DreamRewriteTask]
    apply_required: bool
    redactions: int
    # `| None`, not just NotRequired[DreamEvalResult]: FastMCP converts a
    # tool's top-level return TypedDict into a BaseModel by giving every
    # NotRequired field `default=None` while leaving its original (non-null)
    # annotation in place (`_create_model_from_typeddict`), then dumps the
    # result without `exclude_unset`. An omitted `evaluation` therefore
    # serializes onto the wire as an explicit `null`, which a non-nullable
    # `object` schema rejects — resurfacing P-13 (isError: True on a
    # successful apply) through the real MCP path even though direct
    # TypeAdapter validation (tests/test_contracts.py) looks clean. Found via
    # tests/test_mcp_contract.py, which calls tools through an in-process
    # ClientSession instead of the raw Python function.
    evaluation: NotRequired[DreamEvalResult | None]
