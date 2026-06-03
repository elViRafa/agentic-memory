"""Command line interface for Memory Fabric."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from memory_fabric.version import __version__
from memory_fabric.eval import evaluate_dream_quality, evaluate_memory_fabric
from memory_fabric.paths import local_memory_dir
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
            result = initialize_memory_fabric(cwd, install_hooks=args.install_hooks)
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
            result = dream(
                cwd,
                mode=args.mode,
                apply=args.apply,
                llm_rewrite=args.llm_rewrite,
                max_rewrite_tasks=args.max_rewrite_tasks,
            )
            if args.eval and args.apply:
                result["evaluation"] = evaluate_dream_quality(
                    cwd,
                    snapshot=result["snapshot"] or "latest",
                    save_report=True,
                    llm_review=args.llm_review,
                )
            elif args.eval and not args.apply:
                result["warnings"].append("Dream evaluation requires --apply because candidate mode does not mutate live memory.")
            _print_result(result, args.json)
            return 0
        if args.command == "eval":
            if args.dream_snapshot:
                result = evaluate_dream_quality(
                    cwd,
                    snapshot=args.dream_snapshot,
                    save_report=not args.no_save,
                    llm_review=args.llm_review,
                )
            else:
                result = evaluate_memory_fabric(
                    cwd,
                    save_report=not args.no_save,
                    llm_review=args.llm_review,
                )
            _print_result(result, args.json)
            return 0 if result["status"] != "fail" else 1
        if args.command == "query":
            result = keyword_search(cwd, args.query, max_results=args.max_results)
            _print_result(result, args.json)
            return 0
        if args.command == "sync-global":
            memory_dir = local_memory_dir(cwd)
            if not args.json and sys.stdin.isatty() and memory_dir.exists():
                from memory_fabric.paths import global_memory_dir
                from memory_fabric.storage import _iter_markdown_files, _is_ignored_local_memory_path
                from memory_fabric.locking import locked_file
                import shutil
                
                promoted_count = 0
                local_files = [
                    path
                    for path in _iter_markdown_files(memory_dir)
                    if path.name != "index.md" and not _is_ignored_local_memory_path(memory_dir, path)
                ]
                
                if not local_files:
                    print("No local memory files found to promote.")
                    return 0
                    
                print("Interactive Global Memory Sync:")
                print("===============================")
                for path in local_files:
                    rel_name = path.name
                    choice = input(f"Promote local/{rel_name} to global/{rel_name}? [y/N]: ").strip().lower()
                    if choice in {"y", "yes"}:
                        target_dir = global_memory_dir()
                        target_dir.mkdir(parents=True, exist_ok=True)
                        target_path = target_dir / rel_name
                        
                        action = "copy"
                        if target_path.exists():
                            overwrite = input(f"  global/{rel_name} already exists. Overwrite? [y/N]: ").strip().lower()
                            if overwrite in {"y", "yes"}:
                                action = "copy"
                            else:
                                append = input(f"  Append content to global/{rel_name} instead? [y/N]: ").strip().lower()
                                if append in {"y", "yes"}:
                                    action = "append"
                                else:
                                    action = "skip"
                                    
                        if action == "copy":
                            with locked_file(target_path):
                                shutil.copy2(path, target_path)
                            print(f"  -> Promoted to {target_path}")
                            promoted_count += 1
                        elif action == "append":
                            from memory_fabric.frontmatter import parse_frontmatter, dump_frontmatter
                            with locked_file(target_path):
                                local_meta, local_body = parse_frontmatter(path.read_text(encoding="utf-8"))
                                global_meta, global_body = parse_frontmatter(target_path.read_text(encoding="utf-8"))
                                new_body = global_body.rstrip() + "\n\n" + local_body.lstrip()
                                global_meta["last_updated"] = local_meta.get("last_updated", "")
                                target_path.write_text(dump_frontmatter(global_meta, new_body), encoding="utf-8")
                            print(f"  -> Appended to {target_path}")
                            promoted_count += 1
                        else:
                            print(f"  -> Skipped global/{rel_name}")
                
                print(f"\nSync complete. Promoted {promoted_count} section(s) to global memory.")
                return 0
            else:
                preview = propose_memory_patch(
                    cwd,
                    "Review local memory for durable rules before manually promoting them to global memory.",
                )
                _print_result(
                    {
                        "message": "Global sync is preview-only in v1 when non-interactive or JSON requested. Review local memory before promoting.",
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
    init_parser = subparsers.add_parser("init", help="Create .ai-memory scaffolding")
    init_parser.add_argument("--install-hooks", action="store_true", help="Install opt-in git hooks")
    subparsers.add_parser("status", help="Show memory status")
    subparsers.add_parser("doctor", help="Validate memory files and environment")

    dream_parser = subparsers.add_parser("dream", help="Run local memory maintenance")
    dream_parser.add_argument("--mode", choices=["light", "deep"], default="light")
    dream_parser.add_argument("--apply", action="store_true", help="Apply candidate changes to live .ai-memory files")
    dream_parser.add_argument(
        "--llm-rewrite",
        action="store_true",
        help="Generate agent-assisted rewrite tasks from Dreaming output",
    )
    dream_parser.add_argument("--max-rewrite-tasks", type=int, default=5)
    dream_parser.add_argument("--eval", action="store_true", help="Evaluate quality before and after Dreaming")
    dream_parser.add_argument("--llm-review", action="store_true", help="Add optional qualitative LLM review notes")

    eval_parser = subparsers.add_parser("eval", help="Evaluate memory and Dreaming quality")
    eval_parser.add_argument("--llm-review", action="store_true", help="Add optional qualitative LLM review notes")
    eval_parser.add_argument("--dream", dest="dream_snapshot", help="Evaluate a Dreaming run against a snapshot name or latest")
    eval_parser.add_argument("--no-save", action="store_true", help="Do not save eval reports under .ai-memory/evals")

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
        return "\n" + json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
