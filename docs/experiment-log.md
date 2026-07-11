# Experiment log

## 2026-07-10 - Milestone 0 foundation smoke test

- Purpose: verify repository setup, typed configuration loading, CLI execution, and empty run-manifest generation.
- Corpus inputs: none.
- Models: none.
- Candidate generation: none.
- Result: recorded by the Milestone 0 quality commands and test suite.

## 2026-07-10 - Milestone 1 governance validation

- Purpose: fix research boundaries and validate source and experiment governance before acquisition.
- Corpus inputs: none.
- External downloads: none.
- Source records: ten metadata-only preliminary records.
- Literature inputs: five verified primary-source seed records and a provisional closest-project comparison.
- Implementation: strict Pydantic source and experiment manifests; duplicate and cross-field validation; source CLI reporting and filters.
- Artifacts: charter, corpus scope, source/licensing policy, decision records, literature matrix, prior-project comparison, tests, and CI gate.
- Result: Milestone 1 quality and governance commands pass; detailed results are tied to the milestone commit and CI run.
- Boundary: no acquisition, ingestion, segmentation, embeddings, or candidate analysis was performed.

## 2026-07-11 - Milestone 2 MACULA Hebrew ingestion validation

- Purpose: prove reproducible, provenance-preserving acquisition and canonical ingestion of the Hebrew/Aramaic primary corpus before any discovery analysis.
- Source: official MACULA Hebrew `WLC/nodes`, release `25.08.11`, immutable commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`.
- Acquisition: sparse checkout of 932 expected files; three tracked anchor SHA-256 hashes plus a Git-ignored receipt with hashes and sizes for every acquired file.
- Input/output boundary: raw XML, complete processed tables, and the local database remained under Git-ignored `data/`; only code, configuration, provenance metadata, aggregate statistics, tests with synthetic fixtures, and non-textual reports are publishable in this milestone.
- Implementation: streaming chapter adapter, stable canonical IDs, source/native provenance, explicit zero-width morphemes, deterministic Hebrew normalization, typed Parquet tables, transactional DuckDB loading, and independent corpus validation.
- Result: 475,911 source records mapped one-to-one to 475,911 tokens across 39 books and 929 chapters; 468,362 tokens are Hebrew and 7,549 are Aramaic; no lemma or morphology values are missing.
- Validation: the completed run reported zero errors and zero warnings. Its 6,435 ingestion findings are informational source-structure observations retained for audit, not suppressed parse failures.
- Reproducibility: repeated complete builds produced identical row counts, Parquet hashes, logical table hashes, and run ID `hebrew-7db8035c6ae1c3268074`. Transactional reloads produced no duplicate DuckDB rows.
- Resource note: an initial all-in-memory prototype exhausted process memory during the DuckDB phase. The final pipeline writes Parquet in chapter batches and performs database loading in a fresh process; subsequent end-to-end runs completed successfully without changing logical results.
- Manual review: configured references cover Torah, narrative, poetry, wisdom, prophets, Ezra/Jeremiah Aramaic, and the Daniel language boundary. Order, forms, annotations, language, references, and provenance agreed with the pinned source for the reviewed samples. Daniel 2:4 correctly contains the Hebrew-to-Aramaic transition.
- Variant limitation: the selected representation contains MACULA's preferred Qere and no complete parallel Ketiv layer; the resulting zero Ketiv/Qere-marked token count is documented as source scope, not a claim that the textual tradition has no variants.
- Models and candidate generation: none.
- Boundary: no MACULA Greek acquisition, supplementary annotation, segmentation, embedding, semantic-analysis, candidate-generation, or review-console work was performed.

Substantive experiments are prohibited until their prerequisite milestones and data-governance gates pass.
