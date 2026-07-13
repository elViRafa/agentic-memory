"""Shared internals that `dream()`, `prepare_dream_payload()`, and
`apply_dream_results()` all funnel through: LLM readiness/response parsing,
git context gathering, and finalizing a candidate store's consolidation result.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_fabric.contracts import DreamConsolidation, DreamResult
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.llm import call_llm
from memory_fabric.security import redact_secrets
from memory_fabric.storage._shared import (
    SECTION_PATTERN,
    _get_section_key,
    _is_generated_file,
    _is_ignored_local_memory_path,
    _iter_markdown_files,
    _jaccard_similar,
    _path_to_store_path,
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
            with contextlib.suppress(json.JSONDecodeError):
                resp_data = json.loads(cleaned_resp[start : end + 1])

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


# Files whose diffs are noise, not knowledge: dependency lockfiles, vendored
# trees, build output, minified assets. Skipped so real signal survives the budget.
_DIFF_SKIP_BASENAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Cargo.lock",
        "go.sum",
        "composer.lock",
        "Gemfile.lock",
        "uv.lock",
    }
)
_DIFF_SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".snap", ".lock")
_DIFF_SKIP_DIRS = (
    "node_modules/",
    "dist/",
    "build/",
    "vendor/",
    ".venv/",
    "__pycache__/",
)


def _should_skip_diff_path(path: str) -> bool:
    p = path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    if base in _DIFF_SKIP_BASENAMES:
        return True
    if p.endswith(_DIFF_SKIP_SUFFIXES):
        return True
    return any(seg in p for seg in _DIFF_SKIP_DIRS)


def _summarize_diff(diff_text: str, per_file: int = 1500, total_cap: int = 6000) -> str:
    """Budget a raw ``git diff`` per file instead of one global cut.

    Each file's hunk is truncated to ``per_file`` chars; generated/lock/vendored
    files are elided to a one-line marker; the whole thing is capped at
    ``total_cap``. This keeps signal from many changed files instead of letting
    a single large file consume the entire window.
    """
    parts = re.split(r"(?m)(?=^diff --git )", diff_text)
    kept: list[str] = []
    used = 0
    for part in parts:
        if not part.strip():
            continue
        match = re.match(r"diff --git a/(.+?) b/(.+)", part)
        path = match.group(2).strip() if match else ""
        if path and _should_skip_diff_path(path):
            kept.append(
                f"diff --git a/{path} b/{path}\n... [skipped: generated/lock/vendored] ...\n"
            )
            continue
        if len(part) > per_file:
            part = part[:per_file] + f"\n... [file diff truncated at {per_file} chars] ...\n"
        if used + len(part) > total_cap:
            kept.append("... [remaining diff truncated due to total size] ...\n")
            break
        kept.append(part)
        used += len(part)
    return "".join(kept)


def build_consolidation_prompt(
    sections_data: dict[str, str],
    git_diff_text: str,
    session_text: str,
    tool_calls_text: str,
    include_summaries: bool,
) -> str:
    """Single source of truth for the Dreaming consolidation prompt.

    Store-first + capture-reliability: the prompt asks the LLM not only to
    consolidate existing memory but to EXTRACT new store entries from the diff
    and transcripts — the mechanism that turns a raw commit trail into durable,
    categorized memories.
    """
    prompt = (
        "You are an AI memory consolidation assistant. Below is the project memory index and section bodies.\n"
        "Review the sections to: (1) merge redundant facts or guidelines, (2) resolve overlapping points, "
        "(3) check for contradiction warnings between files, and (4) incorporate recent Git logs/transcripts if provided.\n"
        "Specifically, extract dates, specific IDs, and missing metadata from the recent transcripts or logs "
        "to enrich the relevant memory sections. If a memory file is outdated or stale, clean it up or propose removing "
        "redundancies.\n"
        "(5) EXTRACT NEW MEMORIES: when the Git diff, commits, or transcripts contain durable facts absent from memory "
        "— decisions made and their rationale, bugs fixed, architectural choices, APIs to avoid — propose them as NEW "
        "entries under `store/<category>/<slug>` keys in `consolidated_files` (lowercase slug, e.g. "
        "`store/decisions/jwt-refresh`). Do not restrict yourself to editing existing sections.\n"
        "Note: sections with `local/` prefix are flat top-level memory files, and sections with `store/` prefix "
        "are semantic memory store files located in nested directories. Preserve the exact key prefixes in your response.\n\n"
    )
    if git_diff_text:
        prompt += f"Recent Git Diff/Logs:\n{git_diff_text}\n\n"
    if session_text:
        prompt += f"Recent Session Transcripts:\n{session_text}\n\n"
    if tool_calls_text:
        prompt += f"Recent Tool Calls:\n{tool_calls_text}\n\n"

    prompt += "Active Project Memory Sections:\n" + json.dumps(sections_data, indent=2) + "\n\n"
    prompt += (
        "Output a JSON object ONLY, with no surrounding markdown or explanation, matching this schema:\n"
        "{\n"
        '  "consolidated_files": {\n'
        '    "section_name": "clean markdown body text",\n'
        "    ...\n"
        "  },\n"
    )
    if include_summaries:
        prompt += (
            '  "summaries": {\n'
            '    "section_name": "concise 1-sentence summary (under 150 chars) mapping the section name to summary text",\n'
            "    ...\n"
            "  },\n"
        )
    prompt += (
        '  "contradictions": ["description of contradiction", ...],\n'
        '  "warnings": ["warning note", ...]\n'
        "}"
    )
    return prompt


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
            diff_text = _summarize_diff(res_diff.stdout)
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
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


# Cap the number of store files the O(n^2) pair scan considers — the check is
# a best-effort net, not an index; huge stores must not slow every dream down.
_CONTRADICTION_SCAN_LIMIT = 150
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _detect_numeric_contradictions(memory_root: Path) -> list[str]:
    """Deterministic contradiction heuristic over the memory store (P-10).

    Flags pairs of store files whose bodies overlap in wording (Jaccard) but
    disagree on numbers. Purely advisory; messages avoid commas/colons so the
    list round-trips cleanly through inline-frontmatter storage.
    """
    store_root = memory_root / "memory-store"
    if not store_root.is_dir():
        return []
    entries: list[tuple[str, str, frozenset[str]]] = []
    for path in sorted(_iter_markdown_files(store_root)):
        if path.name == "index.md":
            continue
        relative = path.relative_to(store_root)
        # Episodic journals/commit logs and failure records are full of
        # incidental numbers (dates, line numbers) — comparing them would be
        # all noise.
        if relative.parts and relative.parts[0] in {"episodic", "failures"}:
            continue
        try:
            _meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue  # advisory heuristic scan; a skipped file just doesn't participate
        numbers = frozenset(_NUMBER_RE.findall(body))
        if not numbers:
            continue
        entries.append((_path_to_store_path(store_root, path), body, numbers))
        if len(entries) >= _CONTRADICTION_SCAN_LIMIT:
            break

    contradictions: list[str] = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            sp_a, body_a, nums_a = entries[i]
            sp_b, body_b, nums_b = entries[j]
            if nums_a == nums_b:
                continue
            if not _jaccard_similar(body_a, body_b, threshold=0.3):
                continue
            only_a = " / ".join(sorted(nums_a - nums_b)[:3]) or "-"
            only_b = " / ".join(sorted(nums_b - nums_a)[:3]) or "-"
            contradictions.append(
                f"`{sp_a}` and `{sp_b}` cover similar content but state different numbers "
                f"({only_a} vs {only_b}) - review for conflict [heuristic]"
            )
    return contradictions


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

    dream_contradictions = list(resp_data.get("contradictions", []) or [])
    dream_warnings = resp_data.get("warnings", [])

    for c in dream_contradictions:
        warnings.append(f"Contradiction detected: {c}")
    for w in dream_warnings:
        warnings.append(f"Consolidation warning: {w}")

    # Deterministic contradiction net (P-10): small local models routinely
    # return an empty `contradictions` list even for planted conflicts, and
    # that failure is silent. Independently of what (or whether) an LLM
    # answered, flag store-file pairs whose prose overlaps but whose numbers
    # diverge (e.g. one memory says a cache TTL is 3600 seconds, another 60).
    for c in _detect_numeric_contradictions(candidate_root):
        if c not in dream_contradictions:
            dream_contradictions.append(c)
            warnings.append(f"Contradiction detected (heuristic): {c}")

    # Recalculate hash of consolidated candidates (generated maps excluded — they
    # are derived from the store, which is already part of the hash input)
    final_sections_data = {}
    for path in _iter_markdown_files(candidate_root):
        if path.name == "index.md" or _is_ignored_local_memory_path(candidate_root, path):
            continue
        if _is_generated_file(path):
            continue
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
            warnings.append(
                f"Skipped {path.relative_to(candidate_root)} during consolidation: {exc}"
            )
            continue
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
            except Exception as exc:  # noqa: BLE001 - reported via warnings, not swallowed.
                warnings.append(f"Failed to generate summary for `{path.name}`: {exc}")

    # Stale section detection in candidate files (generated maps regenerate on
    # every Dream, so a staleness marker would be meaningless on them)
    now_dt = datetime.now(UTC)
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
                    lu_dt = lu_dt.replace(tzinfo=UTC)
                if (now_dt - lu_dt).days > 30 and metadata.get("review_status") != "stale":
                    metadata["review_status"] = "stale"
                    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
                    warnings.append(
                        f"Section `{key}` has not been updated in over 30 days and is marked as stale."
                    )
        except (OSError, UnicodeDecodeError, FrontmatterError, ValueError) as exc:
            warnings.append(f"Skipped staleness check for {path.name}: {exc}")

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
        except (OSError, UnicodeDecodeError) as exc:
            # Security-relevant: a file that fails the redaction pass keeps
            # whatever secrets it had, so this must not be silent.
            warnings.append(f"Secret-redaction scan skipped {path.name}: {exc}")

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
        task_count = len(rewrite_tasks)
        if not provider:
            warnings.append(
                "No LLM provider configured; generated local rewrite tasks for an external agent instead."
            )
        elif task_count:
            # P-09: the old single-sentence warning claimed no provider adapter
            # was called at all, even though the consolidation step above DID
            # call the provider directly — only the rewrite tasks are
            # agent-assisted. Say exactly which step used what.
            consolidation_note = (
                f"Consolidation called provider `{provider}` directly. "
                if not is_fallback
                else f"Provider `{provider}` is configured but consolidation used the local fallback. "
            )
            warnings.append(
                consolidation_note
                + f"The {task_count} rewrite_tasks in this result are agent-assisted: returned as "
                "instructions for the calling agent, not executed via the provider."
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
            except (OSError, UnicodeDecodeError) as exc:
                # Fail toward re-applying rather than silently keeping a stale
                # compiled view; still worth a trace since it's unexpected.
                warnings.append(f"Could not compare consolidated_memory.md: {exc}")
                compiled_changed = True

    if apply and (affected_files or compiled_changed):
        _apply_candidate_to_live(memory_dir, candidate_root, affected_files)
        changed = True

    if apply:
        # Retention (P-11): every dream leaves one snapshot + one candidate
        # copy of the whole memory tree behind; keep only the newest few.
        # Best-effort — an applied dream must never fail over cleanup.
        try:
            from memory_fabric.storage.snapshots import prune_dream_artifacts

            prune_dream_artifacts(
                cwd="",
                protect={snapshot or "", candidate_root.name},
                memory_dir=memory_dir,
            )
        except Exception as exc:  # noqa: BLE001 - cleanup is genuinely best-effort; reported, never fatal.
            warnings.append(f"Snapshot/candidate retention cleanup failed (non-fatal): {exc}")

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
