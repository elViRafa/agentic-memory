---
store_path: decisions/git-integration
section: git-integration
summary: "Decisions regarding Git hooks and subprocess integrations for memory maintenance."
priority: low
tags: [decisions, git, hooks, subprocess]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Git Integration Decisions

This document records the granular decisions made for interacting with Git to ingest context.

## Post-Commit Hooks
- Decided to implement the post-commit git hook as an opt-in hook script `.git/hooks/post-commit` calling `ai-memory dream --mode light --apply`.
- Improved post-commit hooks installer to merge with existing post-commit hook instead of replacing it.

## Ingestion & Subprocesses
- Enriched dreaming git input ingestion to include both git diff HEAD and recent commit logs (git log).
- Decided to append `encoding="utf-8"` and `errors="replace"` to all git-related subprocess calls in `storage.py` to prevent `UnicodeDecodeError` crashes on Windows when processing files containing non-ASCII/UTF-8 characters.
