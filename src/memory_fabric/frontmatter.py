"""Small YAML-frontmatter reader/writer for Memory Fabric files.

This intentionally supports the limited YAML shape Memory Fabric writes:
scalars and inline string lists. It keeps the package dependency-light while
remaining predictable for generated memory files.
"""

from __future__ import annotations

import json
from typing import Any


FRONTMATTER_DELIMITER = "---"


class FrontmatterError(ValueError):
    """Raised when a memory file has invalid frontmatter."""


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith(FRONTMATTER_DELIMITER + "\n"):
        raise FrontmatterError("Missing YAML frontmatter delimiter")

    end_marker = "\n" + FRONTMATTER_DELIMITER + "\n"
    end = normalized.find(end_marker, len(FRONTMATTER_DELIMITER) + 1)
    if end == -1:
        raise FrontmatterError("Missing closing YAML frontmatter delimiter")

    raw_metadata = normalized[len(FRONTMATTER_DELIMITER) + 1 : end]
    body = normalized[end + len(end_marker) :]
    return _parse_metadata(raw_metadata), body


def dump_frontmatter(metadata: dict[str, Any], body: str) -> str:
    lines = [FRONTMATTER_DELIMITER]
    for key, value in metadata.items():
        lines.append(f"{key}: {_format_value(value)}")
    lines.append(FRONTMATTER_DELIMITER)
    clean_body = body.lstrip("\n")
    return "\n".join(lines) + "\n\n" + clean_body.rstrip() + "\n"


def _parse_metadata(raw: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise FrontmatterError(f"Invalid frontmatter line {line_number}: {line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise FrontmatterError(f"Empty frontmatter key on line {line_number}")
        metadata[key] = _parse_value(value.strip())
    return metadata


def _parse_value(value: str) -> Any:
    if value == "":
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(part.strip()) for part in _split_inline_list(inner)]
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def _split_inline_list(inner: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in inner:
        if char in {"'", '"'}:
            quote = None if quote == char else char
        if char == "," and quote is None:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_format_scalar(item) for item in value) + "]"
    return _format_scalar(value)


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return '""'
    text = str(value)
    if text == "":
        return '""'
    if _can_be_bare(text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _can_be_bare(text: str) -> bool:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./")
    return all(char in allowed for char in text)
