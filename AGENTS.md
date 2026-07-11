# Project Echoes agent instructions

`docs/master-plan.md` is the governing specification for this repository.

All future Codex sessions must:

- Work on exactly one milestone at a time and respect the master plan's build order.
- Never skip or weaken a milestone acceptance gate.
- Run the relevant tests, linting, formatting checks, type checks, and CLI validations before committing.
- Preserve source, token, experiment, model, licensing, and decision provenance.
- Never commit restricted biblical source data, credentials, API keys, local databases, or generated private research data.
- Record important decisions in `docs/decisions/`, unresolved issues in `docs/limitations.md`, and completed work in `CHANGELOG.md` and `docs/experiment-log.md`.
- Keep the repository runnable and deterministic after every milestone.
- Stop at the current milestone gate when any acceptance criterion remains unsatisfied.

When a local instruction conflicts with the master plan, document the conflict and follow the master plan unless the repository owner explicitly changes the governing specification.
