# Milestone 5 full-corpus structure audit

Date: 2026-07-12  
Executing agent: Codex  
Scope: read-only inspection of the complete local MACULA Hebrew, MACULA Greek,
and OSHB Ketiv/Qere processed tables before passage-schema design.

No raw source file or bulk source text was copied into this report. Counts and
identifiers were computed in memory from the immutable, Git-ignored Parquet
tables using DuckDB. The audit wrote no corpus table or database.

## Early-stop decision

The early stop is **not triggered**. No source sentence and no source clause
contains both included and excluded `critical_core` tokens, whether the three
configured disputed regions are tested together or separately. All affected
source units are wholly inside an exclusion:

| Disputed passage | References | Tokens | Sentences | Clauses | Phrases | First token | Last token |
|---|---|---:|---:|---:|---:|---|---|
| `mark_longer_ending` | `MRK 16:9-16:20` | 167 | 11 | 68 | 148 | `GNT_MRK_016_009_0001` | `GNT_MRK_016_020_0016` |
| `mark_alternate_ending` | `MRK 16:99` | 33 | 2 | 5 | 31 | `GNT_MRK_016_099_0001` | `GNT_MRK_016_099_0033` |
| `pericope_adulterae` | `JHN 7:53-8:11` | 190 | 14 | 71 | 166 | `GNT_JHN_007_053_0001` | `GNT_JHN_008_011_0018` |
| **Total** | 25 extant verses | **390** | **27** | **144** | **345** | | |

ADR 0011 therefore yields one unambiguous conservative treatment: exclude the
whole affected source units from `critical_core`, never truncate or duplicate
them, and break analytical continuity around the removed region. In
particular, `JHN 7:52` and `JHN 8:12` must not become analytical neighbors.

## Whole-corpus totals

| Corpus | Tokens | Sentence IDs | Clause IDs | Phrase IDs | Null sentence | Null clause | Null phrase |
|---|---:|---:|---:|---:|---:|---:|---:|
| Hebrew/Aramaic | 475,911 | 23,213 | 97,106 | 468,638 | 0 | 37,195 | 0 |
| Greek | 137,779 | 8,011 | 46,216 | 121,995 | 0 | 0 | 14,731 |

No structural identifier is an empty string. Across both corpora, sentence,
clause, and phrase identifiers have zero cross-corpus and zero cross-book
collisions. The observed IDs are globally unique, but passage identity will
still encode corpus, book, and source-unit scope instead of relying on that
incidental property.

## Structure by corpus and book

