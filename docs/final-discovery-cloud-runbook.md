# `final-discovery-v1` recovery cloud runbook

The current recovery is governed by
[ADR 0026](decisions/0026-compress-review-csv-and-bound-final-validation.md).
The plain CSV allocation exceeded available capacity by 13.97 GiB. Production
now emits deterministic `review.csv.gz` whose decompression reproduces the
complete exact CSV, together with Parquet. Stage 9 measures full compressed
size and reserves tier outputs, validation scratch and the 80-GiB floor.
The new exact successor `work-20260923-review-compressed` reuses eight
authenticated stages from `work-20260923-review-disk` with fresh provenance and
B2 prefix. Strict validation uses bounded bulk inserts and phase-boundary
capacity checks. Stages 10 and post-11 validation run sequentially; packaging
and checkpoints use same-filesystem hardlinks. Full remote verification and
all final receipts remain mandatory. Long setup/import runs detached; use its
one-shot status command and never launch a duplicate worker. The original
`2026-09-25T02:46:42Z` deadline and preservation rules remain unchanged.

The earlier ADR 0025 path below remains historical provenance.

The current Stage 9 disk repair is governed by
[ADR 0025](decisions/0025-bound-review-export-disk.md). Stages 1-8 completed;
Stage 9 failed with ENOSPC. Prepare locally before restarting. The successor
`/srv/project-echoes/final-discovery/work-20260923-review-disk` reuses all eight
authenticated completions from `work-20260923-calibration-memory` through the
same immutable-payload hardlink contract and independent new provenance.
Use a fresh B2 prefix and resume Stage 9, preserving all prior work.

The review writer replaces simultaneous full CSV/JSONL temporary copies with
compressed canonical partitions. It writes bounded Parquet first, measures the
exact CSV allocation, and requires that allocation plus the remaining tier
ledgers, metadata and unchanged 80-GiB reserve before writing the CSV. All
records, scientific decisions, CSV bytes and logical digests are retained;
Parquet physical encoding may differ. The eight-stage launch gate authenticates
all reuse provenance and reserves the known remaining ledger/index allocation
plus the floor. It does not claim to predict the full review size. A measured
capacity failure must report its byte counts without deleting evidence or
expanding resources. No final result is established by this local repair.

Before deploying, inspect the actual service and refuse a second worker.
The original expiry remains `2026-09-25T02:46:42Z`; no new window is installed.
The earlier recovery descriptions below remain provenance for existing paths.

The 2026-09-23 Stage 7 memory repair is governed by
[ADR 0024](decisions/0024-bounded-calibration-evidence-hydration.md).
Prepare it locally while the owner keeps the instance off. Its exact successor
`/srv/project-echoes/final-discovery/work-20260923-calibration-memory` imports
the six pinned completed stages from the September 22 successor, using immutable
payload hardlinks and independent new completion/provenance records. Reverify
source contents after import; do not rewrite or chmod/chown linked payloads.
Use a fresh B2 prefix and resume Stage 7. Preserve all failed attempts.

After authenticating all six source/current completions and their exact reviewed
code compatibility, this successor requires 162,204,221,220 free bytes: the
76,304,875,300-byte remaining persistent-artifact model plus the unchanged
80-GiB floor. Pre-import preparation also reserves provenance and 1 GiB for
metadata. The estimate excludes future scratch/review overhead and is not a
peak guarantee. Hardlinked checkpoint/package payloads do not duplicate storage.
All other capacity cases retain their existing requirements. Keep DuckDB at
4 GiB/one thread, service ceilings, sole-worker checks and fixed expiry
`2026-09-25T02:46:42Z`. A new work directory does not grant a new runtime window.
The previous Stage 6 passed real-data source authentication; the new Stage 7
repair must still pass production before final results can be claimed.

Status: existing campaign recovery authorized on 2026-09-20; recovery changes
are being prepared locally with the instance powered off.

