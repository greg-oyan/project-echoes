# Benchmark design

Status: **governance amended; implementation and population deferred to Milestone 6**

The [master plan](master-plan.md) is the governing specification. This document fixes source roles, curation boundaries, and statistical requirements without implementing a benchmark, candidate engine, or review system.

## Benchmark tiers

### Tier 1 — project-curated explicit quotations

Tier 1 is a future human-curated benchmark of approximately 300 explicit New Testament quotations of Old Testament passages. Its tracked placeholder is [`data/benchmarks/tier1_quotations.csv`](../data/benchmarks/tier1_quotations.csv), which currently contains only the governed header. No benchmark examples may be invented or added without following the [Tier 1 quotation curation instructions](tier1-quotation-curation.md).

Tier 1 is intended for held-out evaluation only after row-level provenance, independent human verification, source-tradition review, and leakage controls are complete. It is not an automatically imported appendix.

### Tier 2 — specialist curated resources

Tier 2 may contain approved scholarly or specialist relationship datasets whose exact edition, license, relationship definitions, and transformation history are recorded. A Tier 2 label does not make every relation equally strong or authorize redistribution beyond the source license.

### Tier 3 — broad weak supervision and knownness filtering

The OpenBible.info cross-reference graph is Tier 3. Its approximately 340,000 heterogeneous verse links are useful for weak supervision, broad knownness filtering, and candidate exclusion checks. The graph draws primarily from the public-domain Treasury of Scripture Knowledge and related sources, but mixes themes, words, events, and people. It is not scholarly ground truth, must not be the sole positive benchmark, and must not determine Tier 1 labels.

## Copyrighted quotation appendices

Copyrighted UBS, Nestle-Aland, or comparable quotation and allusion appendices must not be ingested into this repository without explicit permission that covers the intended machine processing and redistribution. Researchers may manually consult such an appendix where lawful, cite that consultation, and record its influence on a review decision. Consultation must not become transcription, systematic extraction, reconstructed ordering, or copied benchmark data.

## Planned benchmark records

Every relationship record must retain stable relationship identity, passage references in their source editions, relationship class, source tradition where applicable, row-level curation provenance, source-license status, curator, independent review status, and notes. Later normalized or crosswalked references are separate mappings and do not replace edition-specific references.

Training, tuning, evaluation, and knownness-filter data must be separately versioned. Exact duplicates and near-duplicates across tiers are grouped before splitting. Passage overlap, source-family overlap, quotation families, repeated passages, and transformations of the same relationship are leakage groups, not independent examples.

## Planned null-model requirements

Every Milestone 7 lexical scoring experiment must run repeated simulations from both required null families:

1. **Within-book reassignment null.** Preserve book-level token or lemma frequencies, passage counts, and passage lengths while randomly reassigning tokens or lemmas among passages in the same book. Shuffling only passage order or labels is invalid because it leaves pairwise similarities unchanged.
2. **Frequency-preserving synthetic-passage null.** Preserve passage lengths and book- or genre-conditioned lemma frequencies. Registered stricter variants may additionally preserve part-of-speech distributions, morphological distributions, or local n-gram characteristics.

At every review threshold, a scoring report must state the observed candidate count, mean null candidate count, 95% empirical null interval, observed-to-null enrichment, empirical tail probability where appropriate, and estimated empirical false-discovery rate. Milestone 8 review output must show this expected-noise baseline beside observed candidate counts.

## Conjunctive rare-evidence rule

A shared lemma or root whose total corpus frequency is at or below the configured threshold (initial planned value: three) cannot by itself make a candidate review-eligible. It requires at least one independently defined co-signal: ordered-sequence similarity, a shared rare phrase, syntactic match, a second rare lexical item, or another detector-family signal.

The planned candidate-evidence schema includes:

- `expected_cooccurrence_independence`
- `hypergeometric_p_value`
- `null_model_empirical_rate`
- `multiple_testing_adjustment`

The hypergeometric value is a simple baseline, not a calibrated probability of literary dependence: biblical vocabulary is not independently distributed. Book- or genre-conditioned permutation results take precedence for empirical calibration. This rule must be implemented and tested before Milestone 8 human review begins.

## Milestone 8 review artifact

Milestone 8 must draft the standalone **Output J: Milestone 8 Top-100 Review and False-Positive Taxonomy**. It records candidate selection, thresholds, the null-model expected-noise baseline, accepted and rejected candidates, false-positive categories, data artifacts, formulaic-language effects, genre effects, common-vocabulary effects, lessons for scoring revisions, and methodological limitations.

No benchmark rows, analysis results, or future engine implementation are introduced by this governance amendment.
