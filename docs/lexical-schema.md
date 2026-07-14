# Lexical retrieval schema

Status: **Milestone 7 schema version 1 — implementation in progress**

Milestone 7 uses strict Pydantic contracts, ordered Polars schemas, deterministic
sorting, and typed Parquet under the Git-ignored directory
`data/processed/lexical/schema-v1/`. Tracked files contain only configuration,
schemas, aggregate reports, safe references, hashes, and a sanitized unreviewed
handoff queue; they do not contain bulk biblical text.

## Governed versions and identities

- Lexical schema: `1`
- Representation schema: `1`
- Candidate-pair schema: `1`
- Ranking schema: `1`
- Experiment version: `m7-lexical-baseline-v1`
- Exhaustive scope: `edition_complete` verse passages; Hebrew/Aramaic Qere and
  Greek source readings
- Original-language strata: HB–HB and GNT–GNT
- Cross-testament bridge: HB–GNT using separately marked English-derived gloss
  features with mandatory ablation

Feature IDs hash schema version, family, language namespace, NFC-normalized
value, and order. Representation IDs hash governed analytical and frequency
choices. Candidate IDs hash profile, granularity, and the canonically ordered
unordered pair of passage IDs; scores and labels never enter pair identity.
Ranking IDs are directional and bind experiment run, query, target, detector,
and representation. Canonical payloads use UTF-8 JSON with sorted keys and
compact separators. Collisions are fatal.

## Data contract

The production artifact set contains fourteen logical tables.

### `feature_vocabulary`

One stable language-prefixed feature per row: `feature_id`,
`lexical_schema_version`, `feature_family`, `language_namespace`,
`feature_value`, `feature_order`, `corpus_frequency`, `document_frequency`,
`inverse_document_frequency`, `book_frequency`, `genre_frequency`, `is_rare`,
`is_high_frequency`, `is_formulaic`, `contains_english_derived_content`,
`normalization_method`, and `notes`. Sparse column order is not identity.

### `passage_feature_statistics`

One passage/representation summary per row: `passage_id`, `analysis_profile`,
`analysis_reading`, `granularity`, `representation_id`, `corpus`, `book`,
`broad_genre`, `eligible_token_count`, distinct lemma/root/surface counts,
lemma/root/English sequence lengths, formulaic and rare counts,
`feature_vector_digest`, and `source_passage_digest`.

### `lexical_index_metadata`

Records representation and index identity, schema and experiment versions,
configuration/preregistration digests, input run IDs and hashes, vocabulary and
matrix dimensions, nonzero count, dtype, sparse format, logical matrix hash,
physical hashes, deterministic thread controls, and bounded resource telemetry.
Runtime and local paths are excluded from logical identity.

### `directional_rankings`

One query-to-target detector result: `ranking_id`, run and representation IDs,
query and target passage IDs, corpus pair, direction, detector, raw and
quantized scores, detector rank, tie-break passage ID, and eligibility flags.
Direction changes ranking identity but not candidate-pair identity.

`query_split` and `target_split` are canonical JSON provenance summaries. An
unassigned passage stores only `status=no_eligible_benchmark_assignment`. A
mapped passage stores the benchmark versions, eligible partitions, mapping
statuses, leakage-membership completeness, a SHA-256 commitment to the
canonically ordered grouped assignment facts, and the count plus SHA-256 of
the sorted unique leakage-group IDs. The potentially long ID list is not
repeated in every ranking row. Strict validation reconstructs the canonical
payload from the anchored benchmark database and requires exact equality;
therefore reconstruction depends on retaining that anchored input database.

### `candidate_pairs`

One canonical unordered pair: `candidate_pair_id`, schema and run versions,
ordered passage IDs and references, analysis profile, granularity, corpus pair,
books, broad genres, token lengths, overlap/adjacency/nearby/same-book flags,
duplicate/disputed/reference-gap/Ketiv flags, English-evidence and ablation
flags, review eligibility, and its reason. Scores are deliberately absent from
identity.

### `candidate_detector_scores`

Per pair/detector/representation/direction scores and ranks, including raw and
quantized score, RRF contribution, candidate-union source, ablation ID, and
score-definition digest. Directional rankings retain 100 targets per query;
the detailed candidate/evidence pool is explicitly bounded to 25 per query.

### `candidate_evidence`

Reconciles shared lemma/root/surface/rare/phrase/skip-gram counts, LCS and
alignment, detector and RRF scores, analytical expected overlap,
hypergeometric p-value, BH q-value and hypothesis family, empirical null rate
and FDR, independent co-signal count, rare-rule status, explicit penalties,
overlap exclusion, and `evidence_digest`.

### `shared_evidence`

One inspectable evidence item per pair: family, feature ID and value, positions
in both passages, corpus/document frequencies, association score, independence
expectation, primary-rare marker, independent-co-signal marker,
English-derived marker, and notes. Position lists resolve to authoritative
passage membership.

### `null_replicate_summaries`

One experiment/family/replicate/threshold row with deterministic seed,
conditioning stratum, preservation checks, observed and simulated count,
sequence-change digest, and logical replicate digest. Both required families
retain at least 100 rows per governed experiment. Calibration scores the frozen
deterministic 20,000-pair candidate-union sample, whose identity is retained;
it does not represent or support claims about the global all-pairs universe.

### `threshold_calibration`

One registered threshold per experiment and stratum: observed count, null
replicate count, mean null count, 2.5/97.5 percentiles, enrichment, finite-
simulation empirical tail p-value, estimated empirical FDR, selection status,
and frozen-selection reason.

### `evaluation_results`

Tier 3 weak-supervision recovery only: experiment/preregistration identity,
detector or composite, corpus pair, representation, mapping status, split,
book/genre/length/vote/disputed/gap strata, metric, value, bootstrap interval,
eligible and excluded counts, exclusion reasons, baseline comparator, and
scientific-gate result.

### `candidate_review_queue`

Sanitized unreviewed Milestone 8 handoff fields: queue rank, pair ID, references,
corpus pair, RRF score, detector-support count, rare-rule status, empirical FDR,
known-link status, English marker and ablation result, disputed/gap/Ketiv flags,
review eligibility and reason, evidence digest, and experiment identity. It has
no decision, reviewer, interpretation, or novelty field.

### `lexical_issues`

Deterministic validation and build findings: issue ID, run ID, severity, code,
message, artifact, related passage/pair/feature/ranking IDs, details JSON, and
resolution status. Strict mode fails on errors and warnings.

### `lexical_metadata`

One run record containing all schema versions; configuration and
preregistration digests; upstream corpus, passage, and benchmark anchors;
artifact counts and logical/physical hashes; detector, evaluation, null, and
queue summaries; numerical environment; thread controls; runtime; memory; and
storage footprint. Telemetry is provenance, not logical identity.

## Ordering, storage, and validation

Every table has an explicit column order and deterministic primary sort. Writes
use Zstandard Parquet, stage in a sibling temporary directory, and replace the
complete schema directory atomically only with `--force`. Sparse matrices use a
stable passage order, stable vocabulary identity order, float64 values, and a
logical coordinate/value digest after 12-decimal score quantization. DuckDB
loads all artifacts transactionally and exposes views without copying upstream
corpus, passage, or benchmark tables.

Strict validation reproduces upstream anchors, feature and pair identities,
namespaces, frequencies, sparse hashes, detector fixture scores, evidence
positions and digests, English ablations, benchmark strata and leakage,
both null families, threshold statistics, rare-rule conjunctions, multiple-
testing families, queue eligibility, and two-build logical determinism.
