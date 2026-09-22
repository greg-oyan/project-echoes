# ADR 0023: Authenticate M7 null execution separately from threshold selection

- Status: Accepted
- Date: 2026-09-22
- executing_agent: Codex

## Context

The recovered campaign completed Stages 1–5 and failed at Stage 6 with
`production M7 evidence must authenticate both canonical M7 null families`.
The source M7 candidate field `both_null_families_present` is false when no
frozen RRF threshold qualified. In that state the canonical contract also
requires threshold 1.0, positive-infinity FDR/null rate and review ineligibility.
The lexical producer and strict lexical validator agree on this sentinel.
The adapter correctly preserves it, including the registered JSON infinity
sentinel. Final-discovery consumers incorrectly treated the candidate flag
as an unconditional assertion about execution of the source null experiments.

## Decision

Authenticate execution independently from the preserved source tables. Bind
the pinned M7 manifest, exact schemas, file hashes, row counts, candidate and
RRF representation membership, both registered null families, their original
100 iterations per threshold/stratum, seeds, replicate summaries and frozen
calibration outcomes. Reuse the existing lexical calibration validator rather
than generating new nulls. Bind each accepted trace to its exact canonical
candidate values and the actual evidence passage pair and RRF score.

Production builds this authentication context once from authenticated Stage 1
after Stage 5. Stage 6 saves its receipt; Stages 6/7 and strict final validation
consume the context. Independent completed-campaign validation authenticates
the same retained source. A receipt alone does not grant trust. Missing,
altered, incomplete or inconsistent null evidence remains an error. Bounded
fixtures retain their previous true-flag contract when no context is supplied.

Do not change the canonical false flag, infinity sentinel, M7 projection,
adapter, source artifacts, frozen final thresholds, detector independence,
final null iteration policy, Tier A criteria or exploratory Tier B meaning.
This corrects an authentication mismatch; it does not turn the negative M7
result into a qualified discovery or change the scientific experiment.

The repaired source identity cannot reuse old completion records as though
they were produced by the new code. A separately reviewed one-off importer
may authenticate and independently copy the five completed stages into fresh
ordinary StageStore attempts, with original completions and explicit
compatibility provenance retained. It must pin both code identities, all
five source completion hashes, unchanged Stage 1–5 producer closure, input,
configuration, model and runtime identities. It must reject unreviewed drift.
Old stages, failure records, output namespace and receipts remain untouched.
Resume Stage 6 under a fresh output prefix; never start a duplicate worker.

The exact successor work directory
`/srv/project-echoes/final-discovery/work-20260922-m7-null-recovery` inherits
the existing immutable recovery ledger. Installation still accepts only the
original work directory. The original start and September 25 02:46:42 UTC
deadline, timer and expiry behavior remain unchanged; this is not a new window.

The 280-GiB fresh-run launch gate cannot be applied literally after preserving
both old artifacts and independently imported completions on the existing disk.
For this exact successor only, authenticate all five imported completions,
their source/repair provenance and current source/configuration identity, then
require **225,737,600,612 bytes free after import**. This reserves the entire
original modeled artifact budget of 139,838,254,692 bytes as additional future
space, plus the unchanged 80-GiB checkpoint floor. It gives no space credit for
work already completed. Inputs and models are already local; packaging and
checkpoint staging use existing hardlink mechanics inside the new campaign.
The original projection is an estimate, not a guaranteed peak. The existing
checkpoint disk checks and memory/runtime limits remain active.

Retain 280 GiB for fresh runs and every other work directory. Record the
effective requirement and its authenticated basis in the launch intent.
Before copying, the one-off deploy script must require the exact pinned
source-artifact copy sizes, extra provenance, a 1-GiB filesystem allowance,
and this entire future reserve. Insufficient measured space stops recovery;
it does not authorize deletion, a machine upgrade, or another paid resource.

## Validation and limits

Focused tests cover canonical negative and qualified outcomes, missing or
altered source families/iterations/thresholds, candidate and trace tampering,
consumer integration, and inherited deadline expiry. Reuse previous broad
test evidence for unchanged code and the preserved 1,248,779-row ordering
receipt for the unchanged adapter/projection. Source authentication against
the actual preserved M7 tree must still succeed when production resumes;
local synthetic tests are not a real-data success receipt. No final findings
exist until the remaining stages and durability checks finish.
