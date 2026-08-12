# Heavy-execution contract

Status: active for Milestone 7 cloud preparation on 2026-07-30.

This contract governs resource-intensive Project Echoes work. It does not
authorize anyone or any agent to purchase, create, connect to, start, stop, or
delete cloud resources. The owner performs those actions. The master plan and
milestone acceptance gates remain authoritative.

## Contract rules

Every heavy execution records all of these fields before launch:

1. executor and single-worker ownership;
2. exact machine specification and operating system;
3. process and DuckDB memory limits;
4. computational thread limit;
5. minimum free local disk;
6. hard wall-clock limit;
7. maximum expected external-compute cost;
8. checkpoint boundary or interval;
9. one-shot status command;
10. abort conditions;
11. required outputs and validations;
12. cleanup and retention rules.

An unresolved field blocks a heavy run. Runtime and cost estimates are
provisional until measured on the named machine. A new measurement updates the
contract; it does not silently relax the ceiling. Commands expected to exceed
ten minutes run detached with logs, PID and environment metadata, checkpoints,
and a one-shot status command. A status command inspects once and exits. Polling
and sleep loops are prohibited.

Milestones 2–7, 9–13, 15, and 16 are heavy. Milestones 0, 1, 8, and 14 are
lightweight or human-led; their bounded time budgets remain in the master plan.

## Milestone planning matrix

The completed Milestones 2–6 retain their historical manifests and measured
evidence. Their rows are planning ceilings for a future rerun, not retroactive
claims about old hardware. A future rerun of those milestones is blocked until
the owner records an exact host and one-shot status command. Every later
milestone is likewise blocked while any cell says `unresolved`. An unresolved
value is a fail-closed contract value, not permission to improvise.

| Milestone | Executor and machine | Memory / threads / disk | Wall clock and cost | Checkpoint and one-shot status |
| --- | --- | --- | --- | --- |
| 2 Hebrew ingestion | Exact future-rerun host unresolved; no rerun authorized | Planning ceiling: 12 GiB process, 4 threads, 50 GB free | 12 h/run; external cost authorization USD 0 | Per source book plus atomic database transaction; exact status command unresolved |
| 3 Greek ingestion | Exact future-rerun host unresolved; no rerun authorized | Planning ceiling: 12 GiB process, 4 threads, 50 GB free | 8 h/run; external cost authorization USD 0 | Per source book plus atomic database transaction; exact status command unresolved |
| 4 supplementary annotations | Exact future-rerun host unresolved; no rerun authorized | Planning ceiling: 16 GiB process, 4 threads, 75 GB free | 12 h/run; external cost authorization USD 0 | Per source/artifact boundary; exact status command unresolved |
| 5 passage segmentation | Exact future-rerun host unresolved; no rerun authorized | Planning ceiling: 16 GiB process, 4 threads, 100 GB free | 8 h/run; external cost authorization USD 0 | Per table/partition boundary; exact status command unresolved |
| 6 known-link benchmark | Exact future-rerun host unresolved; no rerun authorized | Planning ceiling: 12 GiB process, 4 threads, 50 GB free | 2 h/run; external cost authorization USD 0 | Per benchmark table boundary; exact status command unresolved |
| 7 lexical baseline | Owner-provisioned Hetzner CCX33, Hillsboro primary and Ashburn fallback, Ubuntu 24.04, 8 dedicated AMD vCPUs, 32 GiB RAM, 240 GB SSD; systemd sole worker | DuckDB 22 GiB, `MemoryHigh=26G`, `MemoryMax=28G`, one frozen thread (hard ceiling 6), at least 120 GiB free before launch and checkpoint-bound safe stop below 25 GiB | Per run: 48 h worker, 72 h lifecycle; formal gross USD 12.816/worker and USD 19.224/lifecycle; two lifecycles USD 38.448; USD 25.00 credit is separate, leaving USD 0.00/13.448 estimated exposure | Every primary/Tier 3 checkpoint and governed artifact part; `sudo bash /srv/project-echoes/repo/cloud/cloud_status.sh` |
| 9 Septuagint bridge | Single worker on a machine selected after source activation; no cloud run authorized yet | Planning ceiling 48 GiB, 12 threads, 250 GB free | 24 h/run; external cost cap unresolved, therefore USD 0 authorized | Per source/alignment partition; milestone-specific one-shot status command required before launch |
| 10 semantic retrieval | Single worker; exact CPU/GPU host selected after registered fixture benchmark; no cloud run authorized yet | Planning ceiling 64 GiB host RAM, 12 CPU threads, 250 GB free; GPU limit unresolved | 24 h/benchmark and 72 h total; external cost cap unresolved, therefore USD 0 authorized | Per representation/evaluation split; milestone-specific one-shot status command required |
| 11 syntactic and narrative engines | Single worker; exact host selected after fixture benchmark; no cloud run authorized yet | Planning ceiling 64 GiB, 12 threads, 250 GB free | 24 h/run and 72 h total; external cost cap unresolved, therefore USD 0 authorized | Per representation/book partition; milestone-specific one-shot status command required |
| 12 anomaly and structural engines | Single worker; exact host selected after fixture benchmark; no cloud run authorized yet | Planning ceiling 64 GiB, 12 threads, 250 GB free | 24 h/run and 72 h total; external cost cap unresolved, therefore USD 0 authorized | Per randomized replicate and analysis partition; milestone-specific one-shot status command required |
| 13 candidate ensemble | Single worker; exact host selected after fixture benchmark; no cloud run authorized yet | Planning ceiling 64 GiB, 12 threads, 250 GB free | 24 h/run; external cost cap unresolved, therefore USD 0 authorized | Per detector-family/score partition; milestone-specific one-shot status command required |
| 15 Pauline case study | Single worker; exact host selected after fixture benchmark; no cloud run authorized yet | Planning ceiling 64 GiB, 12 threads, 250 GB free | 24 h/run and 96 h total; external cost cap unresolved, therefore USD 0 authorized | Per registered comparison and dossier input; milestone-specific one-shot status command required |
| 16 whole-canon run | Single worker; exact host selected after prior milestone measurements; no cloud run authorized yet | Planning ceiling 64 GiB, 12 threads, 300 GB free | 48 h/run; external cost cap unresolved, therefore USD 0 authorized | Per detector family, null replicate, and candidate partition; milestone-specific one-shot status command required |

