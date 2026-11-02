"""Maintainer analyze for local field-diary packs. No network, any project_id."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from memory_fabric.contracts import DiaryAnalyzeResult
from memory_fabric.diary.consent import diary_dir, field_packs_dir
from memory_fabric.security import redact_secrets

_POSTURE_MIN_N = 5
_POSTURE_MIN_RATE = 0.80
_STEERING_MIN_N = 5
_STEERING_MAX_MEDIAN = 0.50
_PRIORITY_MIN_N = 5
_PRIORITY_OMITTED_HIGH = 8
_TOOL_MIN_N = 10
_TOOL_MAX_FAIL_RATE = 0.25
_TOP_QUERIES = 10


def analyze_diary(
    *,
    pack: str | Path | None = None,
    diary: str | Path | None = None,
    project: str | None = None,
) -> DiaryAnalyzeResult:
    """Score product signals from a pack folder or raw diary JSONL."""
    source, source_kind, warnings = _resolve_source(pack=pack, diary=diary)
    events = _read_events(source, source_kind, warnings)
    if project:
        events = [e for e in events if str(e.get("project_id") or "") == project]

    by_project: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        pid = str(event.get("project_id") or "unknown")
        by_project.setdefault(pid, []).append(event)

    projects: dict[str, Any] = {}
    failed = False
    for pid in sorted(by_project):
        report = _analyze_project(pid, by_project[pid])
        projects[pid] = report
        if report.get("failed"):
            failed = True

    rollup = _analyze_project("all", events) if events else {
        "project_id": "all",
        "event_n": 0,
        "signals": {},
        "failed": False,
        "failures": [],
    }
    # Rollup never drives exit code by itself.
    rollup["failed"] = False
    rollup["failures"] = []

    message = (
        f"Analyzed {len(events)} events across {len(projects)} project(s) from {source}."
        if events
        else f"No events to analyze under {source}."
    )
    if failed:
        message += " One or more project gates failed."
    return {
        "ok": not failed,
        "source": str(source),
        "event_n": len(events),
        "project_n": len(projects),
        "projects": projects,
        "rollup": rollup,
        "warnings": warnings,
        "message": message,
    }


def _resolve_source(
    *,
    pack: str | Path | None,
    diary: str | Path | None,
) -> tuple[Path, str, list[str]]:
    warnings: list[str] = []
    if pack is not None:
        return Path(pack), "explicit-pack", warnings
    if diary is not None:
        return Path(diary), "explicit-diary", warnings
    latest = _latest_pack()
    if latest is not None:
        return latest, "latest-pack", warnings
    return diary_dir(), "local-diary", warnings


def _latest_pack() -> Path | None:
    root = field_packs_dir()
    if not root.is_dir():
        return None
    try:
        packs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("field-")]
    except OSError:
        return None
    if not packs:
        return None
    packs.sort(key=lambda p: p.name, reverse=True)
    return packs[0]


def _read_events(source: Path, kind: str, warnings: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not source.exists():
        warnings.append(f"source missing: {source}")
        return events
    files: list[Path] = []
    if source.is_file() and source.suffix == ".jsonl":
        files = [source]
    elif source.is_dir():
        packed = source / "events.jsonl"
        if packed.is_file():
            files = [packed]
        else:
            files = sorted(source.glob("events-*.jsonl"))
            if not files and kind.startswith("explicit-pack"):
                warnings.append(f"no events.jsonl or events-*.jsonl under {source}")
    else:
        warnings.append(f"source is neither a directory nor a jsonl file: {source}")
        return events
    if not files:
        warnings.append(f"no event files under {source}")
        return events
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            warnings.append(f"could not read {path.name}: {exc}")
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                warnings.append(f"skipped unparseable line {path.name}:{line_no}")
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _analyze_project(project_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    packs = [e for e in events if e.get("event") == "context.pack"]
    tools = [e for e in events if e.get("event") in {"tool.call", "dream.result"}]
    failures: list[str] = []

    posture = _posture_signal(packs)
    if posture.get("failed"):
        failures.append(str(posture["detail"]))

    steering = _steering_signal(packs)
    if steering.get("failed"):
        failures.append(str(steering["detail"]))

    priority = _priority_signal(packs)
    if priority.get("failed"):
        failures.append(str(priority["detail"]))

    tool_mix = _tool_signal(tools)
    if tool_mix.get("failed"):
        failures.append(str(tool_mix["detail"]))

    queries = _top_queries(events)

    return {
        "project_id": project_id,
        "event_n": len(events),
        "signals": {
            "posture_slot": posture,
            "steering_share": steering,
            "priority_shape": priority,
            "tool_mix": tool_mix,
            "top_queries": queries,
        },
        "failed": bool(failures),
        "failures": failures,
    }


def _posture_signal(packs: list[dict[str, Any]]) -> dict[str, Any]:
    cohorts: dict[str, dict[str, Any]] = {}
    for label, subset in (
        ("no_query", [p for p in packs if not p.get("query_present")]),
        ("query", [p for p in packs if p.get("query_present")]),
    ):
        included = sum(1 for p in subset if p.get("posture_slot") == "included")
        omitted = sum(1 for p in subset if p.get("posture_slot") == "omitted")
        n = included + omitted
        rate = (included / n) if n else None
        failed = bool(n >= _POSTURE_MIN_N and rate is not None and rate < _POSTURE_MIN_RATE)
        cohorts[label] = {
            "n": n,
            "included": included,
            "omitted": omitted,
            "absent": sum(1 for p in subset if p.get("posture_slot") == "absent"),
            "unknown": sum(
                1
                for p in subset
                if p.get("posture_slot") in {None, "unknown"} or "posture_slot" not in p
            ),
            "rate": rate,
            "failed": failed,
        }
    failed_labels = [k for k, v in cohorts.items() if v["failed"]]
    detail = ""
    if failed_labels:
        bits = [
            f"{k} rate={cohorts[k]['rate']:.2f} (n={cohorts[k]['n']})" for k in failed_labels
        ]
        detail = "posture_slot below 0.80: " + "; ".join(bits)
    return {
        "cohorts": cohorts,
        "failed": bool(failed_labels),
        "detail": detail,
    }


def _steering_signal(packs: list[dict[str, Any]]) -> dict[str, Any]:
    shares: list[float] = []
    for pack in packs:
        budget = pack.get("token_budget")
        if not isinstance(budget, (int, float)) or budget <= 0:
            continue
        roles = pack.get("tokens_by_role") or {}
        if not isinstance(roles, dict):
            continue
        steering = roles.get("steering") or 0
        if not isinstance(steering, (int, float)):
            continue
        shares.append(float(steering) / float(budget))
    n = len(shares)
    median = statistics.median(shares) if shares else None
    failed = bool(n >= _STEERING_MIN_N and median is not None and median > _STEERING_MAX_MEDIAN)
    detail = ""
    if failed:
        detail = f"steering share median {median:.2f} over 0.50 (n={n})"
    return {
        "n": n,
        "median": median,
        "failed": failed,
        "detail": detail,
    }


def _priority_signal(packs: list[dict[str, Any]]) -> dict[str, Any]:
    omitted_high: list[int] = []
    included_high: list[int] = []
    for pack in packs:
        omitted = pack.get("omitted_by_priority") or {}
        included = pack.get("included_by_priority") or {}
        if not isinstance(omitted, dict) or not isinstance(included, dict):
            continue
        oh = omitted.get("high") or 0
        ih = included.get("high") or 0
        if not isinstance(oh, (int, float)) or not isinstance(ih, (int, float)):
            continue
        omitted_high.append(int(oh))
        included_high.append(int(ih))
    n = len(omitted_high)
    med_omit = statistics.median(omitted_high) if omitted_high else None
    med_incl = statistics.median(included_high) if included_high else None
    failed = bool(
        n >= _PRIORITY_MIN_N
        and med_omit is not None
        and med_incl is not None
        and med_omit >= _PRIORITY_OMITTED_HIGH
        and med_omit > med_incl
    )
    detail = ""
    if failed:
        detail = (
            f"priority inflation: median omitted_high={med_omit} "
            f"> included_high={med_incl} (n={n})"
        )
    return {
        "n": n,
        "median_omitted_high": med_omit,
        "median_included_high": med_incl,
        "failed": failed,
        "detail": detail,
    }


def _tool_signal(tools: list[dict[str, Any]]) -> dict[str, Any]:
    by_name: Counter[str] = Counter()
    fail_n = 0
    for event in tools:
        name = str(event.get("name") or "unknown")
        by_name[name] += 1
        if event.get("ok") is False:
            fail_n += 1
    n = len(tools)
    fail_rate = (fail_n / n) if n else None
    failed = bool(n >= _TOOL_MIN_N and fail_rate is not None and fail_rate > _TOOL_MAX_FAIL_RATE)
    detail = ""
    if failed:
        detail = f"tool.call failure rate {fail_rate:.2f} over 0.25 (n={n})"
    return {
        "n": n,
        "fail_n": fail_n,
        "fail_rate": fail_rate,
        "by_name": dict(by_name.most_common()),
        "failed": failed,
        "detail": detail,
    }


def _top_queries(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for event in events:
        raw = event.get("query")
        if not isinstance(raw, str) or not raw.strip():
            continue
        redacted, _n = redact_secrets(raw.strip())
        counts[redacted[:200]] += 1
    if not counts:
        return {
            "present": False,
            "message": "counts-only pack (no query text)",
            "top": [],
        }
    top = [{"query": q, "n": n} for q, n in counts.most_common(_TOP_QUERIES)]
    return {"present": True, "message": f"{len(counts)} distinct redacted queries", "top": top}
