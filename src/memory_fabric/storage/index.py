"""Rebuildable SQLite frontmatter index for the memory read path.

Lives at ``.ai-memory/private/index.db`` (gitignored). Ranking runs on the
index; only files that win a budget slot have their bodies re-read.
Missing or corrupt indexes fall back to a full scan — the same degradation
contract used for ``rg`` and LLM providers.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_fabric.paths import local_memory_dir
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path,
    _is_steering_file,
    _is_store_path,
    _iter_markdown_files,
    _path_to_store_path,
    _read_memory_path,
    estimate_tokens,
)
from memory_fabric.storage.ranking import tokenize

SCHEMA_VERSION = 1

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    relpath TEXT PRIMARY KEY,
    section_key TEXT NOT NULL,
    store_path TEXT,
    priority TEXT,
    title TEXT,
    summary TEXT,
    tags TEXT,
    last_updated TEXT,
    body_tokens INTEGER,
    content_hash TEXT,
    mtime REAL,
    is_generated INTEGER,
    is_steering INTEGER,
    is_map INTEGER,
    rank_text TEXT
);
"""


@dataclass(frozen=True)
class IndexRow:
    relpath: str
    section_key: str
    store_path: str
    priority: str
    title: str
    summary: str
    tags: list[str]
    last_updated: str
    body_tokens: int
    content_hash: str
    mtime: float
    is_generated: bool
    is_steering: bool
    is_map: bool
    rank_text: str
    path: Path


def index_db_path(memory_dir: Path) -> Path:
    return memory_dir / "private" / "index.db"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _section_key_for(memory_dir: Path, path: Path, section_name: str) -> str:
    if _is_store_path(memory_dir, path):
        store_root = memory_dir / "memory-store"
        try:
            return "store/" + _path_to_store_path(store_root, path)
        except ValueError:
            pass
    return f"local/{section_name}"


def _is_startup_map(memory_dir: Path, path: Path, metadata: dict[str, Any]) -> bool:
    """Root maps + memory-store/index.md — the maps-first startup surface."""
    if path == memory_dir / "memory-store" / "index.md":
        return True
    if path.parent == memory_dir and path.suffix == ".md":
        if path.name == "consolidated_memory.md":
            return False
        return not _is_steering_file(path)
    return bool(metadata.get("generated"))


def _open(db_path: Path) -> sqlite3.Connection | None:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_CREATE_SQL)
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        elif int(row["value"]) != SCHEMA_VERSION:
            conn.close()
            db_path.unlink(missing_ok=True)
            return _open(db_path)
        return conn
    except (OSError, sqlite3.Error):
        return None


def sync_index(cwd: str) -> sqlite3.Connection | None:
    """Incrementally update the index. Returns None on any failure."""
    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        return None
    conn = _open(index_db_path(memory_dir))
    if conn is None:
        return None
    try:
        existing = {
            row["relpath"]: (row["mtime"], row["content_hash"])
            for row in conn.execute("SELECT relpath, mtime, content_hash FROM files")
        }
        seen: set[str] = set()
        for path in _iter_markdown_files(memory_dir):
            if _is_ignored_local_memory_path(memory_dir, path):
                continue
            try:
                relpath = path.relative_to(memory_dir).as_posix()
            except ValueError:
                continue
            seen.add(relpath)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            prev = existing.get(relpath)
            if prev is not None and abs(prev[0] - mtime) < 1e-6:
                continue
            try:
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            digest = _content_hash(raw)
            if prev is not None and prev[1] == digest:
                conn.execute("UPDATE files SET mtime = ? WHERE relpath = ?", (mtime, relpath))
                continue
            section_name, metadata, body, warning = _read_memory_path(path)
            if warning:
                continue
            title = str(metadata.get("title") or section_name)
            summary = str(metadata.get("summary") or "")
            raw_tags = metadata.get("tags")
            tags: list[str] = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
            store_path = ""
            if _is_store_path(memory_dir, path):
                try:
                    store_path = _path_to_store_path(memory_dir / "memory-store", path)
                except ValueError:
                    store_path = ""
            rank_text = " ".join(
                part for part in (title, summary, " ".join(str(t) for t in tags), body) if part
            )
            conn.execute(
                """
                INSERT INTO files (
                    relpath, section_key, store_path, priority, title, summary, tags,
                    last_updated, body_tokens, content_hash, mtime, is_generated,
                    is_steering, is_map, rank_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(relpath) DO UPDATE SET
                    section_key=excluded.section_key,
                    store_path=excluded.store_path,
                    priority=excluded.priority,
                    title=excluded.title,
                    summary=excluded.summary,
                    tags=excluded.tags,
                    last_updated=excluded.last_updated,
                    body_tokens=excluded.body_tokens,
                    content_hash=excluded.content_hash,
                    mtime=excluded.mtime,
                    is_generated=excluded.is_generated,
                    is_steering=excluded.is_steering,
                    is_map=excluded.is_map,
                    rank_text=excluded.rank_text
                """,
                (
                    relpath,
                    _section_key_for(memory_dir, path, section_name),
                    store_path,
                    str(metadata.get("priority") or "medium"),
                    title,
                    summary,
                    json.dumps(tags, ensure_ascii=False),
                    str(metadata.get("last_updated") or ""),
                    estimate_tokens(raw),
                    digest,
                    mtime,
                    1 if metadata.get("generated") else 0,
                    1 if _is_steering_file(path) else 0,
                    1 if _is_startup_map(memory_dir, path, metadata) else 0,
                    rank_text,
                ),
            )
        stale = [rel for rel in existing if rel not in seen]
        if stale:
            conn.executemany("DELETE FROM files WHERE relpath = ?", [(rel,) for rel in stale])
        conn.commit()
        return conn
    except (OSError, sqlite3.Error):
        with contextlib.suppress(sqlite3.Error):
            conn.close()
        return None


def load_rows(conn: sqlite3.Connection, memory_dir: Path) -> list[IndexRow]:
    rows: list[IndexRow] = []
    try:
        for row in conn.execute("SELECT * FROM files"):
            try:
                tags = json.loads(row["tags"] or "[]")
            except json.JSONDecodeError:
                tags = []
            if not isinstance(tags, list):
                tags = []
            rows.append(
                IndexRow(
                    relpath=row["relpath"],
                    section_key=row["section_key"],
                    store_path=row["store_path"] or "",
                    priority=row["priority"] or "medium",
                    title=row["title"] or "",
                    summary=row["summary"] or "",
                    tags=[str(t) for t in tags],
                    last_updated=row["last_updated"] or "",
                    body_tokens=int(row["body_tokens"] or 0),
                    content_hash=row["content_hash"] or "",
                    mtime=float(row["mtime"] or 0),
                    is_generated=bool(row["is_generated"]),
                    is_steering=bool(row["is_steering"]),
                    is_map=bool(row["is_map"]),
                    rank_text=row["rank_text"] or "",
                    path=memory_dir / row["relpath"],
                )
            )
    except sqlite3.Error:
        return []
    return rows


def close_quietly(conn: sqlite3.Connection | None) -> None:
    if conn is None:
        return
    with contextlib.suppress(sqlite3.Error):
        conn.close()


def delete_index(cwd: str) -> None:
    """Remove the on-disk index (tests, schema recovery)."""
    path = index_db_path(local_memory_dir(cwd))
    path.unlink(missing_ok=True)


def rank_texts_from_rows(rows: list[IndexRow]) -> list[list[str]]:
    return [tokenize(row.rank_text) for row in rows]
