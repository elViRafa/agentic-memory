"""Stage 2 (ROADMAP_CAPTURE_HOOKS.md): client lifecycle-hook writer.

Covers the generalized `install_hooks()` registry/dispatcher and two
adapters: claude-code (SessionStart/Stop/PreCompact -> .claude/settings.json,
matcher-based blocks) and gemini-cli (SessionStart/AfterAgent/PreCompress ->
.gemini/settings.json, flat hook-definition lists, no matcher on lifecycle
events) — plus the CLI wiring (`install --with-hooks` and `session-start
--hook-format <client>`).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory_fabric.client_hooks import install_hooks


def _settings_path(temp: str) -> Path:
    return Path(temp) / ".claude" / "settings.json"


def _gemini_settings_path(temp: str) -> Path:
    return Path(temp) / ".gemini" / "settings.json"


class InstallCreatesExpectedHooksTests(unittest.TestCase):
    def test_fresh_install_creates_all_three_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install_hooks(temp, "claude-code")

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])
            self.assertTrue(result["supported"])
            path = _settings_path(temp)
            self.assertTrue(path.exists())

            config = json.loads(path.read_text(encoding="utf-8"))
            hooks = config["hooks"]

            session_start = hooks["SessionStart"]
            self.assertEqual({b["matcher"] for b in session_start}, {"startup", "resume"})
            for block in session_start:
                cmd = block["hooks"][0]["command"]
                self.assertIn("session-start", cmd)
                self.assertIn("--hook-format claude-code", cmd)
                self.assertIn("memory-fabric-managed", cmd)

            stop = hooks["Stop"]
            self.assertEqual(len(stop), 1)
            self.assertEqual(stop[0]["matcher"], "")
            self.assertIn("guard-journal", stop[0]["hooks"][0]["command"])

            precompact = hooks["PreCompact"]
            self.assertEqual({b["matcher"] for b in precompact}, {"manual", "auto"})
            for block in precompact:
                cmd = block["hooks"][0]["command"]
                self.assertIn("dream --mode light --apply", cmd)
                self.assertIn("|| true", cmd)

    def test_reinstall_is_byte_stable_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = install_hooks(temp, "claude-code")
            self.assertTrue(first["changed"])
            before = _settings_path(temp).read_text(encoding="utf-8")

            second = install_hooks(temp, "claude-code")
            self.assertFalse(second["changed"])
            after = _settings_path(temp).read_text(encoding="utf-8")
            self.assertEqual(before, after)

    def test_preserves_unrelated_settings_and_user_added_stop_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = _settings_path(temp)
            path.parent.mkdir(parents=True)
            existing = {
                "model": "opusplan",
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": "echo user-hook"}],
                        }
                    ]
                },
            }
            path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

            result = install_hooks(temp, "claude-code")
            self.assertTrue(result["changed"])

            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["model"], "opusplan")

            stop_hooks = config["hooks"]["Stop"][0]["hooks"]
            commands = [h["command"] for h in stop_hooks]
            self.assertIn("echo user-hook", commands)
            self.assertTrue(any("guard-journal" in c for c in commands))

    def test_dry_run_previews_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install_hooks(temp, "claude-code", dry_run=True)

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])
            self.assertFalse(_settings_path(temp).exists())
            self.assertIn("SessionStart", result["diff"])


class UninstallTests(unittest.TestCase):
    def test_uninstall_removes_only_managed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = _settings_path(temp)
            path.parent.mkdir(parents=True)
            existing = {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": "echo user-hook"}],
                        }
                    ]
                },
            }
            path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

            install_hooks(temp, "claude-code")
            result = install_hooks(temp, "claude-code", uninstall=True)

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])

            config = json.loads(path.read_text(encoding="utf-8"))
            # SessionStart and PreCompact were entirely ours -> event keys gone.
            self.assertNotIn("SessionStart", config.get("hooks", {}))
            self.assertNotIn("PreCompact", config.get("hooks", {}))
            # Stop had a user entry too -> the event survives with only that entry.
            stop_hooks = config["hooks"]["Stop"][0]["hooks"]
            commands = [h["command"] for h in stop_hooks]
            self.assertEqual(commands, ["echo user-hook"])

    def test_uninstall_with_nothing_to_remove_is_a_clean_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install_hooks(temp, "claude-code", uninstall=True)

            self.assertTrue(result["ok"])
            self.assertFalse(result["changed"])
            self.assertTrue(any("nothing to remove" in w for w in result["warnings"]))
            self.assertFalse(_settings_path(temp).exists())


class MalformedConfigTests(unittest.TestCase):
    def test_invalid_json_backs_up_and_aborts_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = _settings_path(temp)
            path.parent.mkdir(parents=True)
            path.write_text("{not valid json", encoding="utf-8")

            result = install_hooks(temp, "claude-code")

            self.assertFalse(result["ok"])
            self.assertTrue(result["backup_path"])
            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertEqual(
                Path(result["backup_path"]).read_text(encoding="utf-8"), "{not valid json"
            )
            # Original left untouched, not silently replaced with a fresh config.
            self.assertEqual(path.read_text(encoding="utf-8"), "{not valid json")
            self.assertTrue(any("invalid JSON" in w for w in result["warnings"]))


class UnsupportedClientTests(unittest.TestCase):
    def test_client_with_no_adapter_reports_plainly_not_silently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install_hooks(temp, "cursor")

            self.assertFalse(result["ok"])
            self.assertFalse(result["supported"])
            self.assertFalse(result["changed"])
            joined = " ".join(result["warnings"])
            self.assertIn("cursor", joined)
            self.assertIn("claude-code", joined)


class GeminiCliInstallCreatesExpectedHooksTests(unittest.TestCase):
    def test_fresh_install_creates_all_three_events_flat_no_matcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install_hooks(temp, "gemini-cli")

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])
            self.assertTrue(result["supported"])
            path = _gemini_settings_path(temp)
            self.assertTrue(path.exists())

            config = json.loads(path.read_text(encoding="utf-8"))
            hooks = config["hooks"]

            # Lifecycle events are flat hook-definition lists on Gemini CLI —
            # no {"matcher": ..., "hooks": [...]} wrapper like Claude Code.
            session_start = hooks["SessionStart"]
            self.assertEqual(len(session_start), 1)
            self.assertNotIn("matcher", session_start[0])
            cmd = session_start[0]["command"]
            self.assertIn("session-start", cmd)
            self.assertIn("--hook-format gemini-cli", cmd)
            self.assertIn("memory-fabric-managed", cmd)

            after_agent = hooks["AfterAgent"]
            self.assertEqual(len(after_agent), 1)
            self.assertIn("guard-journal", after_agent[0]["command"])

            precompress = hooks["PreCompress"]
            self.assertEqual(len(precompress), 1)
            self.assertIn("dream --mode light --apply", precompress[0]["command"])
            self.assertIn("|| true", precompress[0]["command"])

    def test_reinstall_is_byte_stable_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = install_hooks(temp, "gemini-cli")
            self.assertTrue(first["changed"])
            before = _gemini_settings_path(temp).read_text(encoding="utf-8")

            second = install_hooks(temp, "gemini-cli")
            self.assertFalse(second["changed"])
            after = _gemini_settings_path(temp).read_text(encoding="utf-8")
            self.assertEqual(before, after)

    def test_preserves_unrelated_settings_and_user_added_after_agent_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = _gemini_settings_path(temp)
            path.parent.mkdir(parents=True)
            existing = {
                "theme": "dark",
                "hooks": {"AfterAgent": [{"type": "command", "command": "echo user-hook"}]},
            }
            path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

            result = install_hooks(temp, "gemini-cli")
            self.assertTrue(result["changed"])

            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["theme"], "dark")

            commands = [h["command"] for h in config["hooks"]["AfterAgent"]]
            self.assertIn("echo user-hook", commands)
            self.assertTrue(any("guard-journal" in c for c in commands))

    def test_dry_run_previews_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install_hooks(temp, "gemini-cli", dry_run=True)

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])
            self.assertFalse(_gemini_settings_path(temp).exists())
            self.assertIn("SessionStart", result["diff"])


class GeminiCliUninstallTests(unittest.TestCase):
    def test_uninstall_removes_only_managed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = _gemini_settings_path(temp)
            path.parent.mkdir(parents=True)
            existing = {
                "hooks": {"AfterAgent": [{"type": "command", "command": "echo user-hook"}]},
            }
            path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

            install_hooks(temp, "gemini-cli")
            result = install_hooks(temp, "gemini-cli", uninstall=True)

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])

            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("SessionStart", config.get("hooks", {}))
            self.assertNotIn("PreCompress", config.get("hooks", {}))
            commands = [h["command"] for h in config["hooks"]["AfterAgent"]]
            self.assertEqual(commands, ["echo user-hook"])

    def test_uninstall_with_nothing_to_remove_is_a_clean_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install_hooks(temp, "gemini-cli", uninstall=True)

            self.assertTrue(result["ok"])
            self.assertFalse(result["changed"])
            self.assertTrue(any("nothing to remove" in w for w in result["warnings"]))
            self.assertFalse(_gemini_settings_path(temp).exists())


class GeminiCliMalformedConfigTests(unittest.TestCase):
    def test_invalid_json_backs_up_and_aborts_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = _gemini_settings_path(temp)
            path.parent.mkdir(parents=True)
            path.write_text("{not valid json", encoding="utf-8")

            result = install_hooks(temp, "gemini-cli")

            self.assertFalse(result["ok"])
            self.assertTrue(result["backup_path"])
            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "{not valid json")
            self.assertTrue(any("invalid JSON" in w for w in result["warnings"]))


class CliWiringTests(unittest.TestCase):
    def test_install_with_hooks_writes_settings_and_reports_hooks_key(self) -> None:
        # Sandbox the MCP-config half of `install` exactly like test_installer.py
        # does: force the claude-code adapter down its `claude mcp add` subprocess
        # path but fake the subprocess, so this test exercises --with-hooks'
        # wiring without touching a real `claude` CLI / its real global config.
        from unittest import mock

        from memory_fabric.cli import main

        with tempfile.TemporaryDirectory() as temp:
            with (
                mock.patch("memory_fabric.installer.shutil.which", return_value="/usr/bin/claude"),
                mock.patch("memory_fabric.installer.subprocess.run") as mock_run,
            ):
                mock_run.return_value = mock.Mock(returncode=0, stderr="")
                exit_code = main(
                    ["--cwd", temp, "install", "--client", "claude-code", "--with-hooks"]
                )
            self.assertEqual(exit_code, 0)
            self.assertTrue(_settings_path(temp).exists())

    def test_session_start_hook_format_emits_claude_code_envelope(self) -> None:
        import contextlib
        import io

        from memory_fabric.cli import main
        from memory_fabric.storage import initialize_memory_fabric

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["--cwd", temp, "session-start", "--hook-format", "claude-code"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertIn(
                "read_combined_context_tool", payload["hookSpecificOutput"]["additionalContext"]
            )
            marker = Path(temp) / ".ai-memory" / "private" / "session_started_at"
            self.assertTrue(marker.exists())

    def test_session_start_hook_format_emits_gemini_cli_envelope(self) -> None:
        import contextlib
        import io

        from memory_fabric.cli import main
        from memory_fabric.storage import initialize_memory_fabric

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["--cwd", temp, "session-start", "--hook-format", "gemini-cli"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertIn(
                "read_combined_context_tool", payload["hookSpecificOutput"]["additionalContext"]
            )
            marker = Path(temp) / ".ai-memory" / "private" / "session_started_at"
            self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
