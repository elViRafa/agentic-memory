# Memory Fabric — Roadmap to Best-in-Class

> Goal: make Memory Fabric the best memory layer for AI coding assistants — installable in
> one command in VS Code, Claude (Code + Desktop), Codex, Antigravity, Cursor, Windsurf,
> Gemini CLI, Cline, and anything MCP-compatible.

Last updated: 2026-07-04 · Current version: 0.3.0 (not yet on PyPI) · Tests: 83 passing

---

## 1. Positioning: what "best in the world" means for us

The memory market leaders (Mem0 ~47k stars, Zep/Graphiti, Letta) all compete on
**conversational user memory**: cloud services, vector/graph databases, personalization.
We do not out-spend them there. We win a different, underserved category:

**Project memory for coding agents — file-first, local-first, cross-tool.**

| | Mem0 / Zep / Letta | Memory Fabric |
|---|---|---|
| Storage | Vector DB / graph DB / cloud | Markdown + YAML in the repo |
| Ownership | Their infra or your DB | Your git history |
| Reviewable by humans | No (embeddings) | Yes (plain files, PR-diffable) |
| Team sharing | Per-account sync | `git pull` |
| Works offline / air-gapped | Mostly no | Yes |
| Same memory in every agent | Partial (OpenMemory MCP) | Core design goal |
| Secret redaction on write | No | Yes |
| Memory quality evals | No | Built-in (`ai-memory eval`) |

"Best in the world" = the definitive answer to *"my coding agents should share one
persistent, trustworthy, human-auditable project brain, in every tool I use."*
Every phase below either widens distribution, deepens quality, or proves the claim.

---

## 2. Phase 0 — Foundation hardening (trust before growth)

Before asking thousands of people to install it, make failure impossible to hide.

- [ ] **Split the god module.** `src/memory_fabric/storage/_core.py` is ~108 KB. Split into
      `context.py` (assembly/budgeting), `store.py` (semantic store CRUD), `dream.py`
      (consolidation), `journal.py` (episodic), `search.py`, `snapshots.py`. Keep the
      public API re-exported from `memory_fabric.storage` so nothing breaks.
- [ ] **CI matrix.** GitHub Actions: {windows, macos, ubuntu} × {3.11, 3.12, 3.13, 3.14},
      `pytest`, `ruff check`, `ruff format --check`, `mypy` (the package ships `py.typed`
      — enforce it). Badge in README.
- [ ] **Coverage gate** (start at current %, ratchet up; target ≥85%).
- [ ] **Docs truth pass.** README still says "v0.1.0" while `pyproject.toml` says 0.3.0;
      single-source the version and audit every README claim against behavior.
- [ ] **Concurrency & corruption tests.** Two writers, crashed process mid-write, huge
      files, non-UTF-8 bytes, symlinks. These are the bugs that kill trust.

Exit criteria: green CI badge on all three OSes, no file >25 KB in `src/`, coverage gate on.

## 3. Phase 1 — Install everywhere (distribution)

This phase is the direct answer to "usable in VS Code, Claude, Codex, Antigravity and others."

### 3.1 Publish to PyPI (unlocks everything else)

- [ ] Reserve names `memory-fabric` on PyPI (and consider `agentic-memory` as alias).
- [ ] GitHub Actions **trusted publishing** (OIDC, no API tokens) on tag push.
- [ ] After this, the universal zero-install invocation becomes:
      `uvx --from "memory-fabric[mcp]" memory-fabric-mcp`
      (works on any machine with `uv`; document `pipx` fallback).

### 3.2 One-command client setup: `ai-memory install`

**Done (2026-07-05) — see `z_PLAN.md` Milestone C for the full implementation record,**
including two path/root-key corrections found by checking current docs instead of
relying on training-data knowledge for the fast-moving clients (VS Code, Antigravity).

New CLI command that detects/receives a client name and writes the right config,
idempotently, with `--dry-run` support:

| Client | What `ai-memory install --client <x>` writes |
|---|---|
| `claude-code` | Runs `claude mcp add memory-fabric -- uvx --from "memory-fabric[mcp]" memory-fabric-mcp`, or writes project `.mcp.json` |
| `claude-desktop` | Adds entry to `claude_desktop_config.json` (per-OS path) |
| `vscode` | Workspace `.vscode/mcp.json` or user-profile MCP config (Copilot agent mode) |
| `cursor` | `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global) |
| `windsurf` | `~/.codeium/windsurf/mcp_config.json` |
| `codex` | `[mcp_servers.memory-fabric]` table in `~/.codex/config.toml` (or `codex mcp add`); project-scoped `.codex/config.toml` supported |
| `antigravity` | `~/.gemini/config/mcp_config.json` (central config shared by Antigravity IDE/CLI and Gemini CLI) |
| `gemini-cli` | Same central config as Antigravity |
| `cline` | Cline MCP settings JSON |
| `all` | Detects installed clients and configures each |

Design rules: never clobber existing entries; JSON/TOML merge, not overwrite; print the
exact diff; `--uninstall` flag for clean removal.

### 3.3 Official MCP Registry

- [ ] Create `server.json`, publish via `mcp-publisher` under the
      `io.github.elvirafa/memory-fabric` namespace to registry.modelcontextprotocol.io.
- [ ] This feeds the VS Code MCP store, Cursor's directory, Glama/PulseMCP/mcp.so
      aggregators — free discovery in every client that browses the registry.

### 3.4 One-click installs

- [ ] **VS Code / Cursor install badges** in README (deeplink `vscode:mcp/install` /
      `cursor://` URLs with the server config embedded).