Rows with unresolved machine, cost, or status details authorize no heavy
execution, paid or local. Before those milestones launch, replace the planning
ceiling with an exact host, current price and all-in cap, lifecycle cap, status
command, and measured fixture evidence through normal change control.

The remaining contract fields are milestone-specific as follows. “Required
outputs” means the applicable master-plan acceptance artifacts plus the listed
execution evidence; it does not weaken any acceptance item.

| Milestone | Abort conditions | Required outputs and validation | Cleanup and retention |
| --- | --- | --- | --- |
| 2 | Source/hash/schema drift, duplicate worker, resource ceiling, nonzero exit, or strict validation failure | Hebrew token/provenance tables, issues, manifest, deterministic hashes, and two accepted builds | Preserve acquisition receipt, source manifest, database, reports, and accepted hashes; delete only positively identified spill with owner approval |
| 3 | The Milestone 2 conditions plus edition/versification drift | Greek token/provenance tables, issues, manifest, deterministic hashes, and two accepted builds | Same governed retention as Milestone 2 |
| 4 | Unapproved source activation, upstream-anchor drift, join loss, duplicate annotation, resource ceiling, or validation failure | Supplementary tables, provenance, coverage/issues report, manifest, and deterministic hashes | Preserve source receipts, activated artifacts, manifests, reports, and accepted output |
| 5 | Upstream-anchor drift, missing/duplicate partition, invalid passage membership, resource ceiling, or validation failure | Six passage relations, metadata, `table-hashes.json`, reports, and two matching logical builds | Preserve both accepted hash manifests, passage artifacts, database, reports, and source anchors |
| 6 | License/identity/leakage/mapping drift, resource ceiling, nonzero exit, or validation failure | Governed benchmark tables, metadata, `table-hashes.json`, reports, and two matching logical builds | Preserve source receipt, normalized benchmark, database, manifests, reports, and both acceptance hashes |
| 7 | The detailed Milestone 7 abort list below | Canonical lexical artifacts, database exposure, launch record, execution manifest, strict validation, packages/manifests, and fresh-run logical reproduction | Preserve recovery and fresh staging/checkpoints, logs, receipts, manifests, canonical outputs, and packages until explicit owner authorization |
| 9 | Unapproved Septuagint edition/license, versification ambiguity, anchor drift, resource ceiling, or validation failure | Governed bridge alignments, mappings, provenance, evaluation, issues, manifest, and deterministic rerun | Preserve approved source receipt, crosswalk, alignments, reports, manifests, and both run hashes |
| 10 | Unregistered representation, benchmark regression, leakage, resource ceiling, cost ceiling, or validation failure | Registered representations, retrieval outputs, benchmark comparison, provenance, configuration, and manifest | Preserve models/versions, representation artifacts, benchmark outputs, rejected experiments, and manifests |
| 11 | Invalid representation, narrative/syntactic trace loss, benchmark regression, resource ceiling, or validation failure | Syntactic/narrative features, detector outputs, evaluation, provenance, and manifest | Preserve governed features, accepted/rejected outputs, reports, and manifests |
| 12 | Invalid randomization, uncalibrated null, structural leakage, resource ceiling, or validation failure | Anomaly/structural scores, null distributions, calibration/evaluation, provenance, and manifest | Preserve seeds, randomized-run manifests, distributions, outputs, and reports |
| 13 | Missing detector trace, unregistered ensemble, calibration failure, resource ceiling, or validation failure | Traceable ensemble scores, ranked candidates, calibration, evaluation, provenance, and manifest | Preserve component and ensemble outputs, accepted/rejected candidates, reports, and manifests |
| 15 | Preregistration/holdout violation, source drift, resource/cost ceiling, or validation failure | Registered Pauline case-study artifacts, dossiers, sensitivity analysis, provenance, and manifest | Preserve preregistration, all accepted/rejected cases, artifacts, reports, and manifests |
| 16 | Any prior gate unmet, whole-canon incompleteness, source/config drift, resource/cost ceiling, or validation failure | Complete whole-canon outputs, deterministic rerun, final validations, manifests, and publication-ready evidence | Permanently retain governed final hashes/manifests and preserve source-governed artifacts until an explicit archival decision |

