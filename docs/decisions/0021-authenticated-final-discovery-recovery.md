# ADR 0021: Authenticate and reuse preserved final-discovery artifacts

Status: Accepted; recovery implementation prepared locally, not yet deployed.

## Context

The owner authorized completion and recovery of the existing campaign on
2026-09-20, including reuse of completed stages and valid test receipts.
The September 9 campaign was terminated by server shutdown during Stage 1
(systemd exit 143), rather than completing or recording a pipeline exception.
Earlier Stage 1/2 artifacts and the successful all-row M7 ordering test remain
preserved. Directly substituting older completion records would violate the
existing exact code-identity and dependency checks.

## Decision

Provide a local-only import command that authenticates the complete original
Stage 1/2 dependency chain, current inputs and scientific configuration,
unchanged scientific code, and actual model/runtime inventories. Copy verified
artifact bytes into fresh ordinary stage attempts; do not rewrite originals,
use shared writable hardlinks, or relax StageStore validation. Include original
completion bytes and explicit reuse provenance in the new stage inventories
and final package. New completion identities describe the revalidation/import
operation, while original generation identities remain recorded.

Stage 3 may consume the preserved passing ordering-test bundle at
`<work>/recovery/m7-projection/receipt.json` and its sibling
`m7-lexical-projection.parquet`. The protected production environment must pin
the exact receipt SHA-256 as `ECHOES_M7_PROJECTION_RECEIPT_SHA256`; the launcher
validates and records that nonsecret value. The reuse helper authenticates the
receipt, source manifests/inventory, projection bytes/counts/bindings, and
unchanged reviewed adapter code. Existing complete-stream evidence validation,
candidate selection, and downstream ordering checks remain active.

An absent cache follows the existing build path. A present but invalid cache
fails closed. No corpus, detector, null, threshold, tier, or benchmark policy
changes. No additional infrastructure or monitoring framework is introduced.

## Operational authorization history

The owner also requested removal of manual billing inputs. Before the
subsequent explicit authorization recorded in ADR 0022, automatic approval
review rejected removing the project-owned dollar-cap and verified-cost
refusal twice. The
existing least-privilege Scaleway credential successfully verified the exact
instance but received HTTP 403 from the billing API. No billing figures were
fabricated and no rejected billing patch was deployed or used to launch
production. The instance was powered off.

The owner then explicitly authorized removing dollar ceilings, manual billing
inputs, billing-API prerequisites, and repeated operational approval stops for
this recovery. [ADR 0022](0022-owner-authorized-operational-recovery.md) records
that authorization and the replacement fixed overall 96-hour deadline, which
retries cannot reset. Resource limits, sole-worker checks, exact-instance
shutdown guards, and all scientific validators remain mandatory. The billing
API denial does not grant broader provider permissions.
