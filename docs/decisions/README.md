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
- executing_agent: Codex | Claude | ChatGPT | Human | Mixed

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
- [0005 — Select pinned MACULA Hebrew node data](0005-macula-hebrew-source-selection.md)
- [0006 — Derive canonical Hebrew token identifiers](0006-canonical-token-identifiers.md)
- [0007 — Preserve source forms and derive conservative Hebrew analytical forms](0007-hebrew-normalization-policy.md)
- [0008 — Apply approved methodological amendments](0008-methodology-amendments.md)
- [0009 — Supply Ketiv readings from OSHB keyed to MACULA word-number gaps](0009-oshb-ketiv-qere-supplementation.md)
- [0010 — Select pinned MACULA Greek Nestle1904 node data](0010-macula-greek-source-selection.md)
- [0011 — Separate source order from disputed-passage analysis](0011-disputed-passage-segmentation-policy.md)
- [0012 — Defer STEPBible activation](0012-defer-stepbible-activation.md)
- [0013 — Passage identity, membership, and analytical continuity](0013-passage-identity-membership-and-analytical-continuity.md)
- [0014 — Known-link benchmark identity, tiering, mapping, and leakage control](0014-known-link-benchmark-identity-tiering-mapping-and-leakage-control.md)
