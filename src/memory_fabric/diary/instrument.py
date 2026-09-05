"""Fail-open record helpers for the product boundary.

Imported lazily from packer/search/hooks so a diary bug cannot break them.
"""

from __future__ import annotations

import functools
import hashlib
import platform
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from memory_fabric.diary.consent import is_approved, read_consent
from memory_fabric.diary.recorder import record
from memory_fabric.diary.roles import classify_role
from memory_fabric.paths import local_memory_dir
from memory_fabric.security import redact_secrets
from memory_fabric.version import __version__

_CLIENTS = frozenset({"cursor", "claude-code", "codex", "gemini-cli", "vscode", "cli", "unknown"})
_LAST_CONTEXT_MARKER = "last_context_at"
_DIARY_CLIENT_MARKER = "diary_client"


def install_kind() -> str:
    try:
        import memory_fabric

        root = Path(memory_fabric.__file__).resolve().parent
        if root.parent.name == "src" and (root.parent.parent / "pyproject.toml").is_file():
            return "editable"
    except (OSError, TypeError):
        pass
    return "pip"


def project_id(cwd: str | None) -> str:
    if not cwd:
        return "unknown"
    try:
        resolved = str(Path(cwd).expanduser().resolve())
    except OSError:
        resolved = str(cwd)
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def envelope(*, cwd: str | None, surface: str, client: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fabric_version": __version__,
        "install_kind": install_kind(),
        "surface": surface,
        "client": _normalize_client(client) or _read_client(cwd),
        "project_id": project_id(cwd),
        "os": platform.system(),
        "python": platform.python_version(),
    }


def _normalize_client(client: str | None) -> str | None:
    if not client:
        return None
    value = client.strip().lower()
    return value if value in _CLIENTS else "unknown"


def _private(cwd: str) -> Path:
    return local_memory_dir(cwd) / "private"


def _write_marker(cwd: str, name: str, value: str) -> None:
    try:
        path = _private(cwd) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")
    except OSError:
        return


def _read_marker(cwd: str | None, name: str) -> str | None:
    if not cwd:
        return None
    try:
        text = (_private(cwd) / name).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _read_client(cwd: str | None) -> str:
    return _normalize_client(_read_marker(cwd, _DIARY_CLIENT_MARKER)) or "unknown"


def _consent_level() -> str:
    data = read_consent() or {}
    level = str(data.get("level") or "counts")
    return level if level in {"counts", "counts+queries"} else "counts"


def record_context_pack(
    cwd: str,
    bundle: Mapping[str, Any],
    *,
    query: str | None = None,
    ms: float | None = None,
    surface: str = "core",
) -> None:
    if not is_approved(cwd):
        return
    stats = dict(bundle.get("pack_stats") or {})
    event: dict[str, Any] = {
        **envelope(cwd=cwd, surface=surface),
        "event": "context.pack",
        **stats,
    }
    if ms is not None:
        event["ms"] = round(ms, 3)
    if _consent_level() == "counts+queries" and query:
        redacted, _count = redact_secrets(query)
        event["query"] = redacted
    record(event, cwd=cwd)
    from memory_fabric.templates import now_iso

    _write_marker(cwd, _LAST_CONTEXT_MARKER, now_iso())


def record_search_run(
    cwd: str,
    results: Sequence[Mapping[str, Any]],
    *,
    query: str,
    ms: float,
    surface: str = "core",
    backend: str | None = None,
) -> None:
    if not is_approved(cwd):
        return
    top_role = None
    top_score = None
    if results:
        top = results[0]
        top_role = classify_role(str(top.get("section") or top.get("path") or ""))
        score = top.get("score")
        if isinstance(score, (int, float)):
            top_score = float(score)
    resolved_backend = backend if backend else ""
    if not resolved_backend and results:
        resolved_backend = str(results[0].get("backend") or "")
    event: dict[str, Any] = {
        **envelope(cwd=cwd, surface=surface),
        "event": "search.run",
        "backend": resolved_backend,
        "hit_n": len(results),
        "ms": round(ms, 3),
        "query_len": len(query or ""),
        "top_hit_role": top_role,
        "top_hit_score": top_score,
    }
    if _consent_level() == "counts+queries" and query:
        redacted, _count = redact_secrets(query)
        event["query"] = redacted
    record(event, cwd=cwd)


def record_tool_call(
    name: str,
    cwd: str | None,
    *,
    ms: float,
    ok: bool,
    error_type: str | None = None,
    extra: dict[str, Any] | None = None,
    surface: str = "mcp",
) -> None:
    if not is_approved(cwd):
        return
    event: dict[str, Any] = {
        **envelope(cwd=cwd, surface=surface),
        "event": "tool.call",
        "name": name,
        "ms": round(ms, 3),
        "ok": ok,
    }
    if error_type:
        event["error_type"] = error_type
    if extra:
        event.update(extra)
    record(event, cwd=cwd)


def record_cli_command(
    command: str,
    cwd: str | None,
    *,
    ms: float,
    ok: bool,
    error_type: str | None = None,
) -> None:
    if command == "diary":
        return
    if not is_approved(cwd):
        return
    record(
        {
            **envelope(cwd=cwd, surface="cli", client="cli"),
            "event": "cli.command",
            "name": command,
            "ms": round(ms, 3),
            "ok": ok,
            **({"error_type": error_type} if error_type else {}),
        },
        cwd=cwd,
    )


