"""Guideline canary: ask a cheap model a known-contradictory convention.

Opt-in. Skipped cleanly when no LLM provider is configured. Catches
instruction-load failures that ``sync-agents --check`` cannot see.
"""

from __future__ import annotations

import os
from typing import Any


async def run_guideline_canary(cwd: str, prompt: str | None = None) -> dict[str, Any]:
    """Return ``{skipped, passed, answer, expected, warnings}``."""
    from memory_fabric.storage.finalize import _is_llm_ready

    expected = "test_*.py"
    question = prompt or (
        "In this project, what should a new Python test file be named? "
        "Answer with only the glob pattern, either test_*.py or tests_*.py."
    )
    if not _is_llm_ready():
        return {
            "skipped": True,
            "passed": True,
            "answer": "",
            "expected": expected,
            "warnings": ["No LLM provider configured; guideline canary skipped."],
        }
    from memory_fabric.llm import call_llm

    answer = await call_llm(
        question,
        "Answer with only a file-name glob. Do not explain.",
        None,
    )
    passed = "test_" in answer and "tests_" not in answer.replace("test_", "")
    # Accept test_*.py / test_foo.py; reject tests_*.py.
    passed = "test_*.py" in answer.replace(" ", "") or (
        "test_" in answer and "tests_" not in answer
    )
    return {
        "skipped": False,
        "passed": passed,
        "answer": answer.strip(),
        "expected": expected,
        "warnings": [] if passed else [f"Canary expected {expected}, model said: {answer!r}"],
    }


def canary_provider_configured() -> bool:
    return bool(os.environ.get("MEMORY_FABRIC_LLM_PROVIDER"))
