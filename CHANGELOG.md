# Changelog

All notable changes to Project Echoes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses semantic versioning once releases begin.

## [Unreleased]

### Added

- Milestone 6 known-link benchmark implementation completed on 2026-07-13:
  ADR 0014
  governs stable source-record, relationship, endpoint, pair, and mapping
  identities; strict benchmark configuration and ten typed Parquet/DuckDB
  artifacts preserve source direction, duplicate provenance, tier permissions,
  reference schemes, mapping uncertainty, leakage groups, deterministic
  non-row-random splits, presumed negatives, and evaluation-metric metadata.
  The CLI now supports governed benchmark ingestion, strict validation, Tier 1
  placeholder validation, split and presumed-negative generation, summaries,
  and relationship/mapping inspection. PR #7 remains open and unmerged at
  `https://github.com/greg-oyan/project-echoes/pull/7`; CI run
  `29235763865` succeeded for commit
  `a680c0b4c14cb6e3bab7e8b5305fd6a516ec37de`, with the quality job completing
  in 32 seconds. No Milestone 7 work has begun.

- Two complete Milestone 6 builds reproduced run
  `benchmark-v1-dff1d3ef650c8ccd4930`, benchmark version
  `known-links-v1-dff1d3ef650c`, every logical table hash, every content-table
  physical hash, and every row count. Wall times were 551.3 and 533.7 seconds;
  persisted pipeline runtimes were 501.93041979987174 and
  479.37766140000895 seconds. Both builds reported 672,790,515 bytes and strict
  validation returned zero errors, zero warnings, and 18 informational findings.
  Metadata Parquet differed physically only because it retains measured runtime
  telemetry; its registered logical content remained identical.

- The validated benchmark contains 344,799 source records and relationships,
  689,598 endpoints, 1,379,196 endpoint mappings, 4,561,525 leakage memberships,
  1,723,995 split assignments, 29,275 presumed negatives, 18 informational
  issues, and one metadata row. Mapping statuses are 639 profile exclusions,
  781 partial, 1,371,984 provisional, 5,756 missing-target, and 36 unresolved
  reference mappings. The source graph contains 187,117 OT–OT, 84,369 NT–NT,
  and 73,313 cross-testament relationships.

- The exact OpenBible.info Tier 3 snapshot
  `snapshot-2026-07-12-sha256-18e63e370308` was audited and acquired from the
  official cross-reference archive under CC BY 4.0. The archive SHA-256 is
  `18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492`;
  its sole extracted file has SHA-256
  `eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37`.
  All 344,799 observed records contain references and signed integer votes, not
  biblical quotation text. OpenBible remains weak supervision and broad
  knownness support only: it is not scholarly truth, primary evaluation, or a
  route to Tier 1.

- The project-curated Tier 1 quotation file remains the approved header and
  zero data rows. Its schema-v1 header-only SHA-256 is
  `7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b`.
  Typed future-row checks use synthetic fixtures only; population, independent
  scholarly review, and curation remain human work. No copyrighted UBS,
  Nestle-Aland, or comparable quotation appendix was copied or reconstructed.

- PR #6, the accepted Milestone 5 passage implementation, merged to `main` as
  `00f5e84a4a83227585bd77dd9a08a0567cd58a7f` before Milestone 6 began. Its
  post-merge source, corpus, supplement, and passage anchors remained unchanged.

- Milestone 5 passage segmentation: an accepted schema-v1 pipeline now derives
  clause, sentence, verse, two-verse, and five-verse units across six governed
  Hebrew/Aramaic and Greek profile/reading streams. ADR 0013 establishes
  content-derived passage identity, authoritative exact membership,
  language-aware reconstruction, distinct physical succession and analytical
  continuity, and explicit Ketiv sensitivity exclusions. Deterministic
  book-partitioned Parquet artifacts and transactional DuckDB views expose
  passages, 21,530,271 membership rows, adjacency, exclusions, issues, and run
  metadata; the CLI supports full or exact-scope generation, strict persisted
  validation, summaries, passage display, reconstruction, and membership
  inspection.

- Milestone 5 full-corpus acceptance produced run ID
  `passages-v1-00e261abea9ed44ef087` twice from the pinned inputs: 914,497
  passages, 913,445 adjacency rows, 148,948 explicit exclusions, zero
  segmentation issues, and one metadata row. Both strict validations completed
  with zero errors, warnings, or informational findings. All six logical table
  hashes, all five deterministic content-table physical hashes, and all 3,570
  non-metadata leaf hashes agreed. The metadata Parquet physical hash alone
  changed because it contains the measured runtime; its logical hash excludes
  that registered telemetry and remained stable. The two generations took
  2,245.249 and 2,225.401 seconds, each reporting 627,780,157 output bytes;
  strict validation took 743.4 and 749.5 seconds.

- Milestone 4 governance closure after PR #4 merged to `main` as
  `0eb04697eb2c3d6cb70a96e85ff25c4d0a44a27b`: the completed OSHB
  Ketiv/Qere supplement, generic beside-not-over annotation and
  conflict-preservation infrastructure, explicit Ketiv structural mappings,
  unresolved-alignment reporting, separate versification crosswalk,
  source-native identities, deterministic analysis streams, and unchanged
  primary-corpus digests now form the acceptance basis. ADR 0012 records the
  owner-approved deferral of STEPBible activation pending a demonstrated
  missing capability, exact-file selection, measurable benefit, file-level
  provenance and licensing review, and a conflict-preserving integration
  design. The deferral is neither rejection nor a licensing determination.
  Milestone 5 structural-uncertainty constraints are documented without
  implementing passage generation.

