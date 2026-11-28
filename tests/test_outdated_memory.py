"""Field cases for outdated-memory handling (age is not truth)."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.storage import (
    context_for_task,
    initialize_memory_fabric,
    read_memory_store,
    write_memory_store,
    write_session_journal,
)
from memory_fabric.storage import dream as _async_dream
from memory_fabric.storage.close import (
    can_close,
    can_close_by_valid_time,
    clear_age_only_stale_on_standing,
    live_posture_body,
)
from memory_fabric.storage.contradictions import Contradiction
from memory_fabric.storage.ranking import blended_score
from memory_fabric.storage.review import promote_review, queue_contradiction_reviews


def dream(*args, **kwargs):
    return asyncio.run(_async_dream(*args, **kwargs))


def _write_store(
    temp: str,
    store_path: str,
    body: str,
    *,
    priority: str = "high",
    last_updated: str = "2026-08-15T00:00:00-03:00",
    review_status: str | None = None,
    superseded_by: str | None = None,
    valid_from: str | None = None,
    role: str | None = None,
    title: str | None = None,
) -> Path:
    root = Path(temp) / ".ai-memory" / "memory-store"
    parts = store_path.split("/")
    dest = root.joinpath(*parts[:-1])
    dest.mkdir(parents=True, exist_ok=True)
    display = title or parts[-1].replace("-", " ").title()
    metadata: dict = {
        "store_path": store_path,
        "title": display,
        "summary": f"{display} — standing memory.",
        "priority": priority,
        "tags": ["test"],
        "schema_version": "1.3",
        "last_updated": last_updated,
    }
    if review_status:
        metadata["review_status"] = review_status
    if superseded_by:
        metadata["superseded_by"] = superseded_by
    if valid_from:
        metadata["valid_from"] = valid_from
    if role:
        metadata["role"] = role
    path = dest / f"{parts[-1]}.md"
    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
    return path


class OutdatedMemoryFieldTests(unittest.TestCase):
    def test_old_lab_only_decision_still_packs(self) -> None:
        """tcc lab-only rule, 94 days untouched, still in a current pack."""
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store(
                temp,
                "decisions/lab-only-sem-prontuario",
                ("# Lab-only\n\nStudy uses lab reports only. Chart review is forbidden.\n"),
                last_updated="2026-08-15T12:00:00-03:00",
            )
            pack = context_for_task(
                temp,
                "lab reports chart review prontuario study constraint",
                max_tokens=3000,
            )
            self.assertIn("store/decisions/lab-only-sem-prontuario", pack["included_sections"])
            self.assertIn("Chart review is forbidden", pack["text"])
            score = blended_score(
                1.0,
                "high",
                "2026-08-15T12:00:00-03:00",
                key="store/decisions/lab-only-sem-prontuario",
                query_present=True,
                review_status="stale",
                role="decisions",
            )
            self.assertGreater(score, 0.0)

    def test_age_only_stale_clear_restores_phaser_decision(self) -> None:
        """GamePilgrim phaser4-migration returns after age-only stale clear."""
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            path = _write_store(
                temp,
                "architecture/decisions/phaser4-migration",
                "# Phaser 4\n\nRenderer is Phaser 4. Keep using it.\n",
                last_updated="2026-07-10T00:00:00-03:00",
                review_status="stale",
            )
            memory_root = Path(temp) / ".ai-memory"
            cleared = clear_age_only_stale_on_standing(memory_root)
            self.assertTrue(
                any("phaser4-migration" in c for c in cleared),
                cleared,
            )
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertNotIn("review_status", meta)
            self.assertIn("Phaser 4", body)
            pack = context_for_task(temp, "phaser renderer migration", max_tokens=3000)
            self.assertIn(
                "store/architecture/decisions/phaser4-migration",
                pack["included_sections"],
            )

    def test_debt_stays_until_named_close_then_shows_successor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store(
                temp,
                "debt/read-path-retrieval-defects",
                "# Defects\n\nv1.2.0 retrieval bugs still open.\n",
                last_updated="2026-08-15T00:00:00-03:00",
            )
            pack = context_for_task(temp, "read-path retrieval defects v1.2.0", max_tokens=3000)
            self.assertIn("store/debt/read-path-retrieval-defects", pack["included_sections"])

            result = write_memory_store(
                temp,
                "architecture/decisions/read-path-fixed",
                (
                    "supersedes: debt/read-path-retrieval-defects\n\n"
                    "Read-path defects from v1.2.0 are fixed.\n"
                ),
                title="Read Path Fixed",
                priority="high",
            )
            self.assertTrue(
                any("Closed `debt/read-path-retrieval-defects`" in w for w in result["warnings"])
            )
            closed = read_memory_store(temp, "debt/read-path-retrieval-defects")
            self.assertIn("Closed by `architecture/decisions/read-path-fixed`", closed["text"])
            self.assertEqual(
                closed["metadata"].get("superseded_by"),
                "architecture/decisions/read-path-fixed",
            )
            self.assertIn(closed["metadata"].get("close_kind"), {"update", "revision"})
            self.assertTrue(str(closed["metadata"].get("closed_at") or "").strip())

            pack2 = context_for_task(temp, "read-path retrieval defects v1.2.0", max_tokens=3000)
            text2 = pack2["text"]
            self.assertIn(
                "`store/debt/read-path-retrieval-defects` closed by "
                "`architecture/decisions/read-path-fixed`",
                text2,
            )
            self.assertIn("store/debt/read-path-retrieval-defects", pack2["included_sections"])

    def test_posture_packs_live_slice_only(self) -> None:
        body = (
            "## Standing\n\n"
            "Do not rent GPU until probe passes.\n\n"
            "## 2026-10-31\n\n"
            "Next: fine-tuning/next-session-rag-refusal\n"
            "OT chase frozen.\n\n"
            "## 2026-11-12\n\n"
            "Next: fine-tuning/next-session-ot-finetune\n"
            "Chase freeze lifted.\n\n"
            "## 2026-11-13\n\n"
            "Next: fine-tuning/next-session-ot-probe-ooc-candidates\n"
        )
        packed, keep = live_posture_body(body)
        self.assertIn("2026-11-13", packed)
        self.assertIn("Do not rent GPU until probe passes", packed)
        self.assertNotIn("next-session-rag-refusal", packed)
        self.assertNotIn("next-session-ot-finetune", packed)
        self.assertIn("fine-tuning/next-session-ot-probe-ooc-candidates", keep)

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store(
                temp,
                "fine-tuning/current-posture-2026-10-31",
                body,
                last_updated="2026-11-16T00:00:00-03:00",
                role="posture",
            )
            _write_store(
                temp,
                "fine-tuning/next-session-ot-probe-ooc-candidates",
                "Live OT probe next step.\n",
                last_updated="2026-11-13T00:00:00-03:00",
            )
            _write_store(
                temp,
                "fine-tuning/next-session-rag-refusal",
                "Old RAG refusal handoff.\n",
                last_updated="2026-10-31T00:00:00-03:00",
            )
            write_memory_store(
                temp,
                "fine-tuning/current-posture-2026-10-31",
                body,
                title="Current Posture",
                priority="high",
                mode="replace",
            )
            rag = (
                Path(temp)
                / ".ai-memory"
                / "memory-store"
                / "fine-tuning"
                / "next-session-rag-refusal.md"
            )
            rag_meta, _ = parse_frontmatter(rag.read_text(encoding="utf-8"))
            self.assertEqual(
                rag_meta.get("superseded_by"),
                "fine-tuning/current-posture-2026-10-31",
            )
            probe = (
                Path(temp)
                / ".ai-memory"
                / "memory-store"
                / "fine-tuning"
                / "next-session-ot-probe-ooc-candidates.md"
            )
            probe_meta, _ = parse_frontmatter(probe.read_text(encoding="utf-8"))
            self.assertFalse(str(probe_meta.get("superseded_by") or "").strip())

    def test_journal_cannot_close_standing_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            decision = _write_store(
                temp,
                "decisions/lab-only-sem-prontuario",
                "Lab reports only. No chart review.\n",
                last_updated="2026-08-15T00:00:00-03:00",
            )
            result = write_memory_store(
                temp,
                "episodic/2026-11-18-lab-override",
                (
                    "supersedes: decisions/lab-only-sem-prontuario\n\n"
                    "Today we decided chart review is fine after all.\n"
                ),
                title="Lab Override Journal",
                priority="medium",
            )
            self.assertTrue(
                any("Refused to close" in w and "less entrenched" in w for w in result["warnings"]),
                result["warnings"],
            )
            meta, _ = parse_frontmatter(decision.read_text(encoding="utf-8"))
            self.assertFalse(str(meta.get("superseded_by") or "").strip())

            # Session journal path is also history and cannot close.
            write_session_journal(
                temp,
                summary="Tried to overturn lab-only via journal.",
                key_decisions=["supersedes: decisions/lab-only-sem-prontuario"],
            )

    def test_backfilled_earlier_valid_from_cannot_close_later_decision(self) -> None:
        writer = {
            "valid_from": "2026-01-01T00:00:00-03:00",
            "last_updated": "2026-11-18T00:00:00-03:00",
        }
        target = {
            "valid_from": "2026-08-15T00:00:00-03:00",
            "last_updated": "2026-08-15T00:00:00-03:00",
        }
        self.assertFalse(can_close_by_valid_time(writer, target))
        self.assertTrue(can_close("decisions", "decisions"))
        self.assertFalse(can_close("episodic", "decisions"))

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            decision = _write_store(
                temp,
                "decisions/later-rule",
                "Later standing rule.\n",
                last_updated="2026-08-15T00:00:00-03:00",
                valid_from="2026-08-15T00:00:00-03:00",
            )
            result = write_memory_store(
                temp,
                "decisions/backfill-note",
                (
                    "---\n"
                    'valid_from: "2026-01-01T00:00:00-03:00"\n'
                    "supersedes: decisions/later-rule\n"
                    "---\n\n"
                    "Backfilled earlier belief.\n"
                ),
                title="Backfill",
                priority="high",
            )
            self.assertTrue(
                any(
                    "valid_from` is earlier" in w or "valid_from is earlier" in w
                    for w in result["warnings"]
                ),
                result["warnings"],
            )
            meta, _ = parse_frontmatter(decision.read_text(encoding="utf-8"))
            self.assertFalse(str(meta.get("superseded_by") or "").strip())

    def test_dream_clears_age_only_stale_on_standing_and_skips_steering_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            path = _write_store(
                temp,
                "architecture/decisions/phaser4-migration",
                "Phaser 4 is current.\n",
                last_updated="2026-07-10T00:00:00-03:00",
                review_status="stale",
            )
            rules = Path(temp) / ".ai-memory" / "framework-rules.md"
            rmeta, rbody = parse_frontmatter(rules.read_text(encoding="utf-8"))
            rmeta["last_updated"] = "2020-01-01T00:00:00-03:00"
            rmeta["review_status"] = "stale"
            rules.write_text(dump_frontmatter(rmeta, rbody), encoding="utf-8")

            result = dream(temp, apply=True, mode="light")
            self.assertTrue(
                any("Cleared age-only stale" in w for w in result["warnings"]),
                result["warnings"],
            )
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertNotIn("review_status", meta)
            new_rules, _ = parse_frontmatter(rules.read_text(encoding="utf-8"))
            self.assertNotEqual(new_rules.get("review_status"), "stale")

    def test_promote_contradiction_review_writes_superseded_by(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store(
                temp,
                "decisions/old-auth",
                "Use sessions.\n",
                last_updated="2026-06-01T00:00:00-03:00",
            )
            _write_store(
                temp,
                "decisions/new-auth",
                "Use JWT.\n",
                last_updated="2026-11-01T00:00:00-03:00",
            )
            hit = Contradiction(
                store_path_a="decisions/old-auth",
                store_path_b="decisions/new-auth",
                kind="replacement",
                message="old-auth replaced by new-auth",
                evidence="decisions/new-auth",
            )
            queued = queue_contradiction_reviews(temp, [hit])
            self.assertEqual(len(queued), 1)
            promoted = promote_review(temp, queued[0], "")
            self.assertEqual(promoted["action"], "promote-close")
            old = read_memory_store(temp, "decisions/old-auth")
            self.assertEqual(old["metadata"].get("superseded_by"), "decisions/new-auth")

    def test_episodic_omitted_from_no_query_constraint_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            _write_store(
                temp,
                "episodic/2026-11-18-note",
                "We discussed JWT and sessions today.\n",
                priority="medium",
                last_updated="2026-11-18T00:00:00-03:00",
            )
            _write_store(
                temp,
                "decisions/auth-choice",
                "Use JWT for auth.\n",
                last_updated="2026-08-01T00:00:00-03:00",
            )
            from memory_fabric.storage import read_combined_context

            pack = read_combined_context(temp, max_tokens=4000)
            self.assertNotIn("store/episodic/2026-11-18-note", pack["included_sections"])


if __name__ == "__main__":
    unittest.main()
