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

## 2026-07-12 - Milestone 5 full-corpus passage segmentation

- Purpose: derive and validate exact, reconstructable multi-scale passage units from the accepted primary and Ketiv/Qere layers without beginning benchmark or discovery work.
- Inputs: MACULA Hebrew `7ab368fcb14e4ad2e0f784138241a098fb516ec4`, MACULA Greek `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`, OSHB `3d15126fb1ef74867fc1434be1942e837932691f`, and their pinned primary and supplement digests.
- Architecture: ADR 0013; exact authoritative membership; content-derived passage IDs; Hebrew Qere/Ketiv and Greek source readings under `edition_complete` and `critical_core`; clause, sentence, verse, two-verse, and five-verse units; language-aware reconstruction; separate source succession and analytical continuity.
- Run identity: both full generations reproduced `passages-v1-00e261abea9ed44ef087`.
- Counts: 914,497 passages; 21,530,271 membership rows; 913,445 adjacency rows; 148,948 explicit exclusion rows; zero segmentation issues; one metadata row.
- Acceptance: both strict persisted validations passed with zero errors, warnings, or informational findings. Boundaries, expected coverage, omitted-reference gaps, profile membership, Mark's alternate-ending boundary, disputed identifiers, Qere structure, Ketiv verse/sentence coverage, explicit unresolved Ketiv clause exclusions, reconstruction, and unchanged input digests all validated.
- Determinism: all six logical table hashes, all five deterministic content-table physical hashes, and all 3,570 non-metadata leaf hashes agreed. The metadata physical hash alone changed with measured runtime telemetry; the metadata logical hash excluded the registered telemetry columns and remained `87b88f0b3d4efa88c9d4668ba1eb0aba5fce244b0350130a033deb1a087578cf`.
- Resources: generations took 2,245.249 and 2,225.401 seconds; strict validations took 743.4 and 749.5 seconds; each metadata row reported 627,780,157 output bytes.
- Storage boundary: complete Parquet and DuckDB artifacts remain local and Git-ignored; tracked reports contain aggregate evidence, IDs, hashes, and non-reconstructive samples rather than bulk source text.
- Boundary: no Milestone 6 benchmark, OpenBible import, lexical scoring, embedding, candidate generation, or review-console work began.

## 2026-07-12 - Milestone 6 governed known-link benchmark implementation

- Purpose: establish versioned known-link infrastructure, source governance, conservative passage mapping, leakage-safe evaluation controls, presumed-negative generation, and metric contracts without beginning lexical retrieval or candidate discovery.
- Merge basis: Milestone 5 PR #6 head `61da893fe51886262342e336d70baeab117f6c2b` merged to `main` as merge commit `00f5e84a4a83227585bd77dd9a08a0567cd58a7f`; the Milestone 6 branch began from that verified merge.
- Source audit: official OpenBible.info cross references under CC BY 4.0, pinned as `snapshot-2026-07-12-sha256-18e63e370308`; archive SHA-256 `18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492`; extracted-file SHA-256 `eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37`.
- Archive findings: one safe tab-delimited reference-and-vote file; 344,799 structurally parsed records; 344,799 directed pairs; 314,921 unordered pairs; 29,878 unordered pairs represented in both directions; zero duplicate lines, duplicate directed pairs, self-links, invalid structural rows, or biblical/ESV quotation text. Signed votes range from -86 to 1,281 and remain ranking values, not scholarly confidence.
- Governance: ADR 0014 fixes separate source-record, relationship, directed/unordered pair, endpoint, and mapping identities; OpenBible remains Tier 3 weak supervision and knownness support only. It cannot supply scholarly ground truth, primary evaluation, or Tier 1.
- Tier 1: `data/benchmarks/tier1_quotations.csv` remains its exact governed header and zero data rows; header-only SHA-256 `7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b`. Future controlled-value checks use synthetic rows only; no quotation appendix was copied or reconstructed.
- Mapping: source references remain in the OpenBible scheme and map only to Milestone 5 verse passages. Same-label mappings without an approved scheme crosswalk remain provisional; ranges expand only to extant targets, and partial, missing, disputed, reference-gap, and `critical_core` exclusion states remain explicit.
- Evaluation controls: exact-pair, endpoint, overlap, target-passage, duplicate-provenance, and source-provenance groups support deterministic held-out-book, book-pair, source-passage, and broad-genre infrastructure splits. Relationship-family labels remain unsupported rather than invented. Five metadata-only presumed-negative strategies check the positive graph in both directions, overlap, partition, and leakage constraints.
- Metrics and storage: pure synthetic-fixture contracts cover recall, reciprocal rank, nDCG, precision, coverage, and governed strata. Ten typed benchmark artifacts and transactional DuckDB views retain logical/physical hashes while complete generated data stays local and Git-ignored. No retrieval model was run.
- Acceptance status at implementation checkpoint: pending the two-build validation recorded in the 2026-07-13 closure entry below.
- Boundary: no TF-IDF, BM25, rare-lemma scoring, phrase or ordered-sequence scoring, similarity search, null simulation, embeddings, semantic retrieval, candidate generation, human review, review console, Septuagint acquisition, or STEPBible activation was implemented or run.

