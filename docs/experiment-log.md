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

## 2026-07-11 - Pre-Milestone-3 token-identity and reading-stream amendment

- Purpose: verify that the approved source-edition identity and non-destructive Ketiv/Qere policy can be introduced without changing any existing full-corpus token identity.
- Implementation: canonical schema version 2 adds the preserved source-edition verse reference and variant relationship fields; normalization configuration version 3 adds a `qere`/`ketiv` derived-stream selection; a separate analysis Parquet table and DuckDB view hold continuous selected-stream positions.
- Fixture result: a legally safe synthetic pair retains distinct Ketiv and Qere rows, IDs, source/normalized forms, and provenance under both settings. Switching the setting selects the corresponding row with identical deterministic analysis positions while the base token table and its hashes remain unchanged. A lone supplied reading remains analyzable.
- Full-corpus result: a governed rebuild from the existing verified receipt produced 475,911 source records and 475,911 base tokens across 39 books, 929 chapters, and 23,213 verses, with 468,362 Hebrew and 7,549 Aramaic records. Validation reported zero errors and zero warnings.
- Identity comparison: SHA-256 over ordered `token_id`, `source_record_id`, and `source_word_id` triples was `91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6` both before and after the amendment.
- Derived stream: the configured Qere stream contains 475,911 rows with continuous corpus positions 1 through 475,911; run ID is `hebrew-0b2cbc267086537c407a`.
- Local Ketiv/Qere spot check: 2 Kings 8:10 contains 18 preserved source-edition records and no variant group in release 25.08.11. No source text was recorded. This confirms that the selected MACULA representation supplies only its preferred analysis there; it does not justify reconstructing a missing Ketiv record or claiming that the tradition has no variant.
- Boundary: no source was reacquired, no raw or processed corpus artifact was tracked, and no Greek, Septuagint, benchmark population, scoring, semantic, or review engine was started.

## 2026-07-11 - Canonical-byte checksum remediation

