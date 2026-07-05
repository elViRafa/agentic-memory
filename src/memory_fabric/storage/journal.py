"""Episodic memory: a dated, append-only log of what happened in a session."""

from __future__ import annotations

from datetime import datetime, timezone

from memory_fabric.contracts import EpisodicJournalResult
from memory_fabric.security import redact_secrets
from memory_fabric.storage.store import write_memory_store


def write_session_journal(
    cwd: str,
    summary: str,
    key_decisions: list[str] | None = None,
    files_changed: list[str] | None = None,
    session_label: str | None = None,
) -> EpisodicJournalResult:
    """Append a timestamped session journal entry to the episodic memory store.

    This implements the Episodic Memory tier — a structured log of "what happened
    in this session" that agents can use to build temporal awareness.

    Journal entries are written to ``episodic/YYYY-MM-DD`` store paths and
    accumulate as append-mode Markdown. Dreaming's light mode consolidates
    entries older than 7 days into monthly summaries.

    Args:
        cwd:            Project root (same as all other tools).
        summary:        2-4 sentence summary of what was accomplished this session.
        key_decisions:  Optional list of key decisions or architecture choices made.
        files_changed:  Optional list of files created or significantly modified.
        session_label:  Optional short label for this session (e.g. "auth-refactor").
                        If omitted, the ISO timestamp is used.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M UTC")
    store_path = f"episodic/{date_str}"

    sanitized_summary, redactions_s = redact_secrets(summary or "")
    redactions = redactions_s
    warnings: list[str] = []
    if redactions_s:
        warnings.append("Detected and redacted secrets in summary.")

    label = session_label.strip() if session_label else time_str

    # Build the journal entry block
    lines: list[str] = [f"## {label}"]
    lines.append("")
    lines.append(sanitized_summary.strip())

    if key_decisions:
        lines.append("")
        lines.append("**Key decisions:**")
        for decision in key_decisions:
            sanitized_dec, r = redact_secrets(str(decision))
            redactions += r
            lines.append(f"- {sanitized_dec.strip()}")

    if files_changed:
        lines.append("")
        lines.append("**Files changed:**")
        for f in files_changed:
            lines.append(f"- `{f}`")

    entry_content = "\n".join(lines)

    # Use write_memory_store in append mode so multiple sessions on the same
    # day accumulate in a single dated file.
    result = write_memory_store(
        cwd,
        store_path=store_path,
        content=entry_content,
        title=f"Episodic Journal — {date_str}",
        tags=["episodic", "session-journal"],
        priority="low",
        mode="append",
    )

    return {
        "changed": result["changed"],
        "store_path": store_path,
        "path": result["path"],
        "date": date_str,
        "redactions": redactions + result["redactions"],
        "warnings": warnings + result["warnings"],
    }