- [ ] **MCPB bundle** (`.mcpb`) built in CI for drag-and-drop install into Claude Desktop.
      Python servers can be bundled with dependencies; test on Windows + macOS.

### 3.5 README install matrix

- [ ] Rewrite the Installation section as a per-client table: one copy-paste command or
      badge per client, each verified by an integration smoke test in CI.

Exit criteria: a stranger on any OS gets from "found the repo" to "agent reads/writes
memory in their tool" in under 2 minutes, for all clients above.

## 4. Phase 2 — Retrieval quality (be the best, not just the most compatible)

Keep the zero-dependency, no-vector-DB default. Add optional layers that degrade gracefully
— the same pattern already used for `rg` and LLM providers.

- [ ] **Hybrid retrieval.** Keep BM25 (shipped). Add optional local embeddings via a
      small ONNX model (e.g. fastembed) + `sqlite-vec` stored inside `.ai-memory/` local
      (gitignored) cache. Blend scores: BM25 + cosine + priority + recency. No cloud calls.
- [ ] **Temporal facts.** Frontmatter gains optional `valid_from` / `superseded_by`.
      Dreaming marks contradicted facts as superseded instead of deleting — the agent can
      answer "when did we change X?" This is Zep's headline feature, done file-first.
- [ ] **Link graph.** `[[wiki-links]]` between memory files + a generated entity index.
      A cheap knowledge graph with zero database — retrieval follows links one hop out.
- [ ] **Memory lifecycle.** Provenance (`source_session`), access-count decay, confidence
      scores; Dreaming demotes stale/unused memories instead of letting them rot.
- [ ] **Contradiction detection** during Dreaming (LLM-assisted when available, Jaccard
      fallback), surfacing conflicts for human review rather than silently choosing.
- [ ] **Latency budget.** `read_combined_context` p95 under 150 ms on a 500-file store;
      add a perf test to CI.

## 5. Phase 3 — Prove it (benchmarks nobody can argue with)

Claims without numbers don't win "best in the world."

- [ ] **Run the standard benchmarks.** Build a small adapter that feeds LongMemEval (S,
      then M) and LoCoMo through Memory Fabric's store/retrieve loop; publish scores and
      the exact reproduction script. These are conversational benchmarks — expect strong
      but not chart-topping numbers; honesty here buys credibility.
- [ ] **Create the coding-memory benchmark.** There is no dominant benchmark for *project
      memory in coding agents*. Build one: N repos × M sessions of realistic tasks, where
      later tasks require decisions recorded in earlier sessions ("which auth approach did
      we pick and why?", "what's the deprecated API we must avoid?"). Score memory-on vs
      memory-off agents. Publish it as a standalone repo — owning the benchmark defines
      the category.
- [ ] **Ship `ai-memory bench`** so any user can run the suite against their own store.
- [ ] Results table in README with reproduction commands.

## 6. Phase 4 — Ecosystem & growth

- [ ] **Docs site** (mkdocs-material on GitHub Pages): quickstart per client, concepts
      (Tiers, Dreaming, store), MCP tool reference, benchmark methodology.
- [ ] **90-second demo** (GIF in README + video): init → agent writes memory in Claude
      Code → same memory read from VS Code and Codex. The cross-tool moment is the hook.
- [ ] **Launch sequence**: PyPI + registry live → Show HN → r/ClaudeAI, r/cursor,
      X/Twitter dev threads → submit to awesome-mcp-servers lists.
- [ ] **Community hygiene**: CONTRIBUTING.md, issue/PR templates, CHANGELOG (keep-a-changelog),
      semver discipline, GitHub Releases automated from tags.
- [ ] **Telemetry: none.** Make "no telemetry, no account, no cloud" a stated guarantee —
      it is a differentiator in this category.

## 7. Success metrics

| Metric | 3 months | 12 months |
|---|---|---|
| Install friction | ≤2 min on any listed client | one-click on all majors |
| PyPI downloads/month | 1k | 20k |
| GitHub stars | 500 | 5k |
| Benchmark | published LongMemEval score | top-3 on own coding-memory benchmark, cited by others |
| Clients verified in CI | 4 | 9+ |

## 8. Suggested execution order

1. **Phase 1.1 PyPI publish** — small effort, unblocks every install story. Do first.
2. **Phase 0 CI + module split** — in parallel; must be green before launch.
3. **Phase 1.2–1.5 install command + registry + badges + MCPB** — the "everywhere" ask.
4. **Launch v1.0** (Phase 4 demo + announcements) on the strength of distribution.
5. **Phase 2 retrieval quality** — iterate post-launch with real users.
6. **Phase 3 benchmarks** — publish numbers; the coding-memory benchmark is the moat.
