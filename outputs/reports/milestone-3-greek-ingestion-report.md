# Milestone 3 Greek ingestion report

Status: **PASSED**

This report contains provenance, hashes, aggregate statistics, and validation findings. It intentionally contains no biblical source text or gloss quotations.

## Source and acquisition

- Source: MACULA Greek Linguistic Datasets
- Edition: Nestle 1904 Greek New Testament as represented by the MACULA Greek 24.06.17 Nestle1904 dataset
- Release label: 24.06.17
- Commit: `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`
- License: MACULA Greek Linguistic Datasets © 2022-2024 Biblica, Inc under CC BY 4.0 as the aggregate license; per the pinned LICENSE.md the aggregate includes the Nestle1904 text (published 1904; transcription by Diego Santos, morphology by Ulrik Sandborg-Petersen, markup by Jonathan Robie), SBLGNT-derived data from Logos, MARBLE word-sense data used with permission, Berean Interlinear glosses placed in the public domain as of 2023-04-30, and Cherith glosses under CC BY 4.0
- Redistribution policy: `acquisition_instructions_only`
- Acquisition method: `git_sparse` with canonical-byte handling (`core.autocrlf=false`, `* -text`)
- Acquisition timestamp: `2026-07-11T14:27:03.538166+00:00`
- Acquisition command: `echoes acquire-source macula-greek`
- Tool version: `0.1.0`

### Acquired-file canonical-byte SHA-256 inventory

| Relative file | Bytes | SHA-256 |
|---|---:|---|
| `LICENSE.md` | 3573 | `41b49a2387b628a7bc772ddfae3a8af9dd8f4d4470b27b6132f6da6c73e4a557` |
| `Nestle1904/nodes/01-matthew.xml` | 12674299 | `3e0624343734958b92d0f8de6093d31f8be57e542961216b4257f2f54e43f21c` |
| `Nestle1904/nodes/02-mark.xml` | 7853196 | `f865a3848334103f331dadc134a49afcaf1d1c01b7ddb553328806b8f2237559` |
| `Nestle1904/nodes/03-luke.xml` | 13733939 | `196d7082577db68496f625610a8fb16da1f216a3246443b9b15f22f248b35d88` |
| `Nestle1904/nodes/04-john.xml` | 10795826 | `97c32b1f14e9e7f725a929d2f0c73ce6952756c9d820095e777deae916232d6f` |
| `Nestle1904/nodes/05-acts.xml` | 12889155 | `b9bfda699a204efca16a2eeed17de16318564f0f40d515f4f84016a192ef1c0a` |
| `Nestle1904/nodes/06-romans.xml` | 4810912 | `bf11114c08136c93835142bfd2df48e357255492af791f39a211dc9be825ee9a` |
| `Nestle1904/nodes/07-1corinthians.xml` | 4629104 | `f85f9a6dcb03d67e5fec2f0c919f74dbd9b2615782551f0a5d7668af2f590fb7` |
| `Nestle1904/nodes/08-2corinthians.xml` | 3026726 | `35d91cd547931db9455833ff44fa7452079d33774230ef4855772cf1287ca19c` |
| `Nestle1904/nodes/09-galatians.xml` | 1524712 | `ecf55bf01d3fe07fa4e373cac12c3e03d4b51382bbf789eb0ca5045658452341` |
| `Nestle1904/nodes/10-ephesians.xml` | 1640826 | `50edc8cb4f4473c796091cbd47700b240f32837d7d7cc695f7809b4f8d239cdf` |
| `Nestle1904/nodes/11-philippians.xml` | 1115474 | `4b6ec27c690f6149b8db0ea0ea881de74db7f3002ac435f38e099be6d323b5ea` |
| `Nestle1904/nodes/12-colossians.xml` | 1076115 | `2510d57e11b286448aafdd71e2b9274bc344ebdd0974c5c755df6283737e7e3f` |
| `Nestle1904/nodes/13-1thessalonians.xml` | 995735 | `1ea190855339d9abfff454c02068aeda0d02b96d538c511331bbbdaf9810d4b8` |
| `Nestle1904/nodes/14-2thessalonians.xml` | 553730 | `ef680944b974b94df16f242fc4fad5e07659ebd054e9e72a19e9a42b6398c7a7` |
| `Nestle1904/nodes/15-1timothy.xml` | 1105995 | `dd13af1e9c17fb4107e41f4658f9c946ea7ad87836641d3fc94e813eeb70a9d0` |
| `Nestle1904/nodes/16-2timothy.xml` | 854297 | `902c19d38e892738d7fd4b5ac61c1835aedf3c7389ec7549eb5fcc472d1d886c` |
| `Nestle1904/nodes/17-titus.xml` | 461428 | `78417b7505c71a9e744b6a441a3b42604f8fdcaac944d56e19ca2a01511d8279` |
| `Nestle1904/nodes/18-philemon.xml` | 223454 | `c613cd4c0db8d553ae0527ccf05ea04d9335fcbc50d403274690722be45fa8a4` |
| `Nestle1904/nodes/19-hebrews.xml` | 3439154 | `be14897c9823e23e87067306536d069f3e383893ebadc33bbe56bcca5c3554bc` |
| `Nestle1904/nodes/20-james.xml` | 1186890 | `ebf652da3eb59e7dadb9109cae2cbdc3334e5172a3315a9fe3bfda5f8a6f7d3b` |
| `Nestle1904/nodes/21-1peter.xml` | 1157603 | `dda35cf47b6dcdda3419e19f121f2396ce83f469f4e10cb29fe100e62997a239` |
| `Nestle1904/nodes/22-2peter.xml` | 763151 | `1d34c430152683a23d6b0089cc88c085edb091a38e6a1eed9c5d63fb214e348d` |
| `Nestle1904/nodes/23-1john.xml` | 1421795 | `d693cfbe0d147cf071e4ae086239752ff370650c3e2f619ea05127eeb9d2a3c1` |
| `Nestle1904/nodes/24-2john.xml` | 163107 | `322b41db8624b68eec1794cc68e4be652e57654c6d25e129e2727aead1083921` |
| `Nestle1904/nodes/25-3john.xml` | 151223 | `68e227d03ef8a63a2dc1cbbb706203f40ac9c3d2788c4fe86f50d4b1027d31f6` |
| `Nestle1904/nodes/26-jude.xml` | 325504 | `cede4239434f5606a02ed729326666e7cabb2a0c8363aeb826dfb8d6ef0e4182` |
| `Nestle1904/nodes/27-revelation.xml` | 6466340 | `f0b9d3e5d51173b90ec47be769616a070ccd909389201b5d34bdd1b4d6c63f06` |
| `README.md` | 1985 | `46bc2238caa8dcc0046798f7ce574fc402e460db54c1d396f45a85caf5a09501` |

