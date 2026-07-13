# Benchmark design

Status: **Milestone 6 local builds validated; pull-request and CI acceptance pending**

The [master plan](master-plan.md) remains the governing specification. The active data
contracts are documented in [benchmark-schema.md](benchmark-schema.md), and the executable
policy is `config/benchmark.yaml`. Milestone 6 creates reference, mapping, split,
contrastive-example, and metric infrastructure only. It does not implement lexical
scoring, retrieval, embeddings, candidate generation, or human review.

The validated local build identity is run `benchmark-v1-dff1d3ef650c8ccd4930`,
benchmark version `known-links-v1-dff1d3ef650c`. Two complete builds reproduced every
logical table hash, row count, and content-table physical hash. Each strict validation
returned zero errors, zero warnings, and 18 informational source-reference findings.

## Active benchmark tiers

### Tier 1 — project-curated explicit quotations

The canonical Tier 1 file remains
[`data/benchmarks/tier1_quotations.csv`](../data/benchmarks/tier1_quotations.csv).
It contains exactly the governed header and zero data rows. This placeholder validates the
future human-curation contract but supplies no current benchmark evidence.

Tier 1 population requires row-level provenance, original-language comparison, independent
human review, source-tradition analysis, rights review, and leakage grouping under the
[curation instructions](tier1-quotation-curation.md). Automated population and automated
`verified` status are prohibited. OpenBible rows cannot be promoted to Tier 1.

### Tier 2 — specialist curated resources

Tier 2 remains a future category for an approved scholarly or specialist relationship
dataset whose exact edition, license, definitions, provenance, and transformation history
have passed source activation. No Tier 2 source is activated by Milestone 6.

### Tier 3 — OpenBible weak supervision

The approved OpenBible.info source is the exact content-addressed snapshot
`snapshot-2026-07-12-sha256-18e63e370308`. Its archive SHA-256 is
`18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492`.
The archive contains the reference-and-vote file `cross_references.txt`, SHA-256
`eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37`.

OpenBible is eligible for Tier 3 weak supervision and broad knownness filtering. It is not
scholarly ground truth, primary evaluation truth, a sole positive benchmark, or a source
of relationship-class certainty. Its signed votes remain source ranking values, not
calibrated confidence or probabilities of literary dependence. The observed direction is
preserved, and the graph is not silently symmetrized.

## Source and relationship identity

Every raw source occurrence is retained, including duplicate or invalid rows. Source-record
identity uses the exact archive and raw-record hashes plus a duplicate-occurrence ordinal;
line number remains provenance only.

Relationship identity is independent of local paths, row numbers, votes, passage IDs,
mappings, split assignments, and timestamps. It uses the source/version/reference scheme,
normalized source endpoints, and observed direction. Directed and canonical unordered
pair identities are stored separately. Duplicate source occurrences may aggregate into one
normalized relationship only when every occurrence remains linked through the provenance
artifact.

## Reference parsing and passage mapping

OpenBible references remain in the `openbible-english-protestant-v1` source scheme. A
same-number label is not proof that an English reference and a MACULA edition are verified
versification equivalents.

Milestone 6 targets verse passages only:

- Default profile: `edition_complete`
- Compatibility profile: `critical_core`
- Hebrew reading: `qere`
- Greek reading: `source`

Same-label extant-reference mappings without an approved crosswalk are
`mapped_provisional`. Ranges expand only to exact ordered extant verse passages. Missing
verses are never fabricated. Partial ranges, reference gaps, disputed-passage membership,
profile exclusions, unresolved references, and versification ambiguity remain explicit.
Mapping identity is separate from relationship identity, so correcting a mapping does not
rewrite the source relationship.

## Leakage control

No split is a random division of raw rows. Relationships receive explicit groups for exact
directed and unordered pairs, duplicate source occurrences, shared endpoints, endpoint
range overlaps, shared or overlapping target passages, canonical unordered book pairs,
relationship families when known, and shared source provenance where relevant.

One unrestricted graph-connected component is not used as the only group: hub verses could
otherwise collapse most of the graph. Each split strategy names the leakage groups it
enforces, and every excluded relationship records a reason.

