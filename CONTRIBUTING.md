# Contributing to Memory Fabric

Thanks for helping build a file-first, local-first memory layer for AI coding
assistants. This guide covers the setup, the checks your change must pass, and
the conventions that keep the project trustworthy.

## Development setup

Requires Python ≥ 3.11.

```sh
git clone https://github.com/elViRafa/agentic-memory.git
cd agentic-memory
python -m pip install -e ".[mcp,test]"
```

That installs the package in editable mode with the MCP server extra and the
test tooling (`pytest`, `pytest-cov`, `ruff`, `mypy`).

## The checks (all enforced in CI)

Run these before opening a pull request — CI runs the full matrix
({windows, macos, ubuntu} × {3.11, 3.12, 3.13, 3.14}), and a red check blocks merge.

```sh
pytest                              # tests + coverage gate (fail_under = 82)
ruff check .                        # lint (E4,E7,E9,F,I,B,UP,SIM,RUF,BLE001,S110,S112)
ruff format --check .               # formatting
mypy src/memory_fabric              # types — the package ships py.typed, so this is enforced
```

- **Coverage** must stay at or above the gate. New code paths need tests; the
  weakest-covered modules are the highest product risk.
- **Types**: `disallow_untyped_defs` is on. Prefer narrowing a real type over a
  `# type: ignore`.
- **Broad `except Exception`** needs a `# noqa: BLE001 - <reason>` and must be
  audible (feed a `warnings`/`errors` list, re-raise, or print) — never a silent
  swallow. Narrow to the exception the operation can actually raise where you can.

## Conventions that matter here

- **Store-first model.** Facts live in `memory-store/<category>/`, one per file.
  The root maps (`architecture.md`, `decisions.md`, `debt.md`, `schemas.md`,
  `index.md`) are *generated views* rebuilt by Dreaming — never hand-written.
  Write facts through `write_memory_store_tool`; the flat write path is
  restricted to steering sections (`framework-rules`, `ubiquitous-language`).
- **Local-first, no telemetry.** No network calls on the core read/write paths,
  no account, no cloud. Optional network checks (PyPI drift, provider preflight)
  must respect `--offline`. Do not add analytics or phone-home behavior.
- **Never delete user content.** Migrations copy and snapshot before rewriting;
  destructive operations are opt-in and reversible.
- **Keep a Changelog.** Add an entry under `## [Unreleased]` in
  [`CHANGELOG.md`](CHANGELOG.md) for anything user-visible, following
  [keep-a-changelog](https://keepachangelog.com/).
- **Version truth.** The version lives in `src/memory_fabric/version.py` (the
  single source; `pyproject.toml` reads it dynamically). If you bump it, the
  README status line, the ROADMAP header, and `server.json` must all agree —
  `tests/test_version_truth.py` enforces this.
- **Module size.** Keep `src/` files under 25 KB; split opportunistically when a
  file grows past the bar.

## Pull requests

1. Branch from `main`.
2. Make focused commits with clear messages.
3. Ensure the four checks above pass locally.
4. Update `CHANGELOG.md` (`[Unreleased]`) and any affected docs.
5. Open the PR against `main` and fill in the template.

## Releases

Releases are tag-driven. A `chore: release vX.Y.Z` commit bumps the version in
all four synced locations, and pushing the `vX.Y.Z` tag triggers the release
workflow (trusted publishing to PyPI via OIDC, and republish of `server.json`
to the MCP registry). Follow [semantic versioning](https://semver.org/); while
on `0.x`, minor versions may carry breaking changes, called out in the changelog.

## Reporting bugs and requesting features

Use the issue templates. For anything security-sensitive, see
[`SECURITY.md`](SECURITY.md) instead of opening a public issue.
