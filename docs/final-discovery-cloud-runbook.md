# `final-discovery-v1` owner cloud runbook

Status: guarded pre-production boundary; no production run has been launched

Last pricing review recorded in this document: 2026-08-08

This runbook is the exact owner-operated boundary for the one canonical
`final-discovery-v1` campaign. It does not authorize Codex, a script, or any
other agent to create, purchase, stop, or delete cloud resources. The owner
creates the server, installs the protected environment, invokes the single
launch command, verifies the result, and makes the destructive cleanup
decision.

The launcher contains no Hetzner provisioning API call and no polling loop. It
starts one detached systemd worker, performs one immediate startup inspection,
and returns control. Every later status check is a separate one-shot owner
action.

## Frozen execution contract

| Field | Required value |
| --- | --- |
| Experiment | `final-discovery-v1` |
| Host | owner-created Hetzner `CCX43` |
| Operating system | Ubuntu 24.04 LTS, x86-64 |
| Compute | 16 dedicated AMD vCPUs; campaign ceiling 12 CPU threads |
| Memory | 64 GB advertised host RAM; cgroup `MemoryMax=56G`, `MemoryHigh=54G`, swap disabled |
| Local SSD | 360 GB advertised; at least 280 GiB free at launch |
| Disk abort floor | 80 GiB, checked at campaign checkpoint boundaries rather than by a monitor |
| DuckDB | 40 GiB host/service ceiling |
| Runtime | `RuntimeMaxSec=96h`; `Restart=no` |
| Worker owner | exactly one `echoes-final-discovery.service` |
| M7 input | B2 `project-echoes-archive/m7/canonical-schema-v1` |
| M7 manifest SHA-256 | `e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6` |
| Authorization | exact `ECHOES_AUTHORIZE_PRODUCTION=final-discovery-v1` |
| Hard all-in cap | USD 75.00, including elapsed server time and a declared B2 reserve |
| Persistence | same-filesystem hardlink staging and direct authenticated object trees; no stage or final archive |

The 40 GiB DuckDB and 12-thread values are ceilings for this machine and
service, not claims about resource consumption. The authenticated M7
projection deliberately retains its stricter built-in bound of 1 GiB and one
DuckDB thread. Other numerical and sparse operations may use up to the
12-thread service ceiling. The model is CPU-only; no GPU host or CUDA package
is part of this run.

The stage runner applies the 80 GiB value as its production checkpoint floor
and checks free space before entering each durable stage (therefore between
completed stages as well). Crossing the floor fails the campaign before the
next stage and preserves completed stages, failed attempts, and staging. There
is no timer, daemon, sleep loop, or continuously running disk monitor.

### Measured preproduction resource gate

The latest bounded, text-free medium benchmark completed in 32.097 seconds on
the development laptop. Its 1,000-pair disk sample covered all nine detectors,
9,000 evidence rows, 32 strata, four external-sort chunks, both final-null
scopes, and review-index lookup. Direct 100,000-score measurements ran each
registered null kernel for the full 1,000 iterations. Detector calibration
took 9.159 seconds; permutation-like and bootstrap kernels took 4.112 and
0.995 seconds. No source text, model, network, or cloud resource was used.

The projection is tied to the campaign scale contract rather than nine rows
for every pair: at most 2,592,480 retained pairs, 11,718,699 evidence rows,
6,633 pair strata, 59,697 detector-strata, 10.123211 billion permutation-like
cells, and 1.595488 billion bootstrap cells. Each production stage is counted
once. A 1.25-safety-factor projection of measured work is 20.77 hours. A
separate 32-hour reserve covers unbenchmarked representation and detector
feature extraction (16 hours), B2 materialization/upload/verification (8
hours), and strict validation/packaging/review artifacts (8 hours). The
planning range is 20.77--52.77 hours, leaving 43.23 hours below the frozen
96-hour stop. At the documented USD 0.529/hour assumption, the 52.77-hour
worker portion is approximately USD 27.91 before setup time and the separately
reserved B2 amount; the launcher still budgets the full 96-hour worst case.

Projected persistent benchmark artifacts are 121,424,656,152 bytes (113.086
GiB); adding the 17.149-GiB canonical M7 input gives 139,838,254,692 bytes
(130.235 GiB). Starting with 280 GiB free leaves approximately 149.765 GiB,
above the 80-GiB floor. The modeled minimum initial free space including that
floor is 225,737,600,612 bytes (210.235 GiB). This estimate excludes source
text and model downloads by design and is not permission to reduce the launch
or checkpoint disk gates.

Schema 2 records the measured process peak RSS against the registered
`MemoryMax=56G` ceiling and fails closed if the measurement is unavailable or
exceeds that limit. The benchmark report is preserved for diagnosis, but its
command exits nonzero unless runtime, memory, disk, and exact cardinality all
pass.

