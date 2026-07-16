"""Stage 3 (ROADMAP_CAPTURE_HOOKS.md): regression-guard the capture-rate proof.

Locks in the launch number from ROADMAP.md's success-metrics table ("Capture
rate (hooks on): 100% of benchmark sessions journaled with a non-compliant
agent") so it can't silently drift — a future change to guard_journal's
semantics, capture_commit's filter, or capture_stats' counting would fail
this test, not just a manually re-run script.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


def _load_benchmark_module() -> ModuleType:
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "capture_rate_benchmark.py"
    spec = importlib.util.spec_from_file_location("capture_rate_benchmark", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bench = _load_benchmark_module()


class CaptureRateBenchmarkTests(unittest.TestCase):
    def test_instructions_only_never_journals_a_non_compliant_agent(self) -> None:
        results = _bench.run_benchmark(sessions=5)
        baseline = results["instructions_only"]

        self.assertEqual(baseline["sessions_journaled"], 0)
        self.assertEqual(baseline["journal_rate_pct"], 0.0)

    def test_hooks_enabled_always_journals_the_same_non_compliant_agent(self) -> None:
        results = _bench.run_benchmark(sessions=5)
        enforced = results["hooks_enabled"]

        self.assertEqual(enforced["sessions_journaled"], 5)
        self.assertEqual(enforced["journal_rate_pct"], 100.0)

    def test_passive_commit_capture_is_unconditional_in_both_modes(self) -> None:
        """Commit capture runs off the git post-commit hook (Stage 0/1), not
        the client-side session hooks — it must hold steady regardless of
        whether session-journal enforcement is on."""
        results = _bench.run_benchmark(sessions=5)

        self.assertEqual(results["instructions_only"]["commit_capture_rate_pct"], 100.0)
        self.assertEqual(results["hooks_enabled"]["commit_capture_rate_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