The current authorization is recorded in
[ADR 0022](decisions/0022-owner-authorized-operational-recovery.md), with
authenticated artifact reuse governed by
[ADR 0021](decisions/0021-authenticated-final-discovery-recovery.md). It permits
necessary repairs, reuse, monitoring, and verified delivery of the existing
campaign. It removes dollar ceilings, manual verified-cost inputs,
billing-API prerequisites, and repeated operational approval stops. Actual
provider permissions, protected credentials, scientific validation, and
preservation of evidence remain mandatory.

Use only the existing Scaleway instance `project-echoes-final-discovery`,
zone `nl-ams-1`, currently identified by public IPv4 `51.15.74.158`. Provider
operations must authenticate its exact instance ID through the protected
shutdown guard; the name or IP alone is insufficient. Do not create a new
server, resize it, attach paid resources, or delete the instance or evidence.
Finish local changes and validation before requesting power-on. Authorized
terminal and expiry actions are evidence-preserving poweroff.

The launcher starts one detached systemd worker, records one immediate startup
inspection, and exits. The engineer may then make repeated bounded status
inspections, diagnose failures, and complete authorized repairs through
verified delivery. Startup inspection is not the end of the recovery task.
Use the fixed overall deadline below; neither retries nor monitoring create a
fresh execution window.

## Frozen execution contract

| Field | Required value |
| --- | --- |
| Experiment | `final-discovery-v1` |
| Host | existing exact-ID Scaleway instance above; retain the governed resource envelope |
| Operating system | Ubuntu 24.04 LTS, x86-64 |
| Compute | 16 dedicated AMD vCPUs; campaign ceiling 12 CPU threads |
| Memory | 64 GB advertised host RAM; cgroup `MemoryMax=56G`, `MemoryHigh=54G`, swap disabled |
| Local SSD | 360 GB advertised; at least 280 GiB free at launch |
| Disk abort floor | 80 GiB, checked at campaign checkpoint boundaries rather than by a monitor |
| DuckDB | 40 GiB host/service ceiling |
| Runtime | one persistent overall 96-hour window; each `RuntimeMaxSec` is remaining seconds; `Restart=no` |
| Worker owner | exactly one `echoes-final-discovery.service` |
| M7 input | B2 `project-echoes-archive/m7/canonical-schema-v1` |
| M7 manifest SHA-256 | `e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6` |
| Authorization | exact `ECHOES_AUTHORIZE_PRODUCTION=final-discovery-v1` |
| Billing | no dollar ceiling, manual verified-cost input, or billing-API gate for this recovery |
| Persistence | same-filesystem hardlink staging and direct authenticated object trees; no stage or final archive |

The 40 GiB DuckDB and 12-thread values are ceilings for this machine and
service, not claims about resource consumption. The authenticated M7
projection deliberately retains its stricter built-in bound of 1 GiB and one
DuckDB thread. Other numerical and sparse operations may use up to the
12-thread service ceiling. The model is CPU-only; no GPU host or CUDA package
is part of this run.

The original CCX43 sizing/pricing references are historical planning context,
not authority to provision a Hetzner host or substitute a provider target.
Measured host checks and the protected exact-instance binding still apply.

The stage runner applies the 80 GiB value as its production checkpoint floor
and checks free space before entering each durable stage (therefore between
completed stages as well). Crossing the floor fails the campaign before the
next stage and preserves completed stages, failed attempts, and staging. There
is no timer, daemon, sleep loop, or continuously running disk monitor.

### Measured preproduction resource gate

The canonical clean-commit, text-free medium benchmark completed in 51.834
seconds on the development laptop. Its 1,000-pair disk sample covered all nine
detectors, 9,000 evidence rows, 32 strata, four external-sort chunks, both final-null
scopes, and review-index lookup. Direct 100,000-score measurements ran each
registered null kernel for the full 1,000 iterations. Detector calibration
took 15.744 seconds; permutation-like and bootstrap kernels took 6.242 and
2.157 seconds. No source text, model, network, or cloud resource was used.

