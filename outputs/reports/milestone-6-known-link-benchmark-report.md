# Milestone 6 known-link benchmark report

## Objective

Establish a governed, versioned known-relationship benchmark using the OpenBible cross-reference graph strictly as Tier 3 weak supervision and broad knownness support, while retaining an empty human-curation-only Tier 1 schema.

## Repository and decision provenance

- PR #6 merge commit: `00f5e84a4a83227585bd77dd9a08a0567cd58a7f`
- Governing decision: ADR 0014, *Known-link benchmark identity, tiering, mapping, and leakage control*.
- Benchmark run ID: `benchmark-v1-dff1d3ef650c8ccd4930`
- Benchmark version: `known-links-v1-dff1d3ef650c`
- Benchmark schema version: `1`; relationship-ID schema version: `1`; mapping schema version: `1`.

## Source, license, and snapshot

The exact OpenBible link graph is approved under CC BY 4.0 with OpenBible.info attribution, a source/license link, preserved notices, and modification notices. Separately copyrighted ESV quotations are excluded. The acquired archive contains reference identifiers, integer votes, and attribution only; no biblical text.

- Snapshot label: `snapshot-2026-07-12-sha256-18e63e370308`
- Archive SHA-256: `18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492`
- Extracted-file hashes: `{"cross_references.txt": "eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37"}`
- Canonical source-record stream SHA-256: `e3b2b3bb8c0097382ce4385c38342d4d4d07dd3cde05b331c0998a007840482e`
- Acquisition: source-approved, content-addressed ZIP with safe extraction, local receipt, and offline exact verification; raw/extracted data remains Git-ignored.
- Archive schema: `utf-8` encoding, `lf` newlines, three data fields (source reference, target reference, signed vote) plus an attribution header.

## Data model and identity

Source records preserve every occurrence, original references, weight, direction, raw-record hash, file, line provenance, and parse status. Relationship identity derives only from the source/version/scheme, normalized endpoints, and source direction; passage mappings, votes, paths, timestamps, splits, and row numbers do not participate. Mapping identity remains separate and records ordered verse targets, method, profile, reading, confidence, gaps, disputed text, and ambiguity.

Direction is never silently symmetrized. Reverse relationships remain distinct directed relationships with a shared unordered-pair identity. Duplicate occurrences remain traceable through relationship-to-source-record links; votes are source ranking evidence, not confidence or literary-dependence probability.

## Tier governance and Tier 1 placeholder

OpenBible is Tier 3, weak-supervision and knownness-filter eligible, never primary-evaluation or Tier-1 eligible, and cannot be the sole positive benchmark. Tier 1 requires human curation and independent review; automated verification is prohibited.

- Tier 1 data rows: `0`
- Tier 1 header SHA-256: `7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b`

## Reference parsing and passage mapping

The parser preserves the OpenBible source scheme and handles governed aliases, single verses, same-chapter ranges, and cross-chapter ranges. Cross-book ranges and invalid/backward/out-of-scheme references remain explicit issues rather than silent loss. Milestone 6 maps only to verse passages under `edition_complete`: Hebrew uses Qere and Greek uses the source reading. Old Testament same-label mappings are provisional (`same_label_extant_reference`), never verified crosswalk equivalence. Omitted verses are never fabricated; partial ranges, disputed text, reference gaps, and critical-core exclusions remain explicit.

### Mapping-status distribution

| Profile | Corpus | Status | Confidence | Count |
|---|---|---|---|---|
| critical_core | greek | excluded_by_profile | profile_excluded | 639 |
| critical_core | greek | mapped_partial | partial_provisional | 145 |
| critical_core | greek | mapped_provisional | provisional_mechanical | 241190 |
| critical_core | greek | unresolved_missing_target | unresolved | 69 |
| critical_core | greek | unresolved_reference | unresolved | 8 |
| critical_core | hebrew | mapped_partial | partial_provisional | 248 |
| critical_core | hebrew | mapped_provisional | provisional_mechanical | 444480 |
| critical_core | hebrew | unresolved_missing_target | unresolved | 2809 |
| critical_core | hebrew | unresolved_reference | unresolved | 10 |
| edition_complete | greek | mapped_partial | partial_provisional | 140 |
| edition_complete | greek | mapped_provisional | provisional_mechanical | 241834 |
| edition_complete | greek | unresolved_missing_target | unresolved | 69 |
| edition_complete | greek | unresolved_reference | unresolved | 8 |
| edition_complete | hebrew | mapped_partial | partial_provisional | 248 |
| edition_complete | hebrew | mapped_provisional | provisional_mechanical | 444480 |
| edition_complete | hebrew | unresolved_missing_target | unresolved | 2809 |
| edition_complete | hebrew | unresolved_reference | unresolved | 10 |

