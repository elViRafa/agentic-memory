"""Self-verifying citations: evidence refs that resolve, or get flagged."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from memory_fabric.eval import evaluate_memory_fabric as _async_evaluate_memory_fabric
from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.storage import (
    initialize_memory_fabric,
    verify_evidence,
    write_memory_store,
)


def evaluate_memory_fabric(*args, **kwargs):
    return asyncio.run(_async_evaluate_memory_fabric(*args, **kwargs))


class VerifyEvidenceTests(unittest.TestCase):
    def test_existing_path_evidence_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            (Path(temp) / "auth.py").write_text("def login():\n    pass\n", encoding="utf-8")
            write_memory_store(
                temp,
                "architecture/auth",
                "JWT auth.",
                title="Auth",
                evidence=["auth.py", "auth.py:1"],
            )

            result = verify_evidence(temp)
            self.assertTrue(result["ok"])
            self.assertEqual(result["checked_files"], 1)
            self.assertEqual(result["broken"], [])

    def test_missing_file_evidence_is_flagged_and_marked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "architecture/gone",
                "References a file that will be deleted.",
                title="Gone",
                evidence=["does-not-exist.py"],
            )

            result = verify_evidence(temp, mark_broken=True)
            self.assertFalse(result["ok"])
            self.assertEqual(len(result["broken"]), 1)
            self.assertIn("does-not-exist.py", result["broken"][0]["problems"][0])
            self.assertIn("store/architecture/gone", result["marked_broken"])

            store_file = Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "gone.md"
            metadata, _ = parse_frontmatter(store_file.read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("review_status"), "broken-evidence")

    def test_line_beyond_file_length_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            (Path(temp) / "short.py").write_text("one line\n", encoding="utf-8")
            write_memory_store(
                temp,
                "architecture/line-ref",
                "Cites a line past EOF.",
                title="Line Ref",
                evidence=["short.py:999"],
            )

            result = verify_evidence(temp)
            self.assertFalse(result["ok"])
            self.assertIn("999", result["broken"][0]["problems"][0])

    def test_no_mark_leaves_file_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp, "architecture/gone", "x", title="Gone", evidence=["missing.py"]
            )
            verify_evidence(temp, mark_broken=False)
            store_file = Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "gone.md"
            metadata, _ = parse_frontmatter(store_file.read_text(encoding="utf-8"))
            self.assertNotIn("review_status", metadata)

    def test_unverifiable_ref_kinds_are_skipped_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "architecture/pr-ref",
                "x",
                title="PR Ref",
                evidence=["pr:123", "https://example.com/thing"],
            )
            result = verify_evidence(temp)
            self.assertTrue(result["ok"])

    def test_commit_ref_checked_against_real_repo(self) -> None:
        git = None
        try:
            git = subprocess.run(["git", "--version"], capture_output=True, check=False)
        except Exception:
            pass
        if not git or git.returncode != 0:
            self.skipTest("git not available")

        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(["git", "init", "-q"], cwd=temp, check=True)
            subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=temp, check=True)
            subprocess.run(["git", "config", "user.name", "T"], cwd=temp, check=True)
            (Path(temp) / "f.py").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "add", "f.py"], cwd=temp, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=temp, check=True)
            real_hash = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=temp, capture_output=True, text=True, check=True
            ).stdout.strip()

            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/real-and-fake",
                "x",
                title="Real And Fake",
                evidence=[f"commit:{real_hash}", "commit:0000000000000000000000000000000000000f"],
            )

            result = verify_evidence(temp)
            self.assertFalse(result["ok"])
            self.assertEqual(len(result["broken"][0]["problems"]), 1)
            self.assertIn("0000000", result["broken"][0]["problems"][0])

    def test_eval_flags_broken_evidence_without_mutating_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "architecture/gone", "x", title="Gone", evidence=["nope.py"])

            result = evaluate_memory_fabric(temp, save_report=False)
            check_ids = [
                check["id"] for category in result["categories"] for check in category["checks"]
            ]
            self.assertIn("store/architecture/gone_evidence_broken", check_ids)

            store_file = Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "gone.md"
            metadata, _ = parse_frontmatter(store_file.read_text(encoding="utf-8"))
            self.assertNotIn("review_status", metadata)


if __name__ == "__main__":
    unittest.main()
