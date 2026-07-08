from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.clients import (
    CLIENTS,
    _antigravity_path,
    _claude_code_path,
    _claude_desktop_path,
    _cline_path,
    _codex_path,
    _cursor_path,
    _gemini_cli_path,
    _os_app_config_dir,
    _vscode_path,
    _vscode_user_dir,
    _windsurf_path,
    build_entry,
    entry_note,
)
from memory_fabric.version import __version__


class ClientRegistryTests(unittest.TestCase):
    def test_all_nine_clients_registered(self) -> None:
        self.assertEqual(
            set(CLIENTS),
            {
                "claude-code",
                "claude-desktop",
                "vscode",
                "cursor",
                "windsurf",
                "codex",
                "antigravity",
                "gemini-cli",
                "cline",
            },
        )

    def test_build_entry_prefers_local_binary(self) -> None:
        """P-02: the server installed next to the running CLI wins over uvx."""
        fake = Path(tempfile.gettempdir()) / "memory-fabric-mcp.exe"
        with mock.patch("memory_fabric.clients.local_server_binary", return_value=fake):
            entry = build_entry(True)
        self.assertEqual(entry["command"], str(fake))
        self.assertEqual(entry["args"], [])
        self.assertIn("same version as this CLI", entry_note(entry) or "")

    def test_build_entry_uvx_is_version_pinned(self) -> None:
        """P-01: an unpinned uvx spec is served stale from the uv cache forever."""
        with mock.patch("memory_fabric.clients.local_server_binary", return_value=None):
            entry = build_entry(True)
        self.assertEqual(entry["command"], "uvx")
        self.assertEqual(
            entry["args"],
            ["--from", f"memory-fabric[mcp]=={__version__}", "memory-fabric-mcp"],
        )
        self.assertIn("re-run", entry_note(entry) or "")

    def test_build_entry_server_command_override_wins(self) -> None:
        entry = build_entry(True, server_command="C:/tools/memory-fabric-mcp.exe --flag")
        self.assertEqual(entry["command"], "C:/tools/memory-fabric-mcp.exe")
        self.assertEqual(entry["args"], ["--flag"])

    def test_build_entry_falls_back_when_uv_unavailable(self) -> None:
        with mock.patch("memory_fabric.clients.local_server_binary", return_value=None):
            entry = build_entry(False)
        self.assertEqual(entry["args"], [])