| Corpus | Book | Sentences | Clauses | Phrases | Null sentence tokens | Null clause tokens | Null phrase tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| hebrew | GEN | 1533 | 6648 | 32010 | 0 | 3230 | 0 |
| hebrew | EXO | 1213 | 4707 | 25736 | 0 | 2041 | 0 |
| hebrew | LEV | 859 | 3491 | 18571 | 0 | 1325 | 0 |
| hebrew | NUM | 1289 | 4276 | 24841 | 0 | 1811 | 0 |
| hebrew | DEU | 959 | 4238 | 22844 | 0 | 1431 | 0 |
| hebrew | JOS | 658 | 2534 | 15601 | 0 | 1182 | 0 |
| hebrew | JDG | 618 | 3122 | 15285 | 0 | 1605 | 0 |
| hebrew | RUT | 85 | 507 | 2020 | 0 | 236 | 0 |
| hebrew | 1SA | 811 | 4390 | 20580 | 0 | 2287 | 0 |
| hebrew | 2SA | 695 | 3509 | 16928 | 0 | 1661 | 0 |
| hebrew | 1KI | 817 | 3966 | 20096 | 0 | 1708 | 0 |
| hebrew | 2KI | 719 | 3722 | 18584 | 0 | 1776 | 0 |
| hebrew | 1CH | 943 | 2555 | 16423 | 0 | 1270 | 0 |
| hebrew | 2CH | 822 | 3581 | 21041 | 0 | 1784 | 0 |
| hebrew | EZR | 280 | 855 | 5793 | 0 | 340 | 0 |
| hebrew | NEH | 405 | 1337 | 8405 | 0 | 625 | 0 |
| hebrew | EST | 167 | 813 | 4848 | 0 | 309 | 0 |
| hebrew | JOB | 1070 | 3593 | 12495 | 0 | 973 | 0 |
| hebrew | PSA | 2527 | 7694 | 29888 | 0 | 1725 | 0 |
| hebrew | PRO | 915 | 2609 | 9704 | 0 | 685 | 0 |
| hebrew | ECC | 222 | 1107 | 4454 | 0 | 290 | 0 |
| hebrew | SNG | 117 | 509 | 1968 | 0 | 55 | 0 |
| hebrew | ISA | 1291 | 6507 | 25249 | 0 | 1798 | 0 |
| hebrew | JER | 1364 | 6963 | 32502 | 0 | 2164 | 0 |
| hebrew | LAM | 154 | 555 | 2252 | 0 | 86 | 0 |
| hebrew | EZK | 1273 | 6150 | 29435 | 0 | 2277 | 0 |
| hebrew | DAN | 357 | 1955 | 9519 | 0 | 785 | 0 |
| hebrew | HOS | 197 | 881 | 3570 | 0 | 320 | 0 |
| hebrew | JOL | 73 | 335 | 1438 | 0 | 119 | 0 |
| hebrew | AMO | 146 | 806 | 2989 | 0 | 201 | 0 |
| hebrew | OBA | 21 | 98 | 435 | 0 | 31 | 0 |
| hebrew | JON | 48 | 250 | 1081 | 0 | 115 | 0 |
| hebrew | MIC | 105 | 509 | 2102 | 0 | 146 | 0 |
| hebrew | NAM | 47 | 215 | 828 | 0 | 71 | 0 |
| hebrew | HAB | 56 | 294 | 1001 | 0 | 75 | 0 |
| hebrew | ZEP | 53 | 251 | 1123 | 0 | 64 | 0 |
| hebrew | HAG | 38 | 173 | 911 | 0 | 57 | 0 |
| hebrew | ZEC | 211 | 1086 | 4784 | 0 | 417 | 0 |
| hebrew | MAL | 55 | 315 | 1304 | 0 | 120 | 0 |
| greek | MAT | 1133 | 6496 | 16117 | 0 | 0 | 2098 |
| greek | MRK | 727 | 4313 | 9720 | 0 | 0 | 1475 |
| greek | LUK | 1155 | 7095 | 17096 | 0 | 0 | 2248 |
| greek | JHN | 1038 | 5820 | 13663 | 0 | 0 | 1931 |
| greek | ACT | 883 | 5952 | 16486 | 0 | 0 | 1728 |
| greek | ROM | 465 | 2204 | 6293 | 0 | 0 | 750 |
| greek | 1CO | 524 | 2488 | 5848 | 0 | 0 | 919 |
| greek | 2CO | 253 | 1451 | 3942 | 0 | 0 | 496 |
| greek | GAL | 150 | 750 | 1979 | 0 | 0 | 239 |
| greek | EPH | 78 | 538 | 2242 | 0 | 0 | 152 |
| greek | PHP | 81 | 482 | 1462 | 0 | 0 | 149 |
| greek | COL | 58 | 348 | 1478 | 0 | 0 | 83 |
| greek | 1TH | 62 | 421 | 1322 | 0 | 0 | 129 |
| greek | 2TH | 34 | 217 | 746 | 0 | 0 | 66 |
| greek | 1TI | 89 | 466 | 1465 | 0 | 0 | 112 |
| greek | 2TI | 74 | 345 | 1140 | 0 | 0 | 85 |
| greek | TIT | 34 | 163 | 618 | 0 | 0 | 33 |
| greek | PHM | 17 | 79 | 308 | 0 | 0 | 23 |
| greek | HEB | 241 | 1488 | 4476 | 0 | 0 | 423 |
| greek | JAS | 133 | 608 | 1545 | 0 | 0 | 177 |
| greek | 1PE | 74 | 480 | 1527 | 0 | 0 | 131 |
| greek | 2PE | 44 | 289 | 1024 | 0 | 0 | 72 |
| greek | 1JN | 144 | 730 | 1886 | 0 | 0 | 241 |
| greek | 2JN | 15 | 73 | 224 | 0 | 0 | 19 |
| greek | 3JN | 21 | 79 | 198 | 0 | 0 | 21 |
| greek | JUD | 18 | 125 | 422 | 0 | 0 | 30 |
| greek | REV | 466 | 2716 | 8768 | 0 | 0 | 901 |

## Cross-reference source units

| Corpus | Unit | Total | Crosses verses | Crosses chapters | Crosses books | Maximum references |
|---|---|---:|---:|---:|---:|---:|
| Hebrew/Aramaic | sentence | 23,213 | 0 | 0 | 0 | 1 |
| Hebrew/Aramaic | clause | 97,106 | 0 | 0 | 0 | 1 |
| Greek | sentence | 8,011 | 1,194 | 0 | 0 | 16 |
| Greek | clause | 46,216 | 277 | 0 | 0 | 16 |

