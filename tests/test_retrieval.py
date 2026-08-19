"""R0-R6 retrieval, ranking, search-filter, review, and hook-guard tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.frontmatter import dump_frontmatter
from memory_fabric.storage import (
    context_for_task,
    initialize_memory_fabric,
    keyword_search,
    read_combined_context,
    write_memory_store,
)
from memory_fabric.storage.failures import write_failure_memory
from memory_fabric.storage.hook_guard import evaluate_hook_payload, run_hook_guard
from memory_fabric.storage.index import delete_index
from memory_fabric.storage.ranking import bm25_scores, slugify, tokenize
from memory_fabric.storage.review import drop_review, list_pending_reviews, promote_review
from memory_fabric.storage.verify import verify_evidence


def _write_store_file(
    temp: str,
    store_path: str,
    body: str,
    *,
    priority: str = "medium",
    title: str | None = None,
    summary: str | None = None,
    last_updated: str = "2026-08-01T00:00:00-04:00",
) -> None:
    root = Path(temp) / ".ai-memory" / "memory-store"
    parts = store_path.split("/")
    dest = root.joinpath(*parts[:-1])
    dest.mkdir(parents=True, exist_ok=True)
    display = title or parts[-1].replace("-", " ").title()
    metadata = {
        "store_path": store_path,
        "title": display,
        "summary": summary or f"{display} — project memory entry.",
        "priority": priority,
        "tags": ["test"],
        "schema_version": "1.3",
        "last_updated": last_updated,
    }
    (dest / f"{parts[-1]}.md").write_text(dump_frontmatter(metadata, body), encoding="utf-8")


class RankingUnitTests(unittest.TestCase):
    def test_slugify_transliterates_portuguese(self) -> None:
        self.assertEqual(slugify("seção de importação"), "secao-de-importacao")
        self.assertEqual(slugify("gráfico"), "grafico")

    def test_tokenize_is_unicode_aware(self) -> None:
        tokens = tokenize("seção de importação")
        self.assertIn("secao", tokens)
        self.assertIn("importacao", tokens)

    def test_bm25_rare_term_in_short_doc_beats_common_term_in_long_doc(self) -> None:
        query = tokenize("merge-by-cpf")
        short = tokenize("ADR: we chose merge-by-cpf for the cadastro join.")
        long = tokenize("journal " * 400 + " the the the the work work work")
        scores = bm25_scores(query, [long, short])
        self.assertGreater(scores[1], scores[0])


class BudgetHonestyTests(unittest.TestCase):
    def test_bundle_never_exceeds_budget_on_varied_store_sizes(self) -> None:
        for n_files in (10, 50):
            with self.subTest(n=n_files), tempfile.TemporaryDirectory() as temp:
                initialize_memory_fabric(temp)
                for i in range(n_files):
                    _write_store_file(
                        temp,
                        f"bulk/entry-{i:03d}",
                        "x" * 800,
                        priority="medium",
                    )
                for budget in (400, 4000):
                    bundle = read_combined_context(temp, max_tokens=budget)
                    self.assertLessEqual(
                        bundle["estimated_tokens"],
                        bundle["token_budget"],
                        f"n={n_files} budget={budget} used={bundle['estimated_tokens']}",
                    )

    def test_compact_omission_line_not_per_section_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            for i in range(20):
                _write_store_file(temp, f"bulk/entry-{i:03d}", "keyword unique-" + ("z" * 4000))
            bundle = read_combined_context(temp, max_tokens=600, query="unique")
            self.assertLessEqual(bundle["estimated_tokens"], bundle["token_budget"])
            self.assertTrue(
                bundle["omitted_sections"],
                "20 large store files must overflow a 600-token budget",
            )
            self.assertIn("more sections omitted", bundle["text"])
            self.assertNotIn("omitted because it exceeded", bundle["text"])

    def test_steering_over_half_budget_emits_named_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            rules = Path(temp) / ".ai-memory" / "framework-rules.md"
            text = rules.read_text(encoding="utf-8")
            rules.write_text(text + (" steer " * 2000), encoding="utf-8")
            bundle = read_combined_context(temp, max_tokens=4000)
            self.assertTrue(any("framework-rules" in w for w in bundle["warnings"]))
            self.assertTrue(any("Always-on steering" in w for w in bundle["warnings"]))

    def test_priority_survives_query_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(
                temp,
                "debt/resolved-item",
                "keyword keyword keyword keyword keyword leftover resolved",
                priority="low",
                title="Resolved leftover",
            )
            _write_store_file(
                temp,
                "architecture/core",
                "keyword once in a short architecture map",
                priority="high",
                title="Architecture core",
            )
            bundle = read_combined_context(temp, max_tokens=800, query="keyword")
            included = [s for s in bundle["included_sections"] if s.startswith("store/")]
            self.assertTrue(included)
            self.assertEqual(included[0], "store/architecture/core")

    def test_file_share_cap_stops_one_journal_monopolizing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(
                temp,
                "episodic/giant-journal",
                "journal " * 8000,
                priority="high",
                title="Giant journal",
            )
            for i in range(8):
                _write_store_file(
                    temp,
                    f"architecture/topic-{i}",
                    f"architecture topic {i} unique-marker-{i}",
                    priority="high",
                    title=f"Topic {i}",
                )
            os.environ["MEMORY_FABRIC_STARTUP_MODE"] = "full"
            try:
                bundle = read_combined_context(temp, max_tokens=2000, query="architecture topic")
            finally:
                os.environ.pop("MEMORY_FABRIC_STARTUP_MODE", None)
            arch = [s for s in bundle["included_sections"] if s.startswith("store/architecture/")]
            self.assertGreaterEqual(len(arch), 2)
            self.assertLessEqual(bundle["estimated_tokens"], bundle["token_budget"])

    def test_search_excludes_candidates_on_python_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            cand = Path(temp) / ".ai-memory" / "candidates" / "snap" / "memory-store" / "noise.md"
            cand.parent.mkdir(parents=True, exist_ok=True)
            cand.write_text("only-in-candidates unique-needle-zzz", encoding="utf-8")
            with mock.patch("shutil.which", return_value=None):
                results = keyword_search(temp, "unique-needle-zzz")
            self.assertEqual(results, [])

    def test_search_results_are_score_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(temp, "decisions/rare-adr", "unique-xyzzy rare term in a short ADR")
            _write_store_file(
                temp,
                "episodic/long-journal",
                "the the the " * 200 + " unique-xyzzy",
            )
            with mock.patch("shutil.which", return_value=None):
                results = keyword_search(temp, "unique-xyzzy")
            self.assertGreaterEqual(len(results), 2)
            self.assertIn("score", results[0])
            self.assertGreaterEqual(results[0]["score"], results[1]["score"])
            self.assertEqual(results[0]["section"], "store:decisions/rare-adr")


class MapsFirstAndRetrieveTests(unittest.TestCase):
    def test_no_query_startup_excludes_granular_store_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(temp, "architecture/detail", "granular body should not dump")
            _write_store_file(temp, "episodic/commits/2026-08-15/abc1234", "commit capture raw")
            bundle = read_combined_context(temp, max_tokens=4000)
            store_bodies = [
                s
                for s in bundle["included_sections"]
                if s.startswith("store/") and s != "store/index"
            ]
            self.assertEqual(store_bodies, [])
            self.assertFalse(any("episodic/commits" in s for s in bundle["included_sections"]))

    def test_full_startup_mode_can_include_store_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(temp, "architecture/detail", "visible in full mode")
            os.environ["MEMORY_FABRIC_STARTUP_MODE"] = "full"
            try:
                bundle = read_combined_context(temp, max_tokens=20000)
            finally:
                os.environ.pop("MEMORY_FABRIC_STARTUP_MODE", None)
            self.assertTrue(
                any(s.startswith("store/architecture/detail") for s in bundle["included_sections"])
            )

    def test_deleting_index_does_not_change_query_hits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(temp, "decisions/jwt-auth", "we chose jwt for service auth")
            first = read_combined_context(temp, max_tokens=4000, query="jwt auth")
            delete_index(temp)
            second = read_combined_context(temp, max_tokens=4000, query="jwt auth")
            self.assertIn("store/decisions/jwt-auth", first["included_sections"])
            self.assertIn("store/decisions/jwt-auth", second["included_sections"])

    def test_context_for_task_includes_relevant_adr(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(
                temp,
                "decisions/merge-by-cpf",
                "We chose MERGE-by-CPF because the cadastro key is the citizen CPF.",
                priority="high",
                title="MERGE-by-CPF",
            )
            _write_store_file(temp, "episodic/noise", "unrelated daily notes " * 50)
            pack = context_for_task(temp, "why did we choose MERGE-by-CPF?")
            self.assertIn("store/decisions/merge-by-cpf", pack["included_sections"])
            self.assertIn("MERGE-by-CPF", pack["text"])
            self.assertLessEqual(pack["estimated_tokens"], pack["token_budget"])


class SummaryAndVerifyTests(unittest.TestCase):
    def test_write_rejects_generic_contexto_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/foo",
                "# Heading\n\nWe picked SQLite for the frontmatter index so ranking needs no extra dependency.",
                title="Contexto",
            )
            text = (Path(temp) / ".ai-memory" / "memory-store" / "decisions" / "foo.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("summary: Contexto", text)
            self.assertNotIn('summary: "Contexto"', text)

    def test_repo_citation_is_skipped_not_broken(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/sister",
                "Depends on the sister repo.",
                title="Sister repo citation",
                evidence=["repo:agregacao/src/foo.py"],
            )
            result = verify_evidence(temp, mark_broken=False)
            self.assertTrue(result["ok"])
            self.assertEqual(result["broken"], [])
            self.assertTrue(result["skipped"])

    def test_write_regenerates_category_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "architecture/new-fact",
                "A concrete architecture fact about the read path.",
                title="Read path fact",
            )
            arch = Path(temp) / ".ai-memory" / "architecture.md"
            self.assertTrue(arch.exists())
            self.assertIn("architecture/new-fact", arch.read_text(encoding="utf-8"))


class FailureAndReviewTests(unittest.TestCase):
    def test_integrity_error_collapses_across_languages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            first = write_failure_memory(
                temp,
                "IntegrityError: UNIQUE constraint failed at site A",
                "Add a get-or-create.",
            )
            second = write_failure_memory(
                temp,
                "IntegrityError: falha na restrição UNIQUE no site B",
                "Use get-or-create.",
            )
            self.assertEqual(Path(first["path"]).name, Path(second["path"]).name)
            text = Path(second["path"]).read_text(encoding="utf-8")
            self.assertIn("occurrences: 2", text)

    def test_review_list_and_promote(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            dest = Path(temp) / ".ai-memory" / "memory-store" / "episodic" / "commits"
            dest.mkdir(parents=True, exist_ok=True)
            write_memory_store(
                temp,
                "episodic/commits/abc1234",
                "### commit `abc1234` — feat: add auth\n\n- source: passive-capture\n",
                title="Commit abc1234 — feat: add auth",
                tags=["episodic", "passive-capture", "needs-review"],
                priority="low",
            )
            listed = list_pending_reviews(temp)
            self.assertGreaterEqual(listed["total"], 1)
            paths = [e["store_path"] for e in listed["entries"]]
            self.assertIn("episodic/commits/abc1234", paths)
            promote_review(temp, "episodic/commits/abc1234", "architecture/auth")
            dest_text = (
                Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "auth.md"
            ).read_text(encoding="utf-8")
            self.assertIn("promoted_from", dest_text)
            listed_after = list_pending_reviews(temp)
            self.assertNotIn(
                "episodic/commits/abc1234",
                [e["store_path"] for e in listed_after["entries"]],
            )
            drop_review(temp, "architecture/auth")  # not pending; just ensure no crash


class HookGuardTests(unittest.TestCase):
    def test_denies_write_into_memory_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            target = str(Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "x.md")
            decision = evaluate_hook_payload(
                temp, {"tool_name": "Write", "tool_input": {"path": target}}
            )
            self.assertEqual(decision["permission"], "deny")
            self.assertIn("write_memory_store_tool", decision["agent_message"])

    def test_allows_steering_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            target = str(Path(temp) / ".ai-memory" / "framework-rules.md")
            decision = evaluate_hook_payload(
                temp, {"tool_name": "Write", "tool_input": {"path": target}}
            )
            self.assertEqual(decision["permission"], "allow")

    def test_fail_open_on_garbage_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            code, payload = run_hook_guard(temp, stdin_text="not-json")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(payload)["permission"], "allow")


class SkipDumpAndCursorInstallTests(unittest.TestCase):
    def test_skip_startup_dump_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            os.environ["MEMORY_FABRIC_SKIP_STARTUP_DUMP"] = "1"
            try:
                bundle = read_combined_context(temp)
            finally:
                os.environ.pop("MEMORY_FABRIC_SKIP_STARTUP_DUMP", None)
            self.assertIn("Skipping a second dump", bundle["text"])
            self.assertTrue(any("Skipped full startup dump" in w for w in bundle["warnings"]))

    def test_cursor_hooks_install(self) -> None:
        from memory_fabric.client_hooks import install_hooks

        with tempfile.TemporaryDirectory() as temp:
            result = install_hooks(temp, "cursor")
            self.assertTrue(result["ok"])
            self.assertTrue(result["supported"])
            path = Path(temp) / ".cursor" / "hooks.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["version"], 1)
            hooks = config["hooks"]
            self.assertIn("sessionStart", hooks)
            self.assertIn("stop", hooks)
            self.assertIn("preToolUse", hooks)
            self.assertIn("beforeReadFile", hooks)
            self.assertIn("preCompact", hooks)
            self.assertEqual(hooks["stop"][0]["loop_limit"], 5)
            self.assertIn("hook-guard", hooks["preToolUse"][0]["command"])


if __name__ == "__main__":
    unittest.main()