Detailed aggregate risks are in `m6-versification-risks.csv`. A bounded, deterministically selected reference-level view (at most three references per book/profile/risk stratum) is in `m6-versification-risk-references.csv`; this satisfies reference-level auditability without publishing a bulk source graph. No biblical text is included.

## Source graph statistics

- Raw / parsed / invalid rows: `344799` / `344799` / `0`
- Exact duplicate occurrences / duplicate directed pairs: `0` / `0`
- Unique directed / unordered relationships: `344799` / `314921`
- Reverse unordered pairs / self-links: `29878` / `0`
- Weight minimum / Q1 / median / Q3 / maximum: `-86` / `2` / `3` / `6` / `1281`
- Negative / zero / positive weights: `1239` / `2277` / `341283`
- Reference-range distribution: `{"cross_book_range": 18, "cross_chapter_range": 637, "same_chapter_range": 87495, "single": 256649}`

### Corpus-pair distribution

| Corpus pair | Relationships |
|---|---|
| old_testament_to_old_testament | 187117 |
| new_testament_to_new_testament | 84369 |
| cross_testament | 73313 |

All artifact and source-audit counts are also recorded in `m6-benchmark-counts.csv`.

## Leakage controls and splits

Independent leakage views cover exact directed/unordered pairs, duplicate source records, shared endpoints, atomic overlapping source/target coordinates, shared target passages, declared relationship families, and shared provenance. Atomic book/ordinal groups avoid both quadratic hub pairs and one unrestricted global connected component.

| Group type | Distinct groups | Membership rows |
|---|---|---|
| canonical_book_pair | 2114 | 344799 |
| exact_directed_pair | 344799 | 344799 |
| exact_unordered_pair | 314921 | 344799 |
| overlapping_endpoint_range | 30266 | 953361 |
| overlapping_target_passage | 30133 | 949259 |
| shared_endpoint | 44663 | 670106 |
| shared_target_passage | 30810 | 954402 |

Held-out book, book-pair, source-passage, relationship-family contract, and broad-genre strategies assign whole configured leakage groups deterministically. Missing family labels are marked unsupported rather than invented. Tier 3 partitions are weak-supervision infrastructure, not definitive scholarly evaluation sets.

| Strategy | Partition | Eligibility | Exclusion reason | Count |
|---|---|---|---|---|
| held_out_book | development | eligible |  | 137 |
| held_out_book | excluded | excluded | leakage_group_partition_conflict:overlapping_endpoint_range | 304068 |
| held_out_book | excluded | excluded | mapping_ineligible | 2873 |
| held_out_book | test | eligible |  | 34859 |
| held_out_book | train | eligible |  | 2862 |
| held_out_book_pair | excluded | excluded | leakage_group_partition_conflict:overlapping_target_passage | 335896 |
| held_out_book_pair | excluded | excluded | mapping_ineligible | 2873 |
| held_out_book_pair | train | eligible |  | 6030 |
| held_out_genre | excluded | excluded | leakage_group_partition_conflict:overlapping_target_passage | 301214 |
| held_out_genre | excluded | excluded | mapping_ineligible | 2873 |
| held_out_genre | test | eligible |  | 32297 |
| held_out_genre | train | eligible |  | 8415 |
| held_out_relationship_family | excluded | excluded | relationship_family_unavailable | 344799 |
| held_out_source_passage | development | eligible |  | 2375 |
| held_out_source_passage | excluded | excluded | endpoint_partition_conflict | 86808 |
| held_out_source_passage | excluded | excluded | mapping_ineligible | 2873 |
| held_out_source_passage | excluded | excluded | range_overlap_guard | 87541 |
| held_out_source_passage | test | eligible |  | 2607 |
| held_out_source_passage | train | eligible |  | 162595 |

The same distribution is recorded in `m6-split-counts.csv`.

## Presumed negatives

