# Milestone 5 passage segmentation report

Status: **PASSED**

This report contains aggregate counts, identifiers, references, provenance, and hashes. It intentionally contains no reconstructed biblical text, token surfaces, lemmas, roots, or glosses.

## Objective

Produce deterministic clause, sentence, verse, two-verse, and five-verse passage representations for the governed Hebrew/Aramaic and Greek analytical streams while preserving exact membership, source identity, disputed-text policy, reference gaps, and Ketiv structural uncertainty.

## Architecture

Validated immutable corpus inputs are transformed into one governed analytical stream at a time, segmented per book, reconstructed with language-aware rules, and written as deterministically sorted partitioned Parquet. DuckDB exposes the Parquet artifacts as external views, so source tables and the high-volume membership relation are not duplicated.

Logical artifacts: `passages`, `passage_membership`, `passage_adjacency`, `segmentation_exclusions`, `segmentation_issues`, and `segmentation_metadata`.

## ADR decision

ADR 0013 governs passage identity, authoritative membership, source succession versus analytical continuity, profile boundaries, reconstruction, Ketiv uncertainty, explicit exclusions, storage, and determinism. ADR 0011 remains binding for disputed passages and the Mark-ending boundary.

## Input corpora and versions

| Item | Pinned version |
|---|---|
| `macula-greek` | `b5b7ecec0882a3e9a609ecac99e157391e5d9b46` |
| `macula-hebrew` | `7ab368fcb14e4ad2e0f784138241a098fb516ec4` |
| `oshb-morphhb` | `3d15126fb1ef74867fc1434be1942e837932691f` |

### Input digest table

#### Primary identity digests

| Item | SHA-256 |
|---|---|
| `greek` | `9035fea8d73a2b2078ad2adc70f8389040dbe2051ee535b2ce88412f551df6f2` |
| `hebrew` | `91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6` |

#### Surface and lemma digests

| Item | SHA-256 |
|---|---|
| `greek` | `a5ede58d287c2d29d5dacc7adeb07ff5c6a10587e2949875928b2dd935c8c683` |
| `hebrew` | `7fb443c3f0c42ada5d89f3abad61dd304145863044107ac86277c9f05f76cc82` |

#### Analytical digests

| Item | SHA-256 |
|---|---|
| `greek` | `31404eb29a1f71855f3670f6f895e3fadc3ab0b39e2685c3cf672620df08a2a1` |
| `hebrew` | `9464a106684b63ff57bcd9dd754bcd0c875d7ea8157fc7bfe643d7eb66dab173` |

#### OSHB supplement digests

| Item | SHA-256 |
|---|---|
| `ketiv_tokens` | `7bb67cebc45c06943a7f1fc2e241202f100a19cf7ad6dd6b0933d999ac01d238` |
| `locus_registry` | `ae6e70a8d1dd75cccfef85bb5535051134104f03d57490976d4e30f93c60f022` |
| `structural_alignments` | `ac0c9ebffe971ef9178ef47edbf868d9f904a189133dccf907f815651b867df9` |

## Passage schema

- Passage schema version: `1`
- Passage-ID schema version: `1`
- Segmentation configuration hash: `bc3210d7358e52283bc1f8f4785e31e01fe0f8335ba59693fe2770cea6f562d1`
- Segmentation run ID: `passages-v1-00e261abea9ed44ef087`
- Passage rows hold identity, reference, reconstruction, provenance, dispute, gap, uncertainty, and neighbor-overlap fields.
- Membership rows hold exact ordered token membership and structural-resolution evidence.

## Passage-ID method

A readable prefix is followed by the complete SHA-256 of canonical JSON containing the ID-schema version, corpus, profile, reading, granularity, book, scoped source-unit ID, ordered reference sequence, and ordered token IDs. Paths, timestamps, row order, and mutable crosswalks do not participate.

## Membership model

`passage_membership` is authoritative. One-based positions, stream order, membership basis, and structural-resolution status are auditable per token. Passage start/end token IDs are convenience fields only; reported membership-row totals equal the validated sum of passage token counts.

## Analytical-stream combinations

| corpus | analysis profile | analysis reading | granularity | passage count | membership rows |
|---|---|---|---|---|---|
| greek | critical_core | source | clause | 46072 | 137389 |
| greek | critical_core | source | five_verse | 7806 | 678138 |
| greek | critical_core | source | sentence | 7984 | 137389 |
| greek | critical_core | source | two_verse | 7890 | 273925 |
| greek | critical_core | source | verse | 7918 | 137389 |
| greek | edition_complete | source | clause | 46216 | 137779 |
| greek | edition_complete | source | five_verse | 7834 | 680348 |
| greek | edition_complete | source | sentence | 8011 | 137779 |
| greek | edition_complete | source | two_verse | 7915 | 274690 |
| greek | edition_complete | source | verse | 7943 | 137779 |
| hebrew | critical_core | ketiv | clause | 97034 | 437653 |
| hebrew | critical_core | ketiv | five_verse | 23057 | 2358666 |
| hebrew | critical_core | ketiv | sentence | 23213 | 474932 |
| hebrew | critical_core | ketiv | two_verse | 23174 | 948305 |
| hebrew | critical_core | ketiv | verse | 23213 | 474932 |
| hebrew | critical_core | qere | clause | 97106 | 438716 |
| hebrew | critical_core | qere | five_verse | 23057 | 2363544 |
| hebrew | critical_core | qere | sentence | 23213 | 475911 |
| hebrew | critical_core | qere | two_verse | 23174 | 950263 |
| hebrew | critical_core | qere | verse | 23213 | 475911 |
| hebrew | edition_complete | ketiv | clause | 97034 | 437653 |
| hebrew | edition_complete | ketiv | five_verse | 23057 | 2358666 |
| hebrew | edition_complete | ketiv | sentence | 23213 | 474932 |
| hebrew | edition_complete | ketiv | two_verse | 23174 | 948305 |
| hebrew | edition_complete | ketiv | verse | 23213 | 474932 |
| hebrew | edition_complete | qere | clause | 97106 | 438716 |
| hebrew | edition_complete | qere | five_verse | 23057 | 2363544 |
| hebrew | edition_complete | qere | sentence | 23213 | 475911 |
| hebrew | edition_complete | qere | two_verse | 23174 | 950263 |
| hebrew | edition_complete | qere | verse | 23213 | 475911 |

## Profile behavior

`edition_complete` retains all inline source text. `critical_core` excludes exactly Mark 16:9-20, Mark 16:99, and John 7:53-8:11 from Greek analytical membership without deleting or renumbering source tokens. Profile exclusions break window continuity. Edition-omitted verse numbers are never fabricated, and extant source-order windows that span an omission are marked as reference gaps.

## Reconstruction method

Hebrew and Aramaic reconstruction follows source word grouping, morpheme order, selected Qere/Ketiv reading, maqqef and punctuation behavior, and zero-width handling. Greek reconstruction follows leading punctuation, source surface form, trailing punctuation, elision metadata, and source order. Surface, normalized, Hebrew unpointed, and Greek folded forms remain separate.

## Full passage counts

| corpus | analysis profile | analysis reading | granularity | passage count | membership rows | reference gap count | disputed passage count | ketiv uncertain count | sensitivity exclusion count |
|---|---|---|---|---|---|---|---|---|---|
| greek | critical_core | source | clause | 46072 | 137389 | 17 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 7806 | 678138 | 54 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 7984 | 137389 | 1 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 7890 | 273925 | 15 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 7918 | 137389 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 46216 | 137779 | 17 | 144 | 0 | 0 |
| greek | edition_complete | source | five_verse | 7834 | 680348 | 54 | 28 | 0 | 0 |
| greek | edition_complete | source | sentence | 8011 | 137779 | 1 | 27 | 0 | 0 |
| greek | edition_complete | source | two_verse | 7915 | 274690 | 15 | 25 | 0 | 0 |
| greek | edition_complete | source | verse | 7943 | 137779 | 0 | 25 | 0 | 0 |
| hebrew | critical_core | ketiv | clause | 97034 | 437653 | 0 | 0 | 568 | 21 |
| hebrew | critical_core | ketiv | five_verse | 23057 | 2358666 | 0 | 0 | 3083 | 0 |
| hebrew | critical_core | ketiv | sentence | 23213 | 474932 | 0 | 0 | 720 | 0 |
| hebrew | critical_core | ketiv | two_verse | 23174 | 948305 | 0 | 0 | 1377 | 0 |
| hebrew | critical_core | ketiv | verse | 23213 | 474932 | 0 | 0 | 720 | 0 |
| hebrew | critical_core | qere | clause | 97106 | 438716 | 0 | 0 | 0 | 11 |
| hebrew | critical_core | qere | five_verse | 23057 | 2363544 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | 23213 | 475911 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | 23174 | 950263 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | 23213 | 475911 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | clause | 97034 | 437653 | 0 | 0 | 568 | 21 |
| hebrew | edition_complete | ketiv | five_verse | 23057 | 2358666 | 0 | 0 | 3083 | 0 |
| hebrew | edition_complete | ketiv | sentence | 23213 | 474932 | 0 | 0 | 720 | 0 |
| hebrew | edition_complete | ketiv | two_verse | 23174 | 948305 | 0 | 0 | 1377 | 0 |
| hebrew | edition_complete | ketiv | verse | 23213 | 474932 | 0 | 0 | 720 | 0 |
| hebrew | edition_complete | qere | clause | 97106 | 438716 | 0 | 0 | 0 | 11 |
| hebrew | edition_complete | qere | five_verse | 23057 | 2363544 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | 23213 | 475911 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | 23174 | 950263 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | 23213 | 475911 | 0 | 0 | 0 | 0 |

### Counts by book

The same deterministic rows are written to `m5-passage-counts.csv`.

