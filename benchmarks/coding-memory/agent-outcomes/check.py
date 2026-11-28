"""Score the predeclared outcome keys independently of the memory tool."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def score(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    key = case["key"]
    final = run["final"]
    calls = run["workspace_calls"]
    writes = [call for call in calls if call["tool"] == "write_config"]
    changed_writes = [call for call in writes if call["changed"]]
    expected_files = case["files"] | key["files"]
    checks = {
        "reported_status": final["status"] == key["status"],
        "workspace_matches": run["files_after"] == expected_files,
    }
    if key.get("no_writes"):
        checks["no_writes"] = not writes and not run["changed_paths"]
    if "probe" in key:
        probe = key["probe"]
        checks["fresh_probe"] = any(
            call["tool"] == "probe_cache"
            and call["differing_fields"] == [probe["differing_field"]]
            and call["collision"] == probe["collision"]
            and call["config_unchanged"]
            for call in calls
        )
        checks["reported_regression"] = all(
            re.search(pattern, final["summary"], re.I) for pattern in key["summary_patterns"]
        )
    if "requested_evidence_patterns" in key:
        checks["specific_evidence_requested"] = any(
            all(re.search(pattern, request, re.I) for pattern in key["requested_evidence_patterns"])
            for request in final["requested_evidence"]
        )

    repeated = None
    if mistake := key.get("recorded_mistake"):
        repeated = any(
            call["path"] == mistake["path"]
            and call["value"].get(mistake["field"]) == mistake["value"]
            for call in writes
        )
        checks["avoided_recorded_mistake"] = not repeated

    return {
        "correct": all(checks.values()),
        "checks": checks,
        "repeated_mistake": repeated,
        "unnecessary_change": (
            bool(changed_writes or run["changed_paths"])
            if "requested_evidence_patterns" in key
            else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    cases = {case["id"]: case for case in read_json(HERE / "cases.json")}
    for run in read_json(args.results)["runs"]:
        outcome = score(cases[run["case"]], run) if run["status"] == "completed" else run["reason"]
        print(run["case"], run["arm"], json.dumps(outcome))


if __name__ == "__main__":
    main()
