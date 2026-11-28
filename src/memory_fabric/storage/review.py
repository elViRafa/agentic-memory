"""Drain ``review_status: pending`` / ``needs-review`` captures into real memories.

Contradiction hits are also queued here as advisory close proposals. Promote
is what writes ``superseded_by``; the detector never closes on its own.
"""

from __future__ import annotations

import hashlib
import re
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
from memory_fabric.storage.close import (
    body_claims_superseded_without_field,
    close_store_file,
    extract_named_store_paths,
)
from memory_fabric.storage.store import write_memory_store
from memory_fabric.templates import now_iso

_PENDING_STATUSES = frozenset({"pending", "needs-review"})
_PENDING_TAGS = frozenset({"needs-review", "passive-capture", "contradiction-review"})
_CONTRADICTION_KIND_TO_CLOSE = {
    "replacement": "update",
    "reversal": "revision",
    "numeric": "revision",
    "polarity": "revision",
    "llm": "revision",
}


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


def queue_contradiction_reviews(cwd: str, hits: list[Any], *, max_new: int = 20) -> list[str]:
    """Write pending review stubs for contradiction hits. Does not close anything.

    Returns the store paths that were created or refreshed.
    """
    store_root = memory_store_dir(cwd)
    created: list[str] = []
    for hit in hits[:max_new]:
        kind = str(getattr(hit, "kind", "") or "llm")
        path_a = str(getattr(hit, "store_path_a", "") or "")
        path_b = str(getattr(hit, "store_path_b", "") or "")
        message = str(getattr(hit, "message", "") or "")
        evidence = str(getattr(hit, "evidence", "") or "")
        if not path_a:
            continue
        # Replacement hits name the successor in evidence; otherwise B is the peer.
        successor = evidence if kind == "replacement" and "/" in evidence else path_b
        closed_candidate = path_a if successor != path_a else path_b
        if not successor or not closed_candidate:
            continue
        slug_src = f"{kind}:{closed_candidate}:{successor}"
        digest = hashlib.md5(slug_src.encode("utf-8")).hexdigest()[:10]
        safe_a = re.sub(r"[^a-z0-9]+", "-", closed_candidate.casefold()).strip("-")[:40]
        store_path = f"reviews/contradiction-{safe_a}-{digest}"
        close_kind = _CONTRADICTION_KIND_TO_CLOSE.get(kind, "revision")
        body = (
            f"Proposed close: `{closed_candidate}` → `{successor}` "
            f"(close_kind={close_kind}, detector={kind}).\n\n"
            f"{message}\n"
        )
        if evidence and evidence != successor:
            body += f"\nEvidence: {evidence}\n"
        result = write_memory_store(
            cwd,
            store_path=store_path,
            content=body,
            title=f"Contradiction review: {closed_candidate}",
            tags=["contradiction-review", "needs-review"],
            priority="low",
            mode="replace",
        )
        # Stamp structured fields for promote_review.
        dest = store_root / "reviews" / f"contradiction-{safe_a}-{digest}.md"
        if dest.exists():
            meta, existing = parse_frontmatter(dest.read_text(encoding="utf-8"))
            meta["review_status"] = "pending"
            meta["close_candidate"] = closed_candidate
            meta["close_successor"] = successor
            meta["suggested_close_kind"] = close_kind
            meta["contradiction_kind"] = kind
            meta["last_queued"] = now_iso()
            dest.write_text(dump_frontmatter(meta, existing), encoding="utf-8")
        if result.get("changed"):
            created.append(store_path)
    return created


