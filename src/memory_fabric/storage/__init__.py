"""Memory Fabric storage package.

Public surface, re-exported here so callers can do `from memory_fabric.storage
import X` without knowing which submodule actually implements it:

- `_shared`: low-level primitives (paths, frontmatter migration, tokens, dedup)
- `lifecycle`: init / sync-agents / status / doctor
- `search`: keyword search
- `sections`: flat `.ai-memory/*.md` section CRUD
- `snapshots`: point-in-time snapshots + rollback
- `store`: semantic `memory-store/` tree CRUD
- `journal`: episodic session journal
- `context`: combined context assembly (token budget, relevance ranking)
- `patch`: dry-run patch preview
- `consolidation`: Dreaming's candidate-store mechanics
- `dream`: Dreaming's public entry points and orchestration
- `maps`: generated root maps rebuilt from memory-store/ subtrees (store-first)
- `migrate`: one-shot split of legacy hand-written sections into store entries
- `capture`: passive commit capture + session/journal enforcement primitives
- `verify`: self-verifying citations — checks `evidence` refs still resolve
- `merge`: semantic 3-way merge for memory files (git merge driver backend)
- `failures`: error -> fix capture with occurrence-counted deduplication
"""

from memory_fabric.llm import call_llm as call_llm
from memory_fabric.storage._shared import (
    STEERING_SECTIONS as STEERING_SECTIONS,
)
from memory_fabric.storage._shared import (
    _get_section_key as _get_section_key,
)
from memory_fabric.storage._shared import (
    _is_ignored_local_memory_path as _is_ignored_local_memory_path,
)
from memory_fabric.storage._shared import (
    _is_steering_file as _is_steering_file,
)
from memory_fabric.storage._shared import (
    _is_store_path as _is_store_path,
)
from memory_fabric.storage._shared import (
    _iter_markdown_files as _iter_markdown_files,
)
from memory_fabric.storage._shared import (
    _path_to_store_path as _path_to_store_path,
)
from memory_fabric.storage._shared import (
    _read_memory_path as _read_memory_path,
)
from memory_fabric.storage._shared import (
    _validate_store_path as _validate_store_path,
)
from memory_fabric.storage._shared import (
    estimate_tokens as estimate_tokens,
)
from memory_fabric.storage.capture import (
    capture_commit as capture_commit,
)
from memory_fabric.storage.capture import (
    capture_stats as capture_stats,
)
from memory_fabric.storage.capture import (
    guard_journal as guard_journal,
)
from memory_fabric.storage.capture import (
    mark_session_start as mark_session_start,
)
from memory_fabric.storage.context import (
    _ordered_context_files as _ordered_context_files,
)
from memory_fabric.storage.context import (
    read_combined_context as read_combined_context,
)
from memory_fabric.storage.dream import (
    apply_dream_results as apply_dream_results,
)
from memory_fabric.storage.dream import (
    dream as dream,
)
from memory_fabric.storage.dream import (
    prepare_dream_payload as prepare_dream_payload,
)
from memory_fabric.storage.failures import write_failure_memory as write_failure_memory
from memory_fabric.storage.journal import write_session_journal as write_session_journal
from memory_fabric.storage.lifecycle import (
    doctor as doctor,
)
from memory_fabric.storage.lifecycle import (
    initialize_memory_fabric as initialize_memory_fabric,
)
from memory_fabric.storage.lifecycle import (
    status as status,
)
from memory_fabric.storage.lifecycle import (
    sync_agent_rules as sync_agent_rules,
)
from memory_fabric.storage.maps import (
    category_fingerprint as category_fingerprint,
)
from memory_fabric.storage.maps import (
    regenerate_maps as regenerate_maps,
)
from memory_fabric.storage.migrate import (
    migrate_memory as migrate_memory,
)
from memory_fabric.storage.patch import propose_memory_patch as propose_memory_patch
from memory_fabric.storage.search import keyword_search as keyword_search
from memory_fabric.storage.sections import (
    flat_write_rejection as flat_write_rejection,
)
from memory_fabric.storage.sections import (
    read_section as read_section,
)
from memory_fabric.storage.sections import (
    write_local_memory as write_local_memory,
)
from memory_fabric.storage.snapshots import (
    create_snapshot as create_snapshot,
)
from memory_fabric.storage.snapshots import (
    list_snapshots as list_snapshots,
)
from memory_fabric.storage.snapshots import (
    prune_dream_artifacts as prune_dream_artifacts,
)
from memory_fabric.storage.snapshots import (
    rollback as rollback,
)
from memory_fabric.storage.store import (
    delete_memory_store as delete_memory_store,
)
from memory_fabric.storage.store import (
    list_memory_store as list_memory_store,
)
from memory_fabric.storage.store import (
    read_memory_store as read_memory_store,
)
from memory_fabric.storage.store import (
    write_memory_store as write_memory_store,
)
from memory_fabric.storage.verify import verify_evidence as verify_evidence