| corpus | analysis profile | analysis reading | granularity | book | passage count | membership rows | reference gap count | disputed passage count | ketiv uncertain count | sensitivity exclusion count |
|---|---|---|---|---|---|---|---|---|---|---|
| greek | critical_core | source | clause | MAT | 6496 | 18299 | 1 | 0 | 0 | 0 |
| greek | critical_core | source | clause | MRK | 4240 | 11077 | 2 | 0 | 0 | 0 |
| greek | critical_core | source | clause | LUK | 7095 | 19456 | 1 | 0 | 0 | 0 |
| greek | critical_core | source | clause | JHN | 5749 | 15453 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | ACT | 5952 | 18393 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | ROM | 2204 | 7100 | 4 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 1CO | 2488 | 6820 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 2CO | 1451 | 4469 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | GAL | 750 | 2228 | 2 | 0 | 0 | 0 |
| greek | critical_core | source | clause | EPH | 538 | 2419 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | PHP | 482 | 1630 | 1 | 0 | 0 | 0 |
| greek | critical_core | source | clause | COL | 348 | 1575 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 1TH | 421 | 1473 | 2 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 2TH | 217 | 822 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 1TI | 466 | 1588 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 2TI | 345 | 1237 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | TIT | 163 | 658 | 1 | 0 | 0 | 0 |
| greek | critical_core | source | clause | PHM | 79 | 335 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | HEB | 1488 | 4955 | 3 | 0 | 0 | 0 |
| greek | critical_core | source | clause | JAS | 608 | 1739 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 1PE | 480 | 1676 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 2PE | 289 | 1098 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 1JN | 730 | 2136 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 2JN | 73 | 245 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | 3JN | 79 | 219 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | JUD | 125 | 457 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | clause | REV | 2716 | 9832 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | MAT | 1064 | 91167 | 12 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | MRK | 657 | 55061 | 17 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | LUK | 1145 | 97057 | 8 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | JHN | 859 | 76506 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | ACT | 998 | 91617 | 14 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | ROM | 428 | 35213 | 3 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 1CO | 433 | 33835 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 2CO | 252 | 21959 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | GAL | 145 | 10835 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | EPH | 151 | 11776 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | PHP | 100 | 7889 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | COL | 91 | 7584 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 1TH | 85 | 7100 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 2TH | 43 | 3803 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 1TI | 109 | 7667 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 2TI | 79 | 5905 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | TIT | 42 | 2977 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | PHM | 21 | 1444 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | HEB | 299 | 24493 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | JAS | 104 | 8410 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 1PE | 101 | 8073 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 2PE | 57 | 5072 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 1JN | 101 | 10268 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 2JN | 9 | 871 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | 3JN | 11 | 851 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | JUD | 21 | 1928 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | five_verse | REV | 401 | 48777 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | MAT | 1133 | 18299 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | MRK | 714 | 11077 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | LUK | 1155 | 19456 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | JHN | 1024 | 15453 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | ACT | 883 | 18393 | 1 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | ROM | 465 | 7100 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 1CO | 524 | 6820 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 2CO | 253 | 4469 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | GAL | 150 | 2228 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | EPH | 78 | 2419 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | PHP | 81 | 1630 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | COL | 58 | 1575 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 1TH | 62 | 1473 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 2TH | 34 | 822 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 1TI | 89 | 1588 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 2TI | 74 | 1237 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | TIT | 34 | 658 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | PHM | 17 | 335 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | HEB | 241 | 4955 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | JAS | 133 | 1739 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 1PE | 74 | 1676 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 2PE | 44 | 1098 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 1JN | 144 | 2136 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 2JN | 15 | 245 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | 3JN | 21 | 219 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | JUD | 18 | 457 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | sentence | REV | 466 | 9832 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | MAT | 1067 | 36569 | 3 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | MRK | 660 | 22129 | 5 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | LUK | 1148 | 38891 | 2 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | JHN | 865 | 30817 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | ACT | 1001 | 36752 | 4 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | ROM | 431 | 14175 | 1 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 1CO | 436 | 13619 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 2CO | 255 | 8889 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | GAL | 148 | 4423 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | EPH | 154 | 4807 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | PHP | 103 | 3230 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | COL | 94 | 3125 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 1TH | 88 | 2918 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 2TH | 46 | 1618 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 1TI | 112 | 3150 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 2TI | 82 | 2450 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | TIT | 45 | 1282 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | PHM | 24 | 646 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | HEB | 302 | 9893 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | JAS | 107 | 3445 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 1PE | 104 | 3328 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 2PE | 60 | 2153 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 1JN | 104 | 4243 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 2JN | 12 | 457 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | 3JN | 14 | 417 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | JUD | 24 | 870 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | two_verse | REV | 404 | 19629 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | MAT | 1068 | 18299 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | MRK | 661 | 11077 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | LUK | 1149 | 19456 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | JHN | 867 | 15453 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | ACT | 1002 | 18393 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | ROM | 432 | 7100 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 1CO | 437 | 6820 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 2CO | 256 | 4469 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | GAL | 149 | 2228 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | EPH | 155 | 2419 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | PHP | 104 | 1630 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | COL | 95 | 1575 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 1TH | 89 | 1473 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 2TH | 47 | 822 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 1TI | 113 | 1588 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 2TI | 83 | 1237 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | TIT | 46 | 658 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | PHM | 25 | 335 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | HEB | 303 | 4955 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | JAS | 108 | 1739 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 1PE | 105 | 1676 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 2PE | 61 | 1098 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 1JN | 105 | 2136 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 2JN | 13 | 245 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | 3JN | 15 | 219 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | JUD | 25 | 457 | 0 | 0 | 0 | 0 |
| greek | critical_core | source | verse | REV | 405 | 9832 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | MAT | 6496 | 18299 | 1 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | MRK | 4313 | 11277 | 2 | 73 | 0 | 0 |
| greek | edition_complete | source | clause | LUK | 7095 | 19456 | 1 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | JHN | 5820 | 15643 | 0 | 71 | 0 | 0 |
| greek | edition_complete | source | clause | ACT | 5952 | 18393 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | ROM | 2204 | 7100 | 4 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 1CO | 2488 | 6820 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 2CO | 1451 | 4469 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | GAL | 750 | 2228 | 2 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | EPH | 538 | 2419 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | PHP | 482 | 1630 | 1 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | COL | 348 | 1575 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 1TH | 421 | 1473 | 2 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 2TH | 217 | 822 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 1TI | 466 | 1588 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 2TI | 345 | 1237 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | TIT | 163 | 658 | 1 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | PHM | 79 | 335 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | HEB | 1488 | 4955 | 3 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | JAS | 608 | 1739 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 1PE | 480 | 1676 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 2PE | 289 | 1098 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 1JN | 730 | 2136 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 2JN | 73 | 245 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | 3JN | 79 | 219 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | JUD | 125 | 457 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | clause | REV | 2716 | 9832 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | MAT | 1064 | 91167 | 12 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | MRK | 669 | 55921 | 17 | 12 | 0 | 0 |
| greek | edition_complete | source | five_verse | LUK | 1145 | 97057 | 8 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | JHN | 875 | 77856 | 0 | 16 | 0 | 0 |
| greek | edition_complete | source | five_verse | ACT | 998 | 91617 | 14 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | ROM | 428 | 35213 | 3 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 1CO | 433 | 33835 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 2CO | 252 | 21959 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | GAL | 145 | 10835 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | EPH | 151 | 11776 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | PHP | 100 | 7889 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | COL | 91 | 7584 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 1TH | 85 | 7100 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 2TH | 43 | 3803 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 1TI | 109 | 7667 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 2TI | 79 | 5905 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | TIT | 42 | 2977 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | PHM | 21 | 1444 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | HEB | 299 | 24493 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | JAS | 104 | 8410 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 1PE | 101 | 8073 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 2PE | 57 | 5072 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 1JN | 101 | 10268 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 2JN | 9 | 871 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | 3JN | 11 | 851 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | JUD | 21 | 1928 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | five_verse | REV | 401 | 48777 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | MAT | 1133 | 18299 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | MRK | 727 | 11277 | 0 | 13 | 0 | 0 |
| greek | edition_complete | source | sentence | LUK | 1155 | 19456 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | JHN | 1038 | 15643 | 0 | 14 | 0 | 0 |
| greek | edition_complete | source | sentence | ACT | 883 | 18393 | 1 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | ROM | 465 | 7100 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 1CO | 524 | 6820 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 2CO | 253 | 4469 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | GAL | 150 | 2228 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | EPH | 78 | 2419 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | PHP | 81 | 1630 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | COL | 58 | 1575 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 1TH | 62 | 1473 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 2TH | 34 | 822 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 1TI | 89 | 1588 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 2TI | 74 | 1237 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | TIT | 34 | 658 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | PHM | 17 | 335 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | HEB | 241 | 4955 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | JAS | 133 | 1739 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 1PE | 74 | 1676 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 2PE | 44 | 1098 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 1JN | 144 | 2136 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 2JN | 15 | 245 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | 3JN | 21 | 219 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | JUD | 18 | 457 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | sentence | REV | 466 | 9832 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | MAT | 1067 | 36569 | 3 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | MRK | 672 | 22465 | 5 | 12 | 0 | 0 |
| greek | edition_complete | source | two_verse | LUK | 1148 | 38891 | 2 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | JHN | 878 | 31246 | 0 | 13 | 0 | 0 |
| greek | edition_complete | source | two_verse | ACT | 1001 | 36752 | 4 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | ROM | 431 | 14175 | 1 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 1CO | 436 | 13619 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 2CO | 255 | 8889 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | GAL | 148 | 4423 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | EPH | 154 | 4807 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | PHP | 103 | 3230 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | COL | 94 | 3125 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 1TH | 88 | 2918 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 2TH | 46 | 1618 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 1TI | 112 | 3150 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 2TI | 82 | 2450 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | TIT | 45 | 1282 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | PHM | 24 | 646 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | HEB | 302 | 9893 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | JAS | 107 | 3445 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 1PE | 104 | 3328 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 2PE | 60 | 2153 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 1JN | 104 | 4243 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 2JN | 12 | 457 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | 3JN | 14 | 417 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | JUD | 24 | 870 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | two_verse | REV | 404 | 19629 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | MAT | 1068 | 18299 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | MRK | 674 | 11277 | 0 | 13 | 0 | 0 |
| greek | edition_complete | source | verse | LUK | 1149 | 19456 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | JHN | 879 | 15643 | 0 | 12 | 0 | 0 |
| greek | edition_complete | source | verse | ACT | 1002 | 18393 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | ROM | 432 | 7100 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 1CO | 437 | 6820 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 2CO | 256 | 4469 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | GAL | 149 | 2228 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | EPH | 155 | 2419 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | PHP | 104 | 1630 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | COL | 95 | 1575 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 1TH | 89 | 1473 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 2TH | 47 | 822 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 1TI | 113 | 1588 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 2TI | 83 | 1237 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | TIT | 46 | 658 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | PHM | 25 | 335 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | HEB | 303 | 4955 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | JAS | 108 | 1739 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 1PE | 105 | 1676 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 2PE | 61 | 1098 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 1JN | 105 | 2136 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 2JN | 13 | 245 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | 3JN | 15 | 219 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | JUD | 25 | 457 | 0 | 0 | 0 | 0 |
| greek | edition_complete | source | verse | REV | 405 | 9832 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | clause | GEN | 6646 | 29127 | 0 | 0 | 4 | 3 |
| hebrew | critical_core | ketiv | clause | EXO | 4707 | 24047 | 0 | 0 | 10 | 0 |
| hebrew | critical_core | ketiv | clause | LEV | 3491 | 17583 | 0 | 0 | 5 | 2 |
| hebrew | critical_core | ketiv | clause | NUM | 4276 | 23436 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | clause | DEU | 4238 | 21717 | 0 | 0 | 20 | 0 |
| hebrew | critical_core | ketiv | clause | JOS | 2534 | 14741 | 0 | 0 | 12 | 0 |
| hebrew | critical_core | ketiv | clause | JDG | 3119 | 13911 | 0 | 0 | 7 | 0 |
| hebrew | critical_core | ketiv | clause | RUT | 505 | 1796 | 0 | 0 | 3 | 0 |
| hebrew | critical_core | ketiv | clause | 1SA | 4387 | 18534 | 0 | 0 | 39 | 1 |
| hebrew | critical_core | ketiv | clause | 2SA | 3501 | 15408 | 0 | 0 | 40 | 0 |
| hebrew | critical_core | ketiv | clause | 1KI | 3964 | 18679 | 0 | 0 | 24 | 2 |
| hebrew | critical_core | ketiv | clause | 2KI | 3719 | 17005 | 0 | 0 | 30 | 0 |
| hebrew | critical_core | ketiv | clause | 1CH | 2555 | 15441 | 0 | 0 | 16 | 1 |
| hebrew | critical_core | ketiv | clause | 2CH | 3580 | 19593 | 0 | 0 | 15 | 2 |
| hebrew | critical_core | ketiv | clause | EZR | 855 | 5486 | 0 | 0 | 17 | 0 |
| hebrew | critical_core | ketiv | clause | NEH | 1335 | 7917 | 0 | 0 | 8 | 0 |
| hebrew | critical_core | ketiv | clause | EST | 813 | 4594 | 0 | 0 | 7 | 0 |
| hebrew | critical_core | ketiv | clause | JOB | 3589 | 11633 | 0 | 0 | 27 | 0 |
| hebrew | critical_core | ketiv | clause | PSA | 7691 | 28519 | 0 | 0 | 29 | 1 |
| hebrew | critical_core | ketiv | clause | PRO | 2604 | 9110 | 0 | 0 | 23 | 1 |
| hebrew | critical_core | ketiv | clause | ECC | 1107 | 4244 | 0 | 0 | 4 | 1 |
| hebrew | critical_core | ketiv | clause | SNG | 509 | 1963 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | clause | ISA | 6504 | 23858 | 0 | 0 | 20 | 1 |
| hebrew | critical_core | ketiv | clause | JER | 6951 | 30763 | 0 | 0 | 56 | 0 |
| hebrew | critical_core | ketiv | clause | LAM | 553 | 2198 | 0 | 0 | 10 | 2 |
| hebrew | critical_core | ketiv | clause | EZK | 6142 | 27461 | 0 | 0 | 65 | 1 |
| hebrew | critical_core | ketiv | clause | DAN | 1948 | 8694 | 0 | 0 | 55 | 2 |
| hebrew | critical_core | ketiv | clause | HOS | 881 | 3320 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | clause | JOL | 335 | 1340 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | clause | AMO | 806 | 2854 | 0 | 0 | 3 | 0 |
| hebrew | critical_core | ketiv | clause | OBA | 98 | 408 | 0 | 0 | 3 | 0 |
| hebrew | critical_core | ketiv | clause | JON | 250 | 974 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | clause | MIC | 509 | 1988 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | clause | NAM | 215 | 772 | 0 | 0 | 3 | 1 |
| hebrew | critical_core | ketiv | clause | HAB | 294 | 942 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | clause | ZEP | 251 | 1080 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | clause | HAG | 172 | 870 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | clause | ZEC | 1085 | 4444 | 0 | 0 | 3 | 0 |
| hebrew | critical_core | ketiv | clause | MAL | 315 | 1203 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | five_verse | GEN | 1529 | 161430 | 0 | 0 | 30 | 0 |
| hebrew | critical_core | ketiv | five_verse | EXO | 1209 | 130166 | 0 | 0 | 55 | 0 |
| hebrew | critical_core | ketiv | five_verse | LEV | 855 | 94147 | 0 | 0 | 20 | 0 |
| hebrew | critical_core | ketiv | five_verse | NUM | 1285 | 125808 | 0 | 0 | 25 | 0 |
| hebrew | critical_core | ketiv | five_verse | DEU | 955 | 115266 | 0 | 0 | 67 | 0 |
| hebrew | critical_core | ketiv | five_verse | JOS | 654 | 79122 | 0 | 0 | 114 | 0 |
| hebrew | critical_core | ketiv | five_verse | JDG | 614 | 77133 | 0 | 0 | 64 | 0 |
| hebrew | critical_core | ketiv | five_verse | RUT | 81 | 9808 | 0 | 0 | 20 | 0 |
| hebrew | critical_core | ketiv | five_verse | 1SA | 807 | 103661 | 0 | 0 | 200 | 0 |
| hebrew | critical_core | ketiv | five_verse | 2SA | 691 | 84825 | 0 | 0 | 237 | 0 |
| hebrew | critical_core | ketiv | five_verse | 1KI | 813 | 101468 | 0 | 0 | 149 | 0 |
| hebrew | critical_core | ketiv | five_verse | 2KI | 715 | 93493 | 0 | 0 | 163 | 0 |
| hebrew | critical_core | ketiv | five_verse | 1CH | 939 | 83301 | 0 | 0 | 94 | 0 |
| hebrew | critical_core | ketiv | five_verse | 2CH | 818 | 106298 | 0 | 0 | 89 | 0 |
| hebrew | critical_core | ketiv | five_verse | EZR | 276 | 28705 | 0 | 0 | 77 | 0 |
| hebrew | critical_core | ketiv | five_verse | NEH | 401 | 42270 | 0 | 0 | 50 | 0 |
| hebrew | critical_core | ketiv | five_verse | EST | 163 | 24046 | 0 | 0 | 39 | 0 |
| hebrew | critical_core | ketiv | five_verse | JOB | 1066 | 62676 | 0 | 0 | 184 | 0 |
| hebrew | critical_core | ketiv | five_verse | PSA | 2523 | 150940 | 0 | 0 | 194 | 0 |
| hebrew | critical_core | ketiv | five_verse | PRO | 911 | 48784 | 0 | 0 | 147 | 0 |
| hebrew | critical_core | ketiv | five_verse | ECC | 218 | 22412 | 0 | 0 | 25 | 0 |
| hebrew | critical_core | ketiv | five_verse | SNG | 113 | 9813 | 0 | 0 | 17 | 0 |
| hebrew | critical_core | ketiv | five_verse | ISA | 1287 | 127885 | 0 | 0 | 125 | 0 |
| hebrew | critical_core | ketiv | five_verse | JER | 1360 | 164259 | 0 | 0 | 310 | 0 |
| hebrew | critical_core | ketiv | five_verse | LAM | 150 | 11070 | 0 | 0 | 69 | 0 |
| hebrew | critical_core | ketiv | five_verse | EZK | 1269 | 148312 | 0 | 0 | 266 | 0 |
| hebrew | critical_core | ketiv | five_verse | DAN | 353 | 47029 | 0 | 0 | 174 | 0 |
| hebrew | critical_core | ketiv | five_verse | HOS | 193 | 17759 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | five_verse | JOL | 69 | 6988 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | five_verse | AMO | 142 | 14778 | 0 | 0 | 10 | 0 |
| hebrew | critical_core | ketiv | five_verse | OBA | 17 | 1772 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | five_verse | JON | 44 | 4972 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | five_verse | MIC | 101 | 10293 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | five_verse | NAM | 43 | 3847 | 0 | 0 | 18 | 0 |
| hebrew | critical_core | ketiv | five_verse | HAB | 52 | 4744 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | five_verse | ZEP | 49 | 5204 | 0 | 0 | 7 | 0 |
| hebrew | critical_core | ketiv | five_verse | HAG | 34 | 4118 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | five_verse | ZEC | 207 | 23806 | 0 | 0 | 24 | 0 |
| hebrew | critical_core | ketiv | five_verse | MAL | 51 | 6258 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | sentence | GEN | 1533 | 32358 | 0 | 0 | 6 | 0 |
| hebrew | critical_core | ketiv | sentence | EXO | 1213 | 26088 | 0 | 0 | 11 | 0 |
| hebrew | critical_core | ketiv | sentence | LEV | 859 | 18908 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | sentence | NUM | 1289 | 25248 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | sentence | DEU | 959 | 23148 | 0 | 0 | 19 | 0 |
| hebrew | critical_core | ketiv | sentence | JOS | 658 | 15925 | 0 | 0 | 24 | 0 |
| hebrew | critical_core | ketiv | sentence | JDG | 618 | 15523 | 0 | 0 | 15 | 0 |
| hebrew | critical_core | ketiv | sentence | RUT | 85 | 2035 | 0 | 0 | 6 | 0 |
| hebrew | critical_core | ketiv | sentence | 1SA | 811 | 20825 | 0 | 0 | 49 | 0 |
| hebrew | critical_core | ketiv | sentence | 2SA | 695 | 17076 | 0 | 0 | 58 | 0 |
| hebrew | critical_core | ketiv | sentence | 1KI | 817 | 20391 | 0 | 0 | 31 | 0 |
| hebrew | critical_core | ketiv | sentence | 2KI | 719 | 18786 | 0 | 0 | 38 | 0 |
| hebrew | critical_core | ketiv | sentence | 1CH | 943 | 16714 | 0 | 0 | 20 | 0 |
| hebrew | critical_core | ketiv | sentence | 2CH | 822 | 21379 | 0 | 0 | 19 | 0 |
| hebrew | critical_core | ketiv | sentence | EZR | 280 | 5827 | 0 | 0 | 19 | 0 |
| hebrew | critical_core | ketiv | sentence | NEH | 405 | 8543 | 0 | 0 | 12 | 0 |
| hebrew | critical_core | ketiv | sentence | EST | 167 | 4904 | 0 | 0 | 9 | 0 |
| hebrew | critical_core | ketiv | sentence | JOB | 1070 | 12609 | 0 | 0 | 39 | 0 |
| hebrew | critical_core | ketiv | sentence | PSA | 2527 | 30245 | 0 | 0 | 40 | 0 |
| hebrew | critical_core | ketiv | sentence | PRO | 915 | 9798 | 0 | 0 | 31 | 0 |
| hebrew | critical_core | ketiv | sentence | ECC | 222 | 4536 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | sentence | SNG | 117 | 2018 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | sentence | ISA | 1291 | 25663 | 0 | 0 | 26 | 0 |
| hebrew | critical_core | ketiv | sentence | JER | 1364 | 32934 | 0 | 0 | 72 | 0 |
| hebrew | critical_core | ketiv | sentence | LAM | 154 | 2284 | 0 | 0 | 17 | 0 |
| hebrew | critical_core | ketiv | sentence | EZK | 1273 | 29746 | 0 | 0 | 70 | 0 |
| hebrew | critical_core | ketiv | sentence | DAN | 357 | 9489 | 0 | 0 | 54 | 0 |
| hebrew | critical_core | ketiv | sentence | HOS | 197 | 3640 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | sentence | JOL | 73 | 1459 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | sentence | AMO | 146 | 3055 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | sentence | OBA | 21 | 439 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | sentence | JON | 48 | 1089 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | sentence | MIC | 105 | 2134 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | sentence | NAM | 47 | 844 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | sentence | HAB | 56 | 1017 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | sentence | ZEP | 53 | 1144 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | sentence | HAG | 38 | 927 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | sentence | ZEC | 211 | 4861 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | sentence | MAL | 55 | 1323 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | two_verse | GEN | 1532 | 64686 | 0 | 0 | 12 | 0 |
| hebrew | critical_core | ketiv | two_verse | EXO | 1212 | 52138 | 0 | 0 | 22 | 0 |
| hebrew | critical_core | ketiv | two_verse | LEV | 858 | 37788 | 0 | 0 | 8 | 0 |
| hebrew | critical_core | ketiv | two_verse | NUM | 1288 | 50444 | 0 | 0 | 10 | 0 |
| hebrew | critical_core | ketiv | two_verse | DEU | 958 | 46242 | 0 | 0 | 33 | 0 |
| hebrew | critical_core | ketiv | two_verse | JOS | 657 | 31811 | 0 | 0 | 48 | 0 |
| hebrew | critical_core | ketiv | two_verse | JDG | 617 | 31003 | 0 | 0 | 29 | 0 |
| hebrew | critical_core | ketiv | two_verse | RUT | 84 | 4027 | 0 | 0 | 11 | 0 |
| hebrew | critical_core | ketiv | two_verse | 1SA | 810 | 41609 | 0 | 0 | 92 | 0 |
| hebrew | critical_core | ketiv | two_verse | 2SA | 694 | 34107 | 0 | 0 | 111 | 0 |
| hebrew | critical_core | ketiv | two_verse | 1KI | 816 | 40741 | 0 | 0 | 62 | 0 |
| hebrew | critical_core | ketiv | two_verse | 2KI | 718 | 37543 | 0 | 0 | 73 | 0 |
| hebrew | critical_core | ketiv | two_verse | 1CH | 942 | 33402 | 0 | 0 | 40 | 0 |
| hebrew | critical_core | ketiv | two_verse | 2CH | 821 | 42693 | 0 | 0 | 37 | 0 |
| hebrew | critical_core | ketiv | two_verse | EZR | 279 | 11606 | 0 | 0 | 37 | 0 |
| hebrew | critical_core | ketiv | two_verse | NEH | 404 | 17048 | 0 | 0 | 23 | 0 |
| hebrew | critical_core | ketiv | two_verse | EST | 166 | 9756 | 0 | 0 | 17 | 0 |
| hebrew | critical_core | ketiv | two_verse | JOB | 1069 | 25187 | 0 | 0 | 78 | 0 |
| hebrew | critical_core | ketiv | two_verse | PSA | 2526 | 60462 | 0 | 0 | 80 | 0 |
| hebrew | critical_core | ketiv | two_verse | PRO | 914 | 19575 | 0 | 0 | 61 | 0 |
| hebrew | critical_core | ketiv | two_verse | ECC | 221 | 9048 | 0 | 0 | 10 | 0 |
| hebrew | critical_core | ketiv | two_verse | SNG | 116 | 4013 | 0 | 0 | 8 | 0 |
| hebrew | critical_core | ketiv | two_verse | ISA | 1290 | 51280 | 0 | 0 | 51 | 0 |
| hebrew | critical_core | ketiv | two_verse | JER | 1363 | 65830 | 0 | 0 | 137 | 0 |
| hebrew | critical_core | ketiv | two_verse | LAM | 153 | 4537 | 0 | 0 | 33 | 0 |
| hebrew | critical_core | ketiv | two_verse | EZK | 1272 | 59450 | 0 | 0 | 128 | 0 |
| hebrew | critical_core | ketiv | two_verse | DAN | 356 | 18944 | 0 | 0 | 92 | 0 |
| hebrew | critical_core | ketiv | two_verse | HOS | 196 | 7233 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | two_verse | JOL | 72 | 2899 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | two_verse | AMO | 145 | 6057 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | two_verse | OBA | 20 | 833 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | two_verse | JON | 47 | 2136 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | two_verse | MIC | 104 | 4232 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | two_verse | NAM | 46 | 1657 | 0 | 0 | 8 | 0 |
| hebrew | critical_core | ketiv | two_verse | HAB | 55 | 2004 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | two_verse | ZEP | 52 | 2226 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | two_verse | HAG | 37 | 1781 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | two_verse | ZEC | 210 | 9659 | 0 | 0 | 10 | 0 |
| hebrew | critical_core | ketiv | two_verse | MAL | 54 | 2618 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | verse | GEN | 1533 | 32358 | 0 | 0 | 6 | 0 |
| hebrew | critical_core | ketiv | verse | EXO | 1213 | 26088 | 0 | 0 | 11 | 0 |
| hebrew | critical_core | ketiv | verse | LEV | 859 | 18908 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | verse | NUM | 1289 | 25248 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | verse | DEU | 959 | 23148 | 0 | 0 | 19 | 0 |
| hebrew | critical_core | ketiv | verse | JOS | 658 | 15925 | 0 | 0 | 24 | 0 |
| hebrew | critical_core | ketiv | verse | JDG | 618 | 15523 | 0 | 0 | 15 | 0 |
| hebrew | critical_core | ketiv | verse | RUT | 85 | 2035 | 0 | 0 | 6 | 0 |
| hebrew | critical_core | ketiv | verse | 1SA | 811 | 20825 | 0 | 0 | 49 | 0 |
| hebrew | critical_core | ketiv | verse | 2SA | 695 | 17076 | 0 | 0 | 58 | 0 |
| hebrew | critical_core | ketiv | verse | 1KI | 817 | 20391 | 0 | 0 | 31 | 0 |
| hebrew | critical_core | ketiv | verse | 2KI | 719 | 18786 | 0 | 0 | 38 | 0 |
| hebrew | critical_core | ketiv | verse | 1CH | 943 | 16714 | 0 | 0 | 20 | 0 |
| hebrew | critical_core | ketiv | verse | 2CH | 822 | 21379 | 0 | 0 | 19 | 0 |
| hebrew | critical_core | ketiv | verse | EZR | 280 | 5827 | 0 | 0 | 19 | 0 |
| hebrew | critical_core | ketiv | verse | NEH | 405 | 8543 | 0 | 0 | 12 | 0 |
| hebrew | critical_core | ketiv | verse | EST | 167 | 4904 | 0 | 0 | 9 | 0 |
| hebrew | critical_core | ketiv | verse | JOB | 1070 | 12609 | 0 | 0 | 39 | 0 |
| hebrew | critical_core | ketiv | verse | PSA | 2527 | 30245 | 0 | 0 | 40 | 0 |
| hebrew | critical_core | ketiv | verse | PRO | 915 | 9798 | 0 | 0 | 31 | 0 |
| hebrew | critical_core | ketiv | verse | ECC | 222 | 4536 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | verse | SNG | 117 | 2018 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | verse | ISA | 1291 | 25663 | 0 | 0 | 26 | 0 |
| hebrew | critical_core | ketiv | verse | JER | 1364 | 32934 | 0 | 0 | 72 | 0 |
| hebrew | critical_core | ketiv | verse | LAM | 154 | 2284 | 0 | 0 | 17 | 0 |
| hebrew | critical_core | ketiv | verse | EZK | 1273 | 29746 | 0 | 0 | 70 | 0 |
| hebrew | critical_core | ketiv | verse | DAN | 357 | 9489 | 0 | 0 | 54 | 0 |
| hebrew | critical_core | ketiv | verse | HOS | 197 | 3640 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | verse | JOL | 73 | 1459 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | verse | AMO | 146 | 3055 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | verse | OBA | 21 | 439 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | verse | JON | 48 | 1089 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | verse | MIC | 105 | 2134 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | ketiv | verse | NAM | 47 | 844 | 0 | 0 | 4 | 0 |
| hebrew | critical_core | ketiv | verse | HAB | 56 | 1017 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | verse | ZEP | 53 | 1144 | 0 | 0 | 2 | 0 |
| hebrew | critical_core | ketiv | verse | HAG | 38 | 927 | 0 | 0 | 1 | 0 |
| hebrew | critical_core | ketiv | verse | ZEC | 211 | 4861 | 0 | 0 | 5 | 0 |
| hebrew | critical_core | ketiv | verse | MAL | 55 | 1323 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | GEN | 6648 | 29135 | 0 | 0 | 0 | 3 |
| hebrew | critical_core | qere | clause | EXO | 4707 | 24061 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | LEV | 3491 | 17587 | 0 | 0 | 0 | 2 |
| hebrew | critical_core | qere | clause | NUM | 4276 | 23442 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | DEU | 4238 | 21744 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | JOS | 2534 | 14771 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | JDG | 3122 | 13936 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | RUT | 507 | 1805 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | 1SA | 4390 | 18605 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | 2SA | 3509 | 15494 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | 1KI | 3966 | 18721 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | 2KI | 3722 | 17055 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | 1CH | 2555 | 15469 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | 2CH | 3581 | 19616 | 0 | 0 | 0 | 1 |
| hebrew | critical_core | qere | clause | EZR | 855 | 5516 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | NEH | 1337 | 7932 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | EST | 813 | 4608 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | JOB | 3593 | 11687 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | PSA | 7694 | 28574 | 0 | 0 | 0 | 1 |
| hebrew | critical_core | qere | clause | PRO | 2609 | 9149 | 0 | 0 | 0 | 1 |
| hebrew | critical_core | qere | clause | ECC | 1107 | 4252 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | SNG | 509 | 1967 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | ISA | 6507 | 23899 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | JER | 6963 | 30852 | 0 | 0 | 0 | 1 |
| hebrew | critical_core | qere | clause | LAM | 555 | 2217 | 0 | 0 | 0 | 2 |
| hebrew | critical_core | qere | clause | EZK | 6150 | 27605 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | DAN | 1955 | 8802 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | HOS | 881 | 3321 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | JOL | 335 | 1340 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | AMO | 806 | 2856 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | OBA | 98 | 409 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | JON | 250 | 974 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | MIC | 509 | 1988 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | NAM | 215 | 778 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | HAB | 294 | 943 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | ZEP | 251 | 1082 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | HAG | 173 | 871 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | ZEC | 1086 | 4450 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | clause | MAL | 315 | 1203 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | GEN | 1529 | 161465 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | EXO | 1209 | 130236 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | LEV | 855 | 94167 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | NUM | 1285 | 125833 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | DEU | 955 | 115401 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | JOS | 654 | 79262 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | JDG | 614 | 77222 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | RUT | 81 | 9838 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | 1SA | 807 | 103996 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | 2SA | 691 | 85218 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | 1KI | 813 | 101658 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | 2KI | 715 | 93718 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | 1CH | 939 | 83426 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | 2CH | 818 | 106403 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | EZR | 276 | 28850 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | NEH | 401 | 42340 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | EST | 163 | 24111 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | JOB | 1066 | 62927 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | PSA | 2523 | 151210 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | PRO | 911 | 48964 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | ECC | 218 | 22442 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | SNG | 113 | 9833 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | ISA | 1287 | 128055 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | JER | 1360 | 164666 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | LAM | 150 | 11162 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | EZK | 1269 | 148992 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | DAN | 353 | 47519 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | HOS | 193 | 17764 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | JOL | 69 | 6988 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | AMO | 142 | 14788 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | OBA | 17 | 1777 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | JON | 44 | 4972 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | MIC | 101 | 10293 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | NAM | 43 | 3870 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | HAB | 52 | 4749 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | ZEP | 49 | 5214 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | HAG | 34 | 4123 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | ZEC | 207 | 23834 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | five_verse | MAL | 51 | 6258 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | GEN | 1533 | 32365 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | EXO | 1213 | 26102 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | LEV | 859 | 18912 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | NUM | 1289 | 25253 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | DEU | 959 | 23175 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | JOS | 658 | 15953 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | JDG | 618 | 15541 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | RUT | 85 | 2041 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | 1SA | 811 | 20892 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | 2SA | 695 | 17155 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | 1KI | 817 | 20429 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | 2KI | 719 | 18831 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | 1CH | 943 | 16739 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | 2CH | 822 | 21400 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | EZR | 280 | 5856 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | NEH | 405 | 8557 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | EST | 167 | 4917 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | JOB | 1070 | 12660 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | PSA | 2527 | 30299 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | PRO | 915 | 9834 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | ECC | 222 | 4542 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | SNG | 117 | 2022 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | ISA | 1291 | 25697 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | JER | 1364 | 33016 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | LAM | 154 | 2303 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | EZK | 1273 | 29882 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | DAN | 357 | 9587 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | HOS | 197 | 3641 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | JOL | 73 | 1459 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | AMO | 146 | 3057 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | OBA | 21 | 440 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | JON | 48 | 1089 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | MIC | 105 | 2134 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | NAM | 47 | 849 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | HAB | 56 | 1018 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | ZEP | 53 | 1146 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | HAG | 38 | 928 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | ZEC | 211 | 4867 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | sentence | MAL | 55 | 1323 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | GEN | 1532 | 64700 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | EXO | 1212 | 52166 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | LEV | 858 | 37796 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | NUM | 1288 | 50454 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | DEU | 958 | 46296 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | JOS | 657 | 31867 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | JDG | 617 | 31039 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | RUT | 84 | 4039 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | 1SA | 810 | 41743 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | 2SA | 694 | 34265 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | 1KI | 816 | 40817 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | 2KI | 718 | 37633 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | 1CH | 942 | 33452 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | 2CH | 821 | 42735 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | EZR | 279 | 11664 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | NEH | 404 | 17076 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | EST | 166 | 9782 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | JOB | 1069 | 25289 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | PSA | 2526 | 60570 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | PRO | 914 | 19647 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | ECC | 221 | 9060 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | SNG | 116 | 4021 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | ISA | 1290 | 51348 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | JER | 1363 | 65994 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | LAM | 153 | 4575 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | EZK | 1272 | 59722 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | DAN | 356 | 19140 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | HOS | 196 | 7235 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | JOL | 72 | 2899 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | AMO | 145 | 6061 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | OBA | 20 | 835 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | JON | 47 | 2136 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | MIC | 104 | 4232 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | NAM | 46 | 1667 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | HAB | 55 | 2006 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | ZEP | 52 | 2230 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | HAG | 37 | 1783 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | ZEC | 210 | 9671 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | two_verse | MAL | 54 | 2618 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | GEN | 1533 | 32365 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | EXO | 1213 | 26102 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | LEV | 859 | 18912 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | NUM | 1289 | 25253 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | DEU | 959 | 23175 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | JOS | 658 | 15953 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | JDG | 618 | 15541 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | RUT | 85 | 2041 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | 1SA | 811 | 20892 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | 2SA | 695 | 17155 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | 1KI | 817 | 20429 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | 2KI | 719 | 18831 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | 1CH | 943 | 16739 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | 2CH | 822 | 21400 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | EZR | 280 | 5856 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | NEH | 405 | 8557 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | EST | 167 | 4917 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | JOB | 1070 | 12660 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | PSA | 2527 | 30299 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | PRO | 915 | 9834 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | ECC | 222 | 4542 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | SNG | 117 | 2022 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | ISA | 1291 | 25697 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | JER | 1364 | 33016 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | LAM | 154 | 2303 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | EZK | 1273 | 29882 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | DAN | 357 | 9587 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | HOS | 197 | 3641 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | JOL | 73 | 1459 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | AMO | 146 | 3057 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | OBA | 21 | 440 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | JON | 48 | 1089 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | MIC | 105 | 2134 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | NAM | 47 | 849 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | HAB | 56 | 1018 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | ZEP | 53 | 1146 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | HAG | 38 | 928 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | ZEC | 211 | 4867 | 0 | 0 | 0 | 0 |
| hebrew | critical_core | qere | verse | MAL | 55 | 1323 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | clause | GEN | 6646 | 29127 | 0 | 0 | 4 | 3 |
| hebrew | edition_complete | ketiv | clause | EXO | 4707 | 24047 | 0 | 0 | 10 | 0 |
| hebrew | edition_complete | ketiv | clause | LEV | 3491 | 17583 | 0 | 0 | 5 | 2 |
| hebrew | edition_complete | ketiv | clause | NUM | 4276 | 23436 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | clause | DEU | 4238 | 21717 | 0 | 0 | 20 | 0 |
| hebrew | edition_complete | ketiv | clause | JOS | 2534 | 14741 | 0 | 0 | 12 | 0 |
| hebrew | edition_complete | ketiv | clause | JDG | 3119 | 13911 | 0 | 0 | 7 | 0 |
| hebrew | edition_complete | ketiv | clause | RUT | 505 | 1796 | 0 | 0 | 3 | 0 |
| hebrew | edition_complete | ketiv | clause | 1SA | 4387 | 18534 | 0 | 0 | 39 | 1 |
| hebrew | edition_complete | ketiv | clause | 2SA | 3501 | 15408 | 0 | 0 | 40 | 0 |
| hebrew | edition_complete | ketiv | clause | 1KI | 3964 | 18679 | 0 | 0 | 24 | 2 |
| hebrew | edition_complete | ketiv | clause | 2KI | 3719 | 17005 | 0 | 0 | 30 | 0 |
| hebrew | edition_complete | ketiv | clause | 1CH | 2555 | 15441 | 0 | 0 | 16 | 1 |
| hebrew | edition_complete | ketiv | clause | 2CH | 3580 | 19593 | 0 | 0 | 15 | 2 |
| hebrew | edition_complete | ketiv | clause | EZR | 855 | 5486 | 0 | 0 | 17 | 0 |
| hebrew | edition_complete | ketiv | clause | NEH | 1335 | 7917 | 0 | 0 | 8 | 0 |
| hebrew | edition_complete | ketiv | clause | EST | 813 | 4594 | 0 | 0 | 7 | 0 |
| hebrew | edition_complete | ketiv | clause | JOB | 3589 | 11633 | 0 | 0 | 27 | 0 |
| hebrew | edition_complete | ketiv | clause | PSA | 7691 | 28519 | 0 | 0 | 29 | 1 |
| hebrew | edition_complete | ketiv | clause | PRO | 2604 | 9110 | 0 | 0 | 23 | 1 |
| hebrew | edition_complete | ketiv | clause | ECC | 1107 | 4244 | 0 | 0 | 4 | 1 |
| hebrew | edition_complete | ketiv | clause | SNG | 509 | 1963 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | clause | ISA | 6504 | 23858 | 0 | 0 | 20 | 1 |
| hebrew | edition_complete | ketiv | clause | JER | 6951 | 30763 | 0 | 0 | 56 | 0 |
| hebrew | edition_complete | ketiv | clause | LAM | 553 | 2198 | 0 | 0 | 10 | 2 |
| hebrew | edition_complete | ketiv | clause | EZK | 6142 | 27461 | 0 | 0 | 65 | 1 |
| hebrew | edition_complete | ketiv | clause | DAN | 1948 | 8694 | 0 | 0 | 55 | 2 |
| hebrew | edition_complete | ketiv | clause | HOS | 881 | 3320 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | clause | JOL | 335 | 1340 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | clause | AMO | 806 | 2854 | 0 | 0 | 3 | 0 |
| hebrew | edition_complete | ketiv | clause | OBA | 98 | 408 | 0 | 0 | 3 | 0 |
| hebrew | edition_complete | ketiv | clause | JON | 250 | 974 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | clause | MIC | 509 | 1988 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | clause | NAM | 215 | 772 | 0 | 0 | 3 | 1 |
| hebrew | edition_complete | ketiv | clause | HAB | 294 | 942 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | clause | ZEP | 251 | 1080 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | clause | HAG | 172 | 870 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | clause | ZEC | 1085 | 4444 | 0 | 0 | 3 | 0 |
| hebrew | edition_complete | ketiv | clause | MAL | 315 | 1203 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | five_verse | GEN | 1529 | 161430 | 0 | 0 | 30 | 0 |
| hebrew | edition_complete | ketiv | five_verse | EXO | 1209 | 130166 | 0 | 0 | 55 | 0 |
| hebrew | edition_complete | ketiv | five_verse | LEV | 855 | 94147 | 0 | 0 | 20 | 0 |
| hebrew | edition_complete | ketiv | five_verse | NUM | 1285 | 125808 | 0 | 0 | 25 | 0 |
| hebrew | edition_complete | ketiv | five_verse | DEU | 955 | 115266 | 0 | 0 | 67 | 0 |
| hebrew | edition_complete | ketiv | five_verse | JOS | 654 | 79122 | 0 | 0 | 114 | 0 |
| hebrew | edition_complete | ketiv | five_verse | JDG | 614 | 77133 | 0 | 0 | 64 | 0 |
| hebrew | edition_complete | ketiv | five_verse | RUT | 81 | 9808 | 0 | 0 | 20 | 0 |
| hebrew | edition_complete | ketiv | five_verse | 1SA | 807 | 103661 | 0 | 0 | 200 | 0 |
| hebrew | edition_complete | ketiv | five_verse | 2SA | 691 | 84825 | 0 | 0 | 237 | 0 |
| hebrew | edition_complete | ketiv | five_verse | 1KI | 813 | 101468 | 0 | 0 | 149 | 0 |
| hebrew | edition_complete | ketiv | five_verse | 2KI | 715 | 93493 | 0 | 0 | 163 | 0 |
| hebrew | edition_complete | ketiv | five_verse | 1CH | 939 | 83301 | 0 | 0 | 94 | 0 |
| hebrew | edition_complete | ketiv | five_verse | 2CH | 818 | 106298 | 0 | 0 | 89 | 0 |
| hebrew | edition_complete | ketiv | five_verse | EZR | 276 | 28705 | 0 | 0 | 77 | 0 |
| hebrew | edition_complete | ketiv | five_verse | NEH | 401 | 42270 | 0 | 0 | 50 | 0 |
| hebrew | edition_complete | ketiv | five_verse | EST | 163 | 24046 | 0 | 0 | 39 | 0 |
| hebrew | edition_complete | ketiv | five_verse | JOB | 1066 | 62676 | 0 | 0 | 184 | 0 |
| hebrew | edition_complete | ketiv | five_verse | PSA | 2523 | 150940 | 0 | 0 | 194 | 0 |
| hebrew | edition_complete | ketiv | five_verse | PRO | 911 | 48784 | 0 | 0 | 147 | 0 |
| hebrew | edition_complete | ketiv | five_verse | ECC | 218 | 22412 | 0 | 0 | 25 | 0 |
| hebrew | edition_complete | ketiv | five_verse | SNG | 113 | 9813 | 0 | 0 | 17 | 0 |
| hebrew | edition_complete | ketiv | five_verse | ISA | 1287 | 127885 | 0 | 0 | 125 | 0 |
| hebrew | edition_complete | ketiv | five_verse | JER | 1360 | 164259 | 0 | 0 | 310 | 0 |
| hebrew | edition_complete | ketiv | five_verse | LAM | 150 | 11070 | 0 | 0 | 69 | 0 |
| hebrew | edition_complete | ketiv | five_verse | EZK | 1269 | 148312 | 0 | 0 | 266 | 0 |
| hebrew | edition_complete | ketiv | five_verse | DAN | 353 | 47029 | 0 | 0 | 174 | 0 |
| hebrew | edition_complete | ketiv | five_verse | HOS | 193 | 17759 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | five_verse | JOL | 69 | 6988 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | five_verse | AMO | 142 | 14778 | 0 | 0 | 10 | 0 |
| hebrew | edition_complete | ketiv | five_verse | OBA | 17 | 1772 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | five_verse | JON | 44 | 4972 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | five_verse | MIC | 101 | 10293 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | five_verse | NAM | 43 | 3847 | 0 | 0 | 18 | 0 |
| hebrew | edition_complete | ketiv | five_verse | HAB | 52 | 4744 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | five_verse | ZEP | 49 | 5204 | 0 | 0 | 7 | 0 |
| hebrew | edition_complete | ketiv | five_verse | HAG | 34 | 4118 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | five_verse | ZEC | 207 | 23806 | 0 | 0 | 24 | 0 |
| hebrew | edition_complete | ketiv | five_verse | MAL | 51 | 6258 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | sentence | GEN | 1533 | 32358 | 0 | 0 | 6 | 0 |
| hebrew | edition_complete | ketiv | sentence | EXO | 1213 | 26088 | 0 | 0 | 11 | 0 |
| hebrew | edition_complete | ketiv | sentence | LEV | 859 | 18908 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | sentence | NUM | 1289 | 25248 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | sentence | DEU | 959 | 23148 | 0 | 0 | 19 | 0 |
| hebrew | edition_complete | ketiv | sentence | JOS | 658 | 15925 | 0 | 0 | 24 | 0 |
| hebrew | edition_complete | ketiv | sentence | JDG | 618 | 15523 | 0 | 0 | 15 | 0 |
| hebrew | edition_complete | ketiv | sentence | RUT | 85 | 2035 | 0 | 0 | 6 | 0 |
| hebrew | edition_complete | ketiv | sentence | 1SA | 811 | 20825 | 0 | 0 | 49 | 0 |
| hebrew | edition_complete | ketiv | sentence | 2SA | 695 | 17076 | 0 | 0 | 58 | 0 |
| hebrew | edition_complete | ketiv | sentence | 1KI | 817 | 20391 | 0 | 0 | 31 | 0 |
| hebrew | edition_complete | ketiv | sentence | 2KI | 719 | 18786 | 0 | 0 | 38 | 0 |
| hebrew | edition_complete | ketiv | sentence | 1CH | 943 | 16714 | 0 | 0 | 20 | 0 |
| hebrew | edition_complete | ketiv | sentence | 2CH | 822 | 21379 | 0 | 0 | 19 | 0 |
| hebrew | edition_complete | ketiv | sentence | EZR | 280 | 5827 | 0 | 0 | 19 | 0 |
| hebrew | edition_complete | ketiv | sentence | NEH | 405 | 8543 | 0 | 0 | 12 | 0 |
| hebrew | edition_complete | ketiv | sentence | EST | 167 | 4904 | 0 | 0 | 9 | 0 |
| hebrew | edition_complete | ketiv | sentence | JOB | 1070 | 12609 | 0 | 0 | 39 | 0 |
| hebrew | edition_complete | ketiv | sentence | PSA | 2527 | 30245 | 0 | 0 | 40 | 0 |
| hebrew | edition_complete | ketiv | sentence | PRO | 915 | 9798 | 0 | 0 | 31 | 0 |
| hebrew | edition_complete | ketiv | sentence | ECC | 222 | 4536 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | sentence | SNG | 117 | 2018 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | sentence | ISA | 1291 | 25663 | 0 | 0 | 26 | 0 |
| hebrew | edition_complete | ketiv | sentence | JER | 1364 | 32934 | 0 | 0 | 72 | 0 |
| hebrew | edition_complete | ketiv | sentence | LAM | 154 | 2284 | 0 | 0 | 17 | 0 |
| hebrew | edition_complete | ketiv | sentence | EZK | 1273 | 29746 | 0 | 0 | 70 | 0 |
| hebrew | edition_complete | ketiv | sentence | DAN | 357 | 9489 | 0 | 0 | 54 | 0 |
| hebrew | edition_complete | ketiv | sentence | HOS | 197 | 3640 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | sentence | JOL | 73 | 1459 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | sentence | AMO | 146 | 3055 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | sentence | OBA | 21 | 439 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | sentence | JON | 48 | 1089 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | sentence | MIC | 105 | 2134 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | sentence | NAM | 47 | 844 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | sentence | HAB | 56 | 1017 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | sentence | ZEP | 53 | 1144 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | sentence | HAG | 38 | 927 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | sentence | ZEC | 211 | 4861 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | sentence | MAL | 55 | 1323 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | two_verse | GEN | 1532 | 64686 | 0 | 0 | 12 | 0 |
| hebrew | edition_complete | ketiv | two_verse | EXO | 1212 | 52138 | 0 | 0 | 22 | 0 |
| hebrew | edition_complete | ketiv | two_verse | LEV | 858 | 37788 | 0 | 0 | 8 | 0 |
| hebrew | edition_complete | ketiv | two_verse | NUM | 1288 | 50444 | 0 | 0 | 10 | 0 |
| hebrew | edition_complete | ketiv | two_verse | DEU | 958 | 46242 | 0 | 0 | 33 | 0 |
| hebrew | edition_complete | ketiv | two_verse | JOS | 657 | 31811 | 0 | 0 | 48 | 0 |
| hebrew | edition_complete | ketiv | two_verse | JDG | 617 | 31003 | 0 | 0 | 29 | 0 |
| hebrew | edition_complete | ketiv | two_verse | RUT | 84 | 4027 | 0 | 0 | 11 | 0 |
| hebrew | edition_complete | ketiv | two_verse | 1SA | 810 | 41609 | 0 | 0 | 92 | 0 |
| hebrew | edition_complete | ketiv | two_verse | 2SA | 694 | 34107 | 0 | 0 | 111 | 0 |
| hebrew | edition_complete | ketiv | two_verse | 1KI | 816 | 40741 | 0 | 0 | 62 | 0 |
| hebrew | edition_complete | ketiv | two_verse | 2KI | 718 | 37543 | 0 | 0 | 73 | 0 |
| hebrew | edition_complete | ketiv | two_verse | 1CH | 942 | 33402 | 0 | 0 | 40 | 0 |
| hebrew | edition_complete | ketiv | two_verse | 2CH | 821 | 42693 | 0 | 0 | 37 | 0 |
| hebrew | edition_complete | ketiv | two_verse | EZR | 279 | 11606 | 0 | 0 | 37 | 0 |
| hebrew | edition_complete | ketiv | two_verse | NEH | 404 | 17048 | 0 | 0 | 23 | 0 |
| hebrew | edition_complete | ketiv | two_verse | EST | 166 | 9756 | 0 | 0 | 17 | 0 |
| hebrew | edition_complete | ketiv | two_verse | JOB | 1069 | 25187 | 0 | 0 | 78 | 0 |
| hebrew | edition_complete | ketiv | two_verse | PSA | 2526 | 60462 | 0 | 0 | 80 | 0 |
| hebrew | edition_complete | ketiv | two_verse | PRO | 914 | 19575 | 0 | 0 | 61 | 0 |
| hebrew | edition_complete | ketiv | two_verse | ECC | 221 | 9048 | 0 | 0 | 10 | 0 |
| hebrew | edition_complete | ketiv | two_verse | SNG | 116 | 4013 | 0 | 0 | 8 | 0 |
| hebrew | edition_complete | ketiv | two_verse | ISA | 1290 | 51280 | 0 | 0 | 51 | 0 |
| hebrew | edition_complete | ketiv | two_verse | JER | 1363 | 65830 | 0 | 0 | 137 | 0 |
| hebrew | edition_complete | ketiv | two_verse | LAM | 153 | 4537 | 0 | 0 | 33 | 0 |
| hebrew | edition_complete | ketiv | two_verse | EZK | 1272 | 59450 | 0 | 0 | 128 | 0 |
| hebrew | edition_complete | ketiv | two_verse | DAN | 356 | 18944 | 0 | 0 | 92 | 0 |
| hebrew | edition_complete | ketiv | two_verse | HOS | 196 | 7233 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | two_verse | JOL | 72 | 2899 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | two_verse | AMO | 145 | 6057 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | two_verse | OBA | 20 | 833 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | two_verse | JON | 47 | 2136 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | two_verse | MIC | 104 | 4232 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | two_verse | NAM | 46 | 1657 | 0 | 0 | 8 | 0 |
| hebrew | edition_complete | ketiv | two_verse | HAB | 55 | 2004 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | two_verse | ZEP | 52 | 2226 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | two_verse | HAG | 37 | 1781 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | two_verse | ZEC | 210 | 9659 | 0 | 0 | 10 | 0 |
| hebrew | edition_complete | ketiv | two_verse | MAL | 54 | 2618 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | verse | GEN | 1533 | 32358 | 0 | 0 | 6 | 0 |
| hebrew | edition_complete | ketiv | verse | EXO | 1213 | 26088 | 0 | 0 | 11 | 0 |
| hebrew | edition_complete | ketiv | verse | LEV | 859 | 18908 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | verse | NUM | 1289 | 25248 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | verse | DEU | 959 | 23148 | 0 | 0 | 19 | 0 |
| hebrew | edition_complete | ketiv | verse | JOS | 658 | 15925 | 0 | 0 | 24 | 0 |
| hebrew | edition_complete | ketiv | verse | JDG | 618 | 15523 | 0 | 0 | 15 | 0 |
| hebrew | edition_complete | ketiv | verse | RUT | 85 | 2035 | 0 | 0 | 6 | 0 |
| hebrew | edition_complete | ketiv | verse | 1SA | 811 | 20825 | 0 | 0 | 49 | 0 |
| hebrew | edition_complete | ketiv | verse | 2SA | 695 | 17076 | 0 | 0 | 58 | 0 |
| hebrew | edition_complete | ketiv | verse | 1KI | 817 | 20391 | 0 | 0 | 31 | 0 |
| hebrew | edition_complete | ketiv | verse | 2KI | 719 | 18786 | 0 | 0 | 38 | 0 |
| hebrew | edition_complete | ketiv | verse | 1CH | 943 | 16714 | 0 | 0 | 20 | 0 |
| hebrew | edition_complete | ketiv | verse | 2CH | 822 | 21379 | 0 | 0 | 19 | 0 |
| hebrew | edition_complete | ketiv | verse | EZR | 280 | 5827 | 0 | 0 | 19 | 0 |
| hebrew | edition_complete | ketiv | verse | NEH | 405 | 8543 | 0 | 0 | 12 | 0 |
| hebrew | edition_complete | ketiv | verse | EST | 167 | 4904 | 0 | 0 | 9 | 0 |
| hebrew | edition_complete | ketiv | verse | JOB | 1070 | 12609 | 0 | 0 | 39 | 0 |
| hebrew | edition_complete | ketiv | verse | PSA | 2527 | 30245 | 0 | 0 | 40 | 0 |
| hebrew | edition_complete | ketiv | verse | PRO | 915 | 9798 | 0 | 0 | 31 | 0 |
| hebrew | edition_complete | ketiv | verse | ECC | 222 | 4536 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | verse | SNG | 117 | 2018 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | verse | ISA | 1291 | 25663 | 0 | 0 | 26 | 0 |
| hebrew | edition_complete | ketiv | verse | JER | 1364 | 32934 | 0 | 0 | 72 | 0 |
| hebrew | edition_complete | ketiv | verse | LAM | 154 | 2284 | 0 | 0 | 17 | 0 |
| hebrew | edition_complete | ketiv | verse | EZK | 1273 | 29746 | 0 | 0 | 70 | 0 |
| hebrew | edition_complete | ketiv | verse | DAN | 357 | 9489 | 0 | 0 | 54 | 0 |
| hebrew | edition_complete | ketiv | verse | HOS | 197 | 3640 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | verse | JOL | 73 | 1459 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | verse | AMO | 146 | 3055 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | verse | OBA | 21 | 439 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | verse | JON | 48 | 1089 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | verse | MIC | 105 | 2134 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | ketiv | verse | NAM | 47 | 844 | 0 | 0 | 4 | 0 |
| hebrew | edition_complete | ketiv | verse | HAB | 56 | 1017 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | verse | ZEP | 53 | 1144 | 0 | 0 | 2 | 0 |
| hebrew | edition_complete | ketiv | verse | HAG | 38 | 927 | 0 | 0 | 1 | 0 |
| hebrew | edition_complete | ketiv | verse | ZEC | 211 | 4861 | 0 | 0 | 5 | 0 |
| hebrew | edition_complete | ketiv | verse | MAL | 55 | 1323 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | GEN | 6648 | 29135 | 0 | 0 | 0 | 3 |
| hebrew | edition_complete | qere | clause | EXO | 4707 | 24061 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | LEV | 3491 | 17587 | 0 | 0 | 0 | 2 |
| hebrew | edition_complete | qere | clause | NUM | 4276 | 23442 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | DEU | 4238 | 21744 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | JOS | 2534 | 14771 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | JDG | 3122 | 13936 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | RUT | 507 | 1805 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | 1SA | 4390 | 18605 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | 2SA | 3509 | 15494 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | 1KI | 3966 | 18721 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | 2KI | 3722 | 17055 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | 1CH | 2555 | 15469 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | 2CH | 3581 | 19616 | 0 | 0 | 0 | 1 |
| hebrew | edition_complete | qere | clause | EZR | 855 | 5516 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | NEH | 1337 | 7932 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | EST | 813 | 4608 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | JOB | 3593 | 11687 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | PSA | 7694 | 28574 | 0 | 0 | 0 | 1 |
| hebrew | edition_complete | qere | clause | PRO | 2609 | 9149 | 0 | 0 | 0 | 1 |
| hebrew | edition_complete | qere | clause | ECC | 1107 | 4252 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | SNG | 509 | 1967 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | ISA | 6507 | 23899 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | JER | 6963 | 30852 | 0 | 0 | 0 | 1 |
| hebrew | edition_complete | qere | clause | LAM | 555 | 2217 | 0 | 0 | 0 | 2 |
| hebrew | edition_complete | qere | clause | EZK | 6150 | 27605 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | DAN | 1955 | 8802 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | HOS | 881 | 3321 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | JOL | 335 | 1340 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | AMO | 806 | 2856 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | OBA | 98 | 409 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | JON | 250 | 974 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | MIC | 509 | 1988 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | NAM | 215 | 778 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | HAB | 294 | 943 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | ZEP | 251 | 1082 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | HAG | 173 | 871 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | ZEC | 1086 | 4450 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | clause | MAL | 315 | 1203 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | GEN | 1529 | 161465 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | EXO | 1209 | 130236 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | LEV | 855 | 94167 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | NUM | 1285 | 125833 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | DEU | 955 | 115401 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | JOS | 654 | 79262 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | JDG | 614 | 77222 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | RUT | 81 | 9838 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | 1SA | 807 | 103996 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | 2SA | 691 | 85218 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | 1KI | 813 | 101658 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | 2KI | 715 | 93718 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | 1CH | 939 | 83426 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | 2CH | 818 | 106403 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | EZR | 276 | 28850 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | NEH | 401 | 42340 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | EST | 163 | 24111 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | JOB | 1066 | 62927 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | PSA | 2523 | 151210 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | PRO | 911 | 48964 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | ECC | 218 | 22442 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | SNG | 113 | 9833 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | ISA | 1287 | 128055 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | JER | 1360 | 164666 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | LAM | 150 | 11162 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | EZK | 1269 | 148992 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | DAN | 353 | 47519 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | HOS | 193 | 17764 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | JOL | 69 | 6988 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | AMO | 142 | 14788 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | OBA | 17 | 1777 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | JON | 44 | 4972 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | MIC | 101 | 10293 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | NAM | 43 | 3870 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | HAB | 52 | 4749 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | ZEP | 49 | 5214 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | HAG | 34 | 4123 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | ZEC | 207 | 23834 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | five_verse | MAL | 51 | 6258 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | GEN | 1533 | 32365 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | EXO | 1213 | 26102 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | LEV | 859 | 18912 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | NUM | 1289 | 25253 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | DEU | 959 | 23175 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | JOS | 658 | 15953 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | JDG | 618 | 15541 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | RUT | 85 | 2041 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | 1SA | 811 | 20892 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | 2SA | 695 | 17155 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | 1KI | 817 | 20429 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | 2KI | 719 | 18831 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | 1CH | 943 | 16739 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | 2CH | 822 | 21400 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | EZR | 280 | 5856 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | NEH | 405 | 8557 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | EST | 167 | 4917 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | JOB | 1070 | 12660 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | PSA | 2527 | 30299 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | PRO | 915 | 9834 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | ECC | 222 | 4542 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | SNG | 117 | 2022 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | ISA | 1291 | 25697 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | JER | 1364 | 33016 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | LAM | 154 | 2303 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | EZK | 1273 | 29882 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | DAN | 357 | 9587 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | HOS | 197 | 3641 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | JOL | 73 | 1459 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | AMO | 146 | 3057 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | OBA | 21 | 440 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | JON | 48 | 1089 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | MIC | 105 | 2134 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | NAM | 47 | 849 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | HAB | 56 | 1018 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | ZEP | 53 | 1146 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | HAG | 38 | 928 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | ZEC | 211 | 4867 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | sentence | MAL | 55 | 1323 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | GEN | 1532 | 64700 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | EXO | 1212 | 52166 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | LEV | 858 | 37796 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | NUM | 1288 | 50454 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | DEU | 958 | 46296 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | JOS | 657 | 31867 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | JDG | 617 | 31039 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | RUT | 84 | 4039 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | 1SA | 810 | 41743 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | 2SA | 694 | 34265 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | 1KI | 816 | 40817 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | 2KI | 718 | 37633 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | 1CH | 942 | 33452 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | 2CH | 821 | 42735 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | EZR | 279 | 11664 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | NEH | 404 | 17076 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | EST | 166 | 9782 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | JOB | 1069 | 25289 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | PSA | 2526 | 60570 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | PRO | 914 | 19647 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | ECC | 221 | 9060 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | SNG | 116 | 4021 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | ISA | 1290 | 51348 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | JER | 1363 | 65994 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | LAM | 153 | 4575 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | EZK | 1272 | 59722 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | DAN | 356 | 19140 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | HOS | 196 | 7235 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | JOL | 72 | 2899 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | AMO | 145 | 6061 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | OBA | 20 | 835 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | JON | 47 | 2136 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | MIC | 104 | 4232 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | NAM | 46 | 1667 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | HAB | 55 | 2006 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | ZEP | 52 | 2230 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | HAG | 37 | 1783 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | ZEC | 210 | 9671 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | two_verse | MAL | 54 | 2618 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | GEN | 1533 | 32365 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | EXO | 1213 | 26102 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | LEV | 859 | 18912 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | NUM | 1289 | 25253 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | DEU | 959 | 23175 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | JOS | 658 | 15953 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | JDG | 618 | 15541 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | RUT | 85 | 2041 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | 1SA | 811 | 20892 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | 2SA | 695 | 17155 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | 1KI | 817 | 20429 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | 2KI | 719 | 18831 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | 1CH | 943 | 16739 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | 2CH | 822 | 21400 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | EZR | 280 | 5856 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | NEH | 405 | 8557 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | EST | 167 | 4917 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | JOB | 1070 | 12660 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | PSA | 2527 | 30299 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | PRO | 915 | 9834 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | ECC | 222 | 4542 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | SNG | 117 | 2022 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | ISA | 1291 | 25697 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | JER | 1364 | 33016 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | LAM | 154 | 2303 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | EZK | 1273 | 29882 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | DAN | 357 | 9587 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | HOS | 197 | 3641 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | JOL | 73 | 1459 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | AMO | 146 | 3057 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | OBA | 21 | 440 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | JON | 48 | 1089 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | MIC | 105 | 2134 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | NAM | 47 | 849 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | HAB | 56 | 1018 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | ZEP | 53 | 1146 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | HAG | 38 | 928 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | ZEC | 211 | 4867 | 0 | 0 | 0 | 0 |
| hebrew | edition_complete | qere | verse | MAL | 55 | 1323 | 0 | 0 | 0 | 0 |

