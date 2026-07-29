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
from memory_fabric.merge_driver import (
    ensure_merge_driver_registered,
    install_merge_driver,
    merge_driver_status,
    resolve_conflict,
    resolve_unmerged,
    run,
)
from memory_fabric.storage import initialize_memory_fabric, write_memory_store
from memory_fabric.storage.maps import FOLD_BASENAME, _body_hash, regenerate_maps

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


def _map_fm(section: str, fingerprint: str, last_updated: str, body: str) -> str:
    """A `generated: true` root map, as `regenerate_maps` writes them."""
    return (
        "---\n"
        f"section: {section}\n"
        f'summary: "Generated map of memory-store/{section}/."\n'
        "priority: high\n"
        f"tags: [{section}]\n"
        'schema_version: "1.3"\n'
        f'last_updated: "{last_updated}"\n'
        "generated: true\n"
        f"generated_from: memory-store/{section}\n"
        f"store_fingerprint: {fingerprint}\n"
        f"body_hash: {_body_hash(body)}\n"
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


class BlockMergeTests(unittest.TestCase):
    """Both branches wrote into the same file but different `##` entries — the
    shape two agents produce when they journal the same day."""

    def test_separate_new_blocks_plus_an_edit_to_an_older_one_merge(self) -> None:
        ancestor = _fm(
            "episodic/2026-07-28",
            "low",
            ["episodic"],
            "2026-07-28T10:00:00+00:00",
            "## shared-earlier\n\nWork both developers already had.\n",
        )
        ours = _fm(
            "episodic/2026-07-28",
            "low",
            ["episodic"],
            "2026-07-28T12:00:00+00:00",
            "## shared-earlier\n\nWork both developers already had.\nAmended by Bob.\n"
            "\n## session-from-bob\n\nBob added the billing webhook retry.\n",
        )
        theirs = _fm(
            "episodic/2026-07-28",
            "low",
            ["episodic"],
            "2026-07-28T11:00:00+00:00",
            "## shared-earlier\n\nWork both developers already had.\n"
            "\n## session-from-alice\n\nAlice added the OAuth refresh flow.\n",
        )
        merged, warnings = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNotNone(merged)
        self.assertEqual(warnings, [])
        self.assertIn("Bob added the billing webhook retry.", merged)
        self.assertIn("Alice added the OAuth refresh flow.", merged)
        self.assertIn("Amended by Bob.", merged)
        self.assertNotIn("<<<<<<<", merged)

    def test_appends_inside_the_same_block_are_both_kept(self) -> None:
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "## entry\n\nBase.\n")
        ours = _fm(
            "x", "medium", ["a"], "2026-01-02T00:00:00+00:00", "## entry\n\nBase.\nOurs detail.\n"
        )
        theirs = _fm(
            "x", "medium", ["a"], "2026-01-03T00:00:00+00:00", "## entry\n\nBase.\nTheirs detail.\n"
        )
        merged, _ = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNotNone(merged)
        self.assertIn("Ours detail.", merged)
        self.assertIn("Theirs detail.", merged)

    def test_same_block_rewritten_on_both_sides_defers_to_fallback(self) -> None:
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", "## entry\n\nBase.\n")
        ours = _fm("x", "medium", ["a"], "2026-01-02T00:00:00+00:00", "## entry\n\nOurs rewrite.\n")
        theirs = _fm(
            "x", "medium", ["a"], "2026-01-03T00:00:00+00:00", "## entry\n\nTheirs rewrite.\n"
        )
        merged, warnings = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNone(merged)
        self.assertTrue(any("not pure appends" in w for w in warnings))

    def test_block_deleted_on_one_side_and_untouched_on_the_other_stays_deleted(self) -> None:
        body = "## keep\n\nKeep me.\n\n## drop\n\nObsolete.\n"
        ancestor = _fm("x", "medium", ["a"], "2026-01-01T00:00:00+00:00", body)
        ours = _fm(
            "x",
            "medium",
            ["a"],
            "2026-01-02T00:00:00+00:00",
            "## keep\n\nKeep me.\n\n## drop\n\nObsolete.\n\n## added\n\nNew fact.\n",
        )
        theirs = _fm("x", "medium", ["a"], "2026-01-03T00:00:00+00:00", "## keep\n\nKeep me.\n")
        merged, _ = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNotNone(merged)
        self.assertIn("New fact.", merged)
        self.assertNotIn("Obsolete.", merged)


