# Project Echoes

Project Echoes is a reproducible computational biblical-studies research repository for token-level analysis of the Hebrew and Aramaic Old Testament and Greek New Testament. It is designed to recover established relationships as validation and generate traceable lexical, semantic, grammatical, structural, narrative, and intertextual candidates for disciplined human review.

The repository has completed **Milestone 5: passage segmentation**. It reproducibly derives clause, sentence, verse, two-verse, and five-verse passages from the validated MACULA Hebrew/Aramaic and Greek corpora under both `edition_complete` and `critical_core`, with separate Qere and Ketiv Hebrew streams. Exact token membership, reconstruction, disputed-text and reference-gap flags, analytical boundaries, and Ketiv structural uncertainty are queryable through Parquet and DuckDB. Two strict full-corpus runs reproduced run ID `passages-v1-00e261abea9ed44ef087`, 914,497 passages, 21,530,271 membership rows, and identical deterministic hashes. [ADR 0013](docs/decisions/0013-passage-identity-membership-and-analytical-continuity.md) records the identity and continuity design. Biblical source data and complete passage artifacts remain local and Git-ignored.

**Milestone 6: known-link benchmark is complete as of 2026-07-13.** Two complete builds reproduced benchmark run `benchmark-v1-dff1d3ef650c8ccd4930`, version `known-links-v1-dff1d3ef650c`, with identical logical hashes, counts, and content-table physical hashes. Each strict validation returned zero errors, zero warnings, and 18 informational source-reference findings. [PR #7](https://github.com/greg-oyan/project-echoes/pull/7) remains open and unmerged; its [CI run](https://github.com/greg-oyan/project-echoes/actions/runs/29235763865) succeeded for commit `a680c0b4c14cb6e3bab7e8b5305fd6a516ec37de` with the quality job completing in 32 seconds. The implementation is governed by [ADR 0014](docs/decisions/0014-known-link-benchmark-identity-tiering-mapping-and-leakage-control.md): OpenBible.info remains Tier 3 weak supervision and knownness support, source and mapping uncertainty remain visible, Tier 1 remains header-only, and splits and presumed negatives are leakage-aware infrastructure rather than scholarly truth. Milestone 7 has not begun.

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

## Passage workflow

The complete governed generation and validation commands are:

```bash
uv run echoes segment-passages --all --force
uv run echoes validate-passages --all --strict
uv run echoes passage-summary --all
```

For inspection without regenerating the corpus, use `echoes show-passage`,
`echoes reconstruct-passage`, and `echoes passage-membership` with a passage
ID. Generated schema-v1 Parquet lives under the Git-ignored
`data/processed/passages/schema-v1/`; the local DuckDB views are in
`data/processed/project_echoes.duckdb`. See [segmentation](docs/segmentation.md),
the [passage schema](docs/passage-schema.md), and the sanitized Milestone 5
report under `outputs/reports/` for the acceptance evidence.

## Known-link benchmark workflow

The governed Milestone 6 workflow uses the content-addressed OpenBible.info
snapshot `snapshot-2026-07-12-sha256-18e63e370308` under CC BY 4.0. Raw archive,
extracted source, normalized Parquet, and DuckDB data remain local and
Git-ignored. The tracked source audit contains aggregate and structural evidence
only.

```bash
uv run echoes acquire-source openbible-cross-references
uv run echoes verify-acquisition openbible-cross-references
uv run echoes ingest-benchmark --source openbible-cross-references --force
uv run echoes generate-benchmark-splits --all --force
uv run echoes generate-presumed-negatives --all --force
uv run echoes validate-tier1-quotations
uv run echoes validate-benchmarks --all --strict
uv run echoes benchmark-summary --all
```

`ingest-benchmark` is the single atomic materialization command: it stages and
publishes source records, relationships, endpoint mappings, leakage groups,
split assignments, presumed negatives, issues, and metadata together. The
`generate-benchmark-splits` and `generate-presumed-negatives` commands verify
the already materialized stages; they do not perform separate mutations or
create a second generation path.

The accepted local build contains 344,799 relationships, 689,598 endpoints,
1,379,196 mappings, 4,561,525 leakage memberships, 1,723,995 split assignments,
29,275 presumed negatives, 18 informational issues, and one metadata row. Its
persisted footprint is 672,790,515 bytes. See the benchmark documents for the
mapping, corpus-pair, hash, and two-build determinism evidence.

Use `echoes show-relationship` and `echoes show-benchmark-mapping` for
provenance and mapping inspection. See the [benchmark design](docs/benchmark-design.md),
[benchmark schema](docs/benchmark-schema.md), [Tier 1 curation instructions](docs/tier1-quotation-curation.md),
and [OpenBible source audit](outputs/reports/m6-openbible-source-audit.md). Tier 3
splits are weak-supervision infrastructure, generated negatives are only
presumed negatives, and the metric code is a tested contract rather than a
Milestone 6 performance result.

## Run manifests

The foundation CLI can generate a provenance-bearing empty run manifest:

```bash
uv run echoes create-run-manifest --experiment-name governance-smoke
```

## Data policy

Raw biblical text, external datasets, restricted sources, generated private research outputs, local databases, credentials, and API keys are excluded from Git. Source manifests contain tracked metadata and reviewed determinations, never the raw corpus. A source is not active merely because it is public or listed; it must pass the charter's activation rule, receive an immutable version and checksums, and have a reproducible acquisition and validation process.

MACULA Hebrew, MACULA Greek, the OSHB Ketiv/Qere supplement, and the exact OpenBible reference snapshot have passed their applicable source gates for reproducible local processing at their pinned revisions. Those validations do not authorize committing or publicly releasing raw corpora, complete processed token or benchmark tables, or reconstructable full-corpus passage text. Milestone 6 acceptance is recorded against the still-unmerged PR #7 and its successful CI run. STEPBible remains inactive with manifest status `under_review` under ADR 0012. Its deferral is not a rejection or licensing determination, and the source may be activated only after a later milestone demonstrates a specific need and completes exact-file provenance, licensing, benefit, and conflict-preserving integration review. Other registered sources remain inactive until they independently pass the same gate.

Repository software/documentation licensing remains pending owner selection. External texts, annotations, and reference collections retain their own source-specific licenses and attribution requirements.