## Passage-length distributions

| corpus | analysis profile | analysis reading | granularity | passage count | minimum | mean | p25 | median | p75 | p95 | maximum |
|---|---|---|---|---|---|---|---|---|---|---|---|
| greek | critical_core | source | clause | 46072 | 1 | 2.982 | 1 | 2 | 4 | 8 | 155 |
| greek | critical_core | source | five_verse | 7806 | 23 | 86.874 | 75 | 85 | 97 | 119 | 163 |
| greek | critical_core | source | sentence | 7984 | 1 | 17.208 | 9 | 14 | 22 | 40 | 165 |
| greek | critical_core | source | two_verse | 7890 | 4 | 34.718 | 28 | 34 | 41 | 52 | 88 |
| greek | critical_core | source | verse | 7918 | 2 | 17.351 | 12 | 17 | 21 | 30 | 58 |
| greek | edition_complete | source | clause | 46216 | 1 | 2.981 | 1 | 2 | 4 | 8 | 155 |
| greek | edition_complete | source | five_verse | 7834 | 23 | 86.846 | 75 | 85 | 97 | 119 | 163 |
| greek | edition_complete | source | sentence | 8011 | 1 | 17.199 | 9 | 14 | 22 | 40 | 165 |
| greek | edition_complete | source | two_verse | 7915 | 4 | 34.705 | 28 | 34 | 41 | 52 | 88 |
| greek | edition_complete | source | verse | 7943 | 2 | 17.346 | 12 | 17 | 21 | 30 | 58 |
| hebrew | critical_core | ketiv | clause | 97034 | 1 | 4.51 | 2 | 4 | 6 | 11 | 54 |
| hebrew | critical_core | ketiv | five_verse | 23057 | 15 | 102.297 | 74 | 105 | 127 | 157 | 251 |
| hebrew | critical_core | ketiv | sentence | 23213 | 2 | 20.46 | 12 | 19 | 27 | 39 | 81 |
| hebrew | critical_core | ketiv | two_verse | 23174 | 4 | 40.921 | 28 | 40 | 51 | 69 | 123 |
| hebrew | critical_core | ketiv | verse | 23213 | 2 | 20.46 | 12 | 19 | 27 | 39 | 81 |
| hebrew | critical_core | qere | clause | 97106 | 1 | 4.518 | 2 | 4 | 6 | 11 | 54 |
| hebrew | critical_core | qere | five_verse | 23057 | 15 | 102.509 | 74 | 105 | 127 | 157 | 251 |
| hebrew | critical_core | qere | sentence | 23213 | 2 | 20.502 | 12 | 19 | 27 | 39 | 81 |
| hebrew | critical_core | qere | two_verse | 23174 | 4 | 41.006 | 28 | 40 | 52 | 69 | 123 |
| hebrew | critical_core | qere | verse | 23213 | 2 | 20.502 | 12 | 19 | 27 | 39 | 81 |
| hebrew | edition_complete | ketiv | clause | 97034 | 1 | 4.51 | 2 | 4 | 6 | 11 | 54 |
| hebrew | edition_complete | ketiv | five_verse | 23057 | 15 | 102.297 | 74 | 105 | 127 | 157 | 251 |
| hebrew | edition_complete | ketiv | sentence | 23213 | 2 | 20.46 | 12 | 19 | 27 | 39 | 81 |
| hebrew | edition_complete | ketiv | two_verse | 23174 | 4 | 40.921 | 28 | 40 | 51 | 69 | 123 |
| hebrew | edition_complete | ketiv | verse | 23213 | 2 | 20.46 | 12 | 19 | 27 | 39 | 81 |
| hebrew | edition_complete | qere | clause | 97106 | 1 | 4.518 | 2 | 4 | 6 | 11 | 54 |
| hebrew | edition_complete | qere | five_verse | 23057 | 15 | 102.509 | 74 | 105 | 127 | 157 | 251 |
| hebrew | edition_complete | qere | sentence | 23213 | 2 | 20.502 | 12 | 19 | 27 | 39 | 81 |
| hebrew | edition_complete | qere | two_verse | 23174 | 4 | 41.006 | 28 | 40 | 52 | 69 | 123 |
| hebrew | edition_complete | qere | verse | 23213 | 2 | 20.502 | 12 | 19 | 27 | 39 | 81 |