- Milestone 4 Part 1, OSHB Ketiv/Qere supplement (ADR 0009, ratified):
  governed canonical-byte acquisition of openscriptures/morphhb at pinned
  commit `3d15126` (42 files, externally verified anchors); a supplement
  adapter keying all 1,268 OSHB ketiv words into vacant MACULA word-number
  slots across 1,260 loci (1,245 paired, 6 ketiv-only, 9 qere-only) with
  zero gap violations, 1,254/1,254 exact qere-surface agreement, and zero
  conflicts; `variant_type=ketiv` canonical schema v2 tokens with IDs from
  the shared identity module and no collisions against either corpus; a
  queryable K/Q locus registry with per-locus alignment method and
  confidence (the Milestone 7 `data_quality_status` input); deterministic
  `analysis_reading=ketiv` stream substitution with the qere stream
  byte-identical to its pre-supplement state; a surface/lemma compatibility digest
  (`corpus_content_digest`) recorded for both corpora as permanent
  regression anchors alongside the identity digests; generalized
  supplementary annotation-alignment tables enforcing the beside-not-over
  contract with overwrite-attempt failure tests; the first governed
  versification-crosswalk instance (39 OSHB-to-MACULA book mappings with
  method and confidence); and a validated segmentation declaration of the
  initial MRK 16:20-to-16:99 source-order declaration, now superseded by the
  separate source-successor and forbidden analytical-boundary policy below.
  Hebrew and Greek identity digests, surface/lemma digests, and token counts
  (475,911 / 137,779) are unchanged throughout.

### Fixed

- PR #4 repair: OSHB Ketiv token identity now derives from the normalized
  source-native OSIS book identifier (`2Kgs` → `2KGS`) while canonical MACULA
  codes remain separate join keys; the supplement retains both reference
  schemes. A deterministic supplementary structural table maps Ketiv tokens
  to MACULA sentence, clause, and phrase units only through explicit Qere or
  two-sided adjacency consensus, preserving every boundary disagreement and
  leaving OSHB source-native syntax null. A versioned comprehensive analytical
  digest now protects stable Hebrew and Greek downstream fields beside the
  historical surface/lemma compatibility digest. The disputed-passage policy
  now separates source succession from analytical continuity, forbids Mark
  16:20/16:99 multi-verse windows, registers `edition_complete` and
  `critical_core` profiles, and pins reference-gap and future-candidate review
  rules without implementing Milestone 5 passage generation.

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

- Milestone 4 preparation (docs, schema, and tests only): a
  versification-crosswalk schema and validator with alignment method and
  confidence fields, cardinality-constrained mapping types (including
  unmatched, addition, and alternate-structure cases), no data rows, and
  synthetic-fixture tests proving invalid crosswalks fail;
  `docs/versification-crosswalk.md` covering the master plan section 10.5
  hazards; and `docs/milestone-4-execution-plan.md` enumerating the
  STEPBible subset-audit questions that require human licensing judgment,
  deliberately unresolved.

- Milestone 3 MACULA Greek ingestion: governed canonical-byte acquisition of
  release `24.06.17` (commit `b5b7ece`), ADR 0010 selecting the Nestle1904 node
  dataset over the annotation-incomplete SBLGNT representation, an active typed
  Greek normalization policy (lossless punctuation separation, preserved
  elision and crasis, accent-insensitive folded forms, preserved source
  accent regularization), a `WLC`-pattern Greek adapter emitting 137,779
  `GNT_` tokens through the shared source-edition-only identity module,
  Greek Parquet/DuckDB tables with a unified `unified_tokens` cross-corpus
  view, full GNT validation (27 books, 260 chapters, declared edition verse
  gaps, MRK 16:99 shorter ending), `ingest-greek`/`validate-corpus
  --corpus greek|unified`/`corpus-summary --corpus greek` CLI workflows,
  17 scripted spot checks with recorded expectations, an extended opt-in
  full-corpus regression, and a Milestone 3 ingestion report whose token
  count matches the pinned upstream test expectation.

- OSHB Ketiv/Qere governance: a pinned, license-verified `oshb-morphhb`
  manifest entry (supplementary role, planned lifecycle, CC BY 4.0 with public
  domain WLC text, no acquisition) and proposed ADR 0009 describing how OSHB
  ketiv records key into the word-number gaps MACULA preserves (verified at
  2KI 8:10 slot 6), producing `variant_type=ketiv` tokens per canonical schema
  v2 with the Qere stream unchanged, an alignment-confidence field, and
  preserved annotation conflicts. Limitations and review documentation now
  record the interim qere-only exposure and the rubric question 14
  textual-variant obligation.

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
- STEPBible and all bridge, textual-witness, and reception sources remain
  inactive. The Milestone 6 local build and determinism gates are validated,
  and its still-unmerged PR #7 has successful CI acceptance evidence. No
  Milestone 7 lexical scoring, embedding, semantic analysis, candidate
  generation, or review-console work has begun.
- Most registered sources still have incomplete licensing or acquisition reviews, as recorded explicitly in `data/manifests/sources.yaml`.