The build uses deterministic, indexed, bounded-probe generation for length-matched random unlinked, same-book, same-book-pair, same-broad-genre, and nearby-context strategies. Every pair is checked against the known graph in both directions, passage overlap, split partition, and leakage constraints. These are presumed negatives only; absence from known-link sources is not proof of nonrelationship.

| Negative strategy | Split strategy | Partition | Count |
|---|---|---|---|
| length_matched_random_unlinked | held_out_book | development | 26 |
| length_matched_random_unlinked | held_out_book | test | 5305 |
| length_matched_random_unlinked | held_out_book | train | 524 |
| nearby_context_unlinked | held_out_book | development | 26 |
| nearby_context_unlinked | held_out_book | test | 5305 |
| nearby_context_unlinked | held_out_book | train | 524 |
| same_book_pair_unlinked | held_out_book | development | 26 |
| same_book_pair_unlinked | held_out_book | test | 5305 |
| same_book_pair_unlinked | held_out_book | train | 524 |
| same_book_unlinked | held_out_book | development | 26 |
| same_book_unlinked | held_out_book | test | 5305 |
| same_book_unlinked | held_out_book | train | 524 |
| same_broad_genre_unlinked | held_out_book | development | 26 |
| same_broad_genre_unlinked | held_out_book | test | 5305 |
| same_broad_genre_unlinked | held_out_book | train | 524 |

The same distribution is recorded in `m6-presumed-negative-counts.csv`.

## Metric contract

Pure synthetic-fixture contracts cover Recall@5/10/20, mean reciprocal rank, nDCG@20, Precision@10/configurable K, coverage, and performance by book, broad genre, passage-length bucket, corpus pair, relationship class, tier, and mapping confidence. Every output requires benchmark version, tiers, mapping eligibility, split, label quality, eligible/excluded query counts, and reasons. No retrieval model was run; OpenBible-only results must be labeled Tier 3 weak-supervision recovery.

## Determinism, hashes, runtime, and storage

- First benchmark run ID supplied for comparison: `benchmark-v1-dff1d3ef650c8ccd4930`
- Two-run logical and expected-physical comparison: `passed`
- First and second run IDs match: `True`
- Current runtime: `479.37766140000895` seconds
- Current storage footprint: `672790515` bytes

| Artifact | Logical SHA-256 | Physical SHA-256 |
|---|---|---|
| benchmark_endpoint_mappings | d56e5211a415b51abbfa5080add85ade3ad8d4f30b6c95313fef19e5c6e956e3 | 6154294e7fd626277fa124afc0f98c90e1fa72b5b7b6e263928cecbdd498b413 |
| benchmark_endpoints | a9560e443ba32b3900f635421f9390f461fdebe0c23f316ec295b7be28ba13c7 | 5f9c2195f6fedf1df9aacc245f8136d38f6e4f6e6c60ec279fb88ec9490e0222 |
| benchmark_issues | f39d5494a1d13e68e9acf77b44e6c1a38dc419ec52abfb879a26f41165a07de0 | 809bdaafa7eec0d5127e67eb1036b1969863d4708ee5ef7fc7f2b9ed25818020 |
| benchmark_leakage_groups | 56c356147c61d12074dbdf88e7ea2dd111e8a2d0e34e7caa530d103e6d66f9d7 | 0775a1592e64ffe237a20bbc484686ad9f9310f23d6e57f9ca3266e499c4d5d2 |
| benchmark_metadata | b406ab043ed90ba59204b1b6937ea742ea6d2e66a552a8678934d94b290086d8 | 050ad3fce87673d24292affa19975bd2b465b51f9222d6b76b42d0ce6b75d2e2 |
| benchmark_presumed_negatives | 9bf1ed5dd30c6a93b6ef359cd7d5fd39704f3c0cb3719e17cbcaae5bf524d6ff | d78a9c018291ce45ffcfacc44701676e07c35d32d761e2f993d62ffc16479c3a |
| benchmark_relationship_source_records | f215928778e16ef496ec309282a327559d242f520d531240059ecdbe21ba64a1 | 59997c7d25534f0e669c6ef7cf17e259b14cdc734f37f25657ed2d031659634a |
| benchmark_relationships | 4bd3d602a2604d425c0016eb7d565667a844b353cb16d0d88f3c369c21a13a6f | cb4fe17d18b58caf0af2c72283ce0f6ba858edf4c38bab6634c661d6d4408c07 |
| benchmark_source_records | 481e53738ae4f4940277d211176194b97e57908eb31ef172359524165409f1f4 | cf08ed16b38c9e5b10471bbbe2f8416851de952759d5d81727528bfeb89d987d |
| benchmark_split_assignments | bda3c63f2aa15cd60567fd3a8dae3118402df35fc07921910a218a941c9ac5e0 | 4b73aaace2e4d74ca235721a3189aa3bc56304fb8ff1439e1252fa14e266efc8 |

