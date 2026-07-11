# Project Echoes

Project Echoes is a reproducible computational biblical-studies research repository for token-level analysis of the Hebrew and Aramaic Old Testament and Greek New Testament. It is designed to generate traceable candidate lexical, semantic, grammatical, structural, narrative, and intertextual relationships for disciplined human review.

The project is currently at **Milestone 0: repository foundation**. No biblical corpus has been acquired or activated.

## Governing specification

The complete staged research and implementation specification is preserved in [`docs/master-plan.md`](docs/master-plan.md). Contributors and automated agents must also follow [`AGENTS.md`](AGENTS.md).

## Requirements

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- Git

## Setup

```bash
uv sync
uv run pre-commit install
uv run echoes version
uv run echoes validate-config
```

`uv` reads `.python-version` and will install a managed Python 3.12 interpreter when necessary.

## Quality gate

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## Run manifests

Generate an empty, provenance-bearing Milestone 0 manifest with:

```bash
uv run echoes create-run-manifest --experiment-name foundation-smoke
```

Generated outputs, local databases, secrets, and source corpora are intentionally excluded from version control.

## License and source data

No reuse license has been selected yet; see [`LICENSE`](LICENSE). Biblical texts, annotations, and other external datasets retain their own licenses and must not be redistributed until their status is documented and approved during Milestone 1.
