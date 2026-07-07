"""Git-native semantic merge driver: unit tests on resolve_conflict(), plus a
real end-to-end `git merge` proving two branches that each append a new fact
merge cleanly instead of producing a textual conflict."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.merge_driver import install_merge_driver, resolve_conflict, run
from memory_fabric.storage import initialize_memory_fabric, write_memory_store

_GIT = shutil.which("git")


def _fm(section: str, priority: str, tags: list[str], last_updated: str, body: str) -> str:
    tags_str = ", ".join(tags)
    return (
        "---\n"
        f"store_path: {section}\n"
        f"title: Test\n"
        f'summary: "Test entry."\n'
        f"priority: {priority}\n"
        f"tags: [{tags_str}]\n"
        f'schema_version: "1.3"\n'
        f'last_updated: "{last_updated}"\n'
        "---\n\n" + body
    )


class ResolveConflictUnitTests(unittest.TestCase):
    def test_identical_sides_trivial(self) -> None:
        text = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "Body.\n")
        merged, warnings = resolve_conflict(text, text, text)
        self.assertEqual(merged, text)
        self.assertEqual(warnings, [])

    def test_only_ours_changed_keeps_ours(self) -> None:
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "Original.\n")
        ours = _fm(
            "x", "medium", ["a"], "2026-01-02T00:00:00+00:00", "Original.\nExtra from ours.\n"
        )
        theirs = ancestor
        merged, _ = resolve_conflict(ancestor, ours, theirs)
        self.assertIn("Extra from ours.", merged or "")

    def test_only_theirs_changed_keeps_theirs(self) -> None:
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "Original.\n")
        ours = ancestor
        theirs = _fm(
            "x", "medium", ["a"], "2026-01-02T00:00:00+00:00", "Original.\nExtra from theirs.\n"
        )
        merged, _ = resolve_conflict(ancestor, ours, theirs)
        self.assertIn("Extra from theirs.", merged or "")

    def test_pure_append_both_sides_merges_both_additions(self) -> None:
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "Shared base line.\n")
        ours = _fm(
            "x",
            "medium",
            ["a"],
            "2026-01-02T00:00:00+00:00",
            "Shared base line.\n\nOurs-only new fact about auth.\n",
        )
        theirs = _fm(
            "x",
            "medium",
            ["a"],
            "2026-01-03T00:00:00+00:00",
            "Shared base line.\n\nTheirs-only new fact about billing.\n",
        )
        merged, warnings = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNotNone(merged)
        self.assertIn("Ours-only new fact about auth.", merged)
        self.assertIn("Theirs-only new fact about billing.", merged)
        self.assertEqual(warnings, [])

    def test_frontmatter_reconciliation_union_tags_max_timestamp_urgent_priority(self) -> None:
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "Base.\n")
        ours = _fm("x", "low", ["a", "b"], "2026-01-02T00:00:00+00:00", "Base.\nOurs addition.\n")
        theirs = _fm(
            "x", "high", ["a", "c"], "2026-01-03T00:00:00+00:00", "Base.\nTheirs addition.\n"
        )
        merged, _ = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNotNone(merged)
        metadata, _ = parse_frontmatter(merged)
        self.assertEqual(set(metadata["tags"]), {"a", "b", "c"})
        self.assertEqual(metadata["priority"], "high")  # more urgent side wins
        self.assertEqual(metadata["last_updated"], "2026-01-03T00:00:00+00:00")  # max

    def test_both_sides_edit_existing_line_defers_to_fallback(self) -> None:
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "Original sentence.\n")
        ours = _fm("x", "medium", ["a"], "2026-01-02T00:00:00+00:00", "Ours-edited sentence.\n")
        theirs = _fm("x", "medium", ["a"], "2026-01-03T00:00:00+00:00", "Theirs-edited sentence.\n")
        merged, warnings = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNone(merged)
        self.assertTrue(any("not pure appends" in w for w in warnings))

    def test_differing_identity_field_defers_to_fallback(self) -> None:
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "Base.\n")
        ours = _fm("x", "medium", ["a"], "2026-01-02T00:00:00+00:00", "Base.\nMore.\n")
        theirs = _fm("y", "medium", ["a"], "2026-01-02T00:00:00+00:00", "Base.\nMore.\n")
        merged, warnings = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNone(merged)
        self.assertTrue(any("differs between branches" in w for w in warnings))

    def test_unparseable_frontmatter_defers_to_fallback(self) -> None:
        merged, warnings = resolve_conflict("---\nbroken: [", "not frontmatter at all", "also not")
        self.assertIsNone(merged)
        self.assertTrue(warnings)


@unittest.skipUnless(_GIT, "git is required for merge-driver integration tests")
class RunFallbackTests(unittest.TestCase):
    def test_run_writes_merged_result_and_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ancestor = Path(temp) / "O"
            ours = Path(temp) / "A"
            theirs = Path(temp) / "B"
            ancestor.write_text(
                _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "Base.\n"), encoding="utf-8"
            )
            ours.write_text(
                _fm("x", "medium", ["a"], "2026-01-02T00:00:00+00:00", "Base.\nOurs fact.\n"),
                encoding="utf-8",
            )
            theirs.write_text(
                _fm("x", "medium", ["a"], "2026-01-03T00:00:00+00:00", "Base.\nTheirs fact.\n"),
                encoding="utf-8",
            )

            exit_code = run(str(ancestor), str(ours), str(theirs))
            self.assertEqual(exit_code, 0)
            merged_text = ours.read_text(encoding="utf-8")
            self.assertIn("Ours fact.", merged_text)
            self.assertIn("Theirs fact.", merged_text)

    def test_run_falls_back_to_git_merge_file_on_unmergeable_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ancestor = Path(temp) / "O"
            ours = Path(temp) / "A"
            theirs = Path(temp) / "B"
            ancestor.write_text("plain text\nline two\n", encoding="utf-8")
            ours.write_text("plain text CHANGED BY OURS\nline two\n", encoding="utf-8")
            theirs.write_text("plain text CHANGED BY THEIRS\nline two\n", encoding="utf-8")

            exit_code = run(str(ancestor), str(ours), str(theirs))
            # git merge-file returns the conflict count (>0) for a real conflict.
            self.assertGreater(exit_code, 0)
            result_text = ours.read_text(encoding="utf-8")
            self.assertIn("<<<<<<<", result_text)


def _run_git(cwd: str, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return res.stdout


@unittest.skipUnless(_GIT, "git is required for merge-driver integration tests")
class EndToEndGitMergeTests(unittest.TestCase):
    def test_two_branches_appending_different_facts_merge_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _run_git(temp, "init", "-q")
            _run_git(temp, "config", "user.email", "t@t.com")
            _run_git(temp, "config", "user.name", "T")

            initialize_memory_fabric(temp)
            write_memory_store(temp, "decisions/shared", "Shared baseline fact.", title="Shared")
            (Path(temp) / ".gitignore").write_text("", encoding="utf-8")
            _run_git(temp, "add", "-A")
            _run_git(temp, "commit", "-qm", "baseline")
            base_branch = _run_git(temp, "branch", "--show-current").strip()

            install_result = install_merge_driver(temp)
            self.assertTrue(install_result["ok"])

            _run_git(temp, "checkout", "-qb", "feature-a")
            write_memory_store(
                temp,
                "decisions/shared",
                "Fact from branch A about auth.",
                title="Shared",
                mode="append",
            )
            _run_git(temp, "commit", "-qam", "branch A adds fact")

            _run_git(temp, "checkout", "-q", base_branch)
            write_memory_store(
                temp,
                "decisions/shared",
                "Fact from branch B about billing.",
                title="Shared",
                mode="append",
            )
            _run_git(temp, "commit", "-qam", "branch B adds fact")

            merge_res = subprocess.run(
                ["git", "merge", "feature-a", "-q", "--no-edit"],
                cwd=temp,
                capture_output=True,
                text=True,
            )

            store_file = Path(temp) / ".ai-memory" / "memory-store" / "decisions" / "shared.md"
            merged_text = store_file.read_text(encoding="utf-8")

            self.assertEqual(merge_res.returncode, 0, merge_res.stdout + merge_res.stderr)
            self.assertNotIn("<<<<<<<", merged_text)
            self.assertIn("Fact from branch A about auth.", merged_text)
            self.assertIn("Fact from branch B about billing.", merged_text)


if __name__ == "__main__":
    unittest.main()
