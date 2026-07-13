# Milestone 5 passage spot-check evidence

Generated deterministically by `scripts/generate_m5_spot_check_evidence.py`
from `outputs/reports/m5-spot-check-config.json` and the local full-corpus
DuckDB artifact. Biblical text, lemma values, and token identifiers are hashed
and are not reproduced here. Passage identifiers and canonical references are
retained as auditable non-textual evidence.

- Specification schema: 1
- Checks passed: 30/30
- Required facets: passage_id, references, token_membership, token_order, reconstruction, lemma_sequence, granularity, analysis_profile, analysis_reading, source_provenance, disputed_status, reference_gap_status, ketiv_uncertainty, exclusions, neighbor_windows

| check_id | category | passage_count | membership_count | disputed_count | reference_gap_count | ketiv_uncertainty_count | exclusion_count | verification_sha256 | neighbor_check | comparison_check | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h-genesis-narrative | Genesis narrative | 1 | 22 | 0 | 0 | 0 | 0 | ddb2a252273c7472aac7e5e3de4944248fcf3c3f2ff784ae21549fcd5fd35318 | passed | not_applicable | PASS |
| h-torah-legal | Torah legal material | 1 | 18 | 0 | 0 | 0 | 0 | c7226d97f8fd6d253641b5814cb47d0201387af0f1eb6fdce5e71d01277f71af | passed | not_applicable | PASS |
| h-samuel-paired-multiword-kq | Samuel narrative; paired Ketiv/Qere locus; multiword Ketiv locus | 1 | 22 | 0 | 0 | 1 | 0 | ff5dfe3c47c51314e14a7203bed306f45e82afab1a2ecadbce369b313e8614f0 | passed | edition_complete/qere:1 | PASS |
| h-psalms | Psalms | 1 | 8 | 0 | 0 | 0 | 0 | 2e2b53850ba5bb3bac05b9b240098750c8b6cec25d805fe39bf650427e479da2 | passed | not_applicable | PASS |
| h-job-wisdom | Job or Proverbs | 1 | 10 | 0 | 0 | 0 | 0 | 140d8c2280a4c1ea5d260420f627aab96fdfb84de739c7970491294c6e99b4fa | passed | not_applicable | PASS |
| h-major-prophet | Major prophet | 1 | 24 | 0 | 0 | 0 | 0 | 2fd087f7ec651c18216270028940ad5b2a71bffa30a8871dfefe616d990a66a8 | passed | not_applicable | PASS |
| h-minor-prophet | Minor prophet | 1 | 28 | 0 | 0 | 0 | 0 | 4751fdbfbf0b4193a1501af0d063edb6392325af7a137bbd8d0ae536c966b06d | passed | not_applicable | PASS |
| h-ezra-aramaic | Ezra Aramaic | 1 | 17 | 0 | 0 | 0 | 0 | b6401fd2fb5c32d1e3ce2335c4a5e8c1f6f0a62a9228fa138d46c54f8e7254da | passed | not_applicable | PASS |
| h-daniel-language-transition | Daniel Hebrew-to-Aramaic transition | 1 | 23 | 0 | 0 | 0 | 0 | fbdb08dffc0d44c6e2960b347417644b371da9d658f41a81247812d93bc4ceba | passed | not_applicable | PASS |
| h-ketiv-only-locus | Kings; Ketiv-only locus | 1 | 46 | 0 | 0 | 1 | 0 | 6e8ceafe85eb7061c7e8737aa264809a67ae978694b276ed3489694ff3af12cb | passed | edition_complete/qere:1 | PASS |
| h-fully-resolved-ketiv-clause | Fully resolved Ketiv clause; clause passage | 1 | 13 | 0 | 0 | 0 | 0 | 8e8513f01b388ddcc06df9727628087bdd9ee541da072b451c2a496d4edca153 | passed | not_applicable | PASS |
| h-partial-ketiv-structure | Partially resolved Ketiv structural locus with explicit clause exclusion | 1 | 14 | 0 | 0 | 1 | 1 | def6d12ce009415273891218a19262af98db0671229e33a2940b29fe022b3964 | passed | not_applicable | PASS |
| h-multiverse-sentence-inventory | Hebrew sentence spanning multiple verses if present (none in source annotations) | 0 | 0 | 0 | 0 | 0 | 0 | 985c746391bc625cda6fce8875de4046ef94a776d0f441b6a4cebbede93c757d | passed | not_applicable | PASS |
| h-chapter-crossing-two-verse | Chapter-crossing two-verse window | 1 | 31 | 0 | 0 | 0 | 0 | c7554f0d125ba9f917265242639b5abdddf798471ceefeccbb5adaabe0ccb745 | passed | not_applicable | PASS |
| h-five-verse-window | Five-verse window and full overlap accounting | 1 | 78 | 0 | 0 | 0 | 0 | 20633b9473dacce314249c64d0e7aa481c255c3fccdc6b9e70dc72aa7f7b4495 | passed | not_applicable | PASS |
| g-synoptic-punctuation | Synoptic narrative; Greek leading and trailing punctuation reconstruction | 1 | 7 | 0 | 0 | 0 | 0 | 5067beca26f0a3bbd63ff4494265b1ebdb558fa74db1463853df6b11df3c80e7 | passed | not_applicable | PASS |
| g-john | John | 1 | 17 | 0 | 0 | 0 | 0 | e50bc445aa717b005d9ac0c2b0f6e201b8c9826dc0380d3d8c2c517bb55dd154 | passed | not_applicable | PASS |
| g-pauline-letter | Pauline letter | 1 | 8 | 0 | 0 | 0 | 0 | e720465db2999499f6c55c979ccf5129faf141e7b5a66469b12ad19591de7ea8 | passed | not_applicable | PASS |
| g-general-letter | General letter | 1 | 15 | 0 | 0 | 0 | 0 | 0cc782730fc76d996a7acf229d38f480007a906ed5952ba5252834f77ec4a029 | passed | not_applicable | PASS |
| g-revelation | Revelation | 1 | 28 | 0 | 0 | 0 | 0 | 92a424dd5e311bd890fc534ac8ce2223a6d087a43a260f07fa76f4ef5e70dc56 | passed | not_applicable | PASS |
| g-multiverse-sentence | Greek sentence spanning multiple verses | 1 | 82 | 0 | 0 | 0 | 0 | a65b3a7a2cf5a85dbf775edc921e342cdfafc18398945d047887c7dd75bbf3be | passed | not_applicable | PASS |
| g-elision | Greek elision reconstruction | 1 | 31 | 0 | 0 | 0 | 0 | bf7f6b17790c9d647fb45b240de3e673635a248acdea9f768b14bb6cdb7ccc34 | passed | not_applicable | PASS |
| g-chapter-crossing-window | Greek chapter-crossing two-verse window | 1 | 34 | 0 | 0 | 0 | 0 | b1d6fd0633662d0277276fddfcca14733d6d00b70aebc4e1996992eebeaef600 | passed | not_applicable | PASS |
| g-edition-omitted-verse-gap | Edition-omitted verse gap | 1 | 50 | 0 | 1 | 0 | 0 | b0602ef0dbd3e0e425e3c3e54874a7bf0419f58da139358d1566ac696b7d157c | passed | not_applicable | PASS |
| g-mark-16-8-boundary | Mark 16:8 before disputed-text boundary | 1 | 18 | 0 | 0 | 0 | 0 | 6bac051194f64e3f4b056aefde4536eb3e608b48beafebe5d8e73f97b5b6df06 | passed | critical_core/source:1 | PASS |
| g-mark-longer-ending | Mark 16:9 through 16:20; edition-complete versus critical-core | 12 | 167 | 12 | 0 | 0 | 0 | f31d65e45b0f5d0a946a1f64e447aeac6e1c11775870ab1b1fad974e213b28a7 | passed | critical_core/source:0 | PASS |
| g-mark-alternate-ending | Mark 16:99 alternate ending and analytical boundary | 1 | 33 | 1 | 0 | 0 | 0 | 82a17d9f0cfcbce213e4785e087920942428eb94bdd7adfa695467f5b57c1c7a | passed | critical_core/source:0 | PASS |
| g-john-7-52-boundary | John 7:52 before disputed-text boundary | 1 | 21 | 0 | 0 | 0 | 0 | 526b553203ed6117840979e83d7d0fb2d9b2092f82ab61b124ec85a7fcdd3236 | passed | critical_core/source:1 | PASS |
| g-john-pericope-adulterae | John 7:53 through 8:11; edition-complete versus critical-core | 12 | 190 | 12 | 0 | 0 | 0 | 3e61d6426ae895b659ec4923cff606fb01a6b4775ab2eaf3796e3a87c70d95bd | passed | critical_core/source:0 | PASS |
| g-john-8-12-boundary | John 8:12 after disputed-text boundary; edition-complete versus critical-core | 1 | 28 | 0 | 0 | 0 | 0 | c7a5486c843d28c5cb5438ef1dae771565f98d9dfd146ecf8e28f791fee6dbed | passed | critical_core/source:1 | PASS |

The companion CSV records the selected passage IDs, exact references, source
IDs, language counts, punctuation/elision counts, and separate membership,
reconstruction, lemma-sequence, and provenance hashes for every check.
