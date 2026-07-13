# Known-link benchmark schema

Status: **Milestone 6 schema version 1 locally validated; pull-request and CI acceptance pending**

The known-link benchmark is represented by ten versioned logical artifacts. Each artifact
has a strict Pydantic row model and an ordered Polars schema in
`echoes.benchmarks.models`. Unknown fields fail validation. The generated Parquet and
DuckDB data remain local and Git-ignored; tracked documentation and reports contain only
governance metadata, hashes, aggregate counts, references, and structural findings.

The active versions are:

- Benchmark schema: `1`
- Relationship identity schema: `1`
- Mapping identity schema: `1`

The validated instance is benchmark run `benchmark-v1-dff1d3ef650c8ccd4930`,
benchmark version `known-links-v1-dff1d3ef650c`. The final
`table-hashes.json` and opt-in full-corpus regression pin these logical hashes:

| Artifact | Rows | Logical SHA-256 |
|---|---:|---|
| `benchmark_source_records` | 344,799 | `481e53738ae4f4940277d211176194b97e57908eb31ef172359524165409f1f4` |
| `benchmark_relationships` | 344,799 | `4bd3d602a2604d425c0016eb7d565667a844b353cb16d0d88f3c369c21a13a6f` |
| `benchmark_relationship_source_records` | 344,799 | `f215928778e16ef496ec309282a327559d242f520d531240059ecdbe21ba64a1` |
| `benchmark_endpoints` | 689,598 | `a9560e443ba32b3900f635421f9390f461fdebe0c23f316ec295b7be28ba13c7` |
| `benchmark_endpoint_mappings` | 1,379,196 | `d56e5211a415b51abbfa5080add85ade3ad8d4f30b6c95313fef19e5c6e956e3` |
| `benchmark_leakage_groups` | 4,561,525 | `56c356147c61d12074dbdf88e7ea2dd111e8a2d0e34e7caa530d103e6d66f9d7` |
| `benchmark_split_assignments` | 1,723,995 | `bda3c63f2aa15cd60567fd3a8dae3118402df35fc07921910a218a941c9ac5e0` |
| `benchmark_presumed_negatives` | 29,275 | `9bf1ed5dd30c6a93b6ef359cd7d5fd39704f3c0cb3719e17cbcaae5bf524d6ff` |
| `benchmark_issues` | 18 | `f39d5494a1d13e68e9acf77b44e6c1a38dc419ec52abfb879a26f41165a07de0` |
| `benchmark_metadata` | 1 | `b406ab043ed90ba59204b1b6937ea742ea6d2e66a552a8678934d94b290086d8` |

Two complete builds reproduced all ten logical hashes and every row count. All
content-artifact physical hashes also matched. The metadata Parquet physical
hash alone changed with measured runtime telemetry, which is deliberately
excluded from the registered metadata logical hash.

## Identity layers

Source-record, relationship, pair, endpoint, and mapping identities are deliberately
separate.

- A source-record ID uses source ID, the complete source-archive SHA-256, the exact raw
  record SHA-256, and a deterministic duplicate-occurrence ordinal. Source line number
  remains provenance and does not define identity.
- A relationship ID uses relationship schema version, source ID and version, source
  reference scheme, normalized source endpoints, and source direction. It excludes source
  line number, votes, local paths, passage IDs, mappings, splits, and timestamps.
- Directed and unordered pair IDs are both retained. Reversing a directed relation changes
  its directed identity while the canonical unordered identity remains shared.
- An endpoint ID identifies one normalized relationship side.
- A mapping ID uses endpoint ID, target corpus, profile, reading, verse granularity,
  mapping method, crosswalk version, and exact ordered target passage IDs. A mapping change
  may therefore change the mapping ID without changing the source relationship ID.

All IDs are SHA-256-based and collision checked. Random UUIDs and database row numbers are
not identity inputs.

## 1. `benchmark_source_records`

One row is retained for every physical post-header source record, including duplicate,
blank, and invalid records. No row may disappear silently.

```text
benchmark_schema_version
source_record_id
source_id
source_version
source_archive_sha256
source_file
source_line_number
raw_record_sha256
source_reference_a
source_reference_b
source_weight
source_direction
parse_status
notes
```

`source_line_number` is mutable provenance. `raw_record_sha256` covers the exact record
bytes. A source weight remains a source ranking value, not confidence or a probability of
literary dependence.

## 2. `benchmark_relationships`

One row represents one deterministically normalized, source-specific relationship.
Duplicate source occurrences aggregate here while remaining traceable through the link
artifact.

```text
relationship_id
benchmark_schema_version
tier
source_id
source_version
source_reference_scheme
source_reference_a
source_reference_b
relationship_direction
relationship_class
source_record_count
source_weight_sum
source_weight_max
canonical_directed_pair_id
canonical_undirected_pair_id
weak_supervision_eligible
knownness_filter_eligible
primary_evaluation_eligible
tier1_eligible
data_quality_status
license_status
provenance_json
notes
```

