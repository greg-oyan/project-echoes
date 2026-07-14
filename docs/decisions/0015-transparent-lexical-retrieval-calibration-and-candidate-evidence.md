# 0015 — Transparent lexical retrieval, calibration, and candidate evidence

- Status: Accepted
- Date: 2026-07-13
- executing_agent: Codex
- Owner authorization: The project owner authorized this decision and its
  Milestone 7 implementation through the current goal before execution.

## Context

Milestone 7 must retrieve lexical candidates reproducibly without turning a
similarity score, OpenBible link, English gloss, or rare word into a claim of
quotation, dependence, intention, or novelty. The validated corpus, passage,
and Tier 3 benchmark layers provide stable inputs, but their language systems,
mapping quality, passage overlap, source context, and formulaic vocabulary
create dependencies that simple all-pairs overlap and analytical p-values do
not model. Held-out results must therefore be frozen before inspection,
calibrated against repeated conditioned nulls, and retained with decomposable
evidence.

## Decision

### Verse-level v1 scope and representations

The exhaustive v1 scope is the `edition_complete` verse layer. Hebrew and
Aramaic use Qere; Greek uses the source reading. Hebrew–Hebrew and GNT–GNT are
the primary original-language strata. Clause, sentence, two-verse, and
five-verse interfaces receive synthetic and bounded smoke tests, not exhaustive
calibration. Direct Hebrew–Greek lemma comparison is prohibited until a
governed Septuagint bridge exists.

Every source-language feature is language-prefixed (`hb:`, `gk:`, or `en:`).
Hebrew and Greek lemma, root, surface, POS, and morphology namespaces remain
distinct. Cross-testament retrieval may use the MACULA English-gloss bridge,
but every such feature and result is explicitly English-derived, reported
separately, and evaluated with a remove-all-English ablation. English-only
evidence cannot acquire a future strong-candidate label.

Features come from authoritative passage membership and token annotations, not
by reparsing reconstructed text. Zero-width records remain members but do not
emit lexical features. Primary frequency statistics count each source token
stream once within a language and representation; book and broad-genre
frequencies are additional descriptive conditioning fields.

### Identity and preregistration

Feature identity schema version 1 hashes feature schema, family, language
namespace, canonically normalized value, and feature order. It never uses a
sparse-matrix column. Representation identity hashes corpus scope, profile,
reading, granularity, sorted feature families, token-eligibility policy,
frequency scope, and normalization configuration. English-derived and
original-language representations cannot share a payload.

Candidate-pair identity schema version 1 hashes the profile, granularity, and
lexically ordered passage IDs. Scores, detector ranks, thresholds, benchmark
labels, OpenBible votes, review eligibility, runtime, paths, and seeds are not
pair identity. Direction belongs to ranking identity, which also includes the
experiment run, query, target, detector, and representation. All identity
registries fail closed on a digest/payload collision.

`config/experiments/m7-lexical-baseline.yaml` freezes upstream identities,
scope, representations, detector parameters, retrieval depth, numeric
quantization, benchmark strata, metrics, seeds, null families, thresholds,
rare-rule definitions, penalties, ablations, and exclusions. Its declared
SHA-256 authenticates canonical validated JSON excluding the self-referential
digest field. The held-out evaluation must require that exact digest. A method
change after results requires a new experiment version and preservation of the
old results.

#### Pre-heldout implementation-closure amendment

On 2026-07-13, before any full or held-out Milestone 7 artifact was generated,
an implementation audit found that the initial scaffold did not yet encode all
of this decision's reproducibility obligations. The accepted contract was
therefore closed before evaluation, without inspecting candidate identities or
test metrics. The frozen preregistration now explicitly includes both required
sensitivity scopes: full `critical_core` Greek retrieval and Tier 3 evaluation,
and Qere-versus-Ketiv retrieval restricted to OSHB-affected Hebrew verse
references against the full Hebrew target corpus. These sensitivities do not
repeat the primary null simulations.