## Deterministic split strategies

The active configuration defines seeded, group-aware infrastructure splits for:

- Held-out books
- Held-out book pairs
- Held-out source passages
- Held-out genres using the documented broad genre registry

The held-out-relationship-family strategy remains disabled until genuine family labels are
available; labels are never invented. Partitions are `train`, `development`, `test`, and
`excluded`. The configured Tier 3 partitions test infrastructure and weak-supervision use;
they are not definitive scholarly evaluation sets.

Split assignments and presumed negatives are atomically materialized by
`echoes ingest-benchmark` as part of the complete governed artifact set. The
`echoes generate-benchmark-splits` and `echoes generate-presumed-negatives`
commands verify those persisted stages and fail if the expected materialization
is absent or inconsistent; they are not separate generation paths.

## Presumed negatives

Milestone 6 generates only presumed negatives or contrastive examples. It never asserts
that an unlinked pair has no relationship. Active strategies are length-matched random
unlinked pairs, same-book unlinked pairs, same-book-pair unlinked pairs, same-broad-genre
unlinked pairs, and nearby-context unlinked pairs.

Every generated pair must:

- Contain distinct passages.
- Be absent from the positive graph in both directions.
- Pass passage-overlap checks.
- Remain in the required split partition.
- Pass configured leakage checks.
- Record strategy, seed, configuration hash, and sampling metadata.

These strategies use passage metadata only. Lexical or semantic features, TF-IDF, BM25,
embeddings, similarity scores, and candidate-ranking logic belong to later milestones.

## Metric contracts

Milestone 6 defines and fixture-tests metrics without running a retrieval model. The active
contracts cover Recall@5, Recall@10, Recall@20, mean reciprocal rank, nDCG@20,
Precision@10, configurable Precision@k, and coverage.

Every metric result must identify benchmark version, included tiers, mapping eligibility,
split strategy, label quality, and eligible/excluded query counts. A Tier 3 result must be
labeled weak-supervision recovery and cannot be reported as Tier 1 quotation recovery.
Zero-query and missing-relevance cases are explicit rather than silently removed.

## Validated build evidence

Each complete build produced these row counts:

| Artifact family | Rows |
|---|---:|
| Source records | 344,799 |
| Relationships and relationship/source links | 344,799 each |
| Endpoints | 689,598 |
| Endpoint mappings | 1,379,196 |
| Leakage-group memberships | 4,561,525 |
| Split assignments | 1,723,995 |
| Presumed negatives | 29,275 |
| Informational issues | 18 |
| Metadata | 1 |

Mapping status counts are 639 `excluded_by_profile`, 781 `mapped_partial`,
1,371,984 `mapped_provisional`, 5,756 `unresolved_missing_target`, and 36
`unresolved_reference`. The 344,799 relationships comprise 187,117 OT–OT,
84,369 NT–NT, and 73,313 cross-testament relationships.

The two wall-clock build times were 551.3 and 533.7 seconds; persisted pipeline runtimes
were 501.93041979987174 and 479.37766140000895 seconds. Both metadata rows report a
672,790,515-byte persisted footprint. There were zero logical-hash, row-count, or
content-table physical-hash differences. The metadata physical hash alone differed, as
expected, because metadata retains measured runtime; its logical hash excludes that
registered telemetry field and remained identical.

## Copyrighted quotation appendices

Copyrighted UBS, Nestle-Aland, or comparable quotation/allusion appendices must not be
ingested without explicit permission covering machine processing and intended publication.
Lawful manual consultation may be cited, but it must not become transcription, systematic
extraction, reconstructed ordering, or copied benchmark data.

## Later lexical calibration

Milestone 7, not Milestone 6, must evaluate transparent lexical retrieval and both required
null families. A shared lemma or root at or below the configured rare-evidence threshold
cannot independently make a candidate review-eligible; it requires an independent
co-signal. Hypergeometric calculations remain simple independence baselines, not
probabilities of literary dependence, and empirical book- or genre-conditioned nulls take
precedence for calibration.
