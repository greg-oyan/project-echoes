# 0017 — Single-node cloud execution exception

- Status: Accepted
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

## Decision

Milestone 7 production execution moves to one owner-provisioned, ephemeral
Hetzner CCX43 in Hillsboro (`hil`), running Ubuntu 24.04 on 16 dedicated AMD
vCPUs, 64 GiB RAM, and a 360 GB local SSD. Codex does not purchase, create,
connect to, or launch this resource.

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
- the service uses at most 12 computational threads, a 48 GiB DuckDB memory
  ceiling, `MemoryHigh=50G`, `MemoryMax=56G`, `RuntimeMaxSec=48h`, and
  `Restart=no`;
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

The current price ceiling is provisional and must be checked again before
ordering. At the official 2026-07-30 US CCX43 rate of USD 0.5280/hour plus USD
0.0010/hour for a Primary IPv4, the governed 72-hour end-to-end lifecycle
ceiling is USD 38.09 before tax and USD 50 all-in. The worker itself remains
hard-capped at 48 hours. The recovery and fresh determinism runs are separate
authorized lifecycles, for a two-run ceiling of USD 76.18 before tax and USD
100 all-in. Keeping either server after its governed lifecycle is outside this
contract.

`docs/cloud-execution.md` is the execution contract. It records the required
fields for every heavy milestone and blocks future heavy execution when a
machine, resource, cost, checkpoint, abort, output, or retention field has not
been resolved.

## Rationale

A dedicated single node supplies enough memory and local spill space without
changing the research architecture or introducing distributed execution.
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
