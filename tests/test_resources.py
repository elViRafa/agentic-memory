"""Tests for MCP Resource registrations in server.py.

These tests exercise the resource handler functions directly — not through the
MCP transport — to keep them fast and dependency-free.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest

# The resource functions are module-level closures defined inside the
# `if FastMCP is not None:` block in server.py.  We import them through the
# module so they can be called like plain functions.
from memory_fabric import server as server_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_resource_fn(name: str):
    """Retrieve a resource handler by its Python function name from server.py."""
    fn = getattr(server_module, name, None)
    if fn is None:
        pytest.skip(f"Resource function '{name}' not found (MCP optional dep missing?)")
    return fn


def _encode(path: str) -> str:
    return urllib.parse.quote(path, safe="")


# ---------------------------------------------------------------------------
# memory_context_resource
# ---------------------------------------------------------------------------


class TestMemoryContextResource:
    def test_returns_context_text_for_initialized_project(self, tmp_path: Path):
        """Returns assembled context text when .ai-memory/ exists."""
        from memory_fabric.storage import initialize_memory_fabric

        initialize_memory_fabric(str(tmp_path))

        fn = _get_resource_fn("memory_context_resource")
        result = fn(_encode(str(tmp_path)))

        assert isinstance(result, str)
        assert len(result) > 0
        # The context bundle always includes the index section marker
        assert "memory-fabric:" in result

    def test_advisory_message_for_uninitialized_project(self, tmp_path: Path):
        """Returns a human-readable advisory when .ai-memory/ is absent."""
        fn = _get_resource_fn("memory_context_resource")
        result = fn(_encode(str(tmp_path)))

        assert "No memory initialized" in result
        assert "ai-memory init" in result

    def test_invalid_path_returns_advisory(self):
        """Returns an advisory (not an exception) for a non-existent path."""
        fn = _get_resource_fn("memory_context_resource")
        non_existent = _encode("/absolutely/does/not/exist/xyz123")
        result = fn(non_existent)

        assert "Invalid project path" in result or "No memory initialized" in result

    def test_windows_path_roundtrip(self, tmp_path: Path):
        """URL-encoded Windows path (backslashes, drive letter) decodes correctly."""
        # Simulate a Windows-style path string even on non-Windows CI.
        # We just test that encoding + decoding is the identity operation.
        win_path = r"C:\Users\rafael\Projetos\my-project"
        encoded = _encode(win_path)

        # Encoded path must not contain backslashes or colons raw
        assert "\\" not in encoded
        assert ":" not in encoded

        decoded = urllib.parse.unquote(encoded)
        assert decoded == win_path

    def test_encoding_is_stable_for_unix_paths(self, tmp_path: Path):
        """Unix paths encode and decode cleanly."""
        unix_path = "/home/user/projects/my-project"
        encoded = _encode(unix_path)
        decoded = urllib.parse.unquote(encoded)
        assert decoded == unix_path


# ---------------------------------------------------------------------------
# memory_index_resource
# ---------------------------------------------------------------------------


class TestMemoryIndexResource:
    def test_returns_index_content_for_initialized_project(self, tmp_path: Path):
        """Returns index.md content when the file exists."""
        from memory_fabric.storage import initialize_memory_fabric

        initialize_memory_fabric(str(tmp_path))

        fn = _get_resource_fn("memory_index_resource")
        result = fn(_encode(str(tmp_path)))

        assert isinstance(result, str)
        assert len(result) > 0
        # index.md always starts with a frontmatter block or heading
        assert "index" in result.lower() or "---" in result

    def test_advisory_message_when_index_missing(self, tmp_path: Path):
        """Returns advisory message when .ai-memory/index.md does not exist."""
        # Create the directory but not index.md
        (tmp_path / ".ai-memory").mkdir()

        fn = _get_resource_fn("memory_index_resource")
        result = fn(_encode(str(tmp_path)))

        assert "No index found" in result
        assert "ai-memory init" in result

    def test_advisory_message_for_uninitialized_project(self, tmp_path: Path):
        """Returns advisory message when .ai-memory/ is completely absent."""
        fn = _get_resource_fn("memory_index_resource")
        result = fn(_encode(str(tmp_path)))

        assert "No index found" in result

    def test_invalid_path_returns_advisory(self):
        """Returns an advisory (not an exception) for a non-existent path."""
        fn = _get_resource_fn("memory_index_resource")
        result = fn(_encode("/absolutely/does/not/exist/xyz123"))

        assert "Invalid project path" in result or "No index found" in result


# ---------------------------------------------------------------------------
# InitResult resource_uris field
# ---------------------------------------------------------------------------


class TestInitResultResourceUris:
    def test_initialize_memory_fabric_tool_returns_resource_uris(self, tmp_path: Path):
        """initialize_memory_fabric_tool includes resource_uris in its result."""
        if server_module.mcp is None:
            pytest.skip("MCP optional dependency not installed")

        from memory_fabric.server import initialize_memory_fabric_tool

        result = initialize_memory_fabric_tool(str(tmp_path))

        assert "resource_uris" in result
        uris = result["resource_uris"]
        assert isinstance(uris, list)
        assert len(uris) == 2

        encoded = _encode(str(tmp_path))
        assert f"memory-fabric://context/{encoded}" in uris
        assert f"memory-fabric://index/{encoded}" in uris

    def test_resource_uris_use_encoded_path(self, tmp_path: Path):
        """resource_uris must not contain raw backslashes or colons (Windows-safe)."""
        if server_module.mcp is None:
            pytest.skip("MCP optional dependency not installed")

        from memory_fabric.server import initialize_memory_fabric_tool

        result = initialize_memory_fabric_tool(str(tmp_path))
        for uri in result["resource_uris"]:
            # Strip the scheme prefix before checking the path segment
            path_segment = uri.split("://", 1)[1].split("/", 1)[1]
            assert "\\" not in path_segment, f"Raw backslash in URI: {uri}"