The authoritative benchmark must be generated outside the repository from
the exact clean launch commit and then added at
`outputs/reports/final-discovery-preproduction-benchmark.json`. Its
`report_status` must be `commit_bound_clean`; its commit, code/config hashes,
resource gates, and file SHA-256 must be recorded together. A dirty-tree
development report is provisional evidence only and cannot authorize launch.

## Price and budget gate

The planning assumption on 2026-08-08 is USD 0.528/hour for a US CCX43 after
the June 2026 Hetzner price adjustment, plus up to USD 0.001/hour if the owner
uses a separately billed Primary IPv4: USD 0.529/hour combined. A full 96-hour
worker window is therefore USD 50.784 before setup time and object storage.
Backblaze's listed pay-as-you-go storage rate is USD 6.95/TB-month, with upload
free; transaction and download conditions remain subject to the current
pricing page. The environment example reserves USD 10.00 for B2 uncertainty.
[Hetzner price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/),
[Hetzner general-purpose cloud](https://www.hetzner.com/cloud/general-purpose),
[Backblaze B2 pricing](https://www.backblaze.com/cloud-storage/pricing),
[Backblaze transaction pricing](https://www.backblaze.com/cloud-storage/transaction-pricing).

These are planning assumptions, not a quote. Immediately before every launch,
the owner must verify the current all-in hourly rate for the chosen location,
server, and IP configuration and enter:

- the verified rate and UTC verification time;
- the server's original creation time; and
- a conservative B2 reserve.

The launcher rejects a price verification older than 24 hours. It computes
the worst case as:

```text
(elapsed server hours before launch + 96 worker hours) * verified hourly rate
+ B2 reserve
```

and refuses to start if that projection exceeds USD 75.00. This guard cannot
replace provider billing review: the owner remains responsible for checking
the Hetzner and Backblaze consoles and deleting the server before additional
idle time breaches the cap.

## Owner preparation

1. Manually create exactly one server named
   `project-echoes-final-discovery-v1` using CCX43, Ubuntu 24.04, 16 dedicated
   AMD vCPUs, 64 GB RAM, and its 360 GB local SSD. Do not attach a paid volume,
   snapshot, backup, GPU, database, or other service. The repository does not
   provision this server.
2. Create the unprivileged `echoes` service account. Keep SSH key-only and do
   not expose an application or web service.
3. Place the reviewed repository at `/srv/project-echoes/repo` on the exact
   commit recorded in the protected environment. The tree must be completely
   clean, including untracked files. Inputs, work products, models, credentials,
   and local research databases remain outside the Git tree. Keep the stage
   store, checkpoint workspaces, and final package staging on the same local
   filesystem: checkpointing fails closed rather than copying payload bytes if
   a hardlink cannot be created.
4. Install `uv`, `rclone`, Git, Python 3.12, and the locked project environment,
   including the non-default `models` dependency group. The service command
   uses `uv run --frozen --no-sync`, so launch cannot resolve or install a
   dependency.
5. Materialize the nine allowed files for
   `intfloat/multilingual-e5-small` revision
   `614241f622f53c4eeff9890bdc4f31cfecc418b3` under the offline model root.
   Do not place a floating Hugging Face cache there. The launch preflight
   verifies every registered file and SHA-256 with network model access
   disabled.
6. Transfer the governed prepared-passage JSONL and bidirectional knownness
   JSONL to the paths declared in the environment. Place the authenticated
   knownness receipt beside the JSONL using the fixed
   `<stem>.receipt.json` name. The launcher checks both files before starting
   the worker. Verify all transfer receipts before launch. Do not transfer raw
   restricted acquisitions.
7. Create a least-privilege Backblaze application key capable of reading the
   frozen M7 prefix and writing/checking the chosen final output prefix. Choose
   a normalized, unique output prefix that is initially empty. A reused or
   mismatched prefix fails closed.
8. Copy [`cloud/final-discovery.env.example`](../cloud/final-discovery.env.example)
   to `/etc/project-echoes/final-discovery.env`, replace every `OWNER_SET`
   value, then protect it:

   ```bash
   sudo chown root:root /etc/project-echoes/final-discovery.env
   sudo chmod 600 /etc/project-echoes/final-discovery.env
   ```

The populated environment is a secret and must never enter Git, shell history,
chat, logs, launch arguments, or a result package. The launch record retains
the exact nonsecret environment and records only that each B2 secret was
present. The service receives credentials through its protected
`EnvironmentFile`; the B2 adapter creates its ephemeral rclone configuration
from those environment values and redacts subprocess errors.

## Launch

From an owner-controlled SSH session on the prepared server, run exactly:

```bash
sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery.sh
```

There are no launch flags. The script refuses to start unless all of these
conditions hold:

- Ubuntu, CPU, RAM, server-type attestation, disk, runtime, resource, and
  budget values match the contract;
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
- no final-discovery worker is active; and
- projected worst-case cost fits the USD 75.00 all-in cap.

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
  resource envelope, disk measurement, and budget calculation; and
- one startup snapshot containing the systemd unit, PID, limits, and the
  intent SHA-256.

The logs use unique launch IDs and are never truncated or reused. A later
restart receives a new launch ID and preserves prior logs and records.

After systemd accepts the service, the launcher performs exactly one startup
inspection. It does not sleep or retry. It prints the PID, record paths, log
paths, and status command, then exits. A failed startup check requires owner
inspection; it never triggers an automatic restart.

## One-shot status

Run only when a human wants a snapshot:

```bash
sudo bash /srv/project-echoes/repo/cloud/final_discovery_status.sh
```

The command performs one bounded inspection and exits. It reports systemd
state, PID memory, current disk space, immutable launch-record identities, the
presence and declared identities of all 11 completion manifests, Stage 10's
validation summary, and Stage 11's transfer summary. It deliberately does not
print log contents, process environment, or credentials.

Do not use `watch`, a shell loop, a sleep loop, `journalctl -f`, repeated SSH
automation, or any other continuous monitor. Logs and checkpoints are
diagnostic artifacts to inspect once, not a feed to follow.

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

1. take one status snapshot;
2. inspect the uniquely named stderr/stdout files once;
3. correct only the infrastructure failure without changing experiment code,
   configuration, model, inputs, output prefix identity, or thresholds; and
4. invoke the same launch command again.

The launcher refuses a duplicate active worker, keeps `Restart=no`, and never
deletes a checkpoint. A new scientific configuration or a reused/nonmatching
B2 prefix is not a recovery; it requires separate change control and
authorization.

Hard abort conditions include source/model/config/code drift, dirty code,
duplicate worker ownership, M7 authentication failure, unexpected output
objects, trace or validation failure, a disk-floor crossing, cgroup memory
limit, the 96-hour runtime, nonzero exit, and inability to establish exact B2
inventory equality. None of these conditions converts partial output into an
accepted result.

## Completion and owner-only cleanup gate

Server deletion is prohibited until every item below is true:

1. `systemctl show echoes-final-discovery.service --property=Result --value`
   returns exactly `success` in a one-shot call.
2. All 11 completion manifests exist and the final all-stage validator exits
   zero:

   ```bash
   sudo -u echoes bash -c \
     'cd /srv/project-echoes/repo && exec /usr/local/bin/uv run --frozen --no-sync echoes validate-final-discovery --all --work-dir /srv/project-echoes/final-discovery/work'
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
6. The owner copies the stable `finalization-receipt.json` and every Stage 11
   UUID-named `stage-checkpoint-receipt.json` to durable owner-controlled
   storage and verifies their SHA-256 values. The stable receipt must bind the
   campaign seal, Stage 11 completion, validation receipts, and the exact
   remote checkpoint inventory; the per-attempt receipt retains the actual
   `uploaded_new`, `resumed_partial`, or `verified_existing` action.
7. The owner confirms in Backblaze that both the intended immutable final
   package prefix and Stage 11 finalization-checkpoint prefix remain present.
   Do not delete or overwrite either after server cleanup.
8. The owner copies the immutable launch intent/startup records and stdout/
   stderr logs to durable owner-controlled storage and verifies their SHA-256
   values. These operational records live outside the scientific package and
   would otherwise be lost with the server.
9. The owner has retained any staging/checkpoints needed for diagnosis. Server
   deletion irreversibly destroys the local SSD; the B2 package is not a
   replacement for un-packaged staging or failed-attempt evidence.

If any item is false or ambiguous, do not clean up. Preserve the server,
staging, logs, and remote prefix, then resolve the ambiguity within the hard
budget. Do not weaken the gate to avoid idle cost.

After all nine items pass, return to the owner's trusted workstation (not an
agent session), verify the exact target once:

```bash
hcloud server describe project-echoes-final-discovery-v1 -o json
```

Then the owner may perform the explicitly destructive cleanup:

```bash
hcloud server delete project-echoes-final-discovery-v1
```

That command permanently deletes the server and its local SSD. It does not
authorize deletion of the B2 result prefix. If the owner separately created a
Primary IP, volume, snapshot, or backup contrary to the minimal plan, inspect
that resource by its exact provider ID and remove it separately only after the
same evidence gate; deleting a server may not stop billing for a separately
owned resource.

After the canonical run and Tier B top-100 human review, stop retrieval-engine
development. An empty Tier A remains a valid result. A second full production
run is not part of this authorization and requires a separate decision for an
invalidating infrastructure failure, a result worth reproducing, or a
publication-level determinism need.
