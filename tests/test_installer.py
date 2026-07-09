from __future__ import annotations

import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.clients import CLIENTS
from memory_fabric.installer import detect_installed_clients, install, install_all

# Clients whose config lives at a project-relative path we can pass via project=True,
# so no HOME/APPDATA sandboxing is needed to keep the test off the real machine.
JSON_PROJECT_CLIENTS = ["vscode", "cursor"]

# Clients with no project scope at all - every scenario for these must sandbox both
# home= and env={} (the latter blocks a real APPDATA/XDG_CONFIG_HOME from leaking in
# on the OS-branching ones: claude-desktop and cline).
JSON_GLOBAL_ONLY_CLIENTS = ["claude-desktop", "windsurf", "antigravity", "gemini-cli", "cline"]


def _install_project(temp: str, client: str, **kwargs):
    return install(temp, client, project=True, **kwargs)


def _install_global(temp: str, client: str, **kwargs):
    return install(temp, client, home=temp, env={}, **kwargs)


class JsonEngineProjectScopeTests(unittest.TestCase):
    def test_fresh_install_creates_config_with_our_entry(self) -> None:
        for name in JSON_PROJECT_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                result = _install_project(temp, name)
                self.assertTrue(result["ok"])
                self.assertTrue(result["changed"])
                path = Path(result["path"])
                self.assertTrue(path.exists())
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("memory-fabric", data[CLIENTS[name].root_key])

    def test_second_run_is_idempotent(self) -> None:
        for name in JSON_PROJECT_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                first = _install_project(temp, name)
                second = _install_project(temp, name)
                self.assertTrue(first["changed"])
                self.assertFalse(second["changed"])
                self.assertEqual(
                    Path(first["path"]).read_bytes(), Path(second["path"]).read_bytes()
                )

    def test_merge_preserves_preexisting_user_servers(self) -> None:
        for name in JSON_PROJECT_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                spec = CLIENTS[name]
                path = spec.config_path(project=True, cwd=Path(temp))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({spec.root_key: {"other-tool": {"command": "foo"}}}),
                    encoding="utf-8",
                )

                _install_project(temp, name)

                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data[spec.root_key]["other-tool"], {"command": "foo"})
                self.assertIn("memory-fabric", data[spec.root_key])

    def test_uninstall_removes_only_our_entry(self) -> None:
        for name in JSON_PROJECT_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                spec = CLIENTS[name]
                path = spec.config_path(project=True, cwd=Path(temp))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({spec.root_key: {"other-tool": {"command": "foo"}}}),
                    encoding="utf-8",
                )
                _install_project(temp, name)

                result = _install_project(temp, name, uninstall=True)

                self.assertTrue(result["changed"])
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("other-tool", data[spec.root_key])
                self.assertNotIn("memory-fabric", data[spec.root_key])

    def test_uninstall_when_absent_is_idempotent_not_an_error(self) -> None:
        for name in JSON_PROJECT_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                result = _install_project(temp, name, uninstall=True)
                self.assertTrue(result["ok"])
                self.assertFalse(result["changed"])
                self.assertTrue(result["warnings"])

    def test_malformed_json_aborts_and_creates_backup(self) -> None:
        for name in JSON_PROJECT_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                spec = CLIENTS[name]
                path = spec.config_path(project=True, cwd=Path(temp))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{not valid json", encoding="utf-8")

                result = _install_project(temp, name)

                self.assertFalse(result["ok"])
                self.assertEqual(path.read_text(encoding="utf-8"), "{not valid json")
                backups = list(path.parent.glob(path.name + ".bak-*"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(encoding="utf-8"), "{not valid json")

    def test_dry_run_writes_nothing_and_shows_diff(self) -> None:
        for name in JSON_PROJECT_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                result = _install_project(temp, name, dry_run=True)
                self.assertFalse(Path(result["path"]).exists())
                self.assertIn("memory-fabric", result["diff"])


class JsonEngineGlobalScopeTests(unittest.TestCase):
    """claude-desktop/windsurf/antigravity/gemini-cli/cline are global-only, so every
    scenario sandboxes HOME (and APPDATA/XDG_CONFIG_HOME via env={}) to a temp dir
    instead of touching the real machine's actual app configs."""

    def test_fresh_install_creates_config_with_our_entry(self) -> None:
        for name in JSON_GLOBAL_ONLY_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                result = _install_global(temp, name)
                self.assertTrue(result["ok"], result["warnings"])
                self.assertTrue(result["changed"])
                path = Path(result["path"])
                self.assertTrue(path.exists())
                self.assertTrue(str(path).startswith(temp))
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("memory-fabric", data[CLIENTS[name].root_key])

    def test_second_run_is_idempotent(self) -> None:
        for name in JSON_GLOBAL_ONLY_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                first = _install_global(temp, name)
                second = _install_global(temp, name)
                self.assertTrue(first["changed"])
                self.assertFalse(second["changed"])

    def test_merge_preserves_preexisting_user_servers(self) -> None:
        for name in JSON_GLOBAL_ONLY_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                spec = CLIENTS[name]
                path = spec.config_path(project=False, cwd=Path(temp), home=temp, env={})
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({spec.root_key: {"other-tool": {"command": "foo"}}}),
                    encoding="utf-8",
                )

                _install_global(temp, name)

                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data[spec.root_key]["other-tool"], {"command": "foo"})
                self.assertIn("memory-fabric", data[spec.root_key])

    def test_uninstall_removes_only_our_entry(self) -> None:
        for name in JSON_GLOBAL_ONLY_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                installed = _install_global(temp, name)
                result = _install_global(temp, name, uninstall=True)
                self.assertTrue(result["changed"])
                data = json.loads(Path(installed["path"]).read_text(encoding="utf-8"))
                self.assertNotIn("memory-fabric", data.get(CLIENTS[name].root_key, {}))

    def test_malformed_json_aborts_and_creates_backup(self) -> None:
        for name in JSON_GLOBAL_ONLY_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                spec = CLIENTS[name]
                path = spec.config_path(project=False, cwd=Path(temp), home=temp, env={})
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{not valid json", encoding="utf-8")

                result = _install_global(temp, name)

                self.assertFalse(result["ok"])
                self.assertEqual(path.read_text(encoding="utf-8"), "{not valid json")
                backups = list(path.parent.glob(path.name + ".bak-*"))
                self.assertEqual(len(backups), 1)

    def test_dry_run_writes_nothing(self) -> None:
        for name in JSON_GLOBAL_ONLY_CLIENTS:
            with self.subTest(client=name), tempfile.TemporaryDirectory() as temp:
                result = _install_global(temp, name, dry_run=True)
                self.assertFalse(Path(result["path"]).exists())
                self.assertIn("memory-fabric", result["diff"])


class VsCodeSpecificTests(unittest.TestCase):
    def test_entry_includes_type_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install(temp, "vscode", project=True)
            data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertEqual(data["servers"]["memory-fabric"]["type"], "stdio")

    def test_project_flag_ignored_for_windsurf_falls_back_to_global_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install(temp, "windsurf", project=True, home=temp, env={}, dry_run=True)
            self.assertEqual(result["scope"], "global")
            self.assertTrue(any("no project scope" in w for w in result["warnings"]))


class TomlEngineTests(unittest.TestCase):
    def test_append_preserves_existing_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".codex" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text("dependencies = []\n", encoding="utf-8")

            result = install(temp, "codex", project=True)

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])
            text = path.read_text(encoding="utf-8")
            self.assertIn("dependencies = []", text)
            parsed = tomllib.loads(text)
            self.assertEqual(parsed["dependencies"], [])
            self.assertIn("memory-fabric", parsed["mcp_servers"])

    def test_append_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = install(temp, "codex", project=True)
            second = install(temp, "codex", project=True)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])

    def test_uninstall_removes_block_and_remainder_still_parses(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".codex" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text("dependencies = []\n", encoding="utf-8")
            install(temp, "codex", project=True)

            result = install(temp, "codex", project=True, uninstall=True)

            self.assertTrue(result["changed"])
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("mcp_servers", text)
            parsed = tomllib.loads(text)
            self.assertNotIn("mcp_servers", parsed)
            self.assertEqual(parsed["dependencies"], [])

    def test_uninstall_when_absent_is_idempotent_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install(temp, "codex", project=True, uninstall=True)
            self.assertTrue(result["ok"])
            self.assertFalse(result["changed"])
            self.assertTrue(result["warnings"])

    def test_malformed_toml_aborts_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".codex" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text("this is not [valid toml", encoding="utf-8")

            result = install(temp, "codex", project=True)

            self.assertFalse(result["ok"])
            self.assertEqual(path.read_text(encoding="utf-8"), "this is not [valid toml")
            backups = list(path.parent.glob("config.toml.bak-*"))
            self.assertEqual(len(backups), 1)

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = install(temp, "codex", project=True, dry_run=True)
            self.assertFalse((Path(temp) / ".codex" / "config.toml").exists())
            self.assertIn("mcp_servers.memory-fabric", result["diff"])


class ClaudeCodeCliTests(unittest.TestCase):
    def test_claude_on_path_invokes_expected_argv(self) -> None:
        from memory_fabric.version import __version__

        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch("memory_fabric.installer.shutil.which", return_value="/usr/bin/claude"),
            mock.patch("memory_fabric.clients.local_server_binary", return_value=None),
            mock.patch("memory_fabric.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

            result = install(temp, "claude-code")

            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(
                args[0],
                [
                    "claude",
                    "mcp",
                    "add",
                    "memory-fabric",
                    "--",
                    "uvx",
                    "--from",
                    f"memory-fabric[mcp]=={__version__}",
                    "memory-fabric-mcp",
                ],
            )
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["timeout"], 15.0)
            self.assertFalse(kwargs["check"])

    def test_install_json_prefers_local_binary_and_notes_choice(self) -> None:
        """P-02: install from a venv writes that venv's server, not uvx."""
        import json as _json

        fake = Path(tempfile.gettempdir()) / "memory-fabric-mcp.exe"
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch("memory_fabric.clients.local_server_binary", return_value=fake),
        ):
            result = install(temp, "cursor", project=True)
            self.assertTrue(result["ok"])
            config = _json.loads((Path(temp) / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            entry = config["mcpServers"]["memory-fabric"]
            self.assertEqual(entry["command"], str(fake))
            self.assertTrue(any("local binary" in w for w in result["warnings"]))

    def test_install_server_command_flag_is_respected(self) -> None:
        import json as _json

        with tempfile.TemporaryDirectory() as temp:
            result = install(
                temp, "cursor", project=True, server_command="C:/custom/server.exe --debug"
            )
            self.assertTrue(result["ok"])
            config = _json.loads((Path(temp) / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            entry = config["mcpServers"]["memory-fabric"]
            self.assertEqual(entry["command"], "C:/custom/server.exe")
            self.assertEqual(entry["args"], ["--debug"])

    def test_nonzero_return_code_is_not_ok_but_does_not_raise(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch("memory_fabric.installer.shutil.which", return_value="/usr/bin/claude"),
            mock.patch("memory_fabric.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")

            result = install(temp, "claude-code")

            self.assertFalse(result["ok"])
            self.assertIn("boom", result["warnings"])

    def test_dry_run_does_not_invoke_subprocess(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch("memory_fabric.installer.shutil.which", return_value="/usr/bin/claude"),
            mock.patch("memory_fabric.installer.subprocess.run") as mock_run,
        ):
            result = install(temp, "claude-code", dry_run=True)

            mock_run.assert_not_called()
            self.assertIn("claude mcp add", result["command"])

    def test_claude_not_on_path_falls_back_to_project_mcp_json(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch("memory_fabric.installer.shutil.which", return_value=None),
        ):
            result = install(temp, "claude-code")

            self.assertEqual(result["method"], "json-merge")
            path = Path(result["path"])
            self.assertEqual(path, Path(temp).resolve() / ".mcp.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("memory-fabric", data["mcpServers"])

    def test_uninstall_invokes_claude_mcp_remove(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch("memory_fabric.installer.shutil.which", return_value="/usr/bin/claude"),
            mock.patch("memory_fabric.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

            install(temp, "claude-code", uninstall=True)

            args, _ = mock_run.call_args
            self.assertEqual(args[0], ["claude", "mcp", "remove", "memory-fabric"])


class InstallAllDetectionTests(unittest.TestCase):
    def test_only_detected_clients_are_attempted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fake_home = Path(temp) / "home"
            (fake_home / ".cursor").mkdir(parents=True)
            (fake_home / ".codex").mkdir(parents=True)

            with mock.patch("memory_fabric.clients.shutil.which", return_value=None):
                result = install_all(temp, home=str(fake_home), env={}, dry_run=True)

            attempted = {r["client"] for r in result["results"]}
            self.assertEqual(attempted, {"cursor", "codex"})

    def test_no_clients_detected_adds_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fake_home = Path(temp) / "empty_home"
            fake_home.mkdir()

            with mock.patch("memory_fabric.clients.shutil.which", return_value=None):
                result = install_all(temp, home=str(fake_home), env={})

            self.assertEqual(result["results"], [])
            self.assertTrue(result["warnings"])

    def test_detect_installed_clients_matches_install_all(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fake_home = Path(temp) / "home"
            (fake_home / ".codeium" / "windsurf").mkdir(parents=True)

            with mock.patch("memory_fabric.clients.shutil.which", return_value=None):
                names = detect_installed_clients(home=str(fake_home), env={})

            self.assertEqual(names, ["windsurf"])


if __name__ == "__main__":
    unittest.main()
