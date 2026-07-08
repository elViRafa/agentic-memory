"""Contract tests: NotRequired fields must stay optional at runtime.

Regression guard for P-13 (real-world test campaign, v0.7.0): contracts.py
used `from __future__ import annotations`, which stringifies annotations and
blinds the TypedDict metaclass to `NotRequired[...]` — every key landed in
`__required_keys__`, so pydantic (used by FastMCP to validate tool results)
rejected legitimate results that omit optional keys. `dream_tool` /
`apply_dream_results_tool` with `apply=True` and no evaluation applied changes
to disk but reported `isError: True` to the MCP client.
"""

import asyncio
import tempfile
import unittest

from memory_fabric import contracts
from memory_fabric.storage import dream, initialize_memory_fabric, write_memory_store

# The single source of truth for which keys are allowed to be absent.
# Adding a NotRequired field to a contract requires registering it here.
EXPECTED_OPTIONAL_KEYS: dict[str, set[str]] = {
    "InitResult": {"resource_uris"},
    "SearchResult": {"backend"},
    "StatusResult": {"capture", "snapshots", "candidates_count"},
    "EvalCheck": {"command"},
    "DreamResult": {"evaluation"},
}

try:
    from pydantic import TypeAdapter

    HAS_PYDANTIC = True
except ImportError:  # pragma: no cover - core-only install
    HAS_PYDANTIC = False


def _all_typed_dicts() -> dict[str, type]:
    found = {}
    for name in dir(contracts):
        obj = getattr(contracts, name)
        if isinstance(obj, type) and hasattr(obj, "__required_keys__"):
            found[name] = obj
    return found


class TestContractOptionalKeys(unittest.TestCase):
    def test_not_required_fields_are_optional_at_runtime(self) -> None:
        """PEP 563 must never be reintroduced in contracts.py (P-13)."""
        typed_dicts = _all_typed_dicts()
        self.assertGreater(len(typed_dicts), 15, "contract discovery looks broken")
        for name, cls in typed_dicts.items():
            expected = EXPECTED_OPTIONAL_KEYS.get(name, set())
            with self.subTest(contract=name):
                self.assertEqual(
                    set(cls.__optional_keys__),
                    expected,
                    f"{name}.__optional_keys__ does not match the NotRequired fields; "
                    "if annotations became strings again (PEP 563), NotRequired is ignored",
                )

    def test_dream_result_without_evaluation_is_required_key_free(self) -> None:
        self.assertIn("evaluation", contracts.DreamResult.__optional_keys__)
        self.assertNotIn("evaluation", contracts.DreamResult.__required_keys__)


@unittest.skipUnless(HAS_PYDANTIC, "pydantic not installed (core-only build)")
class TestDreamResultPydanticValidation(unittest.TestCase):
    def test_applied_dream_without_eval_passes_output_validation(self) -> None:
        """The exact P-13 scenario: apply=True, no evaluation requested.

        FastMCP validates tool results against the return annotation via
        pydantic; this replicates that validation on a real dream result.
        """
        with tempfile.TemporaryDirectory() as temp:
            initialize_memory_fabric(temp)
            write_memory_store(
                temp, "architecture/notes", "# Notes\n\nSome fact.", title="Notes"
            )
            result = asyncio.run(dream(temp, mode="light", apply=True))
            self.assertNotIn("evaluation", result)
            validated = TypeAdapter(contracts.DreamResult).validate_python(result)
            self.assertEqual(validated["changed"], result["changed"])


if __name__ == "__main__":
    unittest.main()
