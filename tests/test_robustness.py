"""Regression tests for gaps surfaced by the Milestone B module split:

- Concurrent writers must serialize safely, not corrupt data or raise spuriously.
- A crash while holding the write lock must not leave it stuck.
- A non-UTF-8 file in .ai-memory/ must degrade gracefully, not crash reads.
- The read path must hold up at a store size well beyond typical projects.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.locking import locked_file
from memory_fabric.storage import (
    doctor,
    initialize_memory_fabric,
    list_memory_store,
    read_combined_context,
    status,
    write_local_memory,
    write_memory_store,
)


class ConcurrentWriteTests(unittest.TestCase):
    # Distinct topics, not just a numeric suffix: write_local_memory's append-mode
    # dedup treats near-identical text as a duplicate (Jaccard word-overlap >= 0.85),
    # and single-digit numbers get stripped by its word-length filter (len > 2) —
    # "entry 0" / "entry 1" collapse to the same significant word-set and would be
    # (correctly) deduplicated to one line, defeating the point of this test.
    _TOPICS = [
        "database migration strategy",
        "authentication token rotation",
        "caching layer redesign",
        "logging pipeline overhaul",
        "deployment rollback procedure",
        "monitoring alert thresholds",
    ]

    def test_concurrent_appends_all_survive_without_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            errors: list[BaseException] = []

            def append_unique(topic: str) -> None:
                try:
                    write_local_memory(
                        temp,
                        "decisions",
                        f"We decided to proceed with the {topic} because it reduces operational risk.",
                        mode="append",
                    )
                except BaseException as exc:  # noqa: BLE001 - capture for assertion, not swallow
                    errors.append(exc)

            threads = [threading.Thread(target=append_unique, args=(t,)) for t in self._TOPICS]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

            self.assertEqual(errors, [], f"concurrent writers raised: {errors!r}")

            section_path = Path(temp) / ".ai-memory" / "decisions.md"
            metadata, body = parse_frontmatter(section_path.read_text(encoding="utf-8"))
            # Every writer's line must be present — none silently lost to a lost update.
            for topic in self._TOPICS:
                self.assertIn(topic, body)
            # File must still be valid, parseable frontmatter (not interleaved/corrupted).
            self.assertIn("section", metadata)

    def test_concurrent_writes_to_semantic_store_all_survive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            n_threads = 6
            errors: list[BaseException] = []

            def write_unique(i: int) -> None:
                try:
                    write_memory_store(
                        temp,
                        store_path=f"concurrent/entry-{i}",
                        content=f"Content for entry {i}.",
                        title=f"Entry {i}",
                    )
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=write_unique, args=(i,)) for i in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

            self.assertEqual(errors, [], f"concurrent writers raised: {errors!r}")

            listing = list_memory_store(temp, prefix="concurrent")
            self.assertEqual(listing["total"], n_threads)


class LockReleaseTests(unittest.TestCase):
    def test_lock_is_released_after_exception_in_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "section.md"
            target.write_text("placeholder", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                with locked_file(target):
                    raise RuntimeError("simulated crash while holding the lock")

            # If the lock leaked, this second acquisition would hang forever.
            # Run it on a worker thread so a regression fails the test instead
            # of freezing the whole suite.
            def acquire_again() -> str:
                with locked_file(target):
                    return "acquired"

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(acquire_again)
                try:
                    result = future.result(timeout=5)
                except FutureTimeoutError:
                    self.fail("lock was not released after an exception in the `with` body")
            self.assertEqual(result, "acquired")

    def test_lock_sidecar_file_does_not_leak_after_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "section.md"
            target.write_text("placeholder", encoding="utf-8")
            lock_path = target.with_name(target.name + ".lock")

            with self.assertRaises(ValueError):
                with locked_file(target):
                    self.assertTrue(lock_path.exists())
                    raise ValueError("simulated crash")

            self.assertFalse(lock_path.exists(), "lock sidecar file leaked after a crash")


class NonUtf8FileTests(unittest.TestCase):
    def _write_invalid_utf8_section(self, temp: str) -> Path:
        memory_dir = Path(temp) / ".ai-memory"
        bad_path = memory_dir / "schemas.md"
        # 0xFF is never valid as a standalone UTF-8 byte.
        bad_path.write_bytes(b"---\nsection: schemas\n---\n\nBroken: \xff\xfe bytes here.\n")
        return bad_path

    def test_doctor_reports_error_but_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            bad_path = self._write_invalid_utf8_section(temp)

            result = doctor(temp)  # must not raise

            self.assertFalse(result["ok"])
            self.assertTrue(any(str(bad_path) in err for err in result["errors"]))

    def test_status_does_not_raise_on_unreadable_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            self._write_invalid_utf8_section(temp)

            result = status(temp)  # must not raise
            self.assertTrue(result["memory_exists"])

    def test_read_combined_context_skips_bad_file_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            self._write_invalid_utf8_section(temp)

            bundle = read_combined_context(temp)  # must not raise

            self.assertTrue(any("schemas" in w for w in bundle["warnings"]))


class LargeStorePerformanceTests(unittest.TestCase):
    N_FILES = 1000

    def _seed_large_store(self, temp: str) -> None:
        store_root = Path(temp) / ".ai-memory" / "memory-store" / "bulk"
        store_root.mkdir(parents=True, exist_ok=True)
        for i in range(self.N_FILES):
            metadata = {
                "store_path": f"bulk/entry-{i:04d}",
                "title": f"Entry {i}",
                "summary": f"Bulk-generated entry number {i}.",
                "priority": "medium",
                "tags": ["bulk"],
                "schema_version": "1.3",
                "last_updated": "2026-07-05T00:00:00-04:00",
            }
            body = f"Bulk content for entry {i}.\n"
            (store_root / f"entry-{i:04d}.md").write_text(
                dump_frontmatter(metadata, body), encoding="utf-8"
            )

    def test_list_memory_store_completes_quickly_at_scale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            self._seed_large_store(temp)

            start = time.monotonic()
            result = list_memory_store(temp, prefix="bulk", max_results=self.N_FILES)
            elapsed = time.monotonic() - start

            self.assertEqual(result["total"], self.N_FILES)
            self.assertLess(
                elapsed, 15.0, f"list_memory_store took {elapsed:.1f}s for {self.N_FILES} files"
            )

    def test_doctor_completes_quickly_at_scale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            self._seed_large_store(temp)

            start = time.monotonic()
            result = doctor(temp)
            elapsed = time.monotonic() - start

            self.assertTrue(result["ok"])
            self.assertLess(elapsed, 15.0, f"doctor took {elapsed:.1f}s for {self.N_FILES} files")

    def test_read_combined_context_completes_quickly_at_scale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            self._seed_large_store(temp)

            start = time.monotonic()
            bundle = read_combined_context(temp, max_tokens=200000)
            elapsed = time.monotonic() - start

            self.assertGreater(len(bundle["included_sections"]), 0)
            self.assertLess(
                elapsed, 15.0, f"read_combined_context took {elapsed:.1f}s for {self.N_FILES} files"
            )


if __name__ == "__main__":
    unittest.main()
