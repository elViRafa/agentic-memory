"""Markdown rendering and on-disk persistence for eval/dream report results."""

from __future__ import annotations

import json
from pathlib import Path

from memory_fabric.contracts import DreamEvalResult, EvalResult
from memory_fabric.templates import LOCAL_GITIGNORE, now_iso


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
