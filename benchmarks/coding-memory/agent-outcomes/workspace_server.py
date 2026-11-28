"""Identical scoped workspace tools for both trial arms."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from check import read_json
from mcp.server.fastmcp import FastMCP


def serve() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("engine_src", type=Path)
    parser.add_argument("memory_budget", type=int)
    parser.add_argument("--memory-root", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.engine_src))

    from memory_fabric.storage.retrieve import context_for_task

    initial = {path.name: path.read_bytes() for path in args.workspace.iterdir() if path.is_file()}
    server = FastMCP("Trial workspace")

    def log(tool: str, **details: Any) -> None:
        with args.audit.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"tool": tool, **details}) + "\n")

    @server.tool()
    def list_files() -> list[str]:
        """List the ordinary files in the current repository."""
        log("list_files")
        return sorted(initial)

    @server.tool()
    def read_file(path: str) -> str:
        """Read an ordinary file by its repository-relative name."""
        if path not in initial:
            raise ValueError("Unknown workspace file")
        log("read_file", path=path)
        return (args.workspace / path).read_text(encoding="utf-8")

    @server.tool()
    def write_config(path: str, value: dict[str, Any]) -> dict[str, bool]:
        """Replace an existing JSON configuration file with the supplied object."""
        if path not in initial or not path.endswith(".json"):
            raise ValueError("Unknown workspace configuration file")
        target = args.workspace / path
        data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
        changed = data != target.read_bytes()
        target.write_bytes(data)
        log("write_config", path=path, value=value, changed=changed)
        return {"changed": changed}

    @server.tool()
    def probe_cache(first: dict[str, str], second: dict[str, str]) -> dict[str, Any]:
        """Compute cache keys for two Spruce manifest records. Use warehouse, route and revision."""
        target = args.workspace / "spruce.json"
        record_fields = {"warehouse", "route", "revision"}
        if (
            "spruce.json" not in initial
            or set(first) != record_fields
            or set(second) != record_fields
        ):
            raise ValueError("Probe requires a Spruce checkout and two complete manifest records")
        dimensions = read_json(target)["key_dimensions"]
        first_key = [first[name] for name in dimensions]
        second_key = [second[name] for name in dimensions]
        result = {
            "first_key": first_key,
            "second_key": second_key,
            "collision": first_key == second_key,
        }
        log(
            "probe_cache",
            first=first,
            second=second,
            **result,
            differing_fields=sorted(name for name in record_fields if first[name] != second[name]),
            config_unchanged=target.read_bytes() == initial["spruce.json"],
        )
        return result

    @server.tool()
    def lookup_history(query: str, files_open: list[str] | None = None) -> dict[str, Any]:
        """Look up prior decisions, failures or verification leads for the current task."""
        if args.memory_root is None:
            result: dict[str, Any] = {
                "retrieval_status": "disabled",
                "included_sections": [],
                "text": "",
                "estimated_tokens": 0,
            }
        else:
            bundle = context_for_task(
                str(args.memory_root),
                query,
                files_open,
                max_tokens=args.memory_budget,
            )
            result = {
                key: bundle[key]
                for key in ("retrieval_status", "included_sections", "text", "estimated_tokens")
                if key in bundle
            }
        log(
            "lookup_history",
            query=query,
            files_open=files_open,
            **{key: value for key, value in result.items() if key != "text"},
        )
        return result

    server.run(transport="stdio")


if __name__ == "__main__":
    serve()
