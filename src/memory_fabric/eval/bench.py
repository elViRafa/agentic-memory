"""Coding-memory benchmark: memory-on vs memory-off retrieval on a fixture.

Phase 5 / R6-3. Measures whether later-session tasks can recover decisions
recorded in earlier sessions. No LLM required for the default score — that
keeps CI honest. Optional suite files let a user run the same harness against
their own store.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from memory_fabric.contracts import (
    BenchContextScore,
    BenchResult,
    BenchSearchScore,
    BenchTaskScore,
    ContextBundle,
    SearchResult,
)
from memory_fabric.diary.roles import classify_role
from memory_fabric.eval._recall_fixture import (
    RECALL_STEERING,
    RECALL_TASKS,
    populate_recall_fixture,
)
from memory_fabric.storage import (
    context_for_task,
    initialize_memory_fabric,
    keyword_search,
    write_memory_store,
)
from memory_fabric.templates import now_iso
from memory_fabric.version import __version__

_DEFAULT_K = 5
_SEARCH_RECALL_CUTOFF = 5
_FIXTURE_NAME = "coding-memory-field"
_SECTION_MARKER = re.compile(r"^<!-- memory-fabric:([^\s]+) -->[ \t]*\r?$", re.MULTILINE)

# Field-scale recall targets (coding-memory fixture): domain column choice,
# test_*.py naming, framework choice, plus a reversed product decision.
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
        "expected_status": "matched",
    },
    {
        "id": "test-file-naming",
        "query": "What should a new Python test file be named?",
        "expected_store_paths": ["rules/test-file-naming"],
        "expected_tokens": ["test_*.py"],
        "expected_status": "matched",
    },
    {
        "id": "no-drf",
        "query": "Can we use Django REST Framework?",
        "expected_store_paths": ["decisions/no-django-rest-framework"],
        "expected_tokens": ["does not use Django REST Framework"],
        "expected_status": "matched",
    },
    {
        "id": "urnas-reversal",
        "query": "Is urnas_add_pos_calc still part of the schema?",
        "expected_store_paths": ["decisions/prd-0009-reverse-urnas-add-pos-calc"],
        "expected_tokens": ["PRD 0009 reverses", "Do not add urnas_add_pos_calc"],
        "expected_status": "matched",
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

    ``fixture="builtin"`` builds the original store in a temp dir.
    ``fixture="recall"`` uses synthetic field-report cases.
    Any other ``fixture`` value is treated as a project cwd whose live store
    is the memory-on side; tasks then come from ``suite_path`` or
    ``.ai-memory/evals/bench.yaml``.
    """
    warnings: list[str] = []
    k = max(1, int(k))
    tasks = RECALL_TASKS if fixture == "recall" else _BUILTIN_TASKS
    if suite_path:
        loaded = _load_suite(Path(suite_path))
        if loaded:
            tasks = loaded
        else:
            warnings.append(f"Suite unreadable or empty: {suite_path}")

    if not fixture or fixture in {"builtin", "recall"}:
        return _run_builtin(tasks, recall=fixture == "recall", k=k, warnings=warnings)

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
    recalls = [task["search"]["memory_on"]["recall_at_5"] for task in result["tasks"]]
    answerable = [recall for recall in recalls if recall is not None]
    recall_at_five = f"{sum(answerable) / len(answerable):.2f}" if answerable else "—"
    lines = [
        "# Coding-memory benchmark",
        "",
        f"- Fixture: `{result['fixture']}`",
        f"- Engine: {result['engine_version']}",
        f"- Generated: {result['generated_at']}",
        f"- k: {result['k']}",
        f"- Search recall at five (cases with search targets): {recall_at_five}",
        f"- Legacy memory-on recall: {result['memory_on_recall']:.2f}",
        f"- Legacy memory-off recall: {result['memory_off_recall']:.2f}",
        f"- Legacy lift: {result['lift']:.2f}",
        f"- passed: {result['passed']}",
        "",
        "| Task | Expected status | Delivered status | First search rank | Recall@5 | Search hits | Search | "
        "Evidence fragments | Delivered evidence | Inclusion disagreement | Case |",
        "|---|---|---|---:|---:|---:|---|---:|---|---:|---|",
    ]
    for task in result["tasks"]:
        search = task["search"]["memory_on"]
        context = task["task_context"]["memory_on"]
        recall = search["recall_at_5"]
        rank_display = search["first_correct_rank"] or "—"
        recall_display = f"{recall:.2f}" if recall is not None else "—"
        disagreement = len(context["metadata_only_sections"]) + len(context["text_only_sections"])
        lines.append(
            f"| {task['id']} | {task['expected_status'] or '—'} | "
            f"{context.get('retrieval_status') or '—'} | {rank_display} | "
            f"{recall_display} | {search['hit_count']} | {'pass' if search['passed'] else 'fail'} | "
            f"{context['evidence_fragments']} | {'pass' if context['passed'] else 'fail'} | "
            f"{disagreement} | {'pass' if task['passed'] else 'fail'} |"
        )
    if result["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {w}" for w in result["warnings"])
    lines.append("")
    return "\n".join(lines)


