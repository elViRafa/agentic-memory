"""Dream-quality evaluation: compares memory state before and after a Dreaming
run against the pre-dream snapshot to measure improvement or regression.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_fabric.contracts import DreamEvalResult, EvalCategory, EvalCheck, EvalResult
from memory_fabric.eval._shared import (
    DREAM_WEIGHTS,
    SECRETS_MARKER,
    _category,
    _check,
    _is_ignored_memory_path,
    _llm_notes,
    _load_sections,
    _recommendations_from_categories,
    _score_status,
    _weighted_score,
)
from memory_fabric.eval.memory_quality import (
    _memory_eval_for_root,
    evaluate_memory_fabric,
    evaluate_memory_quality,
)
from memory_fabric.eval.reports import _dream_report_markdown, _save_dream_report
from memory_fabric.paths import local_memory_dir, project_root
from memory_fabric.templates import now_iso


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