class ConfigPathResolutionTests(unittest.TestCase):
    def test_os_app_config_dir_is_platform_aware(self) -> None:
        windows = _os_app_config_dir(
            "Claude",
            platform_name="Windows",
            env={"APPDATA": r"C:\Users\R\AppData\Roaming"},
            home="C:/Users/R",
        )
        mac = _os_app_config_dir("Claude", platform_name="Darwin", env={}, home="/Users/r")
        linux = _os_app_config_dir(
            "Claude",
            platform_name="Linux",
            env={"XDG_CONFIG_HOME": "/home/r/.config"},
            home="/home/r",
        )
        self.assertEqual(windows, Path(r"C:\Users\R\AppData\Roaming") / "Claude")
        self.assertEqual(mac, Path("/Users/r/Library/Application Support/Claude"))
        self.assertEqual(linux, Path("/home/r/.config/Claude"))

    def test_claude_desktop_path_per_os(self) -> None:
        windows = _claude_desktop_path(
            project=False,
            cwd=Path("."),
            platform_name="Windows",
            env={"APPDATA": r"C:\Users\R\AppData\Roaming"},
            home="C:/Users/R",
        )
        mac = _claude_desktop_path(
            project=False, cwd=Path("."), platform_name="Darwin", env={}, home="/Users/r"
        )
        self.assertEqual(
            windows, Path(r"C:\Users\R\AppData\Roaming") / "Claude" / "claude_desktop_config.json"
        )
        self.assertEqual(
            mac, Path("/Users/r/Library/Application Support/Claude/claude_desktop_config.json")
        )

    def test_vscode_project_scope(self) -> None:
        path = _vscode_path(project=True, cwd=Path("/repo"))
        self.assertEqual(path, Path("/repo/.vscode/mcp.json"))

    def test_vscode_global_scope_uses_servers_file_under_user_dir(self) -> None:
        path = _vscode_path(
            project=False,
            cwd=Path("."),
            platform_name="Linux",
            env={"XDG_CONFIG_HOME": "/home/r/.config"},
            home="/home/r",
        )
        self.assertEqual(path, Path("/home/r/.config/Code/User/mcp.json"))

    def test_cline_path_shares_vscode_user_dir(self) -> None:
        vscode_user = _vscode_user_dir(platform_name="Darwin", env={}, home="/Users/r")
        cline = _cline_path(
            project=False, cwd=Path("."), platform_name="Darwin", env={}, home="/Users/r"
        )
        self.assertEqual(
            cline,
            vscode_user
            / "globalStorage"
            / "saoudrizwan.claude-dev"
            / "settings"
            / "cline_mcp_settings.json",
        )

    def test_cursor_project_vs_global(self) -> None:
        project = _cursor_path(project=True, cwd=Path("/repo"))
        glob = _cursor_path(project=False, cwd=Path("."), home="/home/r")
        self.assertEqual(project, Path("/repo/.cursor/mcp.json"))
        self.assertEqual(glob, Path("/home/r/.cursor/mcp.json"))

    def test_windsurf_path_has_no_os_branching(self) -> None:
        win = _windsurf_path(project=False, cwd=Path("."), platform_name="Windows", home="/home/r")
        mac = _windsurf_path(project=False, cwd=Path("."), platform_name="Darwin", home="/home/r")
        self.assertEqual(win, Path("/home/r/.codeium/windsurf/mcp_config.json"))
        self.assertEqual(mac, win)

    def test_codex_project_vs_global(self) -> None:
        project = _codex_path(project=True, cwd=Path("/repo"))
        glob = _codex_path(project=False, cwd=Path("."), home="/home/r")
        self.assertEqual(project, Path("/repo/.codex/config.toml"))
        self.assertEqual(glob, Path("/home/r/.codex/config.toml"))

    def test_antigravity_path(self) -> None:
        path = _antigravity_path(project=False, cwd=Path("."), home="/home/r")
        self.assertEqual(path, Path("/home/r/.gemini/config/mcp_config.json"))

    def test_gemini_cli_prefers_central_config_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / ".gemini" / "config").mkdir(parents=True)
            path = _gemini_cli_path(project=False, cwd=Path("."), home=temp)
            self.assertEqual(path, Path(temp) / ".gemini" / "config" / "mcp_config.json")

    def test_gemini_cli_falls_back_to_legacy_settings_when_only_that_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gemini_dir = Path(temp) / ".gemini"
            gemini_dir.mkdir(parents=True)
            (gemini_dir / "settings.json").write_text("{}", encoding="utf-8")
            path = _gemini_cli_path(project=False, cwd=Path("."), home=temp)
            self.assertEqual(path, gemini_dir / "settings.json")

    def test_claude_code_path_is_always_project_scoped_mcp_json(self) -> None:
        path = _claude_code_path(project=False, cwd=Path("/repo"))
        self.assertEqual(path, Path("/repo/.mcp.json"))


class DetectInstalledTests(unittest.TestCase):
    """Home-only clients (no OS/APPDATA branching, no subprocess) can be exercised
    purely through the home= DI kwarg — the OS-branching clients (vscode/claude-desktop/
    cline) and the shutil.which-based ones are covered end-to-end in test_installer.py's
    install_all() tests instead, where env={} isolation is exercised alongside home=."""

    def test_cursor_detected_only_once_dir_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(CLIENTS["cursor"].detect_installed(home=temp))
            (Path(temp) / ".cursor").mkdir()
            self.assertTrue(CLIENTS["cursor"].detect_installed(home=temp))

    def test_codex_detected_only_once_dir_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(CLIENTS["codex"].detect_installed(home=temp))
            (Path(temp) / ".codex").mkdir()
            self.assertTrue(CLIENTS["codex"].detect_installed(home=temp))

    def test_windsurf_detected_only_once_dir_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(CLIENTS["windsurf"].detect_installed(home=temp))
            (Path(temp) / ".codeium" / "windsurf").mkdir(parents=True)
            self.assertTrue(CLIENTS["windsurf"].detect_installed(home=temp))


if __name__ == "__main__":
    unittest.main()
