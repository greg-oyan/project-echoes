# Architecture and research decision records

Decision records preserve durable methodological, data, licensing, architecture, and claim-governance choices. They explain why a choice was made and make later revisions explicit rather than silently rewriting project history.

## Process

1. Copy the template below into the next zero-padded file, for example `0005-source-version-policy.md`.
2. Use one of: `Proposed`, `Accepted`, `Superseded by ADR NNNN`, `Deprecated`, or `Rejected`.
3. Cite the evidence and affected configurations or schemas.
4. Obtain normal code review and pass the active milestone gate.
5. Supersede an accepted decision with a new ADR; do not erase it.

## Template

```markdown
# NNNN — Short decision title

- Status: Proposed
- Date: YYYY-MM-DD

## Context

## Decision

## Rationale

## Consequences

## Alternatives considered
```

## Current records

- [0001 — Primary corpus boundary](0001-primary-corpus-boundary.md)
- [0002 — Layered corpus strategy](0002-layered-corpus-strategy.md)
- [0003 — No LLM primary discovery](0003-no-llm-primary-discovery.md)
- [0004 — Local-first architecture](0004-local-first-architecture.md)
