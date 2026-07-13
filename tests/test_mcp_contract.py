"""MCP-boundary contract tests.

Every other test file either calls storage functions directly or calls a
`@mcp.tool()`-decorated function as a plain Python callable (see the module
docstrings on test_resources.py and test_contracts.py). Neither path goes
through FastMCP's actual request handling: input/output JSON-schema
validation via `jsonschema`, and the hand-built pydantic model FastMCP
constructs from each tool's TypedDict return annotation
(`_create_model_from_typeddict` in the `mcp` SDK). That is exactly where P-13
hid — `dream_tool`/`apply_dream_results_tool` reported `isError: True` on a
successful `apply=True` call because a required-looking field was left
unpopulated — and where a second instance of the same bug class was found
while writing this file (see TestDreamToolRegressions below): FastMCP gives
every `NotRequired` field `default=None` but keeps its original non-nullable
type annotation, then serializes with `model_dump()` and no `exclude_unset`,
so an omitted optional field reaches the wire as an explicit `null` and fails
its own (non-nullable) schema. `tests/test_contracts.py`'s direct
`TypeAdapter(...).validate_python()` check does not exercise this path,
because pydantic's native TypedDict validation (used there) differs from the
hand-built BaseModel FastMCP uses for a tool's top-level return type.

These tests use `mcp.shared.memory.create_connected_server_and_client_session`
to run a real `ClientSession` against the real server over in-memory
duplex streams — no subprocess, no network, but the full JSON-RPC-shaped
request/response/validation pipeline a real MCP client exercises.
"""

from __future__ import annotations

import asyncio
import functools
import json
import tempfile
import unittest
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, TypeVar

try:
    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_connected_server_and_client_session

    HAS_MCP = True
except ImportError:  # pragma: no cover - core-only install
    HAS_MCP = False

from memory_fabric import server as server_module

T = TypeVar("T")


