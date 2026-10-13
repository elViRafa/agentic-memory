"""Human consent for the local field diary.

Source of truth: ``get_global_root() / diary.json`` — a user-app-dir file,
never a project file. Agents cannot write here through MCP store tools.

``MEMORY_FABRIC_DIARY=0`` is a kill switch only. ``=1`` does not approve.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from memory_fabric.contracts import DiaryActionResult, DiaryStatusResult
from memory_fabric.locking import locked_file
from memory_fabric.paths import get_global_root, local_memory_dir, validate_cwd
from memory_fabric.templates import now_iso
from memory_fabric.version import __version__

LEVELS = ("counts", "counts+queries")
CONSENT_NAME = "diary.json"
DIARY_DIR_NAME = "diary"
PACKS_DIR_NAME = "field-packs"
MUTE_NAME = "diary-mute"
SCOPE = "local-copy-only"
KILL_SWITCH_ENV = "MEMORY_FABRIC_DIARY"

APPROVE_NOTICE = """\
Field diary is OFF by default. Approving records operational counts on THIS
machine only. This is not the session journal.

Will record: tool names, timings, budget composition, role histograms, errors,
limitation codes, session outcomes.

Will NOT record: memory-store contents, tool arguments, absolute paths, or
query text (unless you pass --level counts+queries).