def _run_builtin(
    tasks: list[dict[str, Any]], *, recall: bool, k: int, warnings: list[str]
) -> BenchResult:
    with tempfile.TemporaryDirectory() as on_dir, tempfile.TemporaryDirectory() as off_dir:
        steering = RECALL_STEERING if recall else None
        initialize_memory_fabric(on_dir, memory_prompt=steering)
        initialize_memory_fabric(off_dir, memory_prompt=steering)
        if recall:
            populate_recall_fixture(on_dir)
        else:
            _populate_fixture(on_dir)
        return _score_pair(
            on_cwd=on_dir,
            off_cwd=off_dir,
            tasks=tasks,
            k=k,
            fixture_name="recall" if recall else _FIXTURE_NAME,
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
    result: BenchResult = {
        "kind": "coding-memory",
        "engine_version": __version__,
        "generated_at": now_iso(),
        "fixture": fixture_name,
        "k": k,
        "tasks": scored,
        "memory_on_recall": on_mean,
        "memory_off_recall": off_mean,
        "lift": lift,
        "passed": bool(scored) and all(task["passed"] for task in scored),
        "warnings": warnings,
        "report_markdown": "",
    }
    result["report_markdown"] = render_bench_markdown(result)
    return result


def _score_task(spec: dict[str, Any], *, on_cwd: str, off_cwd: str, k: int) -> BenchTaskScore:
    query = str(spec.get("query") or "")
    expected = [str(p).strip("/") for p in (spec.get("expected_store_paths") or [])]
    tokens = [str(t) for t in (spec.get("expected_tokens") or [])]
    status = spec.get("expected_status")
    unanswerable = status == "no_match"
    search_paths = spec.get("search_expected_store_paths")
    search_expected = (
        expected if search_paths is None else [str(p).strip("/") for p in search_paths]
    )
    search_unanswerable = unanswerable or search_paths == []
    files_open = spec.get("files_open") or None
    budget = spec.get("max_tokens")
    max_tokens = int(budget) if budget is not None else None
    search_limit = max(k, _SEARCH_RECALL_CUTOFF)
    on_results = keyword_search(on_cwd, query, max_results=search_limit)
    off_results = keyword_search(off_cwd, query, max_results=search_limit)
    on_pack = context_for_task(on_cwd, query, files_open=files_open, max_tokens=max_tokens, top_k=k)
    off_pack = context_for_task(
        off_cwd, query, files_open=files_open, max_tokens=max_tokens, top_k=k
    )
    on_search = _score_search(on_results, search_expected, search_unanswerable)
    off_search = _score_search(off_results, search_expected, search_unanswerable)
    on_context = _score_context(on_pack, expected, tokens, unanswerable)
    off_context = _score_context(off_pack, expected, tokens, unanswerable)
    on_hits = _legacy_hits(on_results[:k], on_pack)
    off_hits = _legacy_hits(off_results[:k], off_pack)
    on_recall = _recall(expected, on_hits)
    off_recall = _recall(expected, off_hits)
    on_token_hit = _tokens_hit(on_pack["text"], tokens)
    inclusion_agrees = all(
        not score["metadata_only_sections"] and not score["text_only_sections"]
        for score in (on_context, off_context)
    )
    search_control = (
        off_search["passed"] if search_unanswerable else off_search["first_correct_rank"] is None
    )
    context_control = (
        off_context["passed"] if unanswerable else not off_context["matched_store_paths"]
    )
    if status is None:
        passed = on_recall == 1.0 and off_recall == 0.0 and on_token_hit
    else:
        passed = (
            on_search["passed"]
            and on_context["passed"]
            and on_context.get("retrieval_status") == status
            and inclusion_agrees
            and search_control
            and context_control
        )
    return {
        "id": str(spec.get("id") or query[:40] or "task"),
        "query": query,
        "expected_store_paths": expected,
        "memory_on_hits": on_hits,
        "memory_off_hits": off_hits,
        "memory_on_recall": on_recall,
        "memory_off_recall": off_recall,
        "memory_on_token_hit": on_token_hit,
        "memory_off_token_hit": _tokens_hit(off_pack["text"], tokens),
        "expected_tokens": tokens,
        "expected_status": status,
        "search_expected_store_paths": search_expected,
        "search": {"memory_on": on_search, "memory_off": off_search},
        "task_context": {"memory_on": on_context, "memory_off": off_context},
        "passed": passed,
    }


def _recall(expected: list[str], paths: list[str]) -> float:
    return sum(path in paths for path in expected) / len(expected) if expected else 0.0


def _score_search(
    results: list[SearchResult], expected: list[str], unanswerable: bool
) -> BenchSearchScore:
    sections = [result["section"] for result in results]
    targets = {f"store:{path}" for path in expected}
    rank = next((i for i, section in enumerate(sections, 1) if section in targets), None)
    recall = None if unanswerable else _recall(list(targets), sections[:_SEARCH_RECALL_CUTOFF])
    return {
        "hit_count": len(sections),
        "first_correct_rank": rank,
        "recall_at_5": recall,
        "passed": not sections if unanswerable else recall == 1.0,
    }


def _score_context(
    pack: ContextBundle, expected: list[str], tokens: list[str], unanswerable: bool
) -> BenchContextScore:
    parts = _SECTION_MARKER.split(pack["text"])
    fragments = [
        (key, text)
        for key, text in zip(parts[1::2], parts[2::2], strict=True)
        if key != "omission-notice"
    ]
    rendered = {key for key, _ in fragments}
    included = set(pack["included_sections"])
    evidence_count = sum(classify_role(key) not in {"tier0", "steering"} for key, _ in fragments)
    matched = [path for path in expected if f"store/{path}" in rendered]
    target_keys = {f"store/{path}" for path in matched}
    source_fragments = [fragment.casefold() for key, fragment in fragments if key in target_keys]
    phrase_hit = bool(matched) and all(
        any(token.casefold() in fragment for fragment in source_fragments) for token in tokens
    )
    passed = evidence_count == 0 if unanswerable else len(matched) == len(expected) and phrase_hit
    score: BenchContextScore = {
        "evidence_fragments": evidence_count,
        "matched_store_paths": matched,
        "phrase_hit": phrase_hit,
        "metadata_only_sections": sorted(included - rendered),
        "text_only_sections": sorted(rendered - included),
        "passed": passed,
    }
    if "retrieval_status" in pack:
        score["retrieval_status"] = pack["retrieval_status"]
    return score


def _legacy_hits(results: list[SearchResult], pack: ContextBundle) -> list[str]:
    hits = [
        result["section"].removeprefix("store:")
        for result in results
        if result["section"].startswith("store:")
    ]
    for key in pack["included_sections"]:
        if key.startswith("store/"):
            path = key.removeprefix("store/")
            if path not in hits:
                hits.append(path)
    return hits


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
