"""Local quality evaluation for memories and Dreaming runs."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from memory_fabric.contracts import DreamEvalResult, EvalCategory, EvalCheck, EvalResult
from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.paths import local_memory_dir, project_root
from memory_fabric.security import redact_secrets
from memory_fabric.storage import read_combined_context
from memory_fabric.storage._shared import STEERING_SECTIONS
from memory_fabric.storage.maps import category_fingerprint
from memory_fabric.templates import LOCAL_GITIGNORE, SECTION_TEMPLATES, now_iso


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


async def evaluate_memory_fabric(
    cwd: str, save_report: bool = True, llm_review: bool = False, context: Any = None
) -> EvalResult:
    root = project_root(cwd)
    memory_dir = local_memory_dir(root)
    generated_at = now_iso()
    warnings: list[str] = []
    report_paths: list[str] = []

    if not memory_dir.exists():
        categories = [
            _category(
                "project_setup",
                MEMORY_WEIGHTS["section_coverage"],
                [
                    _check(
                        "memory_dir_missing",
                        "fail",
                        "high",
                        f"Local memory directory does not exist: {memory_dir}",
                        "Run ai-memory init before evaluating memory quality.",
                        "ai-memory init",
                    )
                ],
            )
        ]
        result = _memory_result(
            generated_at=generated_at,
            cwd=root,
            memory_dir=memory_dir,
            categories=categories,
            report_paths=[],
            warnings=["Pre-init eval only; no files were created."],
            llm_notes=await _llm_notes(llm_review, "", context),
        )
        return result

    sections = _load_sections(memory_dir)
    categories = [
        evaluate_memory_quality(cwd, root=memory_dir),
        _evaluate_section_coverage(memory_dir, sections),
        _evaluate_retrieval_readiness(cwd),
        _evaluate_metadata_quality(sections),
        _evaluate_safety_privacy(memory_dir, sections),
    ]
    warnings.extend(_section_load_warnings(sections))

    result = _memory_result(
        generated_at=generated_at,
        cwd=root,
        memory_dir=memory_dir,
        categories=categories,
        report_paths=[],
        warnings=warnings,
        llm_notes=[],
    )
    result["recommendations"] = _recommendations_from_categories(categories)
    result["llm_notes"] = await _llm_notes(llm_review, _report_markdown(result), context)

    if save_report:
        report_paths = _save_memory_report(memory_dir, result)
        result["report_paths"] = report_paths

    return result


def evaluate_memory_quality(cwd: str, root: Path | None = None) -> EvalCategory:
    memory_dir = root or local_memory_dir(cwd)
    sections = _load_sections(memory_dir)
    checks: list[EvalCheck] = []

    for required in REQUIRED_SECTIONS:
        info = sections.get(required)
        if info is None:
            continue
        if info.get("error"):
            checks.append(
                _check(
                    f"{required}_unreadable",
                    "fail",
                    "high",
                    f"{required}.md cannot be evaluated: {info['error']}",
                    "Fix the file so it is valid UTF-8 Markdown with frontmatter.",
                )
            )
            continue

        body = str(info["body"]).strip()
        metadata = info["metadata"]
        if metadata.get("generated"):
            # Generated maps are views: their content quality follows the store,
            # and freshness is scored by the section_coverage category instead.
            checks.append(
                _check(
                    f"{required}_generated",
                    "pass",
                    "info",
                    f"{required}.md is a generated map over memory-store/{required}/.",
                    "Write facts with write_memory_store_tool and run Dreaming to refresh it.",
                )
            )
            continue
        template_body = str(SECTION_TEMPLATES.get(required, {}).get("body", "")).strip()
        if _is_placeholder_body(required, body, template_body):
            checks.append(
                _check(
                    f"{required}_placeholder",
                    "warn",
                    "medium",
                    f"{required}.md still looks like starter template content.",
                    f"Add project-specific facts to {required}.md.",
                )
            )
        elif len(body) < 120 and required in {"architecture", "schemas", "decisions"}:
            checks.append(
                _check(
                    f"{required}_thin",
                    "warn",
                    "medium",
                    f"{required}.md is short for a high-value coding memory section.",
                    f"Add concrete implementation details, constraints, and examples to {required}.md.",
                )
            )
        else:
            checks.append(
                _check(
                    f"{required}_useful",
                    "pass",
                    "info",
                    f"{required}.md contains project-specific memory.",
                    "Keep this section current as the project changes.",
                )
            )

        summary = str(metadata.get("summary", "")).strip()
        if _bad_summary(summary, required):
            checks.append(
                _check(
                    f"{required}_summary_weak",
                    "warn",
                    "medium",
                    f"{required}.md has a weak summary for token-limited retrieval.",
                    "Write a specific one-line summary that helps an assistant decide when to load this section.",
                )
            )

    duplicate_summaries = _duplicate_summaries(sections)
    for summary, section_names in duplicate_summaries.items():
        checks.append(
            _check(
                "duplicate_summary_" + section_names[0],
                "warn",
                "low",
                f"Sections share the same summary: {', '.join(section_names)}.",
                f"Make each summary specific. Repeated summary: {summary}",
            )
        )

    if not checks:
        checks.append(
            _check(
                "no_memory_to_score",
                "fail",
                "high",
                "No readable memory sections were available for quality evaluation.",
                "Run ai-memory init and add project-specific memory.",
            )
        )

    return _category("coding_usefulness", MEMORY_WEIGHTS["coding_usefulness"], checks)


async def evaluate_dream_quality(
    cwd: str,
    snapshot: str,
    save_report: bool = True,
    llm_review: bool = False,
    context: Any = None,
) -> DreamEvalResult:
    root = project_root(cwd)
    memory_dir = local_memory_dir(root)
    snapshot_name = _resolve_snapshot(memory_dir, snapshot)
    snapshot_dir = memory_dir / "snapshots" / snapshot_name
    if not snapshot_dir.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot}")

    before_category = evaluate_memory_quality(cwd, root=snapshot_dir)
    after_eval = await evaluate_memory_fabric(
        cwd, save_report=False, llm_review=False, context=context
    )
    before_eval = _memory_eval_for_root(cwd, snapshot_dir)

    changed_files = _changed_files(snapshot_dir, memory_dir)
    improvements: list[str] = []
    regressions: list[str] = []

    before_score = before_eval["score"]
    after_score = after_eval["score"]
    delta = after_score - before_score
    if delta > 0:
        improvements.append(f"Memory quality score improved by {delta} points.")
    elif delta < 0:
        regressions.append(f"Memory quality score decreased by {abs(delta)} points.")
    else:
        improvements.append("Memory quality score stayed stable.")

    if "index.md" in changed_files:
        improvements.append("Dreaming updated the project memory index.")
    else:
        regressions.append("Dreaming did not update index.md.")

    before_sections = _load_sections(snapshot_dir)
    after_sections = _load_sections(memory_dir)
    lost_sections = sorted(set(before_sections) - set(after_sections))
    if lost_sections:
        regressions.append("Dreaming removed memory sections: " + ", ".join(lost_sections))

    new_secret_files = _files_with_new_secret_markers(before_sections, after_sections)
    if new_secret_files:
        regressions.append(
            "Dreaming introduced redacted secret markers in: " + ", ".join(new_secret_files)
        )

    churn_ratio = _churn_ratio(snapshot_dir, memory_dir)
    if churn_ratio > 0.75 and len(changed_files) > 2:
        regressions.append(
            "Dreaming changed a large portion of memory; review for excessive churn."
        )
    else:
        improvements.append("Dreaming made a bounded set of memory changes.")

    score_delta_cat = _dream_score_delta_category(delta)
    regression_safety_cat = _dream_regression_category(regressions)
    index_summary_cat = _dream_index_summary_category(changed_files, before_category, after_eval)
    change_safety_cat = _dream_change_safety_category(changed_files, new_secret_files, churn_ratio)

    categories = [
        score_delta_cat,
        regression_safety_cat,
        index_summary_cat,
        change_safety_cat,
    ]
    score = _weighted_score(categories, DREAM_WEIGHTS)
    status = _score_status(score)

    result: DreamEvalResult = {
        "kind": "dream",
        "generated_at": now_iso(),
        "cwd": str(root),
        "memory_dir": str(memory_dir),
        "baseline_snapshot": snapshot_name,
        "before_score": before_score,
        "after_score": after_score,
        "delta": delta,
        "score": score,
        "status": status,
        "changed_files": changed_files,
        "improvements": improvements,
        "regressions": regressions,
        "categories": categories,
        "recommendations": _recommendations_from_categories(categories),
        "report_paths": [],
        "warnings": [],
        "llm_notes": [],
    }
    result["llm_notes"] = await _llm_notes(llm_review, _dream_report_markdown(result), context)

    if save_report:
        result["report_paths"] = _save_dream_report(memory_dir, result)

    return result


def latest_snapshot(cwd: str) -> str | None:
    snapshots_dir = local_memory_dir(cwd) / "snapshots"
    if not snapshots_dir.exists():
        return None
    snapshots = [path for path in snapshots_dir.iterdir() if path.is_dir()]
    if not snapshots:
        return None
    return max(snapshots, key=lambda path: path.stat().st_mtime).name


def _memory_eval_for_root(cwd: str, root: Path) -> EvalResult:
    categories = [
        evaluate_memory_quality(cwd, root=root),
        _evaluate_section_coverage(root, _load_sections(root)),
        _category(
            "retrieval_readiness",
            MEMORY_WEIGHTS["retrieval_readiness"],
            [
                _check(
                    "snapshot_retrieval_skipped",
                    "warn",
                    "low",
                    "Snapshot retrieval is scored indirectly because snapshots are not active memory roots.",
                    "Use active memory retrieval checks after restoring a snapshot if needed.",
                )
            ],
        ),
        _evaluate_metadata_quality(_load_sections(root)),
        _evaluate_safety_privacy(root, _load_sections(root)),
    ]
    return _memory_result(
        generated_at=now_iso(),
        cwd=project_root(cwd),
        memory_dir=root,
        categories=categories,
        report_paths=[],
        warnings=[],
        llm_notes=[],
    )


def _evaluate_section_coverage(
    memory_dir: Path, sections: dict[str, dict[str, Any]]
) -> EvalCategory:
    """Store-first coverage: granular memories exist, root maps are generated and fresh.

    Replaces the legacy flat-file presence scoring: `memory-store/` is the source
    of truth, root maps are generated views over it, and a stale generated map is
    a failing check (the fingerprint no longer matches the store category).
    """
    checks: list[EvalCheck] = []
    store_root = memory_dir / "memory-store"
    store_entries = (
        [p for p in store_root.rglob("*.md") if p.is_file() and p.name != "index.md"]
        if store_root.exists()
        else []
    )

    if not store_entries:
        checks.append(
            _check(
                "memory_store_empty",
                "fail",
                "high",
                "memory-store/ holds no granular memories.",
                "Write facts with write_memory_store_tool — the store is the "
                "source of truth in the store-first model.",
            )
        )
    else:
        checks.append(
            _check(
                "memory_store_present",
                "pass",
                "info",
                f"memory-store/ holds {len(store_entries)} granular memories.",
                "Keep writing one fact per file with write_memory_store_tool.",
            )
        )
        loose = [p for p in store_entries if p.parent == store_root]
        if loose:
            checks.append(
                _check(
                    "store_uncategorized",
                    "warn",
                    "low",
                    f"{len(loose)} store file(s) sit at the store root instead of a category subdirectory.",
                    "Use categorized store paths like `architecture/<topic>` so maps can be generated per category.",
                )
            )

        categories = sorted(
            {
                p.relative_to(store_root).parts[0]
                for p in store_entries
                if len(p.relative_to(store_root).parts) > 1
            }
        )
        for category in categories:
            if category in STEERING_SECTIONS:
                continue
            map_path = memory_dir / f"{category}.md"
            if not map_path.exists():
                checks.append(
                    _check(
                        f"{category}_map_missing",
                        "warn",
                        "medium",
                        f"No generated map for memory-store/{category}/.",
                        "Run Dreaming to generate root maps from the store.",
                        "ai-memory dream --apply",
                    )
                )
                continue
            try:
                metadata, _body = parse_frontmatter(map_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
                checks.append(
                    _check(
                        f"{category}_map_unreadable",
                        "fail",
                        "high",
                        f"{category}.md cannot be parsed: {exc}",
                        "Fix the file so it is valid UTF-8 Markdown with frontmatter.",
                    )
                )
                continue
            if not metadata.get("generated"):
                checks.append(
                    _check(
                        f"{category}_map_handwritten",
                        "warn",
                        "medium",
                        f"{category}.md is a legacy hand-written map; the store-first model expects generated maps.",
                        "Run Dreaming: hand-written content is folded into the store for review and the map is regenerated.",
                        "ai-memory dream --apply",
                    )
                )
                continue
            if str(metadata.get("store_fingerprint") or "") != category_fingerprint(
                store_root, category
            ):
                checks.append(
                    _check(
                        f"{category}_map_stale",
                        "fail",
                        "medium",
                        f"Generated map {category}.md is stale: memory-store/{category}/ changed after it was generated.",
                        "Run Dreaming to regenerate the map from the store.",
                        "ai-memory dream --apply",
                    )
                )
            else:
                checks.append(
                    _check(
                        f"{category}_map_fresh",
                        "pass",
                        "info",
                        f"{category}.md is a fresh generated view of memory-store/{category}/.",
                        "Nothing to do.",
                    )
                )

    for steering in sorted(STEERING_SECTIONS):
        if (memory_dir / f"{steering}.md").exists():
            checks.append(
                _check(
                    f"{steering}_present",
                    "pass",
                    "info",
                    f"Steering section {steering}.md exists (always loaded into context).",
                    "Keep it short and universally applicable.",
                )
            )
        else:
            checks.append(
                _check(
                    f"{steering}_missing",
                    "warn",
                    "low",
                    f"Steering section {steering}.md is missing.",
                    "Create it with ai-memory init, or with write_local_memory_tool "
                    f"if the project needs {steering} directives.",
                )
            )
    return _category("section_coverage", MEMORY_WEIGHTS["section_coverage"], checks)


def _evaluate_retrieval_readiness(cwd: str) -> EvalCategory:
    checks: list[EvalCheck] = []
    try:
        default_context = read_combined_context(cwd, max_tokens=4000)
        checks.append(
            _check(
                "default_context_readable",
                "pass",
                "info",
                "Combined context can be read with the default token budget.",
                "Use read_combined_context from MCP clients for normal sessions.",
            )
        )
        if default_context["estimated_tokens"] <= default_context["token_budget"] + 100:
            checks.append(
                _check(
                    "default_context_budget",
                    "pass",
                    "info",
                    "Combined context fits the default token budget estimate.",
                    "Keep high-priority memories concise.",
                )
            )
        else:
            checks.append(
                _check(
                    "default_context_budget",
                    "warn",
                    "medium",
                    "Combined context is above the default token budget estimate.",
                    "Shorten low-value sections or improve summaries.",
                )
            )
    except Exception as exc:  # noqa: BLE001 - report operational retrieval failures.
        checks.append(
            _check(
                "default_context_failed",
                "fail",
                "high",
                f"Combined context read failed: {exc}",
                "Run ai-memory doctor and fix unreadable memory files.",
            )
        )

    try:
        small_context = read_combined_context(cwd, max_tokens=80)
        if (
            small_context["omitted_sections"]
            and "omitted because it exceeded" in small_context["text"]
        ):
            checks.append(
                _check(
                    "small_budget_summaries",
                    "pass",
                    "info",
                    "Low-budget retrieval uses summaries instead of partial Markdown.",
                    "Keep summaries specific so fallback retrieval remains useful.",
                )
            )
        else:
            checks.append(
                _check(
                    "small_budget_summaries",
                    "warn",
                    "low",
                    "Low-budget retrieval did not exercise summary fallback.",
                    "This is acceptable for tiny memories; add content and re-run eval later.",
                )
            )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _check(
                "small_context_failed",
                "fail",
                "medium",
                f"Low-budget retrieval failed: {exc}",
                "Fix retrieval errors before relying on token-budgeted context.",
            )
        )

    return _category("retrieval_readiness", MEMORY_WEIGHTS["retrieval_readiness"], checks)


def _evaluate_metadata_quality(sections: dict[str, dict[str, Any]]) -> EvalCategory:
    checks: list[EvalCheck] = []
    for section, info in sections.items():
        if info.get("error"):
            checks.append(
                _check(
                    f"{section}_frontmatter_invalid",
                    "fail",
                    "high",
                    f"{section}.md has invalid frontmatter: {info['error']}",
                    "Restore valid YAML frontmatter with required fields.",
                )
            )
            continue
        metadata = info["metadata"]
        for field in ["section", "summary", "priority", "tags", "schema_version", "last_updated"]:
            if field not in metadata:
                checks.append(
                    _check(
                        f"{section}_{field}_missing",
                        "fail",
                        "high",
                        f"{section}.md is missing `{field}`.",
                        f"Add `{field}` to the frontmatter.",
                    )
                )
        if metadata.get("priority") not in {"high", "medium", "low"}:
            checks.append(
                _check(
                    f"{section}_priority_invalid",
                    "fail",
                    "medium",
                    f"{section}.md has invalid priority `{metadata.get('priority')}`.",
                    "Use priority high, medium, or low.",
                )
            )
        if not isinstance(metadata.get("tags"), list) or not metadata.get("tags"):
            checks.append(
                _check(
                    f"{section}_tags_weak",
                    "warn",
                    "medium",
                    f"{section}.md has missing or empty tags.",
                    "Add concise searchable tags.",
                )
            )
        if not _is_timezone_aware(str(metadata.get("last_updated", ""))):
            checks.append(
                _check(
                    f"{section}_timestamp_naive",
                    "warn",
                    "medium",
                    f"{section}.md last_updated is not timezone-aware.",
                    "Use an ISO 8601 timestamp with timezone offset.",
                )
            )
        else:
            checks.append(
                _check(
                    f"{section}_metadata_valid",
                    "pass",
                    "info",
                    f"{section}.md has usable metadata.",
                    "Keep metadata current when content changes.",
                )
            )
    if not checks:
        checks.append(
            _check(
                "metadata_missing",
                "fail",
                "high",
                "No metadata could be evaluated.",
                "Run ai-memory init and add valid memory files.",
            )
        )
    return _category("metadata_quality", MEMORY_WEIGHTS["metadata_quality"], checks)


def _evaluate_safety_privacy(memory_dir: Path, sections: dict[str, dict[str, Any]]) -> EvalCategory:
    checks: list[EvalCheck] = []
    gitignore = memory_dir / ".gitignore"
    if gitignore.exists():
        ignored = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
        for pattern in ["private/", "snapshots/", "candidates/", "*.log", "*.patch", "evals/"]:
            checks.append(
                _check(
                    "gitignore_" + pattern.replace("*", "star").replace("/", ""),
                    "pass" if pattern in ignored else "warn",
                    "info" if pattern in ignored else "medium",
                    f".ai-memory/.gitignore {'includes' if pattern in ignored else 'is missing'} `{pattern}`.",
                    f"Add `{pattern}` to .ai-memory/.gitignore."
                    if pattern not in ignored
                    else "No action needed.",
                )
            )
    else:
        checks.append(
            _check(
                "gitignore_missing",
                "fail",
                "high",
                ".ai-memory/.gitignore is missing.",
                "Run ai-memory init or recreate the ignore file.",
            )
        )

    for section, info in sections.items():
        if info.get("error"):
            continue
        text = str(info["raw"])
        redacted, redactions = redact_secrets(text)
        if redactions:
            checks.append(
                _check(
                    f"{section}_secret_like_content",
                    "fail",
                    "high",
                    f"{section}.md contains likely secret material.",
                    "Manually remove or rotate secrets; eval does not rewrite existing memories.",
                )
            )
        elif SECRETS_MARKER in redacted:
            checks.append(
                _check(
                    f"{section}_redacted_marker",
                    "warn",
                    "medium",
                    f"{section}.md contains redacted secret markers.",
                    "Review whether the surrounding memory should be rewritten more cleanly.",
                )
            )
        else:
            checks.append(
                _check(
                    f"{section}_secret_scan_clean",
                    "pass",
                    "info",
                    f"{section}.md has no obvious secret pattern.",
                    "Continue avoiding credentials in memory files.",
                )
            )
    return _category("safety_privacy", MEMORY_WEIGHTS["safety_privacy"], checks)


def _category(name: str, weight: int, checks: list[EvalCheck]) -> EvalCategory:
    if not checks:
        score = 100
    else:
        score = round(sum(_check_score(check) for check in checks) / len(checks))
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


def _save_memory_report(memory_dir: Path, result: EvalResult) -> list[str]:
    return _save_report(memory_dir, result, "memory", _report_markdown(result))


def _save_dream_report(memory_dir: Path, result: DreamEvalResult) -> list[str]:
    return _save_report(memory_dir, result, "dream", _dream_report_markdown(result))


def _save_report(
    memory_dir: Path, result: EvalResult | DreamEvalResult, report_kind: str, markdown: str
) -> list[str]:
    _ensure_evals_ignored(memory_dir)
    reports_dir = memory_dir / "evals"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _report_timestamp(result.get("generated_at") or now_iso())
    json_path = reports_dir / f"{timestamp}-{report_kind}.json"
    md_path = reports_dir / f"{timestamp}-{report_kind}.md"
    latest_json = reports_dir / "latest.json"
    latest_md = reports_dir / "latest.md"

    paths = [str(latest_json), str(latest_md), str(json_path), str(md_path)]
    result["report_paths"] = paths
    json_text = json.dumps(result, indent=2, ensure_ascii=False)
    json_path.write_text(json_text + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    latest_json.write_text(json_text + "\n", encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    return paths


def _ensure_evals_ignored(memory_dir: Path) -> None:
    gitignore = memory_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(LOCAL_GITIGNORE, encoding="utf-8")
        return
    text = gitignore.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    missing: list[str] = []
    if "evals/" not in lines:
        missing.append("evals/")
    if "candidates/" not in lines:
        missing.append("candidates/")
    if missing:
        suffix = "" if text.endswith("\n") or not text else "\n"
        gitignore.write_text(text + suffix + "\n".join(missing) + "\n", encoding="utf-8")


def _report_timestamp(generated_at: str) -> str:
    return generated_at.replace(":", "").replace("+", "_").replace("-", "").replace(".", "")


def _report_markdown(result: EvalResult) -> str:
    lines = [
        "# Memory Fabric Eval Report",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Score: {result['score']} ({result['status']})",
        f"- Memory dir: `{result['memory_dir']}`",
        "",
        "## Categories",
        "",
    ]
    for category in result["categories"]:
        lines.append(f"### {category['name']} - {category['score']} ({category['status']})")
        lines.append("")
        for check in category["checks"]:
            lines.append(f"- {check['status'].upper()}: {check['message']}")
        lines.append("")
    lines.extend(_recommendation_lines(result["recommendations"]))
    lines.extend(_llm_lines(result["llm_notes"]))
    return "\n".join(lines).rstrip() + "\n"


def _dream_report_markdown(result: DreamEvalResult) -> str:
    lines = [
        "# Memory Fabric Dream Eval Report",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Baseline snapshot: `{result['baseline_snapshot']}`",
        f"- Dream score: {result['score']} ({result['status']})",
        f"- Memory score delta: {result['before_score']} -> {result['after_score']} ({result['delta']:+d})",
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in result["changed_files"] or ["No changed files detected"])
    lines.extend(["", "## Improvements", ""])
    lines.extend(
        f"- {item}" for item in result["improvements"] or ["No clear improvements detected"]
    )
    lines.extend(["", "## Regressions", ""])
    lines.extend(f"- {item}" for item in result["regressions"] or ["No clear regressions detected"])
    lines.extend(["", "## Categories", ""])
    for category in result["categories"]:
        lines.append(f"### {category['name']} - {category['score']} ({category['status']})")
        lines.append("")
        for check in category["checks"]:
            lines.append(f"- {check['status'].upper()}: {check['message']}")
        lines.append("")
    lines.extend(_recommendation_lines(result["recommendations"]))
    lines.extend(_llm_lines(result["llm_notes"]))
    return "\n".join(lines).rstrip() + "\n"


def _recommendation_lines(recommendations: list[str]) -> list[str]:
    if not recommendations:
        return ["", "## Recommendations", "", "- No immediate recommendations."]
    return ["", "## Recommendations", "", *[f"- {item}" for item in recommendations]]


def _llm_lines(notes: list[str]) -> list[str]:
    if not notes:
        return []
    return ["", "## Optional LLM Notes", "", *[f"- {note}" for note in notes]]


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
    except Exception as exc:
        notes.append(f"Failed to generate qualitative LLM review: {exc}")
    return notes


def _resolve_snapshot(memory_dir: Path, snapshot: str) -> str:
    if snapshot != "latest":
        return snapshot
    snapshots_dir = memory_dir / "snapshots"
    if not snapshots_dir.exists():
        raise FileNotFoundError("No snapshots directory exists")
    candidates = [path for path in snapshots_dir.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError("No snapshots available")
    return max(candidates, key=lambda path: path.stat().st_mtime).name


def _changed_files(before_root: Path, after_root: Path) -> list[str]:
    paths = set(_relative_markdown_paths(before_root)) | set(_relative_markdown_paths(after_root))
    changed: list[str] = []
    for relative in sorted(paths):
        before = before_root / relative
        after = after_root / relative
        if not before.exists() or not after.exists():
            changed.append(str(relative))
            continue
        if before.read_text(encoding="utf-8", errors="replace") != after.read_text(
            encoding="utf-8", errors="replace"
        ):
            changed.append(str(relative))
    return changed


def _relative_markdown_paths(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    paths: set[Path] = set()
    for path in root.rglob("*.md"):
        if _is_ignored_memory_path(root, path):
            continue
        paths.add(path.relative_to(root))
    return paths


def _files_with_new_secret_markers(
    before_sections: dict[str, dict[str, Any]],
    after_sections: dict[str, dict[str, Any]],
) -> list[str]:
    files: list[str] = []
    for section, after in after_sections.items():
        before_text = str(before_sections.get(section, {}).get("raw", ""))
        after_text = str(after.get("raw", ""))
        if SECRETS_MARKER in after_text and SECRETS_MARKER not in before_text:
            files.append(Path(after["path"]).name)
    return files


def _churn_ratio(before_root: Path, after_root: Path) -> float:
    paths = set(_relative_markdown_paths(before_root)) | set(_relative_markdown_paths(after_root))
    if not paths:
        return 0.0
    changed_count = len(_changed_files(before_root, after_root))
    return changed_count / len(paths)


def _dream_score_delta_category(delta: int) -> EvalCategory:
    if delta > 0:
        checks = [
            _check(
                "dream_score_delta_positive",
                "pass",
                "info",
                f"Memory score improved by {delta}.",
                "Keep the Dreaming changes.",
            )
        ]
    elif delta == 0:
        checks = [
            _check(
                "dream_score_delta_neutral",
                "warn",
                "low",
                "Memory score did not change.",
                "Review whether Dreaming produced useful maintenance.",
            )
        ]
    else:
        checks = [
            _check(
                "dream_score_delta_negative",
                "fail",
                "high",
                f"Memory score decreased by {abs(delta)}.",
                "Review changes and consider rollback.",
            )
        ]
    return _category("score_delta", DREAM_WEIGHTS["score_delta"], checks)


def _dream_regression_category(regressions: list[str]) -> EvalCategory:
    if not regressions:
        checks = [
            _check(
                "dream_no_regressions",
                "pass",
                "info",
                "No clear Dreaming regressions detected.",
                "No action needed.",
            )
        ]
    else:
        checks = [
            _check(
                "dream_regression_" + str(index),
                "fail" if "removed" in item or "decreased" in item else "warn",
                "high" if "removed" in item or "decreased" in item else "medium",
                item,
                "Review the Dreaming diff and rollback if needed.",
            )
            for index, item in enumerate(regressions, start=1)
        ]
    return _category("regression_safety", DREAM_WEIGHTS["regression_safety"], checks)


def _dream_index_summary_category(
    changed_files: list[str],
    before_category: EvalCategory,
    after_eval: EvalResult,
) -> EvalCategory:
    checks: list[EvalCheck] = []
    checks.append(
        _check(
            "dream_index_changed",
            "pass" if "index.md" in changed_files else "warn",
            "info" if "index.md" in changed_files else "medium",
            "index.md was updated." if "index.md" in changed_files else "index.md was not updated.",
            "Dreaming should refresh the index when memory changes.",
        )
    )
    if after_eval["score"] >= before_category["score"]:
        checks.append(
            _check(
                "dream_summary_not_worse",
                "pass",
                "info",
                "Post-dream memory quality did not score below the baseline quality category.",
                "Keep summaries specific and current.",
            )
        )
    else:
        checks.append(
            _check(
                "dream_summary_worse",
                "warn",
                "medium",
                "Post-dream quality score is below the baseline coding-usefulness category.",
                "Review summaries and restored detail.",
            )
        )
    return _category("index_summary", DREAM_WEIGHTS["index_summary"], checks)


def _dream_change_safety_category(
    changed_files: list[str],
    new_secret_files: list[str],
    churn_ratio: float,
) -> EvalCategory:
    checks = [
        _check(
            "dream_changed_files",
            "pass" if changed_files else "warn",
            "info" if changed_files else "low",
            f"Dreaming changed {len(changed_files)} file(s).",
            "No action needed."
            if changed_files
            else "Run Dreaming only when maintenance is needed.",
        ),
        _check(
            "dream_churn",
            "warn" if churn_ratio > 0.75 and len(changed_files) > 2 else "pass",
            "medium" if churn_ratio > 0.75 and len(changed_files) > 2 else "info",
            f"Dreaming churn ratio is {churn_ratio:.0%}.",
            "Review large Dreaming changes before trusting them."
            if churn_ratio > 0.75
            else "No action needed.",
        ),
    ]
    if new_secret_files:
        checks.append(
            _check(
                "dream_new_secret_markers",
                "fail",
                "high",
                "Dreaming introduced redacted secret markers.",
                "Review the affected memory files and remove sensitive context.",
            )
        )
    return _category("change_safety", DREAM_WEIGHTS["change_safety"], checks)
