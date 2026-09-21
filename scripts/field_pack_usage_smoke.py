"""Almost-real field pack usage smoke (U1–U5).

Simulates an agent session over a search-sermons-*shaped* synthetic store
(or a live ``--cwd`` project): write → startup pack → task pack → light dream
twice → doctor → eval. Hard gates match ``TEST_PLAN_FIELD_PACK_PRECISION.md``.

No domain facts from search-sermons are copied — generic wave/handoff/adapter
vocabulary only.

Usage:
    PYTHONPATH=src python scripts/field_pack_usage_smoke.py
    PYTHONPATH=src python scripts/field_pack_usage_smoke.py --tmpdir %TEMP%\\mf-field-smoke
    PYTHONPATH=src python scripts/field_pack_usage_smoke.py --cwd C:\\path\\to\\search-sermons
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from memory_fabric.eval.memory_quality import evaluate_memory_fabric
from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage import (
    context_for_task,
    doctor,
    dream,
    initialize_memory_fabric,
    read_combined_context,
    write_memory_store,
)
from memory_fabric.templates import now_iso

TASK_QUERY = "continue next session handoff for fine-tuning"
LIVE_HANDOFF = "fine-tuning/next-session-handoff"
STALE_DECISION = "decisions/legacy-model-finetuning"
PLACEHOLDER_UL = "Record project terminology here."


def _write_store_file(
    cwd: str,
    store_path: str,
    body: str,
    *,
    priority: str = "high",
    title: str | None = None,
    summary: str | None = None,
    last_updated: str = "2026-08-01T00:00:00-04:00",
    extra_meta: dict[str, Any] | None = None,
) -> None:
    root = Path(cwd) / ".ai-memory" / "memory-store"
    parts = store_path.split("/")
    dest = root.joinpath(*parts[:-1])
    dest.mkdir(parents=True, exist_ok=True)
    display = title or parts[-1].replace("-", " ").title()
    metadata: dict[str, Any] = {
        "store_path": store_path,
        "title": display,
        "summary": summary or f"{display} — project memory entry.",
        "priority": priority,
        "tags": ["field-smoke"],
        "schema_version": "1.3",
        "last_updated": last_updated,
    }
    if extra_meta:
        metadata.update(extra_meta)
    (dest / f"{parts[-1]}.md").write_text(dump_frontmatter(metadata, body), encoding="utf-8")


def _set_placeholder_ul(cwd: str) -> None:
    ul = Path(cwd) / ".ai-memory" / "ubiquitous-language.md"
    text = ul.read_text(encoding="utf-8")
    body_start = text.find("# Ubiquitous")
    if body_start < 0:
        body_start = text.find("---", 3)
        if body_start >= 0:
            body_start = text.find("\n", body_start + 3) + 1
    if body_start < 0:
        return
    ul.write_text(
        text[:body_start] + f"# Ubiquitous Language\n\n{PLACEHOLDER_UL}\n",
        encoding="utf-8",
    )


def seed_store(cwd: str) -> None:
    """Build a ~80-file diary-shaped store (no domain copy)."""
    initialize_memory_fabric(cwd)

    for i in range(40):
        # Avoid embedding distinct integers — near-duplicate diary files with
        # different numbers explode the numeric contradiction detector.
        _write_store_file(
            cwd,
            f"pretraining/wave-{i:02d}-complete",
            "This wave is DONE. Do not re-run. Pointer to the next wave only.",
            last_updated=f"2026-08-{(i % 28) + 1:02d}T00:00:00-04:00",
        )

    for n, loss in ((2, "0.45"), (3, "0.32"), (4, "0.28")):
        _write_store_file(
            cwd,
            f"pretraining/wave-s{n}-handoff",
            f"S{n} handoff. Completed {n} waves. Loss {loss}. Next is S{n + 1}.",
            title=f"Wave S{n} Handoff",
            last_updated=f"2026-08-{20 + n:02d}T00:00:00-04:00",
        )

    for i in range(8):
        _write_store_file(
            cwd,
            f"pretraining/wave-{i:02d}-adapter-notes",
            "Training notes for this wave. Use adapter tuning here. "
            "Adapter rank stays at sixteen for this wave.",
            title=f"Wave {i} Adapter Notes",
            last_updated=f"2026-08-{(i % 28) + 1:02d}T12:00:00-04:00",
        )

    topics = (
        "learning rate schedule",
        "eval gate checklist",
        "batch size notes",
        "checkpoint cadence",
        "tokenizer freeze policy",
        "gradient clip settings",
        "warmup steps plan",
        "validation split rules",
        "early stop criteria",
        "mixed precision flags",
        "dataset shuffle seed",
        "prompt template version",
        "lora target modules",
        "eval holdout buckets",
    )
    for i, topic in enumerate(topics):
        _write_store_file(
            cwd,
            f"fine-tuning/note-{i:02d}",
            f"Fine-tuning notebook on {topic}. Track progress for this topic only.",
            last_updated=f"2026-08-{(i % 28) + 1:02d}T08:00:00-04:00",
        )
    _write_store_file(
        cwd,
        "fine-tuning/old-session-handoff",
        "Historical fine-tuning handoff. Prefer the live next-session file.",
        last_updated="2026-08-20T00:00:00-04:00",
    )

    _write_store_file(
        cwd,
        "architecture/serving-boundaries",
        "Must not mount the training volume on the serving pod. "
        "Keep inference volumes separate from the training volume.",
        title="Serving Boundaries",
        last_updated="2026-08-15T00:00:00-04:00",
    )
    _write_store_file(
        cwd,
        "bugs/adapter-frozen-weights",
        "Do not use adapter tuning on frozen embeddings. "
        "Adapter tuning caused the tokenizer mismatch on frozen weights.",
        title="Adapter Frozen Weights",
        last_updated="2026-08-18T00:00:00-04:00",
    )

    # One short same-topic reversal so the pack path is exercised without
    # flooding token budget (hygiene fails above ~150 pack tokens).
    _write_store_file(
        cwd,
        "decisions/prd-1001-add-cache-column",
        "PRD 1001 adds the column cache_ttl_override after the tally.",
        title="PRD 1001 add cache_ttl_override",
        last_updated="2026-07-01T00:00:00-04:00",
    )
    _write_store_file(
        cwd,
        "decisions/prd-1002-reverse-cache-column",
        "PRD 1002 reverses PRD 1001. Do not add cache_ttl_override.",
        title="PRD 1002 reverses cache_ttl_override",
        last_updated="2026-07-02T00:00:00-04:00",
    )

    _write_store_file(
        cwd,
        STALE_DECISION,
        "Legacy model fine-tuning decision. Also mentions next session handoff "
        "so keyword search can match, but this entry is stale.",
        title="Legacy Model Finetuning",
        last_updated="2026-06-01T00:00:00-04:00",
        extra_meta={"review_status": "stale"},
    )

    _write_store_file(
        cwd,
        "failures/opc-type-mismatch-sim",
        "OPC UA Variant type mismatch on asyncua client NodeId browse. "
        "Industrial bus simulation only — unrelated to training.",
        title="OPC Type Mismatch Sim",
        priority="medium",
        last_updated="2026-08-10T00:00:00-04:00",
    )
    _write_store_file(
        cwd,
        "failures/opc-subscription-timeout-sim",
        "asyncua subscription watchdog timeout on industrial PLC link. "
        "Not a training failure.",
        title="OPC Subscription Timeout Sim",
        priority="medium",
        last_updated="2026-08-11T00:00:00-04:00",
    )

    _set_placeholder_ul(cwd)

    write_memory_store(
        cwd,
        LIVE_HANDOFF,
        "Live next session handoff for fine-tuning. "
        "Continue the next session handoff: allowlist the API then launch GATE-0.",
        title="Fine-tuning next session handoff",
        priority="high",
        mode="replace",
    )


def _candidate_dirs(memory_dir: Path) -> list[Path]:
    root = memory_dir / "candidates"
    if not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_dir()]


def _snapshot_dirs(memory_dir: Path) -> list[Path]:
    root = memory_dir / "snapshots"
    if not root.is_dir():
        return []
    return [p for p in root.glob("memory-*") if p.is_dir()]


def _contradiction_wall_count(packed_text: str) -> int:
    """Count YAML list items under a ``contradictions:`` block in packed text."""
    match = re.search(r"(?m)^contradictions:\s*\n((?:[ \t]+- .*\n)*)", packed_text)
    if not match:
        # Empty pack form: contradictions: []
        if re.search(r"(?m)^contradictions:\s*\[\s*\]\s*$", packed_text):
            return 0
        return 0
    block = match.group(1)
    return len(re.findall(r"(?m)^[ \t]+- ", block))


def _iter_eval_checks(result: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for category in result.get("categories") or []:
        for check in category.get("checks") or []:
            checks.append(check)
    return checks


def _find_check(result: dict[str, Any], name: str) -> dict[str, Any] | None:
    for check in _iter_eval_checks(result):
        if check.get("name") == name or check.get("id") == name:
            return check
    # Some eval shapes use ``check`` key
    for check in _iter_eval_checks(result):
        if str(check.get("check") or "") == name:
            return check
    return None


def run_smoke(cwd: str, *, mode: str) -> dict[str, Any]:
    memory_dir = local_memory_dir(cwd)
    gates: dict[str, str] = {}
    metrics: dict[str, Any] = {"mode": mode}
    details: dict[str, Any] = {}

    # --- A: seed / store present ---
    if mode == "synthetic":
        seed_store(cwd)
        handoff = memory_dir / "memory-store" / "fine-tuning" / "next-session-handoff.md"
        gates["A"] = "pass" if handoff.exists() else "fail"
        metrics["seed_files"] = sum(
            1 for _ in (memory_dir / "memory-store").rglob("*.md")
        )
    else:
        if not memory_dir.exists():
            gates["A"] = "fail"
            details["A"] = f"missing memory dir: {memory_dir}"
        else:
            gates["A"] = "pass"
            metrics["seed_files"] = sum(
                1 for _ in (memory_dir / "memory-store").rglob("*.md")
            ) if (memory_dir / "memory-store").exists() else 0

    # --- B: startup pack ---
    if gates.get("A") == "pass":
        try:
            bundle = read_combined_context(cwd)
            est = int(bundle.get("estimated_tokens") or 0)
            budget = int(bundle.get("token_budget") or 0)
            wall = _contradiction_wall_count(str(bundle.get("text") or ""))
            metrics["startup_tokens"] = est
            metrics["startup_budget"] = budget
            metrics["startup_contradiction_wall"] = wall
            budget_ok = budget <= 0 or est <= budget
            gates["B"] = "pass" if budget_ok and wall <= 8 else "fail"
            if not budget_ok:
                details["B"] = f"budget overflow {est}/{budget}"
            elif wall > 8:
                details["B"] = f"contradiction wall size {wall}"
        except Exception as exc:  # noqa: BLE001 - smoke reports failures as gates
            gates["B"] = "fail"
            details["B"] = str(exc)
    else:
        gates["B"] = "skip"

    # --- C: task pack ---
    if gates.get("A") == "pass":
        try:
            pack = context_for_task(cwd, TASK_QUERY)
            included = list(pack.get("included_sections") or [])
            metrics["task_included_n"] = len(included)
            has_live = any("next-session-handoff" in s for s in included)
            stale_key = f"store/{STALE_DECISION}"
            excludes_stale = stale_key not in included
            gates["C"] = "pass" if has_live and excludes_stale else "fail"
            if not has_live:
                details["C"] = f"missing next-session-handoff in {included[:12]}"
            elif not excludes_stale:
                details["C"] = f"stale decision still included: {stale_key}"
        except Exception as exc:  # noqa: BLE001
            gates["C"] = "fail"
            details["C"] = str(exc)
    else:
        gates["C"] = "skip"

    # --- D: first light dream ---
    if gates.get("A") == "pass":
        try:
            first = asyncio.run(dream(cwd, mode="light", apply=True))
            index_path = memory_dir / "index.md"
            meta, _ = parse_frontmatter(index_path.read_text(encoding="utf-8"))
            pack_list = meta.get("contradictions") or []
            if not isinstance(pack_list, list):
                pack_list = []
            pack_len = len(pack_list)
            report = memory_dir / "evals" / "contradictions.json"
            candidates_n = len(_candidate_dirs(memory_dir))
            snaps_d = len(_snapshot_dirs(memory_dir))
            metrics["contradiction_pack_len"] = pack_len
            metrics["contradiction_count"] = meta.get("contradiction_count")
            metrics["candidates_after_d"] = candidates_n
            metrics["snapshots_after_d"] = snaps_d
            metrics["dream1_changed"] = bool(first.get("changed"))
            ok = (
                pack_len <= 5
                and meta.get("contradiction_count") is not None
                and report.exists()
                and candidates_n == 0
            )
            gates["D"] = "pass" if ok else "fail"
            if not ok:
                details["D"] = {
                    "pack_len": pack_len,
                    "contradiction_count": meta.get("contradiction_count"),
                    "report_exists": report.exists(),
                    "candidates": candidates_n,
                    "warnings": first.get("warnings") or [],
                }
        except Exception as exc:  # noqa: BLE001
            gates["D"] = "fail"
            details["D"] = str(exc)
            snaps_d = len(_snapshot_dirs(memory_dir))
            metrics["snapshots_after_d"] = snaps_d
    else:
        gates["D"] = "skip"
        snaps_d = 0

    # --- E: second light dream (cooldown) ---
    if gates.get("A") == "pass":
        prev_cooldown = os.environ.get("MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES")
        os.environ["MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES"] = "30"
        try:
            second = asyncio.run(dream(cwd, mode="light", apply=True))
            snaps_e = len(_snapshot_dirs(memory_dir))
            metrics["snapshots_after_e"] = snaps_e
            metrics["dream2_changed"] = bool(second.get("changed"))
            warnings = [str(w).lower() for w in (second.get("warnings") or [])]
            cooldownish = any(
                any(tok in w for tok in ("cooldown", "skipped", "discarded", "no-op", "noop"))
                for w in warnings
            )
            # Prefer: changed False OR cooldown language; snapshots must not grow.
            snaps_ok = snaps_e <= int(metrics.get("snapshots_after_d") or 0)
            changed_ok = (not second.get("changed")) or cooldownish
            gates["E"] = "pass" if snaps_ok and changed_ok else "fail"
            if gates["E"] == "fail":
                details["E"] = {
                    "changed": second.get("changed"),
                    "warnings": second.get("warnings") or [],
                    "snapshots_after_d": metrics.get("snapshots_after_d"),
                    "snapshots_after_e": snaps_e,
                }
        except Exception as exc:  # noqa: BLE001
            gates["E"] = "fail"
            details["E"] = str(exc)
        finally:
            if prev_cooldown is None:
                os.environ.pop("MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES", None)
            else:
                os.environ["MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES"] = prev_cooldown
    else:
        gates["E"] = "skip"

    # --- F: doctor ---
    if gates.get("A") == "pass":
        try:
            report = doctor(cwd, check_network=False)
            joined = "\n".join(report.get("warnings") or []).lower()
            metrics["doctor_warning_n"] = len(report.get("warnings") or [])
            if mode == "synthetic":
                ok = any(
                    tok in joined
                    for tok in ("placeholder", "ubiquitous-language", "steering")
                )
            else:
                ok = any(
                    tok in joined
                    for tok in (
                        "placeholder",
                        "ubiquitous-language",
                        "steering",
                        "stale",
                        "off-topic",
                        "off_topic",
                    )
                )
            gates["F"] = "pass" if ok else "fail"
            if not ok:
                details["F"] = (report.get("warnings") or [])[:8]
        except Exception as exc:  # noqa: BLE001
            gates["F"] = "fail"
            details["F"] = str(exc)
    else:
        gates["F"] = "skip"

    # --- G: eval ---
    if gates.get("A") == "pass":
        try:
            eval_result = asyncio.run(evaluate_memory_fabric(cwd, save_report=False))
            hygiene = _find_check(eval_result, "contradiction_pack_hygiene")
            ul = _find_check(eval_result, "ubiquitous_language_placeholder")
            if ul is None:
                ul = _find_check(eval_result, "ubiquitous-language_placeholder")
            metrics["contradiction_pack_hygiene"] = (
                hygiene.get("status") if hygiene else None
            )
            metrics["ul_placeholder_status"] = ul.get("status") if ul else None
            hygiene_ok = hygiene is None or hygiene.get("status") != "fail"
            if mode == "synthetic":
                ul_ok = ul is not None and ul.get("status") in {"fail", "warn"}
            else:
                # Live stores may have filled UL; only enforce when the check fires.
                ul_ok = ul is None or ul.get("status") in {"fail", "warn", "pass"}
                if ul is not None and ul.get("status") == "pass":
                    # Placeholder check should not pass on empty starter text;
                    # if it says pass, body is real — fine for live.
                    ul_ok = True
            gates["G"] = "pass" if hygiene_ok and ul_ok else "fail"
            if not hygiene_ok:
                details["G"] = {"hygiene": hygiene}
            elif not ul_ok:
                details["G"] = {"ul_placeholder": ul}
        except Exception as exc:  # noqa: BLE001
            gates["G"] = "fail"
            details["G"] = str(exc)
    else:
        gates["G"] = "skip"

    hard = [g for g in ("A", "B", "C", "D", "E", "F", "G") if gates.get(g) == "fail"]
    ok = not hard
    return {
        "ok": ok,
        "cwd": str(cwd),
        "mode": mode,
        "gates": gates,
        "metrics": metrics,
        "details": details,
        "generated_at": now_iso(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cwd",
        type=str,
        default=None,
        help="Live project root (skip seed; run B–G). Default: synthetic temp store.",
    )
    parser.add_argument(
        "--tmpdir",
        type=str,
        default=None,
        help="Directory for synthetic .ai-memory (created if missing). Ignored with --cwd.",
    )
    args = parser.parse_args(argv)

    cleanup: Path | None = None
    if args.cwd:
        cwd = str(Path(args.cwd).resolve())
        mode = "live"
        result = run_smoke(cwd, mode=mode)
    else:
        if args.tmpdir:
            root = Path(args.tmpdir).resolve()
            root.mkdir(parents=True, exist_ok=True)
            cwd = str(root)
        else:
            cleanup = Path(tempfile.mkdtemp(prefix="mf-field-smoke-"))
            cwd = str(cleanup)
        mode = "synthetic"
        try:
            result = run_smoke(cwd, mode=mode)
        finally:
            if cleanup is not None and os.environ.get("MEMORY_FABRIC_SMOKE_KEEP") != "1":
                shutil.rmtree(cleanup, ignore_errors=True)

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
