from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import asyncio
from memory_fabric.eval import (
    evaluate_dream_quality as _async_evaluate_dream_quality,
    evaluate_memory_fabric as _async_evaluate_memory_fabric,
    latest_snapshot,
)
from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.version import __version__
from memory_fabric.paths import get_global_root
from memory_fabric.storage import (
    create_snapshot,
    doctor,
    dream as _async_dream,
    initialize_memory_fabric,
    keyword_search,
    read_combined_context,
    read_memory_store,
    read_section,
    rollback,
    status,
    write_local_memory,
    write_memory_store,
)
from memory_fabric.llm import call_llm as _async_call_llm


def dream(*args, **kwargs):
    return asyncio.run(_async_dream(*args, **kwargs))


def evaluate_dream_quality(*args, **kwargs):
    return asyncio.run(_async_evaluate_dream_quality(*args, **kwargs))


def evaluate_memory_fabric(*args, **kwargs):
    return asyncio.run(_async_evaluate_memory_fabric(*args, **kwargs))


def call_llm(*args, **kwargs):
    return asyncio.run(_async_call_llm(*args, **kwargs))


class MemoryFabricTests(unittest.TestCase):
    def test_init_creates_scaffold_with_valid_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = initialize_memory_fabric(temp)
            memory_dir = Path(temp) / ".ai-memory"

            self.assertTrue(result["created"])
            self.assertTrue((memory_dir / "index.md").exists())
            self.assertTrue((memory_dir / ".gitignore").exists())

            metadata, _body = parse_frontmatter(
                (memory_dir / "architecture.md").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["section"], "architecture")
            self.assertEqual(metadata["schema_version"], "1.3")
            self.assertIn(metadata["priority"], {"high", "medium", "low"})

    def test_init_with_memory_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            # 1. Init with memory prompt
            result = initialize_memory_fabric(
                temp, memory_prompt="Only save architecture guidelines."
            )
            memory_dir = Path(temp) / ".ai-memory"
            prompt_file = memory_dir / "memory_prompt.txt"

            self.assertTrue(result["created"])
            self.assertTrue(prompt_file.exists())
            self.assertEqual(
                prompt_file.read_text(encoding="utf-8").strip(),
                "Only save architecture guidelines.",
            )

            # Verify combined context includes memory prompt
            context = read_combined_context(temp)
            self.assertIn("local/memory_prompt", context["included_sections"])
            self.assertIn("Only save architecture guidelines.", context["text"])

            # 2. Verify consolidated compile includes it
            dream(temp, mode="light", apply=True)
            consolidated_path = memory_dir / "consolidated_memory.md"
            self.assertTrue(consolidated_path.exists())
            self.assertIn("local/memory_prompt", consolidated_path.read_text(encoding="utf-8"))

            # 3. Unlink memory prompt via empty init
            _ = initialize_memory_fabric(temp, memory_prompt="")
            self.assertFalse(prompt_file.exists())

            context2 = read_combined_context(temp)
            self.assertNotIn("local/memory_prompt", context2["included_sections"])
            self.assertNotIn("Only save architecture guidelines.", context2["text"])

    def test_combined_context_includes_tier_zero_and_uses_summary_when_budget_is_small(
        self,
    ) -> None:
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
        windows = get_global_root(
            platform_name="Windows",
            env={"APPDATA": r"C:\Users\R\AppData\Roaming"},
            home="C:/Users/R",
        )
        mac = get_global_root(platform_name="Darwin", env={}, home="/Users/r")
        linux = get_global_root(
            platform_name="Linux", env={"XDG_CONFIG_HOME": "/home/r/.config"}, home="/home/r"
        )

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

    def test_list_snapshots_returns_newest_first_with_stats(self) -> None:
        """P-12: snapshots must be discoverable without touching .ai-memory/."""
        from memory_fabric.storage import list_snapshots

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            self.assertEqual(list_snapshots(temp), [])

            create_snapshot(temp, name="memory_v1")
            create_snapshot(temp, name="memory_v2")
            snapshots = list_snapshots(temp)
            self.assertEqual(len(snapshots), 2)
            names = {s["name"] for s in snapshots}
            self.assertEqual(names, {"memory_v1", "memory_v2"})
            for snap in snapshots:
                self.assertGreater(snap["files"], 0)
                self.assertGreater(snap["size_bytes"], 0)
                self.assertIn("created", snap)

    def test_cli_rollback_list_and_missing_to(self) -> None:
        from memory_fabric.cli import main

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            create_snapshot(temp, name="memory_v1")
            self.assertEqual(main(["--cwd", temp, "rollback", "--list"]), 0)
            self.assertEqual(main(["--cwd", temp, "rollback"]), 1)

    def test_prune_dream_artifacts_keeps_newest(self) -> None:
        """P-11: retention removes all but the newest N snapshots/candidates."""
        from memory_fabric.storage import prune_dream_artifacts

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            memory_dir = Path(temp) / ".ai-memory"
            for i in range(5):
                create_snapshot(temp, name=f"memory_v{i}")
            candidates = memory_dir / "candidates"
            candidates.mkdir(exist_ok=True)
            for i in range(4):
                (candidates / f"memory-cand-{i}").mkdir()

            dry = prune_dream_artifacts(temp, keep_snapshots=2, keep_candidates=1, dry_run=True)
            self.assertEqual(len(dry["removed_snapshots"]), 3)
            self.assertEqual(
                len(list((memory_dir / "snapshots").iterdir())), 5, "dry-run deletes nothing"
            )

            result = prune_dream_artifacts(temp, keep_snapshots=2, keep_candidates=1)
            self.assertEqual(len(result["removed_snapshots"]), 3)
            self.assertEqual(len(result["removed_candidates"]), 3)
            self.assertEqual(len(list((memory_dir / "snapshots").iterdir())), 2)
            self.assertEqual(len(list(candidates.iterdir())), 1)

            # protected names survive even beyond the keep window
            again = prune_dream_artifacts(
                temp,
                keep_snapshots=0,
                keep_candidates=0,
                protect={p.name for p in (memory_dir / "snapshots").iterdir()},
            )
            self.assertEqual(again["removed_snapshots"], [])
            self.assertEqual(len(list((memory_dir / "snapshots").iterdir())), 2)

    def test_dream_apply_prunes_old_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, "architecture/notes", "# Notes\n\nFact.", title="Notes")
            memory_dir = Path(temp) / ".ai-memory"
            with mock.patch.dict(
                os.environ,
                {"MEMORY_FABRIC_KEEP_SNAPSHOTS": "2", "MEMORY_FABRIC_KEEP_CANDIDATES": "1"},
            ):
                for _ in range(4):
                    dream(temp, mode="light", apply=True)

            snap_count = len([p for p in (memory_dir / "snapshots").iterdir() if p.is_dir()])
            cand_count = len([p for p in (memory_dir / "candidates").iterdir() if p.is_dir()])
            self.assertLessEqual(snap_count, 2)
            self.assertLessEqual(cand_count, 1)

    def test_status_reports_snapshot_and_candidate_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            create_snapshot(temp, name="memory_v1")
            res = status(temp)
            self.assertEqual(res["snapshots"]["count"], 1)
            self.assertEqual(res["snapshots"]["latest"], "memory_v1")
            self.assertEqual(res["candidates_count"], 0)

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
            # Resolve, matching validate_cwd()'s internal resolution: on Windows,
            # tempfile's TEMP can be an 8.3 short-name path (e.g. RUNNER~1) that
            # differs textually from the long-name form the app returns.
            memory_dir = Path(temp).resolve() / ".ai-memory"

            self.assertTrue((memory_dir / "evals" / "latest.json").exists())
            self.assertTrue((memory_dir / "evals" / "latest.md").exists())
            self.assertIn(str(memory_dir / "evals" / "latest.json"), result["report_paths"])
            self.assertIn("evals/", (memory_dir / ".gitignore").read_text(encoding="utf-8"))

    def test_memory_eval_detects_template_content_and_llm_review_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = evaluate_memory_fabric(temp, save_report=False, llm_review=True)
            check_ids = [
                check["id"] for category in result["categories"] for check in category["checks"]
            ]

            # Store-first model: starter maps are generated (not placeholder-checked);
            # the empty store and the steering starter templates are what eval flags.
            self.assertIn("memory_store_empty", check_ids)
            self.assertIn("framework-rules_placeholder", check_ids)
            self.assertIn("architecture_generated", check_ids)
            self.assertTrue(
                any("MEMORY_FABRIC_LLM_PROVIDER" in note for note in result["llm_notes"])
            )

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
            write_local_memory(
                temp,
                "schemas",
                "# Schemas\n\nCustomerProfile includes locale and timezone.",
                mode="replace",
            )
            latest = create_snapshot(temp, name="memory_new")
            (Path(temp) / ".ai-memory" / "schemas.md").unlink()

            self.assertEqual(latest_snapshot(temp), latest)
            result = evaluate_dream_quality(temp, snapshot="latest", save_report=False)

            self.assertEqual(result["baseline_snapshot"], "memory_new")
            self.assertTrue(
                any("removed memory sections" in item for item in result["regressions"])
            )

    def test_dream_candidate_mode_is_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            line = "Shared architecture note that is intentionally duplicated across sections for consolidation checks."
            write_local_memory(
                temp, "architecture", f"# Architecture\n\n- {line}\n", mode="replace"
            )
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

    def test_dream_skips_malformed_store_file_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            # Simulate a memory-store file written without going through
            # write_memory_store (e.g. hand-edited, or written directly with a
            # native filesystem tool) so it never got a YAML frontmatter header.
            store_root = Path(temp) / ".ai-memory" / "memory-store"
            store_root.mkdir(parents=True, exist_ok=True)
            bad_file = store_root / "no_frontmatter.md"
            bad_file.write_text("# Just a heading\n\nNo frontmatter at all.\n", encoding="utf-8")

            # Must not raise FrontmatterError — previously this crashed the
            # whole `ai-memory dream` command for both LLM and non-LLM runs.
            result = dream(temp, mode="light", apply=False)

            self.assertTrue(
                any("no_frontmatter.md" in w and "frontmatter" in w.lower() for w in result["warnings"]),
                result["warnings"],
            )

    def test_dream_apply_mode_updates_live_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            line = "This duplicate line should be consolidated by Dreaming apply mode for live memory updates."
            write_local_memory(
                temp, "architecture", f"# Architecture\n\n- {line}\n", mode="replace"
            )
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
            self.assertTrue(any("post-commit" in f for f in result["files_created"]))
            content = post_commit_path.read_text(encoding="utf-8")
            self.assertIn("dream --mode light --apply", content)
            # P-04: hooks must pin the CLI that created them instead of relying
            # on a bare PATH lookup, and must fail audibly instead of `|| true`.
            self.assertIn('MEMORY_FABRIC_BIN="', content)
            self.assertIn("memory-fabric: hook skipped (ai-memory not found)", content)
            self.assertIn("memory-fabric: capture failed (non-fatal)", content)
            self.assertNotIn("|| true\n", content.replace("2>/dev/null || true", ""))

    def test_init_install_hooks_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            git_dir = Path(temp) / ".git"
            git_dir.mkdir()
            initialize_memory_fabric(temp, install_hooks=True)
            post_commit_path = git_dir / "hooks" / "post-commit"
            first = post_commit_path.read_text(encoding="utf-8")

            second_result = initialize_memory_fabric(temp, install_hooks=True)
            self.assertEqual(first, post_commit_path.read_text(encoding="utf-8"))
            self.assertFalse(any("post-commit" in f for f in second_result["files_created"]))

    def test_init_install_hooks_upgrades_legacy_hook_lines(self) -> None:
        """Hooks written by pre-0.7.1 installers get rewritten in place."""
        with tempfile.TemporaryDirectory() as temp:
            git_dir = Path(temp) / ".git"
            git_dir.mkdir()
            hooks_dir = git_dir / "hooks"
            hooks_dir.mkdir()
            post_commit_path = hooks_dir / "post-commit"
            post_commit_path.write_text(
                "#!/bin/sh\n"
                "echo 'user line'\n"
                "# Added by Memory Fabric installer\n"
                "ai-memory capture || true\n"
                "ai-memory dream --mode light --apply || true\n",
                encoding="utf-8",
            )

            initialize_memory_fabric(temp, install_hooks=True)
            content = post_commit_path.read_text(encoding="utf-8")
            self.assertIn("echo 'user line'", content)
            self.assertNotIn("ai-memory capture || true", content)
            self.assertNotIn("ai-memory dream --mode light --apply || true", content)
            self.assertIn('MEMORY_FABRIC_BIN="', content)
            self.assertEqual(content.count("dream --mode light --apply"), 1)

    def test_doctor_warns_when_hook_binary_is_unresolvable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            git_dir = Path(temp) / ".git"
            git_dir.mkdir()
            hooks_dir = git_dir / "hooks"
            hooks_dir.mkdir()
            (hooks_dir / "post-commit").write_text(
                "#!/bin/sh\n# Memory Fabric post-commit hook\n"
                'MEMORY_FABRIC_BIN="C:/nonexistent/venv/Scripts/ai-memory.exe"\n'
                '"$MEMORY_FABRIC_BIN" capture\n',
                encoding="utf-8",
            )
            initialize_memory_fabric(temp)
            with mock.patch("memory_fabric.storage.lifecycle.shutil.which", return_value=None):
                res = doctor(temp)
            self.assertTrue(
                any("post-commit" in w and "does not exist" in w for w in res["warnings"])
            )

    def test_cli_reconfigures_legacy_console_to_utf8(self) -> None:
        """P-05: em-dashes/bullets must not turn into `?` on cp1252 consoles."""
        from memory_fabric.cli import _ensure_utf8_output

        legacy = mock.MagicMock()
        legacy.encoding = "cp1252"
        with mock.patch("sys.stdout", legacy), mock.patch("sys.stderr", legacy):
            _ensure_utf8_output()
        legacy.reconfigure.assert_called_with(encoding="utf-8", errors="replace")

        already_utf8 = mock.MagicMock()
        already_utf8.encoding = "utf-8"
        with mock.patch("sys.stdout", already_utf8), mock.patch("sys.stderr", already_utf8):
            _ensure_utf8_output()
        already_utf8.reconfigure.assert_not_called()

    def test_doctor_warns_on_path_installation_drift(self) -> None:
        """P-01: a different `ai-memory` shadowing this one on PATH is surfaced."""
        from memory_fabric.storage.lifecycle import _check_install_drift

        warnings: list[str] = []
        with mock.patch(
            "memory_fabric.storage.lifecycle.shutil.which",
            return_value=r"C:\somewhere-else\Scripts\ai-memory.exe",
        ):
            _check_install_drift(warnings)
        self.assertTrue(any("different installation" in w for w in warnings))

        clean: list[str] = []
        with mock.patch("memory_fabric.storage.lifecycle.shutil.which", return_value=None):
            _check_install_drift(clean)
        self.assertEqual(clean, [])

    def test_pypi_drift_check_warns_and_is_silent_offline(self) -> None:
        from memory_fabric.storage.lifecycle import _check_pypi_drift

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"info": {"version": "99.0.0"}}'

        warnings: list[str] = []
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            _check_pypi_drift(warnings)
        self.assertTrue(any("99.0.0" in w for w in warnings))

        offline: list[str] = []
        with mock.patch("urllib.request.urlopen", side_effect=OSError("no network")):
            _check_pypi_drift(offline)
        self.assertEqual(offline, [])

    def test_init_install_hooks_without_git_emits_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = initialize_memory_fabric(temp, install_hooks=True)
            self.assertIn("Git repository not found", result["warnings"][0])

    def test_status_includes_memory_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_local_memory(
                temp, "architecture", "# Architecture\n\nSome important rules.", mode="replace"
            )
            res = status(temp)

            self.assertIn("architecture.md", res["memory_sizes"])
            self.assertGreater(res["memory_sizes"]["architecture.md"]["bytes"], 0)
            self.assertGreater(res["memory_sizes"]["architecture.md"]["tokens"], 0)
            self.assertEqual(res["version"], __version__)

    def test_doctor_is_clean_right_after_init(self) -> None:
        """P-03: a scaffold created by init must pass its own health check.

        Environment-dependent warnings (rg missing, PATH drift, mcp extra) are
        tolerated; the seven index-consistency warnings the v0.7.0 campaign
        hit right after following the Quick Start must be gone.
        """
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            res = doctor(temp)
            self.assertTrue(res["ok"])
            index_warnings = [
                w
                for w in res["warnings"]
                if "index.md" in w or "memory-store" in w or "missing" in w.lower()
            ]
            self.assertEqual(index_warnings, [])
            store_index = Path(temp) / ".ai-memory" / "memory-store" / "index.md"
            self.assertTrue(store_index.exists())

    def test_doctor_checks_permissions_and_index_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            res = doctor(temp)
            self.assertTrue(res["ok"])

            (Path(temp) / ".ai-memory" / "schemas.md").unlink()
            res2 = doctor(temp)
            self.assertTrue(
                any(
                    "missing from index.md" in w or "file does not exist" in w
                    for w in res2["warnings"]
                )
            )

    def test_dream_ingests_git_diff_and_scans_secrets_and_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            # Generated maps are exempt from staleness (they regenerate on every
            # Dream); steering sections are hand-curated and still age.
            rules_path = Path(temp) / ".ai-memory" / "framework-rules.md"
            rules_text = rules_path.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(rules_text)
            metadata["last_updated"] = "2020-01-01T12:00:00-04:00"
            from memory_fabric.frontmatter import dump_frontmatter

            rules_path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")

            private_dir = Path(temp) / ".ai-memory" / "private"
            private_dir.mkdir(exist_ok=True)
            (private_dir / "session_transcripts.md").write_text(
                "API_KEY = 'sk-abcdefghijklmnopqrstuvwxyz1234567890'", encoding="utf-8"
            )

            result = dream(temp, apply=True, mode="light")

            self.assertTrue(any("marked as stale" in w for w in result["warnings"]))
            self.assertTrue(any("redacted" in w for w in result["warnings"]))
            self.assertGreater(result["redactions"], 0)

            new_rules_text = rules_path.read_text(encoding="utf-8")
            new_metadata, _ = parse_frontmatter(new_rules_text)
            self.assertEqual(new_metadata.get("review_status"), "stale")

    @mock.patch("sys.stdin.isatty", return_value=True)
    @mock.patch("builtins.input", return_value="y")
    def test_cli_sync_global_interactive(self, mock_input, mock_isatty) -> None:
        from memory_fabric.cli import main

        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as global_home:
            os.environ["MEMORY_FABRIC_HOME"] = global_home
            try:
                initialize_memory_fabric(temp)
                write_local_memory(
                    temp, "decisions", "# Decisions\n\nRule details.", mode="replace"
                )

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

            _ = initialize_memory_fabric(temp, install_hooks=True)
            self.assertTrue(post_commit_path.exists())
            content = post_commit_path.read_text(encoding="utf-8")
            self.assertIn("echo 'hello'", content)
            self.assertIn("dream --mode light --apply", content)
            self.assertIn('MEMORY_FABRIC_BIN="', content)

    @mock.patch("sys.stdin.isatty", return_value=True)
    def test_cli_sync_global_interactive_append(self, mock_isatty) -> None:
        from memory_fabric.cli import main

        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as global_home:
            os.environ["MEMORY_FABRIC_HOME"] = global_home
            try:
                initialize_memory_fabric(temp)
                write_local_memory(
                    temp, "decisions", "# Decisions\n\nRule details local.", mode="replace"
                )

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
                global_decisions.write_text(
                    dump_frontmatter(meta, "# Decisions\n\nRule details global."), encoding="utf-8"
                )

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
                'summary: "Extracted decisions summary."\n'
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
            self.assertNotIn(
                "---", section["text"].split("---", 2)[2]
            )  # verify no second frontmatter in body

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
            json.dumps(
                {"candidates": [{"content": {"parts": [{"text": "gemini result"}]}}]}
            ).encode("utf-8")
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

    @mock.patch("memory_fabric.storage.dream.call_llm", new_callable=mock.AsyncMock)
    def test_dream_with_llm(self, mock_call_llm) -> None:
        import json

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            # Store-first model: facts live in the store; the LLM consolidates
            # store files and the root map is regenerated from them.
            write_memory_store(
                temp,
                "architecture/core-design",
                "# Core Design\n\nDraft architecture notes.",
                title="Core Design",
            )

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            consolidation_response = json.dumps(
                {
                    "consolidated_files": {
                        "store/architecture/core-design": "# Core Design\n\nConsolidated LLM content."
                    },
                    "contradictions": ["Mismatched settings"],
                    "warnings": ["Warning about schema"],
                }
            )

            def mock_llm_func(prompt, system_instruction="", *args, **kwargs):
                if "consolidated_files" in prompt:
                    return consolidation_response
                return "Mocked concise summary of section"

            mock_call_llm.side_effect = mock_llm_func

            result = dream(temp, mode="deep", apply=True)
            self.assertTrue(result["changed"])
            self.assertTrue(
                any("Contradiction detected: Mismatched settings" in w for w in result["warnings"])
            )
            self.assertTrue(
                any("Consolidation warning: Warning about schema" in w for w in result["warnings"])
            )

            # Verify the store file is updated
            store_text = read_memory_store(temp, "architecture/core-design")["text"]
            self.assertIn("Consolidated LLM content", store_text)

            # And the root map is a generated view listing the store entry
            arch = read_section(temp, "architecture")
            self.assertTrue(arch["metadata"].get("generated"))
            self.assertIn("architecture/core-design", arch["text"])

            # Clean up env
            os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
            os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.llm.call_llm", new_callable=mock.AsyncMock)
    def test_eval_with_llm_review(self, mock_call_llm) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            mock_call_llm.return_value = (
                "- Focus on schema definitions.\n- Simplify code standards."
            )

            result = evaluate_memory_fabric(temp, save_report=False, llm_review=True)
            self.assertTrue(
                any("Focus on schema definitions" in note for note in result["llm_notes"])
            )
            self.assertTrue(any("Simplify code standards" in note for note in result["llm_notes"]))

            # Clean up env
            os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
            os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.llm.call_llm", new_callable=mock.AsyncMock)
    def test_eval_with_llm_review_failure(self, mock_call_llm) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            mock_call_llm.side_effect = Exception("API connection timed out")

            result = evaluate_memory_fabric(temp, save_report=False, llm_review=True)
            self.assertTrue(
                any(
                    "Failed to generate qualitative LLM review" in note
                    for note in result["llm_notes"]
                )
            )
            self.assertTrue(any("API connection timed out" in note for note in result["llm_notes"]))

            # Clean up env
            os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
            os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("time.sleep")
    @mock.patch("urllib.request.urlopen")
    def test_llm_retry_on_429_then_success(self, mock_urlopen, mock_sleep) -> None:
        import json
        import urllib.error

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
            json.dumps(
                {"candidates": [{"content": {"parts": [{"text": "retry success"}]}}]}
            ).encode("utf-8")
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
        from memory_fabric.llm import LLMError

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

    @mock.patch("memory_fabric.storage.finalize.call_llm", new_callable=mock.AsyncMock)
    def test_dream_summary_skips_when_hash_matches(self, mock_call_llm) -> None:
        import hashlib
        from memory_fabric.frontmatter import dump_frontmatter

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

            # Store-first model: delete the starter root sections and keep a
            # single store fact — flat maps are generated and never summarized.
            for p in (Path(temp) / ".ai-memory").glob("*.md"):
                p.unlink()
            write_memory_store(
                temp,
                "architecture/core",
                "# Core\n\nArchitecture details worth summarizing.",
                title="Core",
            )
            store_file = Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "core.md"

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            # Return different times on successive calls to prevent snapshot collisions.
            # Shared across both mocks (dream's own now_iso + snapshots.create_snapshot's
            # now_iso) so the counter doesn't restart and collide between the two.
            call_count = 0

            def increment_now_iso():
                nonlocal call_count
                call_count += 1
                return f"2026-06-02T13:00:{call_count:02d}-04:00"

            mock_now_iso.side_effect = increment_now_iso
            mock_snapshot_now_iso.side_effect = increment_now_iso

            try:
                # 1. Run first dream: will generate a summary
                mock_call_llm.return_value = "Custom architecture summary."
                res1 = dream(temp, mode="deep", apply=True)

                self.assertTrue(res1["changed"])
                self.assertEqual(
                    mock_call_llm.call_count, 2
                )  # 1 consolidation call + 1 summary call

                # Check that summary_hash exists in metadata
                metadata, body = parse_frontmatter(store_file.read_text(encoding="utf-8"))
                self.assertEqual(metadata.get("summary"), "Custom architecture summary.")
                expected_hash = hashlib.md5(body.strip().encode("utf-8")).hexdigest()
                self.assertEqual(metadata.get("summary_hash"), expected_hash)

                # 2. Run second dream: body is identical, summary is custom, hash matches -> skips LLM call
                mock_call_llm.reset_mock()
                _ = dream(temp, mode="deep", apply=True)
                self.assertEqual(
                    mock_call_llm.call_count, 1
                )  # 1 consolidation call + 0 summary calls

                # 3. Modify body: hash mismatch -> calls LLM
                metadata["last_updated"] = "2026-06-02T13:00:00-04:00"
                body = "# Core\n\nNew modified content here."
                store_file.write_text(dump_frontmatter(metadata, body), encoding="utf-8")

                mock_call_llm.reset_mock()
                mock_call_llm.return_value = "New custom architecture summary."
                _ = dream(temp, mode="deep", apply=True)
                self.assertEqual(
                    mock_call_llm.call_count, 2
                )  # 1 consolidation call + 1 summary call

                metadata2, body2 = parse_frontmatter(store_file.read_text(encoding="utf-8"))
                self.assertEqual(metadata2.get("summary"), "New custom architecture summary.")

            finally:
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("GEMINI_API_KEY", None)

    @mock.patch("memory_fabric.storage.finalize.call_llm", new_callable=mock.AsyncMock)
    def test_dream_consolidation_skips_when_hash_matches(self, mock_call_llm) -> None:
        import json
        from memory_fabric.frontmatter import dump_frontmatter

        # dream() calls call_llm directly (consolidation prompt) and finalize's
        # _process_and_finalize_candidate also calls it (per-section summaries) —
        # both references must be the *same* mock so call_count/side_effect are shared.
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch("memory_fabric.storage.dream.call_llm", new=mock_call_llm),
            mock.patch("memory_fabric.storage.finalize.now_iso") as mock_now_iso,
            mock.patch("memory_fabric.storage.snapshots.now_iso") as mock_snapshot_now_iso,
            mock.patch("memory_fabric.storage.consolidation.now_iso") as mock_consolidation_now_iso,
        ):
            initialize_memory_fabric(temp)

            # Store-first model: a single store fact is the consolidation target;
            # root maps are generated views excluded from the hash and the LLM.
            for p in (Path(temp) / ".ai-memory").glob("*.md"):
                p.unlink()
            write_memory_store(
                temp,
                "architecture/core",
                "# Core\n\nDraft architecture notes.",
                title="Core",
            )
            store_file = Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "core.md"

            os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "gemini-key"

            call_count = 0

            def increment_now_iso():
                nonlocal call_count
                call_count += 1
                return f"2026-06-02T13:00:{call_count:02d}-04:00"

            mock_now_iso.side_effect = increment_now_iso
            mock_snapshot_now_iso.side_effect = increment_now_iso
            mock_consolidation_now_iso.side_effect = increment_now_iso

            try:
                # 1. First dream run
                mock_call_llm.side_effect = [
                    json.dumps(
                        {
                            "consolidated_files": {
                                "store/architecture/core": "# Core\n\nConsolidated."
                            },
                            "contradictions": [],
                            "warnings": [],
                        }
                    ),
                    "Architecture summary.",
                ]
                res1 = dream(temp, mode="deep", apply=True)
                self.assertTrue(res1["changed"])
                self.assertEqual(mock_call_llm.call_count, 2)

                # 2. Second run: content, git diff, and files are identical -> skips consolidation LLM call!
                mock_call_llm.reset_mock()
                res2 = dream(temp, mode="deep", apply=True)
                self.assertEqual(mock_call_llm.call_count, 0)  # exactly 0 calls!
                # P-15: identical content no longer churns the regenerated
                # indexes — a fully redundant dream leaves the tree untouched
                # (this assertion previously documented the timestamp churn).
                self.assertEqual(res2["affected_files"], [])
                self.assertFalse(res2["changed"])

                # 3. Third run: let's modify the file content so hash mismatches
                store_meta, store_body = parse_frontmatter(store_file.read_text(encoding="utf-8"))
                store_file.write_text(
                    dump_frontmatter(store_meta, store_body + "\nNew change.\n"), encoding="utf-8"
                )

                mock_call_llm.reset_mock()
                mock_call_llm.side_effect = [
                    json.dumps(
                        {
                            "consolidated_files": {
                                "store/architecture/core": "# Core\n\nConsolidated again."
                            },
                            "contradictions": [],
                            "warnings": [],
                        }
                    ),
                    "New architecture summary.",
                ]
                res3 = dream(temp, mode="deep", apply=True)
                self.assertTrue(res3["changed"])
                self.assertEqual(mock_call_llm.call_count, 2)  # Consolidation + summary refreshed

            finally:
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("GEMINI_API_KEY", None)

    def test_index_includes_key_topics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            # Store-first model: facts live in the store; the store index table
            # extracts their key topics. Write one file with H2 headings…
            write_memory_store(
                temp,
                "decisions/local-model",
                (
                    "# Decisions\n\n"
                    "## Decision 1: Use local model\n"
                    "We decided to use Gemma.\n\n"
                    "## Decision 2: Run with CUDA\n"
                    "We decided to run with CUDA acceleration.\n"
                ),
                title="Local Model Decisions",
            )
            # …and another with only lists (no H2)
            write_memory_store(
                temp,
                "debt/cleanup",
                (
                    "# Technical Debt\n\n"
                    "- Fix the imports\n"
                    "- Clean the workspace files\n"
                    "- Add more logs\n"
                ),
                title="Cleanup Targets",
            )

            # Trigger Dreaming (light mode is enough to regenerate indexes)
            dream(temp, mode="light", apply=True)

            index_path = Path(temp) / ".ai-memory" / "index.md"
            self.assertTrue(index_path.exists())
            index_text = index_path.read_text(encoding="utf-8")

            # Verify the headers are updated in the root index table
            self.assertIn("| Section | Priority | Summary | Key Topics |", index_text)
            self.assertIn("| --- | --- | --- | --- |", index_text)

            store_index_path = Path(temp) / ".ai-memory" / "memory-store" / "index.md"
            self.assertTrue(store_index_path.exists())
            store_index_text = store_index_path.read_text(encoding="utf-8")

            # Verify the extracted H2 topics are correct in the store index table
            self.assertIn(
                "• Decision 1: Use local model<br>• Decision 2: Run with CUDA", store_index_text
            )

            # Verify fallback bullet list topics are correct
            self.assertIn(
                "• Fix the imports<br>• Clean the workspace files<br>• Add more logs",
                store_index_text,
            )

            # Root maps were regenerated from the store and listed in the root index
            self.assertIn("| `decisions` |", index_text)
            self.assertIn("| `debt` |", index_text)

            # Run doctor to ensure index consistency validation is happy
            res_doctor = doctor(temp)
            self.assertTrue(res_doctor["ok"])

    def test_consolidated_memory_generation_and_optimization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_local_memory(
                temp, "architecture", "# Architecture\n\nActive arch details.", mode="replace"
            )
            write_local_memory(
                temp, "decisions", "# Decisions\n\nActive decision details.", mode="replace"
            )

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
            self.assertIn(
                "omitted because it exceeded the remaining token budget", small_bundle["text"]
            )

    def test_server_main_stdio(self) -> None:
        import memory_fabric.server as server

        with mock.patch.object(server.FastMCP, "run") as mock_run:
            code = server.main(["--transport", "stdio"])
            self.assertEqual(code, 0)
            mock_run.assert_called_once_with(transport="stdio")

    def test_server_main_sse(self) -> None:
        import memory_fabric.server as server

        with mock.patch.object(server.FastMCP, "run") as mock_run:
            orig_host = server.mcp.settings.host
            orig_port = server.mcp.settings.port
            orig_enable = server.mcp.settings.transport_security.enable_dns_rebinding_protection
            orig_hosts = server.mcp.settings.transport_security.allowed_hosts
            orig_origins = server.mcp.settings.transport_security.allowed_origins

            try:
                code = server.main(
                    [
                        "--transport",
                        "sse",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8888",
                        "--allow-all-origins",
                    ]
                )
                self.assertEqual(code, 0)
                mock_run.assert_called_once_with(transport="sse")
                self.assertEqual(server.mcp.settings.host, "127.0.0.1")
                self.assertEqual(server.mcp.settings.port, 8888)
                self.assertFalse(
                    server.mcp.settings.transport_security.enable_dns_rebinding_protection
                )
                self.assertEqual(server.mcp.settings.transport_security.allowed_hosts, ["*"])
                self.assertEqual(server.mcp.settings.transport_security.allowed_origins, ["*"])
            finally:
                server.mcp.settings.host = orig_host
                server.mcp.settings.port = orig_port
                server.mcp.settings.transport_security.enable_dns_rebinding_protection = orig_enable
                server.mcp.settings.transport_security.allowed_hosts = orig_hosts
                server.mcp.settings.transport_security.allowed_origins = orig_origins

    @mock.patch("sys.stderr")
    @mock.patch("urllib.request.urlopen")
    def test_llm_debugging_logging(self, mock_urlopen, mock_stderr) -> None:
        import json

        class MockResponse:
            def __init__(self, data: bytes):
                self.data = data

            def read(self, *args, **kwargs):
                return self.data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        mock_urlopen.return_value = MockResponse(
            json.dumps({"choices": [{"message": {"content": "logged response"}}]}).encode("utf-8")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            orig_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                # 1. No debug logging by default
                os.environ.pop("MEMORY_FABRIC_LLM_DEBUG", None)
                os.environ["MEMORY_FABRIC_LLM_PROVIDER"] = "openai"
                os.environ["OPENAI_API_KEY"] = "sk-super-secret-key"

                mock_stderr.write.reset_mock()
                call_llm("test prompt", "system instructions")
                mock_stderr.write.assert_not_called()
                self.assertFalse(Path("llm_debug.log").exists())

                # 2. Debug logging to stderr
                os.environ["MEMORY_FABRIC_LLM_DEBUG"] = "stderr"
                mock_stderr.write.reset_mock()
                call_llm("test prompt", "system instructions")

                # Check that stderr received the log containing prompt and URL
                self.assertTrue(
                    any(
                        "--- LLM REQUEST ---" in call[0][0]
                        for call in mock_stderr.write.call_args_list
                    )
                )
                self.assertTrue(
                    any("openai" in call[0][0] for call in mock_stderr.write.call_args_list)
                )
                self.assertTrue(
                    any("[REDACTED]" in call[0][0] for call in mock_stderr.write.call_args_list)
                )
                # Ensure sk-super-secret-key was NOT written
                self.assertFalse(
                    any(
                        "sk-super-secret-key" in call[0][0]
                        for call in mock_stderr.write.call_args_list
                    )
                )
                self.assertFalse(Path("llm_debug.log").exists())

                # 3. Debug logging to a custom file path
                custom_log_path = Path("custom_debug.log")
                os.environ["MEMORY_FABRIC_LLM_DEBUG"] = str(custom_log_path)
                mock_stderr.write.reset_mock()
                call_llm("test prompt", "system instructions")

                # Should not write to stderr
                mock_stderr.write.assert_not_called()
                self.assertTrue(custom_log_path.exists())
                log_content = custom_log_path.read_text(encoding="utf-8")
                self.assertIn("--- LLM REQUEST ---", log_content)
                self.assertIn("--- LLM RESPONSE ---", log_content)
                self.assertIn("[REDACTED]", log_content)
                self.assertNotIn("sk-super-secret-key", log_content)

                # 4. Debug logging using "1" or "true" without .ai-memory directory
                os.environ["MEMORY_FABRIC_LLM_DEBUG"] = "1"
                mock_stderr.write.reset_mock()
                call_llm("test prompt", "system instructions")
                self.assertTrue(
                    any(
                        "--- LLM REQUEST ---" in call[0][0]
                        for call in mock_stderr.write.call_args_list
                    )
                )
                self.assertTrue(Path("llm_debug.log").exists())
                default_log_content = Path("llm_debug.log").read_text(encoding="utf-8")
                self.assertIn("--- LLM REQUEST ---", default_log_content)

                # 5. Debug logging using "1" or "true" with .ai-memory directory
                Path(".ai-memory").mkdir()
                Path("llm_debug.log").unlink()  # Remove the previous one
                call_llm("test prompt", "system instructions")
                self.assertTrue((Path(".ai-memory") / "llm_debug.log").exists())
                aimem_log_content = (Path(".ai-memory") / "llm_debug.log").read_text(
                    encoding="utf-8"
                )
                self.assertIn("--- LLM REQUEST ---", aimem_log_content)

            finally:
                os.chdir(orig_cwd)
                os.environ.pop("MEMORY_FABRIC_LLM_DEBUG", None)
                os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)
                os.environ.pop("OPENAI_API_KEY", None)


