# Milestone 7 recovery and task ledger

Status: **In progress**

Last reconciled: 2026-07-19

This ledger records the exact recovery state of Milestone 7 after the persistent
Codex goal was interrupted. It does not replace the master plan, frozen
preregistration, or ADR 0015. Statuses use the Build Week continuation
categories exactly: `complete and validated`, `complete but unvalidated`,
`partially implemented`, `not started`, and `blocked`.

## Recovered repository state

- Branch: `feature/m7-lexical-baseline`
- Recovered HEAD: `7df3fd150e14983454725e2e69126bea639326b9`
- Branch base: `b9637ee2de1840cbc2056dfcec6aea163d1e9194`
  (`main` and `origin/main`)
- Remote synchronization after `git fetch --prune origin`: local HEAD is two
  commits ahead of `origin/main`; no remote Milestone 7 branch exists yet.
- Milestone 7 commits:
  - `9d454e23affb7241c99cd40f05e640ab7c800510` — transparent lexical
    baseline architecture
  - `7df3fd150e14983454725e2e69126bea639326b9` — directional English
    ablation storage normalization
- Recovered tracked modifications:
  - ADR 0015 records two pre-held-out feasibility failures.
  - `docs/experiment-log.md` records the same failures and pending successful
    builds.
  - The lexical feature audit differs only in measured free-disk telemetry.
- Recovered untracked files: none.
- Recovered Milestone 7 generated output:
  `data/processed/lexical/` contained no promoted schema, run manifest, or
  checkpoint. Both failed staging trees had already been removed.
- Running state at recovery: no lexical process. Full atomic build 1 was
  started only after the audit and prerequisite validation described below.

No branch reset, result deletion, preregistration change, held-out inspection,
or Milestone 8 work occurred during recovery.

## Validation performed before resuming the expensive stage

- `uv run echoes validate-config`: 17 configuration files passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: initially 175 files passed; the post-fix
  suite passes all 179 files.
- `uv run mypy src`: initially 95 source files passed; the post-fix suite
  passes all 96 source files.
- `uv run pytest`: initially 651 passed; after the bounded sensitivity,
  Build Week, recovery, and execution-provenance additions, 720 pass and 29
  governed full-data tests skip under their default opt-in guard.
- `ECHOES_RUN_FULL_CORPUS=1 uv run pytest tests/regression`: all 29 passed.
- `uv run echoes validate-corpus`: 475,911 Hebrew tokens, 39 books, 929
  chapters, 23,213 verses, zero errors, and zero warnings.
- A fresh ignored lexical-feature audit reproduced the tracked audit exactly
  after excluding the declared runtime free-disk telemetry line.

## Original Milestone 7 implementation ledger

| Requirement | Status | Evidence or remaining gate |
| --- | --- | --- |
| Frozen, content-authenticated experiment configuration and upstream anchors | complete and validated | `config/experiments/m7-lexical-baseline.yaml`, `config/lexical.yaml`, config validation, and unit coverage |
| Stable verse-level Hebrew/Aramaic and Greek feature extraction | complete and validated | Governed passage membership, language namespaces, feature audit, full-data regressions |
| TF-IDF | complete and validated | Sparse float64 implementation and fixture/unit coverage; full scientific output pending |
| BM25 | complete and validated | Sparse implementation with frozen `k1` and `b`; fixture/unit coverage; full scientific output pending |
| Binary and IDF-weighted Jaccard | complete and validated | Transparent detector implementation and tests |
| Rare-lemma and rare-root scoring | complete and validated | Interface, scoring, frequency fields, and tests pass. The governed full sources contain zero root annotations, so production root rows must truthfully remain absent rather than fabricated |
| Lemma/root phrase, n-gram, and skip-gram scoring | complete and validated | Feature audit and unit tests pass; production root phrase evidence is unavailable because root coverage is zero |
| Longest-common-subsequence and weighted ordered-sequence scoring | complete and validated | Bounded candidate-union implementation and tests |
| POS/morphology support | complete and validated | Independent support implementation and tests |
| Deterministic representation, ranking, feature, and candidate identities | complete and validated | Schema/identity tests and collision checks pass |
| Interpretable candidate evidence with positions and frequencies | complete and validated | Typed evidence schemas, digest checks, and synthetic tests pass; full generated evidence pending |
| Explicit penalties, exclusions, disputed/gap/Ketiv flags, and raw-score preservation | complete and validated | Candidate materialization and validation tests pass |
| Configurable conjunctive rare-evidence rule and co-signal fields | complete and validated | Frozen threshold/co-signals, correlated-signal rejections, candidate and validator tests |
| Tier 3 OpenBible recovery evaluation | complete and validated | Implementation, split/leakage provenance, baseline comparators, metrics, and tests pass; full result pending |
| Random, length-matched, unweighted-overlap, and presumed-negative baselines | complete and validated | Evaluation implementation/tests pass; full result pending |
| Within-book reassignment null preserving book frequencies, passage counts, and lengths | complete and validated | Implementation and preservation tests pass; 100-replicate production result pending |
| Frequency-preserving synthetic-passage null with book/genre conditioning | complete and validated | Implementation and preservation tests pass; 100-replicate production result pending |
| Threshold reports with observed count, null mean, empirical 95% interval, enrichment, tail probability, and empirical FDR | complete and validated | Typed calibration implementation/tests pass; full report pending |
| Critical-core and Qere/Ketiv sensitivities | complete and validated | Frozen scopes, typed artifacts, tests, and feature audit pass; production result pending |
| All eight frozen ablations, including remove-all-English | complete and validated | Typed candidate ablations and normalized directional English facts pass tests; production result pending |
| Sanitized unreviewed queue with OpenBible represented/unrepresented separation | complete and validated | Queue implementation/schema tests pass; production queue pending |
| Atomic storage, manifests, logical hashes, DuckDB exposure, and strict validation | complete and validated | Storage/validation tests pass; full artifact validation pending |
| Full atomic build 1 | partially implemented | Every failed or weaker attempt remains preserved in ADR 0015 and the experiment log. Sole-worker attempt 5k validated all 26 Tier 3 checkpoint batches, completed all 600 frozen null replicates and calibration, completed global candidate ranking, and wrote four aligned candidate/evidence parts before an adjacent one-bin BM25 reproduction check stopped materialization. Attempt 5l authenticated and adopted the complete 10.16-GiB staging tree and 968-part primary checkpoint, then preserved a separate failed execution when a transient Windows reader lock denied one ignored progress-marker rewrite. All 52 Tier 3 checkpoint files, null/calibration outputs, candidate parts, stderr logs, provenance records, and execution sidecars remain reusable. The exact/adjacent/>1-bin reconciliation, execution-attempt provenance, and bounded progress-marker retry contracts pass focused tests. The next sole-worker resume must authenticate and reuse the retained work without repeating primary retrieval |
| Strict validation of full build 1 | not started | Requires promoted build 1 |
| Independent full build 2 | not started | Requires validated build 1 to be preserved as the determinism reference |
| Exact two-run logical determinism comparison | not started | Requires both promoted builds |
| Final preregistered scientific acceptance decision | not started | Must be read from frozen held-out evaluation and both null families without tuning |
| Final Milestone 7 aggregate reports and failure preservation | not started | Requires completed artifacts and determinism evidence |

