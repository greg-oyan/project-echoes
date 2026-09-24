# Final-discovery run status

The last verified snapshot, **2026-09-24 at 05:43 UTC**, records all 11
computational stages complete and a passing all-stage validation with zero
errors. Finalization and complete delivery remain **unconfirmed**. The owner
subsequently confirmed that the Scaleway instance is **stopped**.

This is a sanitized status record for run
`20260923-review-compressed-e426b189`, produced with code commit
`b0fe9ac8982f12f580a0ea6e37e3ee60c03164a0`. The corresponding
[machine-readable snapshot](final-discovery-run-status.json) contains the same
aggregate facts and proof hashes. Neither file is a live status feed or a
replacement for the private authenticated receipts.

## Verified computational results

| Measure | Verified value |
| --- | ---: |
| Completed stages | 11 of 11 |
| Stages authenticated by final all-stage validation | 11 |
| Final all-stage validation errors | 0 |
| Evidence rows | 5,962,874 |
| Candidate pairs | 1,748,143 |
| Tier A statistically eligible candidates | 1,960 |
| Tier B exploratory candidates | 100 |
| Initially verified final-package transfer size | 92,539,897,055 bytes |
| Initially verified final-package transfer objects | 682 |

Tier A eligibility identifies candidates for scholarly investigation; it does
not establish a discovery, novelty, or literary dependence. Tier B is the
separate exploratory top 100 and is not statistically accepted. This snapshot
does not establish completion of human review or any additional milestone
acceptance gate. Historical Milestone 7 results and frozen scientific policy
remain unchanged.

## Retained proof identities

| Artifact | SHA-256 |
| --- | --- |
| Final all-stage validation report | `a4e3e7be5a8113b6d7a2109218e69ad9dd4b9e51432c4ebcde670c385bb33b7f` |
| Final all-stage validation receipt | `f92ad9982951b56ea900e7525e8fe38436d830460de68d2f9cef6c30f47f8c34` |
| Campaign seal | `ea7c996eb71837d56f504c2d48db6c65257faed0c1fa56410622e649597fc7c8` |
| Stage 11 completion manifest | `7235259cf4c27539556c7b55ec1d8088579c898dbd17853818d335714b43b76d` |

At the snapshot time, `finalization-receipt.json` was absent. A subsequent SSH
check could not reach the instance; the owner later confirmed its stopped
state. The power-state confirmation does not establish successful
finalization. The initial verified package upload does not by
itself establish that the separate Stage 11 finalization checkpoint and its
supplemental proof files were completely uploaded and verified.

## Storage and handoff

The current synchronization destinations are **GitHub and private B2**.
GitHub synchronization covers reviewed code, tests, governance documentation,
and this sanitized aggregate status. The complete review CSV/Parquet,
candidate and evidence ledgers, dossiers, source-bearing artifacts, databases,
operational logs, and original receipts remain in private archive or ignored
local research storage under the [data policy](data-licensing.md). This status
file does not grant public redistribution rights for those artifacts.

The declared review workflow uses the complete CSV/Parquet ledger and
reproducible dossiers. Keep the B2 archive intact until any replacement archive has a verified
complete inventory and matching SHA-256 values. Migration must preserve
access restrictions, source licensing, attribution, and proof records;
deletion of the existing archive requires a separate explicit decision.

The remaining handoff work is:

1. Obtain and authenticate the stable finalization receipt and the Stage 11
   checkpoint receipts; independently verify the finalization checkpoint and
   its campaign seal and all-stage validation files against retained proof.
2. Preserve operational records alongside the owner's stopped-instance
   confirmation. Preserve all staging, checkpoints, failure records, and
   remote artifacts.
3. Collect the authenticated review bundle into private research storage,
   verify its hashes, and begin the governed human review, including all
   100 Tier B candidates. Record decisions and retain rejected candidates.
4. Keep current synchronization scoped to GitHub and B2. Plan any archive
   migration separately before transferring or deleting preserved artifacts.

The [master plan](master-plan.md) remains the governing specification. The
[cloud runbook](final-discovery-cloud-runbook.md) defines the finalization and
delivery checks, and [the campaign specification](final-discovery-v1.md)
defines candidate interpretation and review obligations.
