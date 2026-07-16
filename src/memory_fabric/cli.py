"""Command line interface for Memory Fabric."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from memory_fabric.client_hooks import install_hooks
from memory_fabric.clients import CLIENTS
from memory_fabric.contracts import DreamEvalResult, EvalResult, MigrateResult
from memory_fabric.eval import evaluate_dream_quality, evaluate_memory_fabric
from memory_fabric.installer import install, install_all
from memory_fabric.merge_driver import install_merge_driver
from memory_fabric.merge_driver import run as run_merge_driver
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage import (
    capture_commit,
    delete_memory_store,
    doctor,
    dream,
    guard_journal,
    initialize_memory_fabric,
    keyword_search,
    list_memory_store,
    list_snapshots,
    mark_session_start,
    migrate_memory,
    propose_memory_patch,
    prune_dream_artifacts,
    read_memory_store,
    rollback,
    status,
    sync_agent_rules,
    verify_evidence,
    write_failure_memory,
    write_memory_store,
)
from memory_fabric.version import __version__

# Clients whose SessionStart hook reads a hookSpecificOutput.additionalContext
# JSON envelope on stdout (exit 0) — currently byte-identical across both,
# verified independently against each client's own docs. Split into separate
# builders here the moment either schema diverges; don't assume it stays true.
_SESSION_START_JSON_HOOK_FORMATS = frozenset({"claude-code", "gemini-cli"})


def _ensure_utf8_output() -> None:
    """Make CLI output UTF-8 regardless of the console code page (P-05).

    Default Windows consoles (cp1252/cp850) corrupt the em-dashes and bullets
    that memory templates legitimately contain into `?`/mojibake. Reconfigure
    stdout/stderr to UTF-8 with errors="replace" so output is correct on
    modern terminals and never crashes on legacy ones. CLI-only on purpose:
    the MCP server's stdio transport must not be touched.
    """
    for stream in (sys.stdout, sys.stderr):
        # `reconfigure` is a TextIOWrapper method, not part of the abstract
        # TextIO type sys.stdout/stderr are typed as — fetch it dynamically so
        # mypy doesn't require narrowing, and so any stream that duck-types
        # TextIOWrapper (e.g. colorama's Windows console wrapper) still works.
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            if (stream.encoding or "").lower().replace("-", "") != "utf8":
                reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "debug_llm", False):
        import os

        os.environ["MEMORY_FABRIC_LLM_DEBUG"] = "1"

    cwd = str(Path(args.cwd).expanduser().resolve())

    from memory_fabric.llm import load_env_from_cwd

    load_env_from_cwd(cwd)

    if args.command == "merge-driver":
        # Bypasses the try/except and cwd/env plumbing below: git invokes this
        # directly with absolute temp-file paths, not a project cwd.
        return run_merge_driver(args.ancestor, args.ours, args.theirs)

    try:
        if args.command == "init":
            init_result = initialize_memory_fabric(
                cwd,
                install_hooks=args.install_hooks,
                memory_prompt=args.memory_prompt,
            )
            if args.merge_driver:
                merge_driver_result = install_merge_driver(cwd)
                init_result["warnings"] = list(init_result.get("warnings", [])) + [
                    f"merge-driver: {w}" for w in merge_driver_result["warnings"]
                ]
                if merge_driver_result["gitattributes_changed"]:
                    init_result["files_created"] = [
                        *list(init_result.get("files_created", [])),
                        str(Path(cwd) / ".gitattributes"),
                    ]
            _print_result(init_result, args.json)
            return 0
        if args.command == "status":
            _print_result(status(cwd), args.json)
            return 0
        if args.command == "capture":
            capture_result = capture_commit(
                cwd, commit=args.commit, apply_filter=not args.no_filter
            )
            _print_result(capture_result, args.json)
            return 0
        if args.command == "session-start":
            mark_result = mark_session_start(cwd)
            if args.hook_format in _SESSION_START_JSON_HOOK_FORMATS:
                # Both Claude Code's and Gemini CLI's SessionStart hooks parse
                # stdout as JSON on exit 0 and inject
                # hookSpecificOutput.additionalContext into the session — the
                # same envelope shape on both clients (Gemini CLI's hook schema
                # is explicitly modeled on Claude Code's) — a different shape
                # than our plain result dict, so this bypasses _print_result
                # entirely rather than being folded into the generic output path.
                additional_context = (
                    f'Memory Fabric reminder: call read_combined_context_tool(cwd="{cwd}") '
                    "now if project memory has not been loaded yet this session. Before your "
                    "final response, call write_session_journal_tool to log what was "
                    "accomplished — the Stop hook will block ending the session without it."
                )
                print(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "SessionStart",
                                "additionalContext": additional_context,
                            }
                        }
                    )
                )
                return 0
            _print_result(mark_result, args.json)
            return 0
        if args.command == "guard-journal":
            guard_result = guard_journal(cwd)
            _print_result(guard_result, args.json)
            # Exit 2 (not 1) so a client Stop hook can distinguish "block the
            # stop" from an operational error, and surface the reason. Claude
            # Code (and hook conventions generally) read the block reason from
            # stderr on a plain exit 2, not stdout — printing only to stdout
            # above is silent to the very hook this command exists for.
            if not guard_result["ok"]:
                print(guard_result["reason"], file=sys.stderr)
                return 2
            return 0
        if args.command == "doctor":
            doctor_result = doctor(cwd, check_network=not getattr(args, "offline", False))
            _print_result(doctor_result, args.json)
            return 0 if doctor_result["ok"] else 1
        if args.command == "verify":
            verify_result = verify_evidence(cwd, mark_broken=not args.no_mark)
            _print_result(verify_result, args.json)
            return 0 if verify_result["ok"] else 1
        if args.command == "failure":
            tag_list = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
            failure_result = write_failure_memory(
                cwd, error_summary=args.error, fix_summary=args.fix, tags=tag_list
            )
            _print_result(failure_result, args.json)
            return 0
        if args.command == "install":
            if args.client == "all":
                install_all_result = install_all(
                    cwd,
                    project=args.project,
                    dry_run=args.dry_run,
                    uninstall=args.uninstall,
                    server_command=args.server_command,
                )
                if args.with_hooks:
                    install_all_result["warnings"] = [
                        *install_all_result["warnings"],
                        "--with-hooks is only supported together with a single --client for "
                        "now (e.g. --client claude-code --with-hooks); skipped for --client all.",
                    ]
                _print_result(install_all_result, args.json)
                return 0 if all(r["ok"] for r in install_all_result["results"]) else 1
            install_result = install(
                cwd,
                args.client,
                project=args.project,
                dry_run=args.dry_run,
                uninstall=args.uninstall,
                server_command=args.server_command,
            )
            combined_result: dict[str, Any] = dict(install_result)
            ok = install_result["ok"]
            if args.with_hooks:
                hook_result = install_hooks(
                    cwd, args.client, dry_run=args.dry_run, uninstall=args.uninstall
                )
                combined_result["hooks"] = hook_result
                ok = ok and hook_result["ok"]
            _print_result(combined_result, args.json)
            return 0 if ok else 1
        if args.command == "dream":
            dream_result = asyncio.run(
                dream(
                    cwd,
                    mode=args.mode,
                    apply=args.apply,
                    llm_rewrite=args.llm_rewrite,
                    max_rewrite_tasks=args.max_rewrite_tasks,
                )
            )
            if args.eval and args.apply:
                dream_result["evaluation"] = asyncio.run(
                    evaluate_dream_quality(
                        cwd,
                        snapshot=dream_result["snapshot"] or "latest",
                        save_report=True,
                        llm_review=args.llm_review,
                    )
                )
            elif args.eval and not args.apply:
                dream_result["warnings"].append(
                    "Dream evaluation requires --apply because candidate mode does not mutate live memory."
                )
            _print_result(dream_result, args.json)
            return 0
        if args.command == "migrate":
            migrate_result = asyncio.run(
                migrate_memory(
                    cwd,
                    dry_run=args.dry_run,
                    sections=args.section,
                    use_llm=False if args.no_llm else None,
                )
            )
            if args.json:
                _print_result(migrate_result, True)
            else:
                _print_migrate_plan(migrate_result)
                _print_result({k: v for k, v in migrate_result.items() if k != "plan"}, False)
            return 0
        if args.command == "eval":
            eval_result: EvalResult | DreamEvalResult
            if args.dream_snapshot:
                eval_result = asyncio.run(
                    evaluate_dream_quality(
                        cwd,
                        snapshot=args.dream_snapshot,
                        save_report=not args.no_save,
                        llm_review=args.llm_review,
                    )
                )
            else:
                eval_result = asyncio.run(
                    evaluate_memory_fabric(
                        cwd,
                        save_report=not args.no_save,
                        llm_review=args.llm_review,
                    )
                )
            _print_result(eval_result, args.json)
            return 0 if eval_result["status"] != "fail" else 1
        if args.command == "query":
            query_result = keyword_search(cwd, args.query, max_results=args.max_results)
            _print_result(query_result, args.json)
            return 0
        if args.command == "sync-agents":
            sync_result = sync_agent_rules(cwd)
            _print_result(sync_result, args.json)
            return 0 if sync_result.get("success") else 1
        if args.command == "sync-global":
            memory_dir = local_memory_dir(cwd)
            if not args.json and sys.stdin.isatty() and memory_dir.exists():
                import shutil

                from memory_fabric.locking import locked_file
                from memory_fabric.paths import global_memory_dir
                from memory_fabric.storage import (
                    _is_ignored_local_memory_path,
                    _iter_markdown_files,
                )

                promoted_count = 0
                local_files = [
                    path
                    for path in _iter_markdown_files(memory_dir)
                    if path.name != "index.md"
                    and not _is_ignored_local_memory_path(memory_dir, path)
                ]

                if not local_files:
                    print("No local memory files found to promote.")
                    return 0

                print("Interactive Global Memory Sync:")
                print("===============================")
                for path in local_files:
                    rel_name = path.name
                    choice = (
                        input(f"Promote local/{rel_name} to global/{rel_name}? [y/N]: ")
                        .strip()
                        .lower()
                    )
                    if choice in {"y", "yes"}:
                        target_dir = global_memory_dir()
                        target_dir.mkdir(parents=True, exist_ok=True)
                        target_path = target_dir / rel_name

                        action = "copy"
                        if target_path.exists():
                            overwrite = (
                                input(f"  global/{rel_name} already exists. Overwrite? [y/N]: ")
                                .strip()
                                .lower()
                            )
                            if overwrite in {"y", "yes"}:
                                action = "copy"
                            else:
                                append = (
                                    input(f"  Append content to global/{rel_name} instead? [y/N]: ")
                                    .strip()
                                    .lower()
                                )
                                action = "append" if append in {"y", "yes"} else "skip"

                        if action == "copy":
                            with locked_file(target_path):
                                shutil.copy2(path, target_path)
                            print(f"  -> Promoted to {target_path}")
                            promoted_count += 1
                        elif action == "append":
                            from memory_fabric.frontmatter import (
                                dump_frontmatter,
                                parse_frontmatter,
                            )

                            with locked_file(target_path):
                                local_meta, local_body = parse_frontmatter(
                                    path.read_text(encoding="utf-8")
                                )
                                global_meta, global_body = parse_frontmatter(
                                    target_path.read_text(encoding="utf-8")
                                )
                                new_body = global_body.rstrip() + "\n\n" + local_body.lstrip()
                                global_meta["last_updated"] = local_meta.get("last_updated", "")
                                target_path.write_text(
                                    dump_frontmatter(global_meta, new_body), encoding="utf-8"
                                )
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
            if getattr(args, "list", False):
                _print_result({"snapshots": list_snapshots(cwd)}, args.json)
                return 0
            if not args.to:
                print(
                    "error: provide --to <snapshot>, or run `ai-memory rollback --list` "
                    "to see available snapshots"
                )
                return 1
            rollback_result = rollback(cwd, args.to)
            _print_result(rollback_result, args.json)
            return 0
        if args.command == "clean":
            clean_result = prune_dream_artifacts(
                cwd,
                keep_snapshots=args.keep_snapshots,
                keep_candidates=args.keep_candidates,
                dry_run=args.dry_run,
            )
            _print_result(clean_result, args.json)
            return 0
        if args.command == "store":
            store_action = getattr(args, "store_action", None)
            if store_action == "write":
                tag_list = (
                    [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
                )
                store_write_result = write_memory_store(
                    cwd,
                    store_path=args.store_path,
                    content=args.content,
                    title=args.title,
                    tags=tag_list,
                    priority=args.priority,
                    mode=args.mode,
                )
                _print_result(store_write_result, args.json)
                return 0
            elif store_action == "read":
                store_read_result = read_memory_store(cwd, store_path=args.store_path)
                _print_result(store_read_result, args.json)
                return 0
            elif store_action == "list":
                tag_list = (
                    [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
                )
                store_list_result = list_memory_store(
                    cwd,
                    prefix=args.prefix,
                    tags=tag_list,
                    max_results=args.max_results,
                )
                _print_result(store_list_result, args.json)
                return 0
            elif store_action == "delete":
                store_delete_result = delete_memory_store(cwd, store_path=args.store_path)
                _print_result(store_delete_result, args.json)
                return 0
            else:
                parser.parse_args(["store", "--help"])
                return 1
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
    parser.add_argument(
        "--debug-llm", action="store_true", help="Enable LLM prompt and response logging"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="Create .ai-memory scaffolding")
    init_parser.add_argument(
        "--install-hooks", action="store_true", help="Install opt-in git hooks"
    )
    init_parser.add_argument(
        "--merge-driver",
        action="store_true",
        help="Register the semantic git merge driver for .ai-memory/**/*.md (per-clone; re-run after every fresh clone)",
    )
    init_parser.add_argument(
        "--memory-prompt", default=None, help="Steering instructions for agent memory capture"
    )
    subparsers.add_parser("status", help="Show memory status and capture stats")
    doctor_parser = subparsers.add_parser("doctor", help="Validate memory files and environment")
    doctor_parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip the (best-effort, 2s timeout) PyPI version-drift check",
    )

    verify_parser = subparsers.add_parser(
        "verify", help="Check evidence citations still resolve (self-verifying memory)"
    )
    verify_parser.add_argument(
        "--no-mark",
        action="store_true",
        help="Report broken evidence without stamping review_status: broken-evidence",
    )

    failure_parser = subparsers.add_parser(
        "failure", help="Record an error -> fix pair (deduplicated by normalized error text)"
    )
    failure_parser.add_argument("--error", required=True, help="Error message/symptom")
    failure_parser.add_argument("--fix", required=True, help="What fixed it")
    failure_parser.add_argument("--tags", default="", help="Comma-separated extra tags")

    merge_driver_parser = subparsers.add_parser(
        "merge-driver",
        help="Git merge driver backend (invoked by git itself, not meant for direct use)",
    )
    merge_driver_parser.add_argument("ancestor", help="Path to the common-ancestor version (%%O)")
    merge_driver_parser.add_argument(
        "ours", help="Path to our version; result is written here (%%A)"
    )
    merge_driver_parser.add_argument("theirs", help="Path to their version (%%B)")

    capture_parser = subparsers.add_parser(
        "capture", help="Record a commit as episodic memory (passive capture)"
    )
    capture_parser.add_argument(
        "--commit", default="HEAD", help="Commit to capture (default: HEAD)"
    )
    capture_parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Also capture noise commits (merges, [bot] authors, chore:/style:/ci:/"
        "build(deps) prefixes, lockfile-only changes) that are skipped by default",
    )
    session_start_parser = subparsers.add_parser(
        "session-start", help="Mark session start (for client SessionStart hooks)"
    )
    session_start_parser.add_argument(
        "--hook-format",
        choices=["claude-code", "gemini-cli"],
        default=None,
        help="Emit output in a specific client's hook-envelope format instead of "
        "the plain result (e.g. hookSpecificOutput.additionalContext)",
    )
    subparsers.add_parser(
        "guard-journal",
        help="Exit non-zero if no session journal was written (for client Stop hooks)",
    )

    install_parser = subparsers.add_parser(
        "install", help="Configure an MCP client to use memory-fabric"
    )
    install_parser.add_argument(
        "--client",
        required=True,
        choices=["all", *CLIENTS.keys()],
        help="Client to configure, or 'all' to detect and configure every installed client",
    )
    install_parser.add_argument(
        "--project",
        action="store_true",
        help="Write project-scoped config instead of global/user config",
    )
    install_parser.add_argument(
        "--dry-run", action="store_true", help="Preview the change without writing"
    )
    install_parser.add_argument(
        "--uninstall", action="store_true", help="Remove the memory-fabric entry only"
    )
    install_parser.add_argument(
        "--server-command",
        default=None,
        help=(
            "Explicit server command to write into the client config (e.g. a full path to "
            "memory-fabric-mcp). Overrides the automatic local-binary/uvx resolution."
        ),
    )
    install_parser.add_argument(
        "--with-hooks",
        action="store_true",
        help="Also wire client lifecycle hooks (SessionStart/Stop/PreCompact enforcement) "
        "if the chosen client has a supported hook adapter",
    )

    dream_parser = subparsers.add_parser("dream", help="Run local memory maintenance")
    dream_parser.add_argument("--mode", choices=["light", "deep"], default="light")
    dream_parser.add_argument(
        "--apply", action="store_true", help="Apply candidate changes to live .ai-memory files"
    )
    dream_parser.add_argument(
        "--llm-rewrite",
        action="store_true",
        help="Generate agent-assisted rewrite tasks from Dreaming output",
    )
    dream_parser.add_argument("--max-rewrite-tasks", type=int, default=5)
    dream_parser.add_argument(
        "--eval", action="store_true", help="Evaluate quality before and after Dreaming"
    )
    dream_parser.add_argument(
        "--llm-review", action="store_true", help="Add optional qualitative LLM review notes"
    )

    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Split legacy hand-written sections into memory-store entries (store-first)",
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the full plan without writing anything (no snapshot, no entries, no maps)",
    )
    migrate_parser.add_argument(
        "--section",
        action="append",
        default=None,
        help="Migrate only this section (repeatable; default: every legacy hand-written section)",
    )
    migrate_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM naming and use deterministic heading-based names",
    )

    eval_parser = subparsers.add_parser("eval", help="Evaluate memory and Dreaming quality")
    eval_parser.add_argument(
        "--llm-review", action="store_true", help="Add optional qualitative LLM review notes"
    )
    eval_parser.add_argument(
        "--dream",
        dest="dream_snapshot",
        help="Evaluate a Dreaming run against a snapshot name or latest",
    )
    eval_parser.add_argument(
        "--no-save", action="store_true", help="Do not save eval reports under .ai-memory/evals"
    )

    query_parser = subparsers.add_parser("query", help="Search memory")
    query_parser.add_argument("query")
    query_parser.add_argument("--max-results", type=int, default=10)

    subparsers.add_parser(
        "sync-agents",
        help="Synchronize agent instruction files using AGENTS.md as the source of truth",
    )
    subparsers.add_parser("sync-global", help="Preview local-to-global promotion")

    rollback_parser = subparsers.add_parser("rollback", help="Restore local memory from a snapshot")
    rollback_parser.add_argument(
        "--to", default=None, help="Snapshot name (run with --list to discover valid names)"
    )
    rollback_parser.add_argument(
        "--list", action="store_true", help="List available snapshots and exit"
    )

    clean_parser = subparsers.add_parser(
        "clean", help="Prune old dream snapshots and candidate stores"
    )
    clean_parser.add_argument(
        "--keep-snapshots",
        type=int,
        default=None,
        help="Snapshots to keep, newest first (default 10; env MEMORY_FABRIC_KEEP_SNAPSHOTS)",
    )
    clean_parser.add_argument(
        "--keep-candidates",
        type=int,
        default=None,
        help="Candidate stores to keep, newest first (default 3; env MEMORY_FABRIC_KEEP_CANDIDATES)",
    )
    clean_parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be removed without deleting"
    )

    store_parser = subparsers.add_parser("store", help="Memory store operations")
    store_subs = store_parser.add_subparsers(dest="store_action")

    store_write = store_subs.add_parser("write", help="Write a store file")
    store_write.add_argument(
        "store_path", help="Semantic path (e.g. architecture/decisions/auth-service)"
    )
    store_write.add_argument("--content", required=True, help="Content to write")
    store_write.add_argument("--title", default="", help="Title for the memory")
    store_write.add_argument("--tags", default="", help="Comma-separated tags")
    store_write.add_argument(
        "--priority",
        choices=["high", "medium", "low"],
        default=None,
        help="Omit to keep the existing file's priority (new files default to medium)",
    )
    store_write.add_argument("--mode", choices=["replace", "append"], default="replace")

    store_read = store_subs.add_parser("read", help="Read a store file")
    store_read.add_argument("store_path", help="Semantic path")

    store_list = store_subs.add_parser("list", help="List store files")
    store_list.add_argument("--prefix", default="", help="Filter by path prefix")
    store_list.add_argument("--tags", default="", help="Comma-separated tags to filter by")
    store_list.add_argument("--max-results", type=int, default=50)

    store_delete = store_subs.add_parser("delete", help="Delete a store file")
    store_delete.add_argument("store_path", help="Semantic path")

    return parser


def _print_migrate_plan(result: MigrateResult) -> None:
    """Human-readable plan listing for `ai-memory migrate` (non-JSON output)."""
    plan = result.get("plan") or []
    if not plan:
        print("Nothing to migrate: no legacy hand-written sections found.")
        return
    print("Migration plan (dry run):" if result.get("dry_run") else "Migration applied:")
    for section_plan in plan:
        marker = " [LLM-named]" if section_plan.get("llm_named") else ""
        print(f"  {section_plan['section']}.md -> memory-store/{section_plan['category']}/{marker}")
        for entry in section_plan.get("entries", []):
            print(
                f"    - {entry['store_path']}  ({entry['status']}, {entry['chars']} chars)"
                f"  <- {entry['source']}"
            )


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