def record_session_start(cwd: str, *, client: str | None = None) -> None:
    if client:
        _write_marker(cwd, _DIARY_CLIENT_MARKER, _normalize_client(client) or "unknown")
    if not is_approved(cwd):
        return
    record(
        {
            **envelope(cwd=cwd, surface="hook", client=client),
            "event": "checkpoint.session_start",
        },
        cwd=cwd,
    )


def record_session_end(
    cwd: str,
    *,
    journaled: bool,
    surface: str = "core",
) -> None:
    if not is_approved(cwd):
        return
    context_loaded = _read_marker(cwd, _LAST_CONTEXT_MARKER) is not None
    record(
        {
            **envelope(cwd=cwd, surface=surface),
            "event": "checkpoint.session_end",
            "journaled": journaled,
            "context_loaded": context_loaded,
        },
        cwd=cwd,
    )


def record_limitation(cwd: str | None, code: str, *, surface: str = "core") -> None:
    if not is_approved(cwd):
        return
    record(
        {
            **envelope(cwd=cwd, surface=surface),
            "event": "limitation",
            "code": code,
        },
        cwd=cwd,
    )


def wrap_mcp_tool(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Preserve the original signature so FastMCP still builds the same schema."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        if _is_async(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await _call_recorded(name, fn, args, kwargs, is_async=True)

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return _call_recorded(name, fn, args, kwargs, is_async=False)

        return wrapper

    return decorate


def _is_async(fn: Callable[..., Any]) -> bool:
    import inspect

    return inspect.iscoroutinefunction(fn)


def _call_recorded(
    name: str,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    is_async: bool,
) -> Any:
    cwd = _extract_cwd(args, kwargs)
    started = time.perf_counter()
    if is_async:
        return _call_recorded_async(name, fn, args, kwargs, cwd, started)
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        record_tool_call(
            name,
            cwd,
            ms=(time.perf_counter() - started) * 1000,
            ok=False,
            error_type=type(exc).__name__,
        )
        raise
    record_tool_call(name, cwd, ms=(time.perf_counter() - started) * 1000, ok=True)
    return result


async def _call_recorded_async(
    name: str,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    cwd: str | None,
    started: float,
) -> Any:
    try:
        result = await fn(*args, **kwargs)
    except Exception as exc:
        record_tool_call(
            name,
            cwd,
            ms=(time.perf_counter() - started) * 1000,
            ok=False,
            error_type=type(exc).__name__,
        )
        raise
    extra: dict[str, Any] = {}
    if isinstance(result, dict) and "mode" in result and name.startswith("dream"):
        extra = {
            "event": "dream.result",
            "mode": result.get("mode"),
            "apply": result.get("apply"),
            "changed": result.get("changed"),
            "redactions": result.get("redactions"),
        }
        consolidation = result.get("consolidation") or {}
        if isinstance(consolidation, dict):
            extra["duplicates_found"] = consolidation.get("duplicates_found")
    record_tool_call(
        name, cwd, ms=(time.perf_counter() - started) * 1000, ok=True, extra=extra or None
    )
    return result


def _extract_cwd(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    cwd_value = kwargs.get("cwd")
    if cwd_value:
        return str(cwd_value)
    if args:
        first = args[0]
        if isinstance(first, str):
            return first
    return None


def store_shape(cwd: str) -> dict[str, Any]:
    """Cheap store histogram for a manual checkpoint. Paths never leave."""
    from memory_fabric.paths import memory_store_dir
    from memory_fabric.storage._shared import estimate_tokens

    root = memory_store_dir(cwd)
    files_by_role: dict[str, int] = {}
    largest_tokens = 0
    largest_role: str | None = None
    total = 0
    if root.is_dir():
        for path in root.rglob("*.md"):
            if not path.is_file() or path.name == "index.md":
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            role = classify_role("store/" + relative)
            files_by_role[role] = files_by_role.get(role, 0) + 1
            total += 1
            try:
                tokens = estimate_tokens(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if tokens > largest_tokens:
                largest_tokens = tokens
                largest_role = role
    evals = local_memory_dir(cwd) / "evals" / "retrieval.yaml"
    latest = local_memory_dir(cwd) / "evals" / "latest.json"
    eval_score = None
    retrieval_quality = "skipped"
    if latest.is_file():
        try:
            import json

            payload = json.loads(latest.read_text(encoding="utf-8"))
            eval_score = payload.get("score")
            for category in payload.get("categories") or []:
                if category.get("name") == "retrieval_quality":
                    retrieval_quality = category.get("status") or "scored"
        except (OSError, ValueError, TypeError):
            pass
    return {
        "files_by_role": files_by_role,
        "memories_total": total,
        "largest_file_tokens": largest_tokens,
        "largest_file_role": largest_role,
        "has_retrieval_fixture": evals.is_file(),
        "eval_score": eval_score,
        "retrieval_quality": retrieval_quality,
    }


def write_manual_checkpoint(cwd: str) -> dict[str, Any]:
    if not is_approved(cwd):
        return {"recorded": False, "reason": "field diary is off"}
    import os

    from memory_fabric.storage.capture import capture_stats

    shape = store_shape(cwd)
    capture = capture_stats(cwd)
    event = {
        **envelope(cwd=cwd, surface="cli", client="cli"),
        "event": "checkpoint.manual",
        **shape,
        "commit_captures": capture.get("commit_captures"),
        "memories_last_7d": capture.get("memories_last_7d"),
        "startup_mode": os.environ.get("MEMORY_FABRIC_STARTUP_MODE") or "maps",
    }
    record(event, cwd=cwd)
    return {
        "recorded": True,
        "event": "checkpoint.manual",
        "memories_total": shape["memories_total"],
    }
