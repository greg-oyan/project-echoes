# 0013 — Passage identity, membership, and analytical continuity

- Status: Accepted
- Date: 2026-07-12
- executing_agent: Codex
- Owner authorization: The project owner authorized this decision and its
  Milestone 5 implementation through the current goal before execution.

## Context

Milestone 5 must derive clause, sentence, verse, two-verse, and five-verse
passages from the validated Hebrew, Aramaic, and Greek token corpora without
changing source identity. A passage is not always a contiguous database row
range: Ketiv substitutes supplementary records for primary Qere records,
critical-core profiles omit configured text without deleting it, and valid
source-order windows can span an edition-omitted verse number.

The full-corpus structure audit found 23,213 Hebrew and 8,011 Greek source
sentences, 97,106 Hebrew and 46,216 Greek source clauses, and no identifier
collision across corpus or book scope. It also found 1,194 Greek sentences and
277 Greek clauses crossing verse boundaries, but no sentence or clause crossing
a chapter or book boundary. No source sentence or clause straddles any
`critical_core` exclusion boundary, so the owner-approved whole-unit exclusion
policy is unambiguous and the early-stop condition is not triggered.

The audit confirmed fifteen edition-omitted Greek verse numbers. One source
sentence spans an omission: the 44-token unit
`Nestle1904/nodes/05-acts.xml#sentence-0760:ACT 24:5!1-24:8!13` contains extant
references Acts 24:5, 24:6, and 24:8. It must remain a source-native sentence
and carry a reference-gap marker. The physical successor `MRK 16:20` to
`MRK 16:99` remains analytically broken under ADR 0011.

The OSHB structural layer contains 1,268 Ketiv tokens. Sentence membership is
resolved for all 1,268; clause membership is resolved for 1,013 and unresolved
for 255; phrase membership is resolved for 450 and unresolved for 818. The
6,435 primary Hebrew zero-width tokens remain real membership records but
produce no visible reconstruction text. Greek has no punctuation-only token
records; punctuation is carried on word-token metadata.

## Decision

### Passage identity

Passage identity schema version 1 uses a readable prefix plus the complete
64-character SHA-256 digest. The digest input is canonical JSON
containing, in this order:

1. Passage-ID schema version
2. Corpus
3. Analysis profile
4. Analysis reading
5. Granularity
6. Canonical book
7. The scoped source-unit ID when applicable
8. The exact ordered source-reference sequence
9. Exact ordered token IDs

Canonical JSON uses stable key ordering and separators. Passage identity never
depends on a database row number, table order, local path, timestamp, random
value, Git commit, generated row number, mutable crosswalk, or the full
segmentation-configuration hash. Every emitted ID is recomputed from its
payload. Duplicate payloads and digest collisions are errors; they are never
silently repaired.

### Exact membership

The passage-membership table is authoritative. Each row records the passage,
token, one-based position, source corpus position, source reference, source,
variant type, membership basis, and structural-resolution status. A passage's
start and end token IDs are convenience fields only. Membership must be
continuous in passage position, ordered by the selected source stream, contain
no duplicate token, and reproduce the token-dependent passage identity.

### Source structure and analytical profiles

Source-native sentence and clause IDs are scoped with corpus, book, and source
unit rather than assumed globally unique. Source units retain their complete
membership even when they span verses. `edition_complete` includes all inline
source text. `critical_core` excludes exactly `MRK 16:9-16:20`, `MRK 16:99`,
and `JHN 7:53-8:11`. Profile selection changes analytical membership only; it
never deletes, renumbers, truncates, or duplicates source tokens. A profile
exclusion breaks analytical continuity, including between `JHN 7:52` and
`JHN 8:12`.

### Qere, Ketiv, and Greek streams

Hebrew and Aramaic materialize Qere and Ketiv readings under both profiles.
Greek materializes the source reading under both profiles. The primary Qere
stream retains complete MACULA sentence, clause, and phrase annotation. Ketiv
verse passages contain every Ketiv token and the non-replaced primary tokens;
resolved sentence and clause mappings may be used. Unresolved Ketiv clause
membership is never inferred. Greek uses the exact inline source stream.

### Reconstruction

Reconstruction is deterministic and language-aware. Hebrew and Aramaic use
source word grouping and morpheme order, preserve the selected reading and
source punctuation behavior, and keep zero-width tokens in membership without
rendering visible garbage. Greek uses leading punctuation, surface form,
trailing punctuation, elision metadata, and source order, without spaces before
closing punctuation or loss of opening punctuation. Source, normalized,
unpointed, and folded representations remain separate where applicable; null
is never collapsed into an empty string.

