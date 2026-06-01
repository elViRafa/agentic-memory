"""Secret redaction helpers used before writes and provider calls."""

from __future__ import annotations

import math
import re


SECRET_VALUE = "[REDACTED_SECRET]"

_KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b(?P<key>[A-Z0-9_.-]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PRIVATE[_-]?KEY)[A-Z0-9_.-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[A-Za-z0-9_./+=:-]{12,})"
    r"(?P=quote)"
)

_TOKEN_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]

_HIGH_ENTROPY_PATTERN = re.compile(r"\b[A-Za-z0-9+/=_-]{40,}\b")


def redact_secrets(text: str) -> tuple[str, int]:
    """Redact common secret shapes and return the number of replacements."""

    redactions = 0

    def replace_key_value(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        quote = match.group("quote")
        return f"{match.group('key')}{match.group('sep')}{quote}{SECRET_VALUE}{quote}"

    redacted = _KEY_VALUE_PATTERN.sub(replace_key_value, text)

    for pattern in _TOKEN_PATTERNS:
        redacted, count = pattern.subn(SECRET_VALUE, redacted)
        redactions += count

    def replace_entropy(match: re.Match[str]) -> str:
        nonlocal redactions
        value = match.group(0)
        if _looks_like_secret(value):
            redactions += 1
            return SECRET_VALUE
        return value

    redacted = _HIGH_ENTROPY_PATTERN.sub(replace_entropy, redacted)
    return redacted, redactions


def _looks_like_secret(value: str) -> bool:
    if len(value) < 40:
        return False
    if not any(char.isdigit() for char in value):
        return False
    if not any(char.islower() for char in value):
        return False
    if not any(char.isupper() for char in value):
        return False
    return _shannon_entropy(value) >= 3.5


def _shannon_entropy(value: str) -> float:
    counts = {char: value.count(char) for char in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())
