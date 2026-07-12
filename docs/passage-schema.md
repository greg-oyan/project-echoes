# Passage schema

Status: **Milestone 5 schema version 1 is active; full passage generation,
determinism pinning, and the Milestone 5 acceptance gate remain in progress**.

This document describes the typed passage contract established by ADR 0013,
`config/segmentation.yaml`, and `src/echoes/segment/models.py`. It does not
report generated passage counts or claim that Milestone 5 is complete.

## Authority and data ownership

`passage_membership` is the authoritative mapping between a passage and its
tokens. A passage is defined by its exact ordered membership, not by a database
row range and not by its first and last token alone.

The following fields in `passages` are conveniences derived from membership:

- `start_token_id` and `end_token_id`
- `start_stream_position_in_corpus` and `end_stream_position_in_corpus`
- `token_ids_json`
- token, visibility, punctuation, word, sentence, and clause counts
- reconstructed text and ordered analytical sequences

Validation must reproduce these values from ordered membership. A disagreement
is an error; the convenience fields never override membership.

Source corpus and OSHB supplement tables remain immutable. Segmentation stores
derived passage artifacts separately and never copies or rewrites source token
identity. `source_position_in_corpus` preserves the position inside a token's
own source domain. `stream_position_in_corpus` records its order in the selected
Qere, Ketiv, or Greek analytical stream. This distinction is essential because
OSHB and MACULA positions are not intersortable source coordinates.

## Logical tables

Schema version 1 defines six logical artifacts.

| Artifact | Purpose | Authoritative key or order |
|---|---|---|
| `passages` | Passage identity, scope, reconstructed forms, flags, and summaries | Unique `passage_id` |
| `passage_membership` | Exact passage-to-token mapping | `passage_id`, then one-based `position_in_passage` |
| `passage_adjacency` | Physical source succession and analytical continuity | Context plus `from_passage_id`, `to_passage_id` |
| `segmentation_exclusions` | Explicit granularity-specific token exclusions | Unique `exclusion_id` |
| `segmentation_issues` | Deterministic validation findings | Unique `issue_id` |
| `segmentation_metadata` | Run provenance, hashes, scope, and telemetry | Unique `segmentation_run_id` |

Pydantic models define strict row validation. Matching Polars schemas define
the stable persisted column order and data types. Full-corpus validation is
vectorized; it does not require constructing a Pydantic object for every
membership row.

## `passages`

The passage table groups its fields by responsibility.

### Identity and scope

- `schema_version`
- `passage_id`
- `identity_payload_sha256`
- `segmentation_run_id`
- `corpus`
- `analysis_profile`
- `analysis_reading`
- `granularity`
- `book`
- `book_order`
- `segmentation_config_hash`
- `created_by_schema_version`

Hebrew passages use the `qere` or `ketiv` reading. Greek passages use the
`source` reading. Every passage states its profile explicitly, including where
the two Hebrew profiles have content-equivalent membership.

### References and membership mirrors

- `start_reference`
- `end_reference`
- `reference_sequence_json`
- `token_ids_json`
- `source_unit_id`
- `constituent_verse_passage_ids_json`
- `start_token_id`
- `end_token_id`
- `start_stream_position_in_corpus`
- `end_stream_position_in_corpus`

Clause and sentence passages retain a properly scoped source-unit identifier.
Verse passages preserve one extant reference. Window passages preserve the
ordered reference sequence and exactly two or five constituent verse-passage
IDs. Non-window passages have an empty constituent array.

### Counts and provenance

- `token_count`
- `visible_token_count`
- `zero_width_token_count`
- `punctuation_token_count`
- `word_count`
- `sentence_count`
- `clause_count`
- `source_ids_json`
- `source_versions_json`

`visible_token_count + zero_width_token_count` must equal `token_count`.
Zero-width records remain authoritative members even though they contribute no
visible characters to reconstruction.

### Reconstructed forms and ordered features

- `surface_text`
- `normalized_text`
- `unpointed_text`
- `folded_text`
- `lemma_sequence_json`
- `root_sequence_json`
- `part_of_speech_sequence_json`
- `semantic_domain_sequence_json`
- `entity_ids_json`
- `participant_ids_json`

Hebrew and Aramaic require `unpointed_text` and leave `folded_text` null. Greek
requires `folded_text` and leaves `unpointed_text` null. Every ordered feature
array has exactly `token_count` entries. A missing annotation is JSON `null`;
it is not rewritten as an empty string.

### Analytical flags and neighbors

- `disputed_passage_flag`
- `disputed_passage_ids_json`
- `reference_gap`
- `ketiv_structural_uncertainty`
- `profile_truncated`
- `sensitivity_exclusion_count`
- `previous_passage_id`
- `next_passage_id`
- `overlap_with_previous_token_count`
- `overlap_with_next_token_count`

The disputed flag must agree with the disputed-ID array. `profile_truncated`
must remain false under the approved whole-source-unit policy. Window overlap
is measured from exact token membership, not inferred from the window size.

## `passage_membership`

Each membership row stores:

- `passage_id`
- `token_id`
- `position_in_passage`
- `source_position_in_corpus`
- `source_reference`
- `source_id`
- `variant_type`
- `membership_basis`
- `structural_resolution_status`
- `segmentation_run_id`
- `corpus`
- `analysis_profile`
- `analysis_reading`
- `granularity`
- `stream_position_in_corpus`
- `source_edition_reference`
- `source_version`
- `locus_id`