## Milestone 7 acceptance ledger

| Acceptance requirement | Status | Evidence or remaining gate |
| --- | --- | --- |
| Known-link recovery exceeds random baseline | complete but unvalidated | Frozen evaluation and gate logic exist; held-out production result not yet available |
| Known-link recovery exceeds simple unweighted-overlap baseline | complete but unvalidated | Frozen evaluation and gate logic exist; held-out production result not yet available |
| Candidate evidence is interpretable | complete but unvalidated | Schema and fixtures pass; production spot checks and strict validation pending |
| Within-book null meets every preservation invariant and is not label/order shuffling | complete but unvalidated | Tests pass; 100 production replicates pending |
| Synthetic null preserves length and conditioned frequencies | complete but unvalidated | Tests pass; 100 production replicates pending |
| Every governed threshold includes all required empirical fields | complete but unvalidated | Tests pass; production calibration pending |
| Rare evidence cannot qualify without an independent co-signal | complete but unvalidated | Tests pass; production candidate/queue validation pending |

Failure of either scientific recovery comparison or any strict gate will be
preserved as a real Milestone 7 result. It will not be tuned away.

## Build Week continuation ledger

The full experiment is substantially implemented, so the scope decision is to
finish the original frozen Milestone 7 experiment. A reduced
`m7-build-week-part1` experiment is neither needed nor authorized by the
current state.

| Delivery requirement | Status | Evidence or remaining gate |
| --- | --- | --- |
| First real transparent lexical result | not started | Requires promoted and validated full build |
| Sanitized `demo/data/echoes-demo-v1/` export | partially implemented | ADR 0016, deterministic exporter, recursive prohibited-field checks, and unit tests exist; the real production export awaits validated artifacts |
| `overview.json` | not started | Requires validated metadata and aggregate tables |
| 10–25 real represented recoveries | not started | Deterministic export after validation; actual available count will be reported |
| 25–100 real unrepresented candidates | not started | Deterministic export after validation; no review or novelty judgment |
| Qere/Ketiv and disputed-profile uncertainty examples | not started | Deterministic sensitivity selection; no fabricated examples |
| Export manifest with input/run hashes and generated-file hashes | not started | Requires all other export files |
| Strict prohibited-field/reconstructability exporter test | complete and validated | Recursive fail-closed tests reject feature values, token text, glosses, morphology strings, source paths, raw records, and unresolved redistribution fields |
| Full quality, full-data, strict-validator, upstream-digest, and pre-commit gates | partially implemented | Pre-run quality/full-data gates pass; post-artifact gates remain |
| Clean commit and pushed branch | not started | Requires all outputs and validations |
| Unmerged draft pull request | not started | GitHub CLI is installed and authenticated; remote branch does not yet exist |
| Exact atlas-branch prompt | not started | Delivered only after the scientific checkpoint and PR exist |

## Public demonstration evidence boundary

The pinned MACULA determinations allow local processing but do not approve
committing complete processed annotations or reconstructable corpus text.
Accordingly, the tracked demonstration export may contain real references,
stable candidate/feature IDs, feature families, token-relative positions,
corpus/document frequencies, scores, ranks, null comparisons, flags, hashes,
and attribution. It must not contain source lexical strings, surfaces, English
glosses, morphology values, reconstructed verses, source paths, raw records,
or unresolved redistribution fields. A stable lemma/root feature ID is the
public representation of the shared lexical item; it remains resolvable in the
validated local research artifacts without exposing the protected value.

This conservative boundary is a delivery constraint, not a claim that every
upstream license forbids all short quotations. Any broader public field set
requires a separate documented publication determination.
