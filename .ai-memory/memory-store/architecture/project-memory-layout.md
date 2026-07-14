---
store_path: architecture/project-memory-layout
title: "Project Memory Layout"
summary: "Project Memory Layout"
priority: high
tags: [architecture, design, overview, migrated]
schema_version: 1.3
last_updated: "2026-07-13T21:22:38-04:00"
---

Shared memory files are stored in `.ai-memory/` in the project root:

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

All shared memory files use YAML frontmatter for metadata.
