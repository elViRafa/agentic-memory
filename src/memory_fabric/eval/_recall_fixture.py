"""Synthetic recall cases based on the November 2026 field report."""

from typing import Any

from memory_fabric.frontmatter import dump_frontmatter
from memory_fabric.paths import memory_store_dir

RECALL_STEERING = "Use repository-relative source paths when reporting findings."

_NOTE_DEFAULTS = {
    "priority": "medium",
    "schema_version": "1.3",
    "last_updated": "2026-11-01T12:00:00-03:00",
}

_NOTES = [
    (
        "decisions/ledger-export-encoding",
        "Ledger export encoding",
        "The ADR approved UTF-8 without a byte order mark for ledger exports.",
        {},
    ),
    (
        "decisions/review-window",
        "Review window",
        "A janela aprovada para revisão termina ao meio-dia.",
        {},
    ),
    (
        "failures/frame-decoder-preview",
        "Frame decoder preview",
        "In src/frame_reader.py, reject the frame before allocating the payload buffer.",
        {},
    ),
    (
        "failures/deduplicate-relay-retry",
        "Duplicate relay retry",
        "RELAY_RETRY_DUPLICATE. Reuse the original delivery ID on retry.",
        {"review_status": "stale"},
    ),
    (
        "failures/reparo-cache-expirado",
        "Reparo do cache expirado",
        "CACHE_EXPIRADO_17. O reparo foi remover a chave órfã antes de reabrir o cache.",
        {"review_status": "stale"},
    ),
    (
        "decisions/arquivo-anterior",
        "Política anterior de arquivamento",
        "ARCHIVE_ROUTE_V1. Grave o índice antes de mover o arquivo.",
        {"superseded_by": "decisions/arquivo-atual"},
    ),
    (
        "decisions/arquivo-atual",
        "Política atual de arquivamento",
        "ARCHIVE_ROUTE_V2. Grave o índice depois de verificar a cópia.",
        {},
    ),
    (
        "architecture/compactor-runbook",
        "Storage runbook",
        "# Routine checks\n\n"
        + "Record the time and result of each maintenance check.\n" * 60
        + "\n## Restart after COMPACTOR_OFFSET_MISMATCH\n\n"
        + "Resume from the last committed segment boundary.",
        {},
    ),
]

RECALL_TASKS: list[dict[str, Any]] = [
    {
        "id": "current-decision",
        "query": "Which ledger export encoding did the ADR approve?",
        "expected_store_paths": ["decisions/ledger-export-encoding"],
        "expected_tokens": ["UTF-8 without a byte order mark"],
        "expected_status": "matched",
    },
    {
        "id": "open-file-failure",
        "query": "May I proceed?",
        "files_open": ["src/frame_reader.py"],
        "search_expected_store_paths": [],
        "expected_store_paths": ["failures/frame-decoder-preview"],
        "expected_tokens": ["reject the frame before allocating the payload buffer"],
        "expected_status": "matched",
    },
    {
        "id": "stale-relay-fix",
        "query": "What was the fix for RELAY_RETRY_DUPLICATE?",
        "expected_store_paths": ["failures/deduplicate-relay-retry"],
        "expected_tokens": ["Reuse the original delivery ID on retry"],
        "expected_status": "historical_only",
    },
    {
        "id": "stale-cache-fix",
        "query": "Qual foi o reparo para CACHE_EXPIRADO_17?",
        "expected_store_paths": ["failures/reparo-cache-expirado"],
        "expected_tokens": ["remover a chave órfã antes de reabrir o cache"],
        "expected_status": "historical_only",
    },
    {
        "id": "closed-predecessor",
        "query": "Qual regra substituiu ARCHIVE_ROUTE_V1?",
        "expected_store_paths": ["decisions/arquivo-atual"],
        "expected_tokens": ["Grave o índice depois de verificar a cópia"],
        "expected_status": "matched",
    },
    {
        "id": "late-section",
        "query": "Where should we restart after COMPACTOR_OFFSET_MISMATCH?",
        "max_tokens": 1200,
        "expected_store_paths": ["architecture/compactor-runbook"],
        "expected_tokens": ["Resume from the last committed segment boundary"],
        "expected_status": "matched",
    },
    {
        "id": "invented-identifier",
        "query": "QZX_RECALL_FIXTURE_9047",
        "expected_status": "no_match",
    },
    {
        "id": "incidental-overlap-en",
        "query": "Which kiln temperature was approved for porcelain glazing?",
        "expected_status": "no_match",
    },
    {
        "id": "incidental-overlap-pt",
        "query": "Qual temperatura foi aprovada para a queima de porcelana?",
        "expected_status": "no_match",
    },
    {
        "id": "inclusion-at-budget",
        "query": "QZX_RECALL_FIXTURE_9047",
        "max_tokens": 320,
        "expected_status": "no_match",
    },
]


def populate_recall_fixture(cwd: str) -> None:
    # Seed a snapshot so lifecycle dates and statuses are independent of when
    # the benchmark runs. A regular store write clears the stale flag.
    root = memory_store_dir(cwd)
    for store_path, title, body, lifecycle in _NOTES:
        path = root.joinpath(*store_path.split("/")).with_suffix(".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {**_NOTE_DEFAULTS, "store_path": store_path, "title": title, **lifecycle}
        path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
