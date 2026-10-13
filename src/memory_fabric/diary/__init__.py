"""Local field diary: optional, off-by-default, never sent anywhere.

This package records what Memory Fabric *did* (tools, timings, budget
composition) on the user's machine after they run ``ai-memory diary approve``.
It is not the session journal (what the coding agent accomplished) and it is
not telemetry — there is no upload path.

Public surface is imported from here so CLI and (later) MCP stay thin.
"""

from memory_fabric.diary.consent import (
    APPROVE_NOTICE as APPROVE_NOTICE,
)
from memory_fabric.diary.consent import (
    LEVELS as LEVELS,
)
from memory_fabric.diary.consent import (
    approve as approve,
)
from memory_fabric.diary.consent import (
    consent_path as consent_path,
)
from memory_fabric.diary.consent import (
    diary_dir as diary_dir,
)
from memory_fabric.diary.consent import (
    field_packs_dir as field_packs_dir,
)
from memory_fabric.diary.consent import (
    is_approved as is_approved,
)
from memory_fabric.diary.consent import (
    is_muted as is_muted,
)
from memory_fabric.diary.consent import (
    kill_switch_on as kill_switch_on,
)
from memory_fabric.diary.consent import (
    mute as mute,
)
from memory_fabric.diary.consent import (
    read_consent as read_consent,
)
from memory_fabric.diary.consent import (
    revoke as revoke,
)
from memory_fabric.diary.consent import (
    status as status,
)
from memory_fabric.diary.consent import (
    unmute as unmute,
)
from memory_fabric.diary.consent import (
    wipe as wipe,
)
from memory_fabric.diary.recorder import record as record

__all__ = [
    "APPROVE_NOTICE",
    "LEVELS",
    "approve",
    "consent_path",
    "diary_dir",
    "field_packs_dir",
    "is_approved",
    "is_muted",
    "kill_switch_on",
    "mute",
    "read_consent",
    "record",
    "revoke",
    "status",
    "unmute",
    "wipe",
]