The same pre-heldout closure requires typed, content-hashed `ablation_results`
and `sensitivity_results` artifacts; recomputation for all eight registered
ablations; raw and penalty-adjusted RRF scores; selected-threshold provenance;
actual passage split/leakage metadata; complete profile and evaluation-stratum
provenance; real presumed-negative discrimination; and evidence digests that
cover detector components, penalties, calibration, analytical-overlap inputs,
multiple-testing scope, and ablations. Process resident memory is checked
against the configured six-GiB ceiling at stage, batch, sensitivity, and null
replicate boundaries, with numerical thread controls recorded. The canonical
configuration and preregistration digests were refreshed only after these
contracts were encoded and before held-out execution. Because no prior result
existed, this amendment closes the original experiment rather than replacing or
tuning an observed experiment.

Directional ranking split fields use compact canonical JSON rather than
repeating every leakage-group identifier tens of millions of times. Each
mapped-passage payload retains the unique group count, SHA-256 of the sorted
unique group IDs, and a separate SHA-256 commitment to the canonically ordered
grouped assignment facts, together with versions, partitions, mapping status,
and completeness. Strict validation regenerates the payload from the anchored
benchmark database. This design is reproducible and bounded, but intentionally
requires that anchored database for reconstruction; the compact hashes are not
a reversible substitute for the source assignment tables.

Directional English ablations are stored once, inline on each content-hashed
bridge ranking, rather than duplicated into a second physical row containing
the same ranking ID, query/target IDs, scores, ranks, gloss counts, and flags.
The typed `ablation_results` artifact retains all eight candidate-pair
ablations. Strict validation reproduces every inline directional removal fact,
requires candidate ablation-family completeness, and rejects duplicated
`subject_type=directional_ranking` rows. This physical normalization changes no
score, rank, scope, threshold, identity, or ablation conclusion and keeps the
generated Parquet set above the governed free-disk floor.

### Sparse retrieval and transparent scores

Indexes are deterministic and sparse. Jaccard, IDF-weighted Jaccard, TF-IDF
cosine, BM25, rare lemma/root overlap, lemma/root bigrams and trigrams, bounded
skip-grams, PMI capped at the preregistered natural-log value of 10.0 after the
minimum count of two and log-likelihood association, longest common subsequence,
weighted sequence alignment, and POS/morphology support are individually
inspectable detector families. Dynamic-programming sequence methods run only
on the bounded sparse candidate union. Dense all-pairs comparison is
prohibited.

The composite is reciprocal-rank fusion with a fixed `k`; it is not a learned
ranker. Detector ranks and individual RRF contributions are preserved.
Original-language and English-derived composites remain separate. Scores use
float64 computation, fixed decimal quantization, and passage-ID tie breaking.
Formulaic, local-context, short-passage, overlap, adjacency, same-book,
disputed-text, reference-gap, and Ketiv-sensitivity effects remain explicit
penalties or flags; raw scores are retained.

### Pair eligibility and rare evidence

Self-pairs and exact or direct window overlap are excluded from discovery.
Adjacent, nearby, same-book, formulaic, duplicate, disputed, gap-affected, and
Ketiv-sensitive pairs remain inspectable with their reasons. They are not
silently discarded or upgraded.

The configured rare threshold initially means corpus frequency at most three.
A single rare lemma or root cannot make a candidate review-eligible. It needs
an independent co-signal: a second distinct rare item, additional material in
a phrase, ordered support with at least two other eligible features,
independent POS/morphology sequence support, or a genuinely separate detector
family. TF-IDF and BM25 caused by the same item, lemma/surface or lemma/root
restatements of one token, forward/reverse ranks, stop-feature artifacts, and a
mere English translation of the same item do not count independently.

### Empirical null calibration and statistics

Every governed primary scoring experiment runs both registered null families
for at least 100 deterministic replicates. Within-book feature-token
reassignment preserves book totals, passage counts, and exact passage lengths
while breaking sequences. The frequency-preserving synthetic-passage family
preserves corpus, passage counts and lengths, and book distributions where
supported, falling back to broad genre only when required. Language
vocabularies never mix. Label shuffling and passage-order shuffling are not
valid null families.