- Purpose: replace the Milestone 2 SHA-256 inventory, which was computed on a Windows text-mode (CRLF) checkout, with hashes over the pinned commit's canonical bytes, without changing any token identity.
- Root cause: the acquisition sparse checkout inherited `core.autocrlf=true`, so Git rewrote LF to CRLF in text-classified files before hashing. External verification showed `README.md` and `LICENSE.md` manifest hashes matched the pinned commit's raw bytes only after LF-to-CRLF conversion.
- Remediation: acquisition checkouts now set `core.autocrlf=false` and declare `* -text` in `.git/info/attributes`; HTTP acquisitions already hashed the download stream. The source was re-fetched at pinned commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4` and the full 932-file inventory recomputed from canonical bytes (381,774,487 total bytes). The three manifest anchors were externally verified against `raw.githubusercontent.com` at the pinned commit.
- Validator: `echoes validate-sources` now recomputes canonical hashes for manifest-hashed files whose raw data is present locally; synthetic-fixture tests cover matching bytes, CRLF-rewritten bytes, missing files, and absent local data.
- Result: re-ingestion from canonical-byte raw data produced 475,911 source records and 475,911 tokens across 39 books and 929 chapters with zero validation errors or warnings; run ID `hebrew-9e089f330652392a0dff` (run IDs incorporate raw-file hashes and therefore changed).
- Identity gate: the corpus identity digest (SHA-256 over corpus-position-ordered `token_id\0source_record_id\0source_word_id\n` triples, now implemented as `echoes.corpus.validation.corpus_identity_digest`) was `91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6`, identical to the pre-remediation value, and the opt-in full-corpus regression now asserts it permanently.
- Superseded artifacts: the text-mode inventory is retained, marked superseded, as an appendix inside the regenerated Milestone 2 ingestion report; the superseded values must never be used for verification.
- Boundary: no normalization, schema, or token-identity semantics changed; only acquisition byte handling, hash records, validation, and documentation.

## 2026-07-11 - Milestone 3 MACULA Greek ingestion validation

- Purpose: prove reproducible, provenance-preserving acquisition and canonical ingestion of the Greek New Testament primary corpus and unified cross-corpus queryability before any discovery analysis.
- Source: official MACULA Greek `Nestle1904/nodes`, release `24.06.17`, immutable commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`, selected by ADR 0010 after verifying the SBLGNT representation's documented annotation gaps.
- Acquisition: canonical-byte sparse checkout of 29 expected files (381,774,487-byte Hebrew re-acquisition pattern reused); three tracked anchor SHA-256 hashes externally verified against the pinned commit's raw bytes plus a Git-ignored receipt for every file.
- Result: 137,779 source records mapped one-to-one to 137,779 `GNT_` tokens across 27 books, 260 chapters, and 7,943 verses, exactly matching the count asserted by the pinned upstream test suite (`test/test_nestle1904_nodes.py`). Validation reported zero errors and zero warnings; run ID `greek-c35c0121a2fea8b057cd`.
- Normalization: punctuation separated losslessly (18,552 punctuation-bearing tokens; reconstruction validated per token), 1,223 elided tokens with elision marks kept in the word core, crasis preserved as single tokens, folded accent-insensitive forms derived, and the edition's accent-regularized `NormalizedForm` preserved separately (37,183 tokens differ from the punctuation-separated surface, evidencing preserved grave/enclitic accentuation).
- Versification: fifteen edition-omitted verses declared and verified; the pericope adulterae is present inline (JHN 7:53-8:11, 190 tokens); the shorter ending of Mark is encoded at MRK 16:99 (33 tokens). Both disputed-passage handlings are recorded and flagged for human review, not decided.
- Unified tables: the `unified_tokens` DuckDB view exposes 613,690 rows (475,911 Hebrew + 137,779 Greek) over the shared canonical columns with distinct corpus and provenance values and no token-ID collisions; cross-corpus, duplicate-prevention, and transactional-rerun tests pass on synthetic fixtures and the full corpora.
- Scripted spot checks: 17 of 17 assertions passed with expected values recorded in the Milestone 3 ingestion report (Synoptic samples, John, Romans, James, Revelation, enclitic/punctuation/elision cases, and the disputed-passage and versification cases).
- Boundary: no supplementary annotation, versification-crosswalk data, segmentation, embedding, candidate-generation, or review-console work was performed.

## 2026-07-11 - Milestone 4 Part 1 content-digest baseline

- Purpose: fix whole-corpus content fingerprints for both primary tables before any supplementary layer touches the repository, so Milestone 4 work can prove the base MACULA tables remain byte-identical.
- Encoding: `corpus_content_digest` is the SHA-256 over corpus-position-ordered `token_id\0surface_form\0normalized_form\0lemma\n` rows encoded UTF-8, with a null lemma encoded as the empty string; one shared implementation serves both corpora alongside the existing `corpus_identity_digest` (`token_id\0source_record_id\0source_word_id\n`).
- Recorded constants (asserted by the opt-in full-corpus regression):
  - Hebrew identity `91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6`, content `7fb443c3f0c42ada5d89f3abad61dd304145863044107ac86277c9f05f76cc82`, 475,911 tokens.
  - Greek identity `9035fea8d73a2b2078ad2adc70f8389040dbe2051ee535b2ce88412f551df6f2`, content `a5ede58d287c2d29d5dacc7adeb07ff5c6a10587e2949875928b2dd935c8c683`, 137,779 tokens.
- These constants are stop-condition anchors for every later Milestone 4 task.

## 2026-07-11 - Milestone 4 Part 1 OSHB Ketiv/Qere supplement validation

