"""Field-topology regressions from the search-sermons store (no domain copy).

The live store had ~120 files, almost all high, timestamp summaries, finished
``*-complete`` handoffs still high, maps eating query-pack budget, and CUDA
OOM failures that did not collapse. This fixture copies that *shape*.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.storage import (
    context_for_task,
    doctor,
    initialize_memory_fabric,
    keyword_search,
    read_combined_context,
    write_failure_memory,
    write_memory_store,
)
from memory_fabric.storage.hygiene import is_timestamp_summary, is_weak_summary
from memory_fabric.storage.ranking import blended_score, lifecycle_penalty


def _write_store_file(
    temp: str,
    store_path: str,
    body: str,
    *,
    priority: str = "high",
    title: str | None = None,
    summary: str | None = None,
    last_updated: str = "2026-08-01T00:00:00-04:00",
) -> None:
    root = Path(temp) / ".ai-memory" / "memory-store"
    parts = store_path.split("/")
    dest = root.joinpath(*parts[:-1])
    dest.mkdir(parents=True, exist_ok=True)
    display = title or parts[-1].replace("-", " ").title()
    metadata = {
        "store_path": store_path,
        "title": display,
        "summary": summary or f"{display} — project memory entry.",
        "priority": priority,
        "tags": ["test"],
        "schema_version": "1.3",
        "last_updated": last_updated,
    }
    (dest / f"{parts[-1]}.md").write_text(dump_frontmatter(metadata, body), encoding="utf-8")


def _inflate_high_store(temp: str, n: int = 10) -> None:
    for i in range(n):
        _write_store_file(
            temp,
            f"pretraining/wave-{i:02d}-complete",
            f"Wave {i} is DONE. Do not re-run. Pointer to the next wave.",
            last_updated=f"2026-08-{i + 1:02d}T00:00:00-04:00",
        )


class HygieneUnitTests(unittest.TestCase):
    def test_timestamp_summary_is_weak(self) -> None:
        self.assertTrue(is_timestamp_summary("**Updated:** 2026-09-04 ~01:20 ET"))
        self.assertTrue(is_weak_summary("**Updated:** 2026-09-04 ~01:20 ET", "Handoff"))

    def test_live_handoff_outranks_complete_and_v2(self) -> None:
        live = lifecycle_penalty("store/fine-tuning/next-session-handoff")
        done = lifecycle_penalty("store/pretraining/wave-03-complete")
        old = lifecycle_penalty("store/pretraining/cpt-v2-next-session-handoff")
        self.assertGreater(live, done)
        self.assertGreater(live, old)

    def test_blended_score_prefers_recent_live_handoff(self) -> None:
        live = blended_score(
            1.0,
            "high",
            "2026-09-04T01:20:00-04:00",
            key="store/fine-tuning/next-session-handoff",
            query_present=True,
        )
        stale = blended_score(
            1.0,
            "high",
            "2026-08-25T10:20:00-04:00",
            key="store/pretraining/cpt-v2-next-session-handoff",
            query_present=True,
        )
        self.assertGreater(live, stale)


class WritePathGuardTests(unittest.TestCase):
    def test_timestamp_summary_is_replaced_from_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "fine-tuning/next-session-handoff",
                "Allowlist the API IP then run GATE-0. Scripts are already in the repo.",
                title="Fine-tuning next session handoff",
                priority="high",
            )
            path = (
                Path(temp)
                / ".ai-memory"
                / "memory-store"
                / "fine-tuning"
                / "next-session-handoff.md"
            )
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
            # Frontmatter round-trips through dump then parse: simulate a caller
            # who stamped a timestamp summary on an existing file.
            metadata["summary"] = "**Updated:** 2026-09-04 ~01:20 ET"
            path.write_text(
                dump_frontmatter(
                    metadata,
                    "Allowlist the API IP then run GATE-0. Scripts are already in the repo.\n",
                ),
                encoding="utf-8",
            )
            write_memory_store(
                temp,
                "fine-tuning/next-session-handoff",
                "Allowlist the API IP then run GATE-0. Scripts are already in the repo.",
                title="Fine-tuning next session handoff",
                priority="high",
                mode="replace",
            )
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertFalse(is_timestamp_summary(str(metadata.get("summary") or "")))
            self.assertIn("Allowlist", str(metadata.get("summary") or ""))

    def test_complete_path_is_stored_low(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            result = write_memory_store(
                temp,
                "pretraining/corpus-s3-complete",
                "S3 is DONE. Do not re-run. Pointer to s3-complete results.",
                title="Corpus S3 complete",
                priority="high",
            )
            self.assertTrue(any("-complete" in w for w in result["warnings"]))
            path = (
                Path(temp) / ".ai-memory" / "memory-store" / "pretraining" / "corpus-s3-complete.md"
            )
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("priority"), "low")

    def test_high_inflation_warns_on_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _inflate_high_store(temp, 10)
            _write_store_file(
                temp,
                "fine-tuning/old-wave-handoff",
                "Historical fine-tuning handoff still marked high.",
                last_updated="2026-08-20T00:00:00-04:00",
            )
            result = write_memory_store(
                temp,
                "fine-tuning/next-session-handoff",
                "Live next action: allowlist the API then launch GATE-0 on one GPU.",
                title="Fine-tuning next session handoff",
                priority="high",
            )
            self.assertTrue(any("already priority=high" in w for w in result["warnings"]))
            self.assertTrue(any("handoff files still exist" in w for w in result["warnings"]))


class QueryPackAndRetrieveTests(unittest.TestCase):
    def test_query_pack_prefers_store_hits_over_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            maps = Path(temp) / ".ai-memory"
            for name in ("architecture.md", "decisions.md", "index.md"):
                path = maps / name
                extra = " map-padding " * 400
                path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
            _write_store_file(
                temp,
                "fine-tuning/next-session-handoff",
                "Live GATE-0 next session handoff. Allowlist then launch.",
                last_updated="2026-09-04T01:20:00-04:00",
            )
            _write_store_file(
                temp,
                "pretraining/cpt-v2-next-session-handoff",
                "Historical v2 GATE-0 handoff. Do not restart.",
                last_updated="2026-08-25T10:20:00-04:00",
            )
            bundle = read_combined_context(
                temp, max_tokens=4000, query="continue GATE-0 next session handoff"
            )
            stats = bundle.get("pack_stats") or {}
            map_tokens = int((stats.get("tokens_by_role") or {}).get("map") or 0)
            other_tokens = int((stats.get("tokens_by_role") or {}).get("fine-tuning") or 0) + int(
                (stats.get("tokens_by_role") or {}).get("pretraining") or 0
            )
            self.assertIn("store/fine-tuning/next-session-handoff", bundle["included_sections"])
            self.assertLess(map_tokens, 900)
            self.assertGreater(other_tokens, map_tokens)

    def test_keyword_search_ranks_live_handoff_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(
                temp,
                "fine-tuning/next-session-handoff",
                "Live next session handoff for GATE-0.",
                last_updated="2026-09-04T01:20:00-04:00",
            )
            _write_store_file(
                temp,
                "pretraining/cpt-v2-next-session-handoff",
                "Historical v2 next session handoff. Do not restart.",
                last_updated="2026-08-25T10:20:00-04:00",
            )
            _write_store_file(
                temp,
                "pretraining/wave-03-complete",
                "Wave 3 complete handoff. DONE. Do not re-run.",
                last_updated="2026-08-27T11:22:00-04:00",
            )
            with mock.patch("shutil.which", return_value=None):
                results = keyword_search(temp, "handoff")
            self.assertGreaterEqual(len(results), 2)
            self.assertEqual(results[0]["section"], "store:fine-tuning/next-session-handoff")

    def test_context_for_task_uses_index_and_keeps_live_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(
                temp,
                "fine-tuning/vultr-spend-risk-controls",
                "Keep billing risk minimal. One GPU. Destroy on fail.",
                last_updated="2026-09-04T08:43:00-04:00",
            )
            _write_store_file(
                temp,
                "fine-tuning/next-session-handoff",
                "Continue SFT GATE-0 next session handoff after allowlist.",
                last_updated="2026-09-04T01:20:00-04:00",
            )
            _write_store_file(
                temp,
                "pretraining/cpt-v2-c-eval-gate-verdict",
                "Historical v2 GATE fail. Do not merge. Old handoff.",
                last_updated="2026-08-25T10:20:00-04:00",
            )
            _write_store_file(
                temp,
                "pretraining/wave-s3-handoff",
                "S3 handoff done. Pointer only.",
                last_updated="2026-08-29T11:22:00-04:00",
            )
            pack = context_for_task(temp, "continue SFT GATE-0 next session handoff")
            self.assertTrue((pack.get("pack_stats") or {}).get("index_used"))
            self.assertIn("store/fine-tuning/next-session-handoff", pack["included_sections"])
            self.assertIn("store/fine-tuning/vultr-spend-risk-controls", pack["included_sections"])
            store = [s for s in pack["included_sections"] if s.startswith("store/")]
            self.assertLess(
                store.index("store/fine-tuning/next-session-handoff"),
                store.index("store/pretraining/cpt-v2-c-eval-gate-verdict"),
            )
            self.assertLess(
                store.index("store/fine-tuning/next-session-handoff"),
                store.index("store/pretraining/wave-s3-handoff"),
            )


class StaleSupersededRankingTests(unittest.TestCase):
    def test_stale_and_superseded_lose_to_live_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store_file(
                temp,
                "pretraining/next-session-handoff",
                "Live CPT C-eval next session handoff. Run C-eval only.",
                last_updated="2026-09-20T12:00:00-04:00",
            )
            stale_path = (
                Path(temp)
                / ".ai-memory"
                / "memory-store"
                / "decisions"
                / "gemma4-finetuning.md"
            )
            stale_path.parent.mkdir(parents=True, exist_ok=True)
            stale_path.write_text(
                dump_frontmatter(
                    {
                        "store_path": "decisions/gemma4-finetuning",
                        "title": "Gemma 4 Fine Tuning",
                        "summary": "Legacy Gemma 4 fine-tuning decision.",
                        "priority": "high",
                        "tags": ["test"],
                        "schema_version": "1.3",
                        "last_updated": "2026-06-01T00:00:00-04:00",
                        "review_status": "stale",
                    },
                    "We use Gemma 4 for fine-tuning. CPT next session handoff for Gemma.",
                ),
                encoding="utf-8",
            )
            old_handoff = (
                Path(temp)
                / ".ai-memory"
                / "memory-store"
                / "pretraining"
                / "cpt-s5-handoff.md"
            )
            old_handoff.write_text(
                dump_frontmatter(
                    {
                        "store_path": "pretraining/cpt-s5-handoff",
                        "title": "CPT S5 Handoff",
                        "summary": "Previous CPT handoff, superseded.",
                        "priority": "high",
                        "tags": ["test"],
                        "schema_version": "1.3",
                        "last_updated": "2026-09-18T12:00:00-04:00",
                        "superseded_by": "pretraining/next-session-handoff",
                    },
                    "Old CPT C-eval next session handoff. Superseded.",
                ),
                encoding="utf-8",
            )
            live = blended_score(
                1.0,
                "high",
                "2026-09-20T12:00:00-04:00",
                key="store/pretraining/next-session-handoff",
                query_present=True,
            )
            stale = blended_score(
                1.0,
                "high",
                "2026-06-01T00:00:00-04:00",
                key="store/decisions/gemma4-finetuning",
                query_present=True,
                review_status="stale",
            )
            superseded = blended_score(
                1.0,
                "high",
                "2026-09-18T12:00:00-04:00",
                key="store/pretraining/cpt-s5-handoff",
                query_present=True,
                superseded_by="pretraining/next-session-handoff",
            )
            self.assertGreater(live, stale)
            self.assertGreater(live, superseded)
            pack = context_for_task(temp, "next CPT session handoff C-eval")
            included = pack["included_sections"]
            self.assertIn("store/pretraining/next-session-handoff", included)
            self.assertNotIn("store/decisions/gemma4-finetuning", included)
            if "store/pretraining/cpt-s5-handoff" in included:
                self.assertLess(
                    included.index("store/pretraining/next-session-handoff"),
                    included.index("store/pretraining/cpt-s5-handoff"),
                )


class DoctorEvalSmellTests(unittest.TestCase):
    def test_doctor_warns_on_high_percent_empty_steering_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _inflate_high_store(temp, 10)
            _write_store_file(
                temp,
                "fine-tuning/next-session-handoff",
                "Live GATE-0 next action.",
                summary="**Updated:** 2026-09-04 ~01:20 ET",
                last_updated="2026-09-04T01:20:00-04:00",
            )
            ul = Path(temp) / ".ai-memory" / "ubiquitous-language.md"
            text = ul.read_text(encoding="utf-8")
            body_start = text.find("# Ubiquitous")
            ul.write_text(
                text[:body_start] + "# Ubiquitous Language\n\nRecord project terminology here.\n",
                encoding="utf-8",
            )
            warnings = doctor(temp, check_network=False)["warnings"]
            joined = "\n".join(warnings)
            self.assertIn("priority=high", joined)
            self.assertIn("placeholder steering", joined)
            self.assertIn("weak summary", joined)

    def test_cuda_oom_wordings_collapse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_failure_memory(
                temp,
                error_summary=(
                    "CUDA OOM on Kaggle T4 during CPT B v5 after manual pack "
                    "(float32 Qwen, batch 2, TRAIN_EMBEDDINGS=True)"
                ),
                fix_summary="Drop batch size and eval docs.",
            )
            result = write_failure_memory(
                temp,
                error_summary=(
                    "CUDA out of memory during first eval of embed LoRA CPT: "
                    "tried to allocate 6.81 GiB on T4 while evaluating mix holdout buckets"
                ),
                fix_summary="Lower EVAL_DOCS_PER_BUCKET.",
            )
            failures = list((Path(temp) / ".ai-memory" / "memory-store" / "failures").glob("*.md"))
            self.assertEqual(len(failures), 1)
            self.assertTrue(any("occurred 2 times" in w for w in result["warnings"]))


class DreamChurnTests(unittest.TestCase):
    def test_second_apply_on_quiet_tree_is_cooldown_noop(self) -> None:
        import asyncio
        import os

        from memory_fabric.storage import dream as _async_dream
        from memory_fabric.templates import now_iso

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/cache-policy",
                "The cache TTL for TaskMaster task lists is 3600 seconds.",
                title="Cache Policy",
            )
            # Stamp a recent apply with matching fingerprint so cooldown engages.
            from memory_fabric.storage.finalize import _store_fingerprint

            private = Path(temp) / ".ai-memory" / "private"
            private.mkdir(parents=True, exist_ok=True)
            fp = _store_fingerprint(Path(temp) / ".ai-memory")
            (private / "last_dream_apply").write_text(now_iso() + "\n" + fp + "\n", encoding="utf-8")
            os.environ["MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES"] = "30"
            try:
                snaps_before = list((Path(temp) / ".ai-memory" / "snapshots").glob("memory-*"))
                second = asyncio.run(_async_dream(temp, mode="light", apply=True))
                snaps_after = list((Path(temp) / ".ai-memory" / "snapshots").glob("memory-*"))
            finally:
                os.environ.pop("MEMORY_FABRIC_DREAM_COOLDOWN_MINUTES", None)
            self.assertTrue(
                any("cooldown" in w.lower() or "skipped" in w.lower() for w in second["warnings"]),
                second["warnings"],
            )
            self.assertFalse(second["changed"])
            self.assertEqual(len(snaps_after), len(snaps_before))
            self.assertEqual(second.get("snapshot") or "", "")


if __name__ == "__main__":
    unittest.main()
