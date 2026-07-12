# Segmentation

Status: **Milestone 5 architecture is active and implementation is in progress;
generated passage artifacts are not yet accepted or regression-pinned**.

At the Milestone 4 closure gate this document stated:

> no passage generation is implemented

That historical handoff boundary has now been superseded by the accepted
Milestone 5 architecture, but it remains important: the architecture alone
does not establish a completed or accepted corpus run.

The governing policy is declared in `config/segmentation.yaml`, the row and
storage contracts are documented in [Passage schema](passage-schema.md), and
ADR 0013 governs passage identity, exact membership, and analytical continuity.

## Architecture overview

Milestone 5 derives five passage granularities:

- source-native clauses
- source-native sentences
- extant verses
- complete two-verse windows
- complete five-verse windows

Source clause and sentence boundaries remain primary even when a unit spans
more than one verse. Verse and window construction does not split those units.
Windows are derived from analytical continuity between extant verse passages,
not from numeric verse arithmetic.

The architecture materializes six analytical stream contexts:

- Hebrew/Aramaic `edition_complete` + `qere`
- Hebrew/Aramaic `edition_complete` + `ketiv`
- Hebrew/Aramaic `critical_core` + `qere`
- Hebrew/Aramaic `critical_core` + `ketiv`
- Greek `edition_complete` + `source`
- Greek `critical_core` + `source`

Every stream row preserves the token's source position and separately records
its selected-stream position. Qere retains complete MACULA structure. Ketiv
performs exact registered substitutions and uses the OSHB structural mapping.
Greek preserves the inline source order. Profile selection changes analytical
membership without mutating, deleting, or renumbering a source token.

## Authoritative membership

`passage_membership` is authoritative. It records every token, its one-based
position in the passage, both source and selected-stream positions, provenance,
reading information, membership basis, and structural-resolution status.

The passage table's start/end token IDs and stream positions are convenience
fields. They cannot represent Ketiv substitution, profile selection, reference
gaps, or window composition by themselves. Validation therefore reconstructs
the boundary fields, counts, ordered token and feature arrays, text, and
passage identity from exact membership.

## Passage and run identity

Passage-ID schema version 1 uses a readable corpus/profile/reading/granularity
prefix plus a complete SHA-256 digest. The canonical payload contains the
schema version, corpus, profile, reading, granularity, book, scoped source-unit
ID where applicable, exact ordered references, and exact ordered token IDs.

Identity excludes database order, local paths, timestamps, random values, Git
commits, generated row numbers, mutable crosswalks, and the full configuration
hash. Duplicate payloads or digest collisions are fatal.

The segmentation run ID covers the schema versions, relevant normalized
configuration, selected scope, pinned source versions, and input digests. It
excludes output paths and execution telemetry. Two equivalent validated runs
must reproduce the run ID and deterministic logical outputs.

## Storage semantics

The six logical artifacts are:

- `passages`
- `passage_membership`
- `passage_adjacency`
- `segmentation_exclusions`
- `segmentation_issues`
- `segmentation_metadata`

They use explicit Polars schemas and deterministic Parquet under
`data/processed/passages/schema-v1/`, partitioned by corpus, profile, reading,
and granularity, with deterministic book-sized leaves for non-metadata tables.
Writes use Zstandard compression, statistics, staged atomic replacement,
explicit `--force`, and recovery of the previous target after a failed
replacement. The directory and local DuckDB database remain Git-ignored.

DuckDB exposes passage artifacts transactionally without copying the immutable
source corpus tables. Logical hashes describe typed ordered content; physical
hashes describe exact Parquet bytes. Runtime and environment telemetry remain
metadata outside deterministic logical identity.

## Reconstruction

Reconstruction is language-aware rather than a universal space join.

- Hebrew and Aramaic group morphemes by source word and preserve morpheme
  order, the selected Qere or Ketiv reading, source separators including
  maqqef, and punctuation. Zero-width tokens remain members but add no visible
  text. Surface, normalized, and unpointed forms remain separate.
- Greek validates and uses leading punctuation, the preserved surface/core
  form, trailing punctuation, elision metadata, and source order. It avoids
  spaces before closing punctuation and retains opening punctuation. Surface,
  normalized, and folded forms remain separate.

Ordered lemma, root, part-of-speech, semantic-domain, entity, and participant
arrays contain one entry per member. JSON `null` remains distinct from an empty
string.

## Validation layers

Passage validation must fail nonzero on errors and check:

- pinned primary and OSHB digest invariance
- reproducible passage and run identity
- continuous, duplicate-free membership and exact boundary mirrors
- complete source clause and sentence units
- selected-stream verse coverage, including every Ketiv token
- explicit unresolved Ketiv exclusions and no silent token loss
- extant-source-order windows, reference gaps, profiles, and boundary breaks
- deterministic Hebrew, Aramaic, and Greek reconstruction
- stable logical outputs across two equivalent runs

Warnings fail strict validation. Informational findings do not fail validation.
The structure audit and active schemas establish the architecture; they do not
replace the required two-run full-corpus acceptance and regression-pinning
work.

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

This handoff contract does not by itself establish an accepted passage run. It
defines acceptance conditions the Milestone 5 implementation must satisfy.

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

Two active segmentation profiles are registered:

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
