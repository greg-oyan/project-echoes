# Project Echoes agent instructions

- Read `docs/master-plan.md`; it is the sole governing implementation specification.
- Obey the current milestone, build order, and acceptance gate, and stop when a gate is unmet.
- Never commit restricted source data, credentials, API keys, secrets, or local research databases.
- Record material deviations through an ADR in `docs/decisions/` and an entry in `CHANGELOG.md`.
- Never monitor a local computation continuously. Never use polling or sleep loops for pipeline status.
- Commands expected to exceed ten minutes must be launched detached with logs, PID metadata, checkpoints, and a one-shot status command. After launching, perform only one startup verification after a brief bounded check. Return control to the user while the operating system runs the computation. Never delete preserved staging or checkpoints without explicit user authorization.