Will NOT send anything to the internet. Later, `ai-memory diary pack` builds a
folder you can copy yourself. Nothing is transmitted.
"""

_consent_mtime: float | None = None
_consent_cache: dict[str, Any] | None = None


def consent_path() -> Path:
    return get_global_root() / CONSENT_NAME


def diary_dir() -> Path:
    return get_global_root() / DIARY_DIR_NAME


def field_packs_dir() -> Path:
    return get_global_root() / PACKS_DIR_NAME


def mute_path(cwd: str | Path) -> Path:
    return local_memory_dir(cwd) / "private" / MUTE_NAME


def invalidate_cache() -> None:
    global _consent_mtime, _consent_cache
    _consent_mtime = None
    _consent_cache = None


def kill_switch_on(env: dict[str, str] | None = None) -> bool:
    environment = env if env is not None else os.environ
    raw = (environment.get(KILL_SWITCH_ENV) or "").strip().lower()
    return raw in {"0", "false", "no", "off"}


def read_consent() -> dict[str, Any] | None:
    """Return the on-disk consent dict, or None if missing/unreadable."""
    global _consent_mtime, _consent_cache
    path = consent_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _consent_mtime = None
        _consent_cache = None
        return None
    if _consent_cache is not None and _consent_mtime == mtime:
        return _consent_cache
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _consent_mtime = None
        _consent_cache = None
        return None
    if not isinstance(data, dict):
        return None
    _consent_mtime = mtime
    _consent_cache = data
    return data


def is_muted(cwd: str | Path | None) -> bool:
    if cwd is None:
        return False
    try:
        return mute_path(cwd).is_file()
    except OSError:
        return False


def is_approved(cwd: str | Path | None = None) -> bool:
    """True only when a human approved, the kill switch is off, and cwd is not muted."""
    if kill_switch_on():
        return False
    if is_muted(cwd):
        return False
    data = read_consent()
    if not data:
        return False
    return bool(data.get("approved"))


def _write_consent(payload: dict[str, Any]) -> Path:
    path = consent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with locked_file(path):
        path.write_text(text, encoding="utf-8")
    invalidate_cache()
    return path


def approve(level: str = "counts", *, confirmed: bool) -> DiaryActionResult:
    """Write diary.json. Refuses unless ``confirmed`` is True (CLI --yes or TTY yes)."""
    warnings: list[str] = []
    if level not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")
    if not confirmed:
        return {
            "changed": False,
            "approved": False,
            "level": None,
            "path": str(consent_path()),
            "message": "Approval requires an interactive yes or --yes. Nothing was written.",
            "warnings": warnings,
        }
    existing = read_consent() or {}
    payload = {
        "schema_version": 1,
        "approved": True,
        "level": level,
        "approved_at": existing.get("approved_at") or now_iso(),
        "fabric_version": __version__,
        "scope": SCOPE,
    }
    if existing.get("approved") and existing.get("level") == level:
        return {
            "changed": False,
            "approved": True,
            "level": level,
            "path": str(consent_path()),
            "message": f"Field diary already approved at level {level}.",
            "warnings": warnings,
        }
    if existing.get("approved"):
        payload["approved_at"] = existing.get("approved_at") or now_iso()
    path = _write_consent(payload)
    diary_dir().mkdir(parents=True, exist_ok=True)
    approval_copy = diary_dir() / "approval-copy.json"
    with locked_file(approval_copy):
        approval_copy.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return {
        "changed": True,
        "approved": True,
        "level": level,
        "path": str(path),
        "message": (
            f"Field diary approved at level {level}. "
            "Nothing will be sent. Revoke with `ai-memory diary revoke`."
        ),
        "warnings": warnings,
    }


def revoke() -> DiaryActionResult:
    existing = read_consent()
    path = consent_path()
    if not existing or not existing.get("approved"):
        return {
            "changed": False,
            "approved": False,
            "level": (existing or {}).get("level"),
            "path": str(path),
            "message": "Field diary is already off.",
            "warnings": [],
        }
    payload = {
        **existing,
        "approved": False,
        "revoked_at": now_iso(),
        "fabric_version": __version__,
        "scope": SCOPE,
    }
    _write_consent(payload)
    return {
        "changed": True,
        "approved": False,
        "level": payload.get("level"),
        "path": str(path),
        "message": "Field diary revoked. Existing files were kept; `ai-memory diary wipe` deletes them.",
        "warnings": [],
    }


def mute(cwd: str) -> DiaryActionResult:
    safe = validate_cwd(cwd)
    memory_dir = local_memory_dir(safe)
    if not memory_dir.is_dir():
        return {
            "changed": False,
            "approved": is_approved(safe),
            "level": (read_consent() or {}).get("level"),
            "path": str(mute_path(safe)),
            "message": "No .ai-memory/ here. Run `ai-memory init` before muting this project.",
            "warnings": ["memory directory missing"],
        }
    target = mute_path(safe)
    if target.is_file():
        return {
            "changed": False,
            "approved": False,
            "level": (read_consent() or {}).get("level"),
            "path": str(target),
            "message": "This project is already muted.",
            "warnings": [],
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("muted\n", encoding="utf-8")
    return {
        "changed": True,
        "approved": False,
        "level": (read_consent() or {}).get("level"),
        "path": str(target),
        "message": "This project is muted. The field diary will not record here.",
        "warnings": [],
    }


def unmute(cwd: str) -> DiaryActionResult:
    safe = validate_cwd(cwd)
    target = mute_path(safe)
    if not target.is_file():
        return {
            "changed": False,
            "approved": is_approved(safe),
            "level": (read_consent() or {}).get("level"),
            "path": str(target),
            "message": "This project is not muted.",
            "warnings": [],
        }
    target.unlink()
    return {
        "changed": True,
        "approved": is_approved(safe),
        "level": (read_consent() or {}).get("level"),
        "path": str(target),
        "message": "Mute removed. Global approval applies to this project again.",
        "warnings": [],
    }


def _events_today_count() -> int:
    today = now_iso()[:10]
    path = diary_dir() / f"events-{today}.jsonl"
    if not path.is_file():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _latest_pack_name() -> str | None:
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
    return packs[0].name


def status(cwd: str | None = None) -> DiaryStatusResult:
    data = read_consent()
    safe_cwd: str | None = None
    if cwd:
        try:
            safe_cwd = str(validate_cwd(cwd))
        except ValueError:
            safe_cwd = None
    approved = is_approved(safe_cwd)
    return {
        "approved": approved,
        "level": (data or {}).get("level") if data else None,
        "approved_at": (data or {}).get("approved_at") if data else None,
        "scope": SCOPE,
        "diary_dir": str(diary_dir()),
        "consent_path": str(consent_path()),
        "events_today": _events_today_count(),
        "last_pack": _latest_pack_name(),
        "muted": is_muted(safe_cwd),
        "kill_switch": kill_switch_on(),
        "warnings": [],
    }


def wipe(*, confirmed: bool) -> DiaryActionResult:
    if not confirmed:
        return {
            "changed": False,
            "approved": is_approved(),
            "level": (read_consent() or {}).get("level"),
            "path": str(diary_dir()),
            "message": "Wipe requires an interactive yes or --yes. Nothing was deleted.",
            "warnings": [],
        }
    removed: list[str] = []
    warnings: list[str] = []
    for root in (diary_dir(), field_packs_dir()):
        if not root.exists():
            continue
        try:
            _rmtree(root)
            removed.append(str(root))
        except OSError as exc:
            warnings.append(f"could not remove {root}: {exc}")
    consent = consent_path()
    if consent.exists():
        try:
            consent.unlink()
            removed.append(str(consent))
        except OSError as exc:
            warnings.append(f"could not remove {consent}: {exc}")
    invalidate_cache()
    return {
        "changed": bool(removed),
        "approved": False,
        "level": None,
        "path": str(get_global_root()),
        "message": ("Field diary wiped: " + ", ".join(removed) if removed else "Nothing to wipe."),
        "warnings": warnings,
    }


def _rmtree(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()
        return
    for child in path.iterdir():
        _rmtree(child)
    path.rmdir()