### Two-run logical comparison

| Artifact | First logical hash | Second logical hash | Logical equal | First physical hash | Second physical hash | Physical equality required | Physical equal |
|---|---|---|---|---|---|---|---|
| benchmark_endpoint_mappings | d56e5211a415b51abbfa5080add85ade3ad8d4f30b6c95313fef19e5c6e956e3 | d56e5211a415b51abbfa5080add85ade3ad8d4f30b6c95313fef19e5c6e956e3 | True | 6154294e7fd626277fa124afc0f98c90e1fa72b5b7b6e263928cecbdd498b413 | 6154294e7fd626277fa124afc0f98c90e1fa72b5b7b6e263928cecbdd498b413 | True | True |
| benchmark_endpoints | a9560e443ba32b3900f635421f9390f461fdebe0c23f316ec295b7be28ba13c7 | a9560e443ba32b3900f635421f9390f461fdebe0c23f316ec295b7be28ba13c7 | True | 5f9c2195f6fedf1df9aacc245f8136d38f6e4f6e6c60ec279fb88ec9490e0222 | 5f9c2195f6fedf1df9aacc245f8136d38f6e4f6e6c60ec279fb88ec9490e0222 | True | True |
| benchmark_issues | f39d5494a1d13e68e9acf77b44e6c1a38dc419ec52abfb879a26f41165a07de0 | f39d5494a1d13e68e9acf77b44e6c1a38dc419ec52abfb879a26f41165a07de0 | True | 809bdaafa7eec0d5127e67eb1036b1969863d4708ee5ef7fc7f2b9ed25818020 | 809bdaafa7eec0d5127e67eb1036b1969863d4708ee5ef7fc7f2b9ed25818020 | True | True |
| benchmark_leakage_groups | 56c356147c61d12074dbdf88e7ea2dd111e8a2d0e34e7caa530d103e6d66f9d7 | 56c356147c61d12074dbdf88e7ea2dd111e8a2d0e34e7caa530d103e6d66f9d7 | True | 0775a1592e64ffe237a20bbc484686ad9f9310f23d6e57f9ca3266e499c4d5d2 | 0775a1592e64ffe237a20bbc484686ad9f9310f23d6e57f9ca3266e499c4d5d2 | True | True |
| benchmark_metadata | b406ab043ed90ba59204b1b6937ea742ea6d2e66a552a8678934d94b290086d8 | b406ab043ed90ba59204b1b6937ea742ea6d2e66a552a8678934d94b290086d8 | True | 6d7184ca9fcea664e9337ae3a41d154413b7b4ec50e9615d87c6632c2f42c232 | 050ad3fce87673d24292affa19975bd2b465b51f9222d6b76b42d0ce6b75d2e2 | False | False |
| benchmark_presumed_negatives | 9bf1ed5dd30c6a93b6ef359cd7d5fd39704f3c0cb3719e17cbcaae5bf524d6ff | 9bf1ed5dd30c6a93b6ef359cd7d5fd39704f3c0cb3719e17cbcaae5bf524d6ff | True | d78a9c018291ce45ffcfacc44701676e07c35d32d761e2f993d62ffc16479c3a | d78a9c018291ce45ffcfacc44701676e07c35d32d761e2f993d62ffc16479c3a | True | True |
| benchmark_relationship_source_records | f215928778e16ef496ec309282a327559d242f520d531240059ecdbe21ba64a1 | f215928778e16ef496ec309282a327559d242f520d531240059ecdbe21ba64a1 | True | 59997c7d25534f0e669c6ef7cf17e259b14cdc734f37f25657ed2d031659634a | 59997c7d25534f0e669c6ef7cf17e259b14cdc734f37f25657ed2d031659634a | True | True |
| benchmark_relationships | 4bd3d602a2604d425c0016eb7d565667a844b353cb16d0d88f3c369c21a13a6f | 4bd3d602a2604d425c0016eb7d565667a844b353cb16d0d88f3c369c21a13a6f | True | cb4fe17d18b58caf0af2c72283ce0f6ba858edf4c38bab6634c661d6d4408c07 | cb4fe17d18b58caf0af2c72283ce0f6ba858edf4c38bab6634c661d6d4408c07 | True | True |
| benchmark_source_records | 481e53738ae4f4940277d211176194b97e57908eb31ef172359524165409f1f4 | 481e53738ae4f4940277d211176194b97e57908eb31ef172359524165409f1f4 | True | cf08ed16b38c9e5b10471bbbe2f8416851de952759d5d81727528bfeb89d987d | cf08ed16b38c9e5b10471bbbe2f8416851de952759d5d81727528bfeb89d987d | True | True |
| benchmark_split_assignments | bda3c63f2aa15cd60567fd3a8dae3118402df35fc07921910a218a941c9ac5e0 | bda3c63f2aa15cd60567fd3a8dae3118402df35fc07921910a218a941c9ac5e0 | True | 4b73aaace2e4d74ca235721a3189aa3bc56304fb8ff1439e1252fa14e266efc8 | 4b73aaace2e4d74ca235721a3189aa3bc56304fb8ff1439e1252fa14e266efc8 | True | True |

