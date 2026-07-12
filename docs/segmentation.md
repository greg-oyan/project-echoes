# Segmentation

Status: **Milestone 5 policy placeholder; no passage generation is implemented**.
Planned granularities and the approved edition-handling rules are declared in
`config/segmentation.yaml`.

## Source succession is not analytical adjacency

The pinned MACULA Greek source physically places `MRK 16:99` immediately after
`MRK 16:20`. The configuration records that edition fact as a source successor
with `relation: alternate_ending` and `reference_gap: true`. It separately
declares an analytical boundary break over the same pair.

Consequently, Milestone 5 must never construct a two-verse or five-verse window
that combines `MRK 16:20` and `MRK 16:99`. The latter remains available as its
own verse passage in the edition-complete profile; its position in a source file
does not turn two alternate endings into one analytical sequence.

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
