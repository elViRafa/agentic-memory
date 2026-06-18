---
store_path: schemas/frontmatter
section: frontmatter-schema
summary: "Schema definition for the YAML frontmatter used across Memory Fabric markdown files."
priority: high
tags: [schemas, frontmatter, yaml]
schema_version: 1.3
last_updated: "2026-06-18T10:06:00-04:00"
---

# Markdown Frontmatter Schema

Every memory section (except `index.md` in some contexts, though it can have it too) begins with a YAML frontmatter block enclosed between `---` delimiters:

```yaml
section: <string>           # Name of the section (e.g. architecture, decisions)
summary: <string>           # A concise 1-sentence summary under 150 characters
priority: high|medium|low   # Priority for inclusion in context budget
tags: [<list of strings>]   # Categorization tags (e.g. [api, auth])
schema_version: "1.3"       # Memory structure version compatibility
last_updated: <iso-8601>    # ISO-8601 timestamp of last update
review_status: stale        # (Optional) set to 'stale' if not updated in 30 days
summary_hash: <md5-hash>    # (Optional) md5 hash of the file body to avoid redundant LLM summarization
```
