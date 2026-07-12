# 0011 - Separate source order from disputed-passage analysis

- Status: Accepted
- Date: 2026-07-12
- executing_agent: Codex

## Context

The pinned Nestle 1904 representation places an alternate ending of Mark at
`MRK 16:99` immediately after the inline longer ending at `MRK 16:20`. The first
Milestone 4 declaration called this a non-contiguous verse adjacency and allowed
Milestone 5 either to treat the pair as adjacent or exclude it. That formulation
conflated a physical source-order fact with permission to build an analytical
passage and could concatenate alternate endings in a two-verse or five-verse
window.

The edition also contains the longer ending of Mark and the pericope adulterae
inline, while omitting fifteen later-numbered verses. Segmentation therefore
needs reproducible policies for disputed text, source-order gaps, and future
candidate review without altering source tokens or pretending to settle textual
criticism.

## Decision

1. Physical source succession and analytical continuity are separate data.
   `MRK 16:20` physically precedes `MRK 16:99`, with a reference gap, but a
   matching analytical boundary prohibits two-verse and five-verse windows from
   crossing between them.
2. `MRK 16:99` is classified as an inline alternate ending, not a sequential
   continuation of the longer ending.
3. The `edition_complete` profile includes every token present inline in the
   pinned edition. It is the default profile.
4. The `critical_core` profile excludes exactly `MRK 16:9-16:20`, `MRK 16:99`,
   and `JHN 7:53-8:11`. Exclusion is a derived analytical selection and never
   deletes, rewrites, or renumbers source tokens.
5. Edition-omitted verse numbers are never fabricated. Extant verses on either
   side of an omitted number may remain adjacent in source order, but every
   resulting passage must set `reference_gap`.
6. Alternate readings or endings are never concatenated merely because source
   files place them consecutively.
7. Future candidates intersecting declared disputed text set
   `disputed_passage_flag`. A candidate may retain `strong candidate` status
   only after it survives exclusion of the disputed text or receives a completed
   textual-criticism review.

## Consequences

`config/segmentation.yaml` schema version 2 replaces the ambiguous adjacency
declaration with source successors, analytical boundary breaks, disputed ranges,
analysis profiles, and explicit gap and candidate policies. Milestone 4 records
and validates this contract only. Passage generation, profile materialization,
and candidate flagging remain assigned to their governing future milestones.

Milestone 5 validation must prove that no two-verse or five-verse unit combines
the Mark endings, that omitted verse numbers are not invented, and that both
profiles reproduce deterministically. Later candidate stages must preserve the
disputed-text review status alongside candidate evidence.

## Alternatives rejected

- Treat `MRK 16:20` and `MRK 16:99` as analytical neighbors because they are
  consecutive in the source: rejected because they are alternate endings.
- Remove disputed text at ingestion: rejected because it destroys edition
  evidence and prevents profile-controlled analysis.
- Fabricate omitted verse records to make numbering continuous: rejected because
  it falsifies the pinned edition's contents.
- Allow a disputed-text candidate to remain strong with only an automatic flag:
  rejected because exclusion sensitivity or textual-critical review is required.
