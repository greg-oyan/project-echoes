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

Every token retains source ID and commit, source file and row, native identifier or recorded fallback, source word identifier, source-edition verse identifier, original surface, source positions, language, lemma, morphology, clause/phrase ancestry, semantic and participant fields, gloss, source attributes, schema/normalization versions, and ingestion run identity where applicable. Explicit source zero-width morphemes remain explicit zero-width records. Project token IDs derive only from source-edition book, chapter, verse, token/subtoken position, and native identity when variants require disambiguation; later crosswalks and alignments cannot rename them.

### Hebrew normalization

The original source form is immutable. Derived forms use deterministic Unicode NFD, whitespace collapse, and removal of the combining grapheme joiner. The pointed normalized form retains vowel points, cantillation, maqqef, paseq, sof pasuq, punctuation, final letters, orthographic distinctions, affix segmentation, divine-name forms, and any supplied Ketiv/Qere distinction. A separate unpointed form removes Hebrew vowel points and cantillation while preserving the other distinctions. No normalization changes the source field or fills a source-absent variant.

Supplied Ketiv and Qere readings remain separate canonical rows linked by a stable variant group. The root normalization setting selects `qere` or `ketiv` only for a derived analysis table/view, which recomputes continuous analysis positions after choosing one member of each complete pair. A lone available reading remains usable. Switching the selection leaves base IDs, counts, forms, provenance, and token-table hashes unchanged.

### Storage and validation

Chapter-batched typed Polars frames are written to versioned Parquet tables for tokens, books, source records, ingestion findings, and corpus metadata. Their physical file hashes and sorted logical table hashes are recorded. A separate process loads matching DuckDB tables transactionally and replaces the prior Hebrew tables so a rerun cannot append duplicate rows.

Validation checks the one-to-one source/token mapping, schema and provenance fields, canonical IDs and positions, book/chapter/verse coverage, Hebrew/Aramaic classification, normalization recomputation, zero-width rules, available Ketiv/Qere fields, annotation completeness, file and logical hashes, and DuckDB/Parquet agreement. The validated result contains 475,911 tokens across 39 books and 929 chapters: 468,362 Hebrew and 7,549 Aramaic. Lemma and morphology are present for every token.

Twelve configured manual samples span Torah, historical narrative, poetry, wisdom, major and minor prophets, Ezra and Jeremiah Aramaic, the Daniel language transition, segmentation, and the source's preferred-Qere behavior. These checks assess order, surface/derived forms, lemma, morphology, language, reference, and provenance against the pinned XML; they do not treat a small sample as proof of universal annotation correctness.

### Reproducibility result

At least two independent full builds from the same verified receipt and configuration produced the same 475,911 rows, ingestion run ID `hebrew-7db8035c6ae1c3268074`, Parquet hashes, and logical table hashes. Transactional DuckDB reloads preserved the same row counts and logical fingerprints. Synthetic fixtures also demonstrate that changing input traversal order does not change canonical identities or logical outputs, while changing governed configuration changes the run identity.

## Milestone 5

Milestone 5 derives comparison units without modifying the validated source or
supplement tables. The inputs are the pinned MACULA Hebrew/Aramaic and Greek
tables, the OSHB Ketiv supplement and structural mappings, the immutable corpus
digests, and schema-version-3 `config/segmentation.yaml`. Passage schema version
1 and passage-ID schema version 1 are governed by ADR 0013. No benchmark,
scoring, embedding, candidate-generation, or scholarly inference is part of
this milestone.

### Analytical streams and units

The generator materializes six stream contexts: Hebrew `edition_complete` and
`critical_core`, each with Qere and Ketiv readings, and Greek
`edition_complete` and `critical_core` with the source reading. Each context
produces source-native clauses and sentences, extant verses, and complete
two-verse and five-verse windows. Windows follow explicitly analytical
continuity between extant verse passages; they may cross chapters, never cross
books, never bridge a profile exclusion, and never join `MRK 16:20` to
`MRK 16:99`.

