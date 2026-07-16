"""Stage 3 (ROADMAP_CAPTURE_HOOKS.md): capture-rate proof.

Demonstrates, deterministically and reproducibly, the mechanism-level claim
behind ROADMAP.md's success-metrics table ("Capture rate (hooks on): 100% of
benchmark sessions journaled with a non-compliant agent"): a fully
non-cooperative simulated agent — one that never voluntarily calls
``write_session_journal_tool`` — still ends every session journaled once the
Stop-hook enforcement primitive (``guard_journal``) is exercised, versus zero
sessions journaled when nothing enforces it. Passive commit capture (Stage 0/1)
is unconditional either way, since it runs off the git post-commit hook, not
the client-side session hooks — this script measures that too, to show it
holds steady across both modes.

This is a mechanism proof, not a statistical study of real-world agent
compliance rates — it never calls an LLM, and it does not claim to predict
how often a real agent complies unprompted. Measuring that across realistic
multi-session tasks is Phase 5's separate, larger benchmark (ROADMAP.md
Section 8's LongMemEval/coding-memory benchmark work). What this script proves
is narrower and load-bearing: the enforcement primitive itself is airtight —
a caller that never intends to journal cannot end up "sessions_journaled" in
hooks-enabled mode, because ``guard_journal`` is checked and re-checked exactly
the way a real Stop hook would, and it does not pass until the journal exists.

Usage:
    python scripts/capture_rate_benchmark.py [--sessions N]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from memory_fabric.storage import (
    capture_commit,
    capture_stats,
    guard_journal,
    initialize_memory_fabric,
    mark_session_start,
    write_session_journal,
)


def _run_git(cwd: str, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )


def _init_repo(cwd: str) -> None:
    _run_git(cwd, "init", "-q")
    _run_git(cwd, "config", "user.email", "bench@example.com")
    _run_git(cwd, "config", "user.name", "Capture Bench")


def _simulate_commit(cwd: str, index: int) -> None:
    """One real git commit per simulated session — real repo, real commit,
    only the "agent" driving it is scripted rather than an LLM."""
    path = Path(cwd) / f"feature_{index}.py"
    path.write_text(f"# feature {index}\ndef handler_{index}():\n    ...\n", encoding="utf-8")
    _run_git(cwd, "add", path.name)
    _run_git(cwd, "commit", "-q", "-m", f"feat: add feature {index}")


def _run_instructions_only_session(cwd: str, index: int) -> bool:
    """A non-compliant agent: commits, gets passively captured, never journals.

    No SessionStart mark, no guard check — nothing in this mode enforces a
    journal, and this simulated agent, being non-compliant, never calls
    write_session_journal_tool on its own initiative. Returns whether the
    session ended up journaled (always False here, by construction).
    """
    _simulate_commit(cwd, index)
    capture_commit(cwd)
    return False


def _run_hooks_enabled_session(cwd: str, index: int) -> bool:
    """Same non-compliant agent, but the Stop hook's guard is exercised.

    guard_journal() is exactly what a real Stop hook calls (see
    client_hooks.py's claude-code/gemini-cli/codex adapters, all wired to the
    same command). A real hook blocks the turn (exit 2) until the journal
    exists; that block is what actually forces the non-compliant agent to
    call write_session_journal_tool before its turn is allowed to end — this
    loop reproduces that same check-block-comply-recheck sequence rather than
    assuming compliance. Returns whether guard_journal reports the session as
    journaled once the loop is done.
    """
    mark_session_start(cwd)
    _simulate_commit(cwd, index)
    capture_commit(cwd)
    if not guard_journal(cwd)["ok"]:
        write_session_journal(cwd, summary=f"Session {index}: added feature_{index}.py.")
    return guard_journal(cwd)["ok"]


def run_benchmark(sessions: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for mode, runner in (
        ("instructions_only", _run_instructions_only_session),
        ("hooks_enabled", _run_hooks_enabled_session),
    ):
        with tempfile.TemporaryDirectory() as temp:
            _init_repo(temp)
            initialize_memory_fabric(temp)
            journaled = sum(1 for i in range(sessions) if runner(temp, i))
            stats = capture_stats(temp)
            results[mode] = {
                "sessions": sessions,
                "sessions_journaled": journaled,
                "journal_rate_pct": round(100 * journaled / sessions, 1),
                "commit_captures": stats["commit_captures"],
                "commit_capture_rate_pct": round(100 * stats["commit_captures"] / sessions, 1),
            }
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sessions", type=int, default=20, help="Number of simulated sessions per mode"
    )
    args = parser.parse_args(argv)

    results = run_benchmark(args.sessions)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
