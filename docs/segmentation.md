# Segmentation

Status: **Milestone 5 policy placeholder; no passage generation is implemented**.
Planned granularities and the approved edition-handling rules are declared in
`config/segmentation.yaml`.

## Ketiv structural-uncertainty handoff

Milestone 4 completed supplementary OSHB Ketiv tokens and explicit structural
alignment records. Milestone 5 must consume those records under the following
acceptance contract without treating derived alignments as source-native
structure:

- The default Qere stream retains complete primary MACULA sentence, clause,
  and phrase membership.
- Verse-level Ketiv analysis includes every Ketiv token.
- Sentence-level Ketiv analysis may use the completed sentence mappings.
- Clause- and phrase-level Ketiv analysis must never fabricate membership when
  the applicable mapping is unresolved.
- Every passage that intersects an unresolved Ketiv clause or phrase mapping
  must set `ketiv_structural_uncertainty: true`.
- A granularity-specific sensitivity analysis may exclude an unresolved Ketiv
  mapping, but it must record the exclusion and affected token IDs explicitly.
  The tokens remain in the corpus and in verse-level Ketiv analysis; they must
  never disappear silently.

This contract does not authorize passage generation. It defines the acceptance
conditions the Milestone 5 implementation must satisfy.

## Source succession is not analytical adjacency

The pinned MACULA Greek source physically places `MRK 16:99` immediately after
`MRK 16:20`. The configuration records that edition fact as a source successor
with `relation: alternate_ending` and `reference_gap: true`. It separately
declares an analytical boundary break over the same pair.

Consequently, Milestone 5 must never construct a two-verse or five-verse window
that combines `MRK 16:20` and `MRK 16:99`. The latter remains available as its
own verse passage in the edition-complete profile; its position in a source file
does not turn two alternate endings into one analytical sequence.

The boundary applies to every multi-verse granularity: no multi-verse passage
may contain both `MRK 16:20` and `MRK 16:99`.

ADR 0011 is binding for this boundary, all disputed-passage declarations,
reference-gap behavior, analysis-profile membership, and future candidate
eligibility. The Ketiv structural-uncertainty contract does not weaken or
override any of those requirements.

## Analysis profiles

Two future segmentation profiles are registered:

- `edition_complete` starts from all text present inline in the pinned edition,
  including Mark 16:9-20, Mark 16:99, and John 7:53-8:11.
- `critical_core` excludes exactly the inline longer ending of Mark
  (`MRK 16:9-16:20`), the alternate ending (`MRK 16:99`), and the pericope
  adulterae (`JHN 7:53-JHN 8:11`).

`edition_complete` is the default. Registering both profiles does not decide a
textual-critical question or rewrite the source; it makes the analytical
selection explicit and reproducible.

## Omitted verse numbers and reference gaps

The fifteen edition-omitted Greek verses declared in
`config/greek_ingestion.yaml` must never be fabricated. Physical source order
may still make the surrounding extant verses successive for a sliding window.
Any such passage must carry `reference_gap: true`, preserving the fact that its
canonical reference sequence is discontinuous.

This numbering-gap rule does not override analytical boundary breaks. Alternate
readings or endings must never be concatenated merely because they are adjacent
in source or file order.

## Future candidate handling

A future candidate whose evidence intersects a declared disputed passage must
set `disputed_passage_flag`. It may retain `strong candidate` status only if it
survives exclusion of the disputed text or receives a completed
textual-criticism review. This is a downstream eligibility contract, not a
candidate-generation implementation in Milestone 4.