The projection is tied to the campaign scale contract rather than nine rows
for every pair: at most 2,592,480 retained pairs, 11,718,699 evidence rows,
6,633 pair strata, 59,697 detector-strata, 10.123211 billion permutation-like
cells, and 1.595488 billion bootstrap cells. Each production stage is counted
once. A 1.25-safety-factor projection of measured work is 32.600 hours. A
separate 32-hour reserve covers unbenchmarked representation and detector
feature extraction (16 hours), B2 materialization/upload/verification (8
hours), and strict validation/packaging/review artifacts (8 hours). The
planning range is 32.600--64.600 hours, leaving 31.400 hours below the frozen
96-hour stop. These are preproduction planning measurements, not a renewed
time allowance for recovery. Reuse of authenticated completed stages avoids
repeating their expensive work; all remaining work must fit the single fixed
recovery window.

Projected persistent benchmark artifacts are 121,424,656,152 bytes (113.086
GiB); adding the 17.149-GiB canonical M7 input gives 139,838,254,692 bytes
(130.235 GiB). Starting with 280 GiB free leaves approximately 149.765 GiB,
above the 80-GiB floor. The modeled minimum initial free space including that
floor is 225,737,600,612 bytes (210.235 GiB). This estimate excludes source
text and model downloads by design and is not permission to reduce the launch
or checkpoint disk gates. The exact authenticated successor exception below
is a separately recorded recovery decision under ADR 0023.

For `/srv/project-echoes/final-discovery/work-20260922-m7-null-recovery`
only, the launcher first authenticates all five imported completed stages,
their original source completion pins and reuse provenance, and the repaired
code/configuration identity. It then requires 225,737,600,612 bytes free:
the **entire** 139,838,254,692-byte model above as additional future reserve,
plus the unchanged 80-GiB floor. No completed-artifact bytes are subtracted
from that reserve. This is conservative planning, not a measured peak-space
guarantee. Existing stage-boundary disk checks and all runtime/memory limits
still apply. The initial 280-GiB requirement remains for every other launch.
The launch intent records the effective byte requirement and proof basis.
The one-off importer must additionally precheck exact independent-copy sizes,
extra provenance and 1 GiB for filesystem overhead before copying anything.
An actual capacity failure requires stopping with preserved evidence; no
deletion, instance upgrade or extra storage is implied.

Schema 2 records the measured process peak RSS against the registered
`MemoryMax=56G` ceiling; the canonical measurement observed 260,739,072 bytes.
It fails closed if the measurement is unavailable or exceeds that limit. The
benchmark report is preserved for diagnosis, but its command exits nonzero
unless runtime, memory, disk, and exact cardinality all pass.

The authoritative benchmark at
`outputs/reports/final-discovery-preproduction-benchmark.json` was generated
outside the repository from its recorded clean commit. Its `report_status`
must remain `commit_bound_clean`; retain its original commit, code/config
hashes, resource gates, and file SHA-256 together. A dirty-tree development
report is provisional evidence only and cannot authorize launch. The
canonical report is bound to commit
`e0a48cfad963b709dd70e8f8df46ab4d18aed03e` and has SHA-256
`2e5102d8c5c85da225f7a9e53e0a25627ff4ef7c74ccc1630153775fc7124175`.

For this recovery, reuse that original committed passing report after
confirming the registered benchmark kernels, cardinality contract, and
configuration remain unchanged. The Stage 3 authenticated-projection reuse
and Stage 11 provenance-packaging changes do not rerun or alter those
benchmark kernels. Preserve the report's original generation identity; do
not relabel it with the recovery commit or claim a new measurement. The
frozen runtime, memory, disk, and cardinality checks still apply. A changed
benchmark kernel, cardinality contract, configuration, or report byte
invalidates this reuse proof.

## Fixed overall recovery deadline

