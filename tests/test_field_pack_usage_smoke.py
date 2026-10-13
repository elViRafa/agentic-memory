"""CI wrapper for scripts/field_pack_usage_smoke.py (synthetic mode only)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


def _load_smoke_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parent.parent / "scripts" / "field_pack_usage_smoke.py"
    )
    spec = importlib.util.spec_from_file_location("field_pack_usage_smoke", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_smoke = _load_smoke_module()


class FieldPackUsageSmokeTests(unittest.TestCase):
    def test_synthetic_smoke_exits_zero(self) -> None:
        code = _smoke.main([])
        self.assertEqual(code, 0, "field_pack_usage_smoke synthetic mode must exit 0")


if __name__ == "__main__":
    unittest.main()