`passage_membership` is authoritative. Its ordered token IDs and one-based
positions reproduce passage identity, boundaries, reference sequence, counts,
reconstructed forms, and ordered features. Passage IDs hash a canonical payload
containing schema, corpus, profile, reading, granularity, book, scoped source
unit, exact references, and exact token membership. Run identity adds the
relevant configuration, selected scope, pinned source versions, and immutable
input digests, while excluding paths and execution telemetry.

Hebrew and Aramaic reconstruction groups source morphemes into words and
preserves source separators, punctuation, selected Qere/Ketiv readings, and
zero-width membership. Greek reconstruction uses the stored leading/core/
trailing punctuation and elision metadata. Missing analytical annotations stay
JSON null rather than becoming empty strings. Reconstruction validation
recomputes selected samples from membership instead of trusting stored text.

### Profiles, gaps, and uncertainty

`edition_complete` includes all text inline in the selected editions.
`critical_core` excludes exactly the longer ending of Mark (`MRK 16:9-20`),
the alternate ending (`MRK 16:99`), and the pericope adulterae
(`JHN 7:53-8:11`) without changing source records or positions. The fifteen
edition-omitted Greek verse numbers are not fabricated. Units that span an
omitted reference retain the extant reference sequence and set
`reference_gap=true`.

The Qere stream retains complete primary MACULA structure. Every Ketiv token is
present in the Ketiv verse and sentence analyses. Clause membership uses only
resolved supplementary mappings: 255 unresolved Ketiv clause tokens per
profile receive explicit `ketiv_clause_mapping_unresolved` exclusion rows and
remain in verse analysis. Tokens whose primary clause annotation is absent are
also recorded explicitly instead of disappearing. Intersecting passages carry
`ketiv_structural_uncertainty` for unresolved clause or phrase mappings.

### Storage and full-corpus acceptance

Typed, deterministically sorted Parquet is partitioned into book-sized leaves
under `data/processed/passages/schema-v1/`; DuckDB exposes external views over
the artifacts. Staged writes require explicit `--force`, atomically replace
only generated passage outputs, and recover the prior target on failed
replacement. The local artifacts remain Git-ignored.

Two complete strict runs over identical inputs reproduced segmentation run ID
`passages-v1-00e261abea9ed44ef087` and these exact table counts:

| Artifact | Rows | Logical SHA-256 |
|---|---:|---|
| `passages` | 914,497 | `00047c9dc16ceaefdc0ff1b18a8fb2b4480a1be0534ed861cf5c11706d2048a0` |
| `passage_membership` | 21,530,271 | `726c6b9339a78e7806bac90f7d91930c7f86bec7c7c0be6a51bdedb7a54d40bd` |
| `passage_adjacency` | 913,445 | `1ca8c79f92b2742e12586b6c72eaddbcc834d5bce818b909f33b2c10b9db69bd` |
| `segmentation_exclusions` | 148,948 | `6a0e475398e76730b5a7a92370ee319b803c0d17ba45e01b7155fa3b28c7e209` |
| `segmentation_issues` | 0 | `2f3a57eada1dda388ca99bf67cd0b6de70fb31afa1abc1980eafbf605359eac3` |
| `segmentation_metadata` | 1 | `87b88f0b3d4efa88c9d4668ba1eb0aba5fce244b0350130a033deb1a087578cf` |

Both strict validations reported zero errors, warnings, and informational
findings. All six logical hashes, all five content-table physical hashes, and
all 3,570 non-metadata leaf hashes agreed byte for byte. Generation runtimes
were 2,245.249 and 2,225.401 seconds; strict validation runtimes were 743.4 and
749.5 seconds. Both metadata rows reported 627,780,157 output bytes.

Runtime is observed provenance, not passage content. Accordingly, the metadata
Parquet physical hash changed between runs while its logical hash remained
stable under the registered telemetry-column exclusion. This is the sole
physical-hash exception and does not weaken content determinism.
