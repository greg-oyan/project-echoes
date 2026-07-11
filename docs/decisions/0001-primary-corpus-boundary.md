# 0001 — Primary corpus boundary

- Status: Accepted
- Date: 2026-07-10

## Context

A reproducible first discovery program needs a bounded corpus before source acquisition and method tuning. Biblical traditions use different canonical boundaries, orders, and versification, while the master research question names the Hebrew Bible and Greek New Testament.

## Decision

The initial primary discovery corpus is the Hebrew and Aramaic Old Testament plus Greek New Testament within the 66-book Protestant canonical boundary. MACULA is the intended primary annotated source, subject to governance and validation. English translations are supplementary only. The Septuagint and all other corpora have separate layer roles.

## Rationale

A fixed boundary makes completeness, all-pairs scale, benchmark splits, and published limitations auditable. It matches the first research question while postponing expansions that require different rights, alignments, and interpretive framing.

## Consequences

Book identity and versification require explicit crosswalks. Deuterocanonical books are not initial discovery targets even when included in a Septuagint source. Findings cannot be generalized automatically to other canons. Expanding the boundary requires a new ADR and experiment.

## Alternatives considered

- Begin with every biblical canon: rejected as too broad for the first validated pipeline.
- Search English translations: rejected as the primary evidence layer.
- Start with a small book subset: useful for testing, but insufficient as the declared final primary boundary.
