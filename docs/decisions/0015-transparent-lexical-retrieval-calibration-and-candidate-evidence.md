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

#### Pre-heldout atomic-attempt and resource-feasibility record

The two pre-resume full-build attempts ended before atomic promotion and before
any candidate or scientific output was inspected. Operational progress, timing,
memory, and physical table-size telemetry were inspected solely to diagnose
feasibility. Neither attempt produced an accepted experiment result, and
neither changed the frozen scientific configuration or preregistration.

The first attempt was stopped after approximately three hours at 2.2 percent
completion. Its measured rate was 4.626 seconds per query, implying an
approximately 132-hour retrieval runtime. The staged output was not promoted.
This led to implementation-only reuse of immutable passage score contexts,
phrase and skip-gram extraction, LCS masks, rolling alignment state, gloss and
pair facts, and exact prepared sparse retrieval state. The algorithms, score
definitions, ranks, seeds, scopes, thresholds, and preregistered scientific
contract were unchanged.

The second attempt completed the primary Hebrew–Hebrew and GNT–GNT retrieval
scopes and had entered the primary English-gloss bridge when it was stopped.
Measured physical output projected that the build would violate the mandatory
10-GiB free-disk floor before atomic promotion. Its staged output was likewise
not promoted, and no candidate identities, evidence conclusions, evaluation
metrics, or other scientific results were inspected. Storage accounting showed
that physically duplicating directional English-ablation facts would consume a
projected 6.589 GiB across the primary and critical-core bridge scopes even
though those facts were already present inline on every content-hashed
directional ranking. The lossless inline normalization above removes that
duplication while preserving all registered ablation facts and conclusions.

The same feasibility audit replaced repeated leakage-group identifier arrays
with compact commitments. In the measured provenance map, this reduced unique
serialized provenance from approximately 283.3 MB to 33.9 MB. Strict
validation reconstructs and verifies the exact facts from the anchored
benchmark database, so this is a physical representation change rather than a
change to split membership, leakage controls, eligibility, or evaluation.

The first resumed build on 2026-07-17 completed all primary, critical-core, and
Qere/Ketiv retrieval scopes before the global critical-core sensitivity join
breached the mandatory free-disk floor. At the last safe inventory, the
unpromoted tree retained 1,565 ranking parts (5,718,310,351 bytes), three index
metadata parts, 154 sparse-index files, and the governed feature tables. The
single DuckDB FULL OUTER JOIN and global sort then accumulated 17 temporary
files totaling 13,426,360,320 bytes. Free space fell from above the configured
10,737,418,240-byte floor to 8,606,294,016 bytes and continued declining, so
the process was stopped before disk exhaustion. No artifact was promoted, and
no candidate identity, held-out metric, null result, or science-gate outcome
was inspected. The disposable join spill was removed after its exact footprint
was recorded; completed staging artifacts were retained while the failure was
diagnosed.

Sensitivity materialization now executes the identical reference-keyed FULL
OUTER JOIN and window calculations in deterministic
`(corpus_pair, detector, query-reference hash bucket)` partitions. Four stable
SHA-256 prefix buckets keep every target row for one query reference in the
same partition, so each window remains complete. The partitions emit the same
governed rows, fields, identities, scores, ranks, overlap, digests, and final
sort keys. A per-partition DuckDB spill limit is computed from current free
space after reserving the configured floor and an additional 256 MiB safety
margin; a join fails before execution when at least 256 MiB of bounded spill
headroom is unavailable. The maximum spill for one partition is 2 GiB, and the
sensitivity-only preferred DuckDB memory budget is 1 GiB inside the unchanged
process-wide memory guard.

Before restarting retrieval, the preserved attempt-3 ranking tree was used for
a full-scale operational diagnostic of the corrected critical-core join. It
streamed all 28,336,934 comparison rows in 600 schema-cast frames in
1,637.97 seconds, with empty stderr, minimum observed free disk of
21,304,016,896 bytes, and 1,997,938,688 bytes peak RSS at guarded checkpoints.
Only row/frame counts and resource telemetry were observed; no score,
candidate identity, held-out metric, or scientific conclusion was inspected.
The corrected query left no spill directory behind.

The next atomic attempt started at 2026-07-17 19:48:56 local time and ran for
approximately 3 hours 36 minutes. It completed all 1,565 ranking parts and both
sensitivity comparisons. The intact staging boundary contains 5,718,310,351
bytes of rankings and 640 sensitivity parts totaling 4,601,220,953 bytes,
together with all 14 governed sparse indexes and feature tables. After
sensitivity cleanup, Tier 3 setup attempted one global Polars distinct-strata
scan over the complete ranking tree. The Rust allocator could not satisfy a
708,873,488-byte request, and the process exited before any Tier 3, null,
candidate-evidence, or queue artifact was written. Stderr contains only that
allocator failure. No held-out score, candidate identity, null result, or
science-gate value was inspected.

