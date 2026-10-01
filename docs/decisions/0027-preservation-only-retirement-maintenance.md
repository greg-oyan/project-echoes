# ADR 0027: Preserve remaining evidence before retiring the completed campaign's server

Date: 2026-09-29

Status: Cleanup, preservation and final closeout authenticated; stopped state
owner-reported; resource deletion not performed.

## Context

The existing `final-discovery-v1` campaign completed all eleven computational
stages and passed its retained scientific validation. The September 24 handoff
delivered selected review artifacts and authenticated the remote final package
and terminal checkpoint inventories. That narrow verification did not establish
the full cleanup gate or preserve all failed-attempt and staging evidence.

The owner separately requested preservation of server-only evidence, passing the
existing cleanup verification, and retirement of Scaleway while retaining B2.
On September 29 the owner resumed this work and selected rescue mode. This is
maintenance of a completed campaign, not authorization for another experiment.
The original September 25 recovery deadline is expired and remains unchanged.

The unchanged cleanup verifier exited successfully on September 30 at
`2026-09-30T02:54:48Z`. Its retained finalization receipt SHA-256 is
`e4fa585a842175063be93397fc71e85e01f2247ac5a12be9123a63e4621b394d`.
This establishes the cleanup check, not completion of the broader preservation
job. The owner subsequently requested poweroff as soon as that job finishes,
without waiting until the maintenance deadline.

## Decision

Use the provider's rescue operating system to access the exact original volume
without starting the installed scientific operating system. Authenticate the
rescue connection, provider identity, volume and filesystem identity before
accessing protected credentials or running maintenance. Preserve the original
recovery ledger, shutdown timer, production source commit and all scientific
artifacts unchanged.

Bound this preservation-only session to twelve hours from its rescue boot using
both UTC and system uptime, with a separate maintenance ledger and provider
poweroff safeguard. Reinvoking a helper must not reset that deadline. An expired
or interrupted maintenance session requires a new explicit owner decision; it
does not renew the scientific recovery window. No scientific worker may start.

Run the original production cleanup verifier unchanged in the original
filesystem environment. Retain its output, failure records and successful
receipt. A passing narrow inventory check, local helper test or archival upload
does not substitute for this gate.

Preserve all required earlier work, staging, checkpoints, failure evidence,
operational records and identified bootstrap scripts in a fresh private B2
namespace. Preserve hardlink relationships, authenticate exact archive member
coverage, and verify uploaded bytes by complete download and comparison with
source content. Keep existing final/checkpoint prefixes intact. Credentials and
restricted artifacts must never enter the public repository.

Commands expected to exceed ten minutes run detached with logs, PID metadata,
checkpoints, a runtime limit within the maintenance window and a one-shot status
command. Perform one startup check and return control; do not poll pipeline
status continuously. Preserve partial archives and failed attempts.

After successful controller completion, a separate completion action may
request poweroff of the exact instance once it authenticates the cleanup
receipt, complete evidence-preservation receipt, operational audit supplement
and their verified B2 readbacks. First retain and verify a final closeout of the
completion marker, closed controller logs and poweroff intent in a fresh private
B2 namespace. Attach this action without restarting or changing the running
worker. Missing or inconsistent completion evidence must refuse early poweroff.
The unchanged twelve-hour fallback was `2026-09-30T14:29:49Z` for this rescue
boot; early completion does not extend it. This completion action deletes no
instance, volume, IP reservation, local evidence or B2 object. An accepted
poweroff request does not establish that the provider has stopped the instance.

Retirement is authorized only after the unchanged cleanup gate passes and all
required evidence and small verification receipts are verified off-server.
Then retire only the dedicated instance, its identified SBS volume and its IP
reservations; independently verify their absence. Provider permissions remain
an actual prerequisite. B2 is retained. No deletion has occurred merely because
this decision is recorded.

## Consequences

Private maintenance tooling is separate from frozen production science. The
final public record must distinguish completed computation, human review,
preservation, cleanup verification and actual resource retirement. Human review
is still incomplete. Final receipts, not this authorization, establish execution
success.

The completion poweroff action was armed at `2026-09-30T05:21:41Z` as a runtime
`OnSuccess` hook. The retained arming record confirms the loaded hook, unchanged
active controller process and active fallback timer. Eighteen offline checks,
unit validation and a harmless live completion-event test passed. Preservation
was still running at that arming snapshot.

The final closeout recorded at `2026-09-30T05:43:19.032752Z` was downloaded from
the authenticated B2 object at `2026-10-01T04:35:19.257195Z`. The 97,310-byte
receipt has SHA-256
`e6d52a166d2611cd28285cbfd0466ae66ae7b524c657a0083dbe17cce4cccc79`.
Independent local verification passed its embedded hashes, unchanged cleanup
receipt, successful worker completion, complete preservation receipts,
operational audit supplement and final log-closeout bindings. The retained
proofs cover 207,103 source entries in 27 shards and 114 compressed parts,
totaling 106,531,871,127 compressed bytes. Their original full-download readback
proofs are authenticated; this local closeout check did not download or rehash
the complete archives again. This satisfies the cleanup and preservation
evidence gate for the conditionally authorized exact-resource retirement.

The owner reports the instance stopped on September 30. The closeout preserves
poweroff intent and does not prove execution of the provider action or the
latest provider state. No instance, volume or IP reservation has been deleted,
and no resource absence is claimed. B2 remains retained. Exact-resource
retirement still requires the applicable provider permissions and independent
absence verification under this decision. No new scientific or human-review
acceptance is established.
