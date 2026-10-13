"""R6-3: coding-memory benchmark — memory-on vs memory-off, CLI, suite file."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory_fabric.cli import main
from memory_fabric.eval.bench import run_coding_memory_benchmark
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


if __name__ == "__main__":
    unittest.main()
