# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue for security vulnerabilities.

Report privately through GitHub's
[private vulnerability reporting](https://github.com/elViRafa/agentic-memory/security/advisories/new)
("Report a vulnerability" under the repository's **Security** tab). Include the
affected version, a description, and reproduction steps if you have them. We aim
to acknowledge reports within a few days and will keep you updated on the fix.

## Supported versions

Memory Fabric is under active development. Security fixes land on the latest
released version; please upgrade before reporting an issue you hit on an older
release.

## Security posture

Memory Fabric is designed to minimize the blast radius by construction:

- **Local-first, no telemetry.** No account, no cloud, no analytics. The core
  read/write paths make no network calls; optional network checks (PyPI drift,
  LLM-provider preflight) honor an offline mode.
- **Secret redaction on write.** API keys and credential-shaped strings are
  redacted before any memory is written to disk. If a file fails the redaction
  pass, that failure is surfaced, not swallowed.
- **Path safety.** Agent-supplied working directories are validated and known
  dangerous system roots are rejected, to prevent prompt-injection-style path
  traversal from writing outside the intended project.
- **Human-auditable storage.** Memory is plain Markdown + YAML in your git
  history — every write is diffable and reviewable, not opaque embeddings.

## What to include in a report

- The Memory Fabric version (`ai-memory --version`).
- The client/tool and OS, if relevant.
- A minimal reproduction, and the impact you observed or expect.
