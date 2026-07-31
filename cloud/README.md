# Milestone 7 cloud execution

This directory prepares, launches, inspects, validates, and retrieves the first
Milestone 7 cloud run. It does not provision, purchase, connect to, resize, or
destroy any cloud resource. The first run adopts the transferred interrupted
staging directory; it never starts fresh and never deletes staging or
checkpoints.

The governed server selection is:

- Hetzner Cloud `CCX33`, dedicated x86 (AMD)
- Hillsboro, Oregon as the primary location; Ashburn, Virginia as the fallback
- Ubuntu 24.04
- 8 dedicated vCPUs, 32 GiB RAM, 240 GB local SSD
- one public Primary IP selected manually only if required for SSH

The owner-verified CCX33 rate is USD 0.2660/hour and the Primary IPv4 planning
rate is USD 0.0010/hour, for a combined USD 0.2670/hour. Formal gross ceilings
are USD 12.816 for the 48-hour worker, USD 19.224 for one 72-hour lifecycle,
and USD 38.448 for two separately authorized lifecycles. The existing USD
25.00 account credit remains separate from those ceilings. Estimated remaining
cash exposure is USD 0.00 after one lifecycle and USD 13.448 after two.

## Fixed server layout

| Purpose | Path |
| --- | --- |
| Git checkout and relative project data | `/srv/project-echoes/repo` |
| Pipeline state and receipts | `/var/lib/project-echoes/m7` |
| General and DuckDB local-SSD temporary space | `/var/lib/project-echoes/tmp` |
| Timestamped stdout/stderr logs | `/var/log/project-echoes/m7` |
| Protected review packages and full manifests | `/srv/project-echoes/packages` |
| systemd environment | `/etc/project-echoes/m7.env` |
| Service | `echoes-m7.service` |

The service environment is exact:

```text
ECHOES_M7_CLOUD_EXECUTION=1
ECHOES_MAXIMUM_MEMORY_BYTES=30064771072
ECHOES_DUCKDB_MEMORY_LIMIT_BYTES=23622320128
ECHOES_MINIMUM_FREE_DISK_BYTES=26843545600
ECHOES_THREAD_COUNT=1
ECHOES_DUCKDB_TEMP_DIRECTORY=/var/lib/project-echoes/tmp/duckdb
ECHOES_PROMOTION_JOURNAL=/srv/project-echoes/repo/data/processed/lexical/.schema-v1.promotion-intent.json
TMPDIR=/var/lib/project-echoes/tmp
```

One thread retains the frozen deterministic Milestone 7 configuration and is
within the six-thread ceiling. systemd separately enforces
`MemoryHigh=26G`, `MemoryMax=28G`, no swap, `RuntimeMaxSec=48h`, and
`Restart=no`.

## Transfer-manifest contract

`cloud/transfer-manifest.json` is the sole upload allowlist. Its normalized
shape is:

```json
{
  "schema_version": 1,
  "repository": {
    "branch": "feature/m7-lexical-baseline",
    "commit_policy": "operator_supplied"
  },
  "total_upload_bytes": 123,
  "files": [
    {
      "path": "relative/posix/path",
      "size_bytes": 123,
      "sha256": "<64 lowercase hexadecimal characters>",
      "classification": "required",
      "required": true
    }
  ],
  "excluded": []
}
```

Transferable classifications are `required`, `recoverable_checkpoint`, and
`final_output`. `regenerable`, `obsolete_or_excluded`, and `excluded` entries
must not have `required: true`. The verifier rejects absolute paths, traversal,
backslashes, duplicates, symlinks, size drift, hash drift, total-byte drift,
and repository branch drift. Bootstrap separately authenticates the
operator-supplied full commit and remote branch tip.

The tracked manifest cannot truthfully embed the final commit that contains
itself, and it cannot list its own hash because both would be self-referential.
The final full commit is supplied separately to bootstrap, which authenticates
Git `HEAD` and the remote branch tip. The upload script transfers the manifest
as a control file and verifies every listed payload byte.
`total_upload_bytes` is therefore the exact governed payload size and excludes
only the small control manifest itself.

The manifest builder's SHA-256 logic and upload allowlist remain unchanged.
The scoped acceptance requirement is:

> All database, corpus, staging, checkpoint, generated-data,
> execution-manifest, scientific-configuration, and final-output manifest
> entries remain unchanged. Only entries for scoped tracked code,
> documentation, configuration, tests, and cloud tooling may be refreshed.