def async_test(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., T]:
    """Run an async unittest method to completion via asyncio.run.

    Matches this repo's existing convention of wrapping single async calls
    with `asyncio.run(...)` (see test_dream_store.py, test_maps.py), just
    generalized to wrap an entire async test body that needs to hold one
    ClientSession open across several calls.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


@asynccontextmanager
async def mcp_session() -> AsyncIterator[ClientSession]:
    assert server_module.mcp is not None
    async with create_connected_server_and_client_session(server_module.mcp) as session:
        yield session


def structured(result: Any) -> dict[str, Any]:
    """Unwrap a successful CallToolResult's structuredContent, asserting it's present."""
    assert not result.isError, f"expected success, got isError=True: {result.content}"
    assert result.structuredContent is not None
    return result.structuredContent


def error_text(result: Any) -> str:
    assert result.isError, "expected isError=True, got a successful result"
    return " ".join(getattr(block, "text", "") for block in result.content)


@unittest.skipUnless(HAS_MCP, "optional mcp dependency not installed")
class DreamToolRegressions(unittest.TestCase):
    """P-13 and its previously-unnoticed sibling, exercised through the real server."""

    @async_test
    async def test_dream_apply_without_eval_succeeds(self) -> None:
        """The exact P-13 scenario: apply=True, with_eval left at its default (False).

        Regression: DreamResult.evaluation was NotRequired[DreamEvalResult] (no
        `| None`). FastMCP's output model gives the unset field default=None but
        keeps the non-nullable annotation, so model_dump() emitted
        `"evaluation": null` and jsonschema rejected it ("None is not of type
        'object'") even though `dream()` itself succeeded and wrote to disk.
        """
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                await session.call_tool("initialize_memory_fabric_tool", {"cwd": tmp})
                await session.call_tool(
                    "write_memory_store_tool",
                    {"cwd": tmp, "store_path": "decisions/x", "content": "we picked X because Y"},
                )
                result = await session.call_tool(
                    "dream_tool", {"cwd": tmp, "mode": "light", "apply": True}
                )
                data = structured(result)
                # Not an absent key: the mcp SDK's model_dump() always includes
                # NotRequired top-level fields, so "unset" round-trips onto the
                # wire as an explicit `null` rather than a missing key. That's
                # the mechanism the `| None` fix relies on — asserting a fully
                # absent key here would be asserting a contract the wire
                # doesn't actually offer.
                self.assertIsNone(data.get("evaluation"))
                self.assertTrue(data["changed"])

    @async_test
    async def test_dream_apply_with_eval_populates_nested_evaluation(self) -> None:
        """The other branch: with_eval=True must round-trip a populated, non-null
        DreamEvalResult (exercises the nested-object serialization path, not just
        the omitted-field one)."""
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                await session.call_tool("initialize_memory_fabric_tool", {"cwd": tmp})
                await session.call_tool(
                    "write_memory_store_tool",
                    {"cwd": tmp, "store_path": "decisions/x", "content": "we picked X because Y"},
                )
                result = await session.call_tool(
                    "dream_tool",
                    {"cwd": tmp, "mode": "light", "apply": True, "with_eval": True},
                )
                data = structured(result)
                self.assertIn("evaluation", data)
                self.assertIsNotNone(data["evaluation"])
                self.assertIn("score", data["evaluation"])

    @async_test
    async def test_dream_with_eval_but_no_apply_is_a_truthful_warning_not_an_error(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                await session.call_tool("initialize_memory_fabric_tool", {"cwd": tmp})
                result = await session.call_tool(
                    "dream_tool",
                    {"cwd": tmp, "mode": "light", "apply": False, "with_eval": True},
                )
                data = structured(result)
                self.assertTrue(any("requires apply=true" in w for w in data["warnings"]))


@unittest.skipUnless(HAS_MCP, "optional mcp dependency not installed")
class ToolContractTests(unittest.TestCase):
    """One happy-path and one error-path call through the real server, per tool."""

    @async_test
    async def test_initialize_memory_fabric_tool(self) -> None:
        with _tmp_project(init=False) as tmp:
            async with mcp_session() as session:
                ok = structured(
                    await session.call_tool("initialize_memory_fabric_tool", {"cwd": tmp})
                )
                self.assertTrue(ok["created"])
                self.assertEqual(len(ok["resource_uris"]), 2)

                bad = await session.call_tool(
                    "initialize_memory_fabric_tool", {"cwd": str(Path(tmp) / "does-not-exist")}
                )
                self.assertIn("does not exist", error_text(bad))

    @async_test
    async def test_read_combined_context_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                ok = structured(await session.call_tool("read_combined_context_tool", {"cwd": tmp}))
                self.assertIn("text", ok)

                bad = await session.call_tool(
                    "read_combined_context_tool", {"cwd": str(Path(tmp) / "nope")}
                )
                self.assertIn("does not exist", error_text(bad))

    @async_test
    async def test_read_section_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                ok = structured(
                    await session.call_tool("read_section_tool", {"cwd": tmp, "section": "index"})
                )
                self.assertEqual(ok["section"], "index")

                bad = await session.call_tool(
                    "read_section_tool", {"cwd": tmp, "section": "does-not-exist"}
                )
                self.assertIn("not found", error_text(bad).lower())

    @async_test
    async def test_keyword_search_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                await session.call_tool(
                    "write_memory_store_tool",
                    {
                        "cwd": tmp,
                        "store_path": "decisions/auth",
                        "content": "we use OAuth2 for auth",
                    },
                )
                result = await session.call_tool(
                    "keyword_search_tool", {"cwd": tmp, "query": "OAuth2"}
                )
                self.assertFalse(result.isError)
                self.assertIsInstance(result.structuredContent, dict)

                bad = await session.call_tool(
                    "keyword_search_tool", {"cwd": str(Path(tmp) / "nope"), "query": "x"}
                )
                self.assertIn("does not exist", error_text(bad))

    @async_test
    async def test_write_local_memory_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                ok = structured(
                    await session.call_tool(
                        "write_local_memory_tool",
                        {
                            "cwd": tmp,
                            "section": "framework-rules",
                            "content": "Always use type hints.",
                        },
                    )
                )
                self.assertTrue(ok["changed"])

                bad = await session.call_tool(
                    "write_local_memory_tool",
                    {"cwd": str(Path(tmp) / "nope"), "section": "framework-rules", "content": "x"},
                )
                self.assertIn("does not exist", error_text(bad))

    @async_test
    async def test_propose_memory_patch_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                ok = structured(
                    await session.call_tool(
                        "propose_memory_patch_tool",
                        {
                            "cwd": tmp,
                            "instructions": "store: decisions/patch-test\nProposed content.",
                        },
                    )
                )
                self.assertIn("patch", ok)

                bad = await session.call_tool(
                    "propose_memory_patch_tool",
                    {"cwd": str(Path(tmp) / "nope"), "instructions": "store: x\ny"},
                )
                self.assertIn("does not exist", error_text(bad))

    @async_test
    async def test_write_memory_store_and_read_and_list_tools(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                write_ok = structured(
                    await session.call_tool(
                        "write_memory_store_tool",
                        {
                            "cwd": tmp,
                            "store_path": "architecture/core",
                            "content": "# Core\n\nFacts.",
                        },
                    )
                )
                self.assertTrue(write_ok["changed"])

                read_ok = structured(
                    await session.call_tool(
                        "read_memory_store_tool", {"cwd": tmp, "store_path": "architecture/core"}
                    )
                )
                self.assertIn("Facts.", read_ok["text"])

                read_bad = await session.call_tool(
                    "read_memory_store_tool",
                    {"cwd": tmp, "store_path": "architecture/does-not-exist"},
                )
                self.assertIn("not found", error_text(read_bad).lower())

                list_ok = structured(
                    await session.call_tool("list_memory_store_tool", {"cwd": tmp})
                )
                self.assertGreaterEqual(list_ok["total"], 1)

    @async_test
    async def test_delete_memory_store_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                await session.call_tool(
                    "write_memory_store_tool",
                    {"cwd": tmp, "store_path": "decisions/to-delete", "content": "temp"},
                )
                ok = structured(
                    await session.call_tool(
                        "delete_memory_store_tool",
                        {"cwd": tmp, "store_path": "decisions/to-delete"},
                    )
                )
                self.assertTrue(ok["changed"])

                bad = await session.call_tool(
                    "delete_memory_store_tool", {"cwd": tmp, "store_path": "decisions/to-delete"}
                )
                self.assertIn("not found", error_text(bad).lower())

    @async_test
    async def test_prepare_and_apply_dream_results_tools(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                await session.call_tool(
                    "write_memory_store_tool",
                    {
                        "cwd": tmp,
                        "store_path": "architecture/notes",
                        "content": "Original content.",
                    },
                )
                payload = structured(
                    await session.call_tool(
                        "prepare_dream_payload_tool", {"cwd": tmp, "mode": "light"}
                    )
                )
                self.assertIn("candidate_store", payload)

                llm_response = json.dumps(
                    {
                        "consolidated_files": {
                            "store/architecture/notes": "# Notes\n\nConsolidated by client."
                        },
                        "summaries": {"store/architecture/notes": "Client generated summary."},
                    }
                )
                applied = structured(
                    await session.call_tool(
                        "apply_dream_results_tool",
                        {
                            "cwd": tmp,
                            "candidate_store": payload["candidate_store"],
                            "llm_response": llm_response,
                            "mode": "light",
                            "apply": True,
                        },
                    )
                )
                self.assertTrue(applied["changed"])

                bad = await session.call_tool(
                    "apply_dream_results_tool",
                    {
                        "cwd": tmp,
                        "candidate_store": "totally-bogus-candidate",
                        "llm_response": "{}",
                        "mode": "light",
                        "apply": True,
                    },
                )
                self.assertIn("not found", error_text(bad).lower())

    @async_test
    async def test_evaluate_memory_fabric_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                ok = structured(
                    await session.call_tool("evaluate_memory_fabric_tool", {"cwd": tmp})
                )
                self.assertIn("score", ok)

                bad = await session.call_tool(
                    "evaluate_memory_fabric_tool", {"cwd": str(Path(tmp) / "nope")}
                )
                self.assertIn("does not exist", error_text(bad))

    @async_test
    async def test_evaluate_dream_quality_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                dream_result = structured(
                    await session.call_tool(
                        "dream_tool", {"cwd": tmp, "mode": "light", "apply": True}
                    )
                )
                snapshot = dream_result["snapshot"]
                self.assertTrue(snapshot)

                ok = structured(
                    await session.call_tool(
                        "evaluate_dream_quality_tool", {"cwd": tmp, "snapshot": snapshot}
                    )
                )
                self.assertIn("delta", ok)

                bad = await session.call_tool(
                    "evaluate_dream_quality_tool",
                    {"cwd": tmp, "snapshot": "no-such-snapshot"},
                )
                self.assertIn("not found", error_text(bad).lower())

    @async_test
    async def test_write_session_journal_tool(self) -> None:
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                ok = structured(
                    await session.call_tool(
                        "write_session_journal_tool",
                        {"cwd": tmp, "summary": "Did some work this session."},
                    )
                )
                self.assertTrue(ok["changed"])

                bad = await session.call_tool(
                    "write_session_journal_tool",
                    {"cwd": str(Path(tmp) / "nope"), "summary": "x"},
                )
                self.assertIn("does not exist", error_text(bad))

    @async_test
    async def test_write_failure_memory_tool(self) -> None:
        """Bonus: also regression-guards P-07 dedup through the real MCP path."""
        with _tmp_project() as tmp:
            async with mcp_session() as session:
                first = structured(
                    await session.call_tool(
                        "write_failure_memory_tool",
                        {
                            "cwd": tmp,
                            "error_summary": "ValueError: Invalid isoformat string: 2026-01-01",
                            "fix_summary": "Validate the date format before parsing.",
                        },
                    )
                )
                self.assertTrue(first["changed"])

                second = structured(
                    await session.call_tool(
                        "write_failure_memory_tool",
                        {
                            "cwd": tmp,
                            "error_summary": "ValueError: Invalid isoformat string: 2026/07/20",
                            "fix_summary": "Validate the date format before parsing.",
                        },
                    )
                )
                self.assertEqual(first["path"], second["path"])

                bad = await session.call_tool(
                    "write_failure_memory_tool",
                    {"cwd": str(Path(tmp) / "nope"), "error_summary": "x", "fix_summary": "y"},
                )
                self.assertIn("does not exist", error_text(bad))


@contextmanager
def _tmp_project(init: bool = True) -> Iterator[str]:
    """Yield a fresh temp project dir, optionally pre-initialized on disk.

    Initialization for the `init=True` case is done by calling the storage
    layer directly (not through MCP) purely to set up fixture state cheaply;
    the tests themselves always go through the MCP tool for the behavior
    under test.
    """
    with tempfile.TemporaryDirectory() as tmp:
        if init:
            from memory_fabric.storage import initialize_memory_fabric

            initialize_memory_fabric(tmp)
        yield tmp


if __name__ == "__main__":
    unittest.main()