### Sliding windows and analytical continuity

Windows are composed only from analytically continuous extant verse passages,
never from numeric verse arithmetic. They may cross chapters but never books.
Only complete two-verse and five-verse windows are emitted. They do not bridge
profile exclusions or analytical boundary breaks, and no window combines
`MRK 16:20` with `MRK 16:99`. Ordered references and constituent verse-passage
IDs are preserved, membership is their duplicate-free ordered concatenation,
and neighbor overlap records actual token overlap.

### Reference gaps and disputed passages

Edition-omitted verse records are never fabricated. Extant source-order
neighbors around an omission may be analytically continuous, but every passage
spanning the omission sets `reference_gap=true`. Physical source succession and
analytical continuity remain independent facts in passage adjacency.

Every passage intersecting declared disputed text sets the disputed flag and
identifiers. ADR 0011 governs the three declared ranges and the Mark-ending
boundary. Source units are not truncated at profile boundaries; any future
straddle would reactivate the early-stop decision requirement.

### Structural uncertainty and sensitivity exclusions

Every passage intersecting an unresolved Ketiv clause or phrase mapping sets
`ketiv_structural_uncertainty=true`. Each unresolved Ketiv clause token produces
an explicit clause-granularity exclusion row containing its token, locus,
reference, reason, resolution, and related passages. Phrase uncertainty is
flagged even though phrase is not a Milestone 5 passage granularity. Excluded
tokens remain in the corpus and Ketiv verse stream. No granularity-specific
sensitivity exclusion may occur without an auditable exclusion record; no token
may disappear silently.

### Storage and determinism

Passages, authoritative membership, adjacency, exclusions, issues, and metadata
are stored as explicitly typed, deterministically sorted Parquet under
`data/processed/passages/schema-v1/`, partitioned by corpus, analysis profile,
analysis reading, and granularity. Writes are atomic, use Zstandard compression
and statistics, refuse silent overwrite, and require an explicit `--force` for
generated segmentation artifacts only. DuckDB exposes these artifacts
transactionally without copying source corpus tables.

Identical validated inputs and relevant configuration produce identical run
IDs, passage IDs, ordered rows, logical hashes, and—where the writer guarantees
it—physical hashes. Timestamps, local paths, and processing environment are
metadata excluded from deterministic logical hashes. Reordered input rows do
not change canonical outputs.

## Rationale

Exact membership is the smallest model that handles source-native structure,
reading substitution, profile exclusions, omitted reference numbers, and
window composition without information loss. Separating physical succession
from analytical continuity preserves the edition while preventing invalid
passages. A canonical content payload makes identity reproducible and sensitive
only to changes that alter what a passage is.

## Consequences

- Passage validation must reproduce identity from authoritative membership.
- Start/end token IDs cannot stand in for membership during audit or loading.
- The 255 clause-unresolved Ketiv tokens require explicit clause exclusions;
  all 1,268 Ketiv tokens remain in verse analysis.
- The Acts 24:5-8 source sentence remains intact and records its reference gap.
- Profile-specific content can be stored efficiently, but profile identity must
  remain explicit on every emitted passage.
- Configuration schema version 3 activates and validates these policies.

## Alternatives considered

- **Represent passage membership only through start and end token IDs:**
  rejected because substitution, profile selection, and reference gaps make a
  range incomplete or misleading.
- **Fabricate clause membership for unresolved Ketiv tokens:** rejected because
  it would convert an explicit mapping limitation into false source structure.
- **Bridge profile exclusions as though removed text never existed:** rejected
  because it creates analytical adjacency unsupported by the source stream.
- **Combine Mark 16:20 and Mark 16:99 because they are adjacent in source
  order:** rejected because they are alternate endings and ADR 0011 requires a
  boundary break.
- **Fabricate omitted verse records:** rejected because it falsifies the pinned
  edition and obscures real reference gaps.
- **Generate windows by numeric verse arithmetic alone:** rejected because
  source order includes omissions, chapter transitions, profiles, and explicit
  boundary breaks.
- **Use database row numbers as passage identity:** rejected because storage
  order is mutable and not a textual property.
- **Naively join token surfaces with spaces without language-specific
  reconstruction:** rejected because it corrupts Hebrew word grouping,
  zero-width behavior, Greek punctuation, and elision.
