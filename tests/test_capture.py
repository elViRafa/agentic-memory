"""Phase 3 capture-reliability tests: passive commit capture, session/journal
enforcement primitives, capture stats, extraction prompt, and the diff budget."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.storage import (
    capture_commit,
    capture_stats,
    guard_journal,
    initialize_memory_fabric,
    mark_session_start,
    status,
    write_memory_store,
    write_session_journal,
)
from memory_fabric.storage.capture import _capture_skip_reason, mark_journal_written
from memory_fabric.storage.finalize import (
    _should_skip_diff_path,
    _summarize_diff,
    build_consolidation_prompt,
)

_GIT = shutil.which("git")


def _run_git(cwd: str, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(temp: str) -> None:
    _run_git(temp, "init")
    _run_git(temp, "config", "user.email", "test@example.com")
    _run_git(temp, "config", "user.name", "Test User")


def _commit(temp: str, filename: str, content: str, message: str) -> None:
    (Path(temp) / filename).write_text(content, encoding="utf-8")
    _run_git(temp, "add", filename)
    _run_git(temp, "commit", "-m", message)


@unittest.skipUnless(_GIT, "git is required for passive-capture tests")
class PassiveCaptureTests(unittest.TestCase):
    def test_capture_records_commit_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _init_repo(temp)
            initialize_memory_fabric(temp)
            _commit(temp, "auth.py", "def login(): ...\n", "feat: add auth login module")

            result = capture_commit(temp)

            self.assertTrue(result["captured"])
            self.assertTrue(result["commit"])
            self.assertEqual(result["store_path"].split("/")[:2], ["episodic", "commits"])

            store_root = Path(temp) / ".ai-memory" / "memory-store" / "episodic" / "commits"
            files = list(store_root.glob("*.md"))
            self.assertEqual(len(files), 1)
            metadata, body = parse_frontmatter(files[0].read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("source"), "passive-capture")
            self.assertEqual(metadata.get("review_status"), "pending")
            self.assertIn("feat: add auth login module", body)
            self.assertIn("auth.py", body)

    def test_capture_is_idempotent_per_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _init_repo(temp)
            initialize_memory_fabric(temp)
            _commit(temp, "a.py", "x\n", "first commit")

            first = capture_commit(temp)
            self.assertTrue(first["captured"])

            second = capture_commit(temp)
            self.assertFalse(second["captured"])
            self.assertTrue(any("already captured" in w for w in second["warnings"]))

            # A new commit is captured; both records live in the same dated file.
            _commit(temp, "b.py", "y\n", "second commit")
            third = capture_commit(temp)
            self.assertTrue(third["captured"])

            store_root = Path(temp) / ".ai-memory" / "memory-store" / "episodic" / "commits"
            body = next(store_root.glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("first commit", body)
            self.assertIn("second commit", body)

    def test_capture_graceful_outside_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = capture_commit(temp)
            self.assertFalse(result["captured"])
            self.assertTrue(any("Not a git repository" in w for w in result["warnings"]))


class CaptureFilterRuleTests(unittest.TestCase):
    """One case per `_capture_skip_reason` rule — pure unit tests, no git needed."""

    def test_merge_by_parent_count(self) -> None:
        reason = _capture_skip_reason("anything at all", "Dev", ["src/app.py"], parent_count=2)
        self.assertEqual(reason, "merge commit")

    def test_merge_by_subject_prefix(self) -> None:
        for subject in (
            "Merge branch 'feature' into main",
            "Merge pull request #42 from org/feature",
            "Merge remote-tracking branch 'origin/main'",
        ):
            with self.subTest(subject=subject):
                reason = _capture_skip_reason(subject, "Dev", ["src/app.py"], parent_count=1)
                self.assertEqual(reason, "merge commit")

    def test_bot_author(self) -> None:
        for author in ("dependabot[bot]", "renovate[bot]", "github-actions[bot]"):
            with self.subTest(author=author):
                reason = _capture_skip_reason(
                    "feat: bump requests to 2.32", author, ["src/app.py"], parent_count=1
                )
                self.assertEqual(reason, f"bot author ({author})")

    def test_skippable_conventional_commit_prefixes(self) -> None:
        for subject in (
            "chore: tidy imports",
            "chore(deps): weekly update",
            "style: reformat with ruff",
            "ci: cache uv downloads",
            "ci(release)!: new tag scheme",
            "build(deps): bump requests from 2.31 to 2.32",
            "build(deps-dev): bump pytest",
        ):
            with self.subTest(subject=subject):
                reason = _capture_skip_reason(subject, "Dev", ["src/app.py"], parent_count=1)
                self.assertEqual(reason, "skippable conventional-commit prefix")

    def test_lockfile_only_commit(self) -> None:
        reason = _capture_skip_reason(
            "update deps", "Dev", ["uv.lock", "frontend/package-lock.json"], parent_count=1
        )
        self.assertEqual(reason, "only lockfiles/generated files changed")

    def test_relevant_commits_are_not_skipped(self) -> None:
        for subject, files in (
            ("feat: add auth login module", ["src/auth.py"]),
            ("fix: guard against empty payload", ["src/server.py", "uv.lock"]),
            ("build: switch to hatchling", ["pyproject.toml"]),
            ("refactor!: split storage core", ["src/storage.py"]),
            ("Merged the two auth paths into one", ["src/auth.py"]),
            ("update deps", []),
        ):
            with self.subTest(subject=subject):
                self.assertIsNone(_capture_skip_reason(subject, "Dev", files, parent_count=1))


@unittest.skipUnless(_GIT, "git is required for passive-capture tests")
class CaptureFilterIntegrationTests(unittest.TestCase):
    def test_real_merge_commit_is_skipped_audibly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _init_repo(temp)
            initialize_memory_fabric(temp)
            _commit(temp, "base.py", "base\n", "feat: base work")
            _run_git(temp, "checkout", "-b", "feature")
            _commit(temp, "feature.py", "feature\n", "feat: feature work")
            _run_git(temp, "checkout", "-")
            _commit(temp, "main.py", "main\n", "feat: mainline work")
            _run_git(temp, "merge", "--no-ff", "-m", "knowledge-rich merge message", "feature")

            result = capture_commit(temp)

            self.assertFalse(result["captured"])
            self.assertEqual(result["skipped_reason"], "merge commit")
            self.assertTrue(result["commit"])
            self.assertTrue(any("capture filter" in w for w in result["warnings"]))
            self.assertEqual(capture_stats(temp)["commits_skipped"], 1)
            # No episodic record was written for the merge itself.
            store_root = Path(temp) / ".ai-memory" / "memory-store" / "episodic" / "commits"
            self.assertFalse(list(store_root.glob("*.md")) if store_root.exists() else [])

    def test_bot_commit_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _init_repo(temp)
            initialize_memory_fabric(temp)
            (Path(temp) / "deps.txt").write_text("requests==2.32\n", encoding="utf-8")
            _run_git(temp, "add", "deps.txt")
            _run_git(
                temp,
                "-c",
                "user.name=dependabot[bot]",
                "-c",
                "user.email=bot@example.com",
                "commit",
                "-m",
                "feat: bump requests",
            )

            result = capture_commit(temp)

            self.assertFalse(result["captured"])
            self.assertIn("bot author", result["skipped_reason"])

    def test_no_filter_captures_everything_and_stays_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _init_repo(temp)
            initialize_memory_fabric(temp)
            _commit(temp, "x.py", "x\n", "chore: tidy imports")

            filtered = capture_commit(temp)
            self.assertFalse(filtered["captured"])
            self.assertEqual(filtered["skipped_reason"], "skippable conventional-commit prefix")

            unfiltered = capture_commit(temp, apply_filter=False)
            self.assertTrue(unfiltered["captured"])
            self.assertIsNone(unfiltered["skipped_reason"])

            # Idempotency is unchanged: a second unfiltered run is a dup, not a rewrite.
            again = capture_commit(temp, apply_filter=False)
            self.assertFalse(again["captured"])
            self.assertTrue(any("already captured" in w for w in again["warnings"]))

    def test_skip_counter_accumulates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _init_repo(temp)
            initialize_memory_fabric(temp)
            _commit(temp, "a.py", "a\n", "chore: first noise")
            capture_commit(temp)
            _commit(temp, "b.py", "b\n", "ci: second noise")
            capture_commit(temp)

            self.assertEqual(capture_stats(temp)["commits_skipped"], 2)


class SessionGuardTests(unittest.TestCase):
    def test_guard_fails_open_without_session_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            # No SessionStart marker => never block (avoid false positives).
            self.assertTrue(guard_journal(temp)["ok"])

    def test_guard_blocks_until_journal_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            mark_session_start(temp)

            blocked = guard_journal(temp)
            self.assertFalse(blocked["ok"])
            self.assertIn("write_session_journal_tool", blocked["reason"])

            write_session_journal(temp, summary="Implemented the capture module.")

            self.assertTrue(guard_journal(temp)["ok"])

    def test_journal_write_touches_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            marker = Path(temp) / ".ai-memory" / "private" / "last_journal_at"
            self.assertFalse(marker.exists())
            write_session_journal(temp, summary="Did work.")
            self.assertTrue(marker.exists())
            self.assertTrue(marker.read_text(encoding="utf-8").strip())

    def test_mark_journal_written_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            # Should never raise even if called directly.
            mark_journal_written(temp)
            self.assertTrue((Path(temp) / ".ai-memory" / "private" / "last_journal_at").exists())


class CaptureStatsTests(unittest.TestCase):
    def test_stats_reflect_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "architecture/core", "Core notes.", title="Core")
            write_session_journal(temp, summary="Session summary.")

            stats = capture_stats(temp)
            self.assertGreaterEqual(stats["memories_total"], 1)
            self.assertGreaterEqual(stats["memories_last_7d"], 1)
            self.assertTrue(stats["last_journal_at"])
            self.assertGreaterEqual(stats["episodic_files"], 1)

    def test_status_includes_capture_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = status(temp)
            self.assertIn("capture", result)
            self.assertIn("memories_total", result["capture"])
            self.assertIn("commit_captures", result["capture"])
            self.assertIn("commits_skipped", result["capture"])


class DiffBudgetTests(unittest.TestCase):
    def test_should_skip_diff_path(self) -> None:
        self.assertTrue(_should_skip_diff_path("package-lock.json"))
        self.assertTrue(_should_skip_diff_path("frontend/pnpm-lock.yaml"))
        self.assertTrue(_should_skip_diff_path("node_modules/foo/bar.js"))
        self.assertTrue(_should_skip_diff_path("assets/app.min.js"))
        self.assertTrue(_should_skip_diff_path("dist/bundle.js"))
        self.assertFalse(_should_skip_diff_path("src/app.py"))
        self.assertFalse(_should_skip_diff_path("README.md"))

    def test_summarize_diff_skips_lockfiles_keeps_source(self) -> None:
        diff = (
            "diff --git a/package-lock.json b/package-lock.json\n"
            "index 1111..2222 100644\n"
            "--- a/package-lock.json\n"
            "+++ b/package-lock.json\n"
            "@@ -1 +1 @@\n"
            "-old-lock-content\n"
            "+new-lock-content\n"
            "diff --git a/src/app.py b/src/app.py\n"
            "index 3333..4444 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-old_source\n"
            "+new_source_line\n"
        )
        out = _summarize_diff(diff)
        self.assertIn("skipped: generated/lock/vendored", out)
        self.assertNotIn("new-lock-content", out)
        self.assertIn("new_source_line", out)

    def test_summarize_diff_truncates_large_file(self) -> None:
        big = "diff --git a/src/big.py b/src/big.py\n" + ("+line of code\n" * 500)
        out = _summarize_diff(big, per_file=200)
        self.assertIn("file diff truncated", out)
        self.assertLess(len(out), 500)


class ExtractionPromptTests(unittest.TestCase):
    def test_prompt_asks_to_extract_new_memories(self) -> None:
        prompt = build_consolidation_prompt(
            {"local/architecture": "body"},
            git_diff_text="some diff",
            session_text="",
            tool_calls_text="",
            include_summaries=False,
        )
        self.assertIn("EXTRACT NEW MEMORIES", prompt)
        self.assertIn("store/<category>/<slug>", prompt)
        self.assertNotIn('"summaries"', prompt)

    def test_prompt_includes_summaries_when_requested(self) -> None:
        prompt = build_consolidation_prompt({}, "", "", "", include_summaries=True)
        self.assertIn('"summaries"', prompt)

    def test_prepare_dream_payload_uses_extraction_prompt(self) -> None:
        from memory_fabric.storage import prepare_dream_payload

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "architecture/core", "Original content.", title="Core")
            payload = prepare_dream_payload(temp, mode="light")
            self.assertFalse(payload["skip_required"])
            self.assertIn("EXTRACT NEW MEMORIES", payload["consolidation_prompt"])


if __name__ == "__main__":
    unittest.main()
