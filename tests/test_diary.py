"""Local field diary: default off, human approve, no network, HOME override."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.cli import main
from memory_fabric.diary import (
    approve,
    is_approved,
    is_muted,
    mute,
    read_consent,
    record,
    revoke,
    status,
    unmute,
    wipe,
)
from memory_fabric.diary.consent import consent_path, diary_dir, invalidate_cache
from memory_fabric.storage import initialize_memory_fabric


class _DiaryHome(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # Resolve first: macOS /var → /private/var, Windows 8.3 RUNNER~1 →
        # runneradmin. get_global_root() also resolve()s MEMORY_FABRIC_HOME.
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


class DiaryConsentTests(_DiaryHome):
    def test_default_is_not_approved(self) -> None:
        self.assertFalse(is_approved())
        self.assertIsNone(read_consent())
        self.assertFalse(consent_path().exists())

    def test_approve_without_confirm_writes_nothing(self) -> None:
        result = approve("counts", confirmed=False)
        self.assertFalse(result["changed"])
        self.assertFalse(result["approved"])
        self.assertFalse(consent_path().exists())
        self.assertFalse(is_approved())

    def test_approve_writes_diary_json_under_home(self) -> None:
        result = approve("counts", confirmed=True)
        self.assertTrue(result["changed"])
        self.assertTrue(result["approved"])
        self.assertTrue(consent_path().exists())
        self.assertTrue(consent_path().resolve().is_relative_to(self.home.resolve()))
        data = json.loads(consent_path().read_text(encoding="utf-8"))
        self.assertTrue(data["approved"])
        self.assertEqual(data["level"], "counts")
        self.assertEqual(data["scope"], "local-copy-only")
        self.assertTrue(is_approved())

    def test_approve_counts_plus_queries(self) -> None:
        approve("counts+queries", confirmed=True)
        self.assertEqual(read_consent()["level"], "counts+queries")

    def test_approve_rejects_unknown_level(self) -> None:
        with self.assertRaises(ValueError):
            approve("metrics", confirmed=True)

    def test_revoke_stops_recording_keeps_file(self) -> None:
        approve("counts", confirmed=True)
        record({"event": "tool.call", "name": "status"}, cwd=str(self.project))
        self.assertTrue(any(diary_dir().glob("events-*.jsonl")))
        result = revoke()
        self.assertTrue(result["changed"])
        self.assertFalse(is_approved())
        self.assertTrue(consent_path().exists())
        self.assertTrue(any(diary_dir().glob("events-*.jsonl")))

    def test_kill_switch_overrides_approval(self) -> None:
        approve("counts", confirmed=True)
        self.assertTrue(is_approved())
        with mock.patch.dict(os.environ, {"MEMORY_FABRIC_DIARY": "0"}):
            self.assertFalse(is_approved())
        self.assertTrue(is_approved())

    def test_env_one_does_not_approve(self) -> None:
        with mock.patch.dict(os.environ, {"MEMORY_FABRIC_DIARY": "1"}):
            self.assertFalse(is_approved())

    def test_mute_silences_one_project(self) -> None:
        initialize_memory_fabric(str(self.project))
        approve("counts", confirmed=True)
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        initialize_memory_fabric(str(other))
        muted = mute(str(self.project))
        self.assertTrue(muted["changed"])
        self.assertTrue(is_muted(str(self.project)))
        self.assertFalse(is_approved(str(self.project)))
        self.assertTrue(is_approved(str(other)))
        unmute(str(self.project))
        self.assertTrue(is_approved(str(self.project)))

    def test_mute_without_init_does_not_create_memory_dir(self) -> None:
        result = mute(str(self.project))
        self.assertFalse(result["changed"])
        self.assertFalse((self.project / ".ai-memory").exists())

    def test_wipe_requires_confirm(self) -> None:
        approve("counts", confirmed=True)
        result = wipe(confirmed=False)
        self.assertFalse(result["changed"])
        self.assertTrue(consent_path().exists())

    def test_wipe_deletes_diary_and_consent(self) -> None:
        approve("counts", confirmed=True)
        record({"event": "tool.call", "name": "status"}, cwd=str(self.project))
        result = wipe(confirmed=True)
        self.assertTrue(result["changed"])
        self.assertFalse(consent_path().exists())
        self.assertFalse(diary_dir().exists())
        self.assertFalse(is_approved())

    def test_status_reports_off_by_default(self) -> None:
        result = status(str(self.project))
        self.assertFalse(result["approved"])
        self.assertFalse(result["kill_switch"])
        self.assertEqual(result["events_today"], 0)
        self.assertTrue(Path(result["consent_path"]).resolve().is_relative_to(self.home.resolve()))


class DiaryRecorderTests(_DiaryHome):
    def test_record_is_noop_when_off(self) -> None:
        record({"event": "tool.call", "name": "status"}, cwd=str(self.project))
        self.assertFalse(diary_dir().exists())

    def test_record_appends_jsonl_when_approved(self) -> None:
        approve("counts", confirmed=True)
        record({"event": "tool.call", "name": "status"}, cwd=str(self.project))
        files = list(diary_dir().glob("events-*.jsonl"))
        self.assertEqual(len(files), 1)
        line = files[0].read_text(encoding="utf-8").strip()
        payload = json.loads(line)
        self.assertEqual(payload["event"], "tool.call")
        self.assertEqual(payload["name"], "status")
        self.assertIn("ts", payload)

    def test_record_fail_open_on_write_error(self) -> None:
        approve("counts", confirmed=True)
        with mock.patch(
            "memory_fabric.diary.recorder._append",
            side_effect=OSError("disk full"),
        ):
            record({"event": "tool.call", "name": "status"}, cwd=str(self.project))


class DiaryCliTests(_DiaryHome):
    def test_status_cli(self) -> None:
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            code = main(["--cwd", str(self.project), "diary", "status", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["approved"])

    def test_approve_without_yes_refuses_when_not_a_tty(self) -> None:
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            code = main(["--cwd", str(self.project), "--json", "diary", "approve"])
        self.assertEqual(code, 1)
        self.assertFalse(is_approved())

    def test_approve_yes_writes_consent(self) -> None:
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            code = main(["--cwd", str(self.project), "--json", "diary", "approve", "--yes"])
        self.assertEqual(code, 0)
        self.assertTrue(is_approved())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["approved"])
        self.assertIn("Nothing will be sent", payload["message"])

    def test_revoke_cli(self) -> None:
        main(["--cwd", str(self.project), "diary", "approve", "--yes"])
        code = main(["--cwd", str(self.project), "--json", "diary", "revoke"])
        self.assertEqual(code, 0)
        self.assertFalse(is_approved())


class RoleClassifierTests(unittest.TestCase):
    def test_known_keys(self) -> None:
        from memory_fabric.diary.roles import classify_role

        self.assertEqual(classify_role("store/episodic/2026-08-18.md"), "episodic")
        self.assertEqual(classify_role("store/episodic/commits/2026-08-18/abc"), "episodic_commit")
        self.assertEqual(classify_role("local/architecture"), "map")
        self.assertEqual(classify_role("store/architecture/overview"), "architecture")
        self.assertEqual(classify_role("local/framework-rules"), "steering")
        self.assertEqual(classify_role("global/directives"), "tier0")
        self.assertEqual(classify_role("store/failures/lock-timeout"), "failure")


class PackStatsRecordingTests(_DiaryHome):
    def _events(self) -> list[dict]:
        files = list(diary_dir().glob("events-*.jsonl"))
        rows: list[dict] = []
        for path in files:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def test_packer_records_roles_when_approved(self) -> None:
        from memory_fabric.storage import read_combined_context

        initialize_memory_fabric(str(self.project))
        approve("counts", confirmed=True)
        bundle = read_combined_context(str(self.project))
        stats = bundle["pack_stats"]
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertIn("budget_fit", stats)
        self.assertLessEqual(stats["estimated_tokens"], stats["token_budget"])
        self.assertIn("map", stats["included_by_role"])
        events = [e for e in self._events() if e.get("event") == "context.pack"]
        self.assertEqual(len(events), 1)
        payload = json.dumps(events[0])
        self.assertNotIn("store/", payload)
        self.assertNotIn(str(self.project), payload)
        self.assertNotIn("query", events[0])

    def test_packer_writes_nothing_when_off(self) -> None:
        from memory_fabric.storage import read_combined_context

        initialize_memory_fabric(str(self.project))
        read_combined_context(str(self.project))
        self.assertFalse(any(diary_dir().glob("events-*.jsonl")))

    def test_counts_plus_queries_redacts_secret(self) -> None:
        from memory_fabric.storage import keyword_search

        initialize_memory_fabric(str(self.project))
        approve("counts+queries", confirmed=True)
        keyword_search(str(self.project), "sk-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6")
        events = [e for e in self._events() if e.get("event") == "search.run"]
        self.assertEqual(len(events), 1)
        self.assertIn("[REDACTED_SECRET]", events[0]["query"])
        self.assertNotIn("sk-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6", events[0]["query"])

    def test_checkpoint_cli_when_approved(self) -> None:
        initialize_memory_fabric(str(self.project))
        approve("counts", confirmed=True)
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            code = main(["--cwd", str(self.project), "--json", "diary", "checkpoint"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["recorded"])
        events = [e for e in self._events() if e.get("event") == "checkpoint.manual"]
        self.assertEqual(len(events), 1)
        self.assertNotIn(str(self.project), json.dumps(events[0]))

    def test_status_includes_diary_block(self) -> None:
        from memory_fabric.storage import status as fabric_status

        initialize_memory_fabric(str(self.project))
        approve("counts", confirmed=True)
        result = fabric_status(str(self.project))
        self.assertTrue(result["diary"]["approved"])
        self.assertEqual(result["diary"]["level"], "counts")
