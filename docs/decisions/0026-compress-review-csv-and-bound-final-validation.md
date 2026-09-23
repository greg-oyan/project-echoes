# ADR 0026: Compress the complete review CSV and bound final validation

- Status: Accepted for the existing owner-authorized recovery
- Date: 2026-09-23
- executing_agent: Codex

## Context

The ADR 0025 successor completed or authenticated Stages 1–8, but Stage 9
stopped at its measured allocation gate. The complete CSV required
62,674,079,447 bytes. With tier ledgers, metadata and the unchanged 80-GiB
reserve, required free space was 153,069,847,079 bytes; only 138,069,884,928
bytes remained after Parquet. This was a deliberate refusal before CSV writing,
not an out-of-memory event or automatic restart. The temporary review bundle
was removed by the existing exception handler; completed upstream stages and
the outer failed attempt remain preserved.

Audit of the remaining stages also found per-row DuckDB autocommit inserts in
strict validation. A bounded 10,000-row benchmark took 66.838 seconds for the
old path and 1.379 seconds for a typed Arrow batch. Millions of inserts and two
strict validation passes made that avoidable overhead a deadline risk.
An additional 100,000-row probe with realistic candidate-JSON widths reproduced
an out-of-memory failure at a 256-MiB DuckDB limit in the global wide comparison.
That probe motivated bounding JSON hydration during final candidate comparison.

## Decision

Production publishes the complete ledger as `review.csv.gz` alongside
`review.parquet`. Gzip is deterministic (empty filename, zero timestamp,
compression level 1). Decompression must reproduce the exact prior UTF-8 CSV
bytes, including ordering, quoting, newlines and every field. Frozen candidate
identities, scores, tiers, canonical logical digests and dossier selection do
not change. Plain CSV remains supported for bounded fixture callers.

The existing bounded Parquet pass also measures the full deterministic gzip
stream into a counting/hash sink without materializing it. The allocation gate
uses that exact physical byte count, never an estimated compression ratio.
The actual gzip writer must match both compressed and uncompressed byte counts
and SHA-256 values. The review manifest records the encoding and both
identities; artifact inventories authenticate the compressed file itself.

Stage 9 additionally reserves sequential strict-validation scratch:
`max(20 GiB, 6 * candidate_ledger_bytes + 8 GiB)`. For the authenticated
3,422,679,888-byte ledger this is 29,126,013,920 bytes. This conservative planning
allowance covers multiple candidate representations, narrow evidence/null
tables and spill; it is not a mathematical maximum. Both campaign validation
passes and the independent production validator require the allowance plus the
80-GiB floor before starting and inspect remaining space at computation phase
boundaries. There is no monitoring loop. Successful validation removes only its
own temporary database; failed validation preserves its state.

Strict validation inserts bounded, explicitly typed Arrow batches into the
same DuckDB tables, preserving all values and checks. Candidate
comparison sorts narrow keys and hydrates the corresponding JSON in
bounded batches rather than sorting/joining the full JSON population. The
expected values, comparison fields and tolerance remain unchanged. A fresh
per-invocation authentication cache avoids repeatedly hashing the same immutable upstream
artifacts while retaining dependency, input, code and inventory validation.
DuckDB remains at 4 GiB and one thread. Scientific validation may still reject
an invalid result; this decision never converts a failed check to acceptance.

Stage 11 continues direct authenticated object-tree upload and same-filesystem
hardlink staging. It must verify full remote inventories and retain final
all-stage validation, seal and checkpoint receipts. Compression does not waive
any integrity or scientific gate, and no archive or uncompressed full CSV is
materialized for upload.

## Recovery and evidence

The exact successor is
`/srv/project-echoes/final-discovery/work-20260923-review-compressed`, using a
fresh B2 prefix. Import the eight pinned completions from commit
`2e551688dc8f2d624d71c65c0381d72f5ebf51dd` and `work-20260923-review-disk`
through the immutable-payload hardlink contract. New provenance lives under
`checkpoint-reuse/review-compressed-repair-v1`; original provenance, source
completions and failure evidence remain intact. Authenticate reviewed code
compatibility and unchanged Stage 1–8 producers before reuse. Never chmod,
chown, overwrite or delete linked source payloads.

The original deadline remains `2026-09-25T02:46:42Z`; there is no new runtime
window, new paid resource, destructive cleanup, reduced reserve or automatic
retry. Long deployment/import runs detached with logs, PID metadata and a
one-shot status command before launching the sole governed scientific worker.

Require exact compressed CSV round-trip and logical equivalence, deterministic
bytes, corruption/short-write/refusal checks, bounded batches, validator value
and failure preservation tests, authenticated importer and deadline tests, and
the full bounded production-dispatch path through Stage 11. Local fixtures and
compression probes establish software behavior, not production completion or
scientific results. Final acceptance requires the actual authenticated run.
