"""Failure memory: error -> fix pairs, deduplicated by normalized error signature."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
