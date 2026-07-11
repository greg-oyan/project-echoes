# Contributing

Read [`docs/master-plan.md`](docs/master-plan.md) and [`AGENTS.md`](AGENTS.md) before making changes. Work on one approved milestone at a time and do not cross its acceptance gate prematurely.

## Development workflow

1. Create a focused branch.
2. Run `uv sync`.
3. Make the smallest complete change for the active milestone.
4. Add or update tests and documentation with the implementation.
5. Run the full quality gate:

   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src
   uv run pytest
   uv run echoes validate-config
   ```

6. Record decisions, unresolved issues, and user-visible changes before committing.

Never commit source texts or annotations unless their license and redistribution status have been reviewed and recorded. Never commit API keys, credentials, local databases, or generated private research artifacts.
