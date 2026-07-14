"""Migration tooling tests (ROADMAP Phase 2.2, v0.8): heuristic split, LLM
naming with fallback, dry-run purity, snapshot/rollback safety, resumable
re-runs, exclusion rules, and init's store-category scaffolding."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.cli import main as cli_main
from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.storage import (
    initialize_memory_fabric,
    rollback,
    write_memory_store,
)
from memory_fabric.storage import (
    migrate_memory as _async_migrate_memory,
)
from memory_fabric.storage.migrate import _slugify, _split_by_headings
from memory_fabric.templates import STORE_CATEGORY_SCAFFOLD


def migrate_memory(*args, **kwargs):
    return asyncio.run(_async_migrate_memory(*args, **kwargs))


def _memory_dir(temp: str) -> Path:
    return Path(temp) / ".ai-memory"


LEGACY_BODY = """# Architecture Memory

The system is a local-first memory layer for coding agents.

## Core Characteristics

- File-first storage
- Zero required dependencies

## Component Boundaries

CLI and MCP server share the storage package.

```python
## not a heading, just code
x = 1
```

Closing notes after the fence.
"""


def _write_legacy_section(
    temp: str,
    section: str = "architecture",
    body: str = LEGACY_BODY,
    **meta_overrides,
) -> None:
    metadata = {
        "section": section,
        "summary": "Hand-written legacy section.",
        "priority": "high",
        "tags": [section],
        "schema_version": "1.3",
    }
    metadata.update(meta_overrides)
    (_memory_dir(temp) / f"{section}.md").write_text(
        dump_frontmatter(metadata, body), encoding="utf-8"
    )


class HeuristicSplitTests(unittest.TestCase):
    def test_split_is_fence_aware_and_keeps_preamble(self) -> None:
        chunks = _split_by_headings(LEGACY_BODY)
        headings = [heading for heading, _content in chunks]
        self.assertEqual(headings, ["", "Core Characteristics", "Component Boundaries"])

        preamble = chunks[0][1]
        self.assertIn("local-first memory layer", preamble)

        boundaries = chunks[2][1]
        self.assertIn("## not a heading, just code", boundaries)
        self.assertIn("Closing notes after the fence.", boundaries)

    def test_lone_h1_preamble_is_dropped(self) -> None:
        chunks = _split_by_headings("# Just A Title\n\n## Real Content\n\nBody here.\n")
        self.assertEqual([heading for heading, _ in chunks], ["Real Content"])

    def test_no_headings_yields_single_overview_chunk(self) -> None:
        chunks = _split_by_headings("Free-form notes without any headings.\n")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][0], "")
        self.assertIn("Free-form notes", chunks[0][1])

    def test_slugify(self) -> None:
        self.assertEqual(_slugify("Core Characteristics"), "core-characteristics")
        self.assertEqual(_slugify("1. System Requirements"), "1-system-requirements")
        self.assertEqual(_slugify("???"), "")


class MigrateApplyTests(unittest.TestCase):
    def test_migrate_splits_legacy_section_into_store_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)

            result = migrate_memory(temp, use_llm=False)

            self.assertTrue(result["changed"])
            self.assertEqual(result["sections_migrated"], ["architecture"])
            self.assertIsNotNone(result["snapshot"])
            self.assertIn("architecture.md", result["maps_written"])

            store = _memory_dir(temp) / "memory-store" / "architecture"
            overview_meta, overview_body = parse_frontmatter(
                (store / "overview.md").read_text(encoding="utf-8")
            )
            self.assertIn("local-first memory layer", overview_body)
            self.assertEqual(overview_meta["priority"], "high")
            self.assertIn("migrated", overview_meta["tags"])

            _meta, chars_body = parse_frontmatter(
                (store / "core-characteristics.md").read_text(encoding="utf-8")
            )
            self.assertIn("- File-first storage", chars_body)

            _meta, bounds_body = parse_frontmatter(
                (store / "component-boundaries.md").read_text(encoding="utf-8")
            )
            self.assertIn("## not a heading, just code", bounds_body)
            self.assertIn("Closing notes after the fence.", bounds_body)

            map_meta, _map_body = parse_frontmatter(
                (_memory_dir(temp) / "architecture.md").read_text(encoding="utf-8")
            )
            self.assertTrue(map_meta.get("generated"))
            self.assertEqual(map_meta.get("generated_from"), "memory-store/architecture")

            statuses = {e["status"] for e in result["plan"][0]["entries"]}
            self.assertEqual(statuses, {"written"})

    def test_dry_run_plans_everything_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)
            before = (_memory_dir(temp) / "architecture.md").read_text(encoding="utf-8")

            result = migrate_memory(temp, dry_run=True, use_llm=False)

            self.assertFalse(result["changed"])
            self.assertIsNone(result["snapshot"])
            self.assertEqual(result["entries_written"], [])
            self.assertEqual(len(result["plan"]), 1)
            self.assertEqual({e["status"] for e in result["plan"][0]["entries"]}, {"planned"})
            store = _memory_dir(temp) / "memory-store" / "architecture"
            self.assertEqual(list(store.glob("*.md")), [])
            self.assertFalse((_memory_dir(temp) / "snapshots").exists())
            after = (_memory_dir(temp) / "architecture.md").read_text(encoding="utf-8")
            self.assertEqual(before, after)

    def test_fresh_init_has_nothing_to_migrate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = migrate_memory(temp, use_llm=False)
            self.assertFalse(result["changed"])
            self.assertEqual(result["plan"], [])
            self.assertIsNone(result["snapshot"])

    def test_steering_generated_and_index_are_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            steering_path = _memory_dir(temp) / "framework-rules.md"
            steering_meta, _ = parse_frontmatter(steering_path.read_text(encoding="utf-8"))
            steering_path.write_text(
                dump_frontmatter(steering_meta, "# Rules\n\n## Testing\n\nAlways run pytest.\n"),
                encoding="utf-8",
            )
            before = steering_path.read_text(encoding="utf-8")

            result = migrate_memory(temp, use_llm=False)

            self.assertFalse(result["changed"])
            self.assertEqual(before, steering_path.read_text(encoding="utf-8"))

            explicit = migrate_memory(temp, sections=["framework-rules"], use_llm=False)
            self.assertFalse(explicit["changed"])
            self.assertTrue(any("steering" in warning for warning in explicit["warnings"]))

    def test_second_run_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)
            first = migrate_memory(temp, use_llm=False)
            self.assertTrue(first["changed"])

            second = migrate_memory(temp, use_llm=False)
            self.assertFalse(second["changed"])
            self.assertEqual(second["plan"], [])

    def test_rollback_restores_the_flat_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)

            result = migrate_memory(temp, use_llm=False)
            snapshot = result["snapshot"]
            assert snapshot is not None

            rollback(temp, snapshot)

            metadata, body = parse_frontmatter(
                (_memory_dir(temp) / "architecture.md").read_text(encoding="utf-8")
            )
            self.assertFalse(metadata.get("generated"))
            self.assertIn("## Core Characteristics", body)

    def test_identical_existing_entry_makes_rerun_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)
            # Simulate a partial earlier run: one chunk already landed verbatim.
            write_memory_store(
                temp,
                "architecture/core-characteristics",
                "- File-first storage\n- Zero required dependencies",
            )

            result = migrate_memory(temp, use_llm=False)

            entries = {e["store_path"]: e["status"] for e in result["plan"][0]["entries"]}
            self.assertEqual(entries["architecture/core-characteristics"], "already-migrated")
            self.assertNotIn("architecture/core-characteristics", result["entries_written"])
            self.assertIn("architecture/overview", result["entries_written"])
            store = _memory_dir(temp) / "memory-store" / "architecture"
            self.assertFalse((store / "core-characteristics-migrated.md").exists())

    def test_different_existing_entry_gets_migrated_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)
            write_memory_store(
                temp,
                "architecture/core-characteristics",
                "A genuinely different granular memory that must survive.",
            )

            result = migrate_memory(temp, use_llm=False)

            self.assertIn("architecture/core-characteristics-migrated", result["entries_written"])
            store = _memory_dir(temp) / "memory-store" / "architecture"
            _meta, kept = parse_frontmatter(
                (store / "core-characteristics.md").read_text(encoding="utf-8")
            )
            self.assertIn("genuinely different", kept)
            _meta, moved = parse_frontmatter(
                (store / "core-characteristics-migrated.md").read_text(encoding="utf-8")
            )
            self.assertIn("- File-first storage", moved)

    def test_secrets_are_redacted_in_migrated_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            secret = "sk-" + "a1B2c3D4e5F6g7H8j9K0"
            _write_legacy_section(
                temp,
                body=f"# Notes\n\n## Credentials Mistake\n\nOld key was {secret} — rotate it.\n",
            )

            result = migrate_memory(temp, use_llm=False)

            self.assertGreaterEqual(result["redactions"], 1)
            store = _memory_dir(temp) / "memory-store" / "architecture"
            _meta, body = parse_frontmatter(
                (store / "credentials-mistake.md").read_text(encoding="utf-8")
            )
            self.assertNotIn(secret, body)
            self.assertIn("[REDACTED_SECRET]", body)

    def test_unknown_requested_section_warns(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = migrate_memory(temp, sections=["nope"], use_llm=False)
            self.assertTrue(
                any("not found or not migratable: nope" in w for w in result["warnings"])
            )


class MigrateLlmNamingTests(unittest.TestCase):
    def _migrate_with_llm(self, temp: str, response: str, use_llm: bool | None = None):
        async_response = mock.AsyncMock(return_value=response)
        with (
            mock.patch("memory_fabric.storage.migrate._is_llm_ready", return_value=True),
            mock.patch("memory_fabric.storage.migrate.call_llm", async_response),
        ):
            result = migrate_memory(temp, use_llm=use_llm)
        return result, async_response

    def test_valid_llm_names_are_applied_content_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)
            response = json.dumps(
                {
                    "entries": [
                        {
                            "index": 0,
                            "store_path": "architecture/system-overview",
                            "title": "System Overview",
                            "tags": ["overview", "design"],
                        }
                    ]
                }
            )

            result, _ = self._migrate_with_llm(temp, response)

            self.assertTrue(result["plan"][0]["llm_named"])
            store = _memory_dir(temp) / "memory-store" / "architecture"
            meta, body = parse_frontmatter(
                (store / "system-overview.md").read_text(encoding="utf-8")
            )
            # Content is the verbatim heuristic chunk — the LLM only named it.
            self.assertIn("local-first memory layer", body)
            self.assertEqual(meta["title"], "System Overview")
            self.assertEqual(meta["tags"], ["overview", "design"])
            # The other chunks keep their heuristic names.
            self.assertTrue((store / "core-characteristics.md").exists())

    def test_garbage_llm_response_falls_back_to_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)

            result, _ = self._migrate_with_llm(temp, "I cannot answer in JSON, sorry!")

            self.assertFalse(result["plan"][0]["llm_named"])
            self.assertTrue(any("heuristic names" in w for w in result["warnings"]))
            store = _memory_dir(temp) / "memory-store" / "architecture"
            self.assertTrue((store / "overview.md").exists())
            self.assertTrue((store / "core-characteristics.md").exists())

    def test_invalid_llm_proposals_are_rejected_per_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)
            response = json.dumps(
                {
                    "entries": [
                        {"index": 0, "store_path": "other-category/wrong-prefix"},
                        {"index": 99, "store_path": "architecture/out-of-range"},
                        {"index": 1, "store_path": "architecture/too/deep/path"},
                        {"index": 2, "store_path": "architecture/UPPER CASE"},
                    ]
                }
            )

            result, _ = self._migrate_with_llm(temp, response)

            self.assertFalse(result["plan"][0]["llm_named"])
            store = _memory_dir(temp) / "memory-store" / "architecture"
            self.assertTrue((store / "overview.md").exists())
            self.assertTrue((store / "component-boundaries.md").exists())

    def test_use_llm_false_never_calls_the_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)

            _result, async_response = self._migrate_with_llm(temp, "{}", use_llm=False)

            async_response.assert_not_called()


class InitScaffoldTests(unittest.TestCase):
    def test_init_scaffolds_store_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = initialize_memory_fabric(temp)
            store = _memory_dir(temp) / "memory-store"
            for category in STORE_CATEGORY_SCAFFOLD:
                self.assertTrue((store / category / ".gitkeep").exists(), category)
            self.assertIn(str(store / "architecture" / ".gitkeep"), result["files_created"])
            # Derived-from-templates set plus the write-path categories.
            self.assertEqual(
                set(STORE_CATEGORY_SCAFFOLD),
                {"architecture", "decisions", "schemas", "debt", "episodic", "failures", "rules"},
            )

    def test_init_scaffold_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            second = initialize_memory_fabric(temp)
            scaffold_paths = [p for p in second["files_created"] if ".gitkeep" in p]
            self.assertEqual(scaffold_paths, [])


class MigrateCliTests(unittest.TestCase):
    def test_cli_migrate_dry_run_json_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cli_main(["--cwd", temp, "--json", "migrate", "--dry-run", "--no-llm"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["sections_migrated"], [])
            self.assertEqual(payload["plan"][0]["section"], "architecture")
            self.assertGreaterEqual(len(payload["plan"][0]["entries"]), 3)

    def test_cli_migrate_human_output_prints_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_legacy_section(temp)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cli_main(["--cwd", temp, "migrate", "--dry-run", "--no-llm"])

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("Migration plan (dry run):", output)
            self.assertIn("architecture/core-characteristics", output)


if __name__ == "__main__":
    unittest.main()
