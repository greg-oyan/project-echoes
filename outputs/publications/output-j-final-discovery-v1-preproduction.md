# Output J — `final-discovery-v1` Bounded Tier A/Tier B Review and False-Positive Taxonomy

> **Preproduction publication template — not results.** This standalone draft
> freezes the required Output J sections before production. Every field marked
> `[PRODUCTION PLACEHOLDER]` or `[REVIEW PLACEHOLDER]` must be populated only
> from the authenticated production artifacts and completed human-review
> ledger. As of 2026-08-08, the campaign has not run and no paid compute has
> been launched.

## Artifact status

- Experiment: `final-discovery-v1`
- Status: preregistered and locally implemented; production not launched
- Semantic configuration SHA-256:
  `7b5c511fed3be041576f9c2ea784d71e028a0f539d7642d84ddcf61eccd22627`
- Exact YAML SHA-256:
  `a38c2f6d1c3d84264c7b81a8a62c3a84cae8b993894f6634e339958cdc1f76b0`
- Production run ID, Git identity, code-tree hash, and campaign-seal hash:
  `[PRODUCTION PLACEHOLDER]`
- Tier A count: `[PRODUCTION PLACEHOLDER]`
- Tier B count: `[PRODUCTION PLACEHOLDER — expected top 100 when at least 100
  eligible exploratory rows exist]`
- Completed human-review rows: `[REVIEW PLACEHOLDER]`

Statistical eligibility, exploratory rank, human acceptance, knownness, and
novelty are separate states. This document must not call a Tier B row accepted,
novel, or a discovery merely because it ranks highly.

## Candidate-selection procedure

The candidate universe is the preregistered union of sparse, embedding,
structural, and bounded M7 retrieval. Positive controls are evaluated outside
the discovery tiers. The ensemble retains the maximum registered normalized
score within each independence group and calculates the frozen weighted mean.
Multiple-testing correction covers the complete retained preregistered
hypothesis universe, not every mathematically possible passage pair.

Tier A (`statistically_eligible`) contains only candidates that satisfy every
frozen score, q-value, empirical-FDR, detector-independence,
original-language, bidirectional-knownness, data-quality, traceability, and
applicable remove-all-English gate. Tier B
(`exploratory_not_statistically_accepted`) is the disjoint highest-scoring 100
unknown non-Tier-A rows after basic exclusions, ordered by score and stable
candidate ID. An empty Tier A is a valid result. All Tier B rows must be
reviewed without changing the frozen experiment.

Authenticated selection query, Stage 8/9 artifact hashes, and retained-universe
count: `[PRODUCTION PLACEHOLDER]`

## Frozen thresholds and expected noise

| Rule | Frozen value |
| --- | ---: |
| Minimum Tier A ensemble score | 0.65 |
| Maximum Benjamini–Hochberg q-value | 0.05 |
| Maximum estimated empirical FDR | 0.20 |
| Minimum independent qualifying families | 2 |
| Qualifying normalized group score | 0.90 |
| Production null iterations | 1,000 |
| Minimum effective null draws | 20,000 |
| Tier B size | 100 |

Both required M7 null families remain binding where applicable. Later-family
scores use the registered conditioned permutation or bootstrap control, and
the final ensemble uses stratified candidate-pair permutation. English-derived
evidence is ablated while retaining the registered denominator.

For every reported review threshold, insert the observed candidate count,
mean null count, 95% empirical interval, enrichment, empirical tail
probability where applicable, and estimated empirical FDR:

| Threshold/scope | Observed | Mean null | 95% interval | Enrichment | Tail probability | Empirical FDR |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| `[PRODUCTION PLACEHOLDER]` | — | — | — | — | — | — |

## Tier A — statistically eligible, not automatically accepted

`[PRODUCTION PLACEHOLDER — populate only the first 100 score-ranked Tier A rows
from the authenticated complete ledger; do not replace an empty result with
exploratory rows]`

| Candidate ID | Passages | Score | q-value | Empirical FDR | Independent families | Knownness | Ablation | Review disposition | Dossier |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `[PRODUCTION/REVIEW PLACEHOLDER]` | — | — | — | — | — | — | — | — | — |

## Tier B — exploratory top 100, not statistically accepted

`[PRODUCTION PLACEHOLDER — populate all disjoint Tier B rows in rank order and
complete a human-review disposition for every row]`

