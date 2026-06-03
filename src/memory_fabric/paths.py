"""Path resolution helpers for local and global memory roots."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Mapping


APP_DIR_NAME = "memory-fabric"
LOCAL_MEMORY_DIR = ".ai-memory"


def get_global_root(
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    """Resolve the OS-aware Memory Fabric application directory.

    MEMORY_FABRIC_HOME is supported as a deliberate override for tests,
    portable installs, and advanced users.
    """

    environment = env if env is not None else os.environ
    override = environment.get("MEMORY_FABRIC_HOME")
    if override:
        return Path(override).expanduser().resolve()

    system = (platform_name or platform.system()).lower()
    user_home = Path(home).expanduser() if home is not None else Path.home()

    if system.startswith("win"):
        appdata = environment.get("APPDATA")
        base = Path(appdata) if appdata else user_home / "AppData" / "Roaming"
        return (base / APP_DIR_NAME).resolve()

    if system == "darwin" or system.startswith("mac"):
        return (user_home / "Library" / "Application Support" / APP_DIR_NAME).resolve()

    xdg_config = environment.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else user_home / ".config"
    return (base / APP_DIR_NAME).resolve()


def project_root(cwd: str | Path) -> Path:
    """Resolve a project root from an explicit client-provided cwd."""

    return Path(cwd).expanduser().resolve()


def local_memory_dir(cwd: str | Path) -> Path:
    return project_root(cwd) / LOCAL_MEMORY_DIR


MEMORY_STORE_DIR = "memory-store"


def memory_store_dir(cwd: str | Path) -> Path:
    return local_memory_dir(cwd) / MEMORY_STORE_DIR



def global_memory_dir(
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    return get_global_root(platform_name=platform_name, env=env, home=home) / "global"
