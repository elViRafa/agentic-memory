"""Store-first migration: split legacy hand-written flat sections into granular
`memory-store/` entries (ROADMAP Phase 2.2, v0.8).

The heading-based heuristic split is the content pipeline: chunks are verbatim
source text, so nothing can be lost or rephrased by construction. A configured
LLM improves only the *names* of those chunks (store_path/title/tags); on any
LLM failure the heuristic names are used and migration proceeds — the same
graceful-degradation contract as Dreaming's provider handling.

A snapshot is taken before any write (`ai-memory rollback --to <name>` restores
it). Every entry write goes through `write_memory_store` (locking + secret
redaction). The flat file flips to a generated map only after its entries are
safely on disk, via `maps._generate_category_map` — deliberately bypassing
`regenerate_maps`'s hand-edit fold, which would re-blob the just-granularized
body into `map-notes-pending-review`.
"""

from __future__ import annotations

import re
from typing import Any

from memory_fabric.contracts import MigrateEntryPlan, MigrateResult, MigrateSectionPlan
from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.llm import call_llm
from memory_fabric.paths import local_memory_dir, memory_store_dir
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import (
    STEERING_SECTIONS,
    STORE_PATH_SEGMENT,
    _is_ignored_local_memory_path,
    _resolve_store_file,
    _validate_store_path,
)
from memory_fabric.storage.finalize import _is_llm_ready, _parse_llm_json_response
from memory_fabric.storage.maps import _generate_category_map, _is_starter_placeholder
from memory_fabric.storage.snapshots import create_snapshot
from memory_fabric.storage.store import write_memory_store

_H2_RE = re.compile(r"^##\s+(\S.*?)\s*$")
_MAX_SLUG_CHARS = 60
_PREVIEW_CHARS = 240


