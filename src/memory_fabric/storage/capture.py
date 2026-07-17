"""Capture reliability (ROADMAP Phase 3): make memory that writes itself.

Instruction-only capture fails silently — agents skip mid-session writes, context
compression erodes the rules, and clients that never load rules files run on tool
docstrings alone. This module is the safety net:

- ``capture_commit`` records each git commit as episodic memory with no agent
  cooperation and no LLM, so even a fully non-compliant agent leaves a trail the
  next Dream can consolidate.
- ``mark_session_start`` / ``mark_journal_written`` / ``guard_journal`` are the
  primitives a client Stop hook uses to turn "MANDATORY SESSION END" from a
  request into an enforced check.
- ``capture_stats`` surfaces whether capture is actually happening, locally
  (the no-telemetry guarantee stands).

All pure standard library. Everything degrades gracefully outside a git repo.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.paths import LOCAL_MEMORY_DIR, local_memory_dir, memory_store_dir
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import _should_skip_diff_path
from memory_fabric.storage.store import write_memory_store

# Provenance store path for passively captured commits. Kept separate from
# agent-written session journals (episodic/<date>) so the two never mix and
# review_status stays meaningful.
_COMMITS_PREFIX = "episodic/commits"

_SESSION_START_MARKER = "session_started_at"
_LAST_JOURNAL_MARKER = "last_journal_at"
_SKIPPED_COUNT_MARKER = "capture_skipped_count"

# Capture filter (opt out with `ai-memory capture --no-filter`): once client
# hooks guarantee a record per commit, every noise commit becomes permanent
# noise in episodic/, so merges, bot commits, skippable conventional-commit
# prefixes, and lockfile-only commits are skipped — audibly, never silently.
_MERGE_SUBJECT_PREFIXES = (
    "Merge branch ",
    "Merge pull request ",
    "Merge remote-tracking branch ",
)
# chore:, style:, ci: with optional (scope) and optional `!`; plus dependabot's
# build(deps): / build(deps-dev): — but not every build: commit, which can
# carry real knowledge.
_SKIPPABLE_SUBJECT_RE = re.compile(r"^(?:(?:chore|style|ci)(?:\([^)]*\))?!?:|build\(deps)", re.I)

# A commit that touches nothing but the memory directory is the memory system's
# own bookkeeping, not new project knowledge. Capturing it would write a fresh
# episodic record, re-dirtying the tree; the user then commits that, which
# triggers another capture — an endless commit loop that blocks a clean push
# (issue #5). Skipping memory-only commits breaks the recursion so a single
# follow-up commit reaches a clean tree.
_MEMORY_DIR_PREFIX = f"{LOCAL_MEMORY_DIR}/"


def _is_memory_only_path(path: str) -> bool:
    return path.replace("\\", "/").startswith(_MEMORY_DIR_PREFIX)


def _capture_skip_reason(
    subject: str, author: str, files: list[str], parent_count: int
) -> str | None:
    """Return why this commit should not be captured, or None to capture it."""
    if parent_count > 1 or subject.startswith(_MERGE_SUBJECT_PREFIXES):
        return "merge commit"
    if author.endswith("[bot]"):
        return f"bot author ({author})"
    if _SKIPPABLE_SUBJECT_RE.match(subject):
        return "skippable conventional-commit prefix"
    if files and all(_is_memory_only_path(f) for f in files):
        return "memory-store bookkeeping commit"
    if files and all(_should_skip_diff_path(f) for f in files):
        return "only lockfiles/generated files changed"
    return None


def _git(cwd: str, *args: str, timeout: float = 5.0) -> str | None:
    """Run a git command, returning stdout on success or None on any failure."""
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def _is_git_repo(cwd: str) -> bool:
    out = _git(cwd, "rev-parse", "--is-inside-work-tree")
    return bool(out and "true" in out.lower())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Passive capture: one episodic record per commit
# ---------------------------------------------------------------------------


def capture_commit(cwd: str, commit: str = "HEAD", apply_filter: bool = True) -> dict[str, Any]:
    """Record a single commit as episodic memory. Idempotent per commit hash.

    ``apply_filter=True`` (the default) skips noise commits — merges, ``[bot]``
    authors, skippable conventional-commit prefixes, lockfile-only changes —
    reporting ``skipped_reason`` and counting the skip in ``capture_stats``;
    pass ``apply_filter=False`` (CLI ``--no-filter``) to capture everything.

    Returns a dict with ``captured`` (whether a new record was written),
    ``commit`` (short hash), ``store_path``, ``skipped_reason``, ``redactions``,
    and ``warnings``. Never raises for expected conditions (not a repo, no
    commits, dup) — those are reported via ``warnings`` so the git hook can run
    ``|| true``.
    """
    result: dict[str, Any] = {
        "changed": False,
        "captured": False,
        "commit": None,
        "store_path": None,
        "skipped_reason": None,
        "redactions": 0,
        "warnings": [],
    }

    if not _is_git_repo(cwd):
        result["warnings"].append("Not a git repository; nothing to capture.")
        return result

    full_hash = (_git(cwd, "rev-parse", commit) or "").strip()
    if not full_hash:
        result["warnings"].append(f"Could not resolve commit: {commit}")
        return result
    short_hash = full_hash[:10]

    # subject / author-date (strict ISO) / author-name / parent hashes, one per line.
    meta = (_git(cwd, "show", "-s", "--format=%s%n%aI%n%an%n%P", full_hash) or "").splitlines()
    subject = meta[0].strip() if len(meta) > 0 and meta[0].strip() else "(no subject)"
    author_date = meta[1].strip() if len(meta) > 1 else ""
    author = meta[2].strip() if len(meta) > 2 else ""
    parent_count = len(meta[3].split()) if len(meta) > 3 else 0

    numstat = _git(cwd, "show", "--numstat", "--format=", full_hash) or ""
    files = [
        line.split("\t")[-1].strip()
        for line in numstat.splitlines()
        if line.strip() and "\t" in line
    ]

    if apply_filter:
        skip_reason = _capture_skip_reason(subject, author, files, parent_count)
        if skip_reason:
            _increment_skipped_count(cwd)
            result["commit"] = short_hash
            result["skipped_reason"] = skip_reason
            result["warnings"].append(
                f"Commit {short_hash} skipped by capture filter ({skip_reason}); "
                "use --no-filter to capture it anyway."
            )
            return result

    stat = (_git(cwd, "show", "--stat", "--format=", full_hash) or "").strip()

    date_str = (author_date[:10] if len(author_date) >= 10 else "") or datetime.now(UTC).strftime(
        "%Y-%m-%d"
    )
    store_path = f"{_COMMITS_PREFIX}/{date_str}"

    target = memory_store_dir(cwd) / "episodic" / "commits" / f"{date_str}.md"
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            existing = ""
        if short_hash in existing or full_hash in existing:
            result["commit"] = short_hash
            result["store_path"] = store_path
            result["warnings"].append(f"Commit {short_hash} already captured.")
            return result

    safe_subject, r_subj = redact_secrets(subject)
    redactions = r_subj

    file_lines = "\n".join(f"- `{f}`" for f in files[:50]) if files else "- (no files changed)"
    if len(files) > 50:
        file_lines += f"\n- …and {len(files) - 50} more"

    block_lines = [
        f"### commit `{short_hash}` — {safe_subject}",
        "",
        f"- when: {author_date or _now_iso()}",
        f"- author: {author}",
        "- source: passive-capture",
        "",
        "**Files:**",
        file_lines,
    ]
    if stat:
        safe_stat, r_stat = redact_secrets(stat)
        redactions += r_stat
        block_lines += ["", "```", safe_stat, "```"]
    block = "\n".join(block_lines)

    # Inject provenance frontmatter only when creating the file, so an agent or
    # Dream that later clears review_status is not overwritten on the next append.
    if target.exists():
        content = block
    else:
        provenance = {
            "source": "passive-capture",
            "review_status": "pending",
        }
        content = dump_frontmatter(provenance, block)

    write_result = write_memory_store(
        cwd,
        store_path=store_path,
        content=content,
        title=f"Commit Log — {date_str}",
        tags=["episodic", "passive-capture", "needs-review"],
        priority="low",
        mode="append",
    )

    result["changed"] = write_result["changed"]
    result["captured"] = write_result["changed"]
    result["commit"] = short_hash
    result["store_path"] = store_path
    result["redactions"] = redactions + write_result["redactions"]
    result["warnings"] = write_result["warnings"]
    return result


# ---------------------------------------------------------------------------
# Enforcement primitives: session markers + journal guard
# ---------------------------------------------------------------------------


def _private_dir(cwd: str) -> Path:
    priv = local_memory_dir(cwd) / "private"
    priv.mkdir(parents=True, exist_ok=True)
    return priv


def _read_marker(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    except (OSError, UnicodeDecodeError):
        return None


def _read_skipped_count(priv: Path) -> int:
    raw = _read_marker(priv / _SKIPPED_COUNT_MARKER)
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def _increment_skipped_count(cwd: str) -> None:
    """Count a filtered-out commit so `ai-memory status` shows filter activity."""
    with contextlib.suppress(OSError):
        priv = _private_dir(cwd)
        count = _read_skipped_count(priv) + 1
        (priv / _SKIPPED_COUNT_MARKER).write_text(f"{count}\n", encoding="utf-8")


def mark_session_start(cwd: str) -> dict[str, Any]:
    """Record the session start time (SessionStart hook). Overwrites any prior mark."""
    marker = _private_dir(cwd) / _SESSION_START_MARKER
    stamp = _now_iso()
    marker.write_text(stamp + "\n", encoding="utf-8")
    return {"marked_at": stamp, "path": str(marker)}


def mark_journal_written(cwd: str) -> None:
    """Record that a session journal was just written. Called by write_session_journal."""
    try:
        marker = _private_dir(cwd) / _LAST_JOURNAL_MARKER
        marker.write_text(_now_iso() + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001, S110 - marker plumbing must never break the journal write itself.
        pass


def guard_journal(cwd: str) -> dict[str, Any]:
    """Check whether a session journal was written since the session started.

    Used by a client Stop hook to enforce end-of-session journaling. Fails open
    (``ok=True``) when there is no session-start marker, so it never blocks a
    session that predates the marker plumbing or ran without a SessionStart hook.
    """
    priv = local_memory_dir(cwd) / "private"
    started = _read_marker(priv / _SESSION_START_MARKER)
    if not started:
        return {"ok": True, "reason": "No session-start marker; journaling not enforced."}

    try:
        started_at = datetime.fromisoformat(started)
    except ValueError:
        return {"ok": True, "reason": "Unreadable session-start marker; not enforcing."}

    journaled = _read_marker(priv / _LAST_JOURNAL_MARKER)
    if journaled:
        try:
            if datetime.fromisoformat(journaled) >= started_at:
                return {"ok": True, "reason": "Session already journaled."}
        except ValueError:
            pass

    return {
        "ok": False,
        "reason": (
            "No write_session_journal_tool call recorded this session. "
            "Call write_session_journal_tool to log what was accomplished before ending."
        ),
    }


# ---------------------------------------------------------------------------
# Capture stats (surfaced by `ai-memory status`)
# ---------------------------------------------------------------------------


def capture_stats(cwd: str) -> dict[str, Any]:
    """Local-only capture health: journals, passive commit captures, recent writes."""
    store_root = memory_store_dir(cwd)
    priv = local_memory_dir(cwd) / "private"

    commit_captures = 0
    commits_dir = store_root / "episodic" / "commits"
    if commits_dir.exists():
        for path in commits_dir.glob("*.md"):
            with contextlib.suppress(OSError, UnicodeDecodeError):
                commit_captures += path.read_text(encoding="utf-8").count("### commit ")

    journals = 0
    episodic_dir = store_root / "episodic"
    if episodic_dir.exists():
        journals = sum(1 for p in episodic_dir.glob("*.md") if p.is_file())

    memories_total = 0
    memories_last_7d = 0
    cutoff = datetime.now(UTC) - timedelta(days=7)
    if store_root.exists():
        for path in store_root.rglob("*.md"):
            if not path.is_file() or path.name == "index.md":
                continue
            memories_total += 1
            try:
                metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, FrontmatterError):
                continue
            lu = str(metadata.get("last_updated") or "")
            if lu:
                try:
                    lu_dt = datetime.fromisoformat(lu.replace("Z", "+00:00"))
                    if lu_dt.tzinfo is None:
                        lu_dt = lu_dt.replace(tzinfo=UTC)
                    if lu_dt >= cutoff:
                        memories_last_7d += 1
                except ValueError:
                    pass

    return {
        "last_journal_at": _read_marker(priv / _LAST_JOURNAL_MARKER),
        "session_started_at": _read_marker(priv / _SESSION_START_MARKER),
        "commit_captures": commit_captures,
        "commits_skipped": _read_skipped_count(priv),
        "episodic_files": journals,
        "memories_total": memories_total,
        "memories_last_7d": memories_last_7d,
    }