## Validation results

| Check | Observed | Passed |
|---|---|---|
| source audit raw rows reconcile | 344799 / 344799 | True |
| source audit parsed rows reconcile | 344799 / 344799 | True |
| parsed non-self rows have source links | 344799 / 344799 | True |
| metadata relationship count reconciles | 344799 / 344799 | True |
| OpenBible remains Tier 3 | 0 | True |
| no OpenBible primary-evaluation or Tier1 eligibility | 0 | True |
| Tier 1 remains empty | 0 | True |
| presumed-negative boolean controls all true | 0 | True |
| two endpoints per relationship | 689598 / 689598 | True |
| two mapping profiles per endpoint | 1379196 / 1379196 | True |
| five split assignments per relationship | 1723995 / 1723995 | True |
| exact unordered leakage membership per relationship | 344799 / 344799 | True |
| persisted error issues | 0 | True |

Persisted issue distribution:

| Severity | Code | Count |
|---|---|---|
| informational | endpoint_reference_unmapped | 18 |

The final repository quality suite, strict corpus/passage/benchmark validators, pre-commit hooks, and GitHub Actions remain authoritative for closure beyond these artifact-level checks.

## Scripted and manual spot checks

Deterministic criterion-driven evidence is recorded in `m6-spot-check-evidence.md`. Missing real-snapshot categories are explicitly recorded as audited absences; no example is fabricated and no biblical text is reproduced.
Manual review verdict: `passed`; reviewer: `Codex`; date: `2026-07-12`.

## Known limitations

- OpenBible is heterogeneous Tier 3 weak supervision, not scholarly ground truth.
- Tier 1 remains empty, so no primary high-confidence evaluation benchmark exists.
- Same-label Old Testament mappings remain provisional without an approved external versification crosswalk.
- Cross-reference absence does not establish nonrelationship; generated negatives are presumed only.
- Relationship-family labels are unavailable for OpenBible and are not invented.
- No lexical baseline, retrieval model, candidate discovery, embeddings, or Milestone 7 work has been run in this milestone.

## Acceptance assessment

- Declared final acceptance status: `passed`
- Artifact-level validation checks all passed: `True`
- Two-run logical and expected-physical determinism passed: `True`
- First and second run IDs match: `True`
- Manual spot-check review: `passed`
- Local quality/full-regression gates: `passed`
- Repository and data audit: `passed`
- Unmerged pull request: `https://github.com/greg-oyan/project-echoes/pull/7`
- GitHub Actions: `passed` (https://github.com/greg-oyan/project-echoes/actions/runs/29235763865)
- Milestone 6 may be marked complete only when the declared status is `passed`, the two-run comparison passes, every repository/full-corpus quality command passes, all anchors remain unchanged, and the unmerged PR is CI-green.

## Exact recommended Milestone 7 task

Execute Milestone 7 only: implement the transparent lexical baseline (TF-IDF, BM25, rare-lemma, phrase, and ordered-sequence scoring), candidate-evidence output, both registered repeated null families, the configurable conjunctive rare-evidence rule, and tier/mapping-confidence-separated known-link recovery evaluation. Do not begin Milestone 8 candidate review.