## Reference-gap analysis

| corpus | analysis profile | analysis reading | granularity | passage count |
|---|---|---|---|---|
| greek | critical_core | source | clause | 17 |
| greek | critical_core | source | five_verse | 54 |
| greek | critical_core | source | sentence | 1 |
| greek | critical_core | source | two_verse | 15 |
| greek | edition_complete | source | clause | 17 |
| greek | edition_complete | source | five_verse | 54 |
| greek | edition_complete | source | sentence | 1 |
| greek | edition_complete | source | two_verse | 15 |

The identifier-level audit rows are in `m5-reference-gap-passages.csv`; no omitted verse record or reconstructed text is included.

## Disputed-passage analysis

| corpus | analysis profile | analysis reading | granularity | passage count |
|---|---|---|---|---|
| greek | edition_complete | source | clause | 144 |
| greek | edition_complete | source | five_verse | 28 |
| greek | edition_complete | source | sentence | 27 |
| greek | edition_complete | source | two_verse | 25 |
| greek | edition_complete | source | verse | 25 |

The identifier-level audit rows are in `m5-disputed-passages.csv`.

## Ketiv structural-resolution analysis

### Uncertain passages

| analysis profile | granularity | passage count |
|---|---|---|
| critical_core | clause | 568 |
| critical_core | five_verse | 3083 |
| critical_core | sentence | 720 |
| critical_core | two_verse | 1377 |
| critical_core | verse | 720 |
| edition_complete | clause | 568 |
| edition_complete | five_verse | 3083 |
| edition_complete | sentence | 720 |
| edition_complete | two_verse | 1377 |
| edition_complete | verse | 720 |

