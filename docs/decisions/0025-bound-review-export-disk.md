# ADR 0025: Bound review export disk usage and reuse eight completed stages

- Status: Accepted for the existing owner-authorized recovery
- Date: 2026-09-23
- executing_agent: Codex

## Context

Stages 7 and 8 completed under commit
`94c2a5f105e04494b3bf4591d8a0a0fefea919ef`. Stage 9 then failed with
`OSError: [Errno 28] No space left on device`. The failure record does not
identify the exact write. Its completed M7 hydration index and missing review
bundle are consistent with failure during review construction/publication. The streaming
review writer retained uncompressed canonical JSONL, CSV tier partitions,
combined CSV and Parquet simultaneously. Its exception cleanup explains why a
later snapshot could show substantial free space; that snapshot is not proof
of adequate peak capacity. The earlier benchmark omitted full review exports.

## Decision

Spool only losslessly compressed canonical review partitions. Preserve every
row, field, tier ordering, evidence link, canonical logical digest, and bounded
dossier selection. Write Parquet directly from bounded decoded batches first.
Count the exact UTF-8 CSV bytes from the same record serialization. Before
materializing that CSV, require measured available space for its full size,
the complete Stage 8 candidate ledger as an upper bound for the three tier
ledgers, 1 GiB of metadata allowance, and the unchanged 80 GiB floor. Consume
and remove temporary compressed partitions as the final CSV is written.
Retain the existing atomic bundle publication and failed-attempt recording.

CSV bytes and canonical logical digests must remain identical. Parquet retains
the same logical schema, values and order, but its physical encoding and file
hash may change with the bounded writer. This is an export implementation
change, not a scientific configuration or population change. No dependency,
threshold, model, null calculation, candidate ranking or acceptance test is
relaxed. If the full required output cannot fit, stop with measured byte counts
instead of dropping rows, deleting preserved evidence or expanding resources.

Reuse all eight completed stages through an outside one-off importer into
`/srv/project-echoes/final-discovery/work-20260923-review-disk` and a fresh B2
prefix. Authenticate the source commit and artifact inventory. Pin Stage 8's
completion SHA-256
`fcc0e2a4d10d60c423fcdaf5bb743e1ad6ab176331a1f6d9f3fa7a358a33c686`;
derive the missing Stage 7 completion pin only from that authenticated
dependency graph, then authenticate Stage 7's exact bytes and full artifacts.
Preserve all source completions in new provenance. Require exact reviewed code
compatibility, unchanged Stage 1-8 producer implementations, inputs, models and
configuration. No StageStore authentication exception is introduced.

Payloads use the existing immutable hardlink contract. New provenance and
completion records are independent. Source bytes, ownership, permissions and
mtime remain unchanged; adding links necessarily changes link count and ctime.
Never overwrite destinations, chmod/chown linked payloads, or delete old work.

## Safeguards and validation

Only this exact eight-stage successor receives the authenticated remaining-work
launch reserve. It includes the candidate-ledger size, evidence-index allowance,
metadata and the 80 GiB floor; the review writer additionally gates the actual
measured export allocation. Launch capacity is not a prediction of final output
size. Stage 10's bounded validation scratch and all scientific checks remain
active. Checkpoint and package staging continue to hardlink completed payloads.

The successor inherits the original expiry `2026-09-25T02:46:42Z`. Downtime and
retries cannot reset it. Prepare locally, inspect the real service state before
deployment, and never start a duplicate worker. This repair alone does not
establish production completion.

Require focused CSV/digest equivalence, Parquet logical equality, compressed
partition lifecycle, bounded batch, capacity refusal, importer authentication,
launch lineage and fixed-deadline tests. Reuse prior broad passing validation
and the unchanged 1,248,779-row M7 ordering receipt.
