"""Coding-memory benchmark: memory-on vs memory-off retrieval on a fixture.

Phase 5 / R6-3. Measures whether later-session tasks can recover decisions
recorded in earlier sessions. No LLM required for the default score — that
keeps CI honest. Optional suite files let a user run the same harness against
their own store.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from memory_fabric.contracts import BenchResult, BenchTaskScore
from memory_fabric.storage import (
    context_for_task,
    initialize_memory_fabric,
    keyword_search,
    write_memory_store,
)
from memory_fabric.templates import now_iso

_DEFAULT_K = 5
_FIXTURE_NAME = "coding-memory-field"

# Field-report recall targets (gerenciador-eleicao dogfood): TOT_LOCAL CAD vs
# system columns, test_*.py naming, no DRF, plus the PRD 0008/0009 reversal.
_FIXTURE_MEMORIES: list[dict[str, str]] = [
    {
        "store_path": "decisions/tot-local-cad-columns",
        "title": "TOT_LOCAL uses CAD columns",
        "content": (
            "TOT_LOCAL must be computed from CAD columns, not from system columns. "
            "System columns are derived and must not be treated as the source of "
            "truth for TOT_LOCAL totals."
        ),
    },
    {
        "store_path": "rules/test-file-naming",
        "title": "Python test file naming",
        "content": (
            "New Python tests live under tests/ and must be named test_*.py. "
            "Do not create tests_*.py files — that prefix is wrong for this repo."
        ),
    },
    {
        "store_path": "decisions/no-django-rest-framework",
        "title": "No Django REST Framework",
        "content": (
            "This project does not use Django REST Framework (DRF). Prefer Django "
            "views and HTMX. Do not add rest_framework to INSTALLED_APPS."
        ),
    },
    {
        "store_path": "decisions/prd-0008-urnas-add-pos-calc",
        "title": "PRD 0008 add urnas_add_pos_calc",
        "content": (
            "PRD 0008 adds the column urnas_add_pos_calc so calculated positions "
            "can be stored after the tally."
        ),
    },
    {
        "store_path": "decisions/prd-0009-reverse-urnas-add-pos-calc",
        "title": "PRD 0009 reverses urnas_add_pos_calc",
        "content": (
            "PRD 0009 reverses PRD 0008. Do not add urnas_add_pos_calc; the column "
            "was withdrawn and must not appear in the schema."
        ),
    },
    {
        "store_path": "debt/pagination-backlog",
        "title": "Pagination backlog",
        "content": (
            "List endpoints still paginate at 50 items. Unrelated to column policy "
            "or the test-file convention."
        ),
    },
]

_FIXTURE_DISTRACTOR_JOURNAL = (
    "Session notes. Discussed sync-agents, guidelines compiler, and a long "
    "review of maps. Mentioned TOT_LOCAL only in passing while scrolling logs. "
    + (" journal " * 200)
)

_BUILTIN_TASKS: list[dict[str, Any]] = [
    {
        "id": "tot-local-columns",
        "query": "Should TOT_LOCAL use CAD columns or system columns?",
        "expected_store_paths": ["decisions/tot-local-cad-columns"],
        "expected_tokens": ["CAD columns", "not from system"],
    },
    {
        "id": "test-file-naming",
        "query": "What should a new Python test file be named?",
        "expected_store_paths": ["rules/test-file-naming"],
        "expected_tokens": ["test_*.py"],
    },
    {
        "id": "no-drf",
        "query": "Can we use Django REST Framework?",
        "expected_store_paths": ["decisions/no-django-rest-framework"],
        "expected_tokens": ["does not use Django REST Framework"],
    },
    {
        "id": "urnas-reversal",
        "query": "Is urnas_add_pos_calc still part of the schema?",
        "expected_store_paths": ["decisions/prd-0009-reverse-urnas-add-pos-calc"],
        "expected_tokens": ["PRD 0009 reverses", "Do not add urnas_add_pos_calc"],
    },
]


def run_coding_memory_benchmark(
    cwd: str | None = None,
    *,
    fixture: str = "builtin",
    suite_path: str | None = None,
    k: int = _DEFAULT_K,
) -> BenchResult:
    """Score memory-on vs memory-off retrieval.

    ``fixture="builtin"`` builds the field-inspired store in a temp dir.
    Any other ``fixture`` value is treated as a project cwd whose live store
    is the memory-on side; tasks then come from ``suite_path`` or
    ``.ai-memory/evals/bench.yaml``.
    """
    warnings: list[str] = []
    k = max(1, int(k))
    tasks = list(_BUILTIN_TASKS)
    if suite_path:
        loaded = _load_suite(Path(suite_path))
        if loaded:
            tasks = loaded
        else:
            warnings.append(f"Suite unreadable or empty: {suite_path}")

    if fixture == "builtin" or not fixture:
        return _run_builtin(tasks, k=k, warnings=warnings)

    project = str(Path(fixture if fixture not in {".", "cwd"} else (cwd or ".")).resolve())
    if not suite_path:
        default_suite = Path(project) / ".ai-memory" / "evals" / "bench.yaml"
        alt_suite = Path(project) / ".ai-memory" / "evals" / "retrieval.yaml"
        if default_suite.exists():
            loaded = _load_suite(default_suite)
            if loaded:
                tasks = loaded
        elif alt_suite.exists():
            loaded = _load_retrieval_as_suite(alt_suite)
            if loaded:
                tasks = loaded
                warnings.append(f"Using retrieval.yaml as bench suite: {alt_suite}")
            else:
                warnings.append(
                    "No bench.yaml / usable retrieval.yaml; falling back to builtin tasks."
                )
    return _score_pair(
        on_cwd=project,
        off_cwd=None,
        tasks=tasks,
        k=k,
        fixture_name=project,
        warnings=warnings,
    )


def render_bench_markdown(result: BenchResult) -> str:
    lines = [
        "# Coding-memory benchmark",
        "",
        f"- Fixture: `{result['fixture']}`",
        f"- Generated: {result['generated_at']}",
        f"- k: {result['k']}",
        f"- memory-on recall: {result['memory_on_recall']:.2f}",
        f"- memory-off recall: {result['memory_off_recall']:.2f}",
        f"- lift: {result['lift']:.2f}",
        f"- passed: {result['passed']}",
        "",
        "| Task | Query | On recall | Off recall | On tokens | Off tokens |",
        "|---|---|---:|---:|---|---|",
    ]
    for task in result["tasks"]:
        lines.append(
            f"| {task['id']} | {task['query']} | {task['memory_on_recall']:.2f} | "
            f"{task['memory_off_recall']:.2f} | "
            f"{'yes' if task['memory_on_token_hit'] else 'no'} | "
            f"{'yes' if task['memory_off_token_hit'] else 'no'} |"
        )
    if result["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {w}" for w in result["warnings"])
    lines.append("")
    return "\n".join(lines)


def _run_builtin(tasks: list[dict[str, Any]], *, k: int, warnings: list[str]) -> BenchResult:
    with tempfile.TemporaryDirectory() as on_dir, tempfile.TemporaryDirectory() as off_dir:
        initialize_memory_fabric(on_dir)
        initialize_memory_fabric(off_dir)
        _populate_fixture(on_dir)
        return _score_pair(
            on_cwd=on_dir,
            off_cwd=off_dir,
            tasks=tasks,
            k=k,
            fixture_name=_FIXTURE_NAME,
            warnings=warnings,
        )


def _populate_fixture(cwd: str) -> None:
    for item in _FIXTURE_MEMORIES:
        write_memory_store(
            cwd,
            item["store_path"],
            item["content"],
            title=item["title"],
            tags=["benchmark", "fixture"],
            priority="high",
        )
    write_memory_store(
        cwd,
        "episodic/2026-07-24",
        _FIXTURE_DISTRACTOR_JOURNAL,
        title="Episodic Journal — 2026-07-24",
        tags=["episodic", "benchmark"],
        priority="low",
    )


def _score_pair(
    *,
    on_cwd: str,
    off_cwd: str | None,
    tasks: list[dict[str, Any]],
    k: int,
    fixture_name: str,
    warnings: list[str],
) -> BenchResult:
    off_holder = None
    scored: list[BenchTaskScore] = []
    try:
        if off_cwd is None:
            off_holder = tempfile.TemporaryDirectory()
            off_cwd = off_holder.name
            initialize_memory_fabric(off_cwd)
        for spec in tasks:
            scored.append(_score_task(spec, on_cwd=on_cwd, off_cwd=off_cwd, k=k))
    finally:
        if off_holder is not None:
            off_holder.cleanup()

    on_recalls = [t["memory_on_recall"] for t in scored]
    off_recalls = [t["memory_off_recall"] for t in scored]
    on_mean = sum(on_recalls) / len(on_recalls) if on_recalls else 0.0
    off_mean = sum(off_recalls) / len(off_recalls) if off_recalls else 0.0
    lift = on_mean - off_mean
    token_on = all(t["memory_on_token_hit"] for t in scored) if scored else False
    passed = bool(scored) and on_mean >= 1.0 and off_mean == 0.0 and lift > 0 and token_on
    result: BenchResult = {
        "kind": "coding-memory",
        "generated_at": now_iso(),
        "fixture": fixture_name,
        "k": k,
        "tasks": scored,
        "memory_on_recall": on_mean,
        "memory_off_recall": off_mean,
        "lift": lift,
        "passed": passed,
        "warnings": warnings,
        "report_markdown": "",
    }
    result["report_markdown"] = render_bench_markdown(result)
    return result


def _score_task(spec: dict[str, Any], *, on_cwd: str, off_cwd: str, k: int) -> BenchTaskScore:
    query = str(spec.get("query") or "")
    expected = [str(p).strip("/") for p in (spec.get("expected_store_paths") or [])]
    tokens = [str(t) for t in (spec.get("expected_tokens") or [])]
    on_hits, on_text = _retrieve(on_cwd, query, k)
    off_hits, off_text = _retrieve(off_cwd, query, k)
    on_matched = [p for p in expected if p in on_hits]
    off_matched = [p for p in expected if p in off_hits]
    on_recall = (len(on_matched) / len(expected)) if expected else 0.0
    off_recall = (len(off_matched) / len(expected)) if expected else 0.0
    return {
        "id": str(spec.get("id") or query[:40] or "task"),
        "query": query,
        "expected_store_paths": expected,
        "memory_on_hits": on_hits,
        "memory_off_hits": off_hits,
        "memory_on_recall": on_recall,
        "memory_off_recall": off_recall,
        "memory_on_token_hit": _tokens_hit(on_text, tokens),
        "memory_off_token_hit": _tokens_hit(off_text, tokens),
    }


def _retrieve(cwd: str, query: str, k: int) -> tuple[list[str], str]:
    hits: list[str] = []
    results = keyword_search(cwd, query, max_results=k)
    for result in results:
        section = str(result.get("section") or "")
        if section.startswith("store:"):
            hits.append(section[len("store:") :])
    pack = context_for_task(cwd, query, top_k=k)
    for key in pack.get("included_sections") or []:
        if isinstance(key, str) and key.startswith("store/"):
            path = key[len("store/") :]
            if path not in hits:
                hits.append(path)
    return hits, str(pack.get("text") or "")


def _tokens_hit(text: str, tokens: list[str]) -> bool:
    if not tokens:
        return True
    blob = text.casefold()
    return all(token.casefold() in blob for token in tokens)


def _load_suite(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    data: Any
    if path.suffix == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
    else:
        data = _parse_simple_yaml_list(raw)
    if isinstance(data, dict):
        data = data.get("tasks") or data.get("cases") or []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("query")]


def _load_retrieval_as_suite(path: Path) -> list[dict[str, Any]]:
    cases = _load_suite(path)
    out: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        out.append(
            {
                "id": str(case.get("id") or f"retrieval-{index}"),
                "query": case.get("query"),
                "expected_store_paths": case.get("expected_store_paths") or [],
                "expected_tokens": case.get("expected_tokens") or [],
            }
        )
    return out


def _parse_simple_yaml_list(raw: str) -> list[dict[str, Any]]:
    """Tiny YAML subset: a list of mappings with scalar / list values.

    Avoids a PyYAML dependency. Good enough for bench.yaml / retrieval.yaml.
    """
    try:
        import json

        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    list_key: str | None = None
    for raw_line in raw.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("- "):
            if current:
                items.append(current)
            current = {}
            list_key = None
            rest = raw_line[2:].strip()
            if ":" in rest:
                key, _, value = rest.partition(":")
                current[key.strip()] = _scalar(value.strip())
            continue
        if current is None:
            continue
        stripped = raw_line.strip()
        if stripped.startswith("- ") and list_key:
            current.setdefault(list_key, [])
            if isinstance(current[list_key], list):
                current[list_key].append(_scalar(stripped[2:].strip()))
            continue
        if ":" in raw_line and raw_line[:1] in {" ", "\t"}:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "" or value == "[]":
                current[key] = []
                list_key = key
            else:
                current[key] = _scalar(value)
                list_key = None
    if current:
        items.append(current)
    return items


def _scalar(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value.replace("'", '"'))
        except json.JSONDecodeError:
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [part.strip().strip("'\"") for part in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value
