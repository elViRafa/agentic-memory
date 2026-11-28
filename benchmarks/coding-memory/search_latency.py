"""Measure indexed keyword search against a deterministic 500-note corpus."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sqlite3
import sys
import tempfile
from collections import defaultdict
from contextlib import ExitStack
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from time import perf_counter_ns
from unittest.mock import patch

TOPICS = (
    "replication lag",
    "archive rotation",
    "connection pooling",
    "encryption keys",
    "retry jitter",
    "schema migration",
    "webhook delivery",
    "message ordering",
    "retenção de auditoria",
    "conciliação de pagamentos",
    "expiração da sessão",
    "importação de planilhas",
    "permissões de leitura",
    "filas de processamento",
    "validação de certificados",
    "redução de ruído",
)
QUERIES = (
    *(f"How do we handle {topic}?" for topic in TOPICS[:8]),
    *(f"Como funciona {topic}?" for topic in TOPICS[8:]),
    "relay_flush_quantum",
    "etapa_reprocessamento",
    "archive_cursor_guard",
    "registro_sem_correspondencia",
)
IDENTIFIERS = {
    0: "relay_flush_quantum",
    8: "etapa_reprocessamento",
    1: "archive_cursor_guard",
}
JOURNAL_STEPS = (
    "Reviewed the incident timeline and checked dashboard filters before the team handoff.",
    "Recorded the queue backlog and verified which deployments were included in the sample.",
    "Confirmed the staging snapshot and attached the retry counts to the weekly report.",
    "Replayed the alert, compared the regional counters, and filed the remaining questions.",
    "Na revisão, conferimos o painel, a fila e o relatório de acompanhamento da equipe.",
    "Durante a reunião, registramos os testes pendentes e os resultados da implantação.",
)


def write_fixture(project: Path) -> None:
    store = project / ".ai-memory" / "memory-store"
    for number in range(500):
        topic_index = number % len(TOPICS)
        topic = TOPICS[topic_index]
        journal = number >= 32
        folder = store / ("episodic" if journal else "decisions")
        folder.mkdir(parents=True, exist_ok=True)
        section = f"note-{number:03d}"
        if journal:
            neighboring_topic = TOPICS[(topic_index + 3) % len(TOPICS)]
            title = f"Operations journal {number:03d}"
            body = (
                f"## Review\n\nThe handoff covered {topic} and {neighboring_topic}.\n\n"
                + "\n".join(
                    f"- Pass {step + 1}: {JOURNAL_STEPS[(step + number) % len(JOURNAL_STEPS)]}"
                    for step in range(12 + number % 6)
                )
            )
        else:
            title = f"Decision on {topic}"
            body = (
                f"## Decision\n\nUse cohort {number + 1} as the validation group for {topic}.\n\n"
                "## Rollout\n\nKeep the rollback point available while the team reviews "
                "the first export. Record the observed outcome before increasing coverage.\n\n"
                "## Verification\n\nCompare the observed counts with the controlled sample "
                "and record the previous setting in the release notes.\n"
            )
            if number in IDENTIFIERS:
                body += f"\nThe configuration identifier is `{IDENTIFIERS[number]}`.\n"
        (folder / f"{section}.md").write_text(
            "---\n"
            f'section: {section}\ntitle: "{title}"\nsummary: "{title}"\n'
            f"priority: {'medium' if journal else 'high'}\n"
            'schema_version: 1.3\nlast_updated: "2026-11-01T00:00:00+00:00"\n'
            f"---\n\n# {title}\n\n{body}\n",
            encoding="utf-8",
        )


def profile_sequence(search, index, run_query) -> dict[str, float]:
    totals = defaultdict(int)
    parent_times: list[int] = []

    def timed(function, phase):
        @wraps(function)
        def wrapper(*args, **kwargs):
            parent_times.append(0)
            start = perf_counter_ns()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = perf_counter_ns() - start
                totals[phase] += elapsed - parent_times.pop()
                if parent_times:
                    parent_times[-1] += elapsed

        return wrapper

    with ExitStack() as stack:
        stages = [
            (index, "sync_index", "index_sync"),
            (index, "load_rows", "row_loading"),
            (search, "tokenize", "tokenization"),
        ]
        if hasattr(search, "_rank_notes"):
            stages.extend(
                [
                    (search, "query_tokens", "tokenization"),
                    (search, "_rank_notes", "scoring"),
                    (search, "_search_results", "snippets"),
                ]
            )
        else:
            stages.extend(
                (search, name, phase)
                for name, phase in (
                    ("_search_tokens", "tokenization"),
                    ("bm25_scores", "scoring"),
                    ("blended_score", "scoring"),
                    ("_contains_phrase", "scoring"),
                    ("_snippet_from_path", "snippets"),
                )
            )
        for module, name, phase in stages:
            stack.enter_context(patch.object(module, name, timed(getattr(module, name), phase)))
        start = perf_counter_ns()
        for query in QUERIES:
            run_query(query)
        totals["other"] = perf_counter_ns() - start - sum(totals.values())
    return {phase: round(elapsed / len(QUERIES) / 1e6, 3) for phase, elapsed in totals.items()}


def measure(project: Path, *, semantic_enabled: bool) -> dict:
    from memory_fabric.storage import index, search, semantic
    from memory_fabric.version import __version__

    backends = set()

    def run_query(query: str) -> float:
        start = perf_counter_ns()
        hits = search.keyword_search(str(project), query, max_results=5)
        elapsed = (perf_counter_ns() - start) / 1e6
        backends.update(hit["backend"] for hit in hits)
        if not hits and query not in QUERIES[-1:]:
            raise RuntimeError(f"Expected hits for {query!r}")
        return elapsed

    report = {
        "engine": __version__,
        "engine_source": str(Path(search.__file__).parents[2]),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "notes": 500,
        "cold_ms": round(run_query(QUERIES[0]), 3),
    }
    if semantic_enabled:
        if semantic._fastembed_model is None:
            raise RuntimeError("FastEmbed did not load the embedding model")
        report["fastembed"] = version("fastembed")
        report["model"] = os.getenv(
            "MEMORY_FABRIC_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        report["warm_same_query_ms"] = [round(run_query(QUERIES[0]), 3) for _ in range(3)]
    else:
        for query in QUERIES:
            run_query(query)
        samples = [run_query(query) for _ in range(5) for query in QUERIES]
        report["warm_samples"] = len(samples)
        report["warm_p95_ms"] = round(sorted(samples)[math.ceil(0.95 * len(samples)) - 1], 3)
        report["profile_ms_per_query"] = profile_sequence(search, index, run_query)
    if backends != {"index"}:
        raise RuntimeError(f"Expected the index backend, got {backends}")
    report["backend"] = "index"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-src", type=Path, required=True, help="Checkout's src directory")
    parser.add_argument("--semantic", action="store_true", help="Run a separate model timing")
    args = parser.parse_args()
    engine_src = args.engine_src.resolve()
    if not (engine_src / "memory_fabric").is_dir():
        parser.error(f"Memory Fabric source not found under {engine_src}")
    sys.path.insert(0, str(engine_src))
    os.environ["MEMORY_FABRIC_DIARY"] = "0"
    os.environ["MEMORY_FABRIC_SEMANTIC"] = "1" if args.semantic else "0"
    with tempfile.TemporaryDirectory(prefix="mf-search-") as temp:
        project = Path(temp) / "project"
        os.environ["MEMORY_FABRIC_HOME"] = str(Path(temp) / "home")
        write_fixture(project)
        print(json.dumps(measure(project, semantic_enabled=args.semantic), indent=2))


if __name__ == "__main__":
    main()
