"""Git merge driver for Memory Fabric files: memory that merges with the code
it describes instead of producing textual conflicts on every timestamp both
branches happened to touch.

Registered via ``ai-memory init --merge-driver`` (writes ``.gitattributes`` +
a *local* git config entry — merge driver commands are per-clone by git's own
design, so this must be re-run after every fresh clone; `.gitattributes`
itself is committed and shared, only the driver command registration is
local). Git then invokes, on every conflicting merge of a matched path::

    <driver-command> <ancestor> <ours> <theirs>

and expects the merged result written into ``<ours>``, exiting 0 for a clean
merge or non-zero (with the file left holding whatever content, typically
conflict markers) otherwise.

Merge strategy, cheapest-safe-outcome first:

1. Identical sides, or only one side changed the body -> take that side.
2. Derived views (``generated: true`` root maps, ``index.md``,
   ``memory-store/index.md``) -> union merge, never a conflict. These files are
   rebuilt from ``memory-store/`` on every Dreaming run, so no textual conflict
   in them is worth a human's attention; the union just keeps them readable
   until the next rebuild. See ``_merge_derived_view`` for why the merged file
   is re-stamped rather than left with stale generation hashes.
3. Both sides purely *appended* to a **non-empty** shared prefix (the
   overwhelmingly common case for memory files: two branches each add new
   facts/journal entries) -> concatenate, deduplicating exact-duplicate lines
   the same way ``write_memory_store``'s append mode already does. The
   non-empty requirement is load-bearing: every string starts with ``""``, so
   an add/add merge (both branches created the file independently, no common
   ancestor) would otherwise take this path with *no* shared prefix at all and
   run whole-file dedup over two unrelated bodies — silently deleting the
   repeated per-record boilerplate that gives record-structured files their
   structure. Those belong in the block merge below.
4. Both sides changed different ``##`` blocks, or appended inside the same one
   (two agents writing separate session entries into the same episodic day
   file, plus an edit to an older entry) -> merge block by block. Record logs
   under ``episodic/commits/`` always take this path, because their unit of
   identity is the record, not the line.
5. Anything else (both sides rewrote the same block) -> defer to
   ``git merge-file`` for git's own standard textual 3-way merge with conflict
   markers. This never makes things worse than not having the driver installed
   at all.

Frontmatter fields we know how to reconcile safely regardless of path:
``tags`` (union), ``priority`` (the more urgent value wins), ``last_updated``
(the later timestamp wins).

``resolve_unmerged`` applies the same resolution to an *in-progress* merge from
the index stages, so a team hitting conflicts can clear them without having
registered the driver beforehand (``ai-memory resolve-conflicts``).
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from memory_fabric.clients import resolve_cli_binary
from memory_fabric.contracts import ConflictResolution, MergeDriverStatus
from memory_fabric.frontmatter import FrontmatterError, dump_frontmatter, parse_frontmatter
from memory_fabric.paths import project_root
from memory_fabric.storage._shared import CURRENT_SCHEMA_VERSION, PRIORITY_ORDER, _jaccard_similar
from memory_fabric.storage.maps import _body_hash

_IDENTITY_FIELDS = ("section", "store_path")

# `.gitattributes` line that points matched paths at this driver, and the local
# git config key that maps the driver name to a command. Both must be present
# for git to actually call us: the first is committed and shared, the second is
# per-clone by git's own design (a repo cannot ship executable merge commands).
GITATTRIBUTES_PATTERN = ".ai-memory/**/*.md merge=memory-fabric"
_ATTRIBUTES_MARKER = "merge=memory-fabric"
_DRIVER_CONFIG_KEY = "merge.memory-fabric.driver"

# `##`..`######` headings delimit the atomic units of a memory file: one written
# fact, decision, or session entry per block.
_HEADING_RE = re.compile(r"^#{2,6}\s+\S")

# Passively captured commit records (`storage/capture.py`). Line-level dedup is
# the wrong tool for these on both counts. Exact match: every record repeats the
# same marker lines by design — `**Files:**`, `- source: passive-capture`, the
# ``` fences around the diffstat — so dropping "duplicates" strips the structure
# off every record but the first. Fuzzy match: the content is file paths and
# diffstats, where two lines being *word-similar* is normal and says nothing
# about them being the same line.
#
# The unit that can actually be deduplicated here is the record, identified by
# the commit hash in its `### commit` heading — which is precisely what
# `_merge_blocks` keys on. So these paths skip the line-level append path
# entirely and merge record by record.
_RECORD_LOG_PREFIX = "episodic/commits/"


def _is_record_log(path_hint: str | None) -> bool:
    """True for record-structured capture logs, which merge by record rather
    than by line (see `_RECORD_LOG_PREFIX`)."""
    if not path_hint:
        return False
    return _RECORD_LOG_PREFIX in str(path_hint).replace("\\", "/")


def _dedupe_append(existing_new: str, incoming_new: str, fuzzy: bool = True) -> str:
    """Concatenate two branches' additions to a shared prefix, dropping lines
    from the incoming side that are exact or near-duplicates of lines already
    kept from the existing side (same filter `write_local_memory` applies).

    ``fuzzy=False`` drops only *exact* duplicates — see `_is_record_log`.
    """
    existing_clean = existing_new.strip("\n")
    if not incoming_new.strip():
        return existing_clean + ("\n" if existing_clean else "")

    existing_lines_lower = {
        line.strip().lower() for line in existing_clean.splitlines() if line.strip()
    }
    existing_normalized = {re.sub(r"^[-*+]\s+", "", line).strip() for line in existing_lines_lower}

    kept: list[str] = []
    for line in incoming_new.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        norm = re.sub(r"^[-*+]\s+", "", stripped).strip().lower()
        if norm in existing_normalized or stripped.lower() in existing_lines_lower:
            continue
        if fuzzy and any(_jaccard_similar(norm, existing) for existing in existing_normalized):
            continue
        kept.append(line)

    incoming_clean = "\n".join(kept).strip("\n")
    if not incoming_clean:
        return existing_clean + "\n" if existing_clean else ""
    if not existing_clean:
        return incoming_clean + "\n"
    return existing_clean + "\n\n" + incoming_clean + "\n"


def _merge_frontmatter(ours_meta: dict[str, Any], theirs_meta: dict[str, Any]) -> dict[str, Any]:
    merged = dict(ours_meta)

    ours_tags_raw = ours_meta.get("tags")
    theirs_tags_raw = theirs_meta.get("tags")
    ours_tags: list[Any] = ours_tags_raw if isinstance(ours_tags_raw, list) else []
    theirs_tags: list[Any] = theirs_tags_raw if isinstance(theirs_tags_raw, list) else []
    if ours_tags or theirs_tags:
        union: list[Any] = []
        for tag in [*ours_tags, *theirs_tags]:
            if tag not in union:
                union.append(tag)
        merged["tags"] = union

    ours_prio = str(ours_meta.get("priority") or "medium")
    theirs_prio = str(theirs_meta.get("priority") or "medium")
    if PRIORITY_ORDER.get(theirs_prio, 1) < PRIORITY_ORDER.get(ours_prio, 1):
        merged["priority"] = theirs_prio

    ours_lu = str(ours_meta.get("last_updated") or "")
    theirs_lu = str(theirs_meta.get("last_updated") or "")
    merged["last_updated"] = (
        max(ours_lu, theirs_lu) if ours_lu and theirs_lu else (ours_lu or theirs_lu)
    )

    merged["schema_version"] = CURRENT_SCHEMA_VERSION

    for key, value in theirs_meta.items():
        if key not in merged:
            merged[key] = value

    return merged


def _is_derived_view(metadata: dict[str, Any], path_hint: str | None) -> bool:
    """True for files Memory Fabric rebuilds from `memory-store/` rather than
    accepting hand-written content into: the `generated: true` root maps
    (`architecture.md`, `failures.md`, ...) and the two discovery indexes.

    `index.md` is recognized from frontmatter alone as well as from the path, so
    clones that registered the driver before it took a `%P` argument still get
    conflict-free indexes.
    """
    if metadata.get("generated"):
        return True
    if str(metadata.get("section") or "") == "index":
        return True
    if str(metadata.get("store_path") or "") == "index":
        return True
    return bool(path_hint) and Path(str(path_hint)).name == "index.md"


def _union_merge_bodies(ancestor: str, ours: str, theirs: str) -> str:
    """Three-way merge that resolves every overlap by keeping both sides.

    Delegates to `git merge-file --union`, which anchors each side's additions
    where they actually belong instead of lumping them at the end. Falls back to
    a plain union of lines when git is unavailable (the driver itself is only
    ever invoked by git, but `resolve_unmerged` and the tests are not).

    Always returns LF-only text. The temp files are written as bytes and the
    result is normalized because `Path.write_text` translates `\\n` to `\\r\\n`
    on Windows, and git faithfully returns the CRLF it was given — while
    `parse_frontmatter` normalizes line endings on the way back in. Hashing the
    un-normalized text would leave every merged map with a `body_hash` that
    cannot match its own body, which is precisely the state that makes
    `regenerate_maps` treat the merge as a hand edit and fold it into the store.
    """
    with tempfile.TemporaryDirectory() as temp:
        paths = {}
        for name, text in (("base", ancestor), ("ours", ours), ("theirs", theirs)):
            path = Path(temp) / name
            path.write_bytes(text.encode("utf-8"))
            paths[name] = str(path)
        try:
            res = subprocess.run(
                [
                    "git",
                    "merge-file",
                    "--union",
                    "-p",
                    paths["ours"],
                    paths["base"],
                    paths["theirs"],
                ],
                capture_output=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            res = None
        if res is not None and res.returncode == 0:
            return res.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")

    ancestor_lines = set(ancestor.splitlines())
    ours_lines = ours.splitlines()
    seen = set(ours_lines)
    merged = list(ours_lines)
    merged.extend(
        line for line in theirs.splitlines() if line not in seen and line not in ancestor_lines
    )
    return "\n".join(merged) + ("\n" if merged else "")


def _merge_derived_view(
    ancestor_body: str,
    ours_meta: dict[str, Any],
    ours_body: str,
    theirs_meta: dict[str, Any],
    theirs_body: str,
) -> str:
    """Union-merge a generated map or index and re-stamp its generation state.

    The re-stamp is not cosmetic. `regenerate_maps` decides whether a map body
    was hand-edited by comparing it against the recorded `body_hash`, and folds
    anything that fails that check into `memory-store/` for review. Leaving the
    pre-merge hash on a merged body would make the next Dreaming run mistake the
    merge for a human edit and copy the union — duplicated bullets and all —
    into the store as a permanent memory. So: record the hash of what we
    actually wrote (not hand-written, nothing to fold) and blank the
    `store_fingerprint` (stale, so the map is rebuilt from the store rather than
    skipped as unchanged).
    """
    merged_body = _union_merge_bodies(ancestor_body, ours_body, theirs_body)
    merged_meta = _merge_frontmatter(ours_meta, theirs_meta)
    if merged_meta.get("generated"):
        merged_meta["body_hash"] = _body_hash(merged_body)
        merged_meta["store_fingerprint"] = ""
    return dump_frontmatter(merged_meta, merged_body)


def _split_blocks(body: str) -> list[tuple[str, str]]:
    """Split a memory body into `(key, text)` blocks, one per `##` heading.

    Content before the first heading is the `""` block. Repeated identical
    headings get distinct keys so they stay separate units instead of collapsing
    into one another when the blocks are matched up across branches.

    Block text is stored without trailing blank lines: the blank line before the
    next heading is separation, not content, and letting it into the comparison
    would make an untouched block look edited on the branch that appended
    something after it. Blocks are rejoined with a blank line between them.
    """
    blocks: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    key = ""
    current: list[str] = []
    for line in body.splitlines(keepends=True):
        if _HEADING_RE.match(line):
            blocks.append((key, "".join(current).rstrip("\n")))
            heading = line.strip()
            occurrence = seen.get(heading, 0)
            seen[heading] = occurrence + 1
            key = heading if occurrence == 0 else f"{heading}\x00{occurrence}"
            current = [line]
        else:
            current.append(line)
    blocks.append((key, "".join(current).rstrip("\n")))
    return blocks


def _merged_block_order(
    ours_blocks: list[tuple[str, str]],
    theirs_blocks: list[tuple[str, str]],
    ancestor_keys: set[str],
) -> list[str]:
    """Ours' block order, with theirs-only blocks spliced in after whichever
    block preceded them on their branch. Blocks missing from ours that the
    ancestor had were deleted by ours, and stay deleted."""
    order = [key for key, _ in ours_blocks]
    ours_keys = {key for key, _ in ours_blocks}
    for index, (key, _) in enumerate(theirs_blocks):
        if key in ours_keys or key in ancestor_keys:
            continue
        anchor = next(
            (prev for prev, _ in reversed(theirs_blocks[:index]) if prev in order),
            None,
        )
        order.insert(order.index(anchor) + 1 if anchor is not None else 0, key)
    return order


def _merge_blocks(
    ancestor_body: str, ours_body: str, theirs_body: str, fuzzy: bool = True
) -> str | None:
    """Merge two branches block by block, so edits that touch different facts in
    the same file never collide. Returns None when a single block was rewritten
    on both sides — the one shape that genuinely needs a human."""
    ancestor = dict(_split_blocks(ancestor_body))
    ours_blocks = _split_blocks(ours_body)
    theirs_blocks = _split_blocks(theirs_body)
    ours = dict(ours_blocks)
    theirs = dict(theirs_blocks)

    merged: list[str] = []
    for key in _merged_block_order(ours_blocks, theirs_blocks, set(ancestor)):
        ours_text = ours.get(key)
        theirs_text = theirs.get(key)
        base_text = ancestor.get(key)

        if ours_text is None:
            if theirs_text:
                merged.append(theirs_text)
            continue
        if theirs_text is None:
            # Theirs deleted a block it never touched otherwise: honor the
            # delete. If ours also changed it, keep ours — dropping a fact
            # somebody just wrote is the more expensive mistake.
            if base_text is not None and ours_text == base_text:
                continue
            merged.append(ours_text)
            continue
        if ours_text == theirs_text or theirs_text == base_text:
            merged.append(ours_text)
            continue
        if ours_text == base_text:
            merged.append(theirs_text)
            continue

        base = base_text or ""
        if ours_text.startswith(base) and theirs_text.startswith(base):
            appended = _dedupe_append(ours_text[len(base) :], theirs_text[len(base) :], fuzzy=fuzzy)
            merged.append((base + appended).rstrip("\n"))
            continue
        return None

    return "\n\n".join(block for block in merged if block) + "\n"


def resolve_conflict(
    ancestor_text: str, ours_text: str, theirs_text: str, path_hint: str | None = None
) -> tuple[str | None, list[str]]:
    """Attempt a semantic 3-way merge of a Memory Fabric markdown file.

    Returns ``(merged_text, warnings)``. ``merged_text`` is ``None`` when the
    change shape isn't safely auto-mergeable — the caller should fall back to
    ``git merge-file`` in that case.
    """
    warnings: list[str] = []
    if ours_text == theirs_text:
        return ours_text, warnings

    try:
        _ancestor_meta, ancestor_body = (
            parse_frontmatter(ancestor_text) if ancestor_text.strip() else ({}, "")
        )
        ours_meta, ours_body = parse_frontmatter(ours_text)
        theirs_meta, theirs_body = parse_frontmatter(theirs_text)
    except FrontmatterError as exc:
        warnings.append(f"unparsed frontmatter on one side; deferring to textual merge: {exc}")
        return None, warnings

    for field in _IDENTITY_FIELDS:
        if field in ours_meta and field in theirs_meta and ours_meta[field] != theirs_meta[field]:
            warnings.append(f"`{field}` differs between branches; deferring to textual merge.")
            return None, warnings

    record_log = _is_record_log(path_hint)

    merged_body: str
    if ours_body == theirs_body:
        merged_body = ours_body
    elif ancestor_body == ours_body:
        merged_body = theirs_body
    elif ancestor_body == theirs_body:
        merged_body = ours_body
    elif _is_derived_view(ours_meta, path_hint) or _is_derived_view(theirs_meta, path_hint):
        # A rebuilt view, not authored content: never worth a conflict.
        return _merge_derived_view(
            ancestor_body, ours_meta, ours_body, theirs_meta, theirs_body
        ), warnings
    elif (
        not record_log
        and ancestor_body.strip()
        and ours_body.startswith(ancestor_body)
        and theirs_body.startswith(ancestor_body)
    ):
        # A real shared prefix, so everything past it is genuinely new on both
        # sides. An *empty* ancestor is not a shared prefix — every string
        # starts with "" — and falls through to the block merge below, which
        # keeps each side's records whole instead of deduping one body against
        # the other. Record logs skip this path for the same reason at every
        # ancestor (see `_RECORD_LOG_PREFIX`).
        ours_new = ours_body[len(ancestor_body) :]
        theirs_new = theirs_body[len(ancestor_body) :]
        merged_body = ancestor_body + _dedupe_append(ours_new, theirs_new)
    else:
        block_merged = _merge_blocks(ancestor_body, ours_body, theirs_body, fuzzy=not record_log)
        if block_merged is None:
            warnings.append(
                "the same block was rewritten on both sides (body changes are not pure "
                "appends); deferring to textual merge."
            )
            return None, warnings
        merged_body = block_merged

    merged_meta = _merge_frontmatter(ours_meta, theirs_meta)
    return dump_frontmatter(merged_meta, merged_body), warnings


def _git_merge_file_fallback(ancestor: str, ours: str, theirs: str) -> int:
    """Run git's own textual 3-way merge, writing conflict markers into `ours`
    on failure. Matches default git behavior exactly — the safety net for any
    change shape our semantic merge doesn't understand."""
    try:
        res = subprocess.run(
            ["git", "merge-file", ours, ancestor, theirs],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ai-memory merge-driver: git merge-file unavailable: {exc}", file=sys.stderr)
        return 1
    return res.returncode


def run(ancestor: str, ours: str, theirs: str, path: str | None = None) -> int:
    """Entry point for `ai-memory merge-driver <ancestor> <ours> <theirs> [path]`.

    `path` is git's `%P` (the real pathname being merged; `ours` is a temp file).
    Optional: clones that registered the driver before `%P` was passed keep
    working, they just lose the path hint.
    """
    ancestor_text = (
        Path(ancestor).read_text(encoding="utf-8", errors="replace")
        if Path(ancestor).exists()
        else ""
    )
    ours_text = Path(ours).read_text(encoding="utf-8", errors="replace")
    theirs_text = (
        Path(theirs).read_text(encoding="utf-8", errors="replace") if Path(theirs).exists() else ""
    )

    merged, warnings = resolve_conflict(ancestor_text, ours_text, theirs_text, path_hint=path)
    label = path or Path(ours).name
    for warning in warnings:
        print(f"ai-memory merge-driver: {label}: {warning}", file=sys.stderr)

    if merged is not None:
        Path(ours).write_text(merged, encoding="utf-8")
        return 0

    return _git_merge_file_fallback(ancestor, ours, theirs)


def _git_output(root: Path, *args: str) -> str | None:
    """Run a read-only git command, returning stdout or None when it fails."""
    try:
        res = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.decode("utf-8", errors="replace")


def resolve_unmerged(cwd: str, memory_only: bool = True) -> ConflictResolution:
    """Resolve the conflicted `.ai-memory` files of an in-progress merge.

    The driver only runs for people who registered it *before* merging. This
    does the same resolution after the fact, reading the three sides from the
    index stages git already recorded (`:1:`/`:2:`/`:3:`), so a team that hit
    conflicts mid-merge can clear them without redoing the merge. Files whose
    conflict needs a human are left untouched and reported.
    """
    root = project_root(cwd)
    resolved: list[str] = []
    deferred: list[str] = []
    warnings: list[str] = []

    if not (root / ".git").exists():
        return {
            "ok": False,
            "resolved": resolved,
            "deferred": deferred,
            "warnings": ["Git repository not found; nothing to resolve."],
        }

    listing = _git_output(root, "diff", "--name-only", "--diff-filter=U", "-z")
    if listing is None:
        return {
            "ok": False,
            "resolved": resolved,
            "deferred": deferred,
            "warnings": ["Could not list unmerged paths; is a merge in progress?"],
        }

    paths = [p for p in listing.split("\0") if p]
    for rel_path in paths:
        if memory_only and not (rel_path.startswith(".ai-memory/") and rel_path.endswith(".md")):
            continue
        # Stage 1 is absent for add/add conflicts — an empty ancestor is exactly
        # the right base there, so a missing stage is not an error.
        ancestor_text = _git_output(root, "show", f":1:{rel_path}") or ""
        ours_text = _git_output(root, "show", f":2:{rel_path}")
        theirs_text = _git_output(root, "show", f":3:{rel_path}")
        if ours_text is None or theirs_text is None:
            deferred.append(rel_path)
            warnings.append(f"{rel_path}: one side is missing (delete/modify); resolve by hand.")
            continue

        merged, file_warnings = resolve_conflict(
            ancestor_text, ours_text, theirs_text, path_hint=rel_path
        )
        warnings.extend(f"{rel_path}: {w}" for w in file_warnings)
        if merged is None:
            deferred.append(rel_path)
            continue

        (root / rel_path).write_text(merged, encoding="utf-8")
        if _git_output(root, "add", "--", rel_path) is None:
            deferred.append(rel_path)
            warnings.append(f"{rel_path}: merged content written but `git add` failed; stage it.")
            continue
        resolved.append(rel_path)

    return {"ok": not deferred, "resolved": resolved, "deferred": deferred, "warnings": warnings}


def merge_driver_status(cwd: str) -> MergeDriverStatus:
    """Report whether this clone will actually run the driver.

    Three things have to hold and they fail independently: `.gitattributes`
    declares the attribute (committed and shared), the clone registers a driver
    command (local, by git's own design), and that command still resolves to
    something executable here. A teammate who clones and merges without the
    second gets plain textual conflicts; a moved venv breaks the third the same
    way, and both are silent — git just writes conflict markers into memory
    files. `active` requires all three.
    """
    root = project_root(cwd)
    gitattributes = root / ".gitattributes"
    declared = False
    if gitattributes.exists():
        try:
            declared = _ATTRIBUTES_MARKER in gitattributes.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            declared = False
    command = (_git_output(root, "config", "--get", _DRIVER_CONFIG_KEY) or "").strip()
    registered = bool(command)
    command_ok = registered and driver_command_resolves(command)
    return {
        "declared": declared,
        "registered": registered,
        "command": command,
        "command_ok": command_ok,
        "active": declared and registered and command_ok,
    }


def install_merge_driver(cwd: str) -> dict[str, Any]:
    """Wire the merge driver into this clone: `.gitattributes` (shared, committed)
    + local `git config` (per-clone, per git's own design — must be re-run after
    every fresh clone)."""
    root = project_root(cwd)
    git_dir = root / ".git"
    if not (git_dir.exists() and git_dir.is_dir()):
        return {
            "ok": False,
            "gitattributes_changed": False,
            "warnings": ["Git repository not found; merge driver was not installed."],
        }

    gitattributes = root / ".gitattributes"
    existing = gitattributes.read_text(encoding="utf-8") if gitattributes.exists() else ""
    changed_attrs = False
    if _ATTRIBUTES_MARKER not in existing:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        gitattributes.write_text(
            existing + separator + GITATTRIBUTES_PATTERN + "\n", encoding="utf-8"
        )
        changed_attrs = True

    _register_driver_command(root)

    return {
        "ok": True,
        "gitattributes_changed": changed_attrs,
        "warnings": [
            "Merge driver registration is per-clone by git's own design: "
            "commit .gitattributes, but re-run `ai-memory init --merge-driver` "
            "(or have teammates run it) after every fresh clone. `ai-memory "
            "doctor` warns when a clone is missing it."
        ],
    }


def build_driver_command() -> str:
    """The shell command git runs for a matched path.

    PATH first, the interpreter that registered it only as a fallback. Git
    stores this per-clone in `.git/config`, where it long outlives the
    environment that wrote it: a hardcoded absolute interpreter path
    (`/home/<user>/<project>/env/bin/python`) breaks the moment the venv is
    moved, rebuilt, or the clone is copied to another machine — and a broken
    driver command is worse than none, because git falls back to a plain
    textual merge and writes conflict markers into memory files. Resolving
    `ai-memory` from PATH at merge time survives all of that; the absolute
    path still covers the case where the CLI is only installed in a venv.

    %P is the real pathname being merged (%A is a temp file), which is what
    lets the driver recognize index.md as a rebuilt view.
    """
    args = "merge-driver '%O' '%A' '%B' '%P'"
    fallback, _warning = resolve_cli_binary()
    if fallback == "ai-memory":
        # No absolute path to fall back to; PATH is all there is.
        return f"ai-memory {args}"
    return (
        f"if command -v ai-memory >/dev/null 2>&1; then ai-memory {args}; "
        f'else "{fallback}" {args}; fi'
    )


def driver_command_executables(command: str) -> list[str]:
    """Every executable the registered driver command could invoke.

    `build_driver_command` emits a two-branch shell command, and clones
    registered by older versions hold a single plain command — both reduce to
    "the word in command position", which is what this collects so `doctor` can
    check that at least one of them actually resolves.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    # Words that end a command and start the next one. `shlex` leaves
    # redirections glued to their operand (`>/dev/null`, `2>&1;`), which is
    # fine: those are never in command position.
    separators = {"if", "then", "else", "elif", "do", ";", "&&", "||", "|", "!"}
    terminators = {"fi", "done", "esac"}
    executables: list[str] = []
    expect_command = True
    for token in tokens:
        if token in terminators:
            expect_command = False
        elif token in separators:
            expect_command = True
        elif expect_command:
            executables.append(token)
            expect_command = False
    return executables


def driver_command_resolves(command: str) -> bool:
    """Whether the registered driver command names something git can execute."""
    if not command.strip():
        return False
    for executable in driver_command_executables(command):
        if shutil.which(executable) or Path(executable).exists():
            return True
    return False


def _register_driver_command(root: Path) -> None:
    """Write the per-clone `merge.memory-fabric.*` git config entries."""
    for key, value in (
        ("merge.memory-fabric.name", "Memory Fabric semantic merge"),
        (_DRIVER_CONFIG_KEY, build_driver_command()),
    ):
        subprocess.run(
            ["git", "config", key, value],
            cwd=root,
            check=False,
            capture_output=True,
        )


def ensure_merge_driver_registered(cwd: str) -> bool:
    """Register the driver in this clone if the repo already asks for it.

    Closes the gap that makes memory files conflict on teams: the person who ran
    `init --merge-driver` commits `.gitattributes`, but every teammate's clone
    starts without the local driver command and silently falls back to textual
    merges. Any later `ai-memory init` in such a clone picks it up. A
    registration that no longer *resolves* (moved venv, `.git/config` carried
    over from another machine) is repaired the same way, since it fails just as
    silently. Returns True when a registration was written.
    """
    status = merge_driver_status(cwd)
    if not status["declared"] or (status["registered"] and status["command_ok"]):
        return False
    root = project_root(cwd)
    if not (root / ".git").is_dir():
        return False
    _register_driver_command(root)
    return merge_driver_status(cwd)["command_ok"]
