"""Declarative registry of supported AI coding tool MCP client configs."""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping


PACKAGE_SPEC = "memory-fabric[mcp]"
ENTRY_POINT = "memory-fabric-mcp"


@dataclass(frozen=True)
class ClientSpec:
    name: str
    fmt: Literal["json", "toml", "cli"]
    supports_project: bool
    supports_global: bool
    root_key: str
    extra_entry_keys: dict[str, Any] | None
    config_path: Callable[..., Path]
    detect_installed: Callable[..., bool]


def uv_available() -> bool:
    return shutil.which("uv") is not None


def build_entry(use_uvx: bool) -> dict[str, Any]:
    """Canonical server entry: uvx by default, resolved-executable fallback otherwise."""
    if use_uvx:
        return {"command": "uvx", "args": ["--from", PACKAGE_SPEC, ENTRY_POINT]}
    resolved = shutil.which(ENTRY_POINT)
    return {"command": resolved or ENTRY_POINT, "args": []}


def _resolve_home(home: Path | str | None) -> Path:
    return Path(home).expanduser() if home is not None else Path.home()


def _os_app_config_dir(
    app_name: str,
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    """Per-OS app-support directory, parametrized on app name.

    Same branching as paths.get_global_root, minus the MEMORY_FABRIC_HOME override
    (that override is specific to this package's own config, not other apps').
    """
    environment = env if env is not None else os.environ
    system = (platform_name or platform.system()).lower()
    user_home = _resolve_home(home)

    if system.startswith("win"):
        appdata = environment.get("APPDATA")
        base = Path(appdata) if appdata else user_home / "AppData" / "Roaming"
        return base / app_name

    if system == "darwin" or system.startswith("mac"):
        return user_home / "Library" / "Application Support" / app_name

    xdg_config = environment.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else user_home / ".config"
    return base / app_name


def _vscode_user_dir(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    """The '.../Code/User' directory shared by VS Code's global mcp.json and Cline."""
    return _os_app_config_dir("Code", platform_name=platform_name, env=env, home=home) / "User"


# --- per-client config path resolvers -------------------------------------------------
# All share one keyword-only signature so installer.py never has to branch on which
# kwargs a given client actually needs.


def _claude_code_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    # Only used as the JSON fallback when `claude` isn't on PATH; always project-scoped.
    return cwd / ".mcp.json"


def _claude_desktop_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    return (
        _os_app_config_dir("Claude", platform_name=platform_name, env=env, home=home)
        / "claude_desktop_config.json"
    )


def _vscode_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    if project:
        return cwd / ".vscode" / "mcp.json"
    return _vscode_user_dir(platform_name=platform_name, env=env, home=home) / "mcp.json"


def _cursor_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    if project:
        return cwd / ".cursor" / "mcp.json"
    return _resolve_home(home) / ".cursor" / "mcp.json"


def _windsurf_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    return _resolve_home(home) / ".codeium" / "windsurf" / "mcp_config.json"


def _codex_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    if project:
        return cwd / ".codex" / "config.toml"
    return _resolve_home(home) / ".codex" / "config.toml"


def _antigravity_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    return _resolve_home(home) / ".gemini" / "config" / "mcp_config.json"


def _gemini_cli_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    home_dir = _resolve_home(home)
    primary = home_dir / ".gemini" / "config" / "mcp_config.json"
    legacy = home_dir / ".gemini" / "settings.json"
    if not primary.parent.exists() and legacy.exists():
        return legacy
    return primary


def _cline_path(
    *,
    project: bool,
    cwd: Path,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    return (
        _vscode_user_dir(platform_name=platform_name, env=env, home=home)
        / "globalStorage"
        / "saoudrizwan.claude-dev"
        / "settings"
        / "cline_mcp_settings.json"
    )


# --- --client all detection -----------------------------------------------------------
# Each accepts the same optional platform_name/env/home DI kwargs as the config_path
# resolvers above, so install_all() can be fully sandboxed in tests (no real HOME/APPDATA
# mutation) instead of only sandboxing the write step after detection already looked at
# the real machine.


def _detect_claude_code(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    return shutil.which("claude") is not None


def _detect_claude_desktop(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    return _claude_desktop_path(
        project=False, cwd=Path("."), platform_name=platform_name, env=env, home=home
    ).parent.exists()


def _detect_vscode(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    return (
        shutil.which("code") is not None
        or _vscode_user_dir(platform_name=platform_name, env=env, home=home).exists()
    )


def _detect_cursor(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    return (_resolve_home(home) / ".cursor").exists()


def _detect_windsurf(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    return (_resolve_home(home) / ".codeium" / "windsurf").exists()


def _detect_codex(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    return (_resolve_home(home) / ".codex").exists()


def _detect_antigravity(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    return (_resolve_home(home) / ".gemini" / "config").exists()


def _detect_gemini_cli(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    # Broader than antigravity's check on purpose: also catches the legacy-only case
    # where only ~/.gemini/settings.json exists and ~/.gemini/config was never created.
    return (_resolve_home(home) / ".gemini").exists()


def _detect_cline(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> bool:
    # The extension's own globalStorage subdir is created lazily on first activation,
    # so check the shared globalStorage parent instead of the saoudrizwan.claude-dev
    # subdir — otherwise a real Cline install that hasn't run once yet would false-negative.
    return (
        _vscode_user_dir(platform_name=platform_name, env=env, home=home) / "globalStorage"
    ).exists()


CLIENTS: dict[str, ClientSpec] = {
    "claude-code": ClientSpec(
        name="claude-code",
        fmt="cli",
        supports_project=True,
        supports_global=False,
        root_key="mcpServers",
        extra_entry_keys=None,
        config_path=_claude_code_path,
        detect_installed=_detect_claude_code,
    ),
    "claude-desktop": ClientSpec(
        name="claude-desktop",
        fmt="json",
        supports_project=False,
        supports_global=True,
        root_key="mcpServers",
        extra_entry_keys=None,
        config_path=_claude_desktop_path,
        detect_installed=_detect_claude_desktop,
    ),
    "vscode": ClientSpec(
        name="vscode",
        fmt="json",
        supports_project=True,
        supports_global=True,
        root_key="servers",
        extra_entry_keys={"type": "stdio"},
        config_path=_vscode_path,
        detect_installed=_detect_vscode,
    ),
    "cursor": ClientSpec(
        name="cursor",
        fmt="json",
        supports_project=True,
        supports_global=True,
        root_key="mcpServers",
        extra_entry_keys=None,
        config_path=_cursor_path,
        detect_installed=_detect_cursor,
    ),
    "windsurf": ClientSpec(
        name="windsurf",
        fmt="json",
        supports_project=False,
        supports_global=True,
        root_key="mcpServers",
        extra_entry_keys=None,
        config_path=_windsurf_path,
        detect_installed=_detect_windsurf,
    ),
    "codex": ClientSpec(
        name="codex",
        fmt="toml",
        supports_project=True,
        supports_global=True,
        root_key="mcp_servers",
        extra_entry_keys=None,
        config_path=_codex_path,
        detect_installed=_detect_codex,
    ),
    "antigravity": ClientSpec(
        name="antigravity",
        fmt="json",
        supports_project=False,
        supports_global=True,
        root_key="mcpServers",
        extra_entry_keys=None,
        config_path=_antigravity_path,
        detect_installed=_detect_antigravity,
    ),
    "gemini-cli": ClientSpec(
        name="gemini-cli",
        fmt="json",
        supports_project=False,
        supports_global=True,
        root_key="mcpServers",
        extra_entry_keys=None,
        config_path=_gemini_cli_path,
        detect_installed=_detect_gemini_cli,
    ),
    "cline": ClientSpec(
        name="cline",
        fmt="json",
        supports_project=False,
        supports_global=True,
        root_key="mcpServers",
        extra_entry_keys=None,
        config_path=_cline_path,
        detect_installed=_detect_cline,
    ),
}