Interrupted staging may now be adopted only when it is a non-symlinked
governed sibling of `schema-v1`. Adoption reads, schema-casts, order-checks,
counts, and hashes every existing Parquet leaf before reuse. Ranking-strata
discovery projects and deduplicates the three required columns one Parquet
leaf at a time rather than building a global distinct set over the full
ranking table. The result set and validation rules are unchanged.

The primary candidate aggregates existed only in process memory when the
allocator aborted. Recovering their exact proposal-detector and bounded
alignment traces from persisted top-100 rows alone is not lossless. Therefore
the resume path reloads the already persisted primary sparse indexes and
recomputes only primary retrieval. Every regenerated ranking part must match
the corresponding preserved governed logical rows before its aggregate
updates are accepted. Those exact updates are written to a private,
content-hashed completion checkpoint so a later post-retrieval failure does
not repeat the recovery. Completed critical-core retrieval, Qere/Ketiv
retrieval, and both sensitivity comparisons are inventoried and skipped.
Private checkpoints and transient spill are excluded from final promotion.
Exact primary split-provenance payloads are reconciled one ranking leaf at a
time and reused during that verification; final strict validation still
reconstructs them from the anchored benchmark. This avoids recreating the
measured 8.5-GB provenance spill beside the preserved 9.76-GB staging tree.
Passages with no retained top-100 row cannot be recovered from ranking leaves.
For only those missing IDs, recovery performs an exact `json_contains` join
against the anchored endpoint mappings with a 512-MiB DuckDB spill cap, then
uses the unchanged assignment grouping, canonical ordering, and digest logic.
This targeted query is fixture-checked against the original full JSON
expansion. It must not silently substitute the no-assignment payload for a
mapped passage.

The next resume verified every regenerated primary ranking leaf and finalized
968 checkpoint parts plus its completion manifest. It then repeated the exact
708,873,488-byte allocation failure before writing a Tier 3 row, proving that
the remaining allocation was the following global candidate-universe
`group_by`, not the already bounded strata scan. Directory-backed universe
construction now accumulates each query's target set one Parquet leaf at a
time, pools repeated IDs, enforces the unchanged configured maximum during
accumulation, and canonically sorts the same unique targets. Fixture coverage
compares this bounded path with the original global grouping. The completed
checkpoint is retained so another resume does not repeat primary retrieval.

The following resume passed the former candidate-universe allocation point but
then exposed a distinct 1,827,928,004-byte Rust allocation in the next
per-detector global ranking collection. Evaluation now streams each detector's
filtered ranking rows one sorted leaf at a time, pools repeated identifiers,
enforces the unchanged persisted top-100 bound, and validates canonical rank
order and duplicate identities before constructing the same target and score
maps. Fixture coverage compares the streamed and materialized results exactly.
A private last-stage marker is retained only inside the ignored checkpoint
directory during recovery and is deleted with that directory before promotion.

The next resume completed every edition-complete Tier 3 baseline and detector,
then every critical-core baseline and detector through the final composite
aggregation. No evaluation artifact had yet crossed the atomic writer
boundary. The process retained each completed baseline and detector as Python
row dictionaries until both profiles finished; Windows private commit grew to
approximately 10 GiB, the pagefile expanded, and the Rust allocator ultimately
could not reserve 1,632 bytes at the marker
`evaluation:critical_core:detector:rrf_composite:leaf-1536:groups-25222`.
The process and pagefile released their space after exit, leaving the original
staging and primary-candidate checkpoint intact. No held-out value, candidate
identity, null result, or science-gate outcome was read.

Tier 3 evaluation now converts each unchanged baseline or detector result batch
immediately to the governed typed schema and a private Parquet checkpoint.
Every completed batch is protected by a completion manifest containing the run,
configuration, preregistration, profile, detector, row count, and physical
SHA-256 identity. Reuse verifies those identities, the exact schema, nonempty
row count, unique evaluation IDs, and singleton lineage fields before skipping
the expensive detector-ranking pass. Incomplete physical files have no
completion manifest and remain ignored rather than trusted or overwritten.
The final table is assembled in the same governed sort order, checked for
global evaluation-ID uniqueness, written to the atomic artifact staging area,
and released before null calibration. Fixture coverage proves the
checkpointed, resumed, and original in-memory paths return the identical typed
evaluation frame and scientific-gate details.