class DerivedViewTests(unittest.TestCase):
    """Root maps and indexes are rebuilt from `memory-store/` on every Dreaming
    run, so a textual conflict in one is never worth a human's time."""

    def test_generated_map_union_merges_both_sides(self) -> None:
        base_body = "# Failures Map\n\n- **Shared** (`failures/shared`, high) — Shared\n"
        ancestor = _map_fm("failures", "aaa", "2026-07-27T10:00:00+00:00", base_body)
        ours = _map_fm(
            "failures",
            "bbb",
            "2026-07-28T12:00:00+00:00",
            base_body + "- **Bob bug** (`failures/bob`, high) — Bob bug\n",
        )
        theirs = _map_fm(
            "failures",
            "ccc",
            "2026-07-28T11:00:00+00:00",
            base_body + "- **Alice bug** (`failures/alice`, high) — Alice bug\n",
        )
        merged, warnings = resolve_conflict(
            ancestor, ours, theirs, path_hint=".ai-memory/failures.md"
        )
        self.assertIsNotNone(merged)
        self.assertEqual(warnings, [])
        self.assertNotIn("<<<<<<<", merged)
        self.assertIn("Bob bug", merged)
        self.assertIn("Alice bug", merged)

    def test_generated_map_merge_is_restamped_so_dreaming_rebuilds_without_folding(self) -> None:
        """The re-stamp is load-bearing: a merged body carrying its pre-merge
        `body_hash` looks hand-edited to `regenerate_maps`, which would copy the
        union into `memory-store/` as a permanent memory."""
        base_body = "# Failures Map\n\n- **Shared** (`failures/shared`, high) — Shared\n"
        ancestor = _map_fm("failures", "aaa", "2026-07-27T10:00:00+00:00", base_body)
        ours = _map_fm(
            "failures", "bbb", "2026-07-28T12:00:00+00:00", base_body + "- **Bob bug**\n"
        )
        theirs = _map_fm(
            "failures", "ccc", "2026-07-28T11:00:00+00:00", base_body + "- **Alice bug**\n"
        )
        merged, _ = resolve_conflict(ancestor, ours, theirs)
        metadata, body = parse_frontmatter(merged)

        self.assertEqual(metadata["body_hash"], _body_hash(body))  # not "hand-written"
        self.assertEqual(metadata["store_fingerprint"], "")  # stale -> forces a rebuild

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            memory_root = Path(temp) / ".ai-memory"
            (memory_root / "failures.md").write_text(merged, encoding="utf-8")
            write_memory_store(temp, "failures/shared", "Shared failure.", title="Shared")

            result = regenerate_maps(memory_root)

            self.assertEqual(result["legacy_folded"], [])
            fold_path = memory_root / "memory-store" / "failures" / f"{FOLD_BASENAME}.md"
            self.assertFalse(fold_path.exists(), "merged map was folded into the store as a memory")
            self.assertIn("failures.md", result["maps_written"])

    def test_index_is_recognized_as_derived_without_a_path_hint(self) -> None:
        """Clones that registered the driver before it was passed `%P` still get
        conflict-free indexes — `section: index` is enough to recognize one."""
        header = '---\nsection: index\nsummary: "Map."\npriority: high\ntags: [index]\n'
        header += 'schema_version: "1.3"\nlast_updated: "%s"\n---\n\n'
        table = "| Section | Priority |\n| --- | --- |\n| `architecture` | high |\n"
        ancestor = (header % "2026-07-27T10:00:00+00:00") + table
        ours = (header % "2026-07-28T12:00:00+00:00") + table + "| `debt` | low |\n"
        theirs = (header % "2026-07-28T11:00:00+00:00") + table + "| `features` | medium |\n"

        merged, warnings = resolve_conflict(ancestor, ours, theirs)
        self.assertIsNotNone(merged)
        self.assertEqual(warnings, [])
        self.assertIn("`debt`", merged)
        self.assertIn("`features`", merged)


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
        # ignore_cleanup_errors: git may still be finishing work inside .git/objects
        # when the context manager tears the tree down, which surfaced on macOS CI as
        # "OSError: [Errno 66] Directory not empty: 'objects'". gc.auto=0 below removes
        # the usual cause; this keeps a lost race from failing an otherwise green test.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            _run_git(temp, "init", "-q")
            _run_git(temp, "config", "user.email", "t@t.com")
            _run_git(temp, "config", "user.name", "T")
            # Keep git from forking a background `gc --auto` that writes objects
            # concurrently with the temp-dir cleanup.
            _run_git(temp, "config", "gc.auto", "0")

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