class MemoryStoreTests(unittest.TestCase):
    def test_store_write_creates_nested_file_with_frontmatter(self) -> None:
        from memory_fabric.storage import write_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_memory_store(
                temp,
                store_path="architecture/decisions/auth-service",
                content="Use JWT for authentication.",
                title="Auth Service Decision",
                tags=["auth", "jwt"],
                priority="high",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(result["store_path"], "architecture/decisions/auth-service")
            self.assertIn("auth-service.md", result["path"])

            # Verify file exists and has valid frontmatter
            path = Path(result["path"])
            self.assertTrue(path.exists())
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["store_path"], "architecture/decisions/auth-service")
            self.assertEqual(metadata["title"], "Auth Service Decision")
            self.assertEqual(metadata["tags"], ["auth", "jwt"])
            self.assertEqual(metadata["priority"], "high")
            self.assertIn("Use JWT", body)

    def test_store_append_without_priority_preserves_existing(self) -> None:
        """P-08: frontmatter fields omitted on append inherit from the file."""
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                store_path="architecture/decisions/task-due-dates",
                content="Due dates are ISO 8601 strings.",
                priority="high",
                tags=["schema", "taskmaster", "due-date"],
                mode="replace",
            )
            write_memory_store(
                temp,
                store_path="architecture/decisions/task-due-dates",
                content="Follow-up: overdue checks compare date objects.",
                mode="append",
            )

            res = read_memory_store(temp, "architecture/decisions/task-due-dates")
            self.assertEqual(res["metadata"].get("priority"), "high")
            self.assertEqual(res["metadata"].get("tags"), ["schema", "taskmaster", "due-date"])
            self.assertIn("Follow-up", res["text"])

    def test_store_new_file_without_priority_defaults_to_medium(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_memory_store(temp, "debt/no-priority", "A note.")
            metadata, _ = parse_frontmatter(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("priority"), "medium")

    def test_store_replace_clears_derived_review_status(self) -> None:
        """P-14 (write side): replace drops derived state like review_status."""
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_memory_store(temp, "schemas/rewrite-me", "Old content.")
            path = Path(result["path"])
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            metadata["review_status"] = "broken-evidence"
            from memory_fabric.frontmatter import dump_frontmatter

            path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")

            write_memory_store(temp, "schemas/rewrite-me", "New content.", mode="replace")
            metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertNotIn("review_status", metadata)

            # append keeps derived state untouched
            metadata["review_status"] = "stale"
            path.write_text(dump_frontmatter(metadata, _), encoding="utf-8")
            write_memory_store(temp, "schemas/rewrite-me", "More.", mode="append")
            metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("review_status"), "stale")

    def test_propose_memory_patch_produces_parseable_unified_diff(self) -> None:
        """P-06: header lines must not be concatenated (`--- x+++ y@@`)."""
        from memory_fabric.storage import propose_memory_patch

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "architecture/decisions/task-due-dates",
                "Old decision line.",
                title="Due Dates",
            )
            preview = propose_memory_patch(
                temp,
                instructions=(
                    "store: architecture/decisions/task-due-dates\nNew paragraph about validation."
                ),
            )
            patch = preview["patch"]
            self.assertTrue(patch, "expected a non-empty patch")
            self.assertNotIn(")+++", patch)
            self.assertNotIn(")@@", patch)
            lines = patch.splitlines()
            self.assertTrue(lines[0].startswith("--- "))
            self.assertTrue(lines[1].startswith("+++ "))
            self.assertTrue(lines[2].startswith("@@ "))

    def test_store_write_redacts_secrets(self) -> None:
        from memory_fabric.storage import write_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_memory_store(
                temp,
                store_path="config/api-keys",
                content="OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890",
            )

            self.assertGreater(result["redactions"], 0)
            path = Path(result["path"])
            text = path.read_text(encoding="utf-8")
            self.assertIn("[REDACTED_SECRET]", text)
            self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz1234567890", text)

    def test_store_read_returns_content_and_metadata(self) -> None:
        from memory_fabric.storage import write_memory_store, read_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                store_path="bugs/fix-login",
                content="Fixed the login redirect issue.",
                title="Fix Login Redirect",
                tags=["bugfix"],
            )

            result = read_memory_store(temp, store_path="bugs/fix-login")
            self.assertEqual(result["store_path"], "bugs/fix-login")
            self.assertIn("Fixed the login redirect", result["text"])
            self.assertEqual(result["metadata"]["title"], "Fix Login Redirect")
            self.assertFalse(result["truncated"])

    def test_store_read_truncates_large_files(self) -> None:
        from memory_fabric.storage import write_memory_store, read_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                store_path="context/large-file",
                content="A" * 20000,
                title="Large Memory",
            )

            result = read_memory_store(temp, store_path="context/large-file", max_tokens=50)
            self.assertTrue(result["truncated"])
            self.assertIn("exceeded the token budget", result["text"])

    def test_store_list_returns_entries(self) -> None:
        from memory_fabric.storage import write_memory_store, list_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, store_path="bugs/fix-a", content="Fix A")
            write_memory_store(temp, store_path="bugs/fix-b", content="Fix B")
            write_memory_store(temp, store_path="arch/decision-c", content="Decision C")

            result = list_memory_store(temp)
            self.assertEqual(result["total"], 3)
            self.assertEqual(len(result["entries"]), 3)

            store_paths = [e["store_path"] for e in result["entries"]]
            self.assertIn("bugs/fix-a", store_paths)
            self.assertIn("bugs/fix-b", store_paths)
            self.assertIn("arch/decision-c", store_paths)

    def test_store_list_filters_by_prefix(self) -> None:
        from memory_fabric.storage import write_memory_store, list_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, store_path="bugs/fix-a", content="Fix A")
            write_memory_store(temp, store_path="arch/decision-b", content="Decision B")

            result = list_memory_store(temp, prefix="bugs")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["entries"][0]["store_path"], "bugs/fix-a")

    def test_store_list_filters_by_tags(self) -> None:
        from memory_fabric.storage import write_memory_store, list_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(temp, store_path="bugs/fix-a", content="Fix A", tags=["auth"])
            write_memory_store(temp, store_path="bugs/fix-b", content="Fix B", tags=["database"])

            result = list_memory_store(temp, tags=["auth"])
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["entries"][0]["store_path"], "bugs/fix-a")

    def test_store_delete_removes_file_and_empty_dirs(self) -> None:
        from memory_fabric.storage import write_memory_store, delete_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_result = write_memory_store(
                temp, store_path="deep/nested/file", content="Content"
            )
            file_path = Path(write_result["path"])
            self.assertTrue(file_path.exists())

            result = delete_memory_store(temp, store_path="deep/nested/file")
            self.assertTrue(result["changed"])
            self.assertFalse(file_path.exists())
            # Empty parent dirs should be cleaned up
            self.assertFalse((file_path.parent).exists())

    def test_store_path_validation_rejects_traversal(self) -> None:
        from memory_fabric.storage import _validate_store_path

        with self.assertRaises(ValueError):
            _validate_store_path("../etc/passwd")
        with self.assertRaises(ValueError):
            _validate_store_path("UPPERCASE")
        with self.assertRaises(ValueError):
            _validate_store_path("")
        with self.assertRaises(ValueError):
            _validate_store_path("a/b/c/d/e/f")  # > 5 levels
        # Valid paths should work
        segments = _validate_store_path("architecture/decisions/auth")
        self.assertEqual(segments, ["architecture", "decisions", "auth"])

    def test_store_search_included_in_keyword_search(self) -> None:
        from memory_fabric.storage import write_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                store_path="context/unique-keyword-xyz",
                content="This contains a unique-keyword-xyz marker.",
            )

            with mock.patch("shutil.which", return_value=None):
                results = keyword_search(temp, "unique-keyword-xyz")

            self.assertGreater(len(results), 0)
            store_results = [r for r in results if r["section"].startswith("store:")]
            self.assertGreater(len(store_results), 0)
            self.assertEqual(store_results[0]["section"], "store:context/unique-keyword-xyz")

    def test_store_files_appear_in_combined_context(self) -> None:
        from memory_fabric.storage import write_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                store_path="context/important-rule",
                content="Critical project rule: always use UTC timestamps.",
                priority="high",
            )

            bundle = read_combined_context(temp, max_tokens=20000)
            self.assertIn("Critical project rule", bundle["text"])
            store_sections = [s for s in bundle["included_sections"] if s.startswith("store/")]
            self.assertGreater(len(store_sections), 0)

    def test_init_creates_memory_store_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _ = initialize_memory_fabric(temp)
            store_dir = Path(temp) / ".ai-memory" / "memory-store"
            self.assertTrue(store_dir.exists())
            self.assertTrue((store_dir / ".gitkeep").exists())

    def test_store_index_generated_by_dreaming(self) -> None:
        from memory_fabric.storage import write_memory_store

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                store_path="architecture/api-design",
                content="REST API with versioning.",
                title="API Design",
                tags=["api", "rest"],
                priority="high",
            )

            dream(temp, mode="light", apply=True)

            index_path = Path(temp) / ".ai-memory" / "index.md"
            index_text = index_path.read_text(encoding="utf-8")
            self.assertIn("## Memory Store", index_text)
            self.assertIn("[Memory Store Index](memory-store/index.md)", index_text)

            store_index_path = Path(temp) / ".ai-memory" / "memory-store" / "index.md"
            self.assertTrue(store_index_path.exists())
            store_index_text = store_index_path.read_text(encoding="utf-8")
            self.assertIn("architecture/api-design", store_index_text)
            self.assertIn("api, rest", store_index_text)

    def test_call_llm_with_mcp_sampling(self) -> None:
        # Ensure direct LLM providers are disabled
        os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)

        # Mock Context, session and create_message
        mock_context = mock.MagicMock()
        mock_result = mock.MagicMock()
        mock_result.content = mock.MagicMock()
        mock_result.content.text = "mcp sampling response"

        mock_context.session.client_params.capabilities.sampling = mock.MagicMock()
        mock_context.session.create_message = mock.AsyncMock(return_value=mock_result)

        res = call_llm("test prompt", "system instructions", context=mock_context)
        self.assertEqual(res, "mcp sampling response")

        # Verify it was called with the correct parameters
        mock_context.session.create_message.assert_called_once()
        args, kwargs = mock_context.session.create_message.call_args
        self.assertEqual(kwargs["system_prompt"], "system instructions")
        messages = kwargs["messages"]
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].content.text, "test prompt")

    def test_load_env_from_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text(
                "TEST_ENV_VAR_1=value1\n"
                "# This is a comment\n"
                "TEST_ENV_VAR_2='value2 with spaces'\n"
                'TEST_ENV_VAR_3="value3"\n'
                "TEST_ENV_VAR_4=\n",
                encoding="utf-8",
            )

            # Pre-set TEST_ENV_VAR_1 to ensure it is not overwritten
            os.environ["TEST_ENV_VAR_1"] = "pre-set-value"

            from memory_fabric.llm import load_env_from_cwd

            load_env_from_cwd(temp)

            self.assertEqual(os.environ.get("TEST_ENV_VAR_1"), "pre-set-value")
            self.assertEqual(os.environ.get("TEST_ENV_VAR_2"), "value2 with spaces")
            self.assertEqual(os.environ.get("TEST_ENV_VAR_3"), "value3")
            self.assertEqual(os.environ.get("TEST_ENV_VAR_4"), "")

            # Cleanup
            for key in ("TEST_ENV_VAR_1", "TEST_ENV_VAR_2", "TEST_ENV_VAR_3", "TEST_ENV_VAR_4"):
                os.environ.pop(key, None)

    def test_call_llm_with_mcp_sampling_timeout(self) -> None:
        from memory_fabric.llm import LLMError

        # Ensure direct LLM providers are disabled
        os.environ.pop("MEMORY_FABRIC_LLM_PROVIDER", None)

        # Mock Context, session and create_message that raises TimeoutError
        mock_context = mock.MagicMock()
        mock_context.session.client_params.capabilities.sampling = mock.MagicMock()

        async def mock_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()

        mock_context.session.create_message = mock_timeout

        with self.assertRaises(LLMError) as ctx:
            call_llm("test prompt", "system instructions", context=mock_context)

        self.assertIn("timed out after 45 seconds", str(ctx.exception))
        self.assertIn("JSON-RPC", str(ctx.exception))
        self.assertIn("deadlock", str(ctx.exception))

    def test_split_dream_flow(self) -> None:
        from memory_fabric.storage import prepare_dream_payload, apply_dream_results
        import json

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)

            # Store-first model: delete the starter root sections and keep a
            # single store fact as the consolidation target.
            for p in (Path(temp) / ".ai-memory").glob("*.md"):
                p.unlink()
            write_memory_store(
                temp, "architecture/notes", "# Notes\n\nOriginal content.", title="Notes"
            )

            # 1. Prepare payload
            payload = prepare_dream_payload(temp, mode="light")
            self.assertFalse(payload["skip_required"])
            self.assertTrue(payload["snapshot"])
            self.assertIn("Original content.", payload["consolidation_prompt"])
            self.assertIn("store/architecture/notes", payload["sections_data"])

            # 2. Simulate client LLM consolidation response
            llm_response = json.dumps(
                {
                    "consolidated_files": {
                        "store/architecture/notes": "# Notes\n\nConsolidated by client."
                    },
                    "summaries": {
                        "store/architecture/notes": "Client generated architecture summary."
                    },
                    "contradictions": ["Simulated contradiction"],
                    "warnings": ["Simulated warning"],
                }
            )

            # 3. Apply results
            res = asyncio.run(
                apply_dream_results(
                    temp,
                    candidate_store=payload["candidate_store"],
                    llm_response=llm_response,
                    mode="light",
                    apply=True,
                )
            )

            self.assertTrue(res["changed"])
            self.assertFalse(res["apply_required"])
            self.assertTrue(
                any("Contradiction detected: Simulated contradiction" in w for w in res["warnings"])
            )

            # P-13 regression: apply without evaluation must survive the same
            # pydantic validation FastMCP applies to the tool result.
            try:
                from pydantic import TypeAdapter

                from memory_fabric.contracts import DreamResult

                TypeAdapter(DreamResult).validate_python(res)
            except ImportError:
                pass

            # Verify the store file content is updated
            notes_path = Path(temp) / ".ai-memory" / "memory-store" / "architecture" / "notes.md"
            metadata, body = parse_frontmatter(notes_path.read_text(encoding="utf-8"))
            self.assertIn("Consolidated by client.", body)
            self.assertEqual(metadata.get("summary"), "Client generated architecture summary.")

            # The root map was regenerated as a view over the store category
            arch_path = Path(temp) / ".ai-memory" / "architecture.md"
            map_meta, map_body = parse_frontmatter(arch_path.read_text(encoding="utf-8"))
            self.assertTrue(map_meta.get("generated"))
            self.assertIn("architecture/notes", map_body)

            # 4. Prepare payload again (no change) -> skip_required should be True
            import time

            time.sleep(1.1)
            payload2 = prepare_dream_payload(temp, mode="light")
            self.assertTrue(payload2["skip_required"])


if __name__ == "__main__":
    unittest.main()
