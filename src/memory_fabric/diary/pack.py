"""Build a shareable local field-diary pack. Nothing is transmitted."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_fabric.contracts import DiaryPackResult
from memory_fabric.diary.consent import diary_dir, field_packs_dir
from memory_fabric.security import redact_secrets
from memory_fabric.version import __version__

_PACK_SCHEMA = 1
_QUERY_MAX = 200
_ABS_PATH = re.compile(
    r"(?i)(?:[A-Z]:[\\/][^\s\"']+|\\\\[^\s\"']+|/(?:Users|home|tmp|var|opt|etc)/[^\s\"']+)"
)

_ENVELOPE = frozenset(
    {
        "schema_version",
        "ts",
        "fabric_version",
        "install_kind",
        "surface",
        "client",
        "project_id",
        "os",
        "python",
        "event",
    }
)

_BY_EVENT: dict[str, frozenset[str]] = {
    "context.pack": frozenset(
        {
            "token_budget",
            "estimated_tokens",
            "budget_fit",
            "startup_mode",
            "index_used",
            "query_present",
            "query_len",
            "tokens_by_role",
            "included_by_role",
            "omitted_by_role",
            "included_by_priority",
            "omitted_by_priority",
            "largest_included_tokens",
            "largest_included_role",
            "truncated_n",
            "warning_codes",
            "ms",
            "posture_slot",
            "query",
        }
    ),
    "search.run": frozenset(
        {
            "backend",
            "hit_n",
            "ms",
            "query_len",
            "token_n",
            "content_token_n",
            "candidate_n",
            "phrase_hit",
            "top_hit_role",
            "top_hit_score",
            "query",
        }
    ),
    "tool.call": frozenset(
        {
            "name",
            "ms",
            "ok",
            "error_type",
            "error_code",
            "mode",
            "apply",
            "changed",
            "redactions",
            "duplicates_found",
        }
    ),
    "dream.result": frozenset(
        {
            "name",
            "ms",
            "ok",
            "error_type",
            "error_code",
            "mode",
            "apply",
            "changed",
            "redactions",
            "duplicates_found",
        }
    ),
    "cli.command": frozenset({"name", "ms", "ok", "error_type"}),
    "checkpoint.session_start": frozenset(),
    "journal.written": frozenset(),
    "checkpoint.session_end": frozenset({"journaled", "context_loaded"}),
    "limitation": frozenset({"code"}),
    "checkpoint.manual": frozenset(
        {
            "files_by_role",
            "memories_total",
            "largest_file_tokens",
            "largest_file_role",
            "has_retrieval_fixture",
            "eval_score",
            "retrieval_quality",
            "commit_captures",
            "memories_last_7d",
            "startup_mode",
        }
    ),
}

_DROP_KEYS = frozenset(
    {
        "text",
        "content",
        "body",
        "path",
        "cwd",
        "snippet",
        "included_sections",
        "omitted_sections",
    }
)


def build_pack(
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    out: str | Path | None = None,
    source_dir: str | Path | None = None,
) -> DiaryPackResult:
    """Filter and scrub diary JSONL into a shareable folder under field-packs/."""
    warnings: list[str] = []
    root = Path(source_dir) if source_dir else diary_dir()
    events, load_warnings = _load_events(root, from_date=from_date, to_date=to_date)
    warnings.extend(load_warnings)

    packed: list[dict[str, Any]] = []
    queries_included = False
    for raw in events:
        cleaned = _allowlist_event(raw)
        if cleaned is None:
            continue
        if "query" in cleaned:
            queries_included = True
        packed.append(cleaned)

    out_dir = Path(out) if out else _default_out_dir()
    if out_dir.exists():
        _rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    events_path = out_dir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as handle:
        for event in packed:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    project_ids = sorted({str(e.get("project_id") or "unknown") for e in packed})
    summary = _summarize(packed)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    packed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "schema_version": _PACK_SCHEMA,
        "packed_at": packed_at,
        "fabric_version": __version__,
        "from": from_date,
        "to": to_date,
        "event_n": len(packed),
        "project_n": len(project_ids),
        "queries_included": queries_included,
        "warnings": warnings,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(out_dir),
        "event_n": len(packed),
        "project_n": len(project_ids),
        "queries_included": queries_included,
        "from": from_date,
        "to": to_date,
        "warnings": warnings,
        "message": (
            f"Packed {len(packed)} events into {out_dir}. "
            "Copy this folder yourself — nothing was sent."
        ),
    }


def _default_out_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return field_packs_dir() / f"field-{stamp}"


def _load_events(
    root: Path,
    *,
    from_date: str | None,
    to_date: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    events: list[dict[str, Any]] = []
    if not root.is_dir():
        warnings.append(f"diary directory missing: {root}")
        return events, warnings
    files = sorted(root.glob("events-*.jsonl"))
    if not files:
        warnings.append("no events-*.jsonl files found")
        return events, warnings
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
            if not isinstance(payload, dict):
                warnings.append(f"skipped non-object line {path.name}:{line_no}")
                continue
            ts = str(payload.get("ts") or "")
            day = ts[:10] if len(ts) >= 10 else ""
            if from_date and (not day or day < from_date):
                continue
            if to_date and (not day or day > to_date):
                continue
            events.append(payload)
    return events, warnings


def _allowlist_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    event_name = str(raw.get("event") or "")
    if event_name not in _BY_EVENT:
        return None
    allowed = _ENVELOPE | _BY_EVENT[event_name]
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _DROP_KEYS or key not in allowed:
            continue
        out[key] = _scrub_value(key, value)
    if "event" not in out:
        out["event"] = event_name
    return out


def _scrub_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _scrub_value(str(k), v) for k, v in value.items() if k not in _DROP_KEYS}
    if isinstance(value, list):
        return [_scrub_value(key, item) for item in value]
    if isinstance(value, str):
        text, _count = redact_secrets(value)
        text = _ABS_PATH.sub("[path]", text)
        if key == "query":
            text = text[:_QUERY_MAX]
        return text
    return value


def _summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_project: dict[str, dict[str, Any]] = {}
    for event in events:
        pid = str(event.get("project_id") or "unknown")
        bucket = by_project.setdefault(
            pid,
            {
                "event_n": 0,
                "by_event": Counter(),
                "context_pack_n": 0,
                "tool_call_n": 0,
                "tool_fail_n": 0,
                "queries_n": 0,
            },
        )
        name = str(event.get("event") or "unknown")
        bucket["event_n"] += 1
        bucket["by_event"][name] += 1
        if name == "context.pack":
            bucket["context_pack_n"] += 1
        if name in {"tool.call", "dream.result"}:
            bucket["tool_call_n"] += 1
            if event.get("ok") is False:
                bucket["tool_fail_n"] += 1
        if event.get("query"):
            bucket["queries_n"] += 1
    projects = {}
    for pid, bucket in by_project.items():
        projects[pid] = {
            "event_n": bucket["event_n"],
            "by_event": dict(bucket["by_event"]),
            "context_pack_n": bucket["context_pack_n"],
            "tool_call_n": bucket["tool_call_n"],
            "tool_fail_n": bucket["tool_fail_n"],
            "queries_n": bucket["queries_n"],
        }
    return {"schema_version": _PACK_SCHEMA, "projects": projects}


def _rmtree(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()
        return
    for child in path.iterdir():
        _rmtree(child)
    path.rmdir()