- Purpose: land the first supplementary annotation layer (ADR 0009, ratified) beside the untouched primary corpora and prove the vacant-slot keying premise empirically before implementation.
- Source: openscriptures/morphhb at pinned commit `3d15126fb1ef74867fc1434be1942e837932691f`, canonical-byte acquisition of 42 files with externally verified anchors; OSHB header confirms WLC 4.20, the same edition MACULA represents.
- Premise verification (pre-implementation study, reproduced by the shipped adapter): 1,108/1,108 K/Q verses frame-match (MACULA present word numbers equal OSHB slots minus ketiv slots); 0 gap violations; 1,254/1,254 qere surfaces exactly equal MACULA under NFC; 0 MACULA gaps outside K/Q verses; the only structural oddities are non-variant notes inside ketiv runs at Jer 48:44, Job 38:1, and Job 40:6, handled by the adjacency rule.
- Result: 1,260 loci (1,245 paired, 6 ketiv-only, 9 qere-only) yielding 1,268 `variant_type=ketiv` schema v2 tokens with OSHB provenance and zero token-ID collisions against 475,911 Hebrew and 137,779 Greek IDs; zero conflicts recorded (conflict paths proven on synthetic fixtures); 120 informational language-inferred warnings for Aramaic-passage ketiv tokens; run ID `oshb-kq-c464b2dbc5818b2532f8`.
- Streams: the supplemented `ketiv` analysis stream substitutes OSHB readings at all paired loci with continuous deterministic positions; the `qere` stream is byte-identical to its pre-supplement state.
- Digest gate: Hebrew identity `91e923e6…`/surface-lemma `7fb443c3…` and Greek identity `9035fea8…`/surface-lemma `a5ede58d…` all unchanged; these compatibility digests were newly baselined this run (SHA-256 over corpus-position-ordered `token_id\0surface_form\0normalized_form\0lemma\n` rows, null lemma as empty string) and are asserted by the opt-in regression.
- Infrastructure: generalized supplementary annotation-alignment tables (1,254 qere_surface rows, all agreeing) enforcing the beside-not-over contract; first governed versification-crosswalk instance with 39 book mappings; the initial MRK 16:20→16:99 source-order declaration was later superseded by the explicit source-successor and forbidden analytical-boundary policy recorded in the 2026-07-12 repair entry.
- Sanity: 1,260 loci sits within the ~1,300–1,600 range commonly cited for the Leningrad tradition given counting-method differences; whether OSHB's encoding exhausts the tradition (perpetual qere is unmarked in both sources) is recorded as an open scholarly question.
- Boundary: no STEPBible acquisition or licensing resolution, no segmentation enforcement, no candidate work.

## 2026-07-12 - PR #4 source-identity, structural, and policy repair

- Purpose: repair Milestone 4 Part 1 before merge without beginning STEPBible,
  passage generation, benchmark, or discovery work.
- OSHB identity: every locus now retains the OSIS source book identifier and
  canonical MACULA code separately. The corrected 2 Kings token namespace is
  `HB_2KGS_...`; exact source references remain `2Kgs ...`, while canonical
  joins and `book` remain `2KI`. Of 1,268 Ketiv IDs, 813 changed namespace;
  all remain unique and collision-free.
- Structural alignment: one deterministic supplementary row per Ketiv token;
  paired rows use unanimous replaced-Qere anchors and Ketiv-only rows use
  agreeing two-sided same-verse neighbors. No OSHB source-native syntax field
  is populated. Across 1,251 Ketiv-bearing loci, sentence/clause/phrase
  membership resolves for 1,251/998/449; 448 loci are fully resolved, 803 are
  explicitly partial, and none are wholly unresolved. Every partial locus is
  recorded in `outputs/reports/m4-part1-structural-unresolved.csv`.
