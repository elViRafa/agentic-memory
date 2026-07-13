"""End-to-end git hook test: a real `git commit`, not just hook-file content.

test_memory_fabric.py's `test_init_install_hooks_creates_post_commit_hook` and
`test_init_install_hooks_is_idempotent` only assert what the generated hook
*file* contains, against a fake `.git/` directory (`git_dir.mkdir()` — never a
real repo, so no hook ever actually runs). That was the gap behind P-04: hooks
that read perfectly correct but silently no-op in a real commit because the
resolved `ai-memory` binary isn't on PATH in the shell git spawns. This file
closes that gap by running a real `git init` + `git commit` and checking the
hook's actual side effect (an episodic capture record) landed on disk.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from memory_fabric.storage import initialize_memory_fabric

HAS_GIT = shutil.which("git") is not None


def _run_git(cwd: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


@unittest.skipUnless(HAS_GIT, "git is not available on PATH")
class HookEndToEndTests(unittest.TestCase):
    def test_real_commit_triggers_passive_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            init = _run_git(temp, "init")
            self.assertEqual(init.returncode, 0, init.stderr)
            _run_git(temp, "config", "user.email", "test@example.invalid")
            _run_git(temp, "config", "user.name", "Memory Fabric Test")

            initialize_memory_fabric(temp, install_hooks=True)
            post_commit = Path(temp) / ".git" / "hooks" / "post-commit"
            self.assertTrue(post_commit.exists())

            (Path(temp) / "README.md").write_text("# Test project\n", encoding="utf-8")
            add = _run_git(temp, "add", "README.md")
            self.assertEqual(add.returncode, 0, add.stderr)

            commit = _run_git(temp, "commit", "-m", "Initial commit for hook e2e test")
            self.assertEqual(commit.returncode, 0, commit.stderr)

            # P-04 regression: a hook that can't find its CLI must say so loudly,
            # not disappear behind `|| true`. It must never appear on a machine
            # where the hook resolved correctly, which this one did (it's the
            # same interpreter's sibling binary that ran this test).
            hook_output = commit.stdout + commit.stderr
            self.assertNotIn("command not found", hook_output)
            self.assertNotIn("hook skipped", hook_output)

            full_hash = _run_git(temp, "rev-parse", "HEAD").stdout.strip()
            self.assertTrue(full_hash)

            today = datetime.now(UTC).strftime("%Y-%m-%d")
            episodic_path = (
                Path(temp) / ".ai-memory" / "memory-store" / "episodic" / "commits" / f"{today}.md"
            )
            self.assertTrue(
                episodic_path.exists(),
                f"post-commit hook did not produce an episodic capture record; "
                f"hook output was:\n{hook_output}",
            )
            content = episodic_path.read_text(encoding="utf-8")
            self.assertIn(full_hash[:10], content)
            self.assertIn("Initial commit for hook e2e test", content)


if __name__ == "__main__":
    unittest.main()
