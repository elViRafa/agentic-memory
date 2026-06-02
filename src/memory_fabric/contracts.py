"""Typed result contracts for Memory Fabric public APIs."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


Priority = Literal["high", "medium", "low"]
WriteMode = Literal["append", "replace"]
DreamMode = Literal["light", "deep"]


class InitResult(TypedDict):
    created: bool
    memory_dir: str
    files_created: list[str]
    warnings: list[str]


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


class DoctorResult(TypedDict):
    ok: bool
    errors: list[str]
    warnings: list[str]
    checked_files: list[str]


class StatusResult(TypedDict):
    cwd: str
    memory_dir: str
    memory_exists: bool
    global_dir: str
    provider_configured: bool
    local_files: list[str]
    memory_sizes: dict[str, dict[str, int]]


class DreamResult(TypedDict):
    changed: bool
    snapshot: str | None
    warnings: list[str]
    checked_files: list[str]
    candidate_store: str
    patch_preview: str
    affected_files: list[str]
    consolidation: "DreamConsolidation"
    rewrite_tasks: list["DreamRewriteTask"]
    apply_required: bool
    redactions: int
    evaluation: NotRequired["DreamEvalResult"]


class DreamConsolidation(TypedDict):
    duplicates_found: int
    lines_removed: int
    files_touched: list[str]


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
