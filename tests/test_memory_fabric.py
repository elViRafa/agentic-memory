from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.eval import evaluate_dream_quality, evaluate_memory_fabric, latest_snapshot
from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.paths import get_global_root
from memory_fabric.storage import (
    create_snapshot,
    initialize_memory_fabric,
    keyword_search,
    read_combined_context,
    read_section,
    rollback,
    write_local_memory,
)


class MemoryFabricTests(unittest.TestCase):
    def test_init_creates_scaffold_with_valid_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = initialize_memory_fabric(temp)
            memory_dir = Path(temp) / ".ai-memory"

            self.assertTrue(result["created"])
            self.assertTrue((memory_dir / "index.md").exists())
            self.assertTrue((memory_dir / ".gitignore").exists())

            metadata, _body = parse_frontmatter((memory_dir / "architecture.md").read_text(encoding="utf-8"))
            self.assertEqual(metadata["section"], "architecture")
            self.assertEqual(metadata["schema_version"], "1.3")
            self.assertIn(metadata["priority"], {"high", "medium", "low"})

    def test_combined_context_includes_tier_zero_and_uses_summary_when_budget_is_small(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as global_home:
            os.environ["MEMORY_FABRIC_HOME"] = global_home
            try:
                initialize_memory_fabric(temp)
                global_dir = Path(global_home) / "global"
                global_dir.mkdir(parents=True)
                (global_dir / "directives.md").write_text("Always run tests.\n", encoding="utf-8")

                write_local_memory(temp, "architecture", "A" * 2000, mode="replace")
                bundle = read_combined_context(temp, max_tokens=20)

                self.assertIn("Always run tests.", bundle["text"])
                self.assertIn("omitted because it exceeded", bundle["text"])
                self.assertIn("local/architecture", bundle["omitted_sections"])
            finally:
                os.environ.pop("MEMORY_FABRIC_HOME", None)

    def test_write_redacts_secret_and_preserves_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_local_memory(
                temp,
                "decisions",
                "Usar portugues. OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890",
                mode="replace",
            )
            section = read_section(temp, "decisions")

            self.assertEqual(result["redactions"], 1)
            self.assertIn("Usar portugues", section["text"])
            self.assertIn("[REDACTED_SECRET]", section["text"])
            self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz1234567890", section["text"])

    def test_global_path_resolution_is_platform_aware(self) -> None:
        windows = get_global_root(platform_name="Windows", env={"APPDATA": r"C:\Users\R\AppData\Roaming"}, home="C:/Users/R")
        mac = get_global_root(platform_name="Darwin", env={}, home="/Users/r")
        linux = get_global_root(platform_name="Linux", env={"XDG_CONFIG_HOME": "/home/r/.config"}, home="/home/r")

        self.assertTrue(str(windows).endswith("memory-fabric"))
        self.assertEqual(mac, Path("/Users/r/Library/Application Support/memory-fabric").resolve())
        self.assertEqual(linux, Path("/home/r/.config/memory-fabric").resolve())

    def test_keyword_search_python_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_local_memory(temp, "schemas", "CustomerProfile includes locale.", mode="replace")

            with mock.patch("shutil.which", return_value=None):
                results = keyword_search(temp, "locale")

            self.assertEqual(results[0]["section"], "schemas")
            self.assertIn("locale", results[0]["snippet"])

    def test_rollback_restores_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_local_memory(temp, "debt", "Original debt note.", mode="replace")
            create_snapshot(temp, name="memory_v1")

            write_local_memory(temp, "debt", "Changed debt note.", mode="replace")
            rollback(temp, "memory_v1")
            section = read_section(temp, "debt")

            self.assertIn("Original debt note.", section["text"])
            self.assertNotIn("Changed debt note.", section["text"])

    def test_pre_init_eval_creates_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = evaluate_memory_fabric(temp)

            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["report_paths"], [])
            self.assertFalse((Path(temp) / ".ai-memory").exists())
            self.assertIn("ai-memory init", result["recommendations"][0])

    def test_initialized_eval_saves_reports_and_ignores_evals(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = evaluate_memory_fabric(temp)
            memory_dir = Path(temp) / ".ai-memory"

            self.assertTrue((memory_dir / "evals" / "latest.json").exists())
            self.assertTrue((memory_dir / "evals" / "latest.md").exists())
            self.assertIn(str(memory_dir / "evals" / "latest.json"), result["report_paths"])
            self.assertIn("evals/", (memory_dir / ".gitignore").read_text(encoding="utf-8"))

    def test_memory_eval_detects_template_content_and_llm_review_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = evaluate_memory_fabric(temp, save_report=False, llm_review=True)
            check_ids = [
                check["id"]
                for category in result["categories"]
                for check in category["checks"]
            ]

            self.assertIn("architecture_placeholder", check_ids)
            self.assertTrue(any("MEMORY_FABRIC_LLM_PROVIDER" in note for note in result["llm_notes"]))

    def test_dream_eval_compares_snapshot_and_current_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            snapshot = create_snapshot(temp, name="memory_before")
            write_local_memory(
                temp,
                "architecture",
                (
                    "# Architecture\n\n"
                    "Memory Fabric is a local-first MCP server with file-backed Markdown sections. "
                    "The storage layer owns scaffolding, retrieval, snapshots, rollback, and safety checks. "
                    "The CLI exposes these operations for local developer workflows."
                ),
                mode="replace",
            )

            result = evaluate_dream_quality(temp, snapshot=snapshot)

            self.assertEqual(result["baseline_snapshot"], "memory_before")
            self.assertGreaterEqual(result["after_score"], result["before_score"])
            self.assertIn("architecture.md", result["changed_files"])
            self.assertTrue((Path(temp) / ".ai-memory" / "evals" / "latest.json").exists())

    def test_dream_eval_latest_snapshot_and_content_loss_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            create_snapshot(temp, name="memory_old")
            write_local_memory(temp, "schemas", "# Schemas\n\nCustomerProfile includes locale and timezone.", mode="replace")
            latest = create_snapshot(temp, name="memory_new")
            (Path(temp) / ".ai-memory" / "schemas.md").unlink()

            self.assertEqual(latest_snapshot(temp), latest)
            result = evaluate_dream_quality(temp, snapshot="latest", save_report=False)

            self.assertEqual(result["baseline_snapshot"], "memory_new")
            self.assertTrue(any("removed memory sections" in item for item in result["regressions"]))


if __name__ == "__main__":
    unittest.main()
