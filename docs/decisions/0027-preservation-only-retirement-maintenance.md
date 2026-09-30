# ADR 0027: Preserve remaining evidence before retiring the completed campaign's server

Date: 2026-09-29

Status: Accepted scope; execution and destructive cleanup verification pending.

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
