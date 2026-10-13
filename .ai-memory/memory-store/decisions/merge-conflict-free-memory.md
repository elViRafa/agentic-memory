---
store_path: decisions/merge-conflict-free-memory
title: "Conflict-free memory merges for teams"
summary: "Conflict-free memory merges for teams"
priority: high
tags: [decisions, git, merge, teams]
schema_version: 1.3
last_updated: "2026-07-29T18:03:48+00:00"
---

Multi-developer projects reported a merge conflict on every branch integration in `.ai-memory/` — `failures.md`, `index.md`, and the episodic day file both developers had journaled into. Three distinct causes, fixed together.

**1. The merge driver was only half-installed.** `.gitattributes` is committed and shared; the driver command is per-clone by git's own design (a repo cannot ship executable merge commands). A teammate who clones and merges gets ordinary textual conflicts with nothing explaining why. Fixed from both sides: `doctor` warns when a clone declares the driver but has not registered it, and any `ai-memory init` in such a clone registers the local half automatically.

**2. Generated views were being merged as if they were authored content.** Root maps (`generated: true`) and the two discovery indexes are rebuilt from `memory-store/` on every Dreaming run, so no textual conflict in one was ever worth a human's attention — but they are regenerated wholesale rather than appended to, so they failed the driver's pure-append test and conflicted deterministically. They now union-merge via `git merge-file --union`. The merged file is re-stamped: `body_hash` recomputed and `store_fingerprint` blanked. Without that re-stamp `regenerate_maps` compares the merged body against the pre-merge `body_hash`, concludes a human edited the map, and folds the union into `memory-store/` as a permanent memory.

**3. The driver only understood pure appends.** Two agents journaling into the same episodic day file produce separate `##` entries plus edits to older ones — not a shared prefix. Merging per `##` block covers that; only a single block rewritten on both sides still defers to git's textual merge, which is a real disagreement.

Also added `ai-memory resolve-conflicts` for teams already sitting in a conflicted merge: it applies the same resolution to the index stages git already recorded (`:1:`/`:2:`/`:3:`), so the merge does not have to be redone.