The first recorded recovery boot was `2026-09-21T02:46:42Z`, retained in the
local `initial-diagnostic.txt` evidence. That diagnostic boot counts. Use
`START_UTC=2026-09-21T02:46:42Z` and the fixed deadline
`2026-09-25T02:46:42Z`, exactly 96 hours later. The window includes
installation, repairs, retries, downtime, and finalization. The next power-on
cannot choose a later start. Do not power on until the local recovery changes
and shutdown safeguards are ready.

After access to the exact existing instance is established, install the same
window using the authorized campaign work directory:

```bash
START_UTC=2026-09-21T02:46:42Z
sudo bash /srv/project-echoes/repo/cloud/final_discovery_recovery_window.sh \
  --install "$START_UTC" "$RECOVERY_WORK_DIR"
```

The root-owned immutable record is
`/var/lib/project-echoes/final-discovery/recovery-window.json`. It binds the
start, fixed deadline, recovery work directory, and exact instance. An existing
record must match; it cannot be replaced to renew time. The protected launch
environment must name the same recovery work directory. The launcher reads
the remaining seconds and uses only those seconds for `RuntimeMaxSec`:

```bash
sudo bash /srv/project-echoes/repo/cloud/final_discovery_recovery_window.sh \
  --remaining "$RECOVERY_WORK_DIR"
```

A persistent native systemd expiry timer uses the absolute deadline plus a
boot check. Its bounded expiry service calls the existing exact-instance
poweroff service only when the deadline has expired, including between worker
attempts. No monitoring daemon is needed. Missing, inconsistent, or expired
window state blocks launch. Do not reset, extend, or reinstall a different
window after a failure. A fresh worker is not a fresh 96-hour allowance.

The existing service success action powers off after the worker's all-stage
validation and durable B2 verification. An unrecoverable terminal failure or
deadline expiry also requires poweroff. A recoverable worker failure can be
diagnosed and retried within the remaining window; it does not itself trigger
an automatic restart or renew time. Preserve all disks and artifacts.

No verified rate, accrued-cost declaration, B2 reserve, dollar ceiling, or
billing-API access is required. Do not fabricate cost data or broaden
credentials after a billing denial. This changes the operational gate only;
resource limits, exact-target authorization, and scientific validation remain.

## Recovery preparation

1. Retain the exact existing instance above. Verify its identity and existing
   resource envelope; do not provision or attach a volume, snapshot, backup,
   GPU, database, or other service. Keep it powered off until local preparation
   and validation are complete. Retain the already-recorded first recovery
   boot and fixed expiry; the next power-on cannot reset them.
2. Verify the existing unprivileged `echoes` service account. Keep SSH key-only
   and do not expose an application or web service.
3. Place the reviewed repository at `/srv/project-echoes/repo` on the exact
   commit recorded in the protected environment. The tree must be completely
   clean, including untracked files. Inputs, work products, models, credentials,
   and local research databases remain outside the Git tree. Keep the stage
   store, checkpoint workspaces, and final package staging on the same local
   filesystem: checkpointing fails closed rather than copying payload bytes if
   a hardlink cannot be created.
4. Verify `uv`, `rclone`, Git, Python 3.12, and the locked project environment,
   including the non-default `models` dependency group. The service command
   uses `uv run --frozen --no-sync`, so launch cannot resolve or install a
   dependency.
5. Authenticate the nine existing allowed files for
   `intfloat/multilingual-e5-small` revision
   `614241f622f53c4eeff9890bdc4f31cfecc418b3` under the offline model root.
   Do not place a floating Hugging Face cache there. The launch preflight
   verifies every registered file and SHA-256 with network model access
   disabled.
6. Authenticate the existing governed prepared-passage JSONL and bidirectional
   knownness JSONL at the paths declared in the environment. Require the
   authenticated knownness receipt beside the JSONL using the fixed
   `<stem>.receipt.json` name. The launcher checks both files before starting
   the worker. Verify all transfer receipts before launch. Do not transfer raw
   restricted acquisitions.
