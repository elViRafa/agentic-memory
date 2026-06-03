from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.eval import evaluate_dream_quality, evaluate_memory_fabric, latest_snapshot
from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.version import __version__
from memory_fabric.paths import get_global_root
from memory_fabric.storage import (
    create_snapshot,
    doctor,
    dream,
    initialize_memory_fabric,
    keyword_search,
    read_combined_context,
    read_section,
    rollback,
    status,
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

    def test_dream_candidate_mode_is_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            line = "Shared architecture note that is intentionally duplicated across sections for consolidation checks."
            write_local_memory(temp, "architecture", f"# Architecture\n\n- {line}\n", mode="replace")
            write_local_memory(temp, "decisions", f"# Decisions\n\n- {line}\n", mode="replace")

            before_arch = read_section(temp, "architecture")["text"]
            before_decisions = read_section(temp, "decisions")["text"]
            result = dream(temp, mode="deep", apply=False, llm_rewrite=True)

            self.assertFalse(result["changed"])
            self.assertTrue(result["apply_required"])
            self.assertTrue(Path(result["candidate_store"]).exists())
            self.assertTrue(result["patch_preview"])
            self.assertGreaterEqual(result["consolidation"]["duplicates_found"], 1)
            self.assertTrue(result["rewrite_tasks"])
            self.assertEqual(before_arch, read_section(temp, "architecture")["text"])
            self.assertEqual(before_decisions, read_section(temp, "decisions")["text"])

    def test_dream_apply_mode_updates_live_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            line = "This duplicate line should be consolidated by Dreaming apply mode for live memory updates."
            write_local_memory(temp, "architecture", f"# Architecture\n\n- {line}\n", mode="replace")
            write_local_memory(temp, "schemas", f"# Schemas\n\n- {line}\n", mode="replace")

            result = dream(temp, mode="deep", apply=True)

            self.assertTrue(result["changed"])
            self.assertFalse(result["apply_required"])
            schemas = read_section(temp, "schemas")["text"]
            self.assertNotIn(line, schemas)

    def test_init_install_hooks_creates_post_commit_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            git_dir = Path(temp) / ".git"
            git_dir.mkdir()
            result = initialize_memory_fabric(temp, install_hooks=True)
            post_commit_path = git_dir / "hooks" / "post-commit"
            
            self.assertTrue(post_commit_path.exists())
            self.assertIn("post-commit", result["files_created"][-1])
            self.assertIn("ai-memory dream --mode light --apply", post_commit_path.read_text(encoding="utf-8"))

    def test_init_install_hooks_without_git_emits_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = initialize_memory_fabric(temp, install_hooks=True)
            self.assertIn("Git repository not found", result["warnings"][0])

    def test_status_includes_memory_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_local_memory(temp, "architecture", "# Architecture\n\nSome important rules.", mode="replace")
            res = status(temp)
            
            self.assertIn("architecture.md", res["memory_sizes"])
            self.assertGreater(res["memory_sizes"]["architecture.md"]["bytes"], 0)
            self.assertGreater(res["memory_sizes"]["architecture.md"]["tokens"], 0)
            self.assertEqual(res["version"], __version__)

    def test_doctor_checks_permissions_and_index_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            res = doctor(temp)
            self.assertTrue(res["ok"])
            
            (Path(temp) / ".ai-memory" / "schemas.md").unlink()
            res2 = doctor(temp)
            self.assertTrue(any("missing from index.md" in w or "file does not exist" in w for w in res2["warnings"]))

    def test_dream_ingests_git_diff_and_scans_secrets_and_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            
            arch_path = Path(temp) / ".ai-memory" / "architecture.md"
            arch_text = arch_path.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(arch_text)
            metadata["last_updated"] = "2020-01-01T12:00:00-04:00"
            from memory_fabric.frontmatter import dump_frontmatter
            arch_path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
            
            private_dir = Path(temp) / ".ai-memory" / "private"
            private_dir.mkdir(exist_ok=True)
            (private_dir / "session_transcripts.md").write_text("API_KEY = 'sk-abcdefghijklmnopqrstuvwxyz1234567890'", encoding="utf-8")
            
            result = dream(temp, apply=True, mode="light")
            
            self.assertTrue(any("marked as stale" in w for w in result["warnings"]))
            self.assertTrue(any("redacted" in w for w in result["warnings"]))
            self.assertGreater(result["redactions"], 0)
            
            new_arch_text = arch_path.read_text(encoding="utf-8")
            new_metadata, _ = parse_frontmatter(new_arch_text)
            self.assertEqual(new_metadata.get("review_status"), "stale")

    @mock.patch("sys.stdin.isatty", return_value=True)
    @mock.patch("builtins.input", return_value="y")
    def test_cli_sync_global_interactive(self, mock_input, mock_isatty) -> None:
        from memory_fabric.cli import main
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as global_home:
            os.environ["MEMORY_FABRIC_HOME"] = global_home
            try:
                initialize_memory_fabric(temp)
                write_local_memory(temp, "decisions", "# Decisions\n\nRule details.", mode="replace")
                
                ret = main(["--cwd", temp, "sync-global"])
                self.assertEqual(ret, 0)
                
                global_decisions = Path(global_home) / "global" / "decisions.md"
                self.assertTrue(global_decisions.exists())
                self.assertIn("Rule details", global_decisions.read_text(encoding="utf-8"))
            finally:
                os.environ.pop("MEMORY_FABRIC_HOME", None)

    def test_init_install_hooks_appends_to_existing_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            git_dir = Path(temp) / ".git"
            git_dir.mkdir()
            hooks_dir = git_dir / "hooks"
            hooks_dir.mkdir()
            post_commit_path = hooks_dir / "post-commit"
            post_commit_path.write_text("#!/bin/sh\necho 'hello'\n", encoding="utf-8")
            
            result = initialize_memory_fabric(temp, install_hooks=True)
            self.assertTrue(post_commit_path.exists())
            content = post_commit_path.read_text(encoding="utf-8")
            self.assertIn("echo 'hello'", content)
            self.assertIn("ai-memory dream --mode light --apply", content)

    @mock.patch("sys.stdin.isatty", return_value=True)
    def test_cli_sync_global_interactive_append(self, mock_isatty) -> None:
        from memory_fabric.cli import main
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as global_home:
            os.environ["MEMORY_FABRIC_HOME"] = global_home
            try:
                initialize_memory_fabric(temp)
                write_local_memory(temp, "decisions", "# Decisions\n\nRule details local.", mode="replace")
                
                # Delete other markdown files to ensure only decisions.md is sync'd
                for p in (Path(temp) / ".ai-memory").glob("*.md"):
                    if p.name not in {"decisions.md"}:
                        p.unlink()
                
                global_dir = Path(global_home) / "global"
                global_dir.mkdir(parents=True)
                global_decisions = global_dir / "decisions.md"
                from memory_fabric.templates import build_memory_file
                from memory_fabric.frontmatter import parse_frontmatter, dump_frontmatter
                meta, body = parse_frontmatter(build_memory_file("decisions"))
                global_decisions.write_text(dump_frontmatter(meta, "# Decisions\n\nRule details global."), encoding="utf-8")
                
                with mock.patch("builtins.input", side_effect=["y", "n", "y"]):
                    ret = main(["--cwd", temp, "sync-global"])
                
                self.assertEqual(ret, 0)
                updated_content = global_decisions.read_text(encoding="utf-8")
                self.assertIn("Rule details global.", updated_content)
                self.assertIn("Rule details local.", updated_content)
            finally:
                os.environ.pop("MEMORY_FABRIC_HOME", None)

    def test_write_local_memory_extracts_frontmatter_from_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            input_content = (
                "---\n"
                "priority: high\n"
                "summary: \"Extracted decisions summary.\"\n"
                "tags: [db, schema]\n"
                "---\n"
                "- Bullet 1\n"
            )
            res = write_local_memory(temp, "decisions", input_content, mode="replace")
            self.assertTrue(res["changed"])
            
            section = read_section(temp, "decisions")
            self.assertEqual(section["metadata"]["priority"], "high")
            self.assertEqual(section["metadata"]["summary"], "Extracted decisions summary.")
            self.assertEqual(section["metadata"]["tags"], ["db", "schema"])
            self.assertIn("- Bullet 1", section["text"])
            self.assertNotIn("---", section["text"].split("---", 2)[2]) # verify no second frontmatter in body

    def test_write_local_memory_filters_duplicates_on_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_local_memory(temp, "decisions", "- Bullet 1\n- Bullet 2", mode="replace")
            
            # Try appending a duplicate and a unique bullet
            res = write_local_memory(temp, "decisions", "- Bullet 2\n- Bullet 3", mode="append")
            self.assertTrue(res["changed"])
            
            section = read_section(temp, "decisions")
            # Bullet 2 should not be duplicated
            text = section["text"]
            self.assertEqual(text.count("Bullet 2"), 1)
            self.assertEqual(text.count("Bullet 3"), 1)
            
            # Try appending only duplicates
            res2 = write_local_memory(temp, "decisions", "- Bullet 1\n- Bullet 3", mode="append")
            self.assertFalse(res2["changed"])
            self.assertTrue(any("duplicates filtered" in w for w in res2["warnings"]))

    @mock.patch("urllib.request.urlopen")
    def test_llm_providers_success(self, mock_urlopen) -> None:
        import json
        from memory_fabric.llm import call_llm

        class MockResponse:
            def __init__(self, data: bytes, code: int = 200, reason: str = "OK"):
                self.data = data
                self.code = code
                self.reason = reason
            def read(self, *args, **kwargs):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        # 1. Test Gemini
        mock_urlopen.return_value = MockResponse(
            json.dumps({"candidates": [{"content": {"parts": [{"text": "gemini result"}]}}]}).encode("utf-8")
        )
        os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "gemini-key"
        res = call_llm("test prompt", "system instructions")
        self.assertEqual(res, "gemini result")

        req = mock_urlopen.call_args_list[-1][0][0]
        self.assertIn("generativelanguage.googleapis.com", req.full_url)
        self.assertIn("key=gemini-key", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "test prompt")
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "system instructions")

        # 2. Test OpenAI
        mock_urlopen.return_value = MockResponse(
            json.dumps({"choices": [{"message": {"content": "openai result"}}]}).encode("utf-8")
        )
        os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "openai-key"
        res = call_llm("test prompt", "system instructions")
        self.assertEqual(res, "openai result")

        req = mock_urlopen.call_args_list[-1][0][0]
        self.assertIn("api.openai.com", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["messages"][-1]["content"], "test prompt")
        self.assertEqual(payload["messages"][0]["content"], "system instructions")

        # 3. Test Anthropic
        mock_urlopen.return_value = MockResponse(
            json.dumps({"content": [{"text": "anthropic result"}]}).encode("utf-8")
        )
        os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "anthropic"
        os.environ["ANTHROPIC_API_KEY"] = "anthropic-key"
        res = call_llm("test prompt", "system instructions")
        self.assertEqual(res, "anthropic result")

        req = mock_urlopen.call_args_list[-1][0][0]
        self.assertIn("api.anthropic.com", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["messages"][0]["content"], "test prompt")
        self.assertEqual(payload["system"], "system instructions")

        # 4. Test Ollama
        mock_urlopen.return_value = MockResponse(
            json.dumps({"message": {"content": "ollama result"}}).encode("utf-8")
        )
        os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "ollama"
        os.environ["OLLAMA_MODEL"] = "gemma4"
        res = call_llm("test prompt", "system instructions")
        self.assertEqual(res, "ollama result")

        req = mock_urlopen.call_args_list[-1][0][0]
        self.assertIn("localhost:11434/api/chat", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["model"], "gemma4")
        self.assertEqual(payload["messages"][-1]["content"], "test prompt")
        self.assertEqual(payload["messages"][0]["content"], "system instructions")
        self.assertFalse(payload["stream"])

        # Clean up env
        os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OLLAMA_MODEL", None)


    @mock.patch("memory_fabric.storage.call_llm")
    def test_dream_with_llm(self, mock_call_llm) -> None:
        import json
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            consolidation_response = json.dumps({
                "consolidated_files": {
                    "architecture": "# Architecture\n\nConsolidated LLM content."
                },
                "contradictions": ["Mismatched settings"],
                "warnings": ["Warning about schema"]
            })

            def mock_llm_func(prompt, system_instruction=""):
                if "consolidated_files" in prompt:
                    return consolidation_response
                return "Mocked concise summary of section"

            mock_call_llm.side_effect = mock_llm_func

            result = dream(temp, mode="deep", apply=True)
            self.assertTrue(result["changed"])
            self.assertTrue(any("Contradiction detected: Mismatched settings" in w for w in result["warnings"]))
            self.assertTrue(any("Consolidation warning: Warning about schema" in w for w in result["warnings"]))

            # Verify architecture is updated
            arch_text = read_section(temp, "architecture")["text"]
            self.assertIn("Consolidated LLM content", arch_text)

            # Clean up env
            os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
            os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.llm.call_llm")
    def test_eval_with_llm_review(self, mock_call_llm) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            mock_call_llm.return_value = "- Focus on schema definitions.\n- Simplify code standards."

            result = evaluate_memory_fabric(temp, save_report=False, llm_review=True)
            self.assertTrue(any("Focus on schema definitions" in note for note in result["llm_notes"]))
            self.assertTrue(any("Simplify code standards" in note for note in result["llm_notes"]))

            # Clean up env
            os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
            os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.llm.call_llm")
    def test_eval_with_llm_review_failure(self, mock_call_llm) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            mock_call_llm.side_effect = Exception("API connection timed out")

            result = evaluate_memory_fabric(temp, save_report=False, llm_review=True)
            self.assertTrue(any("Failed to generate qualitative LLM review" in note for note in result["llm_notes"]))
            self.assertTrue(any("API connection timed out" in note for note in result["llm_notes"]))

            # Clean up env
            os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
            os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("time.sleep")
    @mock.patch("urllib.request.urlopen")
    def test_llm_retry_on_429_then_success(self, mock_urlopen, mock_sleep) -> None:
        import json
        import urllib.error
        from memory_fabric.llm import call_llm

        class MockResponse:
            def __init__(self, data: bytes, code: int = 200, reason: str = "OK"):
                self.data = data
                self.code = code
                self.reason = reason
            def read(self, *args, **kwargs):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        err_response = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        success_response = MockResponse(
            json.dumps({"candidates": [{"content": {"parts": [{"text": "retry success"}]}}]}).encode("utf-8")
        )

        mock_urlopen.side_effect = [err_response, success_response]

        os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "gemini-key"
        try:
            res = call_llm("test prompt", "system instructions")
            self.assertEqual(res, "retry success")
            self.assertEqual(mock_urlopen.call_count, 2)
            mock_sleep.assert_called_once()
        finally:
            os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
            os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("time.sleep")
    @mock.patch("urllib.request.urlopen")
    def test_llm_retry_exhausted_raises_error(self, mock_urlopen, mock_sleep) -> None:
        import urllib.error
        from memory_fabric.llm import call_llm, LLMError

        err_response = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        mock_urlopen.side_effect = err_response

        os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "gemini-key"
        try:
            with self.assertRaises(LLMError) as ctx:
                call_llm("test prompt", "system instructions")
            self.assertIn("HTTP Error 429", str(ctx.exception))
            self.assertEqual(mock_urlopen.call_count, 5)  # max_retries
            self.assertEqual(mock_sleep.call_count, 4)
        finally:
            os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
            os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.storage.now_iso")
    @mock.patch("memory_fabric.storage.call_llm")
    def test_dream_summary_skips_when_hash_matches(self, mock_call_llm, mock_now_iso) -> None:
        import hashlib
        from memory_fabric.frontmatter import dump_frontmatter
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            
            # Let's delete other sections so we have a clean test with just one section
            for p in (Path(temp) / ".ai-memory").glob("*.md"):
                if p.name not in {"architecture.md"}:
                    p.unlink()

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            # Return different times on successive calls to prevent snapshot collisions
            call_count = 0
            def increment_now_iso():
                nonlocal call_count
                call_count += 1
                return f"2026-06-02T13:00:{call_count:02d}-04:00"
            mock_now_iso.side_effect = increment_now_iso

            try:
                # 1. Run first dream: will generate a summary
                mock_call_llm.return_value = "Custom architecture summary."
                res1 = dream(temp, mode="deep", apply=True)
                
                self.assertTrue(res1["changed"])
                self.assertEqual(mock_call_llm.call_count, 2)  # 1 consolidation call + 1 summary call
                
                # Check that summary_hash exists in metadata
                arch_path = Path(temp) / ".ai-memory" / "architecture.md"
                metadata, body = parse_frontmatter(arch_path.read_text(encoding="utf-8"))
                self.assertEqual(metadata.get("summary"), "Custom architecture summary.")
                expected_hash = hashlib.md5(body.strip().encode("utf-8")).hexdigest()
                self.assertEqual(metadata.get("summary_hash"), expected_hash)
                
                # 2. Run second dream: body is identical, summary is custom, hash matches -> skips LLM call
                mock_call_llm.reset_mock()
                res2 = dream(temp, mode="deep", apply=True)
                self.assertEqual(mock_call_llm.call_count, 1)  # 1 consolidation call + 0 summary calls
                
                # 3. Modify body: hash mismatch -> calls LLM
                metadata["last_updated"] = "2026-06-02T13:00:00-04:00"
                body = "# Architecture\n\nNew modified content here."
                arch_path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
                
                mock_call_llm.reset_mock()
                mock_call_llm.return_value = "New custom architecture summary."
                res3 = dream(temp, mode="deep", apply=True)
                self.assertEqual(mock_call_llm.call_count, 2)  # 1 consolidation call + 1 summary call
                
                metadata2, body2 = parse_frontmatter(arch_path.read_text(encoding="utf-8"))
                self.assertEqual(metadata2.get("summary"), "New custom architecture summary.")
                
            finally:
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.storage.now_iso")
    @mock.patch("memory_fabric.storage.call_llm")
    def test_dream_consolidation_skips_when_hash_matches(self, mock_call_llm, mock_now_iso) -> None:
        import json
        from memory_fabric.frontmatter import dump_frontmatter
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            
            # Let's delete other sections so we have a clean test with just one section
            for p in (Path(temp) / ".ai-memory").glob("*.md"):
                if p.name not in {"architecture.md"}:
                    p.unlink()

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            call_count = 0
            def increment_now_iso():
                nonlocal call_count
                call_count += 1
                return f"2026-06-02T13:00:{call_count:02d}-04:00"
            mock_now_iso.side_effect = increment_now_iso

            try:
                # 1. First dream run
                mock_call_llm.side_effect = [
                    json.dumps({
                        "consolidated_files": {"architecture": "# Architecture\n\nConsolidated."},
                        "contradictions": [],
                        "warnings": []
                    }),
                    "Architecture summary."
                ]
                res1 = dream(temp, mode="deep", apply=True)
                self.assertTrue(res1["changed"])
                self.assertEqual(mock_call_llm.call_count, 2)

                # 2. Second run: content, git diff, and files are identical -> skips consolidation LLM call!
                mock_call_llm.reset_mock()
                res2 = dream(temp, mode="deep", apply=True)
                self.assertEqual(mock_call_llm.call_count, 0) # exactly 0 calls!
                self.assertEqual(res2["affected_files"], ["index.md"])

                # 3. Third run: let's modify the file content so hash mismatches
                arch_path = Path(temp) / ".ai-memory" / "architecture.md"
                arch_meta, arch_body = parse_frontmatter(arch_path.read_text(encoding="utf-8"))
                arch_path.write_text(dump_frontmatter(arch_meta, arch_body + "\nNew change.\n"), encoding="utf-8")

                mock_call_llm.reset_mock()
                mock_call_llm.side_effect = [
                    json.dumps({
                        "consolidated_files": {"architecture": "# Architecture\n\nConsolidated again."},
                        "contradictions": [],
                        "warnings": []
                    }),
                    "New architecture summary."
                ]
                res3 = dream(temp, mode="deep", apply=True)
                self.assertTrue(res3["changed"])
                self.assertEqual(mock_call_llm.call_count, 2) # Consolidation + summary refreshed

            finally:
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("GEMINI_API_KEY", None)

    def test_index_includes_key_topics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            # Write a section with H2 headings
            write_local_memory(
                temp,
                "decisions",
                (
                    "# Decisions\n\n"
                    "## Decision 1: Use local model\n"
                    "We decided to use Gemma.\n\n"
                    "## Decision 2: Run with CUDA\n"
                    "We decided to run with CUDA acceleration.\n"
                ),
                mode="replace"
            )
            # Write another section with only lists (no H2)
            write_local_memory(
                temp,
                "debt",
                (
                    "# Technical Debt\n\n"
                    "- Fix the imports\n"
                    "- Clean the workspace files\n"
                    "- Add more logs\n"
                ),
                mode="replace"
            )
            
            # Trigger Dreaming (light mode is enough to regenerate index)
            dream(temp, mode="light", apply=True)
            
            index_path = Path(temp) / ".ai-memory" / "index.md"
            self.assertTrue(index_path.exists())
            index_text = index_path.read_text(encoding="utf-8")
            
            # Verify the headers are updated in index table
            self.assertIn("| Section | Priority | Summary | Key Topics |", index_text)
            self.assertIn("| --- | --- | --- | --- |", index_text)
            
            # Verify the extracted H2 topics are correct in the table
            self.assertIn("• Decision 1: Use local model<br>• Decision 2: Run with CUDA", index_text)
            
            # Verify fallback bullet list topics are correct
            self.assertIn("• Fix the imports<br>• Clean the workspace files<br>• Add more logs", index_text)
            
            # Run doctor to ensure index consistency validation is happy
            res_doctor = doctor(temp)
            self.assertTrue(res_doctor["ok"])

    def test_consolidated_memory_generation_and_optimization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_local_memory(temp, "architecture", "# Architecture\n\nActive arch details.", mode="replace")
            write_local_memory(temp, "decisions", "# Decisions\n\nActive decision details.", mode="replace")
            
            # 1. Trigger Dreaming to generate index.md and consolidated_memory.md
            dream(temp, mode="light", apply=True)
            
            memory_dir = Path(temp) / ".ai-memory"
            consolidated_path = memory_dir / "consolidated_memory.md"
            self.assertTrue(consolidated_path.exists())
            
            consolidated_text = consolidated_path.read_text(encoding="utf-8")
            self.assertIn("<!-- memory-fabric:local/architecture -->", consolidated_text)
            self.assertIn("Active arch details.", consolidated_text)
            self.assertIn("<!-- memory-fabric:local/decisions -->", consolidated_text)
            self.assertIn("Active decision details.", consolidated_text)
            
            # 2. Check that consolidated_memory.md is ignored by standard lists and status
            status_res = status(temp)
            self.assertNotIn("consolidated_memory.md", status_res["memory_sizes"])
            
            doctor_res = doctor(temp)
            self.assertTrue(doctor_res["ok"])
            self.assertNotIn(str(consolidated_path), doctor_res["checked_files"])
            
            # 3. Check read_combined_context uses the cached file when within token budget
            bundle = read_combined_context(temp, max_tokens=4000)
            self.assertIn("Active arch details.", bundle["text"])
            self.assertIn("local/architecture", bundle["included_sections"])
            self.assertIn("local/decisions", bundle["included_sections"])
            self.assertEqual(bundle["omitted_sections"], [])
            
            # 4. Check read_combined_context budget fallback (falls back to selective reading if budget too low)
            small_bundle = read_combined_context(temp, max_tokens=20)
            self.assertIn("omitted because it exceeded the remaining token budget", small_bundle["text"])


if __name__ == "__main__":
    unittest.main()