Tier 3 rows cannot be primary-evaluation or Tier 1 eligible. OpenBible relationships retain
their observed direction and broad class; the graph is never silently symmetrized.

## 3. `benchmark_relationship_source_records`

This many-to-many provenance artifact prevents duplicate aggregation from erasing raw
occurrences.

```text
relationship_id
source_record_id
link_role
```

## 4. `benchmark_endpoints`

Each relationship has separate `a` and `b` endpoints in the source's own reference scheme.
Coordinates are either wholly present or wholly absent.

```text
endpoint_id
relationship_id
endpoint_side
source_reference
source_reference_scheme
parsed_book
parsed_start_chapter
parsed_start_verse
parsed_end_chapter
parsed_end_verse
is_range
parse_status
```

Parsing does not assert equivalence with a MACULA edition or a verified versification
crosswalk.

## 5. `benchmark_endpoint_mappings`

Endpoint mapping is a separate uncertainty-bearing layer targeting Milestone 5 verse
passages only.

```text
mapping_id
endpoint_id
target_corpus
target_analysis_profile
target_analysis_reading
target_granularity
target_passage_ids_json
target_reference_sequence_json
mapping_method
mapping_confidence
mapping_status
reference_gap
disputed_passage_flag
disputed_passage_ids_json
crosswalk_source
crosswalk_version
ambiguity_reason
notes
```

The target is `edition_complete`/`verse` by default, with `critical_core` compatibility
stored separately. Hebrew mappings use `qere`; Greek mappings use `source`. Allowed mapping
statuses are:

```text
mapped_verified
mapped_provisional
mapped_partial
unresolved_reference
unresolved_versification
unresolved_missing_target
excluded_by_profile
invalid
```

Same-label mappings without an approved crosswalk are provisional. Ranges expand only to
ordered extant verses. Missing verses are never fabricated; partial mappings, reference
gaps, disputed text, and profile exclusions remain explicit.

## 6. `benchmark_leakage_groups`

One relationship may participate in several explicit leakage groups.

```text
leakage_group_id
relationship_id
group_type
group_key
group_method
notes
```

Implemented group types cover exact directed and unordered pairs, duplicate source
records, shared endpoints, overlapping endpoint ranges, shared and overlapping target
passages, canonical unordered book pairs, relationship families when genuinely available,
and relevant shared source provenance.
One unrestricted graph-connected component is not used as the sole leakage definition.

## 7. `benchmark_split_assignments`

Each row assigns one relationship under one named, deterministic split strategy.

```text
split_assignment_id
benchmark_version
relationship_id
split_strategy
partition
leakage_group_id
seed
eligibility_status
exclusion_reason
config_hash
```

Partitions are `train`, `development`, `test`, or `excluded`; every excluded assignment
requires a reason. Splits operate on governed leakage units rather than randomly splitting
rows. Tier 3 assignments are infrastructure or weak-supervision splits, not definitive
scholarly evaluation sets.

## 8. `benchmark_presumed_negatives`

Generated unlinked pairs are contrastive examples, never proven nonrelationships.

```text
contrastive_id
benchmark_version
passage_a_id
passage_b_id
corpus_pair
negative_strategy
presumed_negative
positive_graph_checked
reverse_pair_checked
passage_overlap_checked
leakage_checked
length_difference
book_pair
genre_pair
split_strategy
partition
seed
generation_config_hash
notes
```

The five check fields are required true. Passage IDs must differ. Generation respects the
positive graph in both directions, passage overlap, leakage groups, and split partitions.
Milestone 6 uses no lexical, semantic, embedding, or candidate score to generate these
pairs.

## 9. `benchmark_issues`

Every deterministic build or validation finding uses a controlled severity and may link
to the affected artifact or identity.

```text
issue_id
benchmark_run_id
severity
code
message
artifact
source_record_id
relationship_id
endpoint_id
details_json
```

Severities are `error`, `warning`, and `informational`. Errors fail validation; warnings
also fail strict validation.

## 10. `benchmark_metadata`

One row records the complete inputs, output identities, counts, and telemetry for a
benchmark build.

```text
benchmark_run_id
benchmark_version
benchmark_schema_version
relationship_id_schema_version
mapping_schema_version
source_versions_json
source_archive_hashes_json
source_file_hashes_json
source_audit_json
tier1_header_sha256
passage_input_run_id
passage_logical_hashes_json
relationship_count
endpoint_count
mapping_count
leakage_group_counts_json
split_counts_json
negative_counts_json
configuration_hash
logical_table_hashes_json
physical_table_hashes_json
processing_environment_json
runtime_seconds
storage_footprint_bytes
```

Logical identity includes governed configuration, schemas, source content, passage inputs,
and canonical table content. Runtime, local paths, and storage telemetry do not alter
logical identity. Rebuilding from the same acquisition receipt, Tier 1 header, passage
inputs, and configuration must reproduce the same logical hashes.