7. Use the existing least-privilege Backblaze application key capable of reading
   the frozen M7 prefix and writing/checking only the output identity already
   authorized for this campaign. The launcher must inspect the complete
   namespace and accept only an empty or authenticated resumable state; a
   mismatched namespace must fail closed. Preserved earlier campaign
   namespaces remain protected.
8. Prepare `/etc/project-echoes/final-discovery.env` using the current
   [`environment contract`](../cloud/final-discovery.env.example), preserving
   protected credentials and recording the reviewed recovery commit and the
   work directory/output identity already authorized for this campaign.
   These identities are protected environment inputs; this procedure does
   not grant permission to select or reuse another namespace. No `OWNER_SET`
   placeholder may remain. Protect it:

   ```bash
   sudo chown root:root /etc/project-echoes/final-discovery.env
   sudo chmod 600 /etc/project-echoes/final-discovery.env
   ```

For recovery, preserve the earlier work directories and output namespaces.
Use the work directory and output identity already authorized for this
campaign. Require the launcher's complete namespace inspection and fail
closed on any state that is neither empty nor authenticated for resumption.
These checks do not authorize reuse of a protected earlier namespace.
Authenticate imported Stage 1/2 artifacts under ADR 0021, including original
completion bytes and provenance; do not copy old completion identities into
place. A cached M7 projection is usable only with its pinned original passing
receipt SHA-256 and complete source/projection authentication. Reuse never
bypasses the ordinary downstream validators. Install the fixed recovery window
and expiry guard before launching the worker.

The populated environment is a secret and must never enter Git, shell history,
chat, logs, launch arguments, or a result package. The launch record retains
the exact nonsecret environment and records only that each B2 secret was
present. The service receives credentials through its protected
`EnvironmentFile`; the B2 adapter creates its ephemeral rclone configuration
from those environment values and redacts subprocess errors.

## Launch

From an authorized SSH session on the prepared exact instance, run exactly:

```bash
sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery_scaleway.sh
```

The Scaleway adapter authenticates the existing provider target and retains
the base launcher's scientific and resource checks. To run its launch
preflight without creating a worker, use:

```bash
sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery_scaleway.sh --preflight-only
```

The script refuses to start unless all of these conditions hold:

- Ubuntu, CPU, RAM, server-type attestation, disk, and resource values match
  the contract;
- the protected overall recovery window matches the exact instance/work
  directory, its expiry guard is installed, and positive time remains;
- the authorization value is exact;
- the environment is root-owned and inaccessible to group/other users;
- every required path is absolute, present, safe, and outside the repository
  where applicable;
- the repository is at the owner-supplied full commit and has no tracked or
  untracked change;
- the frozen YAML byte hash is
  `a38c2f6d1c3d84264c7b81a8a62c3a84cae8b993894f6634e339958cdc1f76b0`;
- configuration validation passes and the local E5 allowlist is exact;
- Python is exactly 3.12 and every preregistered model distribution has its
  exact installed version (a wheel-local suffix such as `+cpu` is recorded but
  cannot change the frozen public version);
- the complete B2 base namespace is either empty or contains only registered
  stage/final prefixes whose path/size state is an exact complete or resumable
  subset of preserved local transfer state;
- no final-discovery worker is active.

The detached service runs this secret-free scientific command:

```bash
uv run --frozen --no-sync echoes run-final-discovery \
  --production \
  --work-dir "$ECHOES_WORK_DIR" \
  --prepared-passages "$ECHOES_PREPARED_PASSAGES" \
  --knownness-path "$ECHOES_KNOWNNESS_PATH" \
  --offline-model-root "$ECHOES_MODEL_ROOT" \
  --m7-bucket project-echoes-archive \
  --m7-prefix m7/canonical-schema-v1 \
  --output-bucket "$ECHOES_OUTPUT_BUCKET" \
  --output-prefix "$ECHOES_OUTPUT_PREFIX"
```

