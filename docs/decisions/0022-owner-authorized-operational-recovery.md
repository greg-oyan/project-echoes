# ADR 0022: Owner-authorized operational recovery with a fixed deadline

- Status: Accepted
- Date: 2026-09-20
- executing_agent: Codex

## Context

The owner explicitly authorized finishing the existing final-discovery
campaign with necessary repairs, authenticated artifact/receipt reuse, and
monitoring through verified delivery. Earlier repository instructions required
startup-only inspection, manual financial inputs, and repeated operational
stops. Billing API access with the existing least-privilege credential returned
HTTP 403. Earlier attempts to remove those gates were rejected by automatic
approval review; no rejected change was deployed and the instance was powered
off. The owner's subsequent explicit authorization removes dollar ceilings,
verified-cost/manual billing inputs, billing-API prerequisites, and repeated
approval requirements for operations already covered by this recovery.

The owner retains a 96-hour **overall** recovery limit, terminal/expiry
shutdown, protection of preserved evidence, and all scientific requirements.
A fresh 96-hour systemd allowance on every retry would violate that limit.

## Decision

Apply this exception only to recovery of the existing `final-discovery-v1`
campaign on the existing Scaleway instance `project-echoes-final-discovery`
in `nl-ams-1`. Finish and validate the local recovery changes before power-on.
No new cloud resources, destructive cleanup, expanded credentials, or new
scientific campaign are authorized. ADR 0021 governs authenticated reuse.

Continue bounded status inspections, diagnosis, necessary repairs, and
verified delivery without stopping merely after startup or at a historical
implementation milestone. A failed integrity or scientific check blocks
acceptance and requires correction, not a validation bypass. Run the worker
detached with preserved logs, launch records, and checkpoints. Keep
`Restart=no` and sole-worker enforcement; recoverable failures may be retried
only after diagnosis within the remaining recovery window.

Do not require a dollar cap, verified hourly rate, accrued-cost declaration,
manual billing acknowledgment, or billing API access. Do not invent cost data
or broaden provider permissions to compensate for the billing denial. Keep
actual permission checks, exact-target shutdown authorization, protected
credentials, resource limits, and scientific/data safeguards.

Anchor the window to the first recorded recovery boot,
`2026-09-21T02:46:42Z`, retained in the local `initial-diagnostic.txt` record.
The deadline is `2026-09-25T02:46:42Z`. The diagnostic boot counts toward
recovery; the upcoming restart cannot receive a fresh window. Install a
root-owned immutable recovery-window record at
`/var/lib/project-echoes/final-discovery/recovery-window.json`, binding that
start, its deadline exactly 96 hours later, the exact instance, and the
recovery work directory. The start and deadline cannot be reset by retries,
repairs, reinstallation, reboots, or powered-off time. The launcher sets
`RuntimeMaxSec` to remaining seconds and refuses an expired or inconsistent
window.

Use a native persistent systemd expiry timer with an absolute `OnCalendar`
deadline and a boot check. Its bounded expiry service invokes the existing
exact-instance poweroff service only once expiry is established; this is not
a new monitoring daemon. Check the deadline before launching or retrying.
Preserve the existing success poweroff behavior; an unrecoverable terminal
failure or expiry also requires poweroff. A recoverable worker failure alone
does not trigger immediate poweroff or renew the window. Poweroff preserves
the instance disks and all stage trees, logs, checkpoints, failure records,
and B2 artifacts. No deletion is implied.

Successful scientific worker completion still requires all 11 authenticated
stages, strict all-stage validation, exact durable B2 output verification,
and bound finalization receipts. Deliver the verified output and receipts,
distinguish statistically eligible Tier A from exploratory Tier B top 100,
and include actual passage-evidence examples. Retrieve from verified durable
outputs after success shutdown; any necessary instance access must remain
within the same recovery window. An empty Tier A is valid. Partial output
cannot be represented as completion.

## Consequences

`AGENTS.md`, the master plan, and the final-discovery runbook now state the
same scoped operational authority. Historical M7 scientific gates and
execution records are retained. Frozen source/configuration identities,
thresholds, detectors, null controls, tier rules, and package integrity checks
are unchanged. Dollar accounting no longer blocks this recovery; the
nonrenewable overall deadline and exact-instance shutdown remain mandatory.

This decision authorizes preparation and subsequent recovery within its
scope, not an assertion that deployment, execution, or delivery has occurred.

## Alternatives considered

- Retain the manual billing gate or add billing credentials: conflicts with
  the explicit recovery authorization and is unnecessary for execution.
- Reset a 96-hour worker limit on retry: fails the overall recovery limit.
- Remove scientific gates alongside operational stops: outside the
  authorization and incompatible with trustworthy results.
- Delete the instance on failure or expiry: would destroy preserved evidence;
  the authorized terminal action is poweroff.
