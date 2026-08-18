#!/usr/bin/env python3
"""Standalone runner for the coding-memory benchmark.

    python benchmarks/coding-memory/run.py
    python benchmarks/coding-memory/run.py --json

When this directory is extracted as its own repo, install `memory-fabric` and
run the same file from the new root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    here = Path(__file__).resolve()
    repo_src = here.parents[2] / "src"
    if repo_src.is_dir():
        sys.path.insert(0, str(repo_src))


def main(argv: list[str] | None = None) -> int:
    _ensure_src_on_path()
    from memory_fabric.eval.bench import run_coding_memory_benchmark

    parser = argparse.ArgumentParser(description="coding-memory-bench")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--suite", default=None, help="Override task file")
    args = parser.parse_args(argv)

    suite = args.suite
    if suite is None:
        sibling = Path(__file__).resolve().parent / "tasks.yaml"
        if sibling.exists():
            suite = str(sibling)

    result = run_coding_memory_benchmark(fixture="builtin", suite_path=suite, k=args.k)
    if args.json:
        payload = {key: value for key, value in result.items() if key != "report_markdown"}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(result["report_markdown"], end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
