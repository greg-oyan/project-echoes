# Methodology

## Milestone 0

Milestone 0 establishes reproducible infrastructure only. Configuration is strict and versioned, dependencies are locked, generated manifests record repository and environment state, and the quality gate runs formatting, linting, typing, and tests.

No corpus, detector, embedding model, alignment, or candidate-generation method is active. Configuration entries for later work are declarations of intent, not implemented research methods or evidence.

## Reproducibility assumptions

- Python is fixed to the 3.12 series through `.python-version` and `pyproject.toml`.
- Direct and transitive Python dependencies are fixed by exact requirements and `uv.lock`.
- Configuration parsing rejects undocumented fields.
- A run manifest records configuration and lockfile hashes, Git state, Python version, hardware summary, model declarations, warnings, and errors.
- Generated outputs are local and excluded from Git unless a later milestone explicitly approves a publishable derived artifact.

Corpus methodology begins only after the research and governance gate in Milestone 1; Milestone 2 introduces the first governed corpus process below. Experimental discovery methods remain inactive.

## Milestone 1

Milestone 1 fixes the research charter, corpus roles, evidentiary language, source lifecycle, and methodology change control before data selection can be influenced by attractive results. Source records are strict metadata documents: unresolved values are explicit `null` or enum states, unsafe lifecycle transitions fail, and no record is equivalent to activation.

The preliminary literature comparison uses primary papers and project repositories. It identifies known component methods and methodological traps; it supports only a provisional integration statement. The literature matrix will expand before candidate-level novelty review.

Experiment YAML now records research questions, inputs, methods, parameters, evaluation data, outputs, acceptance criteria, prohibited claims, seed, and lifecycle status. These are governance declarations only; no listed experiment is implemented in Milestone 1.

## Milestone 2

Milestone 2 implements only MACULA Hebrew acquisition, canonical ingestion, normalization, storage, and validation. It performs no Greek ingestion, downstream segmentation, embeddings, semantic search, candidate generation, or scholarly inference.

### Acquisition and source identity

The input is the official MACULA Hebrew `WLC/nodes` representation from release `25.08.11`, pinned to commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`. A sparse checkout acquires only the upstream README, license, and node files. Before ingestion, the acquisition layer verifies source approval, the immutable commit, a 932-file inventory, required anchor hashes, and a receipt containing the size and SHA-256 hash of every local input. Existing acquisitions are not overwritten without an explicit force option.

The 25.08.11 snapshot was selected instead of a mutable latest release because it is a stable pre-SILHA version whose component notices could be reviewed for this milestone. Any later release is a new governed input and requires a new receipt, validation, and licensing determination.

### Parsing and canonical identity

The adapter streams the 929 chapter XML files in canonical book order and consumes the preferred source tree. Each of the 475,911 upstream morpheme records produces exactly one canonical token. Project identifiers have the form `HB_<BOOK>_<CHAPTER>_<VERSE>_<WORD>.<SUBTOKEN>` and derive from canonical location rather than file traversal or table row order. Duplicate native identifiers, duplicate canonical positions, ID collisions, malformed references or morphology, missing identifiers, and alternate source trees are surfaced as structured findings rather than silently repaired.

Every token retains source ID and commit, source file and row, native identifier or recorded fallback, source word identifier, original surface, canonical reference and token positions, language, lemma, morphology, clause/phrase ancestry, semantic and participant fields, gloss, source attributes, schema/normalization versions, and ingestion run identity where applicable. Explicit source zero-width morphemes remain explicit zero-width records.

### Hebrew normalization

The original source form is immutable. Derived forms use deterministic Unicode NFD, whitespace collapse, and removal of the combining grapheme joiner. The pointed normalized form retains vowel points, cantillation, maqqef, paseq, sof pasuq, punctuation, final letters, orthographic distinctions, affix segmentation, divine-name forms, and any supplied Ketiv/Qere distinction. A separate unpointed form removes Hebrew vowel points and cantillation while preserving the other distinctions. No normalization changes the source field or fills a source-absent variant.

### Storage and validation

Chapter-batched typed Polars frames are written to versioned Parquet tables for tokens, books, source records, ingestion findings, and corpus metadata. Their physical file hashes and sorted logical table hashes are recorded. A separate process loads matching DuckDB tables transactionally and replaces the prior Hebrew tables so a rerun cannot append duplicate rows.

Validation checks the one-to-one source/token mapping, schema and provenance fields, canonical IDs and positions, book/chapter/verse coverage, Hebrew/Aramaic classification, normalization recomputation, zero-width rules, available Ketiv/Qere fields, annotation completeness, file and logical hashes, and DuckDB/Parquet agreement. The validated result contains 475,911 tokens across 39 books and 929 chapters: 468,362 Hebrew and 7,549 Aramaic. Lemma and morphology are present for every token.

Twelve configured manual samples span Torah, historical narrative, poetry, wisdom, major and minor prophets, Ezra and Jeremiah Aramaic, the Daniel language transition, segmentation, and the source's preferred-Qere behavior. These checks assess order, surface/derived forms, lemma, morphology, language, reference, and provenance against the pinned XML; they do not treat a small sample as proof of universal annotation correctness.

### Reproducibility result

At least two independent full builds from the same verified receipt and configuration produced the same 475,911 rows, ingestion run ID `hebrew-7db8035c6ae1c3268074`, Parquet hashes, and logical table hashes. Transactional DuckDB reloads preserved the same row counts and logical fingerprints. Synthetic fixtures also demonstrate that changing input traversal order does not change canonical identities or logical outputs, while changing governed configuration changes the run identity.
