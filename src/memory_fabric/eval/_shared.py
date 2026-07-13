"""Scoring primitives, constants, and section-loading helpers shared by
memory-quality and dream-quality evaluation.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from memory_fabric.contracts import EvalCategory, EvalCheck, EvalResult
from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.security import redact_secrets

REQUIRED_SECTIONS = [
    "architecture",
    "schemas",
    "decisions",
    "debt",
    "ubiquitous-language",
    "framework-rules",
]

MEMORY_WEIGHTS = {
    "coding_usefulness": 30,
    "section_coverage": 20,
    "retrieval_readiness": 20,
    "metadata_quality": 15,
    "safety_privacy": 15,
}

DREAM_WEIGHTS = {
    "score_delta": 35,
    "regression_safety": 25,
    "index_summary": 20,
    "retrieval_readiness": 10,
    "change_safety": 10,
}

SECRETS_MARKER = "[REDACTED_SECRET]"


def _category(name: str, weight: int, checks: list[EvalCheck]) -> EvalCategory:
    score = 100 if not checks else round(sum(_check_score(check) for check in checks) / len(checks))
    return {
        "name": name,
        "score": score,
        "status": _score_status(score),
        "weight": weight,
        "checks": checks,
    }


def _memory_result(
    *,
    generated_at: str,
    cwd: Path,
    memory_dir: Path,
    categories: list[EvalCategory],
    report_paths: list[str],
    warnings: list[str],
    llm_notes: list[str],
) -> EvalResult:
    score = _weighted_score(categories, MEMORY_WEIGHTS)
    return {
        "kind": "memory",
        "generated_at": generated_at,
        "cwd": str(cwd),
        "memory_dir": str(memory_dir),
        "score": score,
        "status": _score_status(score),
        "categories": categories,
        "recommendations": _recommendations_from_categories(categories),
        "report_paths": report_paths,
        "warnings": warnings,
        "llm_notes": llm_notes,
    }


def _weighted_score(categories: list[EvalCategory], weights: dict[str, int]) -> int:
    total_weight = 0
    total = 0
    for category in categories:
        weight = weights.get(category["name"], category.get("weight", 1))
        total_weight += weight
        total += category["score"] * weight
    if total_weight == 0:
        return 0
    return max(0, min(100, round(total / total_weight)))


def _score_status(score: int) -> Literal["pass", "warn", "fail"]:
    if score >= 85:
        return "pass"
    if score >= 60:
        return "warn"
    return "fail"


def _check(
    check_id: str,
    status: str,
    severity: str,
    message: str,
    recommendation: str,
    command: str | None = None,
) -> EvalCheck:
    result: EvalCheck = {
        "id": check_id,
        "status": status,  # type: ignore[typeddict-item]
        "severity": severity,  # type: ignore[typeddict-item]
        "message": message,
        "recommendation": recommendation,
    }
    if command:
        result["command"] = command
    return result


def _check_score(check: EvalCheck) -> int:
    if check["status"] == "pass":
        return 100
    if check["status"] == "warn":
        return 65 if check["severity"] in {"low", "info"} else 50
    return 0 if check["severity"] == "high" else 25


def _recommendations_from_categories(categories: list[EvalCategory]) -> list[str]:
    recommendations: list[str] = []
    seen: set[str] = set()
    for category in categories:
        for check in category["checks"]:
            if check["status"] == "pass":
                continue
            recommendation = check["recommendation"]
            if recommendation not in seen:
                recommendations.append(recommendation)
                seen.add(recommendation)
    return recommendations[:12]


def _load_sections(memory_dir: Path) -> dict[str, dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    if not memory_dir.exists():
        return sections
    for path in sorted(memory_dir.rglob("*.md")):
        if _is_ignored_memory_path(memory_dir, path):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(raw)
            section = str(metadata.get("section") or path.stem)
            sections[section] = {
                "path": path,
                "raw": raw,
                "metadata": metadata,
                "body": body,
                "error": None,
            }
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            sections[path.stem] = {
                "path": path,
                "raw": "",
                "metadata": {},
                "body": "",
                "error": str(exc),
            }
    return sections


def _is_ignored_memory_path(memory_dir: Path, path: Path) -> bool:
    try:
        relative_parts = path.relative_to(memory_dir).parts
    except ValueError:
        return False
    return bool({"private", "snapshots", "evals", "candidates"}.intersection(relative_parts))


def _section_load_warnings(sections: dict[str, dict[str, Any]]) -> list[str]:
    return [f"{info['path']}: {info['error']}" for info in sections.values() if info.get("error")]


def _is_placeholder_body(section: str, body: str, template_body: str) -> bool:
    normalized = _normalize_text(body)
    if not normalized:
        return True
    if template_body and normalized == _normalize_text(template_body):
        return True
    starter_phrases = [
        "record durable",
        "record important",
        "record known",
        "record project",
        "record framework",
        "this file summarizes",
    ]
    return any(phrase in normalized for phrase in starter_phrases) and len(normalized) < 180


def _bad_summary(summary: str, section: str) -> bool:
    if len(summary) < 24:
        return True
    normalized = summary.lower()
    weak = ["one-line", "project memory section", "record ", "todo", "tbd"]
    return any(item in normalized for item in weak) or normalized == section.replace("-", " ")


def _duplicate_summaries(sections: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    summaries: dict[str, list[str]] = {}
    for section, info in sections.items():
        if info.get("error"):
            continue
        summary = _normalize_text(str(info["metadata"].get("summary", "")))
        if summary:
            summaries.setdefault(summary, []).append(section)
    return {summary: names for summary, names in summaries.items() if len(names) > 1}


def _is_timezone_aware(value: str) -> bool:
    if not value:
        return False
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) is not None


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


async def _llm_notes(llm_review: bool, report_text: str, context: Any = None) -> list[str]:
    if not llm_review:
        return []
    sanitized, redactions = redact_secrets(report_text)
    notes = []
    if redactions:
        notes.append(f"Sanitized {redactions} possible secret(s) before optional LLM review.")

    provider = os.environ.get("MEMORY_FABRIC_LLM_PROVIDER")
    sampling_available = False
    if context is not None:
        client_params = getattr(context.session, "client_params", None)
        if (
            client_params is not None
            and getattr(client_params, "capabilities", None) is not None
            and getattr(client_params.capabilities, "sampling", None) is not None
        ):
            sampling_available = True

    if not provider and not sampling_available:
        notes.append(
            "LLM review requested, but neither MEMORY_FABRIC_LLM_PROVIDER nor MCP Sampling is available."
        )
        return notes

    if not sanitized.strip():
        return notes

    try:
        from memory_fabric.llm import call_llm

        prompt = (
            "Review the following quality evaluation report for a software development memory system.\n"
            "Identify areas of improvement, structural weaknesses, or documentation gaps in the memory.\n"
            "Generate between 2 and 4 highly actionable, concise, qualitative recommendations to improve the memory.\n"
            "Each recommendation must be a single sentence, starting with a bullet and without markdown formatting other than inline code symbols.\n\n"
            f"Evaluation Report:\n{sanitized}"
        )
        system_instruction = "You are a senior software architect specializing in technical documentation, repository design, and AI context optimization."
        response = await call_llm(prompt, system_instruction, context)

        import re

        for line in response.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip bullet/list prefix if any
            if line.startswith("-") or line.startswith("*") or line.startswith("•"):
                line = line[1:].strip()
            line = re.sub(r"^\d+\.\s*", "", line)

            if line:
                notes.append(line)
    except Exception as exc:  # noqa: BLE001 - LLM review is best-effort; failure is reported, not swallowed.
        notes.append(f"Failed to generate qualitative LLM review: {exc}")
    return notes
