"""R6-3: coding-memory benchmark — memory-on vs memory-off, CLI, suite file."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_fabric.cli import main
from memory_fabric.eval.bench import _score_task, run_coding_memory_benchmark
from memory_fabric.storage import initialize_memory_fabric, write_memory_store


class CodingMemoryBenchmarkTests(unittest.TestCase):
    def test_builtin_fixture_memory_on_beats_memory_off(self) -> None:
        result = run_coding_memory_benchmark(fixture="builtin", k=5)
        self.assertEqual(result["kind"], "coding-memory")
        self.assertEqual(result["memory_on_recall"], 1.0)
        self.assertEqual(result["memory_off_recall"], 0.0)
        self.assertGreater(result["lift"], 0)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["tasks"]), 4)
        for task in result["tasks"]:
            self.assertEqual(task["memory_on_recall"], 1.0, task)
            self.assertEqual(task["memory_off_recall"], 0.0, task)
            self.assertTrue(task["memory_on_token_hit"], task)
            self.assertFalse(task["memory_off_token_hit"], task)
            self.assertTrue(task["search"]["memory_on"]["passed"], task)
            self.assertTrue(task["task_context"]["memory_on"]["passed"], task)

    def test_project_fixture_uses_live_store_and_suite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/auth-jwt",
                "We chose JWT refresh tokens because sessions cannot span mobile clients.",
                title="JWT refresh tokens",
            )
            suite = Path(temp) / "suite.yaml"
            suite.write_text(
                "- id: auth\n"
                "  query: which auth approach did we pick and why?\n"
                "  expected_store_paths:\n"
                "    - decisions/auth-jwt\n"
                "  expected_tokens:\n"
                "    - JWT refresh\n",
                encoding="utf-8",
            )
            result = run_coding_memory_benchmark(temp, fixture=temp, suite_path=str(suite), k=5)
            self.assertEqual(result["memory_on_recall"], 1.0)
            self.assertEqual(result["memory_off_recall"], 0.0)
            self.assertTrue(result["passed"])

    def test_cli_builtin_exits_zero(self) -> None:
        code = main(["bench", "--json"])
        self.assertEqual(code, 0)


class BenchSuiteParseTests(unittest.TestCase):
    def test_json_suite_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "rules/test-file-naming",
                "New Python tests must be named test_*.py.",
                title="Test naming",
            )
            suite = Path(temp) / "suite.json"
            suite.write_text(
                json.dumps(
                    [
                        {
                            "id": "naming",
                            "query": "What should a new Python test file be named?",
                            "expected_store_paths": ["rules/test-file-naming"],
                            "expected_tokens": ["test_*.py"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            result = run_coding_memory_benchmark(temp, fixture=temp, suite_path=str(suite), k=5)
            self.assertEqual(result["tasks"][0]["id"], "naming")
            self.assertEqual(result["memory_on_recall"], 1.0)


class BenchEvidenceTests(unittest.TestCase):
    def test_expected_phrase_requires_rendered_source(self) -> None:
        target = "decisions/auth-jwt"
        phrase = "JWT refresh tokens"
        spec = {
            "query": "Which auth did we choose?",
            "expected_store_paths": [target],
            "expected_tokens": [phrase],
            "expected_status": "matched",
            "files_open": ["src/auth.py"],
            "max_tokens": 1200,
        }
        decoy = "store/decisions/other"
        unrelated = f"<!-- memory-fabric:{decoy} -->\n{phrase}\n"
        expected_key = f"store/{target}"
        hit = {"section": f"store:{target}"}
        cases = [
            ("search only", [hit], [decoy], unrelated, 2, [], []),
            ("metadata only", [], [decoy, expected_key], unrelated, None, [expected_key], []),
            (
                "phrase under a different source",
                [hit],
                [decoy, expected_key],
                f"<!-- memory-fabric:{expected_key} -->\nNo answer here.\n\n{unrelated}",
                2,
                [],
                [target],
            ),
        ]
        off_pack = {"text": "", "included_sections": []}
        for label, hits, included, text, rank, metadata_only, matched in cases:
            with (
                self.subTest(label=label),
                patch(
                    "memory_fabric.eval.bench.keyword_search",
                    side_effect=[[{"section": "index"}, *hits], []],
                ) as search,
                patch(
                    "memory_fabric.eval.bench.context_for_task",
                    side_effect=[{"text": text, "included_sections": included}, off_pack],
                ) as retrieve,
            ):
                task = _score_task(spec, on_cwd="on", off_cwd="off", k=2)
                self.assertEqual(task["memory_on_recall"], 1.0)
                self.assertTrue(task["memory_on_token_hit"])
                self.assertEqual(task["search"]["memory_on"]["first_correct_rank"], rank)
                self.assertEqual(task["search"]["memory_on"]["recall_at_5"], float(bool(hits)))
                score = task["task_context"]["memory_on"]
                self.assertEqual(score["metadata_only_sections"], metadata_only)
                self.assertEqual(score["matched_store_paths"], matched)
                self.assertFalse(score["passed"])
                self.assertFalse(task["passed"])
                search.assert_any_call("on", spec["query"], max_results=5)
                retrieve.assert_any_call(
                    "on", spec["query"], files_open=["src/auth.py"], max_tokens=1200, top_k=2
                )

    def test_unanswerable_counts_rendered_evidence_and_reports_inclusion_separately(self) -> None:
        steering = "local/memory_prompt"
        unrelated = "store/decisions/unrelated"
        steering_text = f"<!-- memory-fabric:{steering} -->\nFollow the local conventions.\n"
        evidence_text = f"<!-- memory-fabric:{unrelated} -->\nAn unrelated decision.\n"
        off_pack = {
            "text": steering_text,
            "included_sections": [steering],
            "retrieval_status": "no_match",
        }
        cases = [
            (steering_text, [steering], 0, True, True, [], []),
            (steering_text, [steering, unrelated], 0, True, False, [unrelated], []),
            (steering_text + evidence_text, [steering], 1, False, False, [], [unrelated]),
        ]
        for text, included, count, evidence_passed, passed, metadata_only, text_only in cases:
            with (
                self.subTest(included=included, count=count),
                patch("memory_fabric.eval.bench.keyword_search", return_value=[]),
                patch(
                    "memory_fabric.eval.bench.context_for_task",
                    side_effect=[
                        {
                            "text": text,
                            "included_sections": included,
                            "retrieval_status": "no_match",
                        },
                        off_pack,
                    ],
                ),
            ):
                task = _score_task(
                    {"query": "UNKNOWN_ID", "expected_status": "no_match"},
                    on_cwd="on",
                    off_cwd="off",
                    k=5,
                )
                self.assertTrue(task["search"]["memory_on"]["passed"])
                score = task["task_context"]["memory_on"]
                self.assertEqual(score["evidence_fragments"], count)
                self.assertEqual(score["metadata_only_sections"], metadata_only)
                self.assertEqual(score["text_only_sections"], text_only)
                self.assertEqual(score["passed"], evidence_passed)
                self.assertEqual(task["passed"], passed)


if __name__ == "__main__":
    unittest.main()
