"""Memory Fabric storage subpackage.

This package exposes the core memory operations. The implementation is currently
housed in `_core.py` and is being progressively split into focused submodules
(read, write, search, patch, etc.) while maintaining backward compatibility
through this `__init__.py` interface.
"""

from memory_fabric.storage._core import *

# Explicitly import private helpers that CLI or tests rely on
from memory_fabric.storage._core import (
    _iter_markdown_files,
    _path_to_store_path,
    _is_store_path,
    _is_ignored_local_memory_path,
    _ordered_context_files,
    _read_memory_path,
    _validate_store_path,
    call_llm,
)