### Distinct Ketiv-stream token resolution statuses

| structural resolution status | token count |
|---|---|
| partially_resolved | 819 |
| resolved | 449 |
| source_native | 473664 |

Unresolved clause membership is never fabricated. Every affected token remains in verse analysis and receives an explicit granularity-specific exclusion where required.

## Explicit exclusion counts

| corpus | analysis profile | analysis reading | granularity | reason code | resolution status | exclusion count |
|---|---|---|---|---|---|---|
| hebrew | critical_core | ketiv | clause | ketiv_clause_mapping_unresolved | unresolved | 255 |
| hebrew | critical_core | ketiv | clause | primary_clause_annotation_unavailable | source_annotation_unavailable | 37024 |
| hebrew | critical_core | qere | clause | primary_clause_annotation_unavailable | source_annotation_unavailable | 37195 |
| hebrew | edition_complete | ketiv | clause | ketiv_clause_mapping_unresolved | unresolved | 255 |
| hebrew | edition_complete | ketiv | clause | primary_clause_annotation_unavailable | source_annotation_unavailable | 37024 |
| hebrew | edition_complete | qere | clause | primary_clause_annotation_unavailable | source_annotation_unavailable | 37195 |

Identifier-level Ketiv exclusion evidence is in `m5-ketiv-structural-exclusions.csv`.

