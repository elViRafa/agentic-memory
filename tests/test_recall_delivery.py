from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from memory_fabric.cli import main
from memory_fabric.eval._recall_fixture import RECALL_STEERING, populate_recall_fixture
from memory_fabric.frontmatter import dump_frontmatter
from memory_fabric.paths import memory_store_dir
from memory_fabric.storage import context_for_task, initialize_memory_fabric, keyword_search
from memory_fabric.storage._shared import estimate_tokens
from memory_fabric.storage.semantic import set_embedder

_MARKER = re.compile(r"^<!-- memory-fabric:([^ ]+) -->$", re.MULTILINE)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("MEMORY_FABRIC_HOME", str(tmp_path / "empty-home"))
    cwd = str(tmp_path / "project")
    Path(cwd).mkdir()
    initialize_memory_fabric(cwd, memory_prompt=RECALL_STEERING)
    return cwd


def _note(cwd: str, key: str, body: str, **metadata: str) -> Path:
    path = (memory_store_dir(cwd) / key).with_suffix(".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontmatter({"store_path": key, **metadata}, body), encoding="utf-8")
    return path


@pytest.mark.parametrize("backend", ["index", "python"])
def test_recall_status_and_passage(
    project: str, backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if backend == "python":
        monkeypatch.setattr("memory_fabric.storage.index.sync_index", lambda cwd: None)
        monkeypatch.setattr("shutil.which", lambda command: None)
    populate_recall_fixture(project)

    query = "Where should we restart after COMPACTOR_OFFSET_MISMATCH?"
    pack = context_for_task(project, query, max_tokens=1200)
    assert pack["retrieval_status"] == "matched"
    assert pack["estimated_tokens"] <= 1200
    assert RECALL_STEERING in pack["text"]
    assert "Resume from the last committed segment boundary." in pack["text"]
    assert "Record the time and result of each maintenance check." not in pack["text"]
    hit = keyword_search(project, query)[0]
    assert hit["backend"] == backend
    assert "Resume from the last committed segment boundary." in hit["snippet"]
    assert f"Source: `store/architecture/compactor-runbook`, line {hit['line']}." in pack["text"]
    assert (
        "COMPACTOR_OFFSET_MISMATCH"
        in Path(hit["path"]).read_text(encoding="utf-8").splitlines()[hit["line"] - 1]
    )

    for query in (
        "Should we restart after QZX_RECALL_FIXTURE_9047?",
        "Which kiln temperature was approved for porcelain glazing?",
        "Qual temperatura foi aprovada para a queima de porcelana?",
        "May I proceed?",
    ):
        miss = context_for_task(project, query)
        assert miss["retrieval_status"] == "no_match"
        assert _MARKER.findall(miss["text"]) == miss["included_sections"]
        assert all(key.startswith("local/") for key in miss["included_sections"])
        assert RECALL_STEERING in miss["text"]
        assert keyword_search(project, query) == []

    _note(project, "failures/unrelated-reader", "In tests/frame_reader.py, retry immediately.")
    opened = context_for_task(project, "May I proceed?", files_open=[r"src\frame_reader.py"])
    assert opened["retrieval_status"] == "matched"
    assert "reject the frame before allocating the payload buffer" in opened["text"]
    assert "store/failures/unrelated-reader" not in opened["included_sections"]


@pytest.mark.parametrize("indexed", [True, False])
def test_lifecycle_is_applied_before_current_guidance(
    project: str, indexed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not indexed:
        monkeypatch.setattr("memory_fabric.storage.index.sync_index", lambda cwd: None)
    query = "HARBOR_ROUTE_92"
    historical = "failures/old-route"
    broken = "failures/broken-route"
    closed = "decisions/original-route"
    current = "decisions/current-route"
    _note(
        project,
        historical,
        f"{query}. Temporarily route through the old port.",
        review_status="stale",
    )
    _note(project, broken, f"{query}. Discarded route evidence.", review_status="broken-evidence")
    _note(
        project,
        closed,
        f"{query}. Do not reuse this advice.",
        superseded_by=current,
        review_status="broken-evidence",
    )
    _note(project, current, "Use the new harbor navigation plan.", review_status="stale")

    pack = context_for_task(project, query)
    assert pack["retrieval_status"] == "matched"
    assert "Use the new harbor navigation plan." in pack["text"]
    assert f"closed by `{current}`" in pack["text"]
    assert "Historical lead (stale)" in pack["text"]
    assert "Do not reuse this advice." not in pack["text"]
    assert "Discarded route evidence." not in pack["text"]
    hits = {hit["section"]: hit["snippet"] for hit in keyword_search(project, query)}
    assert "Use the new harbor navigation plan." in hits[f"store:{current}"]
    assert f"Closed by `{current}`" in hits[f"store:{closed}"]
    assert hits[f"store:{historical}"].startswith("Historical lead (stale)")
    assert f"store:{broken}" not in hits

    _note(project, current, "Disqualified navigation plan.", review_status="broken-evidence")
    pack = context_for_task(project, query)
    assert pack["retrieval_status"] == "historical_only"
    assert f"closed by `{current}`" in pack["text"]
    assert "Disqualified navigation plan." not in pack["text"]
    assert f"store:{current}" not in {hit["section"] for hit in keyword_search(project, query)}


def test_pack_metadata_tracks_exact_fit_and_dropped_fragment(
    project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORY_FABRIC_FILE_SHARE_CAP", "1")
    query = "EXACT_BUDGET_71"
    first, last = "decisions/primary", "failures/secondary"
    _note(project, first, f"{query}. Keep the enabled mode.", priority="high")
    _note(project, last, f"{query}. Use the supported recovery path.", priority="low")

    full = context_for_task(project, query)
    exact = context_for_task(project, query, max_tokens=full["estimated_tokens"])
    assert exact["text"] == full["text"]
    assert exact["estimated_tokens"] == exact["token_budget"]
    assert exact["pack_stats"]["included_by_role"]["failure"] == 1

    dropped = context_for_task(project, query, max_tokens=full["estimated_tokens"] - 1)
    assert f"store/{first}" in dropped["included_sections"]
    assert f"store/{last}" in dropped["omitted_sections"]
    assert "supported recovery path" not in dropped["text"]
    assert dropped["pack_stats"]["omitted_by_role"]["failure"] == 1
    assert "failure" not in dropped["pack_stats"]["tokens_by_role"]
    for pack in (exact, dropped):
        assert _MARKER.findall(pack["text"]) == pack["included_sections"]
        assert pack["estimated_tokens"] == estimate_tokens(pack["text"])
        assert pack["pack_stats"]["estimated_tokens"] == pack["estimated_tokens"]
        assert pack["retrieval_status"] == "matched"

    steering = context_for_task(project, "")
    limited = context_for_task(project, query, max_tokens=steering["estimated_tokens"])
    assert "retrieval_status" not in steering
    assert limited["retrieval_status"] == "budget_limited"
    assert limited["text"] == steering["text"]


def test_semantic_candidates_obey_lifecycle_and_explicit_identifiers(
    project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORY_FABRIC_SEMANTIC", "1")
    for key, data in (
        ("decisions/standing", {"review_status": "stale"}),
        ("misc/explicit-standing", {"review_status": "stale", "role": "decisions"}),
        ("failures/stale", {"review_status": "stale"}),
        ("failures/broken", {"review_status": "broken-evidence"}),
        ("decisions/closed", {"superseded_by": "decisions/standing"}),
    ):
        _note(project, key, "JWT rotates authentication tokens.", **data)

    def embed(texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0]
            if any(
                marker in text for marker in ("JWT rotates", "remain signed in", "UNKNOWN_AUTH_42")
            )
            else [0.0, 1.0]
            for text in texts
        ]

    set_embedder(embed)
    try:
        for query in ("How do clients remain signed in?", "JWT rotates"):
            hits = {hit["section"]: hit["snippet"] for hit in keyword_search(project, query)}
            assert "store:decisions/standing" in hits
            assert "store:misc/explicit-standing" in hits
            assert "store:failures/broken" not in hits
            if "JWT" in query:
                assert hits["store:failures/stale"].startswith("Historical lead (stale)")
                assert "Closed by" in hits["store:decisions/closed"]
            else:
                assert not ({"store:failures/stale", "store:decisions/closed"} & hits.keys())
        assert keyword_search(project, "UNKNOWN_AUTH_42") == []
    finally:
        set_embedder(None)


def test_cli_retrieve_reports_status(project: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--cwd", project, "--json", "retrieve", "MISSING_CLI_IDENTIFIER_12"]) == 0
    pack = json.loads(capsys.readouterr().out)
    assert pack["retrieval_status"] == "no_match"
    assert RECALL_STEERING in pack["text"]