Subsequent launcher recovery exposed a separate Windows process-control hazard.
A sandboxed background launch exited without creating a worker. Two later
launchers did create independent child workers, but their transient wrapper
processes disappeared while those children continued. Because the wrappers
were initially mistaken for the complete process lifetime, the workers
overlapped and both failed at approximately 15:04 local time under aggregate
memory pressure. Their stdout and stderr logs are retained. One worker had
already written the three edition-complete baseline checkpoint parts; the
other did not add a trusted completion. A bounded startup probe established
the child-process behavior, and a complete nonprivileged process census
confirmed that every earlier worker was gone before the next sole-worker
resume. That resume reused no checkpoint merely because it existed: each of
the three completed baseline parts first passed the run, configuration,
preregistration, schema, lineage, row-count, evaluation-ID, and physical-hash
checks above. The overlap is an execution-control failure, not an accepted
scientific replicate or a reason to alter any frozen parameter.

The next sole-worker resume completed and authenticated all 26 Tier 3
evaluation batches, the complete governed evaluation artifact, all 600 frozen
null replicates, threshold calibration, and the global candidate-ranking
preparation. Candidate materialization persisted four aligned parts in each
governed candidate/evidence table before an internal BM25 reproduction check
compared `12.867698770178` with `12.867698770179`. The values occupy adjacent
bins at the already registered 12-decimal precision and arise from different
deterministic float64 reduction paths. Neither value, its rank, nor any frozen
parameter was changed. The stopped attempt, its stderr, its posthoc physical
inventory, every completed checkpoint, all null/calibration results, and all
complete candidate parts remain preserved.

Evidence reproduction therefore converts both finite values to exact integer
bins only after fixed-decimal formatting. Exact matches add no trace field. An
adjacent one-bin result retains both decimals and the signed bin delta in an
explicit reconciliation object while leaving the persisted score unchanged.
Differences greater than one bin and all non-finite values still fail closed.
Existing resumed leaves must compare logically with regenerated leaves and are
never silently overwritten. Execution-attempt sidecars are created before
pipeline work and bind the git/source state, lock and configuration hashes,
pinned inputs, actual seeds, authenticated resume lineage, output inventories,
runtime, hardware, warnings, errors, and an exact bounded reproduction command.
Failed, recovered-composite, and independent fresh attempts remain separately
identifiable.

The first resume after those recovery changes authenticated and adopted every
preserved artifact and all 968 primary checkpoint parts, then stopped during
bounded evaluation-state reconstruction because Windows denied one rewrite of
the private diagnostic progress marker. The marker and its directory remained
writable after exit, disk headroom was healthy, no canonical output was
promoted, and all 10,910,973,940 bytes of staging remained intact. The failed
execution sidecar and stderr are preserved separately.

Private progress-marker writes therefore use the same bounded Windows
reader/scanner-lock policy already used for atomic acquisition renames. A
`PermissionError` receives ten total attempts with increasing 50-millisecond
steps; another `OSError` fails immediately, and a persistent permission denial
still fails closed after no more than 2.25 seconds. This changes only ignored
diagnostic-marker robustness. It does not change any scientific artifact,
identity, score, rank, source, detector, null, threshold, seed, acceptance
rule, or preregistration value.

The reusable private checkpoint tree is no longer deleted before content
hashing, metadata construction, atomic promotion, DuckDB loading, and execution
manifest finalization. It moves atomically to a governed ignored sibling just
before finalization, is restored to staging after any ordinary failure, is
recovered automatically after an interruption in that narrow move window, and
is removed only after the successful execution manifest is durable. Fresh full
builds also preserve their governed atomic staging directory on error so an
independent second build does not lose completed expensive stages.

The next sole-worker resume authenticated that preserved state and completed
2,535 aligned leaves for each candidate artifact family, covering the sorted
975,000-candidate prefix, before a DuckDB allocator failure. The
`candidate_ranks` relation was a lazy view, so every bounded 5,000-identity
lookup expanded the same baseline and eight ablation window rankings over the
global candidate population. It now materializes the identical SQL once as a
table in the same single-threaded, memory-limited, spill-controlled temporary
DuckDB database, then releases the input table. Subsequent lookups remain
bounded, and every existing resumed leaf is still regenerated and compared
logically before reuse. This changes physical evaluation frequency only; the
candidate population, score expressions, partitions, ordering, ranks, and
artifact semantics are unchanged.

This is a physical execution and fail-closed resource correction only. No
scope, source, representation, detector, threshold, seed, null, evaluation,
acceptance, or preregistration value changed after held-out data.

The Milestone 7 acceptance state remains pending. Two complete, independently
validated deterministic builds and the final preregistered science-gate result
must be recorded before this decision can support milestone closure.

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