For local resource feasibility, null scoring uses a preregistered deterministic
20,000-pair sample drawn from the candidate-union scope. It is not a random
sample of all possible passage pairs and does not support a global all-pairs
testing or FDR claim. The synthetic family uses book conditioning when at least 100
eligible feature tokens are available and otherwise falls back to the frozen
broad-genre stratum. The exact sample identity and conditioning strata are
retained with each replicate. Directional detector rankings retain the top 100,
while expensive sequence alignment and the detailed candidate/evidence pool are
bounded to the preregistered top 25 results per query.

Every enabled detector uses the preregistered score grid
`[0.02, 0.04, 0.06, 0.08, 0.10]`; the composite uses the separately named RRF
grid with the same frozen values. Every registered threshold records the
observed count, mean null count, 2.5th
and 97.5th percentiles, enrichment, finite-simulation-corrected empirical tail
probability, and mean-null/observed empirical-FDR estimate. All replicates are
retained. Threshold selection follows the frozen grid and FDR procedure before
queue construction; identities cannot be inspected to select a threshold, and
thresholds cannot be weakened to manufacture a quota.

Hypergeometric overlap is an analytical baseline only. Its feature universe,
passage counts, observed overlap, expectation, raw p-value, explicit hypothesis
family, retrieval-selection scope, and Benjamini–Hochberg q-value are retained.
Empirical conditioned nulls take precedence because biblical vocabulary is not
independent or equally distributed.

### Evaluation, evidence, and handoff

OpenBible remains Tier 3 weak supervision. Recovery is reported separately by
corpus pair, profile, mapping status, split, book, broad genre, passage length,
vote stratum, disputed text, and reference gaps. Votes are descriptive ranking
values, not probabilities. Tier 3 is compared with random, length-matched,
unweighted-overlap, and presumed-negative baselines using Recall@5/10/20, MRR,
nDCG@20, P@10, coverage, eligible/excluded counts, and deterministic bootstrap
intervals. Leakage groups and governed splits remain enforced.

Every persisted candidate retains passage IDs and references, feature IDs and
values, positions, corpus and document frequencies, alternative passages,
detector scores and ranks, RRF contributions, penalties, analytical and
empirical statistics, rare-rule co-signals, English ablation, known-link
status, evidence digest, and run lineage. No LLM supplies detector evidence.

The Milestone 8 handoff is a tracked, sanitized, unreviewed queue. Its knownness
labels are only `represented_in_openbible_snapshot`,
`not_represented_in_openbible_snapshot`, and `mapping_unresolved`. It contains
no review decisions and makes no novelty claim. Full generated artifacts and
any biblical text remain in Git-ignored local storage.

## Consequences

- Held-out evaluation cannot start without an authentic preregistration digest.
- Stable IDs survive row and sparse-column reordering while changing for
  substantive profile, granularity, representation, or direction changes.
- A high lexical score remains a review lead with reproducible evidence, not a
  historical or literary conclusion.
- Cross-testament English-gloss results are useful but cannot masquerade as
  original-language correspondence.
- Failed scientific gates and unproductive thresholds remain reportable
  results; they are not tuned away.
- Milestone 8 review, semantic retrieval, embeddings, a learned ranker, and the
  Septuagint bridge remain out of scope.

## Alternatives considered

- Dense all-pairs scoring: rejected because it is unnecessary, expensive, and
  encourages unscoped post-selection.
- Raw Hebrew–Greek identifier comparison: rejected because serialization does
  not establish cross-language lexical equivalence.
- Treating English overlap as original-language evidence: rejected because the
  bridge is an English-derived annotation layer.
- A learned composite ranker: rejected because Milestone 7 requires complete
  score decomposition and lacks a suitable high-confidence training target.
- One null family, labels/order shuffling, or independence-only calibration:
  rejected because none represents the required conditioned lexical noise.
- A single hapax or correlated detector restatements as sufficient evidence:
  rejected because rarity alone is fragile and not independent corroboration.
- Selecting thresholds after viewing candidates or held-out identities:
  rejected because it would invalidate the preregistered evaluation.
