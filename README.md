# Project Echoes

Project Echoes is a reproducible computational biblical-studies research repository for token-level analysis of the Hebrew and Aramaic Old Testament and Greek New Testament. It is designed to recover established relationships as validation and generate traceable lexical, semantic, grammatical, structural, narrative, and intertextual candidates for disciplined human review.

The repository has completed **Milestone 2: MACULA Hebrew acquisition and ingestion**. It can reproducibly acquire and validate a pinned MACULA Hebrew snapshot, build canonical Hebrew/Aramaic token tables, and query them through Parquet and DuckDB. Biblical source data and full processed tables remain local and Git-ignored.

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

## MACULA Hebrew workflow

Milestone 2 uses the `WLC/nodes` representation from MACULA Hebrew release `25.08.11`, pinned to commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`. Acquisition verifies the approved source, immutable revision, expected 932-file inventory, and recorded hashes before ingestion. It never authorizes an unreviewed source or overwrites an existing snapshot without `--force`.

```bash
uv run echoes acquire-source macula-hebrew
uv run echoes verify-acquisition macula-hebrew
uv run echoes ingest-hebrew
uv run echoes validate-corpus --corpus hebrew
uv run echoes corpus-summary --corpus hebrew
```

The validated corpus contains 475,911 source records and canonical tokens across 39 books and 929 chapters. Derived forms preserve the source spelling separately, and every token records source version, file, native identifier, canonical reference, language, morphology, syntax, semantic fields, and ingestion provenance where supplied upstream. See [data sources](docs/data-sources.md), [normalization](docs/normalization.md), and the [canonical token schema](docs/canonical-token-schema.md) before using the tables.

Generated files are local:

- `data/raw/macula-hebrew/25.08.11/` contains the verified sparse acquisition and receipt.
- `data/processed/macula-hebrew/25.08.11/` contains versioned Parquet tables and their hashes.
- `data/processed/project_echoes.duckdb` exposes the corresponding query tables.

None of those paths is committed. Re-running the full ingestion from the same receipt and configuration produced the same run identity and logical table hashes.

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

Raw biblical text, external datasets, restricted sources, generated private research outputs, local databases, credentials, and API keys are excluded from Git. Source manifests contain tracked metadata and reviewed determinations, never the raw corpus. A source is not active merely because it is public or listed; it must pass the charter's activation rule, receive an immutable version and checksums, and have a reproducible acquisition and validation process.

MACULA Hebrew is the first source to pass that gate. Its approval covers reproducible local processing of the pinned 25.08.11 snapshot; it does not authorize committing or publicly releasing the raw corpus or complete processed token tables. Other registered sources remain inactive until they independently pass the same gate.

Repository software/documentation licensing remains pending owner selection. External texts, annotations, and reference collections retain their own source-specific licenses and attribution requirements.