## Determinism results

- Overall: **PASSED**
- First run ID: `passages-v1-00e261abea9ed44ef087`
- Second run ID: `passages-v1-00e261abea9ed44ef087`
- Run IDs match: `true`
- Logical hashes match: `true`
- Physical hashes match: `true`
- Input digests match: `true`

## Logical and physical output hashes

### Logical table hashes

| Item | SHA-256 |
|---|---|
| `passage_adjacency` | `1ca8c79f92b2742e12586b6c72eaddbcc834d5bce818b909f33b2c10b9db69bd` |
| `passage_membership` | `726c6b9339a78e7806bac90f7d91930c7f86bec7c7c0be6a51bdedb7a54d40bd` |
| `passages` | `00047c9dc16ceaefdc0ff1b18a8fb2b4480a1be0534ed861cf5c11706d2048a0` |
| `segmentation_exclusions` | `6a0e475398e76730b5a7a92370ee319b803c0d17ba45e01b7155fa3b28c7e209` |
| `segmentation_issues` | `2f3a57eada1dda388ca99bf67cd0b6de70fb31afa1abc1980eafbf605359eac3` |

### Physical table hashes

| Item | SHA-256 |
|---|---|
| `passage_adjacency` | `1971ea2037b70e9b269bd967750af89f2e497707216f322056739748f6483b68` |
| `passage_membership` | `de8d1755c82b81103b5a0eaa1f76ac4cec87d1e37ef91afea34b62f7e5db5293` |
| `passages` | `5c020664588c21cedcca8deb17e9ff54422bd13535bb83ca32e9fa58a6f16a8e` |
| `segmentation_exclusions` | `fd8c744f55460fb34214ee41f0d7380c7217e8f8e9caf05673e845554627e1e2` |
| `segmentation_issues` | `59431e7579d1b4cd4f288a6ea24c0a1d35a31f8a10e8f5282177bfc78ddaf623` |

