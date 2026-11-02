"""Synthetic field-diary pack and analyze tests. No real user queries."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.cli import main
from memory_fabric.diary import analyze_diary, approve, build_pack, status
from memory_fabric.diary.consent import diary_dir, field_packs_dir, invalidate_cache
from memory_fabric.storage import initialize_memory_fabric, write_memory_store


class _DiaryHome(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name).resolve()
        self.home = tmp / "mf-home"
        self.home.mkdir()
        self.project = tmp / "project"
        self.project.mkdir()
        self._env = mock.patch.dict(
            os.environ,
            {"MEMORY_FABRIC_HOME": str(self.home)},
            clear=False,
        )
        self._env.start()
        os.environ.pop("MEMORY_FABRIC_DIARY", None)
        invalidate_cache()

    def tearDown(self) -> None:
        invalidate_cache()
        self._env.stop()
        self._tmp.cleanup()

    def _write_events(self, lines: list[dict], *, name: str = "events-2026-09-01.jsonl") -> Path:
        root = diary_dir()
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in lines),
            encoding="utf-8",
        )
        return path


def _base_envelope(project_id: str, event: str, ts: str = "2026-09-01T12:00:00Z") -> dict:
    return {
        "schema_version": 1,
        "ts": ts,
        "fabric_version": "1.4.4",
        "install_kind": "pip",
        "surface": "core",
        "client": "cli",
        "project_id": project_id,
        "os": "Windows",
        "python": "3.12.0",
        "event": event,
    }


def _healthy_pack_events(project_id: str = "aaaaaaaaaaaaaaaa") -> list[dict]:
    events: list[dict] = []
    for i in range(6):
        events.append(
            {
                **_base_envelope(project_id, "context.pack", f"2026-09-01T12:0{i}:00Z"),
                "token_budget": 4000,
                "estimated_tokens": 2000,
                "budget_fit": True,
                "startup_mode": "maps",
                "index_used": True,
                "query_present": False,
                "query_len": 0,
                "tokens_by_role": {"steering": 800, "map": 1200},
                "included_by_role": {"steering": 2, "map": 4},
                "omitted_by_role": {"episodic": 2},
                "included_by_priority": {"high": 3, "medium": 3},
                "omitted_by_priority": {"high": 2, "low": 4},
                "largest_included_tokens": 400,
                "largest_included_role": "steering",
                "truncated_n": 0,
                "warning_codes": [],
                "posture_slot": "included",
            }
        )
    for i in range(6):
        events.append(
            {
                **_base_envelope(project_id, "context.pack", f"2026-09-02T12:0{i}:00Z"),
                "token_budget": 4000,
                "estimated_tokens": 2500,
                "budget_fit": True,
                "startup_mode": "full",
                "index_used": True,
                "query_present": True,
                "query_len": 12,
                "tokens_by_role": {"steering": 800, "decisions": 1700},
                "included_by_role": {"steering": 2, "decisions": 3},
                "omitted_by_role": {"debt": 1},
                "included_by_priority": {"high": 4, "medium": 1},
                "omitted_by_priority": {"high": 1, "low": 2},
                "largest_included_tokens": 500,
                "largest_included_role": "decisions",
                "truncated_n": 0,
                "warning_codes": [],
                "posture_slot": "included",
            }
        )
    for i in range(12):
        events.append(
            {
                **_base_envelope(project_id, "tool.call", f"2026-09-01T13:0{i % 10}:00Z"),
                "name": "read_combined_context_tool",
                "ms": 10.0,
                "ok": True,
            }
        )
    return events


def _failing_pack_events(project_id: str = "bbbbbbbbbbbbbbbb") -> list[dict]:
    events: list[dict] = []
    for i in range(6):
        events.append(
            {
                **_base_envelope(project_id, "context.pack", f"2026-09-10T12:0{i}:00Z"),
                "token_budget": 4000,
                "estimated_tokens": 3900,
                "budget_fit": True,
                "startup_mode": "full",
                "index_used": True,
                "query_present": True,
                "query_len": 20,
                "tokens_by_role": {"steering": 2500, "map": 1400},
                "included_by_role": {"steering": 2, "map": 2},
                "omitted_by_role": {"decisions": 10},
                "included_by_priority": {"high": 2, "medium": 2},
                "omitted_by_priority": {"high": 20, "low": 1},
                "largest_included_tokens": 1200,
                "largest_included_role": "steering",
                "truncated_n": 1,
                "warning_codes": ["file_share_capped"],
                "posture_slot": "omitted",
                "query": "synthetic failing query",
            }
        )
    for i in range(12):
        events.append(
            {
                **_base_envelope(project_id, "tool.call", f"2026-09-10T13:0{i % 10}:00Z"),
                "name": "dream_tool",
                "ms": 5.0,
                "ok": False,
                "error_type": "RuntimeError",
            }
        )
    return events


class DiaryPackTests(_DiaryHome):
    def test_pack_writes_folder_and_redacts(self) -> None:
        self._write_events(
            [
                {
                    **_base_envelope("proj111111111111", "context.pack"),
                    "token_budget": 4000,
                    "estimated_tokens": 100,
                    "budget_fit": True,
                    "startup_mode": "maps",
                    "index_used": False,
                    "query_present": True,
                    "query_len": 40,
                    "tokens_by_role": {"steering": 50},
                    "included_by_role": {"steering": 1},
                    "omitted_by_role": {},
                    "included_by_priority": {"medium": 1},
                    "omitted_by_priority": {},
                    "largest_included_tokens": 50,
                    "largest_included_role": "steering",
                    "truncated_n": 0,
                    "warning_codes": [],
                    "posture_slot": "absent",
                    "query": r"look at C:\secret\proj and sk-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6",
                    "body": "MUST NOT APPEAR",
                    "cwd": r"C:\secret\proj",
                },
                {
                    **_base_envelope("proj222222222222", "search.run", "2026-08-01T12:00:00Z"),
                    "backend": "python",
                    "hit_n": 0,
                    "ms": 1.0,
                    "query_len": 3,
                    "token_n": 1,
                    "content_token_n": 1,
                    "candidate_n": 0,
                    "phrase_hit": False,
                    "top_hit_role": None,
                    "top_hit_score": None,
                },
            ]
        )
        out = self.home / "custom-pack"
        result = build_pack(from_date="2026-09-01", to_date="2026-09-30", out=out)
        self.assertEqual(result["event_n"], 1)
        self.assertTrue((out / "manifest.json").is_file())
        self.assertTrue((out / "events.jsonl").is_file())
        self.assertTrue((out / "summary.json").is_file())
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["queries_included"])
        self.assertEqual(manifest["project_n"], 1)
        line = (out / "events.jsonl").read_text(encoding="utf-8").strip()
        event = json.loads(line)
        self.assertNotIn("body", event)
        self.assertNotIn("cwd", event)
        self.assertIn("[REDACTED_SECRET]", event["query"])
        self.assertIn("[path]", event["query"])
        self.assertNotIn("sk-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6", event["query"])
        self.assertNotIn(r"C:\secret\proj", event["query"])

    def test_pack_default_out_and_status_last_pack(self) -> None:
        self._write_events(_healthy_pack_events())
        result = build_pack()
        out = Path(result["path"])
        self.assertTrue(out.name.startswith("field-"))
        self.assertEqual(out.parent, field_packs_dir())
        info = status()
        self.assertEqual(info["last_pack"], out.name)

    def test_pack_cli(self) -> None:
        self._write_events(_healthy_pack_events())
        out = self.home / "cli-pack"
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            code = main(
                [
                    "--cwd",
                    str(self.project),
                    "--json",
                    "diary",
                    "pack",
                    "--out",
                    str(out),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertGreater(payload["event_n"], 0)
        self.assertTrue((out / "events.jsonl").is_file())


class DiaryAnalyzeTests(_DiaryHome):
    def test_analyze_healthy_exits_ok(self) -> None:
        self._write_events(_healthy_pack_events("aaaaaaaaaaaaaaaa"))
        packed = build_pack(out=self.home / "healthy-pack")
        report = analyze_diary(pack=packed["path"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["project_n"], 1)
        project = report["projects"]["aaaaaaaaaaaaaaaa"]
        self.assertFalse(project["failed"])
        self.assertFalse(project["signals"]["top_queries"]["present"])

    def test_analyze_failing_exits_nonzero(self) -> None:
        self._write_events(_failing_pack_events("bbbbbbbbbbbbbbbb"))
        packed = build_pack(out=self.home / "fail-pack")
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            code = main(
                [
                    "--cwd",
                    str(self.project),
                    "--json",
                    "diary",
                    "analyze",
                    "--pack",
                    packed["path"],
                ]
            )
        self.assertEqual(code, 1)
        report = json.loads(stdout.getvalue())
        self.assertFalse(report["ok"])
        project = report["projects"]["bbbbbbbbbbbbbbbb"]
        self.assertTrue(project["failed"])
        joined = " ".join(project["failures"])
        self.assertIn("posture_slot", joined)
        self.assertIn("steering", joined)
        self.assertIn("priority", joined)
        self.assertIn("tool.call", joined)
        self.assertTrue(project["signals"]["top_queries"]["present"])

    def test_missing_posture_slot_does_not_fail(self) -> None:
        events = _healthy_pack_events("cccccccccccccccc")
        for event in events:
            event.pop("posture_slot", None)
        self._write_events(events)
        report = analyze_diary(diary=diary_dir())
        self.assertTrue(report["ok"])
        posture = report["projects"]["cccccccccccccccc"]["signals"]["posture_slot"]
        self.assertEqual(posture["cohorts"]["no_query"]["n"], 0)
        self.assertFalse(posture["failed"])

    def test_two_projects_independent(self) -> None:
        self._write_events(_healthy_pack_events("aaaaaaaaaaaaaaaa") + _failing_pack_events())
        report = analyze_diary(diary=diary_dir())
        self.assertFalse(report["ok"])
        self.assertFalse(report["projects"]["aaaaaaaaaaaaaaaa"]["failed"])
        self.assertTrue(report["projects"]["bbbbbbbbbbbbbbbb"]["failed"])


class PostureSlotRecordingTests(_DiaryHome):
    def test_current_posture_records_included_without_store_path(self) -> None:
        from memory_fabric.storage import read_combined_context

        initialize_memory_fabric(str(self.project))
        write_memory_store(
            str(self.project),
            store_path="notes/current-posture",
            content="Live posture for the diary pack test.\n",
            title="Current posture",
            priority="medium",
            tags=["posture"],
        )
        # role: posture via frontmatter — write_memory_store may not set role;
        # path stem current-posture is enough for is_posture_path.
        approve("counts", confirmed=True)
        read_combined_context(str(self.project), query="current posture")
        rows = []
        for path in diary_dir().glob("events-*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        packs = [e for e in rows if e.get("event") == "context.pack"]
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0]["posture_slot"], "included")
        payload = json.dumps(packs[0])
        self.assertNotIn("store/", payload)
        self.assertNotIn("current-posture", payload)


if __name__ == "__main__":
    unittest.main()
