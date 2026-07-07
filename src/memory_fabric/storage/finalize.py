"""Shared internals that `dream()`, `prepare_dream_payload()`, and
`apply_dream_results()` all funnel through: LLM readiness/response parsing,
git context gathering, and finalizing a candidate store's consolidation result.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from memory_fabric.contracts import DreamConsolidation, DreamResult
from memory_fabric.frontmatter import dump_frontmatter, parse_frontmatter
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import (
    SECTION_PATTERN,
    _get_section_key,
    _is_generated_file,
    _is_ignored_local_memory_path,
    _iter_markdown_files,
    _validate_store_path,
)
from memory_fabric.storage.consolidation import (
    _apply_candidate_to_live,
    _build_rewrite_tasks,
    _diff_memory_roots,
    _regenerate_index_root,
)
from memory_fabric.storage.maps import regenerate_maps
from memory_fabric.templates import build_empty_section, now_iso
from memory_fabric.llm import call_llm


def _is_llm_ready(context: Any = None) -> bool:
    provider = (os.environ.get("MEMORY_FABRIC_LLM_PROVIDER") or "").strip().lower()
    if provider:
        if provider == "gemini" and os.environ.get("GEMINI_API_KEY"):
            return True
        if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
            return True
        if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            return True
        if provider == "ollama":
            return True
    if context is not None:
        client_params = getattr(context.session, "client_params", None)
        if (
            client_params is not None
            and getattr(client_params, "capabilities", None) is not None
            and getattr(client_params.capabilities, "sampling", None) is not None
        ):
            return True
    return False


def _parse_llm_json_response(llm_response: str) -> dict[str, Any]:
    cleaned_resp = llm_response.strip()
    resp_data = None
    try:
        resp_data = json.loads(cleaned_resp)
    except json.JSONDecodeError:
        start = cleaned_resp.find("{")
        end = cleaned_resp.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                resp_data = json.loads(cleaned_resp[start : end + 1])
            except json.JSONDecodeError:
                pass

    if resp_data is None:
        import re

        blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", cleaned_resp, re.DOTALL)
        for block in blocks:
            try:
                resp_data = json.loads(block.strip())
                break
            except json.JSONDecodeError:
                pass

    if resp_data is None:
        resp_data = json.loads(cleaned_resp)
    return resp_data


def _get_git_diff(cwd: str) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5.0,
        )
        if res.returncode != 0 or "true" not in res.stdout.lower():
            return ""

        git_info = []

        # Git diff
        res_diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5.0,
        )
        if res_diff.returncode == 0 and res_diff.stdout.strip():
            diff_text = res_diff.stdout
            if len(diff_text) > 4000:
                diff_text = diff_text[:4000] + "\n... [Diff truncated due to size] ...\n"
            git_info.append("=== Git Working Copy Diff ===\n" + diff_text)

        # Git recent log
        res_log = subprocess.run(
            ["git", "log", "-n", "5", "--oneline"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=5.0,
        )
        if res_log.returncode == 0 and res_log.stdout.strip():
            git_info.append("=== Recent Git Commits ===\n" + res_log.stdout)

        return "\n\n".join(git_info)
    except Exception:
        pass
    return ""


async def _process_and_finalize_candidate(
    cwd: str,
    candidate_root: Path,
    memory_dir: Path,
    resp_data: dict[str, Any],
    mode: str,
    apply: bool,
    llm_rewrite: bool,
    max_rewrite_tasks: int,
    git_diff_text: str,
    session_text: str,
    tool_calls_text: str,
    snapshot: str,
    context: Any = None,
    fallback_duplicates: int = 0,
    fallback_lines_removed: int = 0,
    fallback_files_touched: list[str] | None = None,
    is_fallback: bool = False,
) -> DreamResult:
    warnings: list[str] = []
    duplicates_found = fallback_duplicates
    lines_removed = fallback_lines_removed
    files_touched = list(fallback_files_touched) if fallback_files_touched else []

    consolidated_files = resp_data.get("consolidated_files", {})
    summaries = resp_data.get("summaries", {})

    for key, new_body in consolidated_files.items():
        if key.startswith("store/"):
            store_path = key[len("store/") :]
            try:
                _validate_store_path(store_path)
            except ValueError as exc:
                warnings.append(
                    f"Consolidation skipped store path with invalid format: {key}. Error: {exc}"
                )
                continue

            segments = store_path.strip("/").split("/")
            filename = segments[-1] + ".md"
            dir_segments = segments[:-1]
            target_dir = candidate_root / "memory-store"
            for seg in dir_segments:
                target_dir = target_dir / seg
            sec_path = target_dir / filename
        else:
            sec_name = key[len("local/") :] if key.startswith("local/") else key
            if not SECTION_PATTERN.match(sec_name):
                warnings.append(f"Consolidation skipped section with invalid name: {key}")
                continue
            sec_path = candidate_root / f"{sec_name}.md"

        if sec_path.exists():
            metadata, old_body = parse_frontmatter(sec_path.read_text(encoding="utf-8"))
        else:
            if key.startswith("store/"):
                metadata = {
                    "store_path": store_path,
                    "title": segments[-1].replace("-", " ").title(),
                    "summary": f"Memory store section for {store_path}.",
                    "priority": "medium",
                    "tags": [],
                    "schema_version": 1.3,
                    "last_updated": now_iso(),
                }
                old_body = ""
            else:
                metadata, old_body = parse_frontmatter(build_empty_section(sec_name))

        proposed_summary = summaries.get(key) or summaries.get(
            key.replace("local/", "").replace("store/", "")
        )
        if proposed_summary and len(proposed_summary) > 5:
            metadata["summary"] = proposed_summary.strip().strip("\"'")
            import hashlib

            metadata["summary_hash"] = hashlib.md5(new_body.strip().encode("utf-8")).hexdigest()

        if old_body.strip() != new_body.strip():
            rel_path = str(sec_path.relative_to(candidate_root)).replace("\\", "/")
            files_touched.append(rel_path)
            duplicates_found += 1
            lines_removed += max(0, len(old_body.splitlines()) - len(new_body.splitlines()))

            sec_path.parent.mkdir(parents=True, exist_ok=True)
            metadata["last_updated"] = now_iso()
            sec_path.write_text(dump_frontmatter(metadata, new_body), encoding="utf-8")

    dream_contradictions = resp_data.get("contradictions", [])
    dream_warnings = resp_data.get("warnings", [])

    for c in dream_contradictions:
        warnings.append(f"Contradiction detected: {c}")
    for w in dream_warnings:
        warnings.append(f"Consolidation warning: {w}")

    # Recalculate hash of consolidated candidates (generated maps excluded — they
    # are derived from the store, which is already part of the hash input)
    final_sections_data = {}
    for path in _iter_markdown_files(candidate_root):
        if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
            continue
        if _is_generated_file(path):
            continue
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        key = _get_section_key(candidate_root, path)
        final_sections_data[key] = body

    import hashlib

    hash_input = []
    for name in sorted(final_sections_data.keys()):
        hash_input.append(f"section:{name}")
        hash_input.append(final_sections_data[name])
    hash_input.append(f"git_diff:{git_diff_text or ''}")
    hash_input.append(f"session:{session_text or ''}")
    hash_input.append(f"tool_calls:{tool_calls_text or ''}")

    if is_fallback:
        current_consolidation_hash = None
    else:
        current_consolidation_hash = hashlib.md5("\n".join(hash_input).encode("utf-8")).hexdigest()

    llm_active = _is_llm_ready(context)
    if llm_active:
        for path in _iter_markdown_files(candidate_root):
            if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
                continue
            if _is_generated_file(path):
                continue  # maps set their own summary at generation time
            try:
                metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                key = _get_section_key(candidate_root, path)

                body_hash = hashlib.md5(body.strip().encode("utf-8")).hexdigest()
                current_hash = metadata.get("summary_hash")
                current_summary = metadata.get("summary")

                is_store = key.startswith("store/")
                store_path = key[len("store/") :] if is_store else ""
                sec_name = key[len("local/") :] if key.startswith("local/") else key

                has_custom_summary = current_summary and current_summary not in {
                    "Map of available project memory sections.",
                    "Project architecture, boundaries, and important system flows.",
                    "Important data models, schemas, and contracts.",
                    "Architecture and product decisions with rationale.",
                    "Known technical debt, risks, and cleanup targets.",
                    "Project-specific vocabulary and domain terms.",
                    "Framework-specific conventions and constraints.",
                    f"Project memory section for {sec_name}.",
                    f"Memory store section for {store_path}.",
                }

                if has_custom_summary and current_hash == body_hash:
                    continue

                sum_prompt = (
                    f"Generate a concise, 1-sentence summary of the following project memory section named `{key}`. "
                    "The summary must be informative, help coding assistants decide when to read this file, and be under 150 characters. "
                    "Output ONLY the summary text, no quotes or intro:\n\n"
                    f"{body}"
                )
                new_summary = await call_llm(
                    sum_prompt, "You are a concise summarizer of software documentation.", context
                )
                new_summary_clean = new_summary.strip().strip("\"'")
                if new_summary_clean and len(new_summary_clean) > 5:
                    metadata["summary"] = new_summary_clean
                    metadata["summary_hash"] = body_hash
                    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
            except Exception as exc:
                warnings.append(f"Failed to generate summary for `{path.name}`: {exc}")

    # Stale section detection in candidate files (generated maps regenerate on
    # every Dream, so a staleness marker would be meaningless on them)
    now_dt = datetime.now(timezone.utc)
    for path in _iter_markdown_files(candidate_root):
        if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
            continue
        if _is_generated_file(path):
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            key = _get_section_key(candidate_root, path)
            lu_str = metadata.get("last_updated")
            if lu_str:
                lu_dt = datetime.fromisoformat(lu_str.replace("Z", "+00:00"))
                if lu_dt.tzinfo is None:
                    lu_dt = lu_dt.replace(tzinfo=timezone.utc)
                if (now_dt - lu_dt).days > 30:
                    if metadata.get("review_status") != "stale":
                        metadata["review_status"] = "stale"
                        path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
                        warnings.append(
                            f"Section `{key}` has not been updated in over 30 days and is marked as stale."
                        )
        except Exception:
            pass

    # Store-first model: rebuild root maps as generated views over memory-store/.
    # Runs in the candidate root (changes flow through the normal diff/apply) and
    # before secret scanning so folded hand-written content is scanned too.
    maps_result = regenerate_maps(candidate_root)
    warnings.extend(maps_result["warnings"])

    # Secret scanning on inputs and candidate files
    redactions = 0
    if git_diff_text:
        _, r_count = redact_secrets(git_diff_text)
        redactions += r_count
    if session_text:
        _, r_count = redact_secrets(session_text)
        redactions += r_count
    if tool_calls_text:
        _, r_count = redact_secrets(tool_calls_text)
        redactions += r_count

    for path in _iter_markdown_files(candidate_root):
        try:
            text = path.read_text(encoding="utf-8")
            redacted, r_count = redact_secrets(text)
            if r_count > 0:
                path.write_text(redacted, encoding="utf-8")
                redactions += r_count
        except Exception:
            pass

    if redactions > 0:
        warnings.append(f"Detected and redacted {redactions} secrets during Dreaming.")

    # Now regenerate the index file in the candidate store
    checked_files = _regenerate_index_root(
        candidate_root,
        mode=mode,
        consolidation_hash=current_consolidation_hash,
        contradictions=dream_contradictions,
        warnings=dream_warnings,
    )

    patch_preview, affected_files = _diff_memory_roots(memory_dir, candidate_root)
    rewrite_tasks = _build_rewrite_tasks(candidate_root, max_rewrite_tasks=max_rewrite_tasks)

    if not apply:
        warnings.append(
            "Dreaming generated a non-destructive candidate store; apply changes explicitly to update live memory."
        )
    if llm_rewrite:
        provider = os.environ.get("MEMORY_FABRIC_LLM_PROVIDER")
        if not provider:
            warnings.append(
                "No LLM provider configured; generated local rewrite tasks for an external agent instead."
            )
        else:
            warnings.append(
                f"Provider `{provider}` is configured, but this build uses agent-assisted rewrite tasks and does not call provider adapters directly."
            )
    elif not os.environ.get("MEMORY_FABRIC_LLM_PROVIDER"):
        warnings.append("No LLM provider configured; ran local maintenance only.")

    changed = False

    # Check if consolidated_memory.md actually changed
    source_compiled = candidate_root / "consolidated_memory.md"
    target_compiled = memory_dir / "consolidated_memory.md"
    compiled_changed = False
    if source_compiled.exists():
        if not target_compiled.exists():
            compiled_changed = True
        else:
            try:
                if source_compiled.read_text(encoding="utf-8") != target_compiled.read_text(
                    encoding="utf-8"
                ):
                    compiled_changed = True
            except Exception:
                compiled_changed = True

    if apply and (affected_files or compiled_changed):
        _apply_candidate_to_live(memory_dir, candidate_root, affected_files)
        changed = True

    consolidation: DreamConsolidation = {
        "duplicates_found": duplicates_found,
        "lines_removed": lines_removed,
        "files_touched": sorted(files_touched),
    }

    return {
        "changed": changed,
        "snapshot": snapshot,
        "warnings": warnings,
        "checked_files": checked_files,
        "candidate_store": str(candidate_root),
        "patch_preview": patch_preview,
        "affected_files": affected_files,
        "consolidation": consolidation,
        "rewrite_tasks": rewrite_tasks if llm_rewrite else [],
        "apply_required": not apply,
        "redactions": redactions,
    }
