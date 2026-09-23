# ADR 0024: Bound calibration evidence hydration and reuse six completed stages

- Status: Accepted for the existing owner-authorized recovery
- Date: 2026-09-23
- executing_agent: Codex

## Context

The recovered production campaign completed Stage 6, including authentication
of all 1,248,779 canonical M7 candidates and both retained source null families.
Stage 7 then failed with DuckDB's configured 4-GiB memory limit. The retained
failure record does not identify the SQL statement. A local synthetic
reproduction passed ingestion, validation, normalization and detector null
calibration, then reproduced an out-of-memory error in the calibrated evidence
export: full raw JSON was carried through multiple joins and a global sort.
The local reproduction establishes a concrete defect; it does not establish
the precise statement reached by the previous production attempt.

## Decision

Keep the evidence payload out of the calibration joins and hydrate it in
bounded batches after ordering the narrow calibration results. Retain exact
evidence contents, deterministic ordering, registered normalization, random
seeds, null iterations, scientific thresholds and validation. Keep the existing
4-GiB DuckDB limit, one thread, service resource ceilings and atomic publication
contract. Record the failing calibration phase if an error recurs.

Do not recompute the six authenticated completed stages. A reviewed one-off
importer outside the repository may publish ordinary new StageStore completions
in `/srv/project-echoes/final-discovery/work-20260923-calibration-memory`, with
a fresh B2 prefix. Pin source commit `c94e41df0b4ddbc7e1dcd83c27b7bb2200582d9b`,
all six completion hashes, the exact reviewed source diff, unchanged upstream
producer code, input/configuration/model/runtime identities, original artifact
inventories and all prior provenance. No StageStore identity exception is added.

The importer uses the existing campaign's immutable-artifact hardlink contract
for completed payload files only. New attempts, completion records and reuse
provenance are independent files. It must refuse existing destinations, verify
same-filesystem inode identity and exact hashes, and reauthenticate originals
after import. Source contents, size, permissions and modification time remain
unchanged; adding links necessarily changes inode link count and change time.
Neither the importer nor downstream producers may rewrite completed payloads.
Do not recursively chmod/chown imported files. Existing checkpoint and final
package staging also use hardlinks; per-stage read-only bind mounts are not
introduced because they would break cross-mount hardlink staging.

## Capacity and recovery safeguards

For this exact authenticated six-stage successor, reserve the original modeled
future artifacts excluding only the already-completed canonical M7 and raw
evidence production:

```
139,838,254,692 original modeled bytes
 -18,413,598,540 canonical M7 bytes (already retained)
 -45,119,780,852 pre-Stage-7 raw evidence bytes (already retained)
 =76,304,875,300 additional modeled bytes
 +85,899,345,920 unchanged 80-GiB checkpoint floor
=162,204,221,220 required free bytes after import
```

Keep the complete modeled calibrated outputs, null outputs, group scores,
evidence index, candidate ledger and sort chunks. Failed scratch is already
included in measured occupied space and receives no second credit. Before
import, additionally reserve provenance files and 1 GiB of filesystem metadata
allowance. Hardlink checkpoint/package payload is not charged as another full
copy. The benchmark models persistent outputs, not a guaranteed peak; new
DuckDB scratch and review export overhead consume the remaining headroom.
The existing stage-boundary 80-GiB floor and resource safeguards remain active.
Do not delete evidence, expand the instance or add resources to meet this gate.

The five-stage successor retains its prior gate; other launches retain 280 GiB.
The new successor inherits the existing immutable recovery ledger, with expiry
`2026-09-25T02:46:42Z`. No retry or downtime resets it. Keep the instance off
during local preparation; inspect actual service and checkpoint state before
deployment and never start a duplicate worker. Resume Stage 7, retain its failed
attempt, and verify final results before declaring the campaign complete.

## Validation

Require a low-memory regression exercising the actual wide-evidence export,
exact equivalence to the previous calculation at sufficient memory, focused
calibration/pipeline tests, importer integrity and overwrite refusals, capacity
lineage checks and inherited-deadline tests. Reuse broad passing receipts for
unchanged code and the preserved 1,248,779-row M7 ordering receipt. The repaired
real-data Stage 7 still must complete; local tests are not production results.
