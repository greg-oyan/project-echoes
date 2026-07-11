# Changelog

All notable changes to Project Echoes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses semantic versioning once releases begin.

## [Unreleased]

### Fixed

- Canonical-byte checksum remediation: the Milestone 2 SHA-256 inventory had been
  computed on a Windows text-mode (CRLF) checkout. Acquisition checkouts now disable
  Git text conversion (`core.autocrlf=false` plus a `* -text` attributes rule), the
  932-file MACULA Hebrew inventory and manifest anchor hashes were recomputed from the
  pinned commit's canonical bytes and externally verified, `validate-sources`
  recomputes canonical hashes when raw data is present locally, and the regenerated
  Milestone 2 report retains the superseded text-mode inventory. The corpus identity
  digest `91e923e6…` and the 475,911 token count were unchanged, and the opt-in
  full-corpus regression now asserts both.

### Added

- Approved pre-Milestone-3 methodology amendments: source-edition-only token
  identity, non-destructive Ketiv/Qere analysis streams, tiered benchmark
  governance, version 1 Septuagint rescoping, empirical null requirements,
  conjunctive rare-evidence rules, English-feature ablation, Pauline chronology,
  Output J, blank milestone time budgets, and thin multi-agent handoff files.
- ADR 0008 records the amendment, its corrections, affected milestones,
  consequences, rejected alternatives, date, and executing agent.
- Full local schema-v2 validation preserved all 475,911 token identities exactly,
  produced a continuous Qere analysis stream, and passed with zero errors or
  warnings; the synthetic paired-reading suite exercises both configured streams.

- Milestone 2 governed MACULA Hebrew acquisition pinned to release `25.08.11` and commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`, with sparse checkout, non-overwrite behavior, a 932-file receipt, and SHA-256 verification.
- A typed MACULA `WLC/nodes` adapter that maps 475,911 Hebrew/Aramaic source records one-to-one into stable canonical tokens across 39 books and 929 chapters while retaining native identifiers and source provenance.
- Documented Hebrew normalization with immutable source forms, NFD-derived forms, explicit cantillation/vowel handling, combining-grapheme-joiner removal in derived values, and explicit zero-width morphemes.
- Versioned Parquet corpus tables, transactional DuckDB loading, logical and physical table hashes, stable run identities, duplicate prevention, and corpus summary queries.
- `acquire-source`, `verify-acquisition`, `ingest-hebrew`, `validate-corpus`, and `corpus-summary` CLI workflows with safe defaults and machine-readable output modes.
- Full-corpus validation for source/token identity, canonical references and order, coverage, language, normalization, provenance, annotation completeness, hashes, and Parquet/DuckDB agreement.
- Synthetic-fixture unit and integration tests for acquisition safety, adapter edge cases, normalization, deterministic storage, transactional reruns, CLI behavior, and clear failure paths without committing biblical source data.
- MACULA Hebrew licensing and source-selection decisions, canonical-token and normalization documentation, manual spot checks, reproducibility evidence, and a Milestone 2 ingestion report.

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

- MACULA Hebrew normally supplies its preferred Qere reading rather than complete parallel Ketiv material, so the pinned representation cannot support exhaustive Ketiv/Qere comparison.
- Raw MACULA files and full processed token tables remain local and Git-ignored; public redistribution requires a separate field-level rights and attribution review.
- MACULA Greek and every downstream source remain inactive, and no segmentation, embedding, semantic-analysis, candidate-generation, or review-console milestone has begun.
- Most registered sources still have incomplete licensing or acquisition reviews, as recorded explicitly in `data/manifests/sources.yaml`.
