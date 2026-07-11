# Changelog

All notable changes to Project Echoes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses semantic versioning once releases begin.

## [Unreleased]

### Added

- Milestone 1 substantive research charter, layered corpus scope, source/provenance policy, and licensing procedure.
- Strict source-manifest schemas with lifecycle, license, edition, version, hash, duplicate-ID, and raw-data Git-policy validation.
- Preliminary metadata-only governance records for ten planned primary, bridge, supplementary, benchmark, validation, and reception sources.
- `validate-sources`, `list-sources`, and `show-source` CLI commands with filtering and governance summaries.
- Full experiment-governance schema and migrated planned experiment manifests.
- Four accepted decision records, a five-project prior-work comparison, methodological-trap register, and machine-readable literature matrix.
- Fixture-based unit and integration coverage for source and experiment governance failures.
- Source validation in the Makefile, pre-commit gate, and GitHub Actions workflow.

- Milestone 0 repository structure, Python 3.12 `uv` environment, and dependency lock.
- Typer CLI with version, configuration validation, and run-manifest generation commands.
- Pydantic-backed configuration schemas and structured JSON logging.
- Unit and integration tests, Ruff, mypy, pre-commit, and GitHub Actions quality checks.
- Governing master plan, agent instructions, and initial documentation skeleton.

### Known limitations

- No corpus has been downloaded or ingested; source versions, expected files, and hashes remain empty until governed acquisition.
- Most source licensing reviews remain incomplete, as recorded explicitly in `data/manifests/sources.yaml`.