## Ingestion and schema

- Ingestion run ID: `greek-c35c0121a2fea8b057cd`
- Greek token schema version: `1`
- Normalization configuration hash: `75f562aac9c5451c60e6edbf8f3132c8fcf08324ebbfb8645e210f42dea78708`
- Source records: 137779
- Processed tokens: 137779
- Books: 27
- Chapters: 260
- Verses: 7943
- Elided tokens: 1223
- Punctuation-bearing tokens: 18552
- Processing time: 34.361 seconds

### Token-count sanity check

- Processed token count: 137779.
- Expected published figure: 137,779 leaf word nodes, asserted by the pinned upstream repository's own test suite (`test/test_nestle1904_nodes.py` at commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`, tag 24.06.17); the same figure appears in the upstream lowfat, TEI, and TSV tests for the Nestle1904 dataset.
- MATCH: the processed count equals the upstream published expectation.

### Tokens by book

| Book | Tokens |
|---|---:|
| MAT | 18299 |
| MRK | 11277 |
| LUK | 19456 |
| JHN | 15643 |
| ACT | 18393 |
| ROM | 7100 |
| 1CO | 6820 |
| 2CO | 4469 |
| GAL | 2228 |
| EPH | 2419 |
| PHP | 1630 |
| COL | 1575 |
| 1TH | 1473 |
| 2TH | 822 |
| 1TI | 1588 |
| 2TI | 1237 |
| TIT | 658 |
| PHM | 335 |
| HEB | 4955 |
| JAS | 1739 |
| 1PE | 1676 |
| 2PE | 1098 |
| 1JN | 2136 |
| 2JN | 245 |
| 3JN | 219 |
| JUD | 457 |
| REV | 9832 |

## Annotation completeness

| Annotation | Populated | Missing | Coverage |
|---|---:|---:|---:|
| lemma | 137779 | 0 | 100.0000% |
| morphology | 137779 | 0 | 100.0000% |
| syntax | 137779 | 0 | 100.0000% |
| semantic_domain | 127292 | 10487 | 92.3885% |
| word_sense | 127291 | 10488 | 92.3878% |
| gloss | 137622 | 157 | 99.8860% |

## Validation

- Errors: 0
- Warnings: 0
- Informational findings: 6

- No validation errors or warnings.

## Determinism

- This report rerun rebuilt the corpus from the verified canonical-byte acquisition receipt; raw files are stored and hashed exactly as received.
- Ingestion run ID `greek-c35c0121a2fea8b057cd` is derived from the pinned commit, normalization configuration hash, canonical raw-file hashes, and schema version, and is reproduced identically on reruns.
- The logical token-table SHA-256 was `8423575e8bb94d127acb71a4427e43cfa64946c225156d6e6eeeb2ec1c8162f5` for this rebuild.
- The Parquet token-file SHA-256 was `33631cc3340c45119f903e1c442a4c63d9cf50ddcf6b7a5dbd1661da3a823e1d` for this rebuild.
- DuckDB row counts and logical fingerprints matched the Parquet artifacts after transactional reload; reruns introduced no duplicate rows.
- Unified cross-corpus checks passed: distinct corpus and provenance values, no token-ID collisions, and Hebrew plus Greek row counts sum exactly.

## Scripted spot checks

Each check executed as an assertion against the processed corpus with the expected value recorded before comparison.

