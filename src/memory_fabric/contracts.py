"""Typed result contracts for Memory Fabric public APIs."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


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


class DreamResult(TypedDict):
    changed: bool
    snapshot: str | None
    warnings: list[str]
    checked_files: list[str]