## Milestone 7 execution contract

### Executor and machine

- Owner-created Hetzner Cloud server type: `CCX33`
- Primary location: Hillsboro, Oregon, USA
- Allowed fallback location: Ashburn, Virginia, USA
- Image: Ubuntu 24.04 LTS, x86_64
- Compute: 8 dedicated AMD vCPUs
- Memory: 32 GiB
- Local storage: 240 GB SSD
- Worker owner: `echoes-m7.service`; exactly one active worker
- Interactive SSH, VS Code, Codex, and the laptop are not worker owners

The owner-verified CCX33 planning rate is USD 0.2660/hour. A Primary IPv4, if
required for SSH, is planned at USD 0.0010/hour, for a combined rate of USD
0.2670/hour. The gross 48-hour worker ceiling is USD 0.2670 × 48 =
USD 12.8160 (formal gross USD 12.816). The gross 72-hour lifecycle ceiling is
USD 0.2670 × 72 = USD 19.2240 (formal gross USD 19.224). The recovery and later
fresh run remain separately authorized; their combined gross ceiling is USD
0.2670 × 144 = USD 38.4480 (formal gross USD 38.448). The existing USD 25.00
account credit does not reduce these formal gross ceilings. Estimated remaining
cash exposure is USD 0.00 after one lifecycle and USD 13.448 after two.

### Limits and checkpoints

- The service is `Restart=no`, `RuntimeMaxSec=48h`, `MemoryHigh=26G`, and
  `MemoryMax=28G`.
- The process guard ceiling is 28 GiB.
- Every governed DuckDB pipeline connection receives a 22 GiB memory limit.
- Computational libraries and DuckDB use exactly the frozen scientific
  setting of one thread, which remains below the machine-level ceiling of 6.
- DuckDB spill is confined to a dedicated directory on the server's local SSD.
- Launch requires at least 120 GiB free on the filesystem holding repository
  data and spill.
- During execution, the existing checkpoint-bound in-process guard requests a
  safe stop below 25 GiB free. It records the failing stage and observed space
  in execution state and logs while preserving staging, checkpoints, and
  recovery state; it introduces no polling loop, timer, or monitoring daemon.
- Existing primary, Tier 3, candidate, artifact, execution-manifest, and
  progress checkpoints are retained.
- Checkpoints occur at existing governed part boundaries; no time-only
  checkpoint is claimed where the implementation has none.
- The transfer verifier authenticates the original database and full passage
  tree first. Bootstrap then transactionally replaces exactly the six
  Windows-bound passage artifact views and their eight known dependent views,
  records original and rebound database hashes plus the pinned DuckDB version
  and resolved Linux globs in an atomic receipt, and performs at most one-row
  reads through every rebound artifact view.
- The scoped transfer-manifest acceptance requirement is: “All database,
  corpus, staging, checkpoint, generated-data, execution-manifest,
  scientific-configuration, and final-output manifest entries remain
  unchanged. Only entries for scoped tracked code, documentation,
  configuration, tests, and cloud tooling may be refreshed.” Passage-artifact
  entries are protected and remain unchanged as well.
- Bootstrap, service installation, and pre-launch checks require the current
  rebound database hash to match that receipt. The successful pipeline later
  changes the database when it installs lexical views, so post-run validation
  authenticates the receipt chain and current catalog and records a new
  database hash rather than incorrectly requiring the pre-run hash.