Production mode independently rejects direct foreground execution. It requires
the exact `echoes-final-discovery.service` cgroup, systemd's invocation ID, and
the root-owned, non-writable launch-intent path and SHA-256 injected by this
launcher. The intent is nonsecret and group-readable only by the service
account. The worker rehashes and validates it before Stage 1.

The launcher writes new, never-reused stdout/stderr logs under
`/var/log/project-echoes/final-discovery/` and two root-readable, write-once
records under `/var/lib/project-echoes/final-discovery/launches/`:

- an intent containing the exact command, nonsecret environment, Git commit,
  Git tree, deterministic Git-archive SHA-256, lock hash, config hashes,
  resource envelope, disk measurement, and fixed recovery-window identity; and
- one startup snapshot containing the systemd unit, PID, limits, and the
  intent SHA-256.

The logs use unique launch IDs and are never truncated or reused. A later
restart receives a new launch ID and preserves prior logs and records.

After systemd accepts the service, the launcher performs exactly one startup
inspection. It does not sleep or retry. It prints the PID, record paths, log
paths, and status command, then exits. A failed startup check requires owner
or authorized engineer inspection; it never triggers an automatic restart.
Continue the authorized recovery after this bounded launcher action.

## Bounded status and continued recovery

Use this bounded snapshot command as needed through verified delivery:

```bash
sudo bash /srv/project-echoes/repo/cloud/final_discovery_status.sh
```

The command performs one bounded inspection and exits. It reports systemd
state, PID memory, current disk space, immutable launch-record identities, the
presence and declared identities of all 11 completion manifests, Stage 10's
validation summary, and Stage 11's transfer summary. It deliberately does not
print log contents, process environment, or credentials.

Repeated bounded status checks and log/checkpoint inspection are authorized
for this recovery. Space checks sensibly around stage progress and failures;
avoid a busy polling loop or unbounded command that prevents diagnosis or
communication. Do not stop work solely because startup verification passed.
The absolute expiry guard remains independent of this monitoring and must
work when no engineer or worker is active. Never print protected environment
contents or credentials while inspecting status or logs.

## Stages, restart, and failure behavior

The service owns these durable boundaries:

1. authenticate and materialize inputs;
2. semantic representations and indexes;
3. semantic candidate evidence;
4. grammatical/syntactic evidence;
5. structural/narrative evidence;
6. anomaly evidence;
7. empirical null controls;
8. transparent final ensemble;
9. disjoint Tier A and Tier B plus review bundle;
10. strict scientific and traceability validation; and
11. authenticated-directory assembly, direct B2 upload, and exact remote
    verification.

ADR 0020 is the binding persistence contract. Each upload-enabled stage is
reauthenticated and exposed in a new local checkpoint payload as
`checkpoint.json`, `completion.json`, `artifacts/`, and any registered
supplemental files. The runner uses same-filesystem hardlinks for the existing
immutable bytes, inventories the complete tree, and uploads those files
directly. It does not materialize a per-stage tar, compressed tar, or another
aggregate archive. A nonempty remote checkpoint prefix is accepted as complete
only when `check_tree` proves exact equality. If transport stopped after a
strict subset was written, the same launch may add only absent objects using
`rclone copy --immutable --checksum`; every existing path and size must already
belong to the finalized tree, and the complete result must then pass
`check_tree`. Unexpected, renamed, size-conflicting, or content-conflicting
objects are preserved and remain blocking. Nothing is overwritten or deleted.

Stage 11 builds the final `upload/package/` directory the same way and writes
`upload/package-receipt.json`. That receipt records package format
`authenticated_directory_v1`, source-inventory SHA-256, file count, total
size, hardlink staging, and `archive_materialized=false`. The destination B2
prefix therefore contains the `package/` object tree and its receipt, not one
final tar. The full `upload/` tree is verified by exact relative path and size
inventory plus an `rclone check --download` content comparison; the resulting
`transfer-verification.json` binds the portable local and remote inventory
identity, object count, and total size.