def _slugify(text: str) -> str:
    """Reduce heading text to a valid store-path segment ('' when nothing survives)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:_MAX_SLUG_CHARS].rstrip("-")


def _split_by_headings(body: str) -> list[tuple[str, str]]:
    """Split a markdown body into (heading, verbatim chunk) pairs on H2 headings.

    Fence-aware: a ``## `` line inside a ``` / ~~~ code block is content, not a
    boundary. The first pair is ``("", preamble)`` when there is real content
    before the first H2 (a lone leading H1 title does not count as content —
    the generated map brings its own title). Heading lines themselves are not
    part of chunk content; they become the entry title.
    """
    current: list[str] = []
    chunks: list[tuple[str, list[str]]] = [("", current)]
    in_fence = False
    fence_marker = ""
    for line in body.splitlines():
        stripped = line.lstrip()
        if in_fence:
            current.append(line)
            if stripped.startswith(fence_marker):
                in_fence = False
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = True
            fence_marker = stripped[:3]
            current.append(line)
            continue
        match = _H2_RE.match(line)
        if match:
            current = []
            chunks.append((match.group(1), current))
            continue
        current.append(line)

    result = [(heading, "\n".join(lines).strip("\n")) for heading, lines in chunks]
    preamble_lines = [ln for ln in result[0][1].splitlines() if ln.strip()]
    if preamble_lines and preamble_lines[0].lstrip().startswith("# "):
        preamble_lines = preamble_lines[1:]
    if not preamble_lines:
        result = result[1:]
    return result


def _heuristic_entries(
    category: str,
    chunks: list[tuple[str, str]],
    warnings: list[str],
    section: str,
) -> list[dict[str, Any]]:
    """Name each non-empty chunk deterministically; in-plan collisions get -2, -3…"""
    used: set[str] = set()
    entries: list[dict[str, Any]] = []
    for index, (heading, content) in enumerate(chunks):
        if not content.strip():
            warnings.append(
                f"{section}.md: heading '{heading}' has no body content; nothing to migrate."
            )
            continue
        if heading:
            slug = _slugify(heading) or f"part-{index + 1}"
            title = heading
            source = f"## {heading}"
        else:
            slug = "overview"
            title = f"{section.replace('-', ' ').title()} Overview"
            source = "(preamble)"
        base = slug
        suffix = 2
        while f"{category}/{slug}" in used:
            slug = f"{base}-{suffix}"
            suffix += 1
        used.add(f"{category}/{slug}")
        entries.append(
            {
                "store_path": f"{category}/{slug}",
                "title": title,
                "source": source,
                "content": content,
                "tags": None,
            }
        )
    return entries


async def _llm_name_entries(
    section: str,
    category: str,
    entries: list[dict[str, Any]],
    warnings: list[str],
) -> bool:
    """Ask the configured LLM for better names; apply only validated proposals.

    Content is never sent for rewriting — only previews for naming context.
    Returns True when at least one proposal was accepted.
    """
    chunk_lines = []
    for index, entry in enumerate(entries):
        preview = " ".join(entry["content"].split())[:_PREVIEW_CHARS]
        chunk_lines.append(f'[{index}] source: {entry["source"]!r} preview: "{preview}"')
    prompt = (
        f"A hand-written project memory section '{section}' is being split into granular "
        f"memory-store entries under the category '{category}/'.\n"
        "For each chunk below, propose a semantic store_path, a concise title, and 1-4 tags.\n"
        "Rules:\n"
        f"- store_path MUST be exactly '{category}/<slug>' (one slug segment).\n"
        "- slug: lowercase a-z, 0-9, hyphens; short and descriptive.\n"
        "- Respond ONLY with JSON, no prose: "
        '{"entries": [{"index": 0, "store_path": "...", "title": "...", "tags": ["..."]}]}\n'
        "Chunks:\n" + "\n".join(chunk_lines)
    )
    try:
        response = await call_llm(
            prompt,
            system_instruction=(
                "You are a precise memory-organization assistant. Respond with valid JSON only."
            ),
        )
        data = _parse_llm_json_response(response)
    except Exception as exc:  # noqa: BLE001 - LLM naming is best-effort; heuristic names are the guaranteed fallback.
        warnings.append(f"LLM naming for {section}.md failed ({exc}); using heuristic names.")
        return False

    proposals = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(proposals, list):
        warnings.append(f"LLM naming for {section}.md returned no entries; using heuristic names.")
        return False

    used = {entry["store_path"] for entry in entries}
    accepted = 0
    seen_indexes: set[int] = set()
    for item in proposals:
        if not isinstance(item, dict):
            continue
        proposed_index = item.get("index")
        store_path = item.get("store_path")
        if (
            not isinstance(proposed_index, int)
            or not 0 <= proposed_index < len(entries)
            or proposed_index in seen_indexes
        ):
            continue
        if not isinstance(store_path, str) or not store_path.startswith(f"{category}/"):
            continue
        try:
            segments = _validate_store_path(store_path)
        except ValueError:
            continue
        if len(segments) != 2:
            continue
        entry = entries[proposed_index]
        if store_path != entry["store_path"] and store_path in used:
            continue
        seen_indexes.add(proposed_index)
        used.discard(entry["store_path"])
        used.add(store_path)
        entry["store_path"] = store_path
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            entry["title"] = title.strip()
        tags = item.get("tags")
        if isinstance(tags, list) and all(isinstance(t, str) for t in tags):
            entry["tags"] = [t.strip() for t in tags if t.strip()][:4]
        accepted += 1
    if not accepted:
        warnings.append(
            f"LLM naming for {section}.md proposed nothing usable; using heuristic names."
        )
    return accepted > 0


def _resolve_existing_collisions(
    cwd: str,
    entries: list[dict[str, Any]],
) -> None:
    """Reconcile planned paths with files already on disk.

    Identical (redacted, stripped) body already at the target → the entry is
    'already-migrated' (a re-run after a partial failure resumes instead of
    duplicating). Different content → keep both: suffix the new entry with
    -migrated(-N).
    """
    used = {entry["store_path"] for entry in entries}
    for entry in entries:
        planned = redact_secrets(entry["content"])[0].strip()
        candidate = entry["store_path"]
        base = candidate
        suffix = 0
        while True:
            target = _resolve_store_file(cwd, candidate)
            if not target.exists():
                break
            try:
                _meta, existing_body = parse_frontmatter(target.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, FrontmatterError):
                existing_body = None
            if existing_body is not None and existing_body.strip() == planned:
                entry["status"] = "already-migrated"
                break
            suffix += 1
            candidate = f"{base}-migrated" if suffix == 1 else f"{base}-migrated-{suffix}"
            while candidate in used:
                suffix += 1
                candidate = f"{base}-migrated-{suffix}"
        used.discard(entry["store_path"])
        used.add(candidate)
        entry["store_path"] = candidate
        entry.setdefault("status", "planned")


def _normalized_priority(metadata: dict[str, Any]) -> str:
    priority = str(metadata.get("priority") or "medium")
    return priority if priority in {"high", "medium", "low"} else "medium"


def _section_tags(metadata: dict[str, Any]) -> list[str]:
    tags = metadata.get("tags")
    base = [str(t) for t in tags if str(t).strip()] if isinstance(tags, list) else []
    if "migrated" not in base:
        base.append("migrated")
    return base


async def migrate_memory(
    cwd: str,
    dry_run: bool = False,
    sections: list[str] | None = None,
    use_llm: bool | None = None,
) -> MigrateResult:
    """Split every legacy hand-written flat section into store entries.

    Args:
        dry_run:  Build and return the full plan without writing anything —
                  no snapshot, no store entries, no map rewrites.
        sections: Restrict to these section names (default: all legacy ones).
        use_llm:  None = auto (use the configured provider when ready);
                  False = heuristic names only; True warns and degrades to
                  the heuristic when no provider is actually ready.
    """
    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        raise FileNotFoundError(f"Local memory directory does not exist: {memory_dir}")
    store_root = memory_store_dir(cwd)

    warnings: list[str] = []
    requested = {name for name in sections} if sections is not None else None

    llm_ready = _is_llm_ready()
    if use_llm is None:
        use_llm = llm_ready
    elif use_llm and not llm_ready:
        warnings.append("No LLM provider is ready; falling back to heuristic naming.")
        use_llm = False

    # -- discover legacy hand-written sections -------------------------------
    targets: list[tuple[str, dict[str, Any], str]] = []
    for path in sorted(memory_dir.glob("*.md")):
        stem = path.stem
        if path.name == "index.md" or _is_ignored_local_memory_path(memory_dir, path):
            continue
        if requested is not None and stem not in requested:
            continue
        if requested is not None:
            requested.discard(stem)
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            warnings.append(f"Skipped {path.name}: could not parse it ({exc}).")
            continue
        role = str(metadata.get("role") or "").strip().lower()
        is_steering = role == "steering" if role else stem in STEERING_SECTIONS
        if is_steering:
            if sections is not None:
                warnings.append(f"Skipped {stem}: steering sections stay hand-curated.")
            continue
        if metadata.get("generated"):
            if sections is not None:
                warnings.append(f"Skipped {stem}: already a generated map.")
            continue
        if not body.strip() or _is_starter_placeholder(stem, body):
            continue
        targets.append((stem, metadata, body))

    if requested:
        for name in sorted(requested):
            warnings.append(f"Section not found or not migratable: {name}.")

    # -- build the plan -------------------------------------------------------
    prepared: list[dict[str, Any]] = []
    for section, metadata, body in targets:
        category = section.lower()
        if not STORE_PATH_SEGMENT.match(category):
            warnings.append(f"Skipped {section}: name is not a valid store category.")
            continue
        chunks = _split_by_headings(body)
        entries = _heuristic_entries(category, chunks, warnings, section)
        if not entries:
            warnings.append(
                f"Skipped {section}: no extractable content chunks; the file is left untouched."
            )
            continue
        llm_named = False
        if use_llm:
            llm_named = await _llm_name_entries(section, category, entries, warnings)
        _resolve_existing_collisions(cwd, entries)
        prepared.append(
            {
                "section": section,
                "category": category,
                "metadata": metadata,
                "entries": entries,
                "llm_named": llm_named,
            }
        )

    # -- snapshot, then apply -------------------------------------------------
    snapshot: str | None = None
    sections_migrated: list[str] = []
    entries_written: list[str] = []
    maps_written: list[str] = []
    redactions = 0

    if prepared and not dry_run:
        snapshot = create_snapshot(cwd)
        for item in prepared:
            priority = _normalized_priority(item["metadata"])
            default_tags = _section_tags(item["metadata"])
            for entry in item["entries"]:
                if entry["status"] == "already-migrated":
                    continue
                result = write_memory_store(
                    cwd,
                    entry["store_path"],
                    entry["content"],
                    title=entry["title"],
                    tags=entry["tags"] if entry["tags"] is not None else default_tags,
                    priority=priority,
                    mode="replace",
                )
                redactions += result["redactions"]
                warnings.extend(result["warnings"])
                entry["status"] = "written"
                entries_written.append(entry["store_path"])
            # Entries are safely on disk — only now flip the flat file to a
            # generated map (no fold: the body just became granular entries).
            written_map = _generate_category_map(memory_dir, store_root, item["category"], warnings)
            if written_map:
                maps_written.append(written_map)
            sections_migrated.append(item["section"])

    plan: list[MigrateSectionPlan] = [
        MigrateSectionPlan(
            section=item["section"],
            category=item["category"],
            llm_named=item["llm_named"],
            entries=[
                MigrateEntryPlan(
                    store_path=entry["store_path"],
                    title=entry["title"],
                    source=entry["source"],
                    chars=len(entry["content"]),
                    status=entry["status"],
                )
                for entry in item["entries"]
            ],
        )
        for item in prepared
    ]

    return {
        "changed": bool(sections_migrated),
        "dry_run": dry_run,
        "snapshot": snapshot,
        "sections_migrated": sections_migrated,
        "entries_written": entries_written,
        "maps_written": maps_written,
        "plan": plan,
        "redactions": redactions,
        "warnings": warnings,
    }
