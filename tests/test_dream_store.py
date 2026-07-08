import unittest
import tempfile
import json
import os
import hashlib
import time
from pathlib import Path
from unittest import mock

import asyncio
from memory_fabric.storage import (
    initialize_memory_fabric,
    write_memory_store,
    dream as _async_dream,
    doctor,
)
from memory_fabric.frontmatter import parse_frontmatter


def dream(*args, **kwargs):
    return asyncio.run(_async_dream(*args, **kwargs))


class DreamStoreTests(unittest.TestCase):
    def test_repeated_light_dream_is_byte_stable(self) -> None:
        """P-15: a dream right after another must not rewrite any memory file.

        The post-commit hook runs `dream --mode light --apply`; if that bumps
        `last_updated` on the regenerated indexes even when nothing changed,
        the working tree is dirty again immediately after every commit and the
        next checkout/merge is blocked.
        """
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp, "architecture/notes", "# Notes\n\nA stable fact.", title="Notes"
            )
            dream(temp, mode="light", apply=True)

            memory_dir = Path(temp) / ".ai-memory"

            def tree_state() -> dict[str, str]:
                skip = {"snapshots", "candidates", "evals", "private"}
                return {
                    str(p.relative_to(memory_dir)): p.read_text(encoding="utf-8")
                    for p in memory_dir.rglob("*.md")
                    if not skip.intersection(p.relative_to(memory_dir).parts)
                }

            before = tree_state()
            # Cross a real second boundary: when both dreams share the same
            # timestamp string, a broken changed-guard still produces identical
            # bytes by accident and the test would pass vacuously.
            time.sleep(1.1)
            result2 = dream(temp, mode="light", apply=True)
            after = tree_state()

            self.assertEqual(before, after, "second no-op dream must not touch any file")
            self.assertEqual(result2["affected_files"], [])
            self.assertFalse(result2["changed"])

    def test_dream_rewrites_index_when_store_actually_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "architecture/notes", "# Notes\n\nFact one.", title="Notes")
            dream(temp, mode="light", apply=True)

            index_path = Path(temp) / ".ai-memory" / "memory-store" / "index.md"
            body_before = parse_frontmatter(index_path.read_text(encoding="utf-8"))[1]
            self.assertNotIn("decisions/new-decision", body_before)

            write_memory_store(
                temp, "decisions/new-decision", "# New\n\nUse feature flags.", title="New"
            )
            result = dream(temp, mode="light", apply=True)
            self.assertTrue(result["changed"])
            body_after = parse_frontmatter(index_path.read_text(encoding="utf-8"))[1]
            self.assertIn("decisions/new-decision", body_after)

    def test_numeric_contradiction_heuristic_flags_planted_conflict(self) -> None:
        """P-10: the planted TTL conflict from the v0.7.0 campaign (3600 vs 60).

        An 8B local model returned contradictions: [] for this exact setup;
        the deterministic net must flag it regardless of the LLM's answer.
        """
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/cache-policy",
                "The cache TTL for TaskMaster task lists is 3600 seconds. "
                "Cache TTL applies to every TaskMaster list query.",
                title="Cache Policy",
            )
            write_memory_store(
                temp,
                "architecture/decisions/taskmaster-caching",
                "The cache TTL for TaskMaster task lists is 60 seconds by default. "
                "Cache TTL applies to every TaskMaster list query.",
                title="TaskMaster Caching",
            )

            result = dream(temp, mode="light", apply=True)
            heuristic_hits = [
                w for w in result["warnings"] if "heuristic" in w and "3600" in w and "60" in w
            ]
            self.assertTrue(heuristic_hits, f"expected heuristic hit, got: {result['warnings']}")

            # The flagged contradiction must not break byte-stability (P-15):
            # a second no-op dream re-derives the same list and writes nothing.
            result2 = dream(temp, mode="light", apply=True)
            self.assertEqual(result2["affected_files"], [])
            self.assertFalse(result2["changed"])

    def test_unrelated_files_with_numbers_are_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/http-timeouts",
                "External HTTP calls use a 30 second timeout with retries.",
                title="HTTP Timeouts",
            )
            write_memory_store(
                temp,
                "schemas/pagination",
                "List endpoints paginate responses at 50 items per page maximum.",
                title="Pagination",
            )
            result = dream(temp, mode="light", apply=True)
            self.assertFalse(any("heuristic" in w for w in result["warnings"]))

    @mock.patch("memory_fabric.storage.finalize._build_rewrite_tasks")
    @mock.patch("memory_fabric.storage.dream.call_llm", new_callable=mock.AsyncMock)
    def test_provider_warning_distinguishes_consolidation_from_rewrites(
        self, mock_llm, mock_tasks
    ) -> None:
        """P-09: the warning must not deny the direct provider call that DID happen."""
        mock_llm.return_value = json.dumps(
            {"consolidated_files": {}, "summaries": {}, "contradictions": [], "warnings": []}
        )
        mock_tasks.return_value = [
            {"section": "architecture", "reason": "too terse", "instruction": "expand"}
        ]
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "architecture/notes", "# Notes\n\nFact.", title="Notes")
            with mock.patch.dict(
                os.environ,
                {"MEMORY_FABRIC_LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "test-model"},
            ):
                result = dream(temp, mode="deep", apply=True, llm_rewrite=True)

        joined = " ".join(result["warnings"])
        self.assertNotIn("does not call provider adapters directly", joined)
        self.assertIn("called provider `ollama` directly", joined)
        self.assertIn("agent-assisted", joined)

    def test_dream_store_light_mode_regenerates_index_with_topics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                store_path="architecture/tests/isolated-unit-tests",
                content=(
                    "# Isolated Unit Tests\n\n"
                    "## Topic A: Frontmatter Utilities\n"
                    "Extracted fast frontmatter unit tests.\n\n"
                    "## Topic B: Security Checks\n"
                    "Isolated token signature regex tests.\n"
                ),
                title="Isolated Unit Tests",
                tags=["tests", "frontmatter"],
                priority="low",
            )

            # Trigger Dreaming in light mode (only maintains files and index)
            result = dream(temp, mode="light", apply=True)
            self.assertTrue(result["changed"])

            index_path = Path(temp) / ".ai-memory" / "index.md"
            self.assertTrue(index_path.exists())
            index_text = index_path.read_text(encoding="utf-8")

            # Check root index points to the sub-index
            self.assertIn("## Memory Store", index_text)
            self.assertIn("[Memory Store Index](memory-store/index.md)", index_text)

            # Check dedicated store index file
            store_index_path = Path(temp) / ".ai-memory" / "memory-store" / "index.md"
            self.assertTrue(store_index_path.exists())
            store_index_text = store_index_path.read_text(encoding="utf-8")

            # Check that the table has 5 columns
            self.assertIn("| Path | Priority | Summary | Key Topics | Tags |", store_index_text)
            self.assertIn("architecture/tests/isolated-unit-tests", store_index_text)
            self.assertIn(
                "• Topic A: Frontmatter Utilities<br>• Topic B: Security Checks", store_index_text
            )
            self.assertIn("tests, frontmatter", store_index_text)

            # Check frontmatter of the sub-index
            store_meta, _ = parse_frontmatter(store_index_text)
            self.assertEqual(store_meta["store_path"], "index")
            self.assertEqual(store_meta["title"], "Memory Store Index")
            self.assertEqual(store_meta["priority"], "high")
            self.assertEqual(store_meta["tags"], ["index", "memory-store"])

            # Verify doctor is happy
            res_doctor = doctor(temp)
            self.assertTrue(res_doctor["ok"])

    @mock.patch("memory_fabric.storage.dream.call_llm", new_callable=mock.AsyncMock)
    def test_dream_store_deep_mode_consolidates_and_updates_nested_files(
        self, mock_call_llm
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            # Setup a nested file
            write_memory_store(
                temp,
                store_path="architecture/tests/isolated-unit-tests",
                content="- Old content of utility tests.",
                title="Isolated Unit Tests",
                tags=["tests"],
                priority="low",
            )

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            consolidation_response = json.dumps(
                {
                    "consolidated_files": {
                        "store/architecture/tests/isolated-unit-tests": "- Enriched utility tests with dates and IDs.",
                        "local/decisions": "# Decisions\n\n- Consolidated decisions.",
                    },
                    "contradictions": [],
                    "warnings": [],
                }
            )

            def mock_llm_func(prompt, system_instruction="", *args, **kwargs):
                if "consolidated_files" in prompt:
                    return consolidation_response
                return "Mocked summary"

            mock_call_llm.side_effect = mock_llm_func

            try:
                result = dream(temp, mode="deep", apply=True)
                self.assertTrue(result["changed"])

                # Check affected files contains the store file path
                affected = [f.replace("\\", "/") for f in result["affected_files"]]
                self.assertIn("memory-store/architecture/tests/isolated-unit-tests.md", affected)

                # Verify file was NOT flattened to root
                flat_path = Path(temp) / ".ai-memory" / "isolated-unit-tests.md"
                self.assertFalse(flat_path.exists())

                # Verify nested file inside memory-store/ was updated correctly
                nested_path = (
                    Path(temp)
                    / ".ai-memory"
                    / "memory-store"
                    / "architecture"
                    / "tests"
                    / "isolated-unit-tests.md"
                )
                self.assertTrue(nested_path.exists())

                metadata, body = parse_frontmatter(nested_path.read_text(encoding="utf-8"))
                self.assertEqual(body.strip(), "- Enriched utility tests with dates and IDs.")
                self.assertEqual(metadata["store_path"], "architecture/tests/isolated-unit-tests")
                self.assertEqual(metadata["title"], "Isolated Unit Tests")
                self.assertEqual(metadata["priority"], "low")

            finally:
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.storage.finalize.call_llm", new_callable=mock.AsyncMock)
    def test_dream_store_deep_mode_summarizer_refreshes_nested_file_summaries(
        self, mock_call_llm
    ) -> None:
        # dream() calls call_llm directly (consolidation prompt) and finalize's
        # _process_and_finalize_candidate also calls it (per-section summaries) —
        # both references must be the *same* mock so call_count/side_effect are shared.
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch("memory_fabric.storage.dream.call_llm", new=mock_call_llm),
            mock.patch("memory_fabric.storage.finalize.now_iso") as mock_now_iso,
            mock.patch("memory_fabric.storage.snapshots.now_iso") as mock_snapshot_now_iso,
        ):
            initialize_memory_fabric(temp)

            # Let's delete other flat sections so we only have decisions and the nested store file
            for p in (Path(temp) / ".ai-memory").glob("*.md"):
                if p.name not in {"decisions.md"}:
                    p.unlink()

            write_memory_store(
                temp,
                store_path="architecture/tests/isolated-unit-tests",
                content="- Fast frontmatter units.",
                title="Isolated Unit Tests",
                tags=["tests"],
                priority="low",
            )

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            call_count = 0

            def increment_now_iso():
                nonlocal call_count
                call_count += 1
                return f"2026-06-03T14:00:{call_count:02d}-04:00"

            mock_now_iso.side_effect = increment_now_iso
            mock_snapshot_now_iso.side_effect = increment_now_iso

            def mock_llm_func(prompt, system_instruction="", *args, **kwargs):
                if "consolidated_files" in prompt:
                    return json.dumps(
                        {
                            "consolidated_files": {
                                "store/architecture/tests/isolated-unit-tests": "- Enriched fast frontmatter units."
                            },
                            "contradictions": [],
                            "warnings": [],
                        }
                    )
                elif "isolated-unit-tests" in prompt:
                    return "Custom nested unit tests summary."
                else:
                    return "Custom decisions summary."

            mock_call_llm.side_effect = mock_llm_func
            try:
                result1 = dream(temp, mode="deep", apply=True)
                self.assertTrue(result1["changed"])

                # Check that summary & summary_hash are updated in the nested file metadata
                nested_path = (
                    Path(temp)
                    / ".ai-memory"
                    / "memory-store"
                    / "architecture"
                    / "tests"
                    / "isolated-unit-tests.md"
                )
                metadata, body = parse_frontmatter(nested_path.read_text(encoding="utf-8"))
                self.assertEqual(metadata["summary"], "Custom nested unit tests summary.")
                expected_hash = hashlib.md5(body.strip().encode("utf-8")).hexdigest()
                self.assertEqual(metadata["summary_hash"], expected_hash)

                # 2. Run second dream: identical content -> skips summary LLM call
                mock_call_llm.reset_mock()
                # Mock return for the consolidation call, which checks skips
                _ = dream(temp, mode="deep", apply=True)
                self.assertEqual(mock_call_llm.call_count, 0)  # Skipped LLM calls completely!

            finally:
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("GEMINI_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
