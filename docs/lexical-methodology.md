# Transparent lexical-baseline methodology

Status: **Milestone 7 implementation and full-run validation in progress**

The governing configuration is `config/lexical.yaml`, the frozen held-out
preregistration is `config/experiments/m7-lexical-baseline.yaml`, the schema is
documented in [lexical-schema.md](lexical-schema.md), and ADR 0015 records the
architecture decision. This document describes the registered method; numerical
acceptance remains pending until two complete builds, strict validation, and CI
finish. It does not predeclare a successful scientific result.

## Calibrated scope

The full v1 retrieval, evaluation, and null-calibration scope is verse-level:

- Hebrew/Aramaic `edition_complete` Qere verses compared with Hebrew/Aramaic.
- Greek `edition_complete` source-reading verses compared with Greek.
- A separate exploratory Hebrew-to-Greek bridge using only explicitly
  English-derived MACULA gloss features.

Clause, sentence, two-verse, and five-verse feature and detector interfaces are
production-capable and fixture/smoke tested, but Milestone 7 does not make an
exhaustive or null-calibrated claim for those granularities. Greek
`critical_core`, Hebrew Qere/Ketiv loci, disputed text, reference gaps, and
Ketiv uncertainty are sensitivity boundaries rather than silently pooled
evidence.

## Feature identity and counting

Features are built from authoritative passage membership, never by reparsing
reconstructed text. Punctuation-only and zero-width tokens remain in provenance
and membership but do not create lexical features. Original-language feature
IDs include a language namespace (`hb` or `gk`), family, normalized value, and
order. English gloss features use `en`. A serialized Hebrew lemma can therefore
never equal a Greek lemma merely because the source strings happen to match.

The registered feature families are lemma, root, normalized surface, part of
speech, morphology, lemma/root bigrams and trigrams, bounded skip-grams, and
English glosses. Corpus frequency is calculated within language and
representation. Document frequency uses the primary verse passage as the
document and is also summarized by book and broad project genre. The full
source audit found no governed root coverage, so root interfaces remain tested
but production root counts must remain zero unless a future version activates a
documented source; roots are never inferred or fabricated.

High-document-frequency and formulaic features remain persisted for audit.
They are marked from the frozen document-frequency ratio and minimum corpus
count. Proposal filtering and the explicit formulaic penalty do not erase the
raw score or shared evidence.

## Sparse retrieval and transparent detectors

Every primary representation uses stable passage order, stable feature-ID
order, float64 CSR matrices, bounded query blocks, a bounded candidate union,
12-decimal score quantization, and target-passage-ID ascending tie breaks.
Dense all-pairs matrices are prohibited.

The registered detectors are:

- Binary Jaccard over feature sets.
- IDF-weighted multiset Jaccard.
- Sublinear-TF, smoothed-IDF, L2-normalized TF-IDF cosine.
- BM25 with `k1=1.2`, `b=0.75`, and binary query term frequency.
- Inverse-frequency shared rare lemma/root evidence.
- Shared phrase association using registered PMI (capped at 10), bigram
  log-likelihood, and bounded skip-grams.
- Normalized longest common subsequence.
- Rarity-weighted local ordered-sequence alignment with registered gap and
  mismatch penalties.
- POS/morphology sequence support as an independent supporting family.

The composite is reciprocal-rank fusion with `k=60`. It retains only the best
contribution from duplicate members of one detector family, so correlated
representations do not manufacture independent support. Original-language and
English-derived composites remain separate. No learned or opaque model enters
Milestone 7.

## Candidate evidence and statistical baselines

Candidate identity is the canonical unordered pair of immutable passage IDs,
profile, and granularity. Scores, ranks, benchmark labels, eligibility, and
review state never enter identity. Stored evidence retains directional ranks,
detector scores, RRF contributions, exact feature positions, corpus/document
frequencies, phrase association, alternatives, LCS/alignment values,
formulaic/local/short-passage penalties, disputed/gap/Ketiv flags, and English
status.