## 2026-07-13 - Milestone 6 acceptance closure

- Scope: validate the governed OpenBible Tier 3 benchmark twice from the same pinned acquisition and unchanged Milestone 5 passage inputs. No retrieval model or Milestone 7 feature was run.
- Identity: both builds produced run `benchmark-v1-dff1d3ef650c8ccd4930` and version `known-links-v1-dff1d3ef650c`.
- Counts per build: 344,799 source records, 344,799 relationships, 344,799 relationship/source links, 689,598 endpoints, 1,379,196 mappings, 4,561,525 leakage memberships, 1,723,995 split assignments, 29,275 presumed negatives, 18 informational issues, and one metadata row.
- Mapping statuses: 639 `excluded_by_profile`, 781 `mapped_partial`, 1,371,984 `mapped_provisional`, 5,756 `unresolved_missing_target`, and 36 `unresolved_reference`.
- Corpus pairs: 187,117 OT–OT, 84,369 NT–NT, and 73,313 cross-testament relationships; together they account for all 344,799 relationships.
- Validation: strict validation returned zero errors, zero warnings, and 18 informational findings for each build. Presumed negatives had zero collisions with the complete range-expanded and exclusion-aware positive graph.
- Determinism: all ten logical hashes, all table counts, and all content-table physical hashes matched. Metadata physical bytes differed only because `runtime_seconds` is measured telemetry; the metadata logical hash excludes that registered field and matched. Exact hashes are pinned in `docs/benchmark-schema.md` and `tests/regression/test_full_benchmark.py`.
- Resources: wall-clock build times were 551.3 and 533.7 seconds; persisted pipeline runtimes were 501.93041979987174 and 479.37766140000895 seconds. Each build reported a 672,790,515-byte footprint.
- Command semantics: `ingest-benchmark` atomically stages and promotes the complete benchmark, including leakage, split, and presumed-negative artifacts. `generate-benchmark-splits` and `generate-presumed-negatives` verify those already materialized stages rather than generating them separately.
- Source lifecycle: the exact OpenBible snapshot moved from `approved` to `validated` for its restricted Tier 3 role. This does not change its evidence tier, redistribution policy, or mapping uncertainty.
- Repository gate: [PR #7](https://github.com/greg-oyan/project-echoes/pull/7) remains open and unmerged. [CI run 29235763865](https://github.com/greg-oyan/project-echoes/actions/runs/29235763865) succeeded for commit `a680c0b4c14cb6e3bab7e8b5305fd6a516ec37de`; the quality job completed in 32 seconds.
- Acceptance: all Milestone 6 local, governance, repository-audit, pull-request, and CI gates are satisfied. Milestone 6 is complete as of 2026-07-13.
- Boundary: no TF-IDF, BM25, rare-lemma or phrase scoring, similarity search, null simulation, embeddings, semantic retrieval, candidate generation, human review, review console, Septuagint acquisition, or STEPBible activation began.

## 2026-07-13 - Milestone 7 pre-heldout feasibility attempts (in progress)

- Scope: exercise the complete atomic Milestone 7 build far enough to verify
  implementation and local-resource feasibility before accepting or inspecting
  any candidate or scientific result. Both attempts used the frozen
  configuration and preregistration; neither changed the scientific methods,
  scopes, seeds, thresholds, or acceptance gate.
- Attempt 1: stopped after approximately three hours at 2.2 percent completion.
  The measured retrieval rate was 4.626 seconds per query, projecting an
  approximately 132-hour runtime. No staged output was promoted, and no
  candidate or scientific output was inspected. The response was limited to
  implementation reuse of immutable scoring contexts, feature extraction,
  sequence intermediates, gloss and pair facts, and exact sparse-retrieval
  state; registered scores and experiment semantics did not change.
- Attempt 2: completed the primary Hebrew–Hebrew and GNT–GNT retrieval scopes
  and had entered the primary English-gloss bridge when stopped. Measured
  physical table sizes projected a violation of the mandatory 10-GiB free-disk
  floor before atomic promotion. No staged output was promoted, and no
  candidate identity, evidence conclusion, evaluation metric, or other
  scientific output was inspected.
- Compact split provenance: repeated leakage-group identifier arrays were
  replaced by the unique group count, SHA-256 of sorted unique group IDs, and a
  separate canonical assignment digest. The measured unique serialized
  provenance map fell from approximately 283.3 MB to 33.9 MB. Strict validation
  reconstructs the exact payload from the anchored benchmark database; split
  membership, leakage policy, and eligibility are unchanged.
- Directional-ablation normalization: English-removal facts remain inline on
  each content-hashed bridge ranking, while the physical `ablation_results`
  artifact retains all eight candidate-pair ablations and rejects duplicate
  `subject_type=directional_ranking` rows. Avoiding the duplicate directional
  rows saves a projected 6.589 GiB across the primary and critical-core bridge
  scopes without changing any score, rank, identity, scope, threshold, or
  ablation conclusion.
- Atomicity and frozen science: both abandoned staging trees were excluded from
  accepted output. Only operational timing, progress, memory, disk, and table
  footprint telemetry informed the implementation and physical-storage
  corrections. The frozen scientific configuration and preregistration remain
  unchanged.
- Resumed attempt 3 (2026-07-17): completed the primary, critical-core, and
  Qere/Ketiv retrieval scopes, retaining 1,565 ranking parts
  (5,718,310,351 bytes), three index-metadata parts, 154 sparse-index files, and
  the governed feature tables. The first global critical-core sensitivity join
  created 17 temporary DuckDB files totaling 13,426,360,320 bytes. Free disk
  crossed the mandatory 10,737,418,240-byte floor and reached
  8,606,294,016 bytes while still declining. The process was stopped before
  disk exhaustion; the atomic output was not promoted and no candidate,
  held-out evaluation, null, or science-gate result was inspected. The
  disposable spill was removed only after exact inventory.
- Sensitivity storage correction: the unchanged reference-keyed FULL OUTER
  JOIN, window metrics, row identities, and output order now execute in
  deterministic `(corpus_pair, detector, query-reference hash bucket)`
  partitions. Four stable SHA-256 prefix buckets keep complete query windows
  together. Each DuckDB partition is capped at 2 GiB of spill and reserves the
  configured disk floor plus a 256-MiB safety margin, failing before query
  execution when bounded headroom is unavailable. The sensitivity-only
  preferred DuckDB budget is 1 GiB inside the unchanged process-wide guard.
  Focused formatting, lint, type, multi-detector equivalence, spill-cleanup,
  and fail-before-floor tests pass.
- Full-scale physical diagnostic: the preserved attempt-3 ranking tree streamed
  all 28,336,934 corrected critical-core comparison rows in 600 schema-cast
  frames in 1,637.97 seconds. Stderr was empty, minimum free disk was
  21,304,016,896 bytes, guarded peak RSS was 1,997,938,688 bytes, and the spill
  directory cleaned completely. Only operational counts and resource
  telemetry were read; no score, candidate identity, held-out metric, or
  science-gate conclusion was inspected. No registered scientific parameter
  changed.
- Resumed attempt 4 (2026-07-17): ran from 19:48:56 to 23:25:25 local time and
  completed all 1,565 ranking parts plus both sensitivity comparisons. The
  intact, unpromoted staging tree retains 5,718,310,351 bytes of rankings,
  640 sensitivity parts totaling 4,601,220,953 bytes, all 14 governed sparse
  indexes, three index-metadata parts, and both feature tables. Tier 3 setup
  then failed before producing an evaluation row when Rust could not allocate
  708,873,488 bytes for the global Polars distinct-strata scan. Stderr contains
  only that allocator failure. No candidate identity, held-out score, null
  result, or science-gate value was inspected.
- Attempt-4 recovery boundary: the preserved staging tree is now adopted only
  after every existing Parquet leaf passes bounded schema, order, count, and
  hash checks. Ranking strata are reconciled one leaf at a time. Because exact
  primary candidate aggregate traces were lost with process memory and cannot
  be recovered losslessly from top-100 rows, resume recomputes only primary
  retrieval from the persisted primary sparse indexes and verifies every
  regenerated ranking leaf against the preserved governed logical content.
  Aggregate updates receive a private completion checkpoint. Completed
  critical-core retrieval, Qere/Ketiv retrieval, and both sensitivities are
  not repeated. Exact primary split-provenance payloads are reconciled from
  bounded ranking leaves, with final strict validation retaining anchored
  database reconstruction; this avoids repeating the measured 8.5-GB
  provenance spill beside the preserved staging tree. Focused recovery tests,
  Ruff, formatting, and mypy pass. This changes physical execution and
  checkpointing only; all frozen scientific parameters remain unchanged.
- First resume invocation: stopped before staging adoption because the prior
  governed DuckDB spill root still contained empty `experiment/` and
  `sequences/` directories. Inventory confirmed zero files and zero bytes.
  Cleanup now accepts only an exact governed spill root whose complete
  descendant tree contains directories and no files or symlinks; any content
  still fails closed. The preserved staging tree was untouched.
- Second resume invocation: bounded staging adoption and preparation completed,
  then recovery stopped before retrieval because eight primary Hebrew passages
  with no persisted top-100 ranking row were absent from the ranking-derived
  split-provenance map. All eight have real Tier 3 mappings, so the generic
  no-assignment payload was not substituted. Recovery now performs an exact,
  512-MiB-spill-capped `json_contains` lookup for only missing passage IDs and
  passes those rows through the unchanged grouping and canonical digest logic.
  A fixture proves that targeted and full expansion payloads match exactly.
  The preserved staging tree remained untouched; no candidate, score, held-out
  metric, null result, or science-gate value was inspected.
- Third resume launcher invocation: did not reach the pipeline because
  PowerShell split the workspace path containing a space. Its usage-only
  stderr is retained; no staging file was opened or changed.
- Fourth resume invocation: successfully adopted the preserved tree, recovered
  all eight exact split-provenance payloads, regenerated and matched all 968
  primary ranking batches, and finalized the private candidate checkpoint as
  968 Parquet parts plus its content-hashed completion manifest
  (337,330,561 bytes total). The process then repeated the exact
  708,873,488-byte Rust allocation failure before any Tier 3 output row was
  written. This isolated the remaining allocator to the subsequent global
  Polars candidate-universe grouping, not ranking-strata discovery.
- Candidate-universe storage correction: directory-backed rankings now
  accumulate the unchanged `(corpus pair, representation, query)` sets one
  bounded Parquet leaf at a time, pool repeated identifiers, enforce the same
  250-target maximum during accumulation, and return canonically sorted unique
  targets. A fixture proves exact equality with the original global grouping,
  including cross-detector target deduplication. The finalized checkpoint
  prevents another resume from repeating primary retrieval. No score,
  candidate identity, held-out metric, null result, or science-gate value was
  inspected, and no scientific parameter changed.
- Fifth resume invocation: loaded the finalized candidate checkpoint, passed
  the former 708,873,488-byte candidate-universe failure point, and kept the
  replacement universe pass near 1 GiB resident memory. Windows private commit
  reached approximately 8.6 GiB and expanded the pagefile, while the separate
  free-disk guard retained about 8 GiB above its mandatory floor. Before any
  Tier 3 row was written, the following per-detector global ranking collection
  attempted a different 1,827,928,004-byte Rust allocation and exited. Stderr
  contains only that allocator failure.
- Detector-ranking storage correction: evaluation now streams each detector's
  query-filtered rows one sorted Parquet leaf at a time, pools repeated stable
  IDs, enforces the unchanged top-100 target bound, checks canonical rank and
  target order plus duplicate identities, and constructs the same query target
  and scored-ranking maps. A fixture proves exact equality with the prior
  materialized path. A tiny private progress marker inside the already ignored
  checkpoint directory records the last resource-check stage for any raw
  allocator exit and is removed with the checkpoint before promotion. No
  scientific value or frozen parameter changed.
- Sixth resume invocation: completed the full edition-complete Tier 3
  evaluation and the critical-core baselines and detectors through the final
  composite aggregation. Because result dictionaries were retained across all
  baselines, detectors, and both profiles until final assembly, Windows private
  commit reached approximately 10 GiB and expanded the pagefile. The final
  progress marker was
  `evaluation:critical_core:detector:rrf_composite:leaf-1536:groups-25222`;
  stderr contains only `memory allocation of 1632 bytes failed`. No evaluation
  artifact, null artifact, or science-gate report was emitted, and no
  held-out value or candidate identity was inspected. The pagefile released
  its transient space after exit; the 9.76-GiB staging tree and
  337,330,561-byte candidate checkpoint remain intact.
- Evaluation-result storage correction: each unchanged baseline or detector
  batch is now schema-cast and written to a private completion-marked Parquet
  checkpoint before its Python rows are released. Resumes validate run,
  configuration, preregistration, profile, detector, physical SHA-256, schema,
  row count, lineage singletons, and evaluation-ID uniqueness before reusing a
  part. The final frame retains the governed global sort and gate semantics and
  is written and released before null calibration. A fixture proves exact
  equality among the direct, checkpointed, and checkpoint-resumed paths and
  proves completed detector rankings are not reloaded. Focused Ruff, format,
  mypy, and 25 evaluation/pipeline tests pass. No frozen scientific parameter
  changed.
- Background-launch diagnostics (2026-07-18): attempt 5g's sandboxed
  `Start-Process` wrapper exited without a worker and left empty stdout and
  stderr logs. Attempts 5h and 5i each created a child worker after their
  transient wrapper disappeared. The persistent children were initially
  mistaken for completed launches, overlapped, and both failed at approximately
  15:04 local time under combined memory pressure. Attempt 5h retained a
  4,442-byte allocator traceback after completing three edition-complete
  baseline checkpoint parts; attempt 5i retained a 6,007-byte allocator
  traceback before adding another trusted completion. Attempt 5j was a
  two-second startup probe used only to establish the wrapper/child behavior;
  its logs are empty. A later nonprivileged census confirmed all earlier
  workers were gone before attempt 5k. All logs and the three physical parts
  remain preserved. The parts are reusable only after every registered
  checkpoint identity, schema, lineage, row-count, evaluation-ID, and SHA-256
  check succeeds; the overlap is not treated as a scientific replicate.
- Sole-worker attempt 5k (2026-07-18 18:09:27 through 2026-07-19 05:24:16
  local time): **preserved failed execution**. It validated and reused the
  three completed baseline checkpoints, completed and validated the remaining
  23 Tier 3 batches, assembled the governed evaluation artifact, completed all
  600 registered null replicates (100 iterations for each of two null families
  across all three primary corpus pairs), materialized calibration, and
  completed the global candidate-ranking preparation. It then wrote four
  complete, aligned parts for each candidate-pair, detector-score,
  candidate-evidence, shared-evidence, and ablation artifact before
  materialization stopped on one BM25 evidence comparison:
  `persisted=12.867698770178` and `recomputed=12.867698770179`. This is an
  adjacent one-unit bin at the already frozen 12-decimal output precision,
  caused by different deterministic float64 reduction paths. The scores,
  ranks, configuration, preregistration, candidate identities, and held-out
  results were not changed or inspected. The stderr log, a posthoc provenance
  record, all 26 Tier 3 checkpoints, the complete primary-candidate checkpoint,
  all null/calibration artifacts, and all complete candidate parts remain in
  ignored local storage.
- Adjacent-bin reconciliation and recovery provenance: governed evidence
  reproduction now maps the persisted and recomputed float64 values to exact
  integer bins after fixed-decimal formatting. Exact matches retain the
  original trace bytes; a difference of exactly one bin is retained explicitly
  in the evidence trace without changing either score; a difference greater
  than one bin or any non-finite value still fails closed. Resumed candidate
  leaves are replayed and compared rather than overwritten. Execution
  sidecars are written before pipeline work, bind the frozen configuration,
  upstream inputs, actual seeds, reused physical parts and checkpoints, and
  promoted output hashes, and preserve failed and successful attempts
  separately. These are numerical-provenance and execution-recovery
  corrections only.
- Sole-worker attempt 5l (2026-07-19 11:08:04 through 11:23:27 local time):
  **preserved failed execution**. The clean-commit execution sidecar
  authenticated and adopted 2,233 existing artifact leaves, the finalized
  968-part primary-candidate checkpoint, and its completion manifest before
  beginning bounded reconstruction of the completed evaluation state. A
  transient Windows reader or scanner lock then denied one overwrite of the
  private `progress.txt` diagnostic marker. The pipeline failed closed before
  promotion; the canonical output remained absent, both worker processes
  exited, and the complete 10,910,973,940-byte staging tree remained intact
  with all 968 primary parts and all 26 Tier 3 manifests and parts. The stderr
  SHA-256 is
  `00431fd5391ca0d8800653f657326e8cb635809f6ae721dcafced77fccb3eb2d`;
  the finalized failed-sidecar SHA-256 is
  `d59a59ee497510cacc17b461d7c152ac3515a444ad25bf6e253c001a2d4f7aef`.
  No candidate identity, held-out value, null result, or science-gate
  conclusion was inspected.
- Resume-marker lock correction: private progress-marker writes now follow the
  repository's established bounded Windows scanner-lock policy. Only
  `PermissionError` is retried, for ten total attempts with increasing
  50-millisecond steps; any other operating-system error fails immediately,
  and a persistent permission denial still raises the original fail-closed
  pipeline error after at most 2.25 seconds. Tests cover transient recovery,
  persistent denial, and immediate failure for other errors. The marker is
  diagnostic and ignored; no scientific artifact, method, score, rank,
  configuration, preregistration, or frozen parameter changed.
- Late-failure preservation: the private primary/Tier 3 checkpoint tree now
  moves to a governed ignored sibling immediately before final output
  construction, is restored after failure or on the next invocation after a
  process interruption, and is deleted only after DuckDB loading and the
  successful execution manifest are durable. Fresh full builds opt into
  preserving their governed staging tree on failure. This prevents a late
  operational error from forcing repetition of authenticated expensive work.
- Sole-worker attempt 5n (2026-07-19 11:45:30 through 2026-07-20 19:39:20
  local time): **preserved failed execution**. The resume authenticated and
  reused the 2,233 preserved artifact leaves, all 968 primary-candidate
  checkpoint parts, and all 26 Tier 3 checkpoint parts. It completed 2,535
  aligned leaves for each of the five candidate artifact families,
  representing the exact sorted 975,000-candidate prefix of the 1,248,779
  checkpointed candidate identities. It then failed after 114,830.59 seconds
  with a DuckDB out-of-memory exception during the next bounded
  candidate-rank lookup. The lazy `candidate_ranks` view had caused the same
  baseline and eight ablation global window rankings to be expanded for every
  5,000-identity lookup. The failed execution sidecar, stderr, 16,064-file
  staging tree, checkpoints, null/calibration results, and complete candidate
  leaves remain preserved; the canonical output was not promoted.
- Candidate-rank storage correction: the identical governed SQL, global
  candidate population, partitions, score ordering, and passage-ID tie breaks
  are materialized once as a spill-controlled temporary DuckDB table before
  bounded lookups begin. The input table is released after materialization.
  Existing resumed leaves continue to be regenerated and compared logically;
  none are accepted merely because they exist. A bounded fixture verifies
  base-table materialization, partitioned/tied ranks, zero-score ablation
  handling, and input-table release. The operational inventory confirmed that
  the preserved prefix produced no review-eligible spool rows; no individual
  candidate text, feature identity, score, rank, or held-out comparison was
  inspected. No frozen parameter or science-gate rule changed.
- Final canonical result (verified 2026-08-08): the recovered composite
  completed all governed lexical artifacts, 600 registered null-replicate rows
  across the governed strata, calibration, critical-core and Qere/Ketiv
  sensitivities, 1,248,779 candidate rows, and a typed zero-row strict review
  queue. Strict validation returned zero errors and zero warnings. The
  applicable sufficiently powered Tier 3 strata satisfied the registered
  recovery comparison; `gnt_gnt` remained insufficient for a recovery claim.
  No frozen RRF threshold satisfied the maximum empirical-FDR rule under both
  required null families for the applicable primary strata.
- Canonical identity: lexical configuration
  `9625a71c7768b25afa1f2d87eca044155c16b81401b91546a780d608655da83d`,
  preregistration
  `5e5e29e281acacff88d0b954078d2cf995b7e4e37647430e5a08be74750a481c`,
  and table-hash manifest
  `e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6`.
  The canonical 18,606-file, 17.149-GiB tree was copied to Backblaze B2 at
  `project-echoes-archive/m7/canonical-schema-v1`; independent `rclone`
  verification reported 18,606 matches and zero differences. The temporary
  server was deleted.
- Production provenance: the canonical result is not attributed to one
  pristine commit. It combines the M7 launch lineage through `c8fc361`,
  authenticated checkpoints, retained recovery and V5 reconciliation scripts,
  final validator contracts, transactionally sealed promotion receipts, the
  canonical hash manifest, and B2 inventory verification. Recovery-only
  monkeypatches are historical records; permanent source and regressions own
  their legitimate contracts.
- Scientific disposition: M7 is technically successful and scientifically
  negative/incomplete under its frozen positive acceptance gate. Thresholds
  were not weakened and the queue was not manufactured. Lexical similarity
  alone was insufficient under the registered controls; the result does not
  establish that no underdocumented relationships exist.
- Boundary amendment: ADR 0018 closes the original M7/M8 path and authorizes a
  new `final-discovery-v1` preregistration. M7 remains immutable. The new
  experiment reuses it as one lexical family and separates statistically
  eligible Tier A from an exploratory Tier B top 100.

## 2026-08-08 - `final-discovery-v1` local preproduction freeze

- Experiment state: implementation and preregistration only. The semantic
  configuration SHA-256 is
  `7b5c511fed3be041576f9c2ea784d71e028a0f539d7642d84ddcf61eccd22627`;
  the exact tracked YAML SHA-256 is
  `a38c2f6d1c3d84264c7b81a8a62c3a84cae8b993894f6634e339958cdc1f76b0`.
  These identities bind the same frozen scientific configuration and are not
  post-result tuning handles.
- Registered detectors: `m7_lexical_rrf`, `semantic_domain_overlap`,
  `lemma_root_sequence_semantic`, `multilingual_e5_original_language`,
  `multilingual_e5_english_gloss`, `grammar_sequence_alignment`,
  `grammar_rare_pattern`, `participant_frame_progression`, and
  `stratified_representation_anomaly`. Their frozen independence groups are
  lexical M7, semantic annotations, pretrained semantic, supplemental English
  bridge, grammar annotations, structural annotations, and diagnostic anomaly;
  correlated subdetectors do not become independent families.
- Positive controls: the active UBS-derived adaptation has 24 reference-only
  rows in eight leakage groups (15 train, 3 development, 6 test). All test rows
  are the single correlated `PCL_LAST_SUPPER` group, and no independent scholar
  adjudicated their original-language labels; benchmark reporting is
  descriptive. Upstream biblical text and UBS match strings remain inactive.
- Local validation status at this freeze: strict configuration and
  positive-control validation passed; focused final-discovery command,
  production-mode dispatch, checkpoint/restart, disk-calibration,
  disk-ensemble, review, pipeline, and independent-validation tests passed;
  Ruff checking, Ruff formatting checks, and `mypy src` passed. The complete
  repository test/fixture acceptance gate and final benchmark provenance are
  recorded separately by the release audit when complete; they are not
  scientific campaign results.
- Output contract: deterministic dossiers and Output J rows are limited to the
  first 100 score-ranked Tier A rows plus every Tier B row, while CSV/Parquet
  preserve the complete retained-candidate ledger, including known, excluded,
  and rejected rows. The standalone Output
  J preproduction draft freezes its required sections but contains no invented
  candidate or review result.
- Execution boundary: the production campaign was not launched, no paid cloud
  resource was created, no model asset was downloaded, and no full-corpus
  final-discovery result was computed. Local fixture and validation behavior
  cannot be interpreted as candidate recovery, Tier membership, expected
  noise, novelty, or discovery.

Substantive experiments are prohibited until their prerequisite milestones and data-governance gates pass.
