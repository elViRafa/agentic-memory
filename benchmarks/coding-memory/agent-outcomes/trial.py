"""Seed synthetic history over MCP and run fresh paired Codex sessions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from check import HERE, read_json, score
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONTEXT_BUDGET = 32_768
MEMORY_BUDGET = 1_200
REASONING = "low"
TIMEOUT_SECONDS = 150
INSTRUCTIONS = (
    "Use the trial workspace tools to inspect this checkout and do the task. "
    "Look up project history when prior decisions, failures or verification leads may matter. "
    "Return a short final report with any evidence you need from the user."
)
DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "computer_use",
    "hooks",
    "image_generation",
    "memories",
    "multi_agent",
    "plugins",
    "shell_tool",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(files: dict[str, bytes]) -> str:
    return digest(
        json.dumps({name: digest(data) for name, data in files.items()}, sort_keys=True).encode()
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}


def materialize(root: Path, files: dict[str, Any]) -> dict[str, bytes]:
    root.mkdir()
    for name, content in files.items():
        data = content if isinstance(content, str) else json.dumps(content, indent=2) + "\n"
        (root / name).write_bytes(data.encode())
    return snapshot(root)


async def seed(
    case: dict[str, Any],
    root: Path,
    engine_src: Path,
    memory_env: dict[str, str],
) -> dict[str, Any]:
    server_args = ["-m", "memory_fabric.server"]
    if clock := case.get("seed_clock"):
        # Date the write in the seed process. Dreaming then derives its real stale status.
        server_args = [
            "-c",
            "import sys; from memory_fabric.storage import store; "
            "from memory_fabric.server import main; "
            "timestamp = sys.argv.pop(1); store.now_iso = lambda: timestamp; "
            "raise SystemExit(main())",
            clock,
        ]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=server_args,
        env={**memory_env, "PYTHONPATH": str(engine_src)},
    )
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(reader, writer) as session,
    ):
        init = await session.initialize()

        async def call(tool: str, **arguments: Any) -> dict[str, Any]:
            result = await session.call_tool(tool, {"cwd": str(root), **arguments})
            if result.isError or result.structuredContent is None:
                raise RuntimeError(f"Seed MCP tool {tool} failed: {result.content}")
            return result.structuredContent

        await call("read_combined_context_tool")
        for entry in case["history"]:
            await call("write_memory_store_tool", **entry)
        if clock:
            await call("dream_tool", mode="light", apply=True)
        evidence = await call(
            "context_for_task_tool",
            query=case["prompt"],
            files_open=",".join(name for name in case["files"] if name.endswith(".json")),
            max_tokens=MEMORY_BUDGET,
        )

    key = case["key"]
    status = evidence["retrieval_status"]
    sources = evidence["included_sections"]
    if status != key["lookup_status"] or key["source"] not in sources:
        raise RuntimeError(f"{case['id']} seed preflight returned {status}: {sources}")
    return {
        "engine_version": init.serverInfo.version,
        "mcp_protocol_version": init.protocolVersion,
        "writes": [entry["store_path"] for entry in case["history"]],
        "preflight_status": status,
        "preflight_sources": sources,
    }


def agent_command(
    args: argparse.Namespace,
    workspace: Path,
    audit: Path,
    memory_root: Path | None,
    memory_env: dict[str, str],
) -> list[str]:
    server_args = [
        str(HERE / "workspace_server.py"),
        str(workspace),
        str(audit),
        str(args.engine_src),
        str(MEMORY_BUDGET),
    ]
    if memory_root is not None:
        server_args.extend(("--memory-root", str(memory_root)))
    env_toml = ", ".join(f"{key}={json.dumps(value)}" for key, value in memory_env.items())
    server_config = (
        "mcp_servers.trial={"
        f"command={json.dumps(sys.executable)}, args={json.dumps(server_args)}, "
        f"env={{{env_toml}}}, required=true, startup_timeout_sec=20, tool_timeout_sec=20, "
        'default_tools_approval_mode="approve"'
        "}"
    )
    command = [
        args.codex,
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        str(workspace),
        "--json",
        "--model",
        args.model,
        "--output-schema",
        str(HERE / "final.schema.json"),
        "-c",
        'approval_policy="never"',
        "-c",
        'web_search="disabled"',
        "-c",
        f"model_context_window={CONTEXT_BUDGET}",
        "-c",
        f'model_reasoning_effort="{REASONING}"',
        "-c",
        server_config,
    ]
    for feature in DISABLED_FEATURES:
        command.extend(("--disable", feature))
    return [*command, "-"]


def parse_events(output: str) -> tuple[dict[str, Any], list[str]]:
    telemetry: dict[str, Any] = {
        "session": None,
        "tokens": None,
        "final": None,
        "tool_approval_denials": [],
    }
    tools: dict[str, str] = {}
    failures: list[str] = []
    for line in output.splitlines():
        event = json.loads(line)
        kind = event["type"]
        if kind == "thread.started":
            telemetry["session"] = event["thread_id"]
        elif kind == "turn.completed":
            telemetry["tokens"] = event["usage"]
        elif kind in {"item.started", "item.completed"}:
            item = event["item"]
            if item["type"] == "agent_message" and kind == "item.completed":
                telemetry["final"] = item["text"]
            if item["type"] in {"mcp_tool_call", "command_execution", "file_change", "web_search"}:
                tools[item["id"]] = item.get("tool", item["type"])
            if item["type"] == "mcp_tool_call" and item.get("status") == "failed":
                error = json.dumps(item.get("error")).casefold()
                if "approval" in error:
                    telemetry["tool_approval_denials"].append(item["tool"])
        elif kind == "turn.failed":
            failures.append(event["error"]["message"])
    telemetry["tool_calls"] = list(tools.values())
    return telemetry, failures


def evaluate(
    args: argparse.Namespace,
    case: dict[str, Any],
    root: Path,
    baseline: dict[str, bytes],
    memory_root: Path | None,
    memory_env: dict[str, str],
) -> dict[str, Any]:
    arm = "on" if memory_root else "off"
    root.mkdir()
    workspace = root / "checkout"
    files_before = materialize(workspace, case["files"])
    if files_before != baseline:
        raise RuntimeError("Arm started from a different workspace snapshot")
    prompt = f"{case['prompt']}\n\n{INSTRUCTIONS}"
    audit = root / "calls.jsonl"
    run: dict[str, Any] = {
        "case": case["id"],
        "arm": arm,
        "status": "unavailable",
        "session": None,
        "snapshot_sha256": fingerprint(files_before),
        "prompt_sha256": digest(prompt.encode()),
        "tokens": None,
        "tool_calls": None,
    }
    # Do not inherit the enclosing agent's session or desktop tool integration.
    env = {
        key: value
        for key, value in os.environ.items()
        if key == "CODEX_HOME" or not key.startswith("CODEX_")
    }
    try:
        result = subprocess.run(
            agent_command(args, workspace, audit, memory_root, memory_env),
            input=prompt,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        telemetry, failures = parse_events(result.stdout)
        run.update(telemetry)
        if result.returncode != 0:
            stderr = [line for line in result.stderr.splitlines() if line.strip()]
            detail = next(iter(failures or stderr[-1:]), "no diagnostic")
            raise ValueError(f"Codex exit {result.returncode}: {detail}")
        if not run["session"] or run["tokens"] is None or run["final"] is None:
            raise ValueError("Missing session ID, completed usage, or final report")
        if run["tool_approval_denials"] or (
            run["tool_calls"] and not audit.exists() and "approval" in run["final"].casefold()
        ):
            raise ValueError("Codex approval policy denied calls to the workspace MCP server")
        if any(
            tool in {"command_execution", "file_change", "web_search"} for tool in run["tool_calls"]
        ):
            raise ValueError("Codex used a tool outside the scoped workspace MCP")
        final = json.loads(run["final"])
        if (
            not isinstance(final, dict)
            or set(final) != {"status", "summary", "requested_evidence"}
            or final["status"] not in {"completed", "verified", "blocked"}
            or not isinstance(final["summary"], str)
            or not isinstance(final["requested_evidence"], list)
            or not all(isinstance(item, str) for item in final["requested_evidence"])
        ):
            raise ValueError("Final report did not match the requested schema")
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        reason = (
            str(error)
            if not isinstance(error, subprocess.TimeoutExpired)
            else (f"Codex did not finish within {TIMEOUT_SECONDS} seconds")
        )
        run["reason"] = reason.replace(str(root), "<run>").replace(str(HERE), "<benchmark>")
        run.pop("final", None)
        return run

    files_after = snapshot(workspace)
    calls = audit.read_text(encoding="utf-8").splitlines() if audit.exists() else []
    run.update(
        {
            "status": "completed",
            "final": final,
            "workspace_calls": [json.loads(line) for line in calls],
            "changed_paths": sorted(
                path
                for path in files_before.keys() | files_after.keys()
                if files_before.get(path) != files_after.get(path)
            ),
            "files_after": {
                name: read_json(workspace / name) if name.endswith(".json") else data.decode()
                for name, data in files_after.items()
            },
        }
    )
    run["score"] = score(case, run)
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model", default="gpt-6.2-sol")
    parser.add_argument("--engine-src", type=Path, default=HERE.parents[2] / "src")
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    parser.add_argument("--validate-fixtures", action="store_true", help="Run seed preflights only")
    args = parser.parse_args()
    args.engine_src = args.engine_src.resolve()
    cases = read_json(HERE / "cases.json")

    with TemporaryDirectory(prefix="memory-recall-trials-") as temporary:
        root = Path(temporary)
        memory_env = {"MEMORY_FABRIC_HOME": str(root / "empty-global"), "MEMORY_FABRIC_DIARY": "0"}
        seeds = {}
        baselines = {}
        for case in cases:
            case_id = case["id"]
            seed_root = root / (case_id + "-seed")
            baselines[case_id] = materialize(seed_root, case["files"])
            seeds[case_id] = asyncio.run(seed(case, seed_root, args.engine_src, memory_env))
            print(f"Seeded {case_id}: {seeds[case_id]['preflight_status']}", flush=True)
        if args.validate_fixtures:
            return 0

        client = subprocess.run(
            [args.codex, "--version"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        def pair(index: int, case: dict[str, Any]) -> list[dict[str, Any]]:
            case_id = case["id"]
            seed_root = root / (case_id + "-seed")
            memory_roots = (seed_root, None) if index % 2 == 0 else (None, seed_root)
            runs = []
            for slot, memory_root in enumerate(memory_roots, 1):
                run = evaluate(
                    args,
                    case,
                    root / f"{case_id}-{slot}",
                    baselines[case_id],
                    memory_root,
                    memory_env,
                )
                runs.append(run)
                print(f"{case_id} {run['arm']}: {run['status']}", flush=True)
            return runs

        with ThreadPoolExecutor(max_workers=len(cases)) as pool:
            runs = [
                run for pair_runs in pool.map(pair, range(len(cases)), cases) for run in pair_runs
            ]

    session_ids = [run["session"] for run in runs if run["session"]]
    if len(set(session_ids)) != len(session_ids):
        raise RuntimeError("Evaluation sessions were reused")
    for number, run in enumerate(runs, 1):
        if run["session"]:
            run["session"] = f"session-{number:02d}"
    engine_files = {
        path.relative_to(args.engine_src).as_posix(): path.read_bytes()
        for path in (args.engine_src / "memory_fabric").rglob("*.py")
    }
    payload = {
        "model": args.model,
        "client": client,
        "python": platform.python_version(),
        "mcp_sdk": version("mcp"),
        "context_budget": CONTEXT_BUDGET,
        "memory_budget": MEMORY_BUDGET,
        "reasoning_effort": REASONING,
        "engine_source_sha256": fingerprint(engine_files),
        "fixtures_sha256": digest((HERE / "cases.json").read_bytes()),
        "scorer_sha256": digest((HERE / "check.py").read_bytes()),
        "pairs_planned": len(cases),
        "pairs_completed": sum(
            sum(run["case"] == case["id"] and run["status"] == "completed" for run in runs) == 2
            for case in cases
        ),
        "seeds": seeds,
        "runs": runs,
    }
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return 0 if payload["pairs_completed"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
