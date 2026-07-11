# Project Echoes

Project Echoes is a reproducible computational biblical-studies research repository for token-level analysis of the Hebrew and Aramaic Old Testament and Greek New Testament. It is designed to recover established relationships as validation and generate traceable lexical, semantic, grammatical, structural, narrative, and intertextual candidates for disciplined human review.

The repository has completed **Milestone 1: research and source governance**. No biblical corpus data has been downloaded, ingested, or activated.

## Governing documents

- [Master research and implementation plan](docs/master-plan.md)
- [Research charter](docs/research-charter.md)
- [Corpus scope and layered roles](docs/corpus-scope.md)
- [Data sources and provenance](docs/data-sources.md)
- [Data licensing governance](docs/data-licensing.md)
- [Agent instructions](AGENTS.md)

## Requirements and setup

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- Git

```bash
uv sync
uv run pre-commit install
uv run echoes version
```

`uv` reads `.python-version` and installs a managed Python 3.12 interpreter when needed. Direct and transitive dependencies are pinned in `uv.lock`.

## Governance validation

```bash
uv run echoes validate-config
uv run echoes validate-sources
uv run echoes list-sources
uv run echoes list-sources --role primary_discovery
uv run echoes list-sources --status under_review
uv run echoes show-source macula-hebrew
```

`validate-config` checks all general and experiment manifests. `validate-sources` enforces licensing, edition, version, hash, unique-ID, and raw-data policy rules and reports governance-state counts.

## Quality gate

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run echoes validate-config
uv run echoes validate-sources
```

## Run manifests

The foundation CLI can generate a provenance-bearing empty run manifest:

```bash
uv run echoes create-run-manifest --experiment-name governance-smoke
```

## Data policy

Raw biblical text, external datasets, restricted sources, generated research outputs, local databases, credentials, and API keys are excluded from Git. Source manifests contain metadata and preliminary determinations only. A source is not active merely because it is public or listed; it must pass the charter's activation rule, receive an immutable version and checksums, and have a reproducible acquisition and validation process.

Repository software/documentation licensing remains pending owner selection. External texts, annotations, and reference collections retain their own source-specific licenses and attribution requirements.
