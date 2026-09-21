"""R7-3: polarity, reversal, numeric, doctor, and LLM-enrichment tests."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.frontmatter import parse_frontmatter
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage import (
    detect_contradictions,
    doctor,
    initialize_memory_fabric,
    write_memory_store,
)
from memory_fabric.storage import dream as _async_dream
from memory_fabric.storage.contradictions import (
    detect_contradiction_messages,
    enrich_contradictions_with_llm,
)


def dream(*args: object, **kwargs: object):
    return asyncio.run(_async_dream(*args, **kwargs))


class ContradictionPrecisionTests(unittest.TestCase):
    def test_field_false_polarity_across_categories_is_suppressed(self) -> None:
        """Architecture 'must not mount CPT' vs pretraining 'run CPT' is not an ADR clash."""
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "architecture/ask-app-rag",
                "Must not mount the CPT training volume on the serving pod. "
                "Keep inference volumes separate from CPT.",
                title="Ask App Rag",
            )
            write_memory_store(
                temp,
                "pretraining/cpt-eval-stack-pin",
                "Run CPT C-eval with the pinned Unsloth stack. CPT is required next session.",
                title="CPT Eval Stack Pin",
            )
            write_memory_store(
                temp,
                "bugs/lora-frozen-embeddings",
                "Do not use LoRA on frozen embeddings. LoRA caused the tokenizer mismatch.",
                title="LoRA Frozen Embeddings",
            )
            write_memory_store(
                temp,
                "pretraining/cpt-s6-phase0",
                "Use LoRA for CPT S6 phase0. Keep LoRA rank at 16.",
                title="CPT S6 Phase0",
            )
            # Pad the store so CPT/LORA become generic vocabulary via IDF.
            for i in range(8):
                write_memory_store(
                    temp,
                    f"pretraining/wave-{i:02d}-notes",
                    f"Wave {i} CPT notes. LoRA training notes for CPT wave {i}.",
                    title=f"Wave {i} Notes",
                )
            hits = detect_contradictions(local_memory_dir(temp))
            polarity = [h for h in hits if h.kind == "polarity"]
            evidence = " ".join(h.evidence for h in polarity)
            self.assertNotIn("cpt", evidence)
            self.assertNotIn("lora", evidence)
            # bugs vs pretraining polarity must not fire even without IDF.
            crossed = [
                h
                for h in polarity
                if ("bugs/" in h.store_path_a) != ("bugs/" in h.store_path_b)
            ]
            self.assertEqual(crossed, [])

    def test_successive_handoff_numeric_clash_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "pretraining/cpt-corpus-v3-s2-handoff",
                "S2 handoff. Completed 2 waves. Loss 0.45. Next is S3.",
                title="S2 Handoff",
            )
            write_memory_store(
                temp,
                "pretraining/cpt-corpus-v3-s3-handoff",
                "S3 handoff. Completed 3 waves. Loss 0.32. Next is S4.",
                title="S3 Handoff",
            )
            hits = detect_contradictions(local_memory_dir(temp))
            numeric = [h for h in hits if h.kind == "numeric"]
            self.assertEqual(numeric, [])

    def test_pack_surface_caps_index_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/prd-0008-urnas-add-pos-calc",
                "PRD 0008 adds the column urnas_add_pos_calc after the tally.",
                title="PRD 0008 add urnas_add_pos_calc",
            )
            write_memory_store(
                temp,
                "decisions/prd-0009-reverse-urnas-add-pos-calc",
                "PRD 0009 reverses PRD 0008. Do not add urnas_add_pos_calc.",
                title="PRD 0009 reverses urnas_add_pos-calc",
            )
            result = dream(temp, mode="light", apply=True)
            self.assertTrue(result["changed"] or result["warnings"])
            index = Path(temp) / ".ai-memory" / "index.md"
            metadata, _ = parse_frontmatter(index.read_text(encoding="utf-8"))
            pack = metadata.get("contradictions") or []
            self.assertLessEqual(len(pack), 5)
            report = Path(temp) / ".ai-memory" / "evals" / "contradictions.json"
            self.assertTrue(report.exists())


class ContradictionNetTests(unittest.TestCase):
    def test_numeric_conflict_still_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/cache-policy",
                "The cache TTL for TaskMaster task lists is 3600 seconds. "
                "Cache TTL applies to every TaskMaster list query.",
                title="Cache Policy",
            )
            write_memory_store(
                temp,
                "architecture/decisions/taskmaster-caching",
                "The cache TTL for TaskMaster task lists is 60 seconds by default. "
                "Cache TTL applies to every TaskMaster list query.",
                title="TaskMaster Caching",
            )
            hits = detect_contradictions(local_memory_dir(temp))
            numeric = [h for h in hits if h.kind == "numeric"]
            self.assertTrue(numeric)
            joined = " ".join(h.message for h in numeric)
            self.assertIn("3600", joined)
            self.assertIn("60", joined)

    def test_prd_reversal_is_flagged(self) -> None:
        """Field case: urnas_add_pos_calc PRD 0008 vs PRD 0009."""
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/prd-0008-urnas-add-pos-calc",
                "PRD 0008 adds the column urnas_add_pos_calc so positions "
                "can be stored after calculation.",
                title="PRD 0008 add urnas_add_pos_calc",
            )
            write_memory_store(
                temp,
                "decisions/prd-0009-reverse-urnas-add-pos-calc",
                "PRD 0009 reverses PRD 0008. Do not add urnas_add_pos_calc; "
                "the column was withdrawn.",
                title="PRD 0009 reverses urnas_add_pos_calc",
            )
            hits = detect_contradictions(local_memory_dir(temp))
            kinds = {h.kind for h in hits}
            self.assertTrue({"reversal", "polarity"} & kinds, f"got {hits}")
            messages = " ".join(h.message for h in hits)
            self.assertIn("prd-0008", messages)
            self.assertIn("prd-0009", messages)

    def test_polarity_on_shared_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/adopt-drf",
                "We use Django REST Framework (DRF) for every public HTTP API.",
                title="Adopt DRF",
            )
            write_memory_store(
                temp,
                "decisions/no-django-rest-framework",
                "Do not use Django REST Framework (DRF). Prefer Django views.",
                title="No DRF",
            )
            hits = detect_contradictions(local_memory_dir(temp))
            polarity = [h for h in hits if h.kind == "polarity"]
            self.assertTrue(polarity, f"got {hits}")
            self.assertTrue(any("drf" in h.evidence.casefold() for h in polarity))

    def test_unrelated_files_are_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/http-timeouts",
                "External HTTP calls use a 30 second timeout with retries.",
                title="HTTP Timeouts",
            )
            write_memory_store(
                temp,
                "schemas/pagination",
                "List endpoints paginate responses at 50 items per page maximum.",
                title="Pagination",
            )
            hits = detect_contradictions(local_memory_dir(temp))
            self.assertEqual(hits, [])

    def test_dream_surfaces_reversal_without_picking_a_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/prd-0008-urnas-add-pos-calc",
                "PRD 0008 adds the column urnas_add_pos_calc after the tally.",
                title="PRD 0008 add urnas_add_pos_calc",
            )
            write_memory_store(
                temp,
                "decisions/prd-0009-reverse-urnas-add-pos-calc",
                "PRD 0009 reverses PRD 0008. Do not add urnas_add_pos_calc.",
                title="PRD 0009 reverses urnas_add_pos_calc",
            )
            result = dream(temp, mode="light", apply=True)
            hits = [w for w in result["warnings"] if "Contradiction detected" in w]
            self.assertTrue(hits, f"expected contradiction warning, got {result['warnings']}")
            eight = (
                Path(temp)
                / ".ai-memory"
                / "memory-store"
                / "decisions"
                / "prd-0008-urnas-add-pos-calc.md"
            )
            nine = (
                Path(temp)
                / ".ai-memory"
                / "memory-store"
                / "decisions"
                / "prd-0009-reverse-urnas-add-pos-calc.md"
            )
            self.assertTrue(eight.exists())
            self.assertTrue(nine.exists())

    def test_doctor_warns_on_live_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/prd-0008-urnas-add-pos-calc",
                "PRD 0008 adds the column urnas_add_pos_calc after the tally.",
                title="PRD 0008 add urnas_add_pos_calc",
            )
            write_memory_store(
                temp,
                "decisions/prd-0009-reverse-urnas-add-pos-calc",
                "PRD 0009 reverses PRD 0008. Do not add urnas_add_pos_calc.",
                title="PRD 0009 reverses urnas_add_pos-calc",
            )
            warnings = doctor(temp)["warnings"]
            self.assertTrue(
                any("Contradiction detected" in w for w in warnings),
                warnings,
            )


class ContradictionLlmTests(unittest.IsolatedAsyncioTestCase):
    async def test_enrichment_merges_llm_hits_and_survives_garbage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/cache-policy",
                "The cache TTL for TaskMaster task lists is 3600 seconds. "
                "Cache TTL applies to every TaskMaster list query.",
                title="Cache Policy",
            )
            write_memory_store(
                temp,
                "architecture/decisions/taskmaster-caching",
                "The cache TTL for TaskMaster task lists is 60 seconds by default. "
                "Cache TTL applies to every TaskMaster list query.",
                title="TaskMaster Caching",
            )
            existing = detect_contradiction_messages(local_memory_dir(temp))

            async def fake_llm(*_args: object, **_kwargs: object) -> str:
                return '{"contradictions": ["`a` and `b`: TTL clash"]}'

            merged = await enrich_contradictions_with_llm(local_memory_dir(temp), [], fake_llm)
            self.assertTrue(any("TTL clash" in item for item in merged))
            self.assertGreaterEqual(len(merged), 1)

            async def garbage_llm(*_args: object, **_kwargs: object) -> str:
                return "not-json at all"

            unchanged = await enrich_contradictions_with_llm(
                local_memory_dir(temp), existing, garbage_llm
            )
            self.assertEqual(unchanged, existing)
            empty_on_garbage = await enrich_contradictions_with_llm(
                local_memory_dir(temp), [], garbage_llm
            )
            self.assertEqual(empty_on_garbage, [])

    async def test_enrichment_uses_the_injected_callable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp,
                "decisions/cache-policy",
                "The cache TTL for TaskMaster task lists is 3600 seconds. "
                "Cache TTL applies to every TaskMaster list query.",
                title="Cache Policy",
            )
            write_memory_store(
                temp,
                "architecture/decisions/taskmaster-caching",
                "The cache TTL for TaskMaster task lists is 60 seconds by default. "
                "Cache TTL applies to every TaskMaster list query.",
                title="TaskMaster Caching",
            )
            spy = mock.AsyncMock(return_value='{"contradictions": []}')
            existing = detect_contradiction_messages(local_memory_dir(temp))
            await enrich_contradictions_with_llm(local_memory_dir(temp), [], spy)
            # Overlapping pair exists and is not in existing_messages, so the
            # dedicated LLM pass should fire.
            spy.assert_awaited()
            await enrich_contradictions_with_llm(local_memory_dir(temp), existing, spy)
            # Both paths already named in existing_messages → skip the extra call.
            self.assertEqual(spy.await_count, 1)


if __name__ == "__main__":
    unittest.main()
