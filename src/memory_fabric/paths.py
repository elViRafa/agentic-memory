"""Path resolution helpers for local and global memory roots."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path

APP_DIR_NAME = "memory-fabric"
LOCAL_MEMORY_DIR = ".ai-memory"

# Directories that should never be used as a project root — writing memory
# files here could corrupt the OS or expose sensitive files.
_DANGEROUS_ROOTS: frozenset[str] = frozenset(
    {
        "/",
        "/etc",
        "/bin",
        "/sbin",
        "/usr",
        "/var",
        "/sys",
        "/proc",
        "/boot",
        "/root",
        "/lib",
        "/lib64",
        "/dev",
        "/run",
        "C:\\",
        "C:\\Windows",
        "C:\\Windows\\System32",
    }
)


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


def validate_cwd(cwd: str | Path) -> Path:
    """Resolve and validate an agent-supplied working directory.

    Raises ``ValueError`` if the path:
    - Is empty or None
    - Is not an existing directory
    - Resolves to a known dangerous system root

    This prevents prompt-injection-style path traversal where a malicious or
    misconfigured agent passes ``cwd = "../../etc"`` to read or write files
    outside of an intended project directory.
    """
    if not cwd:
        raise ValueError("cwd must not be empty")

    resolved = Path(cwd).expanduser().resolve()

    # Reject known dangerous system paths
    resolved_str = str(resolved)
    for dangerous in _DANGEROUS_ROOTS:
        if resolved_str == dangerous or resolved_str == dangerous.rstrip("/\\"):
            raise ValueError(
                f"cwd resolves to a dangerous system path and cannot be used "
                f"as a Memory Fabric project root: {resolved}"
            )

    if not resolved.exists():
        raise ValueError(f"cwd does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"cwd is not a directory: {resolved}")

    return resolved


def project_root(cwd: str | Path) -> Path:
    """Resolve a project root from an explicit client-provided cwd.

    For security-sensitive contexts (MCP tool calls from agents), prefer
    ``validate_cwd()`` which enforces additional safety checks.
    """
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
