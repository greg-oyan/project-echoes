# 0017 — Single-node cloud execution exception

- Status: Accepted
- Amendment: 2026-07-30 — CCX33 operational re-parameterization
- Date: 2026-07-30
- executing_agent: Codex
- Owner authorization: The project owner requested safe cloud preparation for
  Milestone 7 after the Windows research laptop exhausted usable memory and was
  force-terminated.

## Context

ADR 0004 correctly rejected a cloud-native platform for Project Echoes. It did
not require every experiment to run on an under-provisioned laptop. The first
Milestone 7 production attempt retained a valid interrupted staging tree and
checkpoints, but approximately 7.3 GB of usable laptop memory made another real
local run unsafe. Repeating that run locally would risk the workstation and the
preserved evidence.

The project needs a narrow operational exception that keeps the existing
single-process Python, DuckDB, Parquet, Polars, and `uv` architecture. It must
not create a cloud database, distributed system, managed research service, or
new publication boundary.

The original decision selected CCX43. CCX43, CCX53, and CCX63 are unavailable
to the owner's Hetzner account, while CCX33 is available. The 2026-07-30
amendment therefore changes only the machine-size, operational-resource, and
cost terms below; every scientific, provenance, validation, transfer,
recovery, retention, and acceptance term remains in force.

## Decision

Milestone 7 production execution moves to one owner-provisioned, ephemeral
Hetzner CCX33 in Hillsboro, Oregon, with Ashburn, Virginia as the allowed
fallback. It runs Ubuntu 24.04 on 8 dedicated AMD vCPUs, 32 GiB RAM, and a
240 GB local SSD, with one public IPv4 address only if required for SSH. Codex
does not purchase, create, connect to, configure, resize, launch, stop, or
destroy this resource.

The first cloud execution resumes
`data/processed/lexical/.schema-v1.writing-238902db1f6e479596bea47e70ccf30b`.
A later second execution starts from fresh lexical staging to test
determinism. The preserved recovery run and the fresh run are distinct
execution attempts.

The cloud host is an execution appliance, not a new storage authority:

- transfer is private, manifest-driven, resumable, and SHA-256 verified;
- restricted sources, the local database, staging, and checkpoints remain
  Git-ignored and are never added to a commit;
- the transfer manifest excludes raw acquisitions and includes reconstructable
  derived MACULA, OSHB, and OpenBible content only under the source-specific
  private-processing determination in `docs/data-licensing.md` and the updated
  source-manifest notes; this does not authorize public derived-table release;
- the frozen scientific configuration and its hashes do not change;
- cloud memory, process, thread, temporary-directory, service, and wall-clock
  controls are execution metadata rather than scoring parameters;
- one systemd service owns the worker independently of SSH, VS Code, Codex,
  and the laptop;
- the service preserves the actual frozen scientific thread count of exactly
  one under a machine-level ceiling of 6 computational threads, a 22 GiB
  (23,622,320,128-byte) DuckDB memory ceiling, `MemoryHigh=26G`,
  `MemoryMax=28G`, `RuntimeMaxSec=48h`, and `Restart=no`;
- launch requires at least 120 GiB (128,849,018,880 bytes) free; the existing
  checkpoint-bound in-process disk guard applies a cloud-only 25 GiB
  (26,843,545,600-byte) runtime floor before and after governed artifact parts,
  at sensitivity spill boundaries, and during finalization;
- crossing the runtime disk floor records the stage and observed free space,
  requests a controlled stop, preserves staging and checkpoints, and remains
  visible in execution state, stderr, and one-shot status output without a
  polling process, timer, monitoring daemon, or second worker;
- start, stop, status, validation, packaging, and transfer are explicit
  one-shot commands; no monitor or polling loop is introduced;
- failures, timeouts, signals, and OOMs preserve staging and checkpoints;
- canonical `schema-v1` promotion requires fail-closed strict technical
  validation of the sealed staging tree; a scientifically incomplete but
  technically valid result is preserved and reported rather than discarded,
  and the milestone acceptance gate still stops;
