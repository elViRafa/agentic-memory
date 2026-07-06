# Memory Fabric

<!-- mcp-name: io.github.elViRafa/memory-fabric -->

[![CI](https://github.com/elViRafa/agentic-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/elViRafa/agentic-memory/actions/workflows/ci.yml)

**File-first, local-first memory layer for MCP-compatible AI coding assistants.**

Memory Fabric gives AI tools like Claude Code, Cursor, and GitHub Copilot a consistent, project-aware context layer without locking you into one model, editor, cloud provider, or operating system.

Memory is stored as human-readable Markdown with YAML frontmatter. No vector database. No cloud account. No embeddings required.

---

## Features

- **MCP-native**: exposes memory tools through the standard Model Context Protocol
- **File-first**: Markdown files are the source of truth, inspectable and commit-ready
- **Local-first**: core reads and writes work offline
- **Secret-safe**: API keys and credentials are redacted before writing
- **Token-budget aware**: assembles context within limits; never slices files mid-document
- **Quality eval**: scores memory usefulness and Dreaming before/after results locally
- **Unicode-safe**: works with any human language
- **Graceful degradation**: works without `rg`, git hooks, or Dreaming configured

---

## Status

**v0.5.0 — [live on PyPI](https://pypi.org/project/memory-fabric/).**
Core CLI and MCP tools work end-to-end.

---

## Installation

### From PyPI (recommended)

Requires Python ≥ 3.11.

```sh
pipx install memory-fabric          # CLI only
pipx install "memory-fabric[mcp]"   # CLI + MCP server
```

Or with plain `pip` (inside a virtual environment):

```sh
pip install memory-fabric          # CLI only
pip install "memory-fabric[mcp]"   # CLI + MCP server
```

Zero-install one-off run (requires [`uv`](https://docs.astral.sh/uv/)):

```sh
uvx --from "memory-fabric[mcp]" memory-fabric-mcp   # starts the MCP server on stdio
```

### From GitHub (latest, pre-release)

```sh
# CLI only
pipx install "git+https://github.com/elViRafa/agentic-memory.git"

# CLI + MCP server
pipx install "memory-fabric[mcp] @ git+https://github.com/elViRafa/agentic-memory.git"
```

Or with plain `pip` (inside a virtual environment):

```sh
pip install "git+https://github.com/elViRafa/agentic-memory.git"          # CLI only
pip install "memory-fabric[mcp] @ git+https://github.com/elViRafa/agentic-memory.git"  # + MCP
```

### Upgrading

Because Memory Fabric is in active development, we recommend upgrading regularly:

1. **Upgrade the Package**:
   ```sh
   # If installed via pipx:
   pipx upgrade memory-fabric

   # If installed in a virtual environment via pip:
   pip install --upgrade "memory-fabric[mcp]"

   # If installed from GitHub (pre-release):
   pipx install --force "memory-fabric[mcp] @ git+https://github.com/elViRafa/agentic-memory.git"
   ```

2. **Restart MCP Clients**:
   After upgrading, restart your IDE (Cursor, VS Code) or assistant process (Claude Code) to ensure the client reloads the updated `memory-fabric-mcp` server.

3. **Refresh Local Projects (Optional)**:
   If you have projects initialized with older versions of Memory Fabric, navigate to the project directory and run:
   ```sh
   ai-memory init --install-hooks
   ```
   This will safely refresh starter templates and local git hook integration to the latest format without overwriting your existing memory markdown files.

Or clone and install in editable mode for local development:

```sh
git clone https://github.com/elViRafa/agentic-memory.git
cd agentic-memory
pip install -e .          # CLI only
pip install -e ".[mcp]"   # CLI + MCP server
```

---

## Quick Start

### 1. Initialize a project

```sh
ai-memory init
```

Creates `.ai-memory/` in the current directory with starter sections and a `.gitignore`.

### 2. Check health

```sh
ai-memory doctor
```

### 3. Evaluate memory quality

```sh
ai-memory eval
ai-memory eval --json
```

`eval` scores whether memories are useful for coding assistants. It checks section coverage, starter-template content, summary quality, metadata, retrieval readiness, and likely secrets.

If `.ai-memory/` exists, reports are saved under ignored local files:

```text
.ai-memory/evals/latest.json
.ai-memory/evals/latest.md
.ai-memory/evals/<timestamp>-memory.json
.ai-memory/evals/<timestamp>-memory.md
```

If `.ai-memory/` does not exist yet, eval prints a pre-init report only and creates no files.

### 4. Query memory

```sh
ai-memory query "authentication"
```

### 5. Run maintenance (Dreaming)

```sh
ai-memory dream --mode light
ai-memory dream --mode deep
```

Dreaming creates a snapshot before maintenance. You can evaluate whether a Dreaming run improved memory quality:

```sh
ai-memory eval --dream latest
ai-memory dream --mode light --eval
```

Dream eval compares the pre-dream snapshot to current memory and reports score delta, changed files, improvements, and regressions.

---

## MCP Server — Install

One command per client. Safe to re-run: merges with your existing config, never
overwrites it, and backs up the original file if it can't be parsed.

### One-click install

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](vscode:mcp/install?%7B%22name%22%3A%22memory-fabric%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22memory-fabric%5Bmcp%5D%22%2C%22memory-fabric-mcp%22%5D%7D)
[![Install in VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-Install_Server-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](vscode-insiders:mcp/install?%7B%22name%22%3A%22memory-fabric%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22memory-fabric%5Bmcp%5D%22%2C%22memory-fabric-mcp%22%5D%7D)
[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](cursor://anysphere.cursor-deeplink/mcp/install?name=memory-fabric&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJtZW1vcnktZmFicmljW21jcF0iLCJtZW1vcnktZmFicmljLW1jcCJdfQ==)

These call `uvx --from "memory-fabric[mcp]" memory-fabric-mcp` under the hood — same
canonical invocation as `ai-memory install`, just without the CLI step. Requires
[`uv`](https://docs.astral.sh/uv/).

| Client | Command |
|---|---|
| Claude Code | `ai-memory install --client claude-code` |
| Claude Desktop | `ai-memory install --client claude-desktop` |
| VS Code | `ai-memory install --client vscode` |
| Cursor | `ai-memory install --client cursor` |
| Windsurf | `ai-memory install --client windsurf` |
| Codex | `ai-memory install --client codex` |
| Antigravity | `ai-memory install --client antigravity` |
| Gemini CLI | `ai-memory install --client gemini-cli` |
| Cline | `ai-memory install --client cline` |
| All detected clients | `ai-memory install --client all` |

Add `--project` to write project-scoped config instead of the global/user config
(where the client supports it). Add `--dry-run` to preview the change as a unified
diff without writing anything. Add `--uninstall` to remove only the memory-fabric
entry, leaving everything else in the file untouched.

### Available MCP Tools

| Tool | Description |
|---|---|
| `initialize_memory_fabric_tool` | Create `.ai-memory/` scaffolding in a project |
| `read_combined_context_tool` | Load Tier 0 directives + prioritized memory within token budget |
| `read_section_tool` | Read a single memory section by name |
| `keyword_search_tool` | Search memory with ripgrep or Python fallback |
| `write_local_memory_tool` | Append or replace a section with secret scanning |
| `propose_memory_patch_tool` | Preview proposed memory changes without applying |
| `dream_tool` | Run memory maintenance / consolidation (--mode light|deep) |
| `prepare_dream_payload_tool` | Prepare candidate snapshot and return consolidation prompt for client-driven dreaming |
| `apply_dream_results_tool` | Apply LLM consolidated JSON output to candidate snapshot and save changes |
| `evaluate_memory_fabric_tool` | Evaluate local memory quality |
| `evaluate_dream_quality_tool` | Evaluate a Dreaming run against a snapshot |
| `write_memory_store_tool` | Write a memory file to a semantic store path (e.g. `architecture/decisions/auth`) |
| `read_memory_store_tool` | Read a single memory-store file by its semantic path |
| `list_memory_store_tool` | List files in the memory store, optionally filtered by prefix/tags |
| `delete_memory_store_tool` | Remove a memory-store file by its semantic path |

---

## Agentic Architecture (making agents use Memory Fabric automatically)

Registering the MCP server is necessary but not sufficient — AI agents will not use its tools unless explicitly instructed to do so. 

Memory Fabric provides an automated **Agentic Architecture** to handle this for you.

When you run `ai-memory init` in your project, the CLI automatically deploys a complete suite of agent instruction files tailored for every major AI tool:

| Target | File(s) Created |
|:---|:---|
| **Gemini CLI / Codex / Antigravity** | `AGENTS.md` |
| **Grok (TUI / Build / Agent harness)** | `AGENTS.md` (primary project rules); full docs + MCP registration in `~/.grok/config.toml` or `.mcp.json`; see also `.grok/docs/user-guide/13-memory-fabric.md` when installed for the client |
| **Cursor IDE** | `.cursor/rules/memory-fabric.mdc` |
| **Windsurf IDE** | `.windsurf/rules/memory-fabric.md` |
| **Cline / Generic IDE Agents** | `.agents/rules/memory-store.md`, `.agents/rules/dreaming.md` |
| **Claude Code** | `CLAUDE.md` (created or appended) |
| **GitHub Copilot** | `.github/copilot-instructions.md` (created or appended) |

### Single Source of Truth (Syncing)
All these files are generated from **two canonical content blocks** inside the Memory Fabric Python package. Running `ai-memory sync-agents` regenerates every platform file from these templates, guaranteeing perfect consistency. If you used `ai-memory init --install-hooks`, a `pre-commit` git hook runs this sync automatically on every commit.

For full details on the architecture, see [`AGENTIC_ARCHITECTURE.md`](AGENTIC_ARCHITECTURE.md).

### Why this matters

Without these instruction files, agents will often explain they "don't use MCP tools automatically," or worse, they will write memory markdown files directly using native file-system tools—bypassing secret scanning, token budgeting, and background Dreaming management.

By simply running `ai-memory init`, you get zero-configuration, plug-and-play capability across the entire agent ecosystem.

---

## Using Memory Fabric in Other Projects

You can use a single installed instance of Memory Fabric across all your coding projects:

1. **Scaffold the target project**:
   Navigate to your target project's root folder and initialize it:
   ```sh
   cd /path/to/other-project
   ai-memory init --install-hooks
   ```
   This automatically creates `.ai-memory/`, deploys the **Agentic Architecture** rule files, sets up `.gitignore`, and installs the git post-commit hooks.

2. **Global MCP Configuration**:
   Verify your AI assistant's configuration points to your globally installed `memory-fabric-mcp` executable. The MCP tools automatically parse and use the active project's path passed by the assistant as the `cwd` argument, enabling a single global MCP server registration to support all your local workspaces.

---

## Project Memory Layout

```text
.ai-memory/
|-- index.md
|-- architecture.md
|-- schemas.md
|-- decisions.md
|-- debt.md
|-- ubiquitous-language.md
|-- framework-rules.md
|-- evals/       # ignored local quality reports
|-- snapshots/   # ignored rollback baselines
|-- private/     # ignored personal notes
`-- .gitignore
```

All shared memory files use YAML frontmatter:

```markdown
---
section: architecture
summary: "One-line fallback used when the file exceeds the token budget."
priority: high
tags: [api, auth]
schema_version: "1.3"
last_updated: 2026-06-01T12:00:00-04:00
---

Your memory content here.
```

---

## Global Memory

Developer-level preferences that apply across all projects are stored at:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\memory-fabric\global\` |
| macOS | `~/Library/Application Support/memory-fabric/global/` |
| Linux | `$XDG_CONFIG_HOME/memory-fabric/global/` |

`global/directives.md` is **Tier 0**: it is always loaded fully, bypassing token budgeting.

---

## CLI Reference

```text
ai-memory [--cwd <path>] [--json] [--debug-llm] <command>

Commands:
  init            Create .ai-memory/ scaffolding
  status          Show memory status
  doctor          Validate memory files and environment
  install         Configure an MCP client to use memory-fabric (--client <name|all>)
  eval            Score memory quality or Dreaming quality
  dream           Run memory maintenance (--mode light|deep)
  query           Search memory
  store           CRUD operations on semantic memory store
  sync-global     Preview local-to-global promotions
  rollback        Restore from a snapshot
```

Eval examples:

```sh
ai-memory eval
ai-memory eval --json
ai-memory eval --llm-review
ai-memory eval --dream latest
ai-memory eval --dream memory-20260601T140000_0400
```

Optional LLM review is never enabled by default. When requested, deterministic local scores remain the source of truth; LLM notes are secondary and inputs are sanitized before review.

---

## LLM Configuration & MCP Sampling

Memory Fabric uses Large Language Models (LLMs) to perform semantic memory consolidation (Dreaming) and qualitative evaluation. You can configure this in two ways: via direct environment variables or via zero-config **MCP Sampling**.

### Resolution Precedence

When an operation requires an LLM, Memory Fabric resolves the provider in the following order:

1. **Direct LLM Provider**: Uses direct API calls if `MEMORY_FABRIC_LLM_PROVIDER` is set in the environment along with the corresponding API keys.
2. **Native MCP Sampling**: If no direct provider is set (or configured keys are missing) AND the command is executed within an active MCP session where the parent agent supports sampling, Memory Fabric delegates the LLM call to the agent itself.
3. **Graceful Local Fallback**: If neither is available, it degrades gracefully to local, deterministic regex-based deduplication without semantic synthesis.

### Using MCP Sampling in Dreaming

MCP Sampling allows Memory Fabric to run semantic Dreaming and evaluations **without configuring any local API keys or provider environment variables**. Instead, it uses the host client's (e.g. Claude Code) native LLM connection.

#### How It Works
1. When your AI assistant calls the `dream_tool` or `evaluate_memory_fabric_tool` via MCP, the Memory Fabric server checks if the client session supports sampling capabilities.
2. If supported and no direct provider is configured, the server sends a `create_message` request back to the client.
3. The client assistant executes the LLM reasoning under the hood and returns the consolidated memory JSON or evaluation notes.

#### Key Benefits
- **Zero-Config:** No need to configure or expose `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` to the background MCP server process.
- **Unified Context:** The consolidation uses the same model and settings configured in your main coding assistant.

> [!IMPORTANT]
> **CLI Limitation:** MCP Sampling relies on an active client-server session. Since the standalone terminal CLI (`ai-memory`) runs outside of an MCP client, running `ai-memory dream` from the command line **cannot** use MCP Sampling. To use LLM-based consolidation via the CLI, you must configure a direct LLM provider.

### Client-Driven / Split-Tool Dreaming (Avoiding Deadlocks & Timeouts)

In some sequential/blocking MCP client environments (like IDE extensions or agentic loops), executing a nested MCP Sampling request (`create_message`) while the client is waiting for a tool response can lead to a JSON-RPC deadlock or execution timeouts.

To completely avoid this re-entrancy issue, Memory Fabric provides a client-driven split-tool dreaming protocol:

1. **Prepare Payload**: The agent/client first calls `prepare_dream_payload_tool`. This returns a `consolidation_prompt` and a `candidate_store` ID, but performs no blocking LLM reasoning.
2. **Execute Locally**: The client uses its own local LLM connection/context to execute the returned `consolidation_prompt` and captures the raw JSON output.
3. **Apply Results**: The client sends the raw LLM JSON response back by calling `apply_dream_results_tool(candidate_store=..., llm_response=...)`. Memory Fabric parses the response, applies the consolidated changes to the candidate folder, and saves the new memory states.

### Direct LLM Providers Configuration

To use the CLI with LLMs, or to bypass MCP Sampling with a specific provider, set the following environment variables:

| Provider | Environment Variables | Notes |
|---|---|---|
| **Gemini** | `MEMORY_FABRIC_LLM_PROVIDER=gemini`<br>`GEMINI_API_KEY=your_key` | Defaults to `gemini-2.5-flash` |
| **OpenAI** | `MEMORY_FABRIC_LLM_PROVIDER=openai`<br>`OPENAI_API_KEY=your_key`<br>`OPENAI_MODEL=gpt-4o-mini` *(opt)*<br>`OPENAI_API_BASE=...` *(opt)* | Can connect to custom local/remote OpenAI-compatible endpoints |
| **Anthropic** | `MEMORY_FABRIC_LLM_PROVIDER=anthropic`<br>`ANTHROPIC_API_KEY=your_key` | Defaults to `claude-3-5-haiku-20241022` |
| **Ollama** | `MEMORY_FABRIC_LLM_PROVIDER=ollama`<br>`OLLAMA_HOST=...` *(opt)*<br>`OLLAMA_MODEL=gemma2` *(opt)* | Offline, local reasoning |

---

## LLM Debugging

If you want to view the exact prompts sent and responses received by the LLM providers (Gemini, OpenAI, Anthropic, Ollama), you can enable LLM debug logging.

- **Via the CLI**: Pass the `--debug-llm` global flag **before** the subcommand:
  ```sh
  ai-memory --debug-llm dream --mode deep
  ```
  This automatically prints logs to `sys.stderr` and appends them to a file named `llm_debug.log` (in `.ai-memory/llm_debug.log` if the directory exists, otherwise in the current working directory).

- **Via Environment Variables**: Set the `MEMORY_FABRIC_LLM_DEBUG` variable in your environment:
  - `stderr`: Output prompts and raw JSON responses only to `sys.stderr`.
  - `1` or `true`: Output to `sys.stderr` and write to the default `llm_debug.log` file.
  - `/path/to/log.txt` (or any other custom value): Append logs to a custom file path.

To protect your credentials and API keys, headers like `Authorization` and `x-api-key` are automatically redacted as `[REDACTED]` in the debug logs.

---

## Write Safety

Every write path runs secret detection before saving. Detected secrets are replaced with `[REDACTED_SECRET]` and returned in the `redactions` field of the response. File locking prevents concurrent write corruption.

Eval scans existing memories for likely secrets but does not rewrite existing files. It reports what needs manual review.

---

## Requirements

- Python >= 3.11
- `mcp >= 1.0.0` (optional, required for MCP server only)
- `rg` (optional; ripgrep speeds up keyword search, Python fallback used when absent)

---

## License

MIT
