"""Memory-fabric quality evaluation: coding usefulness, section coverage,
retrieval readiness, metadata quality, and safety/privacy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_fabric.contracts import EvalCategory, EvalCheck, EvalResult
from memory_fabric.eval._shared import (
    MEMORY_WEIGHTS,
    REQUIRED_SECTIONS,
    SECRETS_MARKER,
    _bad_summary,
    _category,
    _check,
    _duplicate_summaries,
    _is_placeholder_body,
    _is_timezone_aware,
    _llm_notes,
    _load_sections,
    _memory_result,
    _recommendations_from_categories,
    _section_load_warnings,
)
from memory_fabric.eval.reports import _report_markdown, _save_memory_report
from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.paths import local_memory_dir, project_root
from memory_fabric.security import redact_secrets
from memory_fabric.storage import read_combined_context
from memory_fabric.storage._shared import STEERING_SECTIONS
from memory_fabric.storage.maps import category_fingerprint
from memory_fabric.storage.verify import verify_evidence
from memory_fabric.templates import SECTION_TEMPLATES, now_iso


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
        _evaluate_metadata_quality(cwd, sections),
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
        _evaluate_metadata_quality(cwd, _load_sections(root), memory_dir=root),
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


def _evaluate_metadata_quality(
    cwd: str, sections: dict[str, dict[str, Any]], memory_dir: Path | None = None
) -> EvalCategory:
    checks: list[EvalCheck] = []

    # Self-verifying citations: read-only here (eval must not mutate files as a
    # side effect of scoring) — `ai-memory verify` is the explicit, opt-in
    # action that stamps review_status: broken-evidence. `memory_dir` lets a
    # snapshot-scoring caller check that snapshot's evidence lists instead of
    # the live store's.
    verify_result = verify_evidence(cwd, mark_broken=False, memory_dir=memory_dir)
    for broken in verify_result["broken"]:
        checks.append(
            _check(
                f"{broken['key']}_evidence_broken",
                "fail",
                "medium",
                f"{broken['key']} cites evidence that no longer resolves: "
                + "; ".join(broken["problems"]),
                "Run `ai-memory verify` and update or remove the stale citation.",
                "ai-memory verify",
            )
        )
    if verify_result["checked_files"] and not verify_result["broken"]:
        checks.append(
            _check(
                "evidence_all_resolved",
                "pass",
                "info",
                f"All {verify_result['checked_files']} memory file(s) with evidence citations resolved.",
                "Keep citing concrete files/commits so memory stays checkable.",
            )
        )

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
