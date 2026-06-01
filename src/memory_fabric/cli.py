"""Command line interface for Memory Fabric."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from memory_fabric import __version__
from memory_fabric.storage import (
    doctor,
    dream,
    initialize_memory_fabric,
    keyword_search,
    propose_memory_patch,
    rollback,
    status,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cwd = str(Path(args.cwd).expanduser().resolve())

    try:
        if args.command == "init":
            result = initialize_memory_fabric(cwd)
            _print_result(result, args.json)
            return 0
        if args.command == "status":
            _print_result(status(cwd), args.json)
            return 0
        if args.command == "doctor":
            result = doctor(cwd)
            _print_result(result, args.json)
            return 0 if result["ok"] else 1
        if args.command == "dream":
            result = dream(cwd, mode=args.mode)
            _print_result(result, args.json)
            return 0
        if args.command == "query":
            result = keyword_search(cwd, args.query, max_results=args.max_results)
            _print_result(result, args.json)
            return 0
        if args.command == "sync-global":
            preview = propose_memory_patch(
                cwd,
                "Review local memory for durable rules before manually promoting them to global memory.",
            )
            _print_result(
                {
                    "message": "Global sync is preview-only in v1. Review local memory before editing global files.",
                    "preview": preview,
                },
                args.json,
            )
            return 0
        if args.command == "rollback":
            result = rollback(cwd, args.to)
            _print_result(result, args.json)
            return 0
    except Exception as exc:  # noqa: BLE001 - CLI should surface all operational failures.
        print(f"ai-memory: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-memory", description="Memory Fabric CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--cwd", default=".", help="Project working directory")
    parser.add_argument("--json", action="store_true", help="Print JSON output")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Create .ai-memory scaffolding")
    subparsers.add_parser("status", help="Show memory status")
    subparsers.add_parser("doctor", help="Validate memory files and environment")

    dream_parser = subparsers.add_parser("dream", help="Run local memory maintenance")
    dream_parser.add_argument("--mode", choices=["light", "deep"], default="light")

    query_parser = subparsers.add_parser("query", help="Search memory")
    query_parser.add_argument("query")
    query_parser.add_argument("--max-results", type=int, default=10)

    subparsers.add_parser("sync-global", help="Preview local-to-global promotion")

    rollback_parser = subparsers.add_parser("rollback", help="Restore local memory from a snapshot")
    rollback_parser.add_argument("--to", required=True, help="Snapshot name")

    return parser


def _print_result(result: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if isinstance(result, list):
        for item in result:
            print(_format_item(item))
        return

    if isinstance(result, dict):
        for key, value in result.items():
            print(f"{key}: {_format_value(value)}")
        return

    print(result)


def _format_item(item: Any) -> str:
    if isinstance(item, dict):
        if {"path", "line", "snippet"}.issubset(item):
            return f"{item['path']}:{item['line']}: {item['snippet']}"
        return json.dumps(item, ensure_ascii=False)
    return str(item)


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "[]"
        return "\n  - " + "\n  - ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