| Reference | Category | Expected | Observed | Status |
|---|---|---|---|---|
| MAT 5:3 | Synoptic sample (Sermon on the Mount) | 12 tokens, 0 elided, 2 punctuation-bearing, continuous positions, complete provenance and lemmas | 12 tokens, 0 elided, 2 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| MRK 1:2 | Synoptic sample with quotation framing | 20 tokens, 0 elided, 2 punctuation-bearing, continuous positions, complete provenance and lemmas | 20 tokens, 0 elided, 2 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| LUK 15:11 | Synoptic sample (Lukan parable opening) | 7 tokens, 0 elided, 1 punctuation-bearing, continuous positions, complete provenance and lemmas | 7 tokens, 0 elided, 1 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| JHN 1:1 | John prologue | 17 tokens, 0 elided, 3 punctuation-bearing, continuous positions, complete provenance and lemmas | 17 tokens, 0 elided, 3 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| ROM 3:23 | Pauline letter | 9 tokens, 0 elided, 1 punctuation-bearing, continuous positions, complete provenance and lemmas | 9 tokens, 0 elided, 1 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| JAS 1:1 | General letter opening | 15 tokens, 0 elided, 1 punctuation-bearing, continuous positions, complete provenance and lemmas | 15 tokens, 0 elided, 1 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| REV 22:20 | Revelation closing | 11 tokens, 0 elided, 4 punctuation-bearing, continuous positions, complete provenance and lemmas | 11 tokens, 0 elided, 4 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| JHN 8:3 | Pericope adulterae (disputed passage) | 18 tokens, 0 elided, 2 punctuation-bearing, continuous positions, complete provenance and lemmas | 18 tokens, 0 elided, 2 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| MRK 16:9 | Longer ending of Mark (disputed passage) | 15 tokens, 1 elided, 3 punctuation-bearing, continuous positions, complete provenance and lemmas | 15 tokens, 1 elided, 3 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| MAT 8:2 | Enclitic and punctuation case | 13 tokens, 0 elided, 2 punctuation-bearing, continuous positions, complete provenance and lemmas | 13 tokens, 0 elided, 2 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| JHN 3:2 | Elision case | 32 tokens, 1 elided, 4 punctuation-bearing, continuous positions, complete provenance and lemmas | 32 tokens, 1 elided, 4 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| ACT 8:36 | Versification boundary (edition omits ACT 8:37) | 20 tokens, 0 elided, 4 punctuation-bearing, continuous positions, complete provenance and lemmas | 20 tokens, 0 elided, 4 punctuation-bearing, continuous=True, provenance_complete=True, lemma_complete=True | PASS |
| JHN 7:53-8:11 | Disputed passage: pericope adulterae | 190 tokens present inline in the pinned Nestle 1904 representation | 190 tokens present inline | PASS |
| MRK 16:9-20; MRK 16:99 | Edition-level versification: endings of Mark | longer ending inline at 16:9-20; shorter ending encoded at out-of-sequence verse 99 with 33 tokens | longer ending tokens=167 (verses 9-20 present), verse-99 tokens=33 | PASS |
| ACT 8:37 | Edition-level versification: omitted verse | 0 tokens; the pinned edition omits this verse entirely | 0 tokens | PASS |
| MAT 8:2 and corpus-wide | Enclitic/accent policy: surface accents preserved | 6 accent-regularized tokens in MAT 8:2 and 37183 corpus-wide where the preserved source NormalizedForm differs from the punctuation-separated surface (grave and enclitic accentuation preserved in surface_form) | 6 accent-regularized tokens in MAT 8:2, 37183 corpus-wide | PASS |
| corpus-wide | Punctuation and elision handling | 1223 elided tokens; 18552 punctuation-bearing tokens with lossless separation; 0 standalone punctuation tokens (punctuation is attached to word text in this representation) | 1223 elided, 18552 punctuation-bearing, 0 standalone punctuation tokens | PASS |

## Items flagged for human review

- The pinned Nestle 1904 representation includes the pericope adulterae (JHN 7:53-8:11, 190 tokens) inline without a variant marker. Whether analyses should treat this disputed passage separately is an interpretation question for human review, not decided here.
- The pinned edition encodes the shorter ending of Mark at the out-of-sequence verse MRK 16:99 (33 tokens) after the inline longer ending (16:9-20). How analyses should treat the endings of Mark is flagged for human review.
- MARBLE-derived LN and LexDomain values are included upstream by permission; their appearance in redistributable derived outputs still needs a field-level human licensing review (recorded as the manifest's unresolved question).

## Local environment

- Python: `3.12.13`
- Operating system: `Windows 11`
- Machine: `AMD64`

## Known limitations

- The selected node representation has no formal XSD; the adapter pins and validates the observed structure.
- The Nestle 1904 edition omits several later-numbered verses and includes the pericope adulterae inline; edition-level versification is recorded, not silently harmonized.
- The aggregate combines components with distinct attribution and downstream-publication conditions; MARBLE word-sense fields are included by permission.
- The SBLGNT representation in the same release documents unmapped nodes lacking Gloss, Louw-Nida, and Domain values and is not selected.

## Acceptance gate

The Milestone 3 acceptance gate passed.
