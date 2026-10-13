# 90-Second Demo Script

The one moment that sells Memory Fabric: **an agent writes a memory in one tool,
and a different tool reads it back.** This is the storyboard for the launch video.
Target runtime ~90 seconds.

> **Status:** the CLI + self-capture portion (Shots 1 and 4 below) is already
> captured as a terminal GIF at [`docs/demo-cli.gif`](docs/demo-cli.gif) and
> embedded in the README. The cross-tool GUI moment (Shots 2–3) needs a real
> screen recording of the actual IDE agents — that's the remaining step, scripted
> below.

Record at 1280×720 or larger, terminal font ≥ 16pt, light or dark but consistent.
Keep each shot tight — no idle typing. Pre-stage a small demo repo (a couple of
source files, a git repo initialized) so there's real context to capture.

---

## Shot 1 — One command, any tool (0:00–0:12)

Terminal in the demo project:

```sh
uvx --from "memory-fabric[mcp]" memory-fabric-mcp   # zero-install, or:
pipx install "memory-fabric[mcp]"
ai-memory init --install-hooks
ai-memory install --client claude-code
```

**Caption:** "File-first memory for AI coding agents. No vector DB, no cloud."

## Shot 2 — The agent writes memory in Claude Code (0:12–0:38)

Split screen or cut to Claude Code. Ask it something that produces a decision,
e.g. "We're using JWT with short-lived access tokens and refresh rotation for
auth — remember that." The agent calls `write_memory_store_tool`.

Cut to the file that just appeared:

```sh
cat .ai-memory/memory-store/decisions/auth-jwt.md
```

**Caption:** "The agent records the decision as plain Markdown in your repo."

Show the frontmatter + body briefly — it's human-readable, not embeddings.

## Shot 3 — The cross-tool moment (0:38–1:05)

Cut to a **different** tool — VS Code (Copilot agent mode) or Codex — already
configured with `ai-memory install --client <that tool>`. Open the same project.
Ask: "What auth approach did we decide on, and why?"

The second agent calls `read_combined_context_tool` / `keyword_search_tool` and
answers correctly — citing the JWT decision written in Claude Code.

**Caption:** "Same project brain, every tool. `git pull` and your team has it too."

This is the payoff shot — hold on the correct cross-tool answer.

## Shot 4 — It captures itself (1:05–1:25)

Back in the terminal, make a real commit:

```sh
git commit -am "feat: add refresh-token rotation"
# post-commit hook: "Running Memory Fabric capture + Dreaming..."
ai-memory status        # shows the episodic capture for that commit
```

**Caption:** "Every commit is recorded automatically — no agent cooperation
required."

## Shot 5 — Close (1:25–1:30)

Card:

> **Memory Fabric** — one persistent, human-auditable project brain, in every
> tool you use.
> `pipx install "memory-fabric[mcp]"` · MIT · no telemetry

---

## Recording notes

- Pre-`init` the repo off-camera so Shot 1 stays short.
- Pre-configure both clients so Shot 3 doesn't spend time on setup.
- If a live LLM call is slow on camera, capture memory with the no-LLM path
  (capture + local Dreaming) so the demo never stalls waiting on a provider.
- Export a trimmed GIF (≤ 8 MB) of Shots 2–3 for the README; the full video
  carries Shots 1, 4, and 5.
