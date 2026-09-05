"""Role labels for field-diary histograms.

Known prefixes map to a closed set (architecture, episodic, …). Custom
first segments (`fine-tuning/`, `pretraining/`) stay as a stable slug so
field packs are not a wall of ``other``.
"""

from __future__ import annotations

import re

ROLES = (
    "steering",
    "tier0",
    "map",
    "architecture",
    "decisions",
    "debt",
    "schema",
    "failure",
    "episodic",
    "episodic_commit",
    "rule",
    "other",
)

_ROOT_MAPS = frozenset(
    {
        "architecture",
        "decisions",
        "debt",
        "schemas",
        "index",
        "failures",
        "episodic",
        "rules",
    }
)
_STEERING_LOCAL = frozenset({"framework-rules", "ubiquitous-language", "memory_prompt"})
_STORE_ROLE = {
    "architecture": "architecture",
    "decisions": "decisions",
    "debt": "debt",
    "schemas": "schema",
    "schema": "schema",
    "failures": "failure",
    "failure": "failure",
    "rules": "rule",
    "rule": "rule",
    "episodic": "episodic",
}


def classify_role(key: str) -> str:
    """Map a packer/search section key to a closed role label."""
    text = (key or "").replace("\\", "/").strip().lstrip("/")
    if not text:
        return "other"
    if text.startswith("<!--"):
        return "other"
    if text == "omission-notice":
        return "other"

    if (text in {"global/directives", "global/directive"} or text.endswith("/directives")) and (
        "global/" in text or text.startswith("global")
    ):
        return "tier0"

    if text.startswith("local/"):
        name = text.split("/", 1)[1]
        if name in _STEERING_LOCAL or name.endswith("-guidelines"):
            return "steering"
        if name in _ROOT_MAPS:
            return "map"
        return "other"

    if text.startswith("global/"):
        name = text.split("/", 1)[1]
        if name in {"directives", "directive"}:
            return "tier0"
        return "other"

    store = text
    if store.startswith("store/"):
        store = store[6:]
    elif store.startswith("memory-store/"):
        store = store[13:]

    parts = [p for p in store.split("/") if p]
    if not parts:
        return "other"
    if parts[0] == "index.md" or parts == ["index"]:
        return "map"
    if parts[0] == "episodic":
        if len(parts) > 1 and parts[1] == "commits":
            return "episodic_commit"
        return "episodic"
    known = _STORE_ROLE.get(parts[0])
    if known:
        return known
    slug = re.sub(r"[^a-z0-9]+", "-", parts[0].casefold()).strip("-")
    return (slug[:32] if slug else "other")


def classify_priority(raw: str | None) -> str:
    value = (raw or "medium").strip().lower()
    if value in {"high", "medium", "low"}:
        return value
    return "medium"
