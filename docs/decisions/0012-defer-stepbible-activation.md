# 0012 - Defer STEPBible activation

- Status: Accepted
- Date: 2026-07-12
- executing_agent: Codex

The project owner authorized this deferral before execution through the
Milestone 4 governance-closure instruction issued on 2026-07-12.

## Context

Milestone 4 originally placed a STEPBible adapter on its critical path. Since
that plan was written, the milestone has established the required
supplementary-data foundation without activating STEPBible:

- MACULA Hebrew and Greek provide the required primary linguistic foundation.
- OSHB supplies the required Ketiv/Qere supplementary layer.
- Generic supplementary-annotation, conflict-preservation,
  structural-alignment, and versification-crosswalk infrastructure exists.

No specific downstream capability currently requires a STEPBible file.
Acquiring STEPBible now would therefore introduce file-level provenance,
licensing, namespace, and annotation-conflict work without a demonstrated
analytical benefit.

## Decision

STEPBible ingestion is deferred and is not required to close Milestone 4.
STEPBible remains an eligible future supplementary source. A later milestone
may activate it only after identifying and documenting all five of the
following:

1. A specific missing field or capability.
2. The exact STEPBible files required.
3. A measurable benefit.
4. Completed file-level licensing and provenance review.
5. A conflict-preserving integration design.

This deferral does not constitute rejection of STEPBible or a licensing
determination. Its seven recorded subset-audit questions remain unresolved.
The source must not be approved, blocked, acquired, validated, or ingested on
the authority of this decision.

## Rationale

Project Echoes activates datasets to meet demonstrated research needs, not
merely because data is available. The completed OSHB and generic alignment
work satisfies Milestone 4's supplementary-annotation obligations while
preserving primary annotations and source-native identity. Deferral avoids
premature source-specific complexity and preserves STEPBible as an option when
a later analytical requirement can justify the exact data and integration
cost.

## Consequences

- The STEPBible manifest record retains an inactive review state with no
  version, acquisition date, expected files, hashes, or adapter.
- The repository performs no STEPBible acquisition, ingestion, source
  validation, namespace assignment, or annotation reconciliation at Milestone
  4 closure.
- The seven file-level provenance and licensing questions remain open and must
  be answered for the exact proposed files before future activation.
- A future activation requires a reviewed governance change that demonstrates
  all five activation criteria above; this ADR alone grants no acquisition or
  processing authority.

## Alternatives considered

- **Acquire a broad STEPBible snapshot now:** rejected because no downstream
  requirement identifies which files provide measurable value, and a broad
  snapshot would expand provenance and conflict-review scope unnecessarily.
- **Declare STEPBible rejected or license-blocked:** rejected because the
  current decision makes neither a source-quality judgment nor a licensing
  determination.
- **Require STEPBible solely because it appeared in the original Milestone 4
  plan:** rejected because the generic infrastructure and OSHB layer now meet
  the milestone's demonstrated supplementary-data requirements.