Positions begin at one and are continuous inside each passage. A token may not
occur twice in one passage. Membership order follows the selected analytical
stream and must reproduce the passage's reference sequence, token sequence,
boundary fields, counts, reconstruction, and identity payload.

`membership_basis` makes derivation explicit:

- `source_native`
- `qere_primary`
- `ketiv_verse_stream`
- `ketiv_sentence_alignment`
- `ketiv_clause_alignment`
- `window_composition`

Structural status is one of `source_native`, `resolved`,
`partially_resolved`, or `unresolved`. Supplementary structure is never
presented as source-native MACULA or OSHB annotation.

## `passage_adjacency`

Adjacency rows store the corpus, profile, reading, and granularity context,
followed by:

- `from_passage_id`
- `to_passage_id`
- `source_successor`
- `analytically_continuous`
- `reference_gap`
- `boundary_break`
- `relation`
- `reason`
- `segmentation_run_id`

`source_successor` and `analytically_continuous` are independent facts. A
boundary break cannot be analytically continuous. This permits the edition to
record `MRK 16:20 -> MRK 16:99` as physical succession while prohibiting it as
an analytical edge.

## `segmentation_exclusions`

An exclusion row is required whenever a token is omitted from one affected
granularity. It stores:

- `exclusion_id` and `segmentation_run_id`
- corpus, profile, reading, and granularity
- `token_id`, optional `locus_id`, and `source_reference`
- `reason_code` and `resolution_status`
- `related_passage_ids_json` and `notes`
- `source_id`, `source_version`, and `source_edition_reference`
- `stream_position_in_corpus`

An exclusion is local to its declared granularity. In particular, an
unresolved Ketiv clause mapping creates a clause exclusion without removing
the token from the Ketiv stream, corpus, or verse passage. No silent token loss
is permitted.

## `segmentation_issues`

Issue rows contain an ID, run ID, severity, code, message, optional analytical
context, optional passage/token/reference, and structured `details_json`.
Allowed severities are `error`, `warning`, and `informational`. Errors fail
validation. Warnings also fail strict validation. Unknown severities are
errors.

## `segmentation_metadata`

The single run-level metadata row records:

- segmentation run, passage-schema, passage-ID-schema, and configuration IDs
- source versions
- primary identity, surface/lemma, and analytical digests
- OSHB supplement digests
- enabled corpora, profiles, readings, and granularities
- table counts and logical and physical table hashes
- processing environment, runtime, approximate peak memory, and output size

Runtime, local paths, timestamps, and environment observations do not enter
passage identity or deterministic logical hashes. Telemetry remains provenance
metadata rather than textual identity.

## Passage identity

Passage-ID schema version 1 hashes canonical compact JSON containing, in this
order:

1. Passage-ID schema version
2. Corpus
3. Analysis profile
4. Analysis reading
5. Granularity
6. Canonical book
7. Scoped source-unit ID when applicable
8. Exact ordered reference sequence
9. Exact ordered token IDs

The persisted ID uses a readable `P_HB_...` or `P_GNT_...` prefix followed by
the complete 64-character SHA-256 digest. The full digest is also stored as
`identity_payload_sha256`. Passage IDs never depend on table row order, local
paths, timestamps, random identifiers, Git commits, generated row numbers, a
mutable crosswalk, or the full segmentation-configuration hash.

Every ID is recomputed during validation. Duplicate payloads and digest
collisions fail rather than receiving a suffix or other silent repair. A
profile, reading, source-unit, reference, or membership change therefore
changes identity; an unrelated operational setting does not.

## Segmentation run identity

A segmentation run identifies one validated combination of schema versions,
relevant normalized segmentation configuration, selected scope, pinned source
versions, and input logical digests. It excludes output paths, database paths,
timestamps, runtime, host details, and Git state.

Identical validated inputs and relevant configuration must reproduce the run
ID and every deterministic logical output. A relevant policy change must
change the run ID. Observational metadata may change between executions and is
excluded from the deterministic hash domain.

## Storage

Generated artifacts belong under:

```text
data/processed/passages/schema-v1/
```

The directory is Git-ignored. Large outputs are partitioned in the canonical
order `corpus`, `analysis_profile`, `analysis_reading`, and `granularity`.
Non-metadata artifacts use deterministic book-sized leaves beneath that
context; metadata has one global leaf. Parquet files use explicit schemas,
stable column order, deterministic sorting, Zstandard compression, and
statistics.

Writes stage a complete generated artifact set before replacing the target.
They refuse silent overwrite, require explicit `--force`, and restore the old
target after a failed replacement. `--force` applies only to generated
segmentation artifacts and cannot bypass source, digest, schema, profile, or
boundary validation.

DuckDB exposes the six logical artifacts and convenience views transactionally.
It does not duplicate the source corpus tables, and rerunning the loader must
not duplicate passage rows. Physical Parquet hashes and logical table hashes
are recorded separately.

## Validation contract

Passage validation covers:

- pinned primary and OSHB input invariance
- unique, reproducible passage identities
- continuous, duplicate-free authoritative membership
- source-native sentence and clause boundaries
- resolved Ketiv mappings and explicit unresolved exclusions
- exact verse coverage for every selected stream
- extant-source-order window continuity and complete window sizes
- language-aware reconstruction and ordered feature arrays
- exact profile membership and no source-token mutation
- deterministic run IDs, logical hashes, and governed physical hashes

The schema is necessary but not sufficient for Milestone 5 acceptance. The
milestone remains open until two complete local runs agree, output constants
are independently verified and pinned, all quality gates pass, and the
Milestone 5 pull request is open and CI-green.