| Rank | Candidate ID | Passages | Score | Failed Tier A gates | Knownness | Review disposition | Rejection category | Dossier |
| ---: | --- | --- | ---: | --- | --- | --- | --- | --- |
| `[PRODUCTION/REVIEW PLACEHOLDER]` | — | — | — | — | — | — | — | — |

## Complete retained-candidate ledger

The authenticated CSV and Parquet ledger must preserve every retained
candidate, including known, quality-excluded, statistically ineligible, and
rejected rows. Markdown dossiers and Output J rows are intentionally limited
to the first 100 score-ranked Tier A rows plus all Tier B rows so production
does not generate redundant dossiers for the entire retained universe.

- Ledger path, row count, and SHA-256: `[PRODUCTION PLACEHOLDER]`
- Bounded dossier-selection manifest (first 100 Tier A plus all Tier B), count,
  and SHA-256:
  `[PRODUCTION PLACEHOLDER]`
- Review-history identity and completeness receipt: `[REVIEW PLACEHOLDER]`

## Accepted and plausible candidates

`[REVIEW PLACEHOLDER — report only completed human classifications, strongest
counterarguments, falsifiers, and calibrated conclusion language. Do not infer
authorial intent, literary dependence, or novelty automatically.]`

## Rejected candidates and false-positive categories

Report counts and representative, license-safe evidence for every used class.
The frozen review taxonomy includes `formulaic_language`, `common_topic_only`,
`named_entity_only`, `local_or_overlapping_context`, `translation_artifact`,
`annotation_artifact`, `data_quality`, `insufficient_independent_evidence`,
`already_known`, and `other`.

| Category | Count | Representative candidate IDs | Diagnostic lesson |
| --- | ---: | --- | --- |
| `[REVIEW PLACEHOLDER]` | — | — | — |

## Data artifacts

`[REVIEW PLACEHOLDER — identify tokenization, annotation, reference-mapping,
alignment, disputed-text, Ketiv, truncation, or implementation artifacts;
distinguish source limitations from software defects and preserve rejected
rows.]`

## Formulaic-language effects

`[REVIEW PLACEHOLDER — report high-document-frequency lemma/root n-gram
controls, affected candidates, sensitivity outcomes, and whether downweighting
was sufficient.]`

## Genre effects

`[REVIEW PLACEHOLDER — report genre-conditioned null behavior, generic
templates, class imbalance, and candidates whose similarity is better
explained by genre.]`

## Common-vocabulary effects

`[REVIEW PLACEHOLDER — report common-lemma/gloss dominance, rare-evidence
co-signal failures, alternative nearer passages, and English-mediated
artifacts.]`

## Lessons for scoring revisions

`[REVIEW PLACEHOLDER — describe supported lessons without retuning this frozen
run. Any threshold, detector, weight, exclusion, or candidate-universe change
must be registered as a new experiment.]`

## Methodological limitations

- The primary calibrated scope is verse passages. Other passage granularities
  are not production results for this experiment.
- Calibration, BH q-values, and empirical FDR are conditional on the complete
  retained top-k candidate union, not all possible passage pairs.
- `multilingual-e5-small` has unestablished validity for Biblical Hebrew,
  Biblical Aramaic, and Ancient Greek. Possible exposure to biblical text,
  translations, commentary, and benchmark relationships during broad web
  pretraining is unquantified.
- Removing explicit English-derived features cannot remove latent training
  exposure from model weights. English glosses remain supplemental and cannot
  supply independent original-language support.
- The 24-row UBS positive controls span eight leakage groups, but their six-row
  test split is one correlated group and has no independent original-language
  adjudication. Recovery is descriptive rather than a generalizable gold-set
  result.
- OpenBible absence means only absence from the pinned mapping checked in both
  directions; it is not proof of scholarly novelty.
- LXX activation is deferred, so no campaign result can claim direct
  Hebrew–LXX–GNT triangulation.
- `[REVIEW PLACEHOLDER — add run-specific missingness, failure, exposure,
  reviewer, and literature-search limitations without deleting the frozen
  items above.]`

## Publication and completeness declaration

`[REVIEW PLACEHOLDER — name the authenticated final package, validation
receipt, complete ledger, dossier manifest, review completion record, searched
knownness sources, and any external review. State negative or empty outcomes
directly.]`

This Output J supplements, and never replaces, the complete retained-candidate
ledger, evidence traces, tier dossiers, review history, run manifests, and
campaign validation receipts. Until all placeholders are resolved from a
governed production run and completed review, it remains a preproduction
template and cannot satisfy the Milestone 8 top-100 review gate.