The analytical overlap calculation uses a hypergeometric independence model,
with Benjamini-Hochberg correction within the registered corpus-pair hypothesis
family. These values are useful baselines; they are not probabilities of
literary dependence. Empirical book- or genre-conditioned null calibration is
primary.

## Repeated null calibration

Every governed detector and the RRF composite are calibrated on a frozen,
deterministically selected 20,000-pair candidate-union sample. This scope does
not authorize a global all-pairs false-discovery claim.

Two null families each run 100 deterministic, uniquely seeded replicates:

1. Within-book feature-token reassignment preserves the corpus, book, passage
   count, exact passage-length vector, and book feature totals while breaking
   original within-passage sequences. It is not a passage-label or order
   shuffle.
2. Frequency-preserving synthetic passages preserve the exact length vector
   and sample from book-conditioned feature distributions when the registered
   support minimum is met, otherwise from the registered broad-genre
   distribution. Languages and English-derived source corpora never mix.

Every registered threshold reports the observed candidate count, mean null
count, empirical 2.5th and 97.5th percentiles, observed-to-null enrichment,
finite-replicate corrected upper-tail probability, and estimated empirical FDR
(`mean null count / observed count`). Undefined zero-denominator values remain
null rather than infinity disguised as a number.

Measured null-replicate runtime is retained as provenance telemetry but is
excluded from logical artifact identity, as are measured whole-run runtime and
local paths. Physical metadata or null Parquet bytes may consequently differ
between two otherwise identical runs. Acceptance requires exact equality of
every governed logical hash; physical telemetry-bearing differences are
reported rather than misrepresented as scientific nondeterminism.

## Conjunctive rare-evidence rule

A lemma or root at corpus frequency three or below cannot independently make a
candidate eligible. It requires a distinct registered co-signal: a second rare
item, a phrase with additional lexical material, an ordered sequence with at
least two additional features, an independent POS/morphology sequence, or a
non-restatement detector family. TF-IDF and BM25 on the same item, lemma and
surface from the same token, lemma and root restatements, forward/reverse reuse,
and English restatements are not independent. The stored evidence records the
co-signals and the reason for every pass or failure.

## Tier 3 evaluation

The only populated benchmark is the exact OpenBible snapshot, used as
**Tier 3 weak-supervision recovery**. Tier 1 remains header-only and empty, so
no high-confidence quotation-recovery, scholarly benchmark accuracy, or
validated allusion-recovery claim has been tested.

Recall@5/10/20, MRR, nDCG@20, Precision@10, coverage, eligible queries,
eligible relationships, and exclusions are reported with fixed-seed query
bootstrap intervals. Results remain separate by corpus pair, provisional
mapping status, split strategy and partition, book/genre/length where eligible,
disputed/gap status, and descriptive OpenBible vote stratum. Random ranking,
length-only ranking, and simple unweighted overlap are mandatory comparators.
Held-out results cannot tune weights or overwrite the frozen experiment.

## English bridge and ablation

The cross-testament v1 representation is explicitly English-gloss mediated.
It is retrieval infrastructure for a future approved Greek Old Testament
bridge, not direct Hebrew-Greek lexical evidence. Removing all English-derived
features removes the M7 bridge representation and therefore leaves no
non-English score or rank. Such a result may remain an English-mediated lead,
but it cannot satisfy a future `strong candidate` gate.

## Reporting and review boundary

The complete local Parquet and sparse artifacts remain Git-ignored. Tracked
reports contain aggregate counts, metrics, hashes, IDs, references, flags, and
bounded positional evidence, not bulk biblical text. The Milestone 8 queue is
unreviewed: it contains no reviewer, decision, interpretive classification, or
novelty claim. No Milestone 8 review begins as part of this methodology.
If the preregistered scientific gate, strict validation, or two-run logical
comparison fails, Milestone 8 remains blocked; the result must be preserved and
any remedy must be a separately registered Milestone 7 follow-up experiment.
