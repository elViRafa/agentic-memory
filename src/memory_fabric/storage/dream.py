"""Dreaming's public entry points: `dream`, `prepare_dream_payload`, and
`apply_dream_results`. All three gather external inputs (git diff, session
transcripts, tool calls) and a candidate store, then hand off to
`finalize._process_and_finalize_candidate` to do the actual consolidation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_fabric.contracts import DreamResult
from memory_fabric.frontmatter import FrontmatterError, parse_frontmatter
from memory_fabric.paths import local_memory_dir
from memory_fabric.storage._shared import (
    _get_section_key,
    _is_generated_file,
    _is_ignored_local_memory_path,
    _iter_markdown_files,
)
from memory_fabric.storage.consolidation import (
    _consolidate_candidate_memory,
    _create_candidate_store,
)
from memory_fabric.storage.finalize import (
    _get_git_diff,
    _is_llm_ready,
    _parse_llm_json_response,
    _process_and_finalize_candidate,
    build_consolidation_prompt,
)
from memory_fabric.storage.lifecycle import initialize_memory_fabric
from memory_fabric.storage.maps import regenerate_maps
from memory_fabric.storage.snapshots import create_snapshot
from memory_fabric.llm import call_llm


async def dream(
    cwd: str,
    mode: str = "light",
    apply: bool = False,
    llm_rewrite: bool = False,
    max_rewrite_tasks: int = 5,
    context: Any = None,
) -> DreamResult:
    if mode not in {"light", "deep"}:
        raise ValueError("mode must be 'light' or 'deep'")
    if max_rewrite_tasks < 0:
        raise ValueError("max_rewrite_tasks must be >= 0")

    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        initialize_memory_fabric(cwd)

    snapshot = create_snapshot(cwd)
    candidate_root = _create_candidate_store(memory_dir, snapshot)

    warnings: list[str] = []

    # Store-first model: fold hand edits on generated maps into the store and
    # rebuild the maps BEFORE assembling the payload, so folded content is
    # consolidated in this very Dream instead of one cycle later.
    early_maps = regenerate_maps(candidate_root)
    warnings.extend(early_maps["warnings"])

    # Ingest external inputs
    git_diff_text = _get_git_diff(cwd)
    session_text = ""
    tool_calls_text = ""

    session_path = memory_dir / "private" / "session_transcripts.md"
    if session_path.exists():
        try:
            session_text = session_path.read_text(encoding="utf-8")
        except Exception:
            pass

    tool_calls_path = memory_dir / "private" / "tool_calls.jsonl"
    if tool_calls_path.exists():
        try:
            tool_calls_text = tool_calls_path.read_text(encoding="utf-8")
        except Exception:
            pass

    llm_active = _is_llm_ready(context)

    fallback_duplicates = 0
    fallback_lines_removed = 0
    fallback_files_touched = None
    is_fallback = False

    resp_data = None
    current_consolidation_hash = None

    if llm_active:
        try:
            # 1. Read files into payload (generated maps are derived views — the
            # LLM must not rewrite them, and they must not perturb the hash)
            sections_data = {}
            for path in _iter_markdown_files(candidate_root):
                if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
                    continue
                if _is_generated_file(path):
                    continue
                metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                key = _get_section_key(candidate_root, path)
                sections_data[key] = body

            # Calculate consolidation input hash
            import hashlib

            hash_input = []
            for name in sorted(sections_data.keys()):
                hash_input.append(f"section:{name}")
                hash_input.append(sections_data[name])
            hash_input.append(f"git_diff:{git_diff_text or ''}")
            hash_input.append(f"session:{session_text or ''}")
            hash_input.append(f"tool_calls:{tool_calls_text or ''}")

            current_consolidation_hash = hashlib.md5(
                "\n".join(hash_input).encode("utf-8")
            ).hexdigest()

            # Read previous consolidation metadata from index.md
            previous_consolidation_hash = None
            previous_contradictions = []
            previous_warnings = []
            index_path = memory_dir / "index.md"
            if index_path.exists():
                try:
                    index_metadata, _ = parse_frontmatter(index_path.read_text(encoding="utf-8"))
                    previous_consolidation_hash = index_metadata.get("consolidation_hash")
                    previous_contradictions = index_metadata.get("contradictions", [])
                    previous_warnings = index_metadata.get("consolidation_warnings", [])
                except Exception:
                    pass

            if previous_consolidation_hash == current_consolidation_hash:
                # Skip LLM consolidation call and use cached results
                resp_data = {
                    "consolidated_files": {},
                    "contradictions": previous_contradictions,
                    "warnings": previous_warnings,
                }
            else:
                # 2. Build consolidation prompt (shared builder — also asks the
                # LLM to extract new store entries from the diff/transcripts)
                prompt = build_consolidation_prompt(
                    sections_data,
                    git_diff_text,
                    session_text,
                    tool_calls_text,
                    include_summaries=False,
                )

                response_str = await call_llm(
                    prompt, "You are a software architect memory consolidation agent.", context
                )
                resp_data = _parse_llm_json_response(response_str)

        except Exception as exc:
            warnings.append(f"LLM-based consolidation failed; falling back to local. Error: {exc}")
            local_c = _consolidate_candidate_memory(candidate_root)
            fallback_duplicates = local_c["duplicates_found"]
            fallback_lines_removed = local_c["lines_removed"]
            fallback_files_touched = local_c["files_touched"]
            warnings.extend(local_c.get("warnings", []))
            resp_data = {"consolidated_files": {}}
            is_fallback = True
    else:
        local_c = _consolidate_candidate_memory(candidate_root)
        fallback_duplicates = local_c["duplicates_found"]
        fallback_lines_removed = local_c["lines_removed"]
        fallback_files_touched = local_c["files_touched"]
        warnings.extend(local_c.get("warnings", []))
        resp_data = {"consolidated_files": {}}
        is_fallback = True

    res = await _process_and_finalize_candidate(
        cwd=cwd,
        candidate_root=candidate_root,
        memory_dir=memory_dir,
        resp_data=resp_data,
        mode=mode,
        apply=apply,
        llm_rewrite=llm_rewrite,
        max_rewrite_tasks=max_rewrite_tasks,
        git_diff_text=git_diff_text,
        session_text=session_text,
        tool_calls_text=tool_calls_text,
        snapshot=snapshot,
        context=context,
        fallback_duplicates=fallback_duplicates,
        fallback_lines_removed=fallback_lines_removed,
        fallback_files_touched=fallback_files_touched,
        is_fallback=is_fallback,
    )
    if warnings:
        res["warnings"] = warnings + res["warnings"]
    return res


def prepare_dream_payload(cwd: str, mode: str = "light") -> dict[str, Any]:
    """Prepare the LLM prompt and payload for memory consolidation (Dreaming).

    This is designed to be called by MCP clients to run Dreaming in a client-driven split-tool manner.
    """
    if mode not in {"light", "deep"}:
        raise ValueError("mode must be 'light' or 'deep'")

    memory_dir = local_memory_dir(cwd)
    if not memory_dir.exists():
        initialize_memory_fabric(cwd)

    snapshot = create_snapshot(cwd)
    candidate_root = _create_candidate_store(memory_dir, snapshot)

    # Store-first model: fold hand edits on generated maps into the store and
    # rebuild the maps before assembling the payload, so folded content is
    # consolidated in this very Dream instead of one cycle later.
    early_maps = regenerate_maps(candidate_root)

    # Ingest external inputs
    git_diff_text = _get_git_diff(cwd)
    session_text = ""
    tool_calls_text = ""

    session_path = memory_dir / "private" / "session_transcripts.md"
    if session_path.exists():
        try:
            session_text = session_path.read_text(encoding="utf-8")
        except Exception:
            pass

    tool_calls_path = memory_dir / "private" / "tool_calls.jsonl"
    if tool_calls_path.exists():
        try:
            tool_calls_text = tool_calls_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # Read files into payload (generated maps are derived views — the LLM must
    # not rewrite them, and they must not perturb the consolidation hash)
    payload_warnings: list[str] = []
    sections_data = {}
    for path in _iter_markdown_files(candidate_root):
        if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
            continue
        if _is_generated_file(path):
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            payload_warnings.append(
                f"Skipped {path.relative_to(candidate_root)} during consolidation: {exc}"
            )
            continue
        key = _get_section_key(candidate_root, path)
        sections_data[key] = body

    # Calculate consolidation input hash
    import hashlib

    hash_input = []
    for name in sorted(sections_data.keys()):
        hash_input.append(f"section:{name}")
        hash_input.append(sections_data[name])
    hash_input.append(f"git_diff:{git_diff_text or ''}")
    hash_input.append(f"session:{session_text or ''}")
    hash_input.append(f"tool_calls:{tool_calls_text or ''}")

    current_consolidation_hash = hashlib.md5("\n".join(hash_input).encode("utf-8")).hexdigest()

    # Read previous consolidation metadata from index.md
    previous_consolidation_hash = None
    previous_contradictions = []
    previous_warnings = []
    index_path = memory_dir / "index.md"
    if index_path.exists():
        try:
            index_metadata, _ = parse_frontmatter(index_path.read_text(encoding="utf-8"))
            previous_consolidation_hash = index_metadata.get("consolidation_hash")
            previous_contradictions = index_metadata.get("contradictions", [])
            previous_warnings = index_metadata.get("consolidation_warnings", [])
        except Exception:
            pass

    if previous_consolidation_hash == current_consolidation_hash:
        return {
            "skip_required": True,
            "snapshot": snapshot,
            "current_consolidation_hash": current_consolidation_hash,
            "contradictions": previous_contradictions,
            "warnings": list(previous_warnings) + early_maps["warnings"] + payload_warnings,
        }

    # Build consolidation prompt (shared builder — the split-tool variant keeps
    # the summaries block so client-driven Dreaming refreshes summaries too)
    prompt = build_consolidation_prompt(
        sections_data,
        git_diff_text,
        session_text,
        tool_calls_text,
        include_summaries=True,
    )

    return {
        "skip_required": False,
        "snapshot": snapshot,
        "candidate_store": candidate_root.name,
        "current_consolidation_hash": current_consolidation_hash,
        "consolidation_prompt": prompt,
        "sections_data": sections_data,
        "warnings": early_maps["warnings"] + payload_warnings,
    }


async def apply_dream_results(
    cwd: str,
    candidate_store: str,
    llm_response: str,
    mode: str = "light",
    apply: bool = True,
    llm_rewrite: bool = False,
    max_rewrite_tasks: int = 5,
    context: Any = None,
) -> DreamResult:
    """Apply consolidation results from client agent's LLM run to target memory files.

    This is designed to be called by MCP clients to complete the dreaming process.
    """
    if mode not in {"light", "deep"}:
        raise ValueError("mode must be 'light' or 'deep'")
    if max_rewrite_tasks < 0:
        raise ValueError("max_rewrite_tasks must be >= 0")

    memory_dir = local_memory_dir(cwd)
    candidate_path = Path(candidate_store)
    if candidate_path.is_absolute():
        candidate_root = candidate_path
    else:
        candidate_root = memory_dir / "candidates" / candidate_store

    if not candidate_root.exists():
        raise FileNotFoundError(
            f"Candidate store directory not found for candidate_store: {candidate_store}"
        )

    # Extract snapshot name from candidate_root name
    parts = candidate_root.name.split("-")
    if len(parts) >= 2:
        snapshot = "-".join(parts[:-1])
    else:
        snapshot = candidate_root.name

    git_diff_text = _get_git_diff(cwd)
    session_text = ""
    tool_calls_text = ""

    session_path = memory_dir / "private" / "session_transcripts.md"
    if session_path.exists():
        try:
            session_text = session_path.read_text(encoding="utf-8")
        except Exception:
            pass

    tool_calls_path = memory_dir / "private" / "tool_calls.jsonl"
    if tool_calls_path.exists():
        try:
            tool_calls_text = tool_calls_path.read_text(encoding="utf-8")
        except Exception:
            pass

    resp_data = _parse_llm_json_response(llm_response)

    return await _process_and_finalize_candidate(
        cwd=cwd,
        candidate_root=candidate_root,
        memory_dir=memory_dir,
        resp_data=resp_data,
        mode=mode,
        apply=apply,
        llm_rewrite=llm_rewrite,
        max_rewrite_tasks=max_rewrite_tasks,
        git_diff_text=git_diff_text,
        session_text=session_text,
        tool_calls_text=tool_calls_text,
        snapshot=snapshot,
        context=context,
    )
