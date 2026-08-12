# Milestone 7 lexical baseline closure and postmortem

Date: 2026-08-08

Experiment: `m7-lexical-baseline` / lexical schema v1

Outcome: technically successful and canonically sealed; scientifically
negative/incomplete under the frozen acceptance policy

## Research question and frozen scope

Milestone 7 asked whether transparent lexical and phrase evidence could recover
known relationships above registered baselines and produce unknown candidates
that satisfied the frozen empirical-null and false-discovery policy.

The primary experiment used verse passages from the full original-language
primary corpus:

- Hebrew/Aramaic Old Testament, `edition_complete`, Qere reading;
- Greek New Testament, `edition_complete`, source reading;
- Hebrew–Greek comparison through a separately identified English-gloss
  bridge, never represented as original-language lexical identity.

The registered lexical detector set comprised binary and weighted Jaccard,
TF-IDF, BM25, rare-lemma/root overlap, phrase and skip-gram association,
ordered sequence methods, POS/morphology support, and a transparent
reciprocal-rank-fusion composite. Correlated lexical subdetectors remained one
lexical family. No semantic model, learned ranker, LLM discovery engine,
Septuagint bridge, or later detector family was part of M7.

The sensitivity plan materialized the complete critical-core Greek comparison
and the registered Qere/Ketiv comparison. Disputed text, reference gaps, and
Ketiv structural uncertainty remained explicit.

## Benchmark and null design

The project-curated Tier 1 quotation file contained its governed header and
**zero curated rows**. It supplied no M7 benchmark evidence. M7 evaluation used
the pinned OpenBible graph as **Tier 3 weak supervision**, not scholarly ground
truth or a sole high-confidence positive benchmark.

Both preregistered empirical-null families ran:

1. within-book feature reassignment preserving book frequencies, passage
   counts, and passage lengths; and
2. frequency-preserving synthetic passages preserving passage lengths and
   book- or genre-conditioned feature frequencies.

The frozen calibration applied these nulls to its registered candidate-union
sample and threshold grids. Hypergeometric values remained an analytical
independence baseline rather than a probability of literary dependence.

## Canonical result

| Item | Canonical fact |
| --- | --- |
| Candidate rows | 1,248,779 |
| Strict review-queue rows | 0 |
| Strict validation | 0 errors, 0 warnings |
| Scientific recovery gate | true for applicable sufficiently powered strata |
| `gnt_gnt` recovery | insufficient eligible benchmark evidence for a claim |
| RRF empirical-FDR selection | no registered threshold qualified under both required null families for the applicable primary strata |
| Frozen lexical configuration SHA-256 | `9625a71c7768b25afa1f2d87eca044155c16b81401b91546a780d608655da83d` |
| Frozen preregistration SHA-256 | `5e5e29e281acacff88d0b954078d2cf995b7e4e37647430e5a08be74750a481c` |
| Canonical table-hash manifest SHA-256 | `e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6` |
| Canonical inventory | 18,606 files; 17.149 GiB |
| Durable archive | Backblaze B2 `project-echoes-archive/m7/canonical-schema-v1` |
| Independent archive verification | 18,606 matching files; zero `rclone` differences |
| Temporary server | deleted after durable verification |

No threshold, score weight, seed, candidate identity, null family, acceptance
criterion, or preregistration value was weakened after results were observed.
The zero-row queue is the correct output of the frozen policy; it is not a
missing artifact.

## Sensitivity result

The critical-core Greek and Qere/Ketiv sensitivity outputs were materialized
and retained with the canonical run. They support inspection of disputed-text
and reading-stream sensitivity without deleting edition-complete or Qere
evidence. Their presence does not convert an English-gloss bridge into
original-language evidence and does not supply a qualifying RRF threshold.

## Runtime and resource envelope

The canonical result is a recovered composite, so one pristine end-to-end
stopwatch would be misleading. The retained ledger records at least these
substantial worker segments before final cloud reconciliation: approximately
3 hours for the first feasibility attempt, 3 hours 36 minutes for attempt 4,
11 hours 15 minutes for sole-worker attempt 5k, 15 minutes for attempt 5l, and
31 hours 54 minutes for attempt 5n. Those named segments alone total roughly
50 hours, excluding attempt 2, attempt 3, short failed launches, transfer,
final repair, hashing, validation, promotion, and archive verification. The
largest near-complete continuous worker segment was about 32 hours.

Final repair and promotion used the governed Hetzner CCX33 envelope: Ubuntu
24.04, 8 dedicated AMD vCPUs, 32 GiB RAM, 240 GB local SSD, exactly one frozen
scientific thread, a 22-GiB per-stage DuckDB ceiling, `MemoryHigh=26G`,
`MemoryMax=28G`, a 48-hour worker cap, and a 25-GiB runtime free-disk floor.
The canonical output itself is 17.149 GiB.

Legitimate compute time includes sparse retrieval, sensitivity retrieval,
Tier 3 evaluation, 600 null-replicate rows across the governed strata,
calibration, global candidate ranking, candidate/evidence materialization,
hashing, and strict validation. Operational recovery overhead includes
diagnosing allocator failures, Windows process ownership and reader locks,
checkpoint adoption, transfer/bootstrap work, validator-contract
reconciliation, portable index regeneration, transactional promotion, and B2
verification. Calendar time between the first feasibility work and canonical
archival therefore substantially exceeds actual scoring time and must not be
reported as model runtime.

## Composite source and recovery provenance

