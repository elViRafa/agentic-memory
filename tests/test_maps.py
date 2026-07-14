"""Store-first model tests: generated root maps, steering sections, priority
interleave in context assembly, flat-write deprecation, and eval freshness."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from memory_fabric.eval import evaluate_memory_fabric as _async_evaluate_memory_fabric
from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.storage import (
    _ordered_context_files,
    category_fingerprint,
    initialize_memory_fabric,
    read_combined_context,
    regenerate_maps,
    write_local_memory,
    write_memory_store,
)


def evaluate_memory_fabric(*args, **kwargs):
    return asyncio.run(_async_evaluate_memory_fabric(*args, **kwargs))


def _memory_dir(temp: str) -> Path:
    return Path(temp) / ".ai-memory"


class GeneratedMapsTests(unittest.TestCase):
    def test_regenerate_creates_generated_map_from_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "architecture/auth-flow",
                "# Auth Flow\n\nJWT with refresh tokens.",
                title="Auth Flow",
                priority="high",
            )

            result = regenerate_maps(_memory_dir(temp))

            self.assertIn("architecture.md", result["maps_written"])
            metadata, body = parse_frontmatter(
                (_memory_dir(temp) / "architecture.md").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata.get("generated"))
            self.assertEqual(metadata.get("generated_from"), "memory-store/architecture")
            self.assertEqual(
                metadata.get("store_fingerprint"),
                category_fingerprint(_memory_dir(temp) / "memory-store", "architecture"),
            )
            self.assertIn("Auth Flow", body)
            self.assertIn("architecture/auth-flow", body)

    def test_regenerate_is_idempotent_when_store_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "decisions/db-choice", "Postgres.", title="DB Choice")

            first = regenerate_maps(_memory_dir(temp))
            self.assertIn("decisions.md", first["maps_written"])
            before = (_memory_dir(temp) / "decisions.md").read_text(encoding="utf-8")

            second = regenerate_maps(_memory_dir(temp))
            self.assertEqual(second["maps_written"], [])
            after = (_memory_dir(temp) / "decisions.md").read_text(encoding="utf-8")
            self.assertEqual(before, after)

    def test_legacy_handwritten_map_is_folded_not_destroyed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "decisions/db-choice", "Postgres.", title="DB Choice")

            legacy_meta = {
                "section": "decisions",
                "summary": "Hand-maintained decisions map.",
                "priority": "high",
                "tags": ["decisions"],
                "schema_version": "1.3",
            }
            legacy_body = "# Decisions\n\nWe chose gRPC over REST for internal APIs.\n"
            (_memory_dir(temp) / "decisions.md").write_text(
                dump_frontmatter(legacy_meta, legacy_body), encoding="utf-8"
            )

            result = regenerate_maps(_memory_dir(temp))

            self.assertIn("decisions/map-notes-pending-review", result["legacy_folded"])
            fold_path = (
                _memory_dir(temp) / "memory-store" / "decisions" / "map-notes-pending-review.md"
            )
            self.assertTrue(fold_path.exists())
            self.assertIn("gRPC over REST", fold_path.read_text(encoding="utf-8"))

            metadata, body = parse_frontmatter(
                (_memory_dir(temp) / "decisions.md").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata.get("generated"))
            self.assertIn("decisions/map-notes-pending-review", body)
            self.assertIn("decisions/db-choice", body)

    def test_hand_edit_on_generated_map_is_folded_on_next_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "architecture/core", "Core notes.", title="Core")
            regenerate_maps(_memory_dir(temp))

            map_path = _memory_dir(temp) / "architecture.md"
            metadata, body = parse_frontmatter(map_path.read_text(encoding="utf-8"))
            map_path.write_text(
                dump_frontmatter(metadata, body + "\nManual addition that must survive.\n"),
                encoding="utf-8",
            )

            result = regenerate_maps(_memory_dir(temp))

            self.assertIn("architecture/map-notes-pending-review", result["legacy_folded"])
            fold_path = (
                _memory_dir(temp) / "memory-store" / "architecture" / "map-notes-pending-review.md"
            )
            self.assertIn(
                "Manual addition that must survive.", fold_path.read_text(encoding="utf-8")
            )
            new_meta, _new_body = parse_frontmatter(map_path.read_text(encoding="utf-8"))
            self.assertTrue(new_meta.get("generated"))

    def test_steering_sections_are_never_overwritten_by_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp, "ubiquitous-language/tenant", "Tenant means paying org.", title="Tenant"
            )

            before = (_memory_dir(temp) / "ubiquitous-language.md").read_text(encoding="utf-8")
            result = regenerate_maps(_memory_dir(temp))
            after = (_memory_dir(temp) / "ubiquitous-language.md").read_text(encoding="utf-8")

            self.assertEqual(before, after)
            self.assertNotIn("ubiquitous-language.md", result["maps_written"])

    def test_map_token_cap_elides_lowest_priority_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            for i in range(15):
                write_memory_store(
                    temp,
                    f"debt/item-{i:02d}",
                    f"Debt item number {i} with a reasonably long description body.",
                    title=f"Debt Item {i:02d}",
                    priority="low",
                )

            os.environ["MEMORY_FABRIC_MAP_TOKEN_CAP"] = "60"
            try:
                regenerate_maps(_memory_dir(temp))
            finally:
                os.environ.pop("MEMORY_FABRIC_MAP_TOKEN_CAP", None)

            _metadata, body = parse_frontmatter(
                (_memory_dir(temp) / "debt.md").read_text(encoding="utf-8")
            )
            self.assertIn("more entries — see `memory-store/index.md`", body)


class SteeringAndOrderingTests(unittest.TestCase):
    def test_steering_sections_always_loaded_under_tight_budget(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            tempfile.TemporaryDirectory() as global_home,
        ):
            os.environ["MEMORY_FABRIC_HOME"] = global_home
            try:
                initialize_memory_fabric(temp)
                write_local_memory(
                    temp,
                    "framework-rules",
                    "# Framework Rules\n\nAlways use dependency injection for services.",
                    mode="replace",
                )
                write_memory_store(
                    temp,
                    "architecture/huge",
                    "Filler line for budget pressure.\n" * 200,
                    title="Huge",
                )

                bundle = read_combined_context(temp, max_tokens=10)

                self.assertIn("local/framework-rules", bundle["included_sections"])
                self.assertIn("local/ubiquitous-language", bundle["included_sections"])
                self.assertIn("store/architecture/huge", bundle["omitted_sections"])
            finally:
                os.environ.pop("MEMORY_FABRIC_HOME", None)

    def test_context_interleaves_store_and_local_by_priority(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            tempfile.TemporaryDirectory() as global_home,
        ):
            os.environ["MEMORY_FABRIC_HOME"] = global_home
            try:
                initialize_memory_fabric(temp)
                write_memory_store(temp, "architecture/hot", "Hot fact.", priority="high")
                write_memory_store(temp, "schemas/warm", "Warm fact.", priority="medium")
                write_memory_store(temp, "debt/cold", "Cold fact.", priority="low")

                ordered = [p.name for p in _ordered_context_files(temp)]

                # Store files compete on priority with local maps — no bias.
                self.assertLess(ordered.index("hot.md"), ordered.index("warm.md"))
                self.assertLess(ordered.index("warm.md"), ordered.index("cold.md"))
                # Steering sections are handled separately, not budgeted here.
                self.assertNotIn("framework-rules.md", ordered)
                self.assertNotIn("ubiquitous-language.md", ordered)
                # Regression: low-priority files used to be silently dropped
                # (`>= 3` filter against a 0-2 priority scale).
                self.assertIn("debt.md", ordered)
                self.assertIn("cold.md", ordered)
            finally:
                os.environ.pop("MEMORY_FABRIC_HOME", None)


class FlatWriteDeprecationTests(unittest.TestCase):
    def test_write_to_map_section_warns_deprecated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_local_memory(temp, "decisions", "New decision.", mode="append")
            self.assertTrue(any("DEPRECATED" in w for w in result["warnings"]))
            self.assertTrue(any("generated map" in w for w in result["warnings"]))

    def test_write_to_steering_section_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_local_memory(
                temp, "framework-rules", "Prefer composition.", mode="append"
            )
            self.assertFalse(any("DEPRECATED" in w for w in result["warnings"]))


class EvalMapFreshnessTests(unittest.TestCase):
    def test_fresh_and_stale_generated_maps_are_scored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "architecture/one", "First fact.", title="One")
            regenerate_maps(_memory_dir(temp))

            result = evaluate_memory_fabric(temp, save_report=False)
            check_ids = [
                check["id"] for category in result["categories"] for check in category["checks"]
            ]
            self.assertIn("memory_store_present", check_ids)
            self.assertIn("architecture_map_fresh", check_ids)

            # A store write after generation makes the map stale.
            write_memory_store(temp, "architecture/two", "Second fact.", title="Two")
            result2 = evaluate_memory_fabric(temp, save_report=False)
            check_ids2 = [
                check["id"] for category in result2["categories"] for check in category["checks"]
            ]
            self.assertIn("architecture_map_stale", check_ids2)


class StoreFileMetadataEvalTests(unittest.TestCase):
    """Regressions found by the v0.8 migration dogfood run (2026-07-13)."""

    def _failed_check_ids(self, temp: str) -> list[str]:
        result = evaluate_memory_fabric(temp, save_report=False)
        return [
            check["id"]
            for category in result["categories"]
            for check in category["checks"]
            if check["status"] == "fail"
        ]

    def test_store_files_are_identified_by_store_path_not_section(self) -> None:
        # write_memory_store writes `store_path`, never `section`; the eval
        # used to fail every such file with <stem>_section_missing.
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "decisions/db-choice", "Postgres.", title="DB Choice")

            failed = self._failed_check_ids(temp)
            self.assertNotIn("db-choice_section_missing", failed)
            self.assertNotIn("db-choice_store_path_missing", failed)

    def test_consolidated_memory_artifact_is_not_scored(self) -> None:
        # consolidated_memory.md is a compiled Dreaming artifact with no
        # frontmatter; every other subsystem ignores it, and the eval's
        # hand-copied ignore rule had drifted and penalized it.
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            (_memory_dir(temp) / "consolidated_memory.md").write_text(
                "# Compiled context document\n\nNo frontmatter on purpose.\n",
                encoding="utf-8",
            )

            failed = self._failed_check_ids(temp)
            self.assertNotIn("consolidated_memory_frontmatter_invalid", failed)


if __name__ == "__main__":
    unittest.main()
