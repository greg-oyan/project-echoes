# Project Echoes agent instructions

- Read `docs/master-plan.md`; it is the sole governing implementation specification.
- Obey the current milestone, build order, and scientific acceptance gate. The owner-authorized final-discovery recovery exception below governs operational stopping and monitoring.
- Never commit restricted source data, credentials, API keys, secrets, or local research databases.
- Record material deviations through an ADR in `docs/decisions/` and an entry in `CHANGELOG.md`.
- Outside the current final-discovery recovery, never monitor a local computation continuously or use polling or sleep loops for pipeline status.
- Commands expected to exceed ten minutes must be launched detached with logs, PID metadata, checkpoints, and a bounded status command. Outside the current recovery, perform only one startup verification after a brief bounded check and return control to the user. Never delete preserved staging or checkpoints without explicit user authorization.

## Current final-discovery recovery authorization

The owner's 2026-09-20 authorization, incorporated into `docs/master-plan.md`
and ADR 0022, permits completion of the existing campaign, necessary repairs,
authenticated reuse of preserved stages/receipts, and continued bounded
monitoring through verified delivery. Do not stop solely at startup or a
historical implementation milestone, or request repeated authorization for
work already covered by this recovery. A failed scientific or integrity check
still blocks acceptance; investigate and repair within the authorized scope
without bypassing the check or altering frozen scientific policy.

Dollar ceilings, manually verified rates/accrued costs, and billing-API access
are not prerequisites for this recovery. Enforce one persistent overall
96-hour window anchored to the first recorded recovery boot,
`2026-09-21T02:46:42Z`, with fixed expiry `2026-09-25T02:46:42Z`; retries,
downtime, and repairs cannot reset or extend it.
Do not power on until the recovery changes and safeguards are ready. Power off
the exact existing instance after success, an unrecoverable terminal failure,
or expiry, preserving all evidence. Actual provider permissions, exact-target
checks, data protection, resource limits, and scientific acceptance gates
remain mandatory. This exception does not authorize a new campaign or
destructive cleanup. See `docs/final-discovery-cloud-runbook.md`.
