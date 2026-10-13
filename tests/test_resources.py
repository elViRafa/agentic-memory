"""Tests for MCP Resource registrations in server.py.

These tests exercise the resource handler functions directly — not through the
MCP transport — to keep them fast. Unittest so ``python -m unittest discover``
works without the optional ``pytest`` extra; CI still runs them via pytest.
"""

from __future__ import annotations

import tempfile
import unittest
import urllib.parse
from pathlib import Path

from memory_fabric import server as server_module


def _get_resource_fn(name: str):
    """Retrieve a resource handler by its Python function name from server.py."""
    fn = getattr(server_module, name, None)
    if fn is None:
        raise unittest.SkipTest(
            f"Resource function '{name}' not found (MCP optional dep missing?)"
        )
    return fn


def _encode(path: str) -> str:
    return urllib.parse.quote(path, safe="")


class MemoryContextResourceTests(unittest.TestCase):
    def test_returns_context_text_for_initialized_project(self) -> None:
        from memory_fabric.storage import initialize_memory_fabric

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            fn = _get_resource_fn("memory_context_resource")
            result = fn(_encode(temp))
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)
            self.assertIn("memory-fabric:", result)

    def test_advisory_message_for_uninitialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fn = _get_resource_fn("memory_context_resource")
            result = fn(_encode(temp))
            self.assertIn("No memory initialized", result)
            self.assertIn("ai-memory init", result)

    def test_invalid_path_returns_advisory(self) -> None:
        fn = _get_resource_fn("memory_context_resource")
        result = fn(_encode("/absolutely/does/not/exist/xyz123"))
        self.assertTrue(
            "Invalid project path" in result or "No memory initialized" in result
        )

    def test_windows_path_roundtrip(self) -> None:
        win_path = r"C:\Users\rafael\Projetos\my-project"
        encoded = _encode(win_path)
        self.assertNotIn("\\", encoded)
        self.assertNotIn(":", encoded)
        self.assertEqual(urllib.parse.unquote(encoded), win_path)

    def test_encoding_is_stable_for_unix_paths(self) -> None:
        unix_path = "/home/user/projects/my-project"
        self.assertEqual(urllib.parse.unquote(_encode(unix_path)), unix_path)


class MemoryIndexResourceTests(unittest.TestCase):
    def test_returns_index_content_for_initialized_project(self) -> None:
        from memory_fabric.storage import initialize_memory_fabric

        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            fn = _get_resource_fn("memory_index_resource")
            result = fn(_encode(temp))
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)
            self.assertTrue("index" in result.lower() or "---" in result)

    def test_advisory_message_when_index_missing(self) -> None:
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / ".ai-memory").mkdir()
            fn = _get_resource_fn("memory_index_resource")
            result = fn(_encode(temp))
            self.assertIn("No index found", result)
            self.assertIn("ai-memory init", result)

    def test_advisory_message_for_uninitialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fn = _get_resource_fn("memory_index_resource")
            result = fn(_encode(temp))
            self.assertIn("No index found", result)

    def test_invalid_path_returns_advisory(self) -> None:
        fn = _get_resource_fn("memory_index_resource")
        result = fn(_encode("/absolutely/does/not/exist/xyz123"))
        self.assertTrue("Invalid project path" in result or "No index found" in result)


class InitResultResourceUrisTests(unittest.TestCase):
    def test_initialize_memory_fabric_tool_returns_resource_uris(self) -> None:
        if server_module.mcp is None:
            self.skipTest("MCP optional dependency not installed")

        from memory_fabric.server import initialize_memory_fabric_tool

        with tempfile.TemporaryDirectory() as temp:
            # initialize resolves cwd (Windows short vs long paths differ).
            resolved = str(Path(temp).resolve())
            result = initialize_memory_fabric_tool(temp)
            self.assertIn("resource_uris", result)
            uris = result["resource_uris"]
            self.assertIsInstance(uris, list)
            self.assertEqual(len(uris), 2)
            encoded = _encode(resolved)
            self.assertIn(f"memory-fabric://context/{encoded}", uris)
            self.assertIn(f"memory-fabric://index/{encoded}", uris)

    def test_resource_uris_use_encoded_path(self) -> None:
        if server_module.mcp is None:
            self.skipTest("MCP optional dependency not installed")

        from memory_fabric.server import initialize_memory_fabric_tool

        with tempfile.TemporaryDirectory() as temp:
            result = initialize_memory_fabric_tool(temp)
            for uri in result["resource_uris"]:
                path_segment = uri.split("://", 1)[1].split("/", 1)[1]
                self.assertNotIn("\\", path_segment, f"Raw backslash in URI: {uri}")


if __name__ == "__main__":
    unittest.main()
