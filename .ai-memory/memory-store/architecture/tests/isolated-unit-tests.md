---
store_path: architecture/tests/isolated-unit-tests
title: "Isolated Unit Tests for Utilities"
summary: "Contains isolated unit tests for utility functions like frontmatter parsing and security checks, separating them from high-level integration tests."
priority: low
tags: [tests, frontmatter, security]
schema_version: 1.3
last_updated: "2026-06-03T14:00:39-04:00"
summary_hash: 6606834085c88acf9851671ea710da11
---

- Extracted utility tests for frontmatter.py and security.py into separate dedicated files: tests/test_frontmatter.py and tests/test_security.py.
- Promoted isolated test cases for token signatures (ghp, AKIA, sk), Shannon entropy, bare string validation, list/boolean YAML parsing, and invalid keys.
- Ensured high-level tests remain in test_memory_fabric.py, while modular components have dedicated fast units.