- a durable promotion journal is written before the filesystem rename and
  retained across the DuckDB exposure transaction; the transaction records a
  unique promotion ID plus exact artifact-manifest and lexical-view-catalog
  identities; recovery keeps canonical only after that complete
  catalog/path/tiny-read witness, otherwise restores the exact staging path,
  while ambiguous state is preserved and rejected;
- active or archived commit evidence preserves recoverable canonical bytes but
  never overrides the requirement for an authenticated successful systemd
  result, and failed provenance is never reclassified;
- no automatic cleanup deletes preserved staging, checkpoints, manifests, or
  result packages.

The transferred DuckDB is portable as a file but its six passage artifact
views persist absolute Windows Parquet paths. Transfer verification therefore
authenticates the original database and full passage tree before any mutation.
Bootstrap then replaces exactly those six views and their eight known
dependent convenience views in one DuckDB transaction, performs bounded
one-row reads, and writes a non-overwriting receipt containing the original
and rebound database hashes, pinned DuckDB version, and resolved Linux globs.
Pre-launch checks authenticate that receipt. Post-run validation expects the
pipeline's lexical load to have changed the database and records its new hash
instead of applying a stale pre-run hash.

Only the owner-verified planning rates supplied for this amendment are used:
CCX33 is USD 0.2660/hour, Primary IPv4 is USD 0.0010/hour, and the combined
rate is USD 0.2670/hour. The formal gross ceilings are USD 12.816 for the
unchanged 48-hour worker cap, USD 19.224 for one 72-hour server lifecycle, and
USD 38.448 for two separately authorized 72-hour lifecycles. The existing
USD 25.00 account credit does not reduce those gross ceilings; estimated
remaining cash exposure is USD 0.00 after one lifecycle and USD 13.448 after
two. Keeping either server after its governed lifecycle is outside this
contract.

`docs/cloud-execution.md` is the execution contract. It records the required
fields for every heavy milestone and blocks future heavy execution when a
machine, resource, cost, checkpoint, abort, output, or retention field has not
been resolved.

## Rationale

A dedicated available single node supplies governed memory and local spill
space without changing the research architecture or introducing distributed
execution.
Systemd supplies one-worker exclusion, OS-level memory and runtime limits, and
execution independence. A file-level transfer manifest and hash verification
make private data movement auditable without creating a second local archive.
Separating operational overrides from the frozen scientific configuration
allows the valid checkpoints to resume under the same experiment identity.

## Consequences

- The real Milestone 7 pipeline must never run on the current Windows laptop
  again.
- Linux portability and the transferred DuckDB are checked on the target host
  before the service can start.
- Cloud execution does not satisfy the Milestone 7 acceptance gate by itself.
  Strict validation, reports, the later fresh determinism run, and the
  master-plan acceptance criteria remain required.
- Remote data remains protected until the owner explicitly authorizes
  download or deletion.
- Future heavy milestones use the contract in
  `docs/cloud-execution.md`; any cloud choice or price is revalidated before
  launch.
- ADR 0004 remains accepted. This decision is a single-node execution
  exception, not a cloud-native architecture change.

## Alternatives considered

- Run the recovery again on the laptop: rejected because the observed memory
  pressure made the workstation unusable.
- Discard staging and start fresh: rejected because valid recovery work and
  checkpoints must be preserved.
- Use a distributed framework, managed database, or Kubernetes: rejected as
  unnecessary and contrary to ADR 0004 and the master plan.
- Copy the data into one local archive before upload: rejected because it
  duplicates the 17 GB staging tree and creates another failure surface.
- Let an interactive SSH or editor session own the worker: rejected because
  disconnection would weaken execution control and provenance.
- CCX43, CCX53, or CCX63: unavailable to the owner's Hetzner account.
