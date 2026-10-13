from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from memory_fabric.version import __version__

ROOT = Path(__file__).resolve().parents[1]


class VersionTruthTests(unittest.TestCase):
    """README/ROADMAP/server.json must agree with the shipped version.

    This drifted twice in this repo's own history: README claimed "v0.1.0"
    while pyproject.toml said 0.3.0, then README/ROADMAP claimed 0.7.1 for
    days after PyPI, the MCP registry, and server.json had already moved to
    0.7.2. A manual docs-sync pass fixes the symptom once; this test fixes
    the recurrence.
    """

    def test_readme_status_line_matches_version(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        match = re.search(r"\*\*v(\d+\.\d+\.\d+)\b", readme)
        self.assertIsNotNone(match, "README.md is missing a '**vX.Y.Z' status line")
        assert match is not None
        self.assertEqual(match.group(1), __version__)

    def test_roadmap_header_matches_version(self) -> None:
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        match = re.search(r"Current version:\s*(\d+\.\d+\.\d+)", roadmap)
        self.assertIsNotNone(match, "ROADMAP.md is missing a 'Current version: X.Y.Z' header line")
        assert match is not None
        self.assertEqual(match.group(1), __version__)

    def test_server_json_versions_match(self) -> None:
        data = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], __version__)
        package = data["packages"][0]
        self.assertEqual(package["version"], __version__)
        pin_arg = next(arg for arg in package["runtimeArguments"] if arg.get("name") == "--from")
        self.assertEqual(pin_arg["value"], f"memory-fabric[mcp]=={__version__}")

    def test_mcpb_manifest_rewrite_step_still_exists(self) -> None:
        """mcpb/manifest.json intentionally ships a stale version in-repo —
        release.yml rewrites it to the release tag at pack time, so pinning
        the in-repo value here would just create a release-day chore. Instead,
        assert the rewrite step itself hasn't silently been removed.
        """
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("mcpb/manifest.json", workflow)
        self.assertIn("Sync manifest version to release tag", workflow)


if __name__ == "__main__":
    unittest.main()
