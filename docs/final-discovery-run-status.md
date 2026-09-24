# Final-discovery run status

The verified handoff snapshot, **2026-09-24 at 16:25 UTC**, confirms all 11
computational stages, passing all-stage validation with zero errors, the final
checkpoint receipts, and delivery of the selected review bundle into private
research storage. The provider API independently confirmed the existing
instance is **stopped** after retrieval. Human review remains incomplete, with
zero candidate adjudications recorded.

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
| Verified final-package transfer size | 92,539,897,055 bytes |
| Verified final-package transfer objects | 682 |
| Verified terminal checkpoint transfer size | 92,540,069,172 bytes |
| Verified terminal checkpoint transfer objects | 689 |
| Privately delivered handoff files, excluding transport manifest | 217 |
| Privately delivered handoff size, excluding transport manifest | 23,897,594 bytes |
| Authenticated selected review files | 206 |
| Authenticated selected dossiers | 200 |

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
| Stable finalization receipt | `27fef6b79af4337705bbd543ad20d62d0fe3f9467461c6748fef8a482c802f15` |
| Private delivery verification receipt | `14d89ec41ec85fcc2693216763a5eb4859908754287d044d6142e562d674ea64` |
| Private handoff transport manifest | `e472404783fe99137dbb9c921f37ce030315e7ed4aa265beeea25be9ea23704b` |
| Bounded B2 handoff reverification receipt | `2454f5b6d5d32c1b0311fc32f62e17e8c621322af16ac83ac03ba7450e0c740d` |
| Post-retrieval provider-state verification | `2cc84136fa26777469d836cb7a7dfb104d72afaf42bc868f3868357dc90f9050` |

The retrieved stable finalization receipt binds the campaign seal, Stage 11
completion, all-stage validation records, and the terminal checkpoint transfer.
Its local and remote transfer inventories match. The delivery verifier passed
after checking those bindings and every selected review file against the
authenticated Stage 9 inventory. The original per-attempt checkpoint receipt
and worker logs were also retained privately.

This delivery check binds the successful production content-verification
receipts. At **16:24:13 UTC**, a separate bounded B2 recheck passed: the complete
path/size inventories for the final package and terminal checkpoint matched
the retained receipts, and all six critical remote proof files matched their
expected bytes. This recheck did not rehash the full local artifact tree or
repeat the full remote content comparison. The destructive cleanup gate has
not been established, and no deletion is authorized.

At **16:25:29 UTC**, an authenticated provider API query for the exact existing
instance confirmed `stopped`. Retrieval and these checks did not start the
scientific pipeline. All preserved worker and remote evidence remains subject
to the existing retention requirements.

## Storage and handoff

The current synchronization destinations are **GitHub and private B2**.
GitHub synchronization covers reviewed code, tests, governance documentation,
and this sanitized aggregate status. The complete review CSV/Parquet,
candidate and evidence ledgers, dossiers, source-bearing artifacts, databases,
operational logs, and original receipts remain in private archive or ignored
local research storage under the [data policy](data-licensing.md). This status
file does not grant public redistribution rights for those artifacts.

The approximately 92.5-GB full artifact package remains in B2. The approximately
23.9-MB private handoff contains the proof files, selected review material,
checkpoint receipt, and logs; it is not a local copy of the full package.
The selected review material includes both complete tier ledgers and the 200
registered dossiers, alongside the review summary, manifest, and template.
The complete CSV/Parquet ledger remains available in the full B2 package.

Keep the B2 archive intact until any replacement archive has a verified
complete inventory and matching SHA-256 values. Migration must preserve
access restrictions, source licensing, attribution, and proof records;
deletion of the existing archive requires a separate explicit decision.

The remaining handoff work is:

1. Preserve the delivered proof, review and operational records, all worker
   staging, checkpoints, failure records, and remote artifacts.
2. Complete the governed human review, including all 100 Tier B candidates.
   Record decisions and retain rejected candidates; do not treat computational
   eligibility as a scholarly finding.
3. Keep current synchronization scoped to GitHub and B2. Plan any archive
   migration separately before transferring or deleting preserved artifacts.

The [master plan](master-plan.md) remains the governing specification. The
[cloud runbook](final-discovery-cloud-runbook.md) defines the finalization and
delivery checks, and [the campaign specification](final-discovery-v1.md)
defines candidate interpretation and review obligations.
