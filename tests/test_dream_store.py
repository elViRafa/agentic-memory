import unittest
import tempfile
import json
import os
import hashlib
from pathlib import Path
from unittest import mock

import asyncio
from memory_fabric.storage import (
    initialize_memory_fabric,
    write_memory_store,
    read_memory_store,
    dream as _async_dream,
    read_section,
    doctor,
)

def dream(*args, **kwargs):
    return asyncio.run(_async_dream(*args, **kwargs))

from memory_fabric.frontmatter import parse_frontmatter, dump_frontmatter


class DreamStoreTests(unittest.TestCase):
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
                priority="low"
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
            self.assertIn("• Topic A: Frontmatter Utilities<br>• Topic B: Security Checks", store_index_text)
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

    @mock.patch("memory_fabric.storage._core.call_llm", new_callable=mock.AsyncMock)
    def test_dream_store_deep_mode_consolidates_and_updates_nested_files(self, mock_call_llm) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            
            # Setup a nested file
            write_memory_store(
                temp,
                store_path="architecture/tests/isolated-unit-tests",
                content="- Old content of utility tests.",
                title="Isolated Unit Tests",
                tags=["tests"],
                priority="low"
            )

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            consolidation_response = json.dumps({
                "consolidated_files": {
                    "store/architecture/tests/isolated-unit-tests": "- Enriched utility tests with dates and IDs.",
                    "local/decisions": "# Decisions\n\n- Consolidated decisions."
                },
                "contradictions": [],
                "warnings": []
            })

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
                nested_path = Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "tests" / "isolated-unit-tests.md"
                self.assertTrue(nested_path.exists())
                
                metadata, body = parse_frontmatter(nested_path.read_text(encoding="utf-8"))
                self.assertEqual(body.strip(), "- Enriched utility tests with dates and IDs.")
                self.assertEqual(metadata["store_path"], "architecture/tests/isolated-unit-tests")
                self.assertEqual(metadata["title"], "Isolated Unit Tests")
                self.assertEqual(metadata["priority"], "low")

            finally:
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.storage._core.now_iso")
    @mock.patch("memory_fabric.storage._core.call_llm", new_callable=mock.AsyncMock)
    def test_dream_store_deep_mode_summarizer_refreshes_nested_file_summaries(self, mock_call_llm, mock_now_iso) -> None:
        with tempfile.TemporaryDirectory() as temp:
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
                priority="low"
            )

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            call_count = 0
            def increment_now_iso():
                nonlocal call_count
                call_count += 1
                return f"2026-06-03T14:00:{call_count:02d}-04:00"
            mock_now_iso.side_effect = increment_now_iso

            def mock_llm_func(prompt, system_instruction="", *args, **kwargs):
                if "consolidated_files" in prompt:
                    return json.dumps({
                        "consolidated_files": {
                            "store/architecture/tests/isolated-unit-tests": "- Enriched fast frontmatter units."
                        },
                        "contradictions": [],
                        "warnings": []
                    })
                elif "isolated-unit-tests" in prompt:
                    return "Custom nested unit tests summary."
                else:
                    return "Custom decisions summary."
            mock_call_llm.side_effect = mock_llm_func
            try:
                result1 = dream(temp, mode="deep", apply=True)
                self.assertTrue(result1["changed"])
                
                # Check that summary & summary_hash are updated in the nested file metadata
                nested_path = Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "tests" / "isolated-unit-tests.md"
                metadata, body = parse_frontmatter(nested_path.read_text(encoding="utf-8"))
                self.assertEqual(metadata["summary"], "Custom nested unit tests summary.")
                expected_hash = hashlib.md5(body.strip().encode("utf-8")).hexdigest()
                self.assertEqual(metadata["summary_hash"], expected_hash)

                # 2. Run second dream: identical content -> skips summary LLM call
                mock_call_llm.reset_mock()
                # Mock return for the consolidation call, which checks skips
                result2 = dream(temp, mode="deep", apply=True)
                self.assertEqual(mock_call_llm.call_count, 0) # Skipped LLM calls completely!

            finally:
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("GEMINI_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