- Primary digest gate: Hebrew identity
  `91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6`
  and surface/lemma
  `7fb443c3f0c42ada5d89f3abad61dd304145863044107ac86277c9f05f76cc82`
  remain unchanged; Greek identity
  `9035fea8d73a2b2078ad2adc70f8389040dbe2051ee535b2ce88412f551df6f2`
  and surface/lemma
  `a5ede58d287c2d29d5dacc7adeb07ff5c6a10587e2949875928b2dd935c8c683`
  remain unchanged. New comprehensive analytical digests are Hebrew
  `9464a106684b63ff57bcd9dd754bcd0c875d7ea8157fc7bfe643d7eb66dab173`
  and Greek
  `31404eb29a1f71855f3670f6f895e3fadc3ab0b39e2685c3cf672620df08a2a1`.
- Supplement determinism: corrected run ID
  `oshb-kq-0fed79a1841208ff4d77`; Ketiv-token logical SHA-256
  `7bb67cebc45c06943a7f1fc2e241202f100a19cf7ad6dd6b0933d999ac01d238`;
  locus-registry logical SHA-256
  `ae6e70a8d1dd75cccfef85bb5535051134104f03d57490976d4e30f93c60f022`;
  structural logical SHA-256
  `ac0c9ebffe971ef9178ef47edbf868d9f904a189133dccf907f815651b867df9`.
  Two consecutive full rebuilds produced identical physical and logical hash
  documents.
- Segmentation policy: ADR 0011 separates the `MRK 16:20 -> MRK 16:99`
  source successor from a mandatory analytical boundary, registers
  `edition_complete` and `critical_core`, forbids fabricated omitted verses
  and alternate-ending concatenation, and pins reference-gap and future
  disputed-candidate rules. No passage was generated.

## 2026-07-12 - Milestone 4 governance closure

- Purpose: verify the merged Milestone 4 implementation, record its acceptance
  basis, and defer unneeded STEPBible activation without beginning Milestone 5.
- Merge basis: PR #4 head `7fa8e80e5723017f1ca11b4ce00069c8cb5ca473`
  merged to `main` as merge commit
  `0eb04697eb2c3d6cb70a96e85ff25c4d0a44a27b`.
- Completion basis: the OSHB Ketiv/Qere supplement, generic supplementary
  annotation and conflict-preservation tables, explicit Ketiv structural
  mappings with queryable unresolved states, the separate versification
  crosswalk, source-native identity preservation, deterministic analysis
  streams, and primary-corpus digest invariance satisfy the amended Milestone
  4 gate.
- Governance decision: owner-authorized ADR 0012 defers STEPBible. It remains
  an eligible future source in an inactive `under_review` state, but no file
  is activated and no licensing answer is inferred. Later activation requires
  a named missing field or capability,
  exact files, measurable benefit, completed file-level provenance and
  licensing review, and a conflict-preserving integration design.
- Post-merge quality verification: `uv sync` completed with 39 packages; Ruff lint
  passed; Ruff format check passed for 77 files; mypy passed for 49 source
  files; the default suite passed 207 tests with 8 opt-in tests skipped;
  configuration validation covered 14 files; and source validation covered 12
  records plus the canonical-hash audit of all three locally present sources.
- Full-corpus verification: all 8 opt-in regression tests passed. Hebrew
  validation covered 475,911 tokens, 39 books, 929 chapters, and 23,213 verses
  with zero errors or warnings; Greek covered 137,779 tokens, 27 books, 260
  chapters, and 7,943 verses with zero errors or warnings; unified validation
  reran both corpora cleanly.
- Digest gate: the established Hebrew and Greek identity, surface/lemma, and
  analytical digests, plus the OSHB Ketiv-token, locus-registry, and structural
  supplement digests, remained unchanged.
- Unresolved governance: STEPBible's file-level provenance, licensing,
  namespace, annotation-conflict, and redistribution questions remain open
  until an exact future source subset is proposed. Repository
  software/documentation licensing and the other source-specific issues in
  `docs/limitations.md` also remain unresolved.
- Boundary: this closure changed governance and documentation only. No passage
  generation, STEPBible acquisition, benchmark work, lexical scoring,
  embedding, or discovery analysis was performed.

Substantive experiments are prohibited until their prerequisite milestones and data-governance gates pass.