The storage form does not change the scientific campaign. Completion
manifests and their artifact hashes remain authoritative, and no detector,
null, tier, configuration, seed, or preregistration value changes.

Each successful stage publishes its completion manifest last. The next launch
authenticates every claimed dependency, code/config identity, artifact path,
size, and SHA-256 before skipping it. In-progress and failed attempts remain
preserved. A Stage 8 failure therefore does not invalidate embeddings, and a
Stage 11 transfer failure does not invalidate candidate or validation output.
Checkpoint receipts distinguish a resumed exact partial upload from a new
upload and an already-complete verified prefix.

The Stage 11 checkpoint is also the post-package finalization object. Its
supplemental tree contains `campaign-seal.json`,
`all-stage-validation-report.json`, and
`all-stage-validation-receipt.json`. The seal names the exact checkpoint B2
prefix and declares that remote reverification is mandatory before cleanup.
After upload, the runner writes a stable local `finalization-receipt.json`
which binds those identities and the verified checkpoint payload without its
restart-dependent transfer action. The corresponding UUID-named
`stage-checkpoint-receipt.json` retains that action. Neither receipt may be
discarded merely because the final package prefix is complete.

If the worker exits nonzero, is stopped at a checkpoint, reaches the 80 GiB
floor, times out, or is OOM-killed:

1. preserve a bounded status snapshot and inspect the uniquely named logs;
2. check the fixed deadline before any recovery operation;
3. diagnose and make only necessary repairs, with focused regression
   validation and a reviewed clean code identity when code changes are needed;
4. reauthenticate every reused artifact and code/config dependency under
   ADR 0021, preserving original completions, failure records, and provenance;
5. retry the same launch command only if the failure is recoverable and time
   remains; otherwise power off the exact instance while preserving evidence.

Repairs do not authorize changes to governed inputs, models, detector/null
policy, thresholds, tier meanings, or the recovery output-prefix identity.
Changed relevant code invalidates a prior reuse proof until authenticated
again; a passing receipt cannot bypass changed-code validation. A worker
timeout at the fixed overall deadline is expiry, not a retry opportunity.

The launcher refuses a duplicate active worker, keeps `Restart=no`, and never
deletes a checkpoint. A new scientific configuration or a reused/nonmatching
B2 prefix is not a recovery; it requires separate change control and
authorization.

Hard abort conditions include source/model/config/code drift, dirty code,
duplicate worker ownership, M7 authentication failure, unexpected output
objects, trace or validation failure, a disk-floor crossing, cgroup memory
limit, the fixed overall deadline, nonzero exit, and inability to establish exact B2
inventory equality. None of these conditions converts partial output into an
accepted result. Preserve the failed attempt; authorized diagnosis and a
corrected retry may proceed only within the same unexpired recovery window.

## Verified delivery and evidence-preserving poweroff

All verification and retention items below remain required for completed
delivery. Poweroff does not delete evidence and is mandatory on successful
worker completion, unrecoverable terminal failure, or expiry even if delivery
checks are still pending. Retrieve from verified B2 outputs after shutdown;
any necessary further instance access is bounded by the same fixed deadline.
This recovery does not authorize server deletion, disk destruction, or B2
cleanup.

1. `systemctl show echoes-final-discovery.service --property=Result --value`
   returns exactly `success` in a one-shot call.
2. All 11 completion manifests exist and the final all-stage validator exits
   zero:

   ```bash
   sudo bash -c \
     'set -a; source /etc/project-echoes/final-discovery.env; set +a; cd "$ECHOES_REPO_ROOT"; exec runuser -u "$ECHOES_SERVICE_USER" -- "$ECHOES_UV_BIN" run --frozen --no-sync echoes validate-final-discovery --all --work-dir "$ECHOES_WORK_DIR"'
   ```