Passage-artifact entries are protected and remain unchanged as well.

The file manifest intentionally records regular files, not empty directories.
The currently empty `.candidate-review-queue-spool` directory is operationally
non-semantic, and the resume path safely recreates it when needed; its absence
from the upload manifest does not change recovered computation or scientific
content.

Excluded material includes `.venv`, Python/tool caches, unrelated logs,
page/swap files, unrelated outputs, obsolete failed staging attempts,
credentials, private keys, and secrets. Do not broaden the manifest merely to
make a transfer pass.

## Exact first-run procedure

Replace only the server address, SSH host-key fingerprint, private-key path,
and final pushed commit. Obtain the SHA-256 host-key fingerprint through a
trusted Hetzner Console channel before the first scripted connection. Never use
an accept-any host-key option.

1. In the Hetzner Console, manually create the exact server described above.
   Do not use these scripts to create it. Ensure the branch is already pushed.

2. Establish the remote Git checkout at the exact pushed commit. If the stock
   image lacks Git, install only Git and CA certificates first:

   ```bash
   apt-get update
   apt-get install -y --no-install-recommends git ca-certificates
   install -d -m 0750 /srv/project-echoes
   git clone --branch feature/m7-lexical-baseline --single-branch \
     https://github.com/greg-oyan/project-echoes.git /srv/project-echoes/repo
   git -C /srv/project-echoes/repo checkout <FULL_40_CHARACTER_COMMIT>
   ```