The largest Greek sentence is
`Nestle1904/nodes/03-luke.xml#sentence-0120:LUK 3:23!1-3:38!8` and spans
`LUK 3:23-3:38` (16 extant references, 165 tokens). The largest Greek clause
is `Nestle1904/nodes/03-luke.xml#420030230091550` over the same 16 references
(155 tokens). Source sentence and clause boundaries must therefore be primary;
verse boundaries must not split them.

No sentence or clause crosses a chapter or book boundary. One Hebrew phrase
and 40 Greek phrases cross a verse, but phrase passages are not a Milestone 5
granularity.

## Greek reference gaps and analytical continuity

The pinned edition omits exactly these fifteen verse numbers:

`MAT 17:21`, `MAT 18:11`, `MAT 23:14`, `MRK 7:16`, `MRK 9:44`,
`MRK 9:46`, `MRK 11:26`, `MRK 15:28`, `LUK 17:36`, `LUK 23:17`,
`ACT 8:37`, `ACT 15:34`, `ACT 24:7`, `ACT 28:29`, and `ROM 16:24`.

All fifteen have extant source-order neighbors on either side. They may remain
analytically continuous under ADR 0011, but every affected sentence or window
must set `reference_gap: true`; no omitted verse record may be fabricated.
Exactly one source sentence spans such a gap:
`Nestle1904/nodes/05-acts.xml#sentence-0760:ACT 24:5!1-24:8!13`, which contains
the extant references `ACT 24:5`, `ACT 24:6`, and `ACT 24:8` (44 tokens) around
omitted `ACT 24:7`. No clause spans an edition omission.

`MRK 16:20 -> MRK 16:99` is different: it is both a physical source successor
with a reference gap and a declared analytical break. Its boundary token IDs
are `GNT_MRK_016_020_0016 -> GNT_MRK_016_099_0001`. No source sentence or
clause spans it, and no multi-verse passage may contain both references.

## Zero-width and punctuation records

- Hebrew/Aramaic contains 6,435 explicit zero-width tokens across 4,769
  references. Every one has an empty source and normalized form, all are
  non-variant, and all retain a positive word/subtoken position. They remain
  authoritative passage members but contribute no visible garbage to
  reconstruction.
- Greek contains no punctuation-only or empty-surface token. Punctuation is
  retained as leading/trailing metadata on word tokens and must be reconstructed
  with Greek-specific spacing rules.

## Ketiv structural resolution

The supplement contains 1,268 Ketiv tokens across 1,251 Ketiv-bearing loci.

| Field | Resolved tokens | Total tokens | Coverage | Fully resolved loci | Total loci |
|---|---:|---:|---:|---:|---:|
| sentence | 1,268 | 1,268 | 100% | 1,251 | 1,251 |
| clause | 1,013 | 1,268 | 79.889590% | 998 | 1,251 |
| phrase | 450 | 1,268 | 35.488959% | 449 | 1,251 |

Overall structural status is 449 `resolved` and 819 `partially_resolved`; none
is wholly unresolved because every sentence mapping resolves. Milestone 5 may
use every sentence mapping. It must exclude exactly 255 unresolved Ketiv tokens
from clause granularity with explicit exclusion rows, flag phrase uncertainty
for 818 tokens, and retain all 1,268 tokens in verse-level Ketiv analysis.

Ketiv `position_in_corpus` belongs to the supplement source domain and must not
be intersorted with primary positions. The deterministic
`analysis_position_in_corpus` from `derive_supplemented_analysis_stream` is the
selected Qere/Ketiv stream order used for passage membership.

## Architectural consequences

- Passage IDs scope every source unit by corpus, profile, reading, granularity,
  book, ordered references, and exact ordered token membership.
- Authoritative passage membership stores every token explicitly; start/end
  token IDs are convenience fields only.
- Source structures remain whole. Profile exclusions are analytical selection
  boundaries, never structural truncation.
- Sliding windows use extant source order plus explicit analytical-continuity
  edges, not numeric verse arithmetic.
- Zero-width records remain members, and language-aware reconstruction ignores
  only their visible contribution.
- Unresolved Ketiv clause structure creates explicit exclusions; it never
  creates fabricated clause IDs and never removes the token from verse analysis.