No retained local launch receipt records an exact server `HEAD`. The tracked
transfer manifest intentionally used `commit_policy: operator_supplied`, and
the corresponding `latest-launch.json`/remote proof is not retained. The
strongest locally auditable statement is therefore **launch lineage through
`c8fc361567a931f6743061a5f14306a2a7ef49d1`**, not a claim that the exact
launch `HEAD` has been recovered. This provenance gap is retained explicitly
rather than filled with an inference. The initial production/recovery code
lineage is the M7 feature history rooted at
`9d454e23affb7241c99cd40f05e640ab7c800510` and includes the operational and
resource fixes through `c8fc361567a931f6743061a5f14306a2a7ef49d1`.
PR #9's per-stage DuckDB ceiling changes are already ancestral through merge
commit `f5cdcebacc295981156e4f36fd1e5c16bf95949d`.

The final artifact additionally depended on retained server-side recovery
programs. The repository descendant
`dffc0324766bb6adb239944915e2c30978b95d2b` preserves the first completed-stage
repair validator as `cloud/m7_repair_and_validate.py`. Later retained operator
records include:

- `finalize_project_echoes_m7.ps1`, SHA-256
  `9573b1ff909d5d5bb847593125d108b1a39150808287f6cef79563ddc0b80449`;
- `finalize_project_echoes_m7_v2.ps1`, SHA-256
  `b415fa9a8ae18889d7b9aa831b8812d1c07d07bb8db804f6f73dfb098b13ffd4`;
- `run_m7_repair_and_validate.ps1`, SHA-256
  `7542abaf08fec9212b2e5e0390a268c3018e5465ef200bb7c8bfa5a6917681e4`;
- `run_m7_repair_and_validate_v2.ps1`, SHA-256
  `ea9e2b65bf99f9c641b4b65fec231d1c07c624c5355fae0928b057028a6095b8`;
- `run_m7_repair_and_validate_v3.ps1`, SHA-256
  `fa96ad48667238c1dca7770a8578efeaf9d4fa584f2e45d7818b45d63981e179`;
- `run_m7_repair_and_validate_v4.ps1`, SHA-256
  `98506c80cd4e61656bfd89f603b97950cb82937c18672385c85d831264fa09bf`;
- `run_m7_reconcile_and_validate_v5.ps1`, local wrapper SHA-256
  `637b226d3e29048afa5637632aea7e2df2c9616e89fad73ebb856ab4d023047a`;
- the V5 server reconciler payload authenticated by the final promoter as
  SHA-256 `636c65ddcb691761f11a5080873ef0ac6cd8bad52f452af55e025f0e5b7676d1`;
- `run_m7_final_canonical_promotion.ps1`, local wrapper SHA-256
  `60cdbab0d58799ad2addb67b257e85317463fb209bf8bac958138451487d8f61`;
- `download_and_verify_project_echoes_m7_final.ps1`, SHA-256
  `72024eef4df5610786f8f90a802cabe83a6f575486375be0680fdf5d1872aaf2`.

The final validator contracts covered nullable evidence fields, Python rather
than DuckDB score-quantization semantics, raw-score RRF ordering, special
English-derived evidence identities, retrieval-direction trace positions,
no-qualified-threshold sentinels, critical-core/Ketiv sparse passage axes,
exact sparse-index inventories, bounded validation, zero-row queue validity,
and transactional promotion/finalization receipts. Index regeneration matched
scientific metadata and logical content before platform-specific physical
index hashes were refreshed and resealed.

Accordingly, the canonical data cannot honestly be attributed to one pristine
initial commit. Its scientific configuration is frozen and unchanged, while
its physical realization and authentication are a traceable composite of the
launch lineage, preserved checkpoints, recovery scripts, final validator
contracts, promotion receipts, table-hash seal, and independent B2 inventory
verification. Permanent repository source and regression tests now absorb the
legitimate validator contracts; the ad hoc scripts remain historical
provenance rather than the supported validator API.

## What the result supports

- The project successfully executed and authenticated its preregistered
  transparent lexical experiment at whole-primary-corpus verse scale.
- The applicable sufficiently powered Tier 3 strata showed recovery above the
  registered comparison baselines.
- Under the frozen candidate-union sampling, null families, RRF threshold grid,
  and maximum empirical-FDR policy, no applicable threshold qualified.
- Lexical similarity alone was insufficient to yield a strict review queue
  under those frozen controls.
- Operational recovery can preserve scientific identity when each physical
  correction is explicit, fail-closed, and separately authenticated.

## What the result does not support

- It does not establish that no underdocumented biblical relationships exist.
- It does not establish performance against a populated Tier 1
  high-confidence quotation benchmark; Tier 1 had zero rows.
- It does not prove that Tier 3 benchmark mismatch caused the negative result.
  Benchmark heterogeneity is a plausible limitation or hypothesis, not a
  demonstrated cause.
- It does not evaluate independent semantic, syntactic, structural, narrative,
  anomaly, or Septuagint evidence.
- It does not justify lowering thresholds, relabeling an arbitrary top 100 as
  accepted, or describing absence from OpenBible as universal novelty.

## Closure decision

M7 is closed as a valid technically successful, scientifically
negative/incomplete experiment. Its original acceptance gate remains unmet and
the original form of Milestone 8 did not occur. ADR 0018 authorizes the new
`final-discovery-v1` experiment, which reuses M7 as one lexical family and
pre-registers a statistically eligible Tier A separately from an exploratory
Tier B top 100. M7 itself remains immutable.