3. From Windows PowerShell in the local repository, use WinSCP's .NET
   assembly for resumable, repeatable, structure-preserving upload:

   ```powershell
   .\cloud\upload_to_server.ps1 `
     -Server <SERVER_IP> `
     -User root `
     -HostKeyFingerprint "ssh-ed25519 255 SHA256:<VERIFIED_FINGERPRINT>" `
     -PrivateKeyPath "C:\path\to\ssh-key.ppk" `
     -RemoteRoot "/srv/project-echoes/repo"
   ```

   Existing remote files are reused only after exact size and SHA-256
   agreement. Interrupted files use WinSCP resume support. The script runs the
   remote manifest verifier and launches nothing. Once a rebind intent or
   rebind index exists, upload refuses to restore the original database over
   the authenticated server state.

4. Over SSH, bootstrap Ubuntu and verify the pinned DuckDB 1.5.4 database with
   a bounded read-only metadata query:

   ```bash
   cd /srv/project-echoes/repo
   sudo bash cloud/bootstrap_ubuntu.sh \
     --repo-root /srv/project-echoes/repo \
     --expected-branch feature/m7-lexical-baseline \
     --expected-commit <FULL_40_CHARACTER_COMMIT>
   ```

   Bootstrap refuses the wrong OS/architecture, fewer than 120 GiB free,
   branch or commit drift, a remote branch tip mismatch, dirty tracked files,
   transfer hash failure, lockfile failure, DuckDB version/read failure, or a
   failed 22 GiB setting probe. After authenticating the original transferred
   database and passage tree, it uses the repository's governed transactional
   rebind command to replace the six Windows-bound passage views with Linux
   globs, performs at-most-one-row reads through each view, and records a
   durable pre-mutation intent plus an atomic receipt with the original and
   rebound database hashes. An interrupted post-commit invocation can recover
   its receipt only from that exact intent, catalog, and tiny reads. Bootstrap,
   service installation, and launch all verify that receipt and the rebound
   hash before the worker may start. Post-run validation records the database's
   new hash because loading lexical views legitimately changes it.

5. Install, but do not yet start, the singleton service:

   ```bash
   sudo bash cloud/install_echoes_service.sh \
     --repo-root /srv/project-echoes/repo \
     --resume-staging \
       data/processed/lexical/.schema-v1.writing-238902db1f6e479596bea47e70ccf30b
   ```

6. Launch the recovered run:

   ```bash
   sudo bash cloud/cloud_start.sh
   ```

   The launcher checks the 120 GiB free-disk floor again, refuses another
   pipeline process, and first runs the bounded `recover-lexical-promotion`
   command as the `echoes` service user. Any live
   `data/processed/lexical/.schema-v1.promotion-intent.json` is copied to an
   immutable protected state artifact before recovery. A restored-staging
   result proceeds through the normal staging gates; a committed-canonical
   result preserves the active journal, refuses a new worker, and directs the
   operator to detached strict validation/provenance recovery. Every preflight
   writes an immutable recovery receipt that the worker authenticates. A
   committed archive with already-succeeded execution provenance is also a
   terminal recovery witness, including the narrow archive-to-process-exit
   interruption window. It prevents relaunch but does not override the later
   acceptance requirement that the authenticated systemd `Result` equal
   `success`. Each committed recovery receipt identifies the active or archived
   journal path and SHA-256, promotion ID, execution-manifest path and execution
   ID, and manifest status observed at recovery; archived recovery therefore
   never depends on a now-absent active journal. The launcher then submits one
   systemd start, performs one startup inspection, and returns control. Never
   edit or delete a promotion journal. Do not keep an SSH session open and do
   not poll.

7. When a human chooses to inspect it, run the one-shot status command once:

   ```bash
   sudo bash cloud/cloud_status.sh
   ```

   It reports service state, PID, elapsed and CPU time, resident and virtual
   committed memory, cgroup and system committed memory, disk free, staging
   size, primary/Tier 3 checkpoint counts, partition counts, latest output,
   canonical existence, bounded safe details and SHA-256 identities for every
   active/resolved `.schema-v1.promotion-*.json` journal, the latest promotion
   recovery receipt, and bounded latest log tails. It never sleeps or writes a
   status loop.

8. Abort only for an execution-contract condition. This sends one graceful
   SIGINT-based systemd stop and returns without deleting anything:

   ```bash
   sudo bash cloud/cloud_stop.sh
   ```

9. After the pipeline service has finished successfully, submit strict
   validation:

   ```bash
   sudo bash cloud/cloud_validate.sh --submit
   ```

   Validation is detached because full file hashing and strict validation may
   exceed ten minutes. Inspect it later with `cloud_status.sh`; do not poll.
   The validator checks expected artifacts and parts, contiguous and unique
   partition names, Parquet metadata readability and consistent schemas,
   table/file manifests and every SHA-256, row counts, the successful recovered
   execution manifest and checkpoint lineage, DuckDB 1.5.4 exposure, canonical
   promotion, every active/resolved promotion journal and recovery receipt,
   and passage/benchmark/report prerequisites. A committed-canonical crash
   witness is never treated as permission to relaunch. Validation first runs
   the repository's strict `echoes validate-lexical --all --strict` gate. Only
   after that exact JSON report passes may it internally invoke:

   ```bash
   echoes finalize-lexical-promotion-recovery \
     --validation-report <STRICT_VALIDATION_JSON> \
     --service-result <AUTHENTICATED_SYSTEMD_RESULT> \
     --database /srv/project-echoes/repo/data/processed/project_echoes.duckdb \
     --output-dir /srv/project-echoes/repo/data/processed/lexical/schema-v1 \
     --json
   ```

   The authenticated systemd `Result` is passed without reinterpretation. A
   recorded failed execution is never reclassified, and a still-running
   manifest is eligible only when `Result=success`. The validator preserves an
   immutable finalization receipt, verifies the archived journal byte-for-byte,
   recomputes the exact governed lexical/convenience-view catalog SHA-256 and
   compares it with the DuckDB promotion marker, binds that marker to one
   committed journal and succeeded execution manifest, runs the independent
   cloud structural/hash audit against sealed provenance, and writes
   `/var/lib/project-echoes/m7/latest-validation.json`.

10. After that receipt reports `passed: true`, submit protected packaging:

    ```bash
    sudo bash cloud/package_results.sh --submit
    ```

    The small `.tar.zst` review package contains bounded operational logs,
    manifests, sanitized reports, metrics, validation, promotion-recovery, and
    promotion-finalization receipts, every preserved
    `.schema-v1.promotion-*.json` journal, and the strongest 100 unreviewed
    queue rows. The full result is not duplicated: a protected remote-only JSON
    manifest hashes the canonical result, database, execution manifests,
    journals, validation, logs, and reports.

11. Download the small verified review package without creating a local
    duplicate:

    ```powershell
    .\cloud\download_from_server.ps1 `
      -Server <SERVER_IP> `
      -User root `
      -HostKeyFingerprint "ssh-ed25519 255 SHA256:<VERIFIED_FINGERPRINT>" `
      -PrivateKeyPath "C:\path\to\ssh-key.ppk"
    ```

    The default destination is
    `%USERPROFILE%\Downloads\project-echoes-m7`. A matching archive is reused;
    a different file with the same name is never overwritten. Interrupted
    downloads retain WinSCP resume state, and the final archive is atomically
    named only after size and SHA-256 verification.

## Heavy-execution contract

| Field | Governed value |
| --- | --- |
| Executor | `echoes-m7.service`, dedicated `echoes` user, nonblocking SSH-independent systemd process, `flock -n` singleton |
| Machine | Hetzner `CCX33`, Hillsboro primary and Ashburn fallback, Ubuntu 24.04 x86_64, 8 dedicated AMD vCPU, 32 GiB RAM, 240 GB local SSD |
| Process/cgroup memory | cloud process ceiling 28 GiB; `MemoryHigh=26G`; `MemoryMax=28G`; `MemorySwapMax=0` |
| DuckDB | pinned 1.5.4; 22 GiB connection limit; spill under `/var/lib/project-echoes/tmp/duckdb` on local SSD |
| Threads | exactly 1 for the frozen run; hard machine-level policy is no more than 6 |
| Disk | refuse launch below 120 GiB free; checkpoint-bound safe stop below 25 GiB during execution; no local or remote duplicate of the transferred staging tree |
| Pipeline wall clock | hard 48 hours through `RuntimeMaxSec=48h` |
| Validation/package wall clock | detached transient units, each capped at 12 hours |
| Maximum expected cost | combined planning rate USD 0.2670/hour; formal gross USD 12.816 per 48-hour worker, USD 19.224 per 72-hour lifecycle, and USD 38.448 for two; USD 25.00 credit is separate, leaving USD 0.00/13.448 estimated exposure |
| Checkpoints | event-based primary candidate parts and Tier 3 profile/detector completion manifests; no fabricated time interval |
| Status | `sudo bash cloud/cloud_status.sh`, one snapshot only |
| Abort conditions | hash/commit/config drift, duplicate worker, ambiguous/unsafe promotion journal, canonical preexistence without a committed recovery witness, staging ambiguity, fewer than 120 GiB free at launch, crossing the 25 GiB execution safe-stop floor, memory/cgroup limit, I/O or Parquet corruption, service failure/OOM, 48-hour timeout, or an explicit human stop |
| Required outputs | canonical `schema-v1`, `table-hashes.json`, one preserved committed promotion journal bound to the DuckDB marker and successful recovered execution manifest, DuckDB lexical exposure, strict validation receipt, small review package, protected full-result manifest |
| Retention | preserve all active/resolved promotion journals, recovery receipts, failed staging, checkpoints, manifests, logs, validation receipts, canonical results, and packages until the owner explicitly authorizes deletion |

The cost and runtime estimates are provisional until this exact first cloud run
is measured. The second fresh determinism run is deliberately not automated by
these first-run commands. Preserve the first canonical result, hash manifest,
execution manifest, validation receipt, and full-result manifest before
designing that fresh run. Never repurpose `--force` to erase the first result.

## Failure behavior

- `Restart=no` prevents a failed/OOM run from silently restarting.
- The event-bound in-process disk guard fails below 25 GiB at governed write,
  sensitivity-spill, and finalization boundaries. Its error is retained in
  execution state and stderr, while staging and checkpoints remain preserved
  for the one-shot status and recovery paths.
- Strict validation and packaging require an inactive worker whose exact
  systemd `Result` is `success`. Active or archived committed-journal evidence
  preserves and explains canonical bytes but never turns `signal`, `oom-kill`,
  `timeout`, `exit-code`, or another failure into acceptance.
- SIGINT gives Python a chance to finalize failure provenance and restore any
  checkpoint quarantine. systemd may use SIGKILL only after the ten-minute stop
  timeout; already-written staging remains.
- Memory and runtime termination never invoke cleanup code from these shell
  tools.
- `cloud_start.sh` preserves a byte-identical protected copy before asking the
  governed CLI to resolve an active promotion journal. Restored journals are
  archived, and a committed-canonical journal stays active until successful
  validation/provenance sealing; shell tooling never deletes one.
- The pipeline's governed pre-promotion validation must pass before the atomic
  canonical rename. `cloud_validate.sh` independently revalidates the promoted
  result and refuses packaging on any failure.
- A failed transfer, bootstrap, launch preflight, validation, or packaging step
  leaves preserved source/staging/checkpoint data in place.