def queue_prose_superseded_reviews(cwd: str, *, max_new: int = 20) -> list[str]:
    """Queue review stubs for files that claim supersession in prose only."""
    store_root = memory_store_dir(cwd)
    memory_dir = local_memory_dir(cwd)
    created: list[str] = []
    if not store_root.is_dir():
        return created
    for path in _iter_markdown_files(store_root):
        if len(created) >= max_new:
            break
        if _is_ignored_local_memory_path(memory_dir, path) or path.name == "index.md":
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        if not body_claims_superseded_without_field(metadata, body):
            continue
        store_path = _path_to_store_path(store_root, path)
        if store_path.startswith("reviews/"):
            continue
        named = extract_named_store_paths(body[:1200])
        successor = next((p for p in named if p != store_path), "")
        digest = hashlib.md5(f"prose:{store_path}:{successor}".encode()).hexdigest()[:10]
        safe = re.sub(r"[^a-z0-9]+", "-", store_path.casefold()).strip("-")[:40]
        review_path = f"reviews/prose-superseded-{safe}-{digest}"
        body_out = (
            f"Prose claims supersession without a `supersedes:` field.\n\n"
            f"Candidate to close: `{store_path}`\n"
            f"Suggested successor: `{successor or '(none named)'}`\n\n"
            f"Promote to write superseded_by, or drop if the prose is wrong.\n"
        )
        result = write_memory_store(
            cwd,
            store_path=review_path,
            content=body_out,
            title=f"Prose superseded review: {store_path}",
            tags=["contradiction-review", "needs-review", "prose-superseded"],
            priority="low",
            mode="replace",
        )
        dest = store_root / "reviews" / f"prose-superseded-{safe}-{digest}.md"
        if dest.exists():
            meta, existing = parse_frontmatter(dest.read_text(encoding="utf-8"))
            meta["review_status"] = "pending"
            meta["close_candidate"] = store_path
            if successor:
                meta["close_successor"] = successor
            meta["suggested_close_kind"] = "update"
            meta["contradiction_kind"] = "prose-superseded"
            meta["last_queued"] = now_iso()
            dest.write_text(dump_frontmatter(meta, existing), encoding="utf-8")
        if result.get("changed"):
            created.append(review_path)
    return created


def promote_review(cwd: str, store_path: str, target_store_path: str) -> ReviewActionResult:
    """Promote a pending capture, or apply a queued contradiction close.

    For contradiction reviews (``reviews/contradiction-*``), *target_store_path*
    may be empty: the stub's ``close_candidate`` / ``close_successor`` are used
    and ``superseded_by`` is written on the candidate.
    """
    _validate_store_path(store_path)
    source = memory_store_dir(cwd) / f"{store_path}.md"
    if not source.exists():
        # Nested path under reviews/
        parts = store_path.replace("\\", "/").strip("/").split("/")
        source = memory_store_dir(cwd).joinpath(*parts[:-1], f"{parts[-1]}.md")
    if not source.exists():
        raise FileNotFoundError(f"Review source not found: {store_path}")
    metadata, body = parse_frontmatter(source.read_text(encoding="utf-8"))
    warnings: list[str] = []

    # Contradiction close: promote writes superseded_by, keeps both texts.
    close_candidate = str(metadata.get("close_candidate") or "").strip()
    close_successor = str(metadata.get("close_successor") or "").strip()
    if close_candidate and close_successor:
        kind = str(metadata.get("suggested_close_kind") or "update")
        closed = close_store_file(
            memory_store_dir(cwd),
            close_candidate,
            successor=close_successor,
            close_kind=kind,
        )
        metadata["review_status"] = "promoted"
        metadata["promoted_to"] = close_successor
        source.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
        if closed:
            warnings.append(f"Closed `{close_candidate}` with superseded_by: {close_successor}.")
        else:
            warnings.append(
                f"Promote recorded but `{close_candidate}` was missing or already closed."
            )
        return {
            "changed": True,
            "action": "promote-close",
            "store_path": store_path,
            "target_store_path": close_successor,
            "path": str(source),
            "warnings": warnings,
        }

    if not target_store_path:
        raise ValueError("target_store_path is required for non-contradiction reviews")
    _validate_store_path(target_store_path)
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
            if str(t).lower() not in {"needs-review", "passive-capture", "contradiction-review"}
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
