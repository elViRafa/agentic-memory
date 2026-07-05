"""Memory Fabric public package API."""

from memory_fabric.version import __version__
from memory_fabric.storage import (
    doctor,
    dream,
    initialize_memory_fabric,
    keyword_search,
    propose_memory_patch,
    read_combined_context,
    read_section,
    rollback,
    status,
    write_local_memory,
    prepare_dream_payload,
    apply_dream_results,
)
from memory_fabric.eval import (
    evaluate_dream_quality,
    evaluate_memory_fabric,
    evaluate_memory_quality,
)

__all__ = [
    "__version__",
    "doctor",
    "dream",
    "evaluate_dream_quality",
    "evaluate_memory_fabric",
    "evaluate_memory_quality",
    "initialize_memory_fabric",
    "keyword_search",
    "propose_memory_patch",
    "read_combined_context",
    "read_section",
    "rollback",
    "status",
    "write_local_memory",
    "prepare_dream_payload",
    "apply_dream_results",
]