- Strict artifact validation durably writes
  `data/processed/lexical/.schema-v1.promotion-intent.json` before the
  staging-to-canonical rename. The journal covers the subsequent DuckDB
  transaction. That transaction writes a unique promotion ID, the exact
  `table-hashes.json` identity, and the exact governed lexical-view catalog
  hash as its commit witness. Before any resumed launch, a bounded recovery
  command verifies those identities, catalog paths, the complete lexical-view
  set, and at-most-one-row reads. It retains canonical only for a wholly
  committed exposure, restores the same tree to the recorded staging path
  when exposure did not commit, and preserves/rejects any ambiguous state.
  Active and archived witnesses make validation/finalization retries
  idempotent, but they never override the unconditional requirement that the
  authenticated systemd `Result` equal `success`.

### Abort conditions

The bootstrap, verifier, installer, or service refuses or aborts when any of
these conditions applies:

- branch or commit differs from the operator-supplied expected commit;
- a required transfer path, size, or SHA-256 differs;
- the pinned Python or DuckDB version is unavailable or the database cannot be
  opened read-only with a bounded metadata query;
- free disk is below 120 GiB at bootstrap or launch;
- more than one matching worker exists;
- canonical `data/processed/lexical/schema-v1` already exists when a resume
  launch is requested, except that a matching durable promotion journal is
  resolved first and a wholly committed run is directed to validation rather
  than relaunched;
- the governed staging directory is missing, symlinked, outside its expected
  parent, or inconsistent with its checkpoint manifests;
- memory or runtime limits are exceeded, the kernel OOM-kills the service, or
  the worker exits nonzero;
- execution free disk crosses below the 25 GiB safe-stop floor;
- staging loses required parts, a checkpoint hash differs, a partition is
  missing or duplicated, or Parquet metadata is unreadable;
- strict post-run validation fails.

An abort never promotes a technically invalid result, never deletes staging,
and never restarts automatically. A scientifically incomplete but technically
valid negative result is promoted for reporting, then stops the milestone gate
without tuning or advancing. A signal, timeout, OOM, or nonzero exit remains
gate-blocking even if it occurs after an atomic DuckDB commit; the committed
bytes and journal are preserved for diagnosis, and a failed execution manifest
is never reclassified as successful.

### Required outputs and validation

The recovery run must produce:

- a successful experiment execution manifest containing command, commit,
  runtime environment, start/end time, seeds, inputs, and output hashes;
- an immutable systemd launch record containing the service unit, PID, commit,
  exact environment, start time, and process/cgroup limits;
- timestamped stdout and stderr logs;
- complete governed lexical Parquet artifacts and sparse indexes;
- `table-hashes.json` and one `lexical_metadata` row;
- canonical DuckDB lexical views bound to the same run;
- strict validation JSON with no missing or duplicate parts and readable
  Parquet metadata;
- benchmark recovery, empirical-null, calibration, ablation, sensitivity,
  candidate-evidence, issue, and report prerequisites required by Milestone 7;
- a small review package and a protected full-result package or manifest.

The first run resumes preserved work. A later separately authorized fresh run
must preserve the first run's result, deliberately use the governed `--force`
replacement path with a new staging directory, and compare logical outputs for
determinism. An active interrupted journal always blocks that fresh path; only
a sealed prior commit is eligible. Milestone 7 remains open until both runs and
every master-plan acceptance item pass.

### Cleanup and retention

- Never automatically delete the transferred database, source manifests,
  preserved staging, checkpoints, execution manifests, validation reports,
  logs, durable promotion journal, or result packages.
- Temporary DuckDB spill may be removed only when it is positively identified
  as an execution-owned spill directory and no worker uses it. The service
  itself does not delete preserved research state.
- Keep the complete remote result protected until the owner verifies the
  downloaded review package and explicitly authorizes any cleanup.
- Never add the database, source data, staging, checkpoints, or result packages
  to Git.
- Server deletion and remote-data destruction are owner actions outside this
  repository contract.
- The owner completes verified retrieval and an explicit deletion decision
  within each 72-hour lifecycle or stops before the cap and records a new
  authorization. No provider snapshot, image, or backup is created.

### Private-processing boundary

This run transfers only the derived files named by the allowlist; raw MACULA,
OSHB, and OpenBible acquisitions are excluded. The activated inputs all have
completed license review and `machine_processing_status: permitted`. For this
run, “local-only” means nonpublic, owner-controlled research storage rather
than a particular chassis: SFTP/SSH host-key verification, key-only access,
restrictive server permissions, no web service, no provider snapshot or
backup, no public bucket, no Git tracking, and explicit owner-controlled
deletion preserve that boundary. This is private computation, not permission
to publish or redistribute reconstructable processed tables. The
source-specific determinations and attribution obligations remain binding in
`docs/data-licensing.md` and `data/manifests/sources.yaml`.
