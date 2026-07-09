"""Failure memory: error -> fix pairs, deduplicated by normalized error signature."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.storage import initialize_memory_fabric, write_failure_memory
from memory_fabric.storage.failures import _normalize_error, _slug_for


class NormalizationTests(unittest.TestCase):
    def test_paths_and_numbers_are_stripped(self) -> None:
        a = _normalize_error("TypeError at /home/user/src/auth.py:42 in login()")
        b = _normalize_error("TypeError at /home/user/src/auth.py:99 in login()")
        self.assertEqual(a, b)

    def test_windows_paths_are_stripped(self) -> None:
        a = _normalize_error(r"Error in C:\Users\dev\app.py line 10")
        b = _normalize_error(r"Error in C:\Users\dev\app.py line 20")
        self.assertEqual(a, b)

    def test_different_errors_produce_different_slugs(self) -> None:
        self.assertNotEqual(
            _slug_for(_normalize_error("KeyError: 'foo'")),
            _slug_for(_normalize_error("ValueError: bad input")),
        )

    def test_quoted_literals_are_masked(self) -> None:
        a = _normalize_error("ValueError: Invalid isoformat string: '2026/07/20'")
        b = _normalize_error("ValueError: Invalid isoformat string: '07/15/2026'")
        self.assertEqual(a, b)
        self.assertIn("<val>", a)

    def test_hex_ids_are_masked(self) -> None:
        a = _normalize_error("Stale object 0xdeadbeef in cache for commit a1b2c3d4e5f6a7b8")
        b = _normalize_error("Stale object 0xfeedface in cache for commit 9f8e7d6c5b4a3210")
        self.assertEqual(a, b)


class WriteFailureMemoryTests(unittest.TestCase):
    def test_first_occurrence_creates_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_failure_memory(
                temp,
                error_summary="KeyError: 'user_id' in handlers.py:12",
                fix_summary="Added default value for missing user_id.",
            )
            self.assertTrue(result["changed"])

            failures_dir = Path(temp) / ".ai-memory" / "memory-store" / "failures"
            files = list(failures_dir.glob("*.md"))
            self.assertEqual(len(files), 1)
            metadata, body = parse_frontmatter(files[0].read_text(encoding="utf-8"))
            # Memory Fabric's minimal frontmatter parser doesn't type numbers —
            # they round-trip as strings, same as every other numeric field.
            self.assertEqual(metadata.get("occurrences"), "1")
            self.assertIn("failure", metadata.get("tags", []))
            self.assertIn("KeyError", body)
            self.assertIn("Added default value", body)

    def test_repeat_error_increments_occurrences_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_failure_memory(
                temp,
                error_summary="KeyError: 'user_id' in handlers.py:12",
                fix_summary="Added default value.",
            )
            result2 = write_failure_memory(
                temp,
                error_summary="KeyError: 'user_id' in handlers.py:87",
                fix_summary="Added default value again elsewhere.",
            )

            self.assertTrue(any("occurred 2 times" in w for w in result2["warnings"]))

            failures_dir = Path(temp) / ".ai-memory" / "memory-store" / "failures"
            files = list(failures_dir.glob("*.md"))
            self.assertEqual(len(files), 1, "same normalized error must not fragment into 2 files")
            metadata, body = parse_frontmatter(files[0].read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("occurrences"), "2")
            self.assertIn("Occurrence 1", body)
            self.assertIn("Occurrence 2", body)

    def test_different_errors_create_separate_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_failure_memory(temp, error_summary="KeyError: x", fix_summary="fix a")
            write_failure_memory(temp, error_summary="ValueError: y", fix_summary="fix b")

            failures_dir = Path(temp) / ".ai-memory" / "memory-store" / "failures"
            self.assertEqual(len(list(failures_dir.glob("*.md"))), 2)

    def test_reworded_same_root_cause_merges_via_similarity(self) -> None:
        """P-07: the two literal reports from the real-world test campaign.

        Same root cause, but the exception message embeds the offending value
        and the sentence is reorganized — exactly how an agent reports the
        same bug in two different sessions. Must collapse onto one entry.
        """
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_failure_memory(
                temp,
                error_summary=(
                    "ValueError: Invalid isoformat string in Task.is_overdue() "
                    "when --due receives non-ISO date like 07/15/2026"
                ),
                fix_summary="Validate --due before parsing.",
            )
            result2 = write_failure_memory(
                temp,
                error_summary=(
                    "ValueError: Invalid isoformat string: 2026/07/20 - "
                    "Task.is_overdue() parsing due_date"
                ),
                fix_summary="Validate --due before parsing (again).",
            )

            failures_dir = Path(temp) / ".ai-memory" / "memory-store" / "failures"
            files = list(failures_dir.glob("*.md"))
            self.assertEqual(len(files), 1, "reworded reports of the same root cause must merge")
            metadata, body = parse_frontmatter(files[0].read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("occurrences"), "2")
            self.assertIn("error_signature", metadata)
            self.assertIn("Occurrence 2", body)
            self.assertTrue(any("occurred 2 times" in w for w in result2["warnings"]))

    def test_merge_threshold_respects_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            first = "ValueError: Invalid isoformat string in Task.is_overdue() for --due"
            second = "ValueError: Invalid isoformat string: parsing due_date elsewhere"
            with mock.patch.dict(os.environ, {"MEMORY_FABRIC_FAILURE_MERGE_THRESHOLD": "1.0"}):
                write_failure_memory(temp, error_summary=first, fix_summary="f1")
                write_failure_memory(temp, error_summary=second, fix_summary="f2")

            failures_dir = Path(temp) / ".ai-memory" / "memory-store" / "failures"
            self.assertEqual(
                len(list(failures_dir.glob("*.md"))),
                2,
                "threshold 1.0 must disable similarity merging",
            )

    def test_same_hint_but_unrelated_message_stays_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_failure_memory(
                temp,
                error_summary="TypeError: unsupported operand type for + in totals renderer",
                fix_summary="Cast to int.",
            )
            write_failure_memory(
                temp,
                error_summary=(
                    "TypeError: unsupported callback signature registered by plugin loader "
                    "hooks during startup sequence scan"
                ),
                fix_summary="Fix plugin API.",
            )
            failures_dir = Path(temp) / ".ai-memory" / "memory-store" / "failures"
            self.assertEqual(len(list(failures_dir.glob("*.md"))), 2)


if __name__ == "__main__":
    unittest.main()