3. The validator reports `passed=true`, zero findings, and 11 authenticated
   stages. Stage 10's embedded scientific validation must also report
   `passed=true` and zero findings.
4. Stage 11's `transfer-verification.json` names the intended B2 bucket/prefix,
   has a positive object count and size, and records identical exact local and
   remote inventory SHA-256 values. The authenticated Stage 11 completion must
   include that receipt and `package-receipt.json`; the latter must declare
   `authenticated_directory_v1`, `archive_materialized=false`, and the exact
   inventory SHA-256, file count, and size of the remote `package/` tree.
5. The Stage 11 finalization checkpoint at
   `<output-prefix>/checkpoints/11-package_upload_verify` is independently
   reverified against its preserved local `payload/` tree. Its exact remote
   inventory must match the local Stage 11 checkpoint receipt, and its
   authenticated `checkpoint.json` must inventory the campaign seal plus both
   all-stage validation files. The seal must name this same prefix, report 11
   authenticated stages, and require cleanup-time remote reverification.

   Perform that bounded one-shot reauthentication with exactly:

   ```bash
   sudo bash /srv/project-echoes/repo/cloud/verify_final_discovery_cleanup.sh
   ```

   This lists the complete remote path/size inventory once and downloads the
   small checkpoint, completion, seal, and validation records. It does not
   redownload the potentially large package: the initial Stage 11 receipt is
   the immutable evidence for the completed `rclone check --download`. The
   command creates a new root-readable receipt under
   `/var/lib/project-echoes/final-discovery/cleanup-verifications/`, preserves
   a failed record, never polls, and never deletes anything.
6. Copy the stable `finalization-receipt.json` and every Stage 11
   UUID-named `stage-checkpoint-receipt.json` to durable owner-controlled
   storage and verify their SHA-256 values. The stable receipt must bind the
   campaign seal, Stage 11 completion, validation receipts, and the exact
   remote checkpoint inventory; the per-attempt receipt retains the actual
   `uploaded_new`, `resumed_partial`, or `verified_existing` action.
7. Verify that both the intended immutable final package prefix and Stage 11
   finalization-checkpoint prefix remain present in B2 using authenticated
   inventories/receipts. No manual billing or console acknowledgment is a
   prerequisite. Do not delete or overwrite either after poweroff.
8. Copy the immutable launch intent/startup records, recovery-window record,
   and stdout/stderr logs to durable owner-controlled storage and verify their
   SHA-256 values. These operational records live outside the scientific
   package and would otherwise be lost with the server.
9. Retain all earlier work directories, staging/checkpoints, and failure
   records needed for diagnosis. Poweroff preserves them. The B2 package is
   not a replacement for un-packaged staging or failed-attempt evidence.

Capture the service result and verification receipts while the instance is
available; retain them durably alongside the authenticated finalization
records. Automatic success poweroff follows the worker's internal all-stage
validation and B2 verification. It does not waive delivery or independent
reverification. If a check cannot be completed before poweroff, continue from
the preserved local/durable receipts and verified remote artifacts, or obtain
the necessary instance records within the same unexpired window.

Deliver the verified result locations, retained receipt identities, a clear
distinction between statistically eligible Tier A and exploratory Tier B top
100, and several actual passage-evidence examples. Do not describe Tier B as
accepted discoveries; an empty Tier A is a valid outcome. Confirm the provider
reports the exact instance powered off when recovery terminates.

If any required verification is false or ambiguous, report the incomplete
result accurately and preserve the instance, staging, logs, and remote
prefixes. Resolve a recoverable problem within the remaining window; do not
weaken validation, prolong the deadline, or keep compute on after expiry.
Future destructive cleanup requires separate explicit authorization and must
retain the evidence required above.

After the canonical run and Tier B top-100 human review, stop retrieval-engine
development. An empty Tier A remains a valid result. A second full production
run is not part of this authorization and requires a separate decision for an
invalidating infrastructure failure, a result worth reproducing, or a
publication-level determinism need.
