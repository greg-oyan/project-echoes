# 0018 — Close the lexical baseline and authorize `final-discovery-v1`

- Status: Accepted
- Date: 2026-08-08
- executing_agent: Codex
- Owner authorization: The project owner supplied the verified canonical
  Milestone 7 outcome and authorized one integrated local pre-production
  implementation for a later, separately launched whole-canon campaign.

## Context

Milestone 7 is technically complete and canonically sealed. Its frozen
edition-complete verse experiment analyzed the Hebrew/Aramaic Old Testament,
the Greek New Testament, and a separately labeled Hebrew–Greek English-gloss
bridge. The canonical result contains 1,248,779 candidates and a zero-row
strict review queue. Strict validation reported zero errors and zero warnings.
The applicable, sufficiently powered Tier 3 strata passed the registered
recovery comparison; `gnt_gnt` did not contain enough eligible benchmark
evidence for a recovery claim. No registered reciprocal-rank-fusion threshold
satisfied the maximum empirical-FDR policy under both required null families
for the applicable primary strata.

The frozen lexical configuration SHA-256 is
`9625a71c7768b25afa1f2d87eca044155c16b81401b91546a780d608655da83d`.
The frozen preregistration SHA-256 is
`5e5e29e281acacff88d0b954078d2cf995b7e4e37647430e5a08be74750a481c`.
The canonical table-hash manifest SHA-256 is
`e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6`.
The 18,606-file, 17.149-GiB canonical tree is independently archived and
verified in Backblaze B2 bucket `project-echoes-archive` at
`m7/canonical-schema-v1`; `rclone` reported 18,606 matching files and no
differences. The temporary production server was deleted.

The original Milestone 7 acceptance gate required a positive lexical
benchmark and empirical-FDR result. A technically valid scientific negative
was explicitly promotable and reportable, but it did not pass that scientific
gate or authorize the original Milestone 8 review. Because the strict queue is
empty, the original requirement to review its top 100 rows cannot be
satisfied. Lowering the frozen thresholds or manufacturing a queue would
invalidate the experiment.

The retained production history also shows that canonical bytes were produced
through a governed sequence of recovery and validator-contract corrections,
not one pristine initial commit. That composite provenance must be preserved
without treating ad hoc runtime monkeypatches as the permanent source
implementation.

## Decision

1. Close Milestone 7 as a technically successful, scientifically
   negative/incomplete lexical baseline. Preserve its configuration,
   preregistration, outputs, null results, failed attempts, recovery records,
   thresholds, and zero-row queue exactly. Do not reinterpret it as an
   accepted positive result and do not weaken its thresholds.
2. Record that the original form of Milestone 8 was not authorized and cannot
   meet its top-100 gate from the strict M7 queue.
3. Create a new experiment identity, `final-discovery-v1`, with a new frozen
   preregistration. It asks whether independent lexical, semantic,
   grammatical/syntactic, structural/narrative, and anomaly evidence can
   identify passage relationships that survive knownness, data-quality,
   remove-all-English, empirical-null, multiple-testing, and detector-family
   independence controls.
4. Reuse the authenticated M7 canonical artifacts as one lexical family. Do
   not rerun the M7 candidate-generation pipeline merely to reproduce that
   evidence. Correlated M7 subdetectors remain one family.
5. Build a separate, bounded, lawful positive-control benchmark for later
   engines. It does not modify or retroactively strengthen the historical M7
   Tier 3 evaluation.
6. Consolidate the remaining Milestone 8–16 implementation and production work
   operationally into one final campaign while retaining each milestone's
   traceable scientific component, stage outputs, validation, and acceptance
   evidence. This is an amendment within the existing milestone numbers, not
   a competing milestone sequence.
7. Pre-register two distinct final outputs:
   - **Tier A** contains only statistically eligible candidates satisfying the
     frozen null/FDR, multiple-testing, independent-family, knownness,
     data-quality, and English-ablation rules.
   - **Tier B** is the top 100 unknown, basically eligible exploratory rows for
     diagnosis and human review even when Tier A is empty. Tier B is never
     labeled statistically accepted, novel, or a discovery.
8. Require at least two genuinely independent evidence families for Tier A.
   English-derived evidence cannot be the only independent support, and every
   status that depends on English-derived evidence must be recomputed with all
   English-derived features removed.
9. Treat a Septuagint bridge as optional for this campaign. Activate it only
   if a source-specific edition, transcription, morphology, alignment,
   redistribution, and attribution review resolves safely without derailing
   the campaign. A documented deferral does not block `final-discovery-v1`.
10. Implement one restartable, manifest-authenticated production command with
    durable stages for input materialization, representations, detector
    evidence, null controls, ensemble, Tier A/Tier B, validation, packaging,
    B2 upload, and verification. Paid compute and the full production run
    require separate owner action; local development uses fixtures and bounded
    samples only.
11. A second whole-corpus run is optional and separately authorized only for
    a genuine infrastructure invalidation, a worthwhile reproduction, or a
    publication-level determinism requirement. It is not an automatic repeat
    of M7.
12. After the final production run and top-100 review, stop building detector
    engines. Report the result honestly even if Tier A is empty.

## Rationale

A negative baseline is evidence about a frozen method, not a permanent veto on
the broader research question. A new experiment identity allows independent
evidence families and stronger controls without rewriting the M7 result.
Separating statistically eligible and exploratory review outputs prevents a
second empty strict queue from blocking error analysis while preserving the
meaning of statistical acceptance.

One checkpointed campaign minimizes repeated whole-corpus cost and makes
failure recovery stage-local. Reusing M7 avoids unnecessary recomputation and
preserves the interpretability of the lexical baseline.

## Consequences

- M7 remains a citable negative/incomplete experiment with immutable hashes
  and a zero-row strict queue.
- Recovery-only validator contracts must be integrated into normal source and
  regression tests; retained recovery scripts remain provenance records, not
  the production API.
- `final-discovery-v1` may proceed only after its configuration,
  preregistration, sources/models, positive controls, family registry,
  thresholds, nulls, and output-tier rules validate locally.
- Tier B guarantees a bounded human-review set but confers no statistical or
  novelty label.
- The final campaign can complete with an empty Tier A.
- No paid cloud resource or production computation is authorized by this ADR.

## Alternatives considered

- Lower M7 thresholds or choose new thresholds after inspecting candidates:
  rejected because it would invalidate the frozen experiment.
- Treat the zero queue as evidence that no underdocumented relationships
  exist: rejected because M7 tested lexical similarity under one registered
  benchmark and calibration design.
- Keep the original Milestone 8 gate permanently blocking all later methods:
  rejected because a valid negative baseline should constrain, not terminate,
  a newly preregistered multi-family experiment.
- Relabel an arbitrary M7 top 100 as accepted candidates: rejected because it
  would erase the statistical/exploratory distinction.
- Require the Septuagint or a second full determinism run before any final
  campaign: rejected because unresolved licensing and unnecessary repeated
  compute must not become permanent blockers.
