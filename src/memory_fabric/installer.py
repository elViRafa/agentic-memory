"""Safe-write engine that wires memory-fabric into AI tool MCP client configs.

CLI-only by design (see clients.py's docstring context) — this deliberately writes
outside any single project's sandbox (global app config, or a subprocess call to
another CLI), so it is never exposed as an MCP tool.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Literal, Mapping

from memory_fabric.clients import CLIENTS, ClientSpec, build_entry, entry_note, uv_available
from memory_fabric.contracts import InstallAllResult, InstallResult
from memory_fabric.locking import locked_file
from memory_fabric.templates import now_iso

SERVER_NAME = "memory-fabric"

_TOML_START = "# >>> memory-fabric install (managed block; safe to delete this whole block) >>>"
_TOML_END = "# <<< memory-fabric install <<<"
_TOML_BLOCK_PATTERN = re.compile(
    re.escape(_TOML_START) + r".*?" + re.escape(_TOML_END) + r"\n?", re.DOTALL
)


class ConfigParseError(ValueError):
    """Raised when an existing client config file can't be parsed."""


def install(
    cwd: str,
    client: str,
    *,
    project: bool = False,
    dry_run: bool = False,
    uninstall: bool = False,
    server_command: str | None = None,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> InstallResult:
    if client not in CLIENTS:
        raise ValueError(f"Unknown client: {client!r}. Known clients: {', '.join(CLIENTS)}")
    spec = CLIENTS[client]
    cwd_path = Path(cwd).expanduser().resolve()
    warnings: list[str] = []

    use_project = project
    if project and not spec.supports_project:
        warnings.append(f"{client} has no project scope; using global config instead.")
        use_project = False

    if spec.fmt == "cli":
        return _install_cli(
            spec,
            cwd_path,
            project=use_project,
            dry_run=dry_run,
            uninstall=uninstall,
            server_command=server_command,
            warnings=warnings,
            platform_name=platform_name,
            env=env,
            home=home,
        )

    path = spec.config_path(
        project=use_project, cwd=cwd_path, platform_name=platform_name, env=env, home=home
    )
    scope: Literal["global", "project"] = "project" if use_project else "global"

    if spec.fmt == "toml":
        return _install_toml(
            spec,
            path,
            scope,
            dry_run=dry_run,
            uninstall=uninstall,
            server_command=server_command,
            warnings=warnings,
        )
    return _install_json(
        spec,
        path,
        scope,
        dry_run=dry_run,
        uninstall=uninstall,
        server_command=server_command,
        warnings=warnings,
    )


def install_all(
    cwd: str,
    *,
    project: bool = False,
    dry_run: bool = False,
    uninstall: bool = False,
    server_command: str | None = None,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> InstallAllResult:
    detected = detect_installed_clients(platform_name=platform_name, env=env, home=home)
    warnings: list[str] = []
    if not detected:
        warnings.append("No supported clients detected on this machine.")

    results = [
        install(
            cwd,
            name,
            project=project,
            dry_run=dry_run,
            uninstall=uninstall,
            server_command=server_command,
            platform_name=platform_name,
            env=env,
            home=home,
        )
        for name in detected
    ]
    return {"results": results, "warnings": warnings}


def detect_installed_clients(
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> list[str]:
    return [
        name
        for name, spec in CLIENTS.items()
        if spec.detect_installed(platform_name=platform_name, env=env, home=home)
    ]


# --- JSON engine ------------------------------------------------------------------
# A *targeted* single-key merge, not a generic deep-merge: we only ever touch
# config[root_key][SERVER_NAME], so nothing else needs preserving by clever merge
# logic — it's simply never touched. json.loads/dumps round-tripping keeps every
# other key (and their original insertion order) byte-for-identical.


def _install_json(
    spec: ClientSpec,
    path: Path,
    scope: Literal["global", "project"],
    *,
    dry_run: bool,
    uninstall: bool,
    warnings: list[str],
    server_command: str | None = None,
) -> InstallResult:
    try:
        config, old_text = _read_json_config(path)
    except ConfigParseError as exc:
        backup_path = "" if dry_run else _backup_file(path)
        warnings.append(str(exc))
        return {
            "client": spec.name,
            "scope": scope,
            "method": "json-merge",
            "ok": False,
            "changed": False,
            "path": str(path),
            "diff": "",
            "backup_path": backup_path,
            "command": "",
            "warnings": warnings,
        }

    if uninstall:
        new_config, removed = _remove_entry(config, spec.root_key)
        if removed:
            new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
            changed = True
        else:
            # Nothing to remove - treat as a strict no-op rather than re-serializing
            # (a nonexistent file has old_text == "", which would never equal any
            # valid JSON serialization, even of an unchanged empty config).
            warnings.append(f"No memory-fabric entry found in {path}; nothing to remove.")
            new_text = old_text
            changed = False
    else:
        entry = build_entry(uv_available(), server_command)
        note = entry_note(entry)
        if note:
            warnings.append(note)
        new_config = _merge_entry(config, spec.root_key, entry, spec.extra_entry_keys)
        new_text = json.dumps(new_config, indent=2, ensure_ascii=False) + "\n"
        changed = new_text != old_text

    diff = _unified_diff(old_text, new_text, str(path)) if dry_run else ""
    if not dry_run and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(path):
            path.write_text(new_text, encoding="utf-8")

    return {
        "client": spec.name,
        "scope": scope,
        "method": "json-merge",
        "ok": True,
        "changed": changed,
        "path": str(path),
        "diff": diff,
        "backup_path": "",
        "command": "",
        "warnings": warnings,
    }


def _read_json_config(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text), text
    except json.JSONDecodeError as exc:
        raise ConfigParseError(
            f"{path} contains invalid JSON ({exc}); backed up original and aborted."
        ) from exc


def _merge_entry(config: dict, root_key: str, entry: dict, extra_keys: dict | None) -> dict:
    new_config = dict(config)
    root = dict(new_config.get(root_key, {}))
    root[SERVER_NAME] = {**entry, **(extra_keys or {})}
    new_config[root_key] = root
    return new_config


def _remove_entry(config: dict, root_key: str) -> tuple[dict, bool]:
    if root_key not in config or SERVER_NAME not in config[root_key]:
        return config, False
    new_config = dict(config)
    root = dict(new_config[root_key])
    del root[SERVER_NAME]
    new_config[root_key] = root
    return new_config, True


# --- TOML engine (Codex only) ------------------------------------------------------
# Reading uses stdlib tomllib; writing is append/marker-slice-only (no TOML-writer
# dependency, per the zero-required-deps decision).


def _install_toml(
    spec: ClientSpec,
    path: Path,
    scope: Literal["global", "project"],
    *,
    dry_run: bool,
    uninstall: bool,
    warnings: list[str],
    server_command: str | None = None,
) -> InstallResult:
    old_text = path.read_text(encoding="utf-8") if path.exists() else ""
    if old_text:
        try:
            tomllib.loads(old_text)
        except tomllib.TOMLDecodeError as exc:
            backup_path = "" if dry_run else _backup_file(path)
            warnings.append(
                f"{path} contains invalid TOML ({exc}); backed up original and aborted."
            )
            return _toml_result(
                spec, scope, path, ok=False, backup_path=backup_path, warnings=warnings
            )

    if uninstall:
        new_text, changed = _remove_toml_block(old_text)
        if not changed:
            warnings.append(f"No memory-fabric block found in {path}; nothing to remove.")
    else:
        entry = build_entry(uv_available(), server_command)
        new_text, changed = _append_toml_block(old_text, entry)
        if changed:
            note = entry_note(entry)
            if note:
                warnings.append(note)
        else:
            warnings.append(f"memory-fabric already present in {path}; nothing to do.")

    if new_text:
        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            warnings.append(f"Refusing to write {path}: result would not be valid TOML ({exc}).")
            return _toml_result(spec, scope, path, ok=False, warnings=warnings)

    diff = _unified_diff(old_text, new_text, str(path)) if dry_run else ""
    if not dry_run and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(path):
            path.write_text(new_text, encoding="utf-8")

    return _toml_result(spec, scope, path, ok=True, changed=changed, diff=diff, warnings=warnings)


def _toml_result(
    spec: ClientSpec,
    scope: Literal["global", "project"],
    path: Path,
    *,
    ok: bool,
    changed: bool = False,
    diff: str = "",
    backup_path: str = "",
    warnings: list[str],
) -> InstallResult:
    return {
        "client": spec.name,
        "scope": scope,
        "method": "toml-append",
        "ok": ok,
        "changed": changed,
        "path": str(path),
        "diff": diff,
        "backup_path": backup_path,
        "command": "",
        "warnings": warnings,
    }


def _append_toml_block(old_text: str, entry: dict) -> tuple[str, bool]:
    if _TOML_START in old_text:
        return old_text, False

    args_toml = ", ".join(_toml_string(arg) for arg in entry["args"])
    lines = [
        _TOML_START,
        "[mcp_servers.memory-fabric]",
        f"command = {_toml_string(entry['command'])}",
        f"args = [{args_toml}]",
        _TOML_END,
    ]
    block = "\n".join(lines)

    if not old_text:
        new_text = block + "\n"
    else:
        new_text = old_text.rstrip("\n") + "\n\n" + block + "\n"
    return new_text, True


def _remove_toml_block(old_text: str) -> tuple[str, bool]:
    new_text, count = _TOML_BLOCK_PATTERN.subn("", old_text)
    return new_text, count > 0


def _toml_string(value: str) -> str:
    # JSON's string-escaping is a compatible subset of TOML's basic-string rules
    # (both use "..." with backslash escapes) — safe here since our values are
    # simple command/path strings, never multi-line.
    return json.dumps(value)


# --- claude-code: prefer the `claude` CLI, fall back to project .mcp.json ----------


def _install_cli(
    spec: ClientSpec,
    cwd: Path,
    *,
    project: bool,
    dry_run: bool,
    uninstall: bool,
    warnings: list[str],
    platform_name: str | None,
    env: Mapping[str, str] | None,
    home: Path | str | None,
    server_command: str | None = None,
) -> InstallResult:
    claude_bin = shutil.which("claude")
    scope: Literal["global", "project"] = "project" if project else "global"

    if claude_bin is None:
        fallback_path = spec.config_path(
            project=True, cwd=cwd, platform_name=platform_name, env=env, home=home
        )
        result = _install_json(
            spec,
            fallback_path,
            "project",
            dry_run=dry_run,
            uninstall=uninstall,
            server_command=server_command,
            warnings=warnings,
        )
        result["warnings"] = [
            "`claude` CLI not found on PATH; wrote project .mcp.json directly instead.",
            *result["warnings"],
        ]
        return result

    if uninstall:
        argv = ["claude", "mcp", "remove", SERVER_NAME]
    else:
        entry = build_entry(uv_available(), server_command)
        note = entry_note(entry)
        if note:
            warnings.append(note)
        argv = ["claude", "mcp", "add", SERVER_NAME, "--", entry["command"], *entry["args"]]
    command_str = " ".join(argv)

    if dry_run:
        return {
            "client": spec.name,
            "scope": scope,
            "method": "cli",
            "ok": True,
            "changed": False,
            "path": "",
            "diff": "",
            "backup_path": "",
            "command": f"Would run: {command_str}",
            "warnings": warnings,
        }

    proc = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15.0,
        check=False,
    )
    ok = proc.returncode == 0
    if not ok and proc.stderr.strip():
        warnings.append(proc.stderr.strip())

    return {
        "client": spec.name,
        "scope": scope,
        "method": "cli",
        "ok": ok,
        "changed": ok,
        "path": "",
        "diff": "",
        "backup_path": "",
        "command": command_str,
        "warnings": warnings,
    }


# --- shared -------------------------------------------------------------------------


def _unified_diff(old_text: str, new_text: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=label,
            tofile=label,
        )
    )


def _backup_file(path: Path) -> str:
    ts = now_iso().replace(":", "").replace("+", "_").replace("-", "")
    backup_path = path.with_name(path.name + f".bak-{ts}")
    backup_path.write_bytes(path.read_bytes())
    return str(backup_path)
