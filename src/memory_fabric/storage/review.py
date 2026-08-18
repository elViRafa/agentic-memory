"""Drain ``review_status: pending`` / ``needs-review`` captures into real memories."""

from __future__ import annotations

from typing import Any

from memory_fabric.contracts import ReviewActionResult, ReviewEntry, ReviewListResult
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.paths import local_memory_dir, memory_store_dir
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path,
    _iter_markdown_files,
    _path_to_store_path,
    _validate_store_path,
)
from memory_fabric.storage.store import write_memory_store

_PENDING_STATUSES = frozenset({"pending", "needs-review"})
_PENDING_TAGS = frozenset({"needs-review", "passive-capture"})


def _is_pending(metadata: dict[str, Any]) -> bool:
    status = str(metadata.get("review_status") or "").strip().lower()
    if status in _PENDING_STATUSES:
        return True
    tags = metadata.get("tags")
    if isinstance(tags, list) and _PENDING_TAGS.intersection(str(t).lower() for t in tags):
        return status not in {"promoted", "dropped", "discarded", "consolidated"}
    return False


def list_pending_reviews(cwd: str, max_results: int = 100) -> ReviewListResult:
    """List store entries waiting to be promoted or dropped."""
    store_root = memory_store_dir(cwd)
    memory_dir = local_memory_dir(cwd)
    entries: list[ReviewEntry] = []
    warnings: list[str] = []
    if not store_root.exists():
        return {"entries": [], "total": 0, "warnings": ["Memory store not found."]}

    for path in _iter_markdown_files(store_root):
        if _is_ignored_local_memory_path(memory_dir, path) or path.name == "index.md":
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            warnings.append(f"{path}: {exc}")
            continue
        if not _is_pending(metadata):
            continue
        store_path = _path_to_store_path(store_root, path)
        entries.append(
            {
                "store_path": store_path,
                "path": str(path),
                "title": str(metadata.get("title") or path.stem),
                "summary": str(metadata.get("summary") or ""),
                "review_status": str(metadata.get("review_status") or "pending"),
                "preview": body.strip()[:400],
            }
        )
        if len(entries) >= max_results:
            break

    return {"entries": entries, "total": len(entries), "warnings": warnings}


def promote_review(cwd: str, store_path: str, target_store_path: str) -> ReviewActionResult:
    """Copy a pending capture to ``target_store_path`` and mark the source promoted."""
    _validate_store_path(store_path)
    _validate_store_path(target_store_path)
    source = memory_store_dir(cwd) / f"{store_path}.md"
    if not source.exists():
        raise FileNotFoundError(f"Review source not found: {store_path}")
    metadata, body = parse_frontmatter(source.read_text(encoding="utf-8"))
    provenance = (
        f"_Promoted from `{store_path}` (review queue). "
        f"Original status: {metadata.get('review_status') or 'pending'}_\n\n"
    )
    write_result = write_memory_store(
        cwd,
        store_path=target_store_path,
        content=provenance + body,
        title=str(metadata.get("title") or target_store_path.split("/")[-1]),
        tags=[
            t
            for t in list(metadata.get("tags") or [])
            if str(t).lower() not in {"needs-review", "passive-capture"}
        ]
        + ["promoted"],
        priority=str(metadata.get("priority") or "medium"),
        mode="replace",
    )
    # Stamp provenance on the destination and drain the source.
    dest = memory_store_dir(cwd) / f"{target_store_path}.md"
    if dest.exists():
        dest_meta, dest_body = parse_frontmatter(dest.read_text(encoding="utf-8"))
        dest_meta["promoted_from"] = store_path
        dest_meta["review_status"] = "current"
        dest.write_text(dump_frontmatter(dest_meta, dest_body), encoding="utf-8")

    metadata["review_status"] = "promoted"
    metadata["promoted_to"] = target_store_path
    source.write_text(dump_frontmatter(metadata, body), encoding="utf-8")

    return {
        "changed": True,
        "action": "promote",
        "store_path": store_path,
        "target_store_path": target_store_path,
        "path": write_result["path"],
        "warnings": write_result.get("warnings") or [],
    }


def drop_review(cwd: str, store_path: str) -> ReviewActionResult:
    """Mark a pending capture as dropped so it leaves the review queue."""
    _validate_store_path(store_path)
    source = memory_store_dir(cwd) / f"{store_path}.md"
    if not source.exists():
        raise FileNotFoundError(f"Review source not found: {store_path}")
    metadata, body = parse_frontmatter(source.read_text(encoding="utf-8"))
    metadata["review_status"] = "dropped"
    raw_tags = metadata.get("tags")
    tag_list = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
    metadata["tags"] = [t for t in tag_list if t.lower() != "needs-review"] + ["dropped"]
    source.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
    return {
        "changed": True,
        "action": "drop",
        "store_path": store_path,
        "target_store_path": "",
        "path": str(source),
        "warnings": [],
    }


def count_pending_reviews(cwd: str) -> int:
    return list_pending_reviews(cwd, max_results=10_000)["total"]