@unittest.skipUnless(_GIT, "git is required for merge-driver integration tests")
class ResolveUnmergedTests(unittest.TestCase):
    """`ai-memory resolve-conflicts`: the after-the-fact path, for the team that
    already hit conflicts because nobody had registered the driver."""

    def _repo(self, temp: str) -> str:
        _run_git(temp, "init", "-q")
        _run_git(temp, "config", "user.email", "t@t.com")
        _run_git(temp, "config", "user.name", "T")
        _run_git(temp, "config", "gc.auto", "0")
        initialize_memory_fabric(temp)
        (Path(temp) / ".gitignore").write_text("", encoding="utf-8")
        return temp

    def test_resolves_and_stages_a_conflicted_merge_without_the_driver(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            self._repo(temp)
            write_memory_store(temp, "episodic/2026-07-28", "Shared earlier work.", title="Day")
            _run_git(temp, "add", "-A")
            _run_git(temp, "commit", "-qm", "baseline")
            base_branch = _run_git(temp, "branch", "--show-current").strip()

            _run_git(temp, "checkout", "-qb", "alice")
            write_memory_store(
                temp, "episodic/2026-07-28", "Alice: OAuth refresh.", title="Day", mode="append"
            )
            _run_git(temp, "commit", "-qam", "alice")

            _run_git(temp, "checkout", "-q", base_branch)
            write_memory_store(
                temp, "episodic/2026-07-28", "Bob: billing retry.", title="Day", mode="append"
            )
            _run_git(temp, "commit", "-qam", "bob")

            # No driver registered: git leaves textual conflict markers behind.
            merge = subprocess.run(
                ["git", "merge", "alice", "--no-edit"], cwd=temp, capture_output=True, text=True
            )
            self.assertNotEqual(merge.returncode, 0)
            self.assertIn("CONFLICT", merge.stdout + merge.stderr)

            resolution = resolve_unmerged(temp)

            self.assertTrue(resolution["ok"], resolution["warnings"])
            self.assertEqual(resolution["deferred"], [])
            self.assertIn(".ai-memory/memory-store/episodic/2026-07-28.md", resolution["resolved"])
            day_file = Path(temp) / ".ai-memory/memory-store/episodic/2026-07-28.md"
            merged_text = day_file.read_text(encoding="utf-8")
            self.assertNotIn("<<<<<<<", merged_text)
            self.assertIn("Alice: OAuth refresh.", merged_text)
            self.assertIn("Bob: billing retry.", merged_text)
            # Staged, so the merge can be committed straight away.
            self.assertEqual(_run_git(temp, "diff", "--name-only", "--diff-filter=U").strip(), "")

    def test_reports_files_that_still_need_a_human(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            self._repo(temp)
            store_file = Path(temp) / ".ai-memory/memory-store/decisions/api.md"
            store_file.parent.mkdir(parents=True, exist_ok=True)
            store_file.write_text(
                _fm(
                    "decisions/api",
                    "medium",
                    ["d"],
                    "2026-01-01T00:00:00+00:00",
                    "## call\n\nUse REST.\n",
                ),
                encoding="utf-8",
            )
            _run_git(temp, "add", "-A")
            _run_git(temp, "commit", "-qm", "baseline")
            base_branch = _run_git(temp, "branch", "--show-current").strip()

            _run_git(temp, "checkout", "-qb", "alice")
            store_file.write_text(
                _fm(
                    "decisions/api",
                    "medium",
                    ["d"],
                    "2026-01-02T00:00:00+00:00",
                    "## call\n\nUse GraphQL.\n",
                ),
                encoding="utf-8",
            )
            _run_git(temp, "commit", "-qam", "alice")

            _run_git(temp, "checkout", "-q", base_branch)
            store_file.write_text(
                _fm(
                    "decisions/api",
                    "medium",
                    ["d"],
                    "2026-01-03T00:00:00+00:00",
                    "## call\n\nUse gRPC.\n",
                ),
                encoding="utf-8",
            )
            _run_git(temp, "commit", "-qam", "bob")
            subprocess.run(
                ["git", "merge", "alice", "--no-edit"], cwd=temp, capture_output=True, text=True
            )

            resolution = resolve_unmerged(temp)

            # Two branches genuinely disagree on one decision: not ours to pick.
            self.assertFalse(resolution["ok"])
            self.assertEqual(resolution["deferred"], [".ai-memory/memory-store/decisions/api.md"])
            self.assertIn("<<<<<<<", store_file.read_text(encoding="utf-8"))

    def test_no_merge_in_progress_is_a_clean_no_op(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            self._repo(temp)
            _run_git(temp, "add", "-A")
            _run_git(temp, "commit", "-qm", "baseline")
            resolution = resolve_unmerged(temp)
            self.assertTrue(resolution["ok"])
            self.assertEqual(resolution["resolved"], [])


@unittest.skipUnless(_GIT, "git is required for merge-driver integration tests")
class DriverRegistrationTests(unittest.TestCase):
    """The half-installed state — `.gitattributes` committed, driver command
    missing — is what makes memory files conflict on a team."""

    def test_status_reports_the_two_halves_independently(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            _run_git(temp, "init", "-q")
            initialize_memory_fabric(temp)
            self.assertEqual(
                merge_driver_status(temp),
                {"declared": False, "registered": False, "active": False},
            )

            install_merge_driver(temp)
            self.assertEqual(
                merge_driver_status(temp),
                {"declared": True, "registered": True, "active": True},
            )

            # A teammate's fresh clone: the committed .gitattributes is there,
            # the local driver command is not.
            _run_git(temp, "config", "--unset", "merge.memory-fabric.driver")
            status = merge_driver_status(temp)
            self.assertTrue(status["declared"])
            self.assertFalse(status["registered"])
            self.assertFalse(status["active"])

    def test_ensure_registered_repairs_a_clone_that_already_declares_the_driver(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            _run_git(temp, "init", "-q")
            initialize_memory_fabric(temp)
            install_merge_driver(temp)
            _run_git(temp, "config", "--unset", "merge.memory-fabric.driver")

            self.assertTrue(ensure_merge_driver_registered(temp))
            self.assertTrue(merge_driver_status(temp)["active"])
            # Idempotent: nothing left to repair on a second call.
            self.assertFalse(ensure_merge_driver_registered(temp))

    def test_ensure_registered_does_nothing_when_the_repo_never_asked_for_it(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            _run_git(temp, "init", "-q")
            initialize_memory_fabric(temp)
            self.assertFalse(ensure_merge_driver_registered(temp))
            self.assertFalse(merge_driver_status(temp)["registered"])

    def test_doctor_warns_when_the_driver_is_declared_but_not_registered(self) -> None:
        from memory_fabric.storage import doctor

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            _run_git(temp, "init", "-q")
            initialize_memory_fabric(temp)
            install_merge_driver(temp)
            _run_git(temp, "config", "--unset", "merge.memory-fabric.driver")

            warnings = doctor(temp, check_network=False)["warnings"]
            self.assertTrue(
                any("has not registered it" in w for w in warnings),
                warnings,
            )


@unittest.skipUnless(_GIT, "git is required for merge-driver integration tests")
class EndToEndGeneratedMapMergeTests(unittest.TestCase):
    def test_generated_map_merges_cleanly_with_the_driver_installed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            _run_git(temp, "init", "-q")
            _run_git(temp, "config", "user.email", "t@t.com")
            _run_git(temp, "config", "user.name", "T")
            _run_git(temp, "config", "gc.auto", "0")
            initialize_memory_fabric(temp)
            (Path(temp) / ".gitignore").write_text("", encoding="utf-8")
            memory_root = Path(temp) / ".ai-memory"

            write_memory_store(temp, "failures/shared", "Shared failure.", title="Shared")
            regenerate_maps(memory_root)
            install_merge_driver(temp)
            _run_git(temp, "add", "-A")
            _run_git(temp, "commit", "-qm", "baseline")
            base_branch = _run_git(temp, "branch", "--show-current").strip()

            _run_git(temp, "checkout", "-qb", "alice")
            write_memory_store(temp, "failures/alice", "Alice failure.", title="Alice")
            regenerate_maps(memory_root)
            _run_git(temp, "add", "-A")
            _run_git(temp, "commit", "-qm", "alice")

            _run_git(temp, "checkout", "-q", base_branch)
            write_memory_store(temp, "failures/bob", "Bob failure.", title="Bob")
            regenerate_maps(memory_root)
            _run_git(temp, "add", "-A")
            _run_git(temp, "commit", "-qm", "bob")

            merge = subprocess.run(
                ["git", "merge", "alice", "-q", "--no-edit"],
                cwd=temp,
                capture_output=True,
                text=True,
            )

            self.assertEqual(merge.returncode, 0, merge.stdout + merge.stderr)
            map_text = (memory_root / "failures.md").read_text(encoding="utf-8")
            self.assertNotIn("<<<<<<<", map_text)
            self.assertIn("Alice", map_text)
            self.assertIn("Bob", map_text)


if __name__ == "__main__":
    unittest.main()
