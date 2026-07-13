"""Cross-process corruption tests (ROADMAP.md Phase 0 "Concurrency & corruption
tests" / §2.1 Q4).

test_robustness.py's ConcurrentWriteTests already prove locking.py is correct
under multi-threaded contention *within one process*. Real-world contention is
two separate agent *processes* — two IDEs open on the same project, or a git
post-commit hook firing while a live session is mid-write — which never share
Python's GIL or any in-process state. locking.py's lock is a genuine OS-level
file lock (msvcrt.locking on Windows, fcntl.flock on POSIX), so it should
serialize real processes too; these tests verify that directly with real
`subprocess`-spawned Python processes instead of assuming it from the
thread-level tests.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.storage import (
    initialize_memory_fabric,
    list_memory_store,
    read_memory_store,
    write_memory_store,
)

_HELPER = Path(__file__).with_name("_cross_process_helpers.py")


class ConcurrentProcessWriteTests(unittest.TestCase):
    def test_two_processes_appending_to_one_store_file_lose_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            count = 15
            procs = [
                subprocess.Popen(
                    [
                        sys.executable,
                        str(_HELPER),
                        "write_loop",
                        temp,
                        "concurrent/target",
                        f"P{label}",
                        str(count),
                    ]
                )
                for label in range(2)
            ]
            for proc in procs:
                returncode = proc.wait(timeout=120)
                self.assertEqual(returncode, 0, f"writer process exited {returncode}")

            result = read_memory_store(temp, "concurrent/target")
            text = result["text"]
            missing = [
                f"Marker-P{label}-{i}"
                for label in range(2)
                for i in range(count)
                if f"Marker-P{label}-{i}" not in text
            ]
            self.assertEqual(missing, [], "writes lost to a lost-update race between processes")

            # Still valid, parseable frontmatter — interleaved writes from two
            # processes did not corrupt the file structure.
            metadata, _body = parse_frontmatter(text)
            self.assertEqual(metadata["store_path"], "concurrent/target")


class KilledWriterTests(unittest.TestCase):
    def test_killed_writer_releases_lock_for_next_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            target_path = Path(temp) / ".ai-memory" / "memory-store" / "hang" / "target.md"
            target_path.parent.mkdir(parents=True, exist_ok=True)

            proc = subprocess.Popen(
                [sys.executable, str(_HELPER), "hang_while_locked", str(target_path)],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                assert proc.stdout is not None
                line = proc.stdout.readline()
                self.assertEqual(
                    line.strip(), "LOCK_ACQUIRED", "writer process never signaled it held the lock"
                )
            finally:
                proc.kill()
                proc.wait(timeout=10)

            # The OS releases a process's file locks when it dies (including a
            # hard kill) — a fresh writer must not hang waiting on a lock
            # nobody holds anymore. This is the property that actually matters
            # here; it's what distinguishes a real OS lock from a naive
            # "lock file exists" convention, which *would* stay stuck forever.
            start = time.monotonic()
            result = write_memory_store(temp, "hang/target", "Recovered content", mode="replace")
            elapsed = time.monotonic() - start
            self.assertLess(
                elapsed, 10.0, f"write blocked {elapsed:.1f}s on a lock held by a dead process"
            )
            self.assertTrue(result["changed"])

            # And the file is left fully valid afterward, not torn.
            read_result = read_memory_store(temp, "hang/target")
            self.assertIn("Recovered content", read_result["text"])
            metadata, _body = parse_frontmatter(read_result["text"])
            self.assertEqual(metadata["store_path"], "hang/target")


class LargeStoreFileTests(unittest.TestCase):
    def test_10mb_store_file_write_read_list_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            big_content = "Line of bulk content for size testing.\n" * 250_000  # ~10 MB
            self.assertGreater(len(big_content.encode("utf-8")), 9_000_000)

            write_result = write_memory_store(temp, "bulk/huge", big_content, mode="replace")
            self.assertTrue(write_result["changed"])

            read_result = read_memory_store(temp, "bulk/huge", max_tokens=100)
            self.assertTrue(read_result["truncated"], "10MB body should exceed a 100-token budget")

            list_result = list_memory_store(temp, prefix="bulk")
            self.assertEqual(list_result["total"], 1)

            append_result = write_memory_store(
                temp, "bulk/huge", "One more distinct line at the end.", mode="append"
            )
            self.assertTrue(append_result["changed"])


class NonUtf8ExistingFileTests(unittest.TestCase):
    """Regression tests for a real crash found while writing this suite:
    write_memory_store / write_local_memory / read_section all unconditionally
    read the existing target file as UTF-8 with no error handling, so a file
    corrupted by any other tool (or a partial/binary write) crashed every
    subsequent write — including `mode="replace"`, whose entire point is to
    overwrite what's there.
    """

    _BAD_STORE_FILE = (
        b"---\nstore_path: bad/encoding\ntitle: Bad\nsummary: x\npriority: medium\n"
        b'tags: []\nschema_version: "1.3"\nlast_updated: "2026-01-01T00:00:00+00:00"\n'
        b"---\n\nGarbage byte follows: \xff\xfe end.\n"
    )
    _BAD_FLAT_FILE = (
        b"---\nsection: decisions\nsummary: x\npriority: medium\ntags: []\n"
        b'schema_version: "1.3"\nlast_updated: "2026-01-01T00:00:00+00:00"\n'
        b"---\n\nGarbage byte follows: \xff\xfe end.\n"
    )

    def test_store_append_refuses_cleanly_replace_recovers(self) -> None:
        from memory_fabric.storage import write_local_memory

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            target = Path(temp) / ".ai-memory" / "memory-store" / "bad" / "encoding.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self._BAD_STORE_FILE)

            with self.assertRaises(ValueError) as ctx:
                write_memory_store(temp, "bad/encoding", "New", mode="append")
            self.assertIn("unreadable", str(ctx.exception))

            result = write_memory_store(temp, "bad/encoding", "New content", mode="replace")
            self.assertTrue(result["changed"])
            self.assertTrue(any("could not be read" in w for w in result["warnings"]))
            self.assertIn("New content", read_memory_store(temp, "bad/encoding")["text"])

            # Same bug, same fix, in the flat-section write path.
            flat = Path(temp) / ".ai-memory" / "decisions.md"
            flat.write_bytes(self._BAD_FLAT_FILE)
            with self.assertRaises(ValueError):
                write_local_memory(temp, "decisions", "New", mode="append")
            flat_result = write_local_memory(temp, "decisions", "New content", mode="replace")
            self.assertTrue(flat_result["changed"])

    def test_read_section_raises_clean_error_not_unicode_decode_error(self) -> None:
        from memory_fabric.storage import read_section

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            flat = Path(temp) / ".ai-memory" / "decisions.md"
            flat.write_bytes(self._BAD_FLAT_FILE)
            with self.assertRaises(ValueError) as ctx:
                read_section(temp, "decisions")
            self.assertIn("unreadable", str(ctx.exception))


@unittest.skipUnless(os.name != "nt", "symlink creation needs admin/Developer Mode on Windows")
class SymlinkedMemoryDirTests(unittest.TestCase):
    def test_operations_work_through_a_symlinked_ai_memory(self) -> None:
        with tempfile.TemporaryDirectory() as real_root, tempfile.TemporaryDirectory() as project:
            real_memory_dir = Path(real_root) / "actual-ai-memory"
            initialize_memory_fabric(project)
            live_memory_dir = Path(project) / ".ai-memory"
            live_memory_dir.rename(real_memory_dir)
            (Path(project) / ".ai-memory").symlink_to(real_memory_dir, target_is_directory=True)

            result = write_memory_store(project, "decisions/via-symlink", "A fact.")
            self.assertTrue(result["changed"])
            self.assertTrue(
                (real_memory_dir / "memory-store" / "decisions" / "via-symlink.md").exists()
            )

            read_result = read_memory_store(project, "decisions/via-symlink")
            self.assertIn("A fact.", read_result["text"])


class ReadOnlyTargetFileTests(unittest.TestCase):
    """Windows NTFS ignores POSIX-style directory permission bits (`chmod` on a
    *directory* does not block file creation inside it — verified empirically
    on this machine), so a "read-only store dir" test would silently pass
    without exercising anything on Windows. A read-only *file* is enforced
    identically on both platforms, which is what this actually tests: what
    happens when a write hits a permission error, cross-platform.
    """

    def test_write_to_a_read_only_existing_file_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "protected/entry", "Original content.")
            target = Path(temp) / ".ai-memory" / "memory-store" / "protected" / "entry.md"
            self.assertTrue(target.exists())

            os.chmod(target, stat.S_IREAD)
            try:
                with self.assertRaises(OSError):
                    write_memory_store(
                        temp, "protected/entry", "Attempted overwrite.", mode="replace"
                    )
            finally:
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)

            # Original content survives a failed write untouched.
            self.assertIn("Original content.", read_memory_store(temp, "protected/entry")["text"])


if __name__ == "__main__":
    unittest.main()
