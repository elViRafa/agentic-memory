# Companion ops pack — version relationship

Memory Fabric (this public repository / PyPI package `memory-fabric`) is the **free engine**.

A separate **private** companion repository, [`elViRafa/memory-fabric-ops`](https://github.com/elViRafa/memory-fabric-ops), holds the Agensi skill-pack procedures. Paid `SKILL.md` files are **not** stored in this public MIT tree.

## Version matrix

| Artifact | Current version | Where it is controlled |
| --- | --- | --- |
| Engine (`memory-fabric`) | `1.4.5` | [`src/memory_fabric/version.py`](../src/memory_fabric/version.py) |
| Ops skill pack | `1.0.0` | Private repo `versions.json` → `skill_pack.version` |
| Ops pack tested against engine | `1.4.5` | Private repo `versions.json` → `engine.tested_version` |
| Ops pack minimum engine | `1.4.5` | Private repo `versions.json` → `engine.min_version` |

Semver is **independent**:

- Ship a new engine release without changing the skill pack when MCP/CLI contracts used by the skills stay compatible.
- Ship a new skill-pack tag when Agensi procedures change; point `docs_url` at this public repo so buyers still install `memory-fabric` from PyPI/GitHub.
- After re-validating the private pack against a new engine build, update `engine.tested_version` (and `min_version` if the floor moves), then refresh this matrix.

## What stays out of this repo

- Paid `SKILL.md` bodies
- Agensi `LISTING.md` copy
- The Agensi upload ZIP

Those live only in the private ops repository (and in the ZIP uploaded to Agensi).
