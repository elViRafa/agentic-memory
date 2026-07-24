"""Acceptance tests for v1.1 project directives: routing frontmatter,
`sync-agents` composition/markers/teardown, `--check`, and doctor guardrails."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from memory_fabric.frontmatter import dump_frontmatter
from memory_fabric.storage import (
    doctor,
    initialize_memory_fabric,
    read_combined_context,
    sync_agent_rules,
    write_local_memory,
)
from memory_fabric.templates import (
    DIRECTIVES_BLOCK_END,
    DIRECTIVES_BLOCK_START,
    INSTRUCTIONS_BLOCK_START,
)


def _write_directive(
    temp: str,
    section: str,
    body: str,
    sync: bool | str | None = None,
    context: bool | str | None = None,
) -> Path:
    """Hand-write a steering directive file, as a human editing via file tools would."""
    metadata: dict[str, object] = {
        "section": section,
        "summary": f"Directive {section}.",
        "priority": "medium",
        "tags": [section],
        "schema_version": "1.3",
        "last_updated": "2026-07-24T00:00:00+00:00",
        "role": "steering",
    }
    if sync is not None:
        metadata["sync"] = sync
    if context is not None:
        metadata["context"] = context
    path = Path(temp) / ".ai-memory" / f"{section}.md"
    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
    return path


def _disable_builtin_sync(temp: str) -> None:
    """Set `sync: false` on the two scaffolded steering built-ins."""
    for name in ("framework-rules", "ubiquitous-language"):
        _write_directive(temp, name, f"# {name}\n", sync=False)


class IsolatedProjectTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_ctx = tempfile.TemporaryDirectory()
        self._home_ctx = tempfile.TemporaryDirectory()
        # sync_agent_rules resolves cwd internally, so the paths it reports back
        # are canonical. Resolve the temp root here too, or comparing against it
        # breaks on macOS runners (/var -> /private/var) and on Windows runners
        # whose account name needs an 8.3 short-name alias (RUNNER~1 vs
        # runneradmin) — see the same note in tests/test_migrate.py.
        self.temp = str(Path(self._temp_ctx.name).resolve())
        os.environ["MEMORY_FABRIC_HOME"] = self._home_ctx.name
        initialize_memory_fabric(self.temp)

    def tearDown(self) -> None:
        os.environ.pop("MEMORY_FABRIC_HOME", None)
        self._temp_ctx.cleanup()
        self._home_ctx.cleanup()


class SyncCompositionTests(IsolatedProjectTestCase):
    def test_only_sync_true_directives_composed_in_deterministic_order(self) -> None:
        _write_directive(self.temp, "zeta-guidelines", "# Zeta\n\nZeta rule body.\n")
        _write_directive(self.temp, "alpha-guidelines", "# Alpha\n\nAlpha rule body.\n", sync=True)
        _write_directive(self.temp, "hidden-notes", "# Hidden\n\nNever synced.\n", sync=False)

        result = sync_agent_rules(self.temp)
        self.assertTrue(result["success"])
        self.assertEqual(
            result["directives_synced"],
            ["framework-rules", "ubiquitous-language", "alpha-guidelines", "zeta-guidelines"],
        )

        content = (Path(self.temp) / ".agents" / "rules" / "project-directives.md").read_text(
            encoding="utf-8"
        )
        self.assertTrue(content.startswith("---\ntrigger: always_on\n---\n"))
        self.assertIn("Zeta rule body.", content)
        self.assertIn("Alpha rule body.", content)
        self.assertNotIn("Never synced.", content)
        # Frontmatter is stripped from composed bodies.
        self.assertNotIn("schema_version", content)
        self.assertNotIn("last_updated", content)
        # Built-ins first, then user directives, each alphabetical.
        positions = [
            content.index(f"<!-- directive: {name} -->")
            for name in (
                "framework-rules",
                "ubiquitous-language",
                "alpha-guidelines",
                "zeta-guidelines",
            )
        ]
        self.assertEqual(positions, sorted(positions))

        cursor = (Path(self.temp) / ".cursor" / "rules" / "project-directives.mdc").read_text(
            encoding="utf-8"
        )
        self.assertIn("alwaysApply: true", cursor)
        windsurf = (Path(self.temp) / ".windsurf" / "rules" / "project-directives.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("trigger: always_on", windsurf)

    def test_second_sync_run_is_idempotent(self) -> None:
        _write_directive(self.temp, "dev-guidelines", "# Dev\n\nRule.\n")
        first = sync_agent_rules(self.temp)
        self.assertTrue(first["synced_files"])
        second = sync_agent_rules(self.temp)
        self.assertEqual(second["synced_files"], [])


class MarkerBlockTests(IsolatedProjectTestCase):
    def test_agents_md_content_outside_markers_preserved_byte_for_byte(self) -> None:
        agents_md = Path(self.temp) / "AGENTS.md"
        user_top = "# My Project\n\nBuild with `make`.\n"
        agents_md.write_text(user_top, encoding="utf-8")
        _write_directive(self.temp, "dev-guidelines", "First version.\n")

        sync_agent_rules(self.temp)
        text = agents_md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(user_top))
        self.assertIn(DIRECTIVES_BLOCK_START, text)
        self.assertIn("First version.", text)

        # User adds content below the managed block.
        user_bottom = "## Deploy notes\n\nShip on Fridays only ironically.\n"
        agents_md.write_text(text + user_bottom, encoding="utf-8")

        # Edit the directive and re-sync: block replaced in place.
        _write_directive(self.temp, "dev-guidelines", "Second version.\n")
        sync_agent_rules(self.temp)
        text = agents_md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(user_top))
        self.assertTrue(text.endswith(user_bottom))
        self.assertIn("Second version.", text)
        self.assertNotIn("First version.", text)
        self.assertEqual(text.count(DIRECTIVES_BLOCK_START), 1)

    def test_claude_md_legacy_heading_upgraded_to_markers_once(self) -> None:
        claude_md = Path(self.temp) / "CLAUDE.md"
        user_top = "# Team conventions\n\nUse ruff.\n\n"
        legacy = "## Memory Fabric — Semantic Store Agent Instructions\n\nstale old protocol\n"
        claude_md.write_text(user_top + legacy, encoding="utf-8")
        _disable_builtin_sync(self.temp)

        sync_agent_rules(self.temp)
        text = claude_md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(user_top))
        self.assertIn(INSTRUCTIONS_BLOCK_START, text)
        self.assertNotIn("stale old protocol", text)

        # Doctor no longer flags the upgraded file.
        report = doctor(self.temp)
        self.assertFalse(
            [w for w in report["warnings"] if "CLAUDE.md" in w and "managed markers" in w]
        )


class TeardownTests(IsolatedProjectTestCase):
    def test_removing_last_synced_directive_tears_down_outputs(self) -> None:
        _disable_builtin_sync(self.temp)
        _write_directive(self.temp, "dev-guidelines", "# Dev\n\nRule.\n")
        sync_agent_rules(self.temp)

        targets = [
            Path(self.temp) / ".agents" / "rules" / "project-directives.md",
            Path(self.temp) / ".cursor" / "rules" / "project-directives.mdc",
            Path(self.temp) / ".windsurf" / "rules" / "project-directives.md",
        ]
        for target in targets:
            self.assertTrue(target.exists(), target)
        agents_md = Path(self.temp) / "AGENTS.md"
        self.assertIn(DIRECTIVES_BLOCK_START, agents_md.read_text(encoding="utf-8"))

        _write_directive(self.temp, "dev-guidelines", "# Dev\n\nRule.\n", sync=False)
        result = sync_agent_rules(self.temp)
        self.assertEqual(result["directives_synced"], [])
        for target in targets:
            self.assertFalse(target.exists(), target)
        text = agents_md.read_text(encoding="utf-8")
        self.assertNotIn(DIRECTIVES_BLOCK_START, text)
        self.assertNotIn(DIRECTIVES_BLOCK_END, text)
        # Instructions block (init content) is untouched by the teardown.
        self.assertIn(INSTRUCTIONS_BLOCK_START, text)


class SyncCheckTests(IsolatedProjectTestCase):
    def test_check_is_clean_after_sync_and_dirty_after_hand_edit(self) -> None:
        _write_directive(self.temp, "dev-guidelines", "# Dev\n\nRule.\n")
        sync_agent_rules(self.temp)

        clean = sync_agent_rules(self.temp, check=True)
        self.assertTrue(clean["success"])
        self.assertEqual(clean["would_change"], [])

        generated = Path(self.temp) / ".agents" / "rules" / "project-directives.md"
        tampered = generated.read_text(encoding="utf-8") + "\nhand edit\n"
        generated.write_text(tampered, encoding="utf-8")
        dirty = sync_agent_rules(self.temp, check=True)
        self.assertFalse(dirty["success"])
        self.assertIn(str(generated), dirty["would_change"])
        # check mode never writes.
        self.assertEqual(generated.read_text(encoding="utf-8"), tampered)

    def test_check_flags_directive_edited_without_resync(self) -> None:
        _write_directive(self.temp, "dev-guidelines", "# Dev\n\nRule.\n")
        sync_agent_rules(self.temp)
        _write_directive(self.temp, "dev-guidelines", "# Dev\n\nChanged rule.\n")
        dirty = sync_agent_rules(self.temp, check=True)
        self.assertFalse(dirty["success"])
        self.assertTrue(dirty["would_change"])


class ContextRoutingTests(IsolatedProjectTestCase):
    def test_user_directive_defaults_to_context_false(self) -> None:
        _write_directive(self.temp, "dev-guidelines", "Unmistakable directive body.\n")
        bundle = read_combined_context(self.temp)
        self.assertNotIn("local/dev-guidelines", bundle["included_sections"])
        self.assertNotIn("Unmistakable directive body.", bundle["text"])
        # It doesn't fall into the budget-competing pool either.
        self.assertNotIn("local/dev-guidelines", bundle["omitted_sections"])

    def test_builtin_steering_sections_still_loaded_without_flags(self) -> None:
        bundle = read_combined_context(self.temp)
        self.assertIn("local/framework-rules", bundle["included_sections"])
        self.assertIn("local/ubiquitous-language", bundle["included_sections"])

    def test_context_true_directive_loaded_in_full_and_budget_exempt(self) -> None:
        body = "# Rules\n\n" + ("Directive line that must always be present.\n" * 40)
        _write_directive(self.temp, "dev-guidelines", body, context=True)
        bundle = read_combined_context(self.temp, max_tokens=10)
        self.assertIn("local/dev-guidelines", bundle["included_sections"])
        self.assertIn("Directive line that must always be present.", bundle["text"])

    def test_context_false_excluded_from_consolidated_cache(self) -> None:
        from memory_fabric.storage.consolidation import _compile_consolidated_memory

        _write_directive(self.temp, "dev-guidelines", "Unmistakable directive body.\n")
        compiled = _compile_consolidated_memory(Path(self.temp) / ".ai-memory")
        self.assertNotIn("Unmistakable directive body.", compiled)
        self.assertIn("local/framework-rules", compiled)


class WritePathRoutingTests(IsolatedProjectTestCase):
    def test_write_local_memory_persists_boolean_routing_keys(self) -> None:
        content = "---\nrole: steering\nsync: false\ncontext: true\n---\n\n# Dev\n\nRule.\n"
        result = write_local_memory(self.temp, "dev-guidelines", content, mode="replace")
        self.assertTrue(result["changed"])
        text = (Path(self.temp) / ".ai-memory" / "dev-guidelines.md").read_text(encoding="utf-8")
        self.assertIn("sync: false", text)
        self.assertIn("context: true", text)

    def test_write_local_memory_rejects_non_boolean_routing_keys(self) -> None:
        content = "---\nrole: steering\nsync: yes\n---\n\n# Dev\n\nRule.\n"
        with self.assertRaises(ValueError):
            write_local_memory(self.temp, "dev-guidelines", content, mode="replace")


class DoctorGuardrailTests(IsolatedProjectTestCase):
    def test_budget_warning_when_context_surface_exceeds_threshold(self) -> None:
        _write_directive(self.temp, "dev-guidelines", "Long directive body. " * 200, context=True)
        os.environ["MEMORY_FABRIC_DIRECTIVE_BUDGET"] = "100"
        try:
            report = doctor(self.temp)
        finally:
            os.environ.pop("MEMORY_FABRIC_DIRECTIVE_BUDGET", None)
        self.assertTrue(
            [w for w in report["warnings"] if "Always-loaded context surface" in w],
            report["warnings"],
        )

    def test_no_budget_warning_under_threshold(self) -> None:
        report = doctor(self.temp)
        self.assertFalse(
            [w for w in report["warnings"] if "Always-loaded context surface" in w],
            report["warnings"],
        )

    def test_secret_warning_on_planted_token_in_steering_file(self) -> None:
        token = "ghp_" + "Abc123Def456Ghi789Jkl012"
        _write_directive(self.temp, "framework-rules", f"# Rules\n\nUse {token} to auth.\n")
        report = doctor(self.temp)
        self.assertTrue(
            [w for w in report["warnings"] if "potential secret" in w],
            report["warnings"],
        )

    def test_stale_legacy_block_warning_and_clean_fresh_init(self) -> None:
        fresh = doctor(self.temp)
        stale_warnings = [w for w in fresh["warnings"] if "managed markers" in w]
        self.assertFalse(stale_warnings, fresh["warnings"])

        agents_md = Path(self.temp) / "AGENTS.md"
        agents_md.write_text(
            "# Project\n\n## Memory Fabric — Semantic Store Agent Instructions\n\nold\n",
            encoding="utf-8",
        )
        report = doctor(self.temp)
        self.assertTrue(
            [w for w in report["warnings"] if "AGENTS.md" in w and "managed markers" in w],
            report["warnings"],
        )

    def test_routing_key_booleans_validated(self) -> None:
        _write_directive(self.temp, "dev-guidelines", "# Dev\n", sync=True, context=False)
        clean = doctor(self.temp)
        self.assertFalse([e for e in clean["errors"] if "dev-guidelines" in e], clean["errors"])

        _write_directive(self.temp, "dev-guidelines", "# Dev\n", sync="maybe")
        report = doctor(self.temp)
        self.assertTrue(
            [e for e in report["errors"] if "`sync` must be a boolean" in e],
            report["errors"],
        )


if __name__ == "__main__":
    unittest.main()
