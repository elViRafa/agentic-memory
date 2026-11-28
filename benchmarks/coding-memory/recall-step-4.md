# Step 4 paired agent outcomes

## Answer keys

The fixture, answer keys, and executable scorer were fixed before the evaluation
sessions. Each synthetic repository has an ordinary README and one JSON
configuration file. [Fixture and machine-readable answer keys](agent-outcomes/cases.json)

| Task | Passing outcome |
| --- | --- |
| Follow the current decision | Set Harbor's CSV column order to `depot, service, parcel_id`. The pilot order was superseded. |
| Avoid a recorded failure | Set Orchid's multiline mode to `base64_utf8` and preserve single-line passthrough. Any successful `literal_escape` write counts as a repeat, including a write later reverted. |
| Verify an old fix | Probe the unchanged Spruce checkout with two manifest records that differ only in `revision`. Report that the cache keys collide again. |
| Ask for missing evidence | Request the signed `WMS-27` routing matrix, report the rollout as blocked, and make zero writes. Any content-changing write counts as unnecessary, including one later reverted. |

The scorer checks the structured final report against the tool audit and final
workspace. For Spruce it requires a probe of the original configuration. For
Juniper it requires the specific artifact name in the evidence request.
[Executable scorer](agent-outcomes/check.py)

## Protocol

1. Open a separate native MCP seed session per task and record the history using
   `write_memory_store_tool`. For Spruce, date the seed write to January 1, 2024
   and run light Dreaming to derive its stale status. Preflight the expected
   source and retrieval status in the seed session, then close it.
2. Make two clean copies per task and check the byte-level snapshot and prompt
   digests. Run each copy in a separate ephemeral Codex session. Alternate which
   arm runs first across tasks. Evaluation processes receive the same ordinary
   files, prompt, model setting, reasoning effort, output schema, and tool
   definitions.
3. Give both arms a workspace-scoped MCP server for file reads, JSON writes,
   and the Spruce probe. Approve that server's tools in both arms and disable
   the shell and web search. The same history lookup tool calls Memory
   Fabric's task-context engine against the isolated
   seed store in the on arm and returns a disabled response with no evidence in
   the off arm. Neither checkout contains the seed history or answer key. The
   isolated Memory Fabric global store is empty.
4. Score completed sessions against the predeclared keys. Count distinct
   tool-call events by ID, including failed calls. Report the client's token
   usage with cache hits listed separately. Cached input tokens are a subset
   of input tokens. Report unavailable runs separately from scored outcomes.

## Results

The November 28, 2026 run completed **4/4 scored pairs**. Memory Fabric on
passed **3/4** task answer keys and Memory Fabric off passed **1/4**.
[Per-session scores, audit and workspace snapshots](agent-outcomes/results.json)

The published results use per-run session labels after checking uniqueness.

| Outcome | Memory on | Memory off | Observed behavior |
| --- | ---: | ---: | --- |
| Follow the current decision | 0/1 | 0/1 | On set the approved columns and retained CSV, satisfying the workspace check. Its report used `verified` where the key required `completed`. Off requested the approved order. |
| Avoid a recorded failure | 1/1 | 0/1 | On set the correct multiline mode. Off left the exporter unchanged and asked for the vendor contract. |
| Verify an old fix | 1/1 | 1/1 | Both used fresh probes to confirm that the collision returned. On used the historical lead. Off inferred a reproduction from the current checkout. |
| Ask for missing evidence | 1/1 | 0/1 | On requested the signed routing matrix. Off requested general warehouse confirmation. Both avoided edits. |
| **All outcomes** | **3/4** | **1/4** | Two on-only passes, one shared pass, and one shared miss under the frozen keys. |

| Behavior | Memory on | Memory off |
| --- | ---: | ---: |
| Repeated Orchid's recorded mistake | 0/1 | 0/1 |
| Changed the workspace unnecessarily on the unanswerable Juniper task | 0/1 | 0/1 |

| Task | On input | On cached | On output | On calls | Off input | Off cached | Off output | Off calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Harbor | 86,501 | 70,784 | 320 | 6 | 64,263 | 57,728 | 315 | 5 |
| Orchid | 79,994 | 51,968 | 402 | 7 | 54,631 | 35,968 | 293 | 4 |
| Spruce | 70,899 | 65,408 | 301 | 5 | 69,836 | 54,528 | 383 | 7 |
| Juniper | 55,657 | 50,688 | 229 | 4 | 69,352 | 54,272 | 304 | 5 |
| **Total** | **293,051** | **238,848** | **1,252** | **22** | **258,082** | **202,496** | **1,295** | **21** |

The client reports cumulative input across model requests within each session.
Each request used the same configured 32,768-token context window in both
arms. The Memory Fabric lookup cap was 1,200 estimated tokens.

| Component | Version or setting |
| --- | --- |
| Model | `gpt-6.2-sol`, low reasoning effort. Hosted Codex reported no dated model build. |
| Memory Fabric engine | `1.4.6` from the local recall candidate. Source SHA-256 `e03a8e4702b6ea98e50b52367fb528b6e1adcc972328df4a713599bd5cf7cb16`. |
| Client | `codex-cli 0.171.0-alpha.13.2` |
| Seed runtime | Python `3.14.0`, MCP SDK `1.27.2`, MCP protocol `2025-11-25` |
| Sessions | Four native MCP seeds and eight distinct Codex evaluation sessions in the scored batch |

An initial batch of four pairs was unavailable. Codex's default MCP approval
setting denied workspace tool calls in all eight sessions. The rerun explicitly
approved the scoped trial tools for both arms and used the same fixtures, keys,
and scorer. All eight rerun sessions were available. The initial attempts are
excluded from the outcome and token totals above.
[Unavailable attempt and its token and tool counts](agent-outcomes/results-unavailable.json)

This comparison measures four synthetic tasks with one scored run per arm per
task.

## Reproduce

From the repository root with Python 3.11 or later, the optional MCP SDK and an
authenticated Codex CLI:

```sh
python -m pip install -e '.[mcp]'
python benchmarks/coding-memory/agent-outcomes/trial.py --validate-fixtures
python benchmarks/coding-memory/agent-outcomes/trial.py --output trial-results.json
python benchmarks/coding-memory/agent-outcomes/check.py trial-results.json
```

Use `--engine-src` to point the same runner at a different Memory Fabric source
tree. Rerun the comparison when default retrieval policy changes.