## Runtime and storage footprint

- First full run: 2245.249000 seconds; 598.698 MiB
- Second full run: 2225.401000 seconds; 598.698 MiB
- Persisted current-run metadata: 2225.400735 seconds; 598.698 MiB

### Runtime by corpus, profile, reading, and granularity

No partition-level runtime evidence was supplied.

### Logical table row counts

| Item | Rows |
|---|---|
| `passage_adjacency` | `913445` |
| `passage_membership` | `21530271` |
| `passages` | `914497` |
| `segmentation_exclusions` | `148948` |
| `segmentation_issues` | `0` |

## Validation results

- Persisted-artifact validation: **PASSED**
- Errors: 0
- Warnings: 0
- Informational findings: 0

### Generation issue inventory

| severity | code | issue count |
|---|---|---|
| none |  |  |

## Manual and scripted spot checks

| check id | category | reference | passage id | corpus | analysis profile | analysis reading | granularity | token count | membership count | verification sha256 | source ids | disputed passage | reference gap | ketiv structural uncertainty | exclusion count | neighbor check | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| g-chapter-crossing-window | Greek chapter-crossing two-verse window | ["MAT 1:25","MAT 2:1"] | P_GNT_EDITION_COMPLETE_SOURCE_TWO_VERSE_MAT_001_025_MAT_002_001~512b0576e92cd7c585e95075679fdf5f9985543deedf5c03cdb5184ef248ce64 | greek | edition_complete | source | two_verse | 34 | 34 | b1d6fd0633662d0277276fddfcca14733d6d00b70aebc4e1996992eebeaef600 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-edition-omitted-verse-gap | Edition-omitted verse gap | ["MAT 17:20","MAT 17:22"] | P_GNT_EDITION_COMPLETE_SOURCE_TWO_VERSE_MAT_017_020_MAT_017_022~787da2b971dd4fbe1eb16ca6e4c706faab3b2dfc0b24db9e83124b5c5db05c45 | greek | edition_complete | source | two_verse | 50 | 50 | b0602ef0dbd3e0e425e3c3e54874a7bf0419f58da139358d1566ac696b7d157c | ["macula-greek"] | false | true | false | 0 | passed | PASS |
| g-elision | Greek elision reconstruction | ["MAT 1:20"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MAT_001_020~0c4289985bada65465651a70dc89fad8e92113de810c75cb85dfe571a7d7de20 | greek | edition_complete | source | verse | 31 | 31 | bf7f6b17790c9d647fb45b240de3e673635a248acdea9f768b14bb6cdb7ccc34 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-general-letter | General letter | ["JAS 1:1"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JAS_001_001~b06f934101c2cdb307240445164faef2080202d6d42ecb94ca196ba911a4ef42 | greek | edition_complete | source | verse | 15 | 15 | 0cc782730fc76d996a7acf229d38f480007a906ed5952ba5252834f77ec4a029 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-john | John | ["JHN 1:1"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_001_001~bc7468c57cac90cb85e9315d0373bc73d1d1fe5444b11f2fe82e6a64dbf7e057 | greek | edition_complete | source | verse | 17 | 17 | e50bc445aa717b005d9ac0c2b0f6e201b8c9826dc0380d3d8c2c517bb55dd154 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-john-7-52-boundary | John 7:52 before disputed-text boundary | ["JHN 7:52"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_007_052~d245d8fcfe05c4668cfac76bc7bec7a9c2736ee56ada60490f27d12b487a70a9 | greek | edition_complete | source | verse | 21 | 21 | 526b553203ed6117840979e83d7d0fb2d9b2092f82ab61b124ec85a7fcdd3236 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-john-8-12-boundary | John 8:12 after disputed-text boundary; edition-complete versus critical-core | ["JHN 8:12"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_012~4dc4155a4a286a7323f82b90996d1f2b90dc30d1f16e39dd947082b66b80f84b | greek | edition_complete | source | verse | 28 | 28 | c7a5486c843d28c5cb5438ef1dae771565f98d9dfd146ecf8e28f791fee6dbed | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-john-pericope-adulterae | John 7:53 through 8:11; edition-complete versus critical-core | ["JHN 7:53","JHN 8:1","JHN 8:2","JHN 8:3","JHN 8:4","JHN 8:5","JHN 8:6","JHN 8:7","JHN 8:8","JHN 8:9","JHN 8:10","JHN 8:11"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_007_053~b7d330c358c0eba268b8f1f561ba49a6203e3748f5f0ad97eb284d1bc79b73b2,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_001~ad775386b4a3423532717d7b85c654d78d914aa73f415eae3635796888635c00,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_002~e1d1b85d0cc58e624a9efdd0fb69f891d0d9bc031dbd928656cab2e8e9642f86,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_003~ad2b1f6bb5cb4e944c849ec03537ecc6c0e14458989a9a253d6e82c950e539a4,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_004~e500565500af2c66b7bc8425713304ef1736ae33faffb264814bc0ff8385820f,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_005~693f1a38eaf1b430047196688944ab75b0905bd892ee24e00965b4c812df2336,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_006~aa00bfc184d3512b90cdaee0c774a362d6c888aa3e9ad9870a21577afaffcb83,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_007~c4b431e1db9f0969d026860d15c2e6058bac13ea3b6fab221f0aeb814455bdd4,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_008~a42f70ad46addc2fe4bf3f6d5ad4fd97a2ab42d3f73d515531dc10e2c2747117,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_009~b8335da74ebccf332d4ba55b794b21b826ec66e7daddeb9a33625c5609d6626a,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_010~65dd3ef809e78ac183881ac675ec95d2e26a5164a14a2e1b4329280a08fb53a9,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_008_011~d1335bbb4bedaf2e66997b2ad38812afb8f783b6bd96d90b7bd786570fc3bc15 | greek | edition_complete | source | verse | 190 | 190 | 3e61d6426ae895b659ec4923cff606fb01a6b4775ab2eaf3796e3a87c70d95bd | ["macula-greek"] | true | false | false | 0 | passed | PASS |
| g-mark-16-8-boundary | Mark 16:8 before disputed-text boundary | ["MRK 16:8"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_008~5b605f7722e0092939e633f10164d0266df59be4a1ec9ead93523c29d1d48e91 | greek | edition_complete | source | verse | 18 | 18 | 6bac051194f64e3f4b056aefde4536eb3e608b48beafebe5d8e73f97b5b6df06 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-mark-alternate-ending | Mark 16:99 alternate ending and analytical boundary | ["MRK 16:99"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_099~5327b4c8b1f8d683c3582d63d954572f92b4c770899967eb2b6835ef2e6c1f76 | greek | edition_complete | source | verse | 33 | 33 | 82a17d9f0cfcbce213e4785e087920942428eb94bdd7adfa695467f5b57c1c7a | ["macula-greek"] | true | false | false | 0 | passed | PASS |
| g-mark-longer-ending | Mark 16:9 through 16:20; edition-complete versus critical-core | ["MRK 16:9","MRK 16:10","MRK 16:11","MRK 16:12","MRK 16:13","MRK 16:14","MRK 16:15","MRK 16:16","MRK 16:17","MRK 16:18","MRK 16:19","MRK 16:20"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_009~28da1ea23370ad4ef6d8377efeefb2a51a26b7a24ace9cdeedf76f52eaa1bc8f,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_010~5e7c1ebdeceb05283ff367e83887d429c5a5fd708d0447b0ae1a1080eb011b8e,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_011~87e3a464629d74bc3d5bb8cd513fcf197ea9de6b2e7041c53ca0896e45c95b67,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_012~b21b8913c11bea1a5904ee2bc699cec0121a1439a24eb30cdceeefca03185411,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_013~2dc8deb9f7e2c31258536d17bc0cdc75c3f576b83a4e26244e9f555ac2b06768,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_014~5bbd0d615e32c7a1ea6d843235c2d07fcc9909e634b4e220687d81c1463e364b,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_015~29b024e5e84dda1335d66b847a22cfaeea71ad9229e1d875b13879e6b0612e36,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_016~8ff538237c09c68fedc68fc2923b518a173efda60eb731b3523766fcc04cee9a,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_017~a60b4d7cf376e22c4b7c5e3554afbb2dc375a1fc614e1ae1acb1fdc4a9af64d1,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_018~be614c9cb6f4f7f55a36bebef1dff86f5fc6bfbf8b62f770425e5c3a07a9355f,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_019~625e83612e8b2b341e0bc52aee496c5e0c4413feee782541bb4c8386630555da,P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_020~8388eb549c7da95850ec819cf4b093bff94c7df11878c714e6c6c554f8961927 | greek | edition_complete | source | verse | 167 | 167 | f31d65e45b0f5d0a946a1f64e447aeac6e1c11775870ab1b1fad974e213b28a7 | ["macula-greek"] | true | false | false | 0 | passed | PASS |
| g-multiverse-sentence | Greek sentence spanning multiple verses | ["MAT 1:2","MAT 1:3","MAT 1:4","MAT 1:5","MAT 1:6"] | P_GNT_EDITION_COMPLETE_SOURCE_SENTENCE_MAT_001_002_MAT_001_006~3a050cd739ba2899f370ecc9e52025b1549b5b80f784b07237089ad5eb50c4c0 | greek | edition_complete | source | sentence | 82 | 82 | a65b3a7a2cf5a85dbf775edc921e342cdfafc18398945d047887c7dd75bbf3be | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-pauline-letter | Pauline letter | ["ROM 8:1"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_ROM_008_001~bc768c434ae3ad878fc1c1336a3c9fad1d1060021d42446347bcdfc8091cbe4a | greek | edition_complete | source | verse | 8 | 8 | e720465db2999499f6c55c979ccf5129faf141e7b5a66469b12ad19591de7ea8 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-revelation | Revelation | ["REV 1:1"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_REV_001_001~6e217846896b68fa524295b4de30d01aff00c1fb890f8095ffc044fa6563283c | greek | edition_complete | source | verse | 28 | 28 | 92a424dd5e311bd890fc534ac8ce2223a6d087a43a260f07fa76f4ef5e70dc56 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| g-synoptic-punctuation | Synoptic narrative; Greek leading and trailing punctuation reconstruction | ["MRK 1:1"] | P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_001_001~823627c0ab76af006c84d29b7250351332d72aa7638cb67ef326f080b8ff5d06 | greek | edition_complete | source | verse | 7 | 7 | 5067beca26f0a3bbd63ff4494265b1ebdb558fa74db1463853df6b11df3c80e7 | ["macula-greek"] | false | false | false | 0 | passed | PASS |
| h-chapter-crossing-two-verse | Chapter-crossing two-verse window | ["GEN 1:31","GEN 2:1"] | P_HB_EDITION_COMPLETE_QERE_TWO_VERSE_GEN_001_031_GEN_002_001~5d2eeea455b8bd2b62a72c9cd9387959a1387d94110fc8d76d1e884996fcfdc2 | hebrew | edition_complete | qere | two_verse | 31 | 31 | c7554f0d125ba9f917265242639b5abdddf798471ceefeccbb5adaabe0ccb745 | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-daniel-language-transition | Daniel Hebrew-to-Aramaic transition | ["DAN 2:4"] | P_HB_EDITION_COMPLETE_QERE_VERSE_DAN_002_004~2607e1b71bfc9718cdf56eb83cbdf1cd3ddcf47e82c896ae0de19a8f2782802f | hebrew | edition_complete | qere | verse | 23 | 23 | fbdb08dffc0d44c6e2960b347417644b371da9d658f41a81247812d93bc4ceba | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-ezra-aramaic | Ezra Aramaic | ["EZR 4:8"] | P_HB_EDITION_COMPLETE_QERE_VERSE_EZR_004_008~50f6d56f13c110adc2e3531447cf293dfb0763a21c17e86267956c2e9d8cba5e | hebrew | edition_complete | qere | verse | 17 | 17 | b6401fd2fb5c32d1e3ce2335c4a5e8c1f6f0a62a9228fa138d46c54f8e7254da | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-five-verse-window | Five-verse window and full overlap accounting | ["GEN 1:1","GEN 1:2","GEN 1:3","GEN 1:4","GEN 1:5"] | P_HB_EDITION_COMPLETE_QERE_FIVE_VERSE_GEN_001_001_GEN_001_005~807ca12a6e5ac04852fa91fc600de0caaa14f991f45ee2abb3f9d2cffc712696 | hebrew | edition_complete | qere | five_verse | 78 | 78 | 20633b9473dacce314249c64d0e7aa481c255c3fccdc6b9e70dc72aa7f7b4495 | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-fully-resolved-ketiv-clause | Fully resolved Ketiv clause; clause passage | ["1CH 1:11"] | P_HB_EDITION_COMPLETE_KETIV_CLAUSE_1CH_001_011~38255b4ee4aae5e40398d3b2c7361bd690a522969dc41cc87b31064d2c2263ec | hebrew | edition_complete | ketiv | clause | 13 | 13 | 8e8513f01b388ddcc06df9727628087bdd9ee541da072b451c2a496d4edca153 | ["macula-hebrew","oshb-morphhb"] | false | false | false | 0 | passed | PASS |
| h-genesis-narrative | Genesis narrative | ["GEN 22:1"] | P_HB_EDITION_COMPLETE_QERE_VERSE_GEN_022_001~e9a9b5c0ed08edff146d53f2f2986e1491038bea8b044ac77626b4e29963252c | hebrew | edition_complete | qere | verse | 22 | 22 | ddb2a252273c7472aac7e5e3de4944248fcf3c3f2ff784ae21549fcd5fd35318 | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-job-wisdom | Job or Proverbs | ["JOB 38:1"] | P_HB_EDITION_COMPLETE_QERE_VERSE_JOB_038_001~e032815945648437a830e7edc6a421b3333b64556d4b4f29249b55a5096df402 | hebrew | edition_complete | qere | verse | 10 | 10 | 140d8c2280a4c1ea5d260420f627aab96fdfb84de739c7970491294c6e99b4fa | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-ketiv-only-locus | Kings; Ketiv-only locus | ["2KI 5:18"] | P_HB_EDITION_COMPLETE_KETIV_VERSE_2KI_005_018~126c2279e2fef16200604b3a1323c3426ec51c529cbee56da97893eda52f608c | hebrew | edition_complete | ketiv | verse | 46 | 46 | 6e8ceafe85eb7061c7e8737aa264809a67ae978694b276ed3489694ff3af12cb | ["macula-hebrew","oshb-morphhb"] | false | false | true | 0 | passed | PASS |
| h-major-prophet | Major prophet | ["ISA 6:1"] | P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_006_001~85c2d7d176a55ba23b41d76060cb21cabe99806a550d5fd3d4805784c6c7ee83 | hebrew | edition_complete | qere | verse | 24 | 24 | 2fd087f7ec651c18216270028940ad5b2a71bffa30a8871dfefe616d990a66a8 | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-minor-prophet | Minor prophet | ["OBA 1:1"] | P_HB_EDITION_COMPLETE_QERE_VERSE_OBA_001_001~d3e29fcde7583a90f596f696a3e4ccdca20b16f2190d02fc1eb3943fb9c7ee3f | hebrew | edition_complete | qere | verse | 28 | 28 | 4751fdbfbf0b4193a1501af0d063edb6392325af7a137bbd8d0ae536c966b06d | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-partial-ketiv-structure | Partially resolved Ketiv structural locus with explicit clause exclusion | ["1CH 2:16"] | P_HB_EDITION_COMPLETE_KETIV_VERSE_1CH_002_016~a1eed8a0c03dd479a453262980f4c1d0cab86e56b23276097aed4a97aefbe920 | hebrew | edition_complete | ketiv | verse | 14 | 14 | def6d12ce009415273891218a19262af98db0671229e33a2940b29fe022b3964 | ["macula-hebrew","oshb-morphhb"] | false | false | true | 1 | passed | PASS |
| h-psalms | Psalms | ["PSA 23:1"] | P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_023_001~f3c3b679268f4b41a854bf4faa783738379145241ded4766abd849c5bea3deab | hebrew | edition_complete | qere | verse | 8 | 8 | 2e2b53850ba5bb3bac05b9b240098750c8b6cec25d805fe39bf650427e479da2 | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |
| h-samuel-paired-multiword-kq | Samuel narrative; paired Ketiv/Qere locus; multiword Ketiv locus | ["1SA 9:1"] | P_HB_EDITION_COMPLETE_KETIV_VERSE_1SA_009_001~e26be744da9974061c93ae2e5e978daa12edea8c54545fe82065930a921228b2 | hebrew | edition_complete | ketiv | verse | 22 | 22 | ff5dfe3c47c51314e14a7203bed306f45e82afab1a2ecadbce369b313e8614f0 | ["macula-hebrew","oshb-morphhb"] | false | false | true | 0 | passed | PASS |
| h-torah-legal | Torah legal material | ["LEV 19:18"] | P_HB_EDITION_COMPLETE_QERE_VERSE_LEV_019_018~bbd92a909b65df8ca5f273657a53d31b4d93c12ad7484f47e99d4db7ff1a0c8d | hebrew | edition_complete | qere | verse | 18 | 18 | c7226d97f8fd6d253641b5814cb47d0201387af0f1eb6fdce5e71d01277f71af | ["macula-hebrew"] | false | false | false | 0 | passed | PASS |

## Known limitations

- MACULA source annotations contain 37195 Qere-primary rows without clause assignments per profile; each omission is explicit rather than fabricated.
- The OSHB supplement resolves 1013 of 1268 Ketiv tokens to clauses; the remaining 255 tokens per profile have explicit clause exclusions while remaining in verse analysis.
- Runtime telemetry is recorded for each complete run, not independently for each granularity because all five granularities are generated together per book.
- The metadata Parquet leaf contains runtime telemetry and therefore differs physically between runs; its telemetry-excluded logical hash matches, and every content leaf is byte-identical.

## Acceptance gate

| Gate | Status | Evidence |
|---|---|---|
| Verified Milestone 4 handoff | PASSED | PR #5 merged as b4b5c707d9eb852c01652df438455c828c0100a8; post-merge gates and source anchors passed. |
| Five passage granularities and six streams | PASSED | Clause, sentence, verse, two-verse, and five-verse passages exist for all governed profile/reading combinations. |
| Exact identity and membership | PASSED | 914497 unique deterministic passages reproduce from 21530271 authoritative ordered membership rows. |
| Source structure and Ketiv uncertainty | PASSED | Resolved mappings are used; 510 unresolved Ketiv clause exclusions are explicit across both profiles; every Ketiv token remains in verse analysis. |
| Profiles, disputed text, and continuity | PASSED | Critical-core excludes exactly 390 tokens in 25 extant references; no profile exclusion or Mark 16:20-to-16:99 boundary is bridged. |
| Reference gaps and omitted verses | PASSED | No omitted verse record is fabricated; valid extant-source gaps are flagged in 174 passages across both Greek profiles. |
| Language-aware reconstruction | PASSED | Hebrew, Aramaic, and Greek reconstruction and ordered analytical arrays pass persisted validation and 30 sanitized spot checks. |
| Two-run determinism | PASSED | Run IDs, all six logical hashes, five content-table physical hashes, and all 3570 content Parquet leaf hashes match. |
| Quality and full-corpus regressions | PASSED | Both strict validators returned zero findings; pinned full-corpus regression suite passes 20/20. |
| Repository and milestone boundary | PASSED | Generated/source data remain ignored; no benchmark, retrieval, scoring, embedding, candidate, or review-console implementation began. |

Every Milestone 5 acceptance gate passed.

## Exact next recommended task

Milestone 6 only: define the benchmark schema and validation contract, acquire OpenBible cross-references as licensed Tier 3 weak supervision, and validate the existing header-only Tier 1 benchmark without implementing retrieval, scoring, embeddings, candidates, or review tooling.
