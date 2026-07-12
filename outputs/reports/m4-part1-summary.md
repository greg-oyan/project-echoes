# Milestone 4 Part 1 summary: OSHB Ketiv/Qere supplement

Date: 2026-07-11; PR repair completed 2026-07-12
Branch: `feature/m4-part1-oshb-ketiv-qere` (cut from post-merge main after PR #3)
Executing agents: Claude (initial delegated run); Codex (PR #4 repair)

All tasks completed with green gates; no blocker report was needed and no stop
condition fired. Every commit passed `uv run ruff check .`,
`uv run ruff format --check .`, `uv run mypy src`, and `uv run pytest`; the
full-corpus work additionally passed
`ECHOES_RUN_FULL_CORPUS=1 uv run pytest tests/regression` (7/7),
`echoes validate-corpus` (hebrew, greek, unified), `echoes validate-sources`
(with canonical-hash recomputation over three locally present sources), and
`echoes validate-config`.

## Digest table (stop-condition anchors)

All recorded digests for both primary corpora remain identical before and
after the supplement repair:

| Corpus | Tokens | Digest | Before (recorded baseline) | After (post-supplement) |
|---|---:|---|---|---|
| Hebrew | 475,911 | identity | `91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6` | identical |
| Hebrew | 475,911 | content | `7fb443c3f0c42ada5d89f3abad61dd304145863044107ac86277c9f05f76cc82` | identical |
| Greek | 137,779 | identity | `9035fea8d73a2b2078ad2adc70f8389040dbe2051ee535b2ce88412f551df6f2` | identical |
| Greek | 137,779 | content | `a5ede58d287c2d29d5dacc7adeb07ff5c6a10587e2949875928b2dd935c8c683` | identical |
| Hebrew | 475,911 | analytical | `9464a106684b63ff57bcd9dd754bcd0c875d7ea8157fc7bfe643d7eb66dab173` | identical |
| Greek | 137,779 | analytical | `31404eb29a1f71855f3670f6f895e3fadc3ab0b39e2685c3cf672620df08a2a1` | identical |

The content digest (`corpus_content_digest`) was introduced by Task 1 of this
run: SHA-256 over corpus-position-ordered
`token_id\0surface_form\0normalized_form\0lemma\n` rows encoded UTF-8, null
lemma as the empty string. All four values are asserted permanently by the
opt-in full-corpus regression.

The historical `corpus_content_digest` is now documented accurately as a
surface/normalized-form/lemma compatibility digest. The separate versioned
`corpus_analytical_digest` covers stable source identity, source and normalized
forms, lexical, morphological, sentence/clause/phrase, syntactic, semantic,
participant, language, and variant fields. It canonicalizes null and serialized
JSON, excludes environment-dependent values, and is invariant to input row
order.

## PR #4 repair addendum (2026-07-12)

### Source-native OSHB identity

OSHB loci now preserve both the exact OSIS `source_book_identifier` and the
mapped `canonical_book`. Token IDs normalize only the source identifier to
bounded uppercase ASCII alphanumerics; source references retain the exact OSIS
casing, while `book` and all MACULA joins use the canonical code. The corrected
2 Kings example is:

```text
token_id:                 HB_2KGS_008_010_0006~94c99d606560
source_edition_reference: 2Kgs 8:10
source_word_id:            2Kgs 8:10!6
book / canonical_book:     2KI
source_book_identifier:    2Kgs
```

Changing the `2Kgs -> 2KI` mapping cannot change that token ID. Of the 1,268
supplement IDs, 813 changed because their source OSIS book identifier differs
from the former canonical namespace; all 1,268 corrected IDs remain unique and
collision-free. No primary Hebrew or Greek token ID changed.

### Corrected supplement hashes and determinism

The corrected K/Q schema version is 2 and run ID is
`oshb-kq-0fed79a1841208ff4d77`. Two consecutive full `ingest-oshb-kq --force`
runs produced a byte-identical `table-hashes.json`, proving both physical
Parquet and logical-table determinism.

| Table | Parquet SHA-256 | Logical SHA-256 |
|---|---|---|
| Ketiv tokens | `c14187ed7cdcfa03367c2fbc1a2630e08f0dc51258626d78d95e96967d9cf7da` | `7bb67cebc45c06943a7f1fc2e241202f100a19cf7ad6dd6b0933d999ac01d238` |
| Locus registry | `61d3bb76c218537dfc401864685100285308367aa5f2020a2101a97d3c696304` | `ae6e70a8d1dd75cccfef85bb5535051134104f03d57490976d4e30f93c60f022` |
| Structural alignments | `ce59933c69da553f1b74a26296606fc141bdc46c9b9efc399926be9f2e654b58` | `ac0c9ebffe971ef9178ef47edbf868d9f904a189133dccf907f815651b867df9` |

### Explicit Ketiv analytical structure

`kq_structural_alignments.parquet` contains one row for every Ketiv token,
with a first-class locus ID, separate sentence/clause/phrase memberships,
ordered structural anchors, method, confidence, resolution status, and
field-level notes. Paired loci use unanimous replaced-Qere anchors. Ketiv-only
loci use the nearest primary token on each side within the same verse and only
when both agree. No inherited value is written into an OSHB source-native
annotation field.

| Measure | Resolved | Total | Rate |
|---|---:|---:|---:|
| Sentence membership, loci | 1,251 | 1,251 | 100.00% |
| Clause membership, loci | 998 | 1,251 | 79.78% |
| Phrase membership, loci | 449 | 1,251 | 35.89% |
| Fully resolved structure, loci | 448 | 1,251 | 35.81% |
| Partially resolved structure, loci | 803 | 1,251 | 64.19% |
| Wholly unresolved structure, loci | 0 | 1,251 | 0.00% |

At token level, 449 of 1,268 rows are fully resolved and 819 are partially
resolved; sentence/clause/phrase memberships resolve for 1,268/1,013/450
tokens respectively. Every partial full-corpus locus and every field-level
reason is enumerated in
[`m4-part1-structural-unresolved.csv`](m4-part1-structural-unresolved.csv).
The enriched Ketiv stream exposes the resolved IDs and computes clause
positions from them; null membership always carries an explicit partial or
unresolved status and reason.

### Approved disputed-passage policy

`MRK 16:20 -> MRK 16:99` is now modeled as a physical source successor and a
separate mandatory analytical boundary. No two- or five-verse window may cross
it. `edition_complete` retains every inline edition token;
`critical_core` excludes `MRK 16:9-20`, `MRK 16:99`, and `JHN 7:53-8:11`.
Omitted verse numbers are never fabricated; source-order windows across an
edition omission must record `reference_gap`; alternate readings are never
concatenated because of file order. Future disputed-text candidates require a
data-quality flag and cannot remain unqualified strong candidates without the
registered exclusion survival or textual-critical review.

## Task 0 — Ratify and merge PR #3: COMPLETED

- ADR 0009 moved Proposed → Accepted with the owner-ratification line; ADR
  0010 gained its ratification line; cross-references updated.
- PR #3 merged into main with a merge commit (`61cdcdf`), matching PRs #1-#2;
  the remote feature branch was deleted. This merge was explicitly owner-
  sanctioned, superseding the standing no-merge rule for PR #3 only.
- Post-merge main passed the complete quality suite including the opt-in
  full-corpus regression (then 4/4 gates), validate-corpus (unified),
  validate-sources, and validate-config.

## Task 1 — Content-level digest baseline: COMPLETED

- `corpus_content_digest` implemented beside `corpus_identity_digest` (one
  shared function for both corpora), exact encoding documented in
  `docs/data-sources.md` and `docs/experiment-log.md`.
- Both corpora's content digests computed from the full processed tables and
  recorded (table above); the Greek identity digest was also pinned as a
  constant for the first time. Unit tests cover ordering invariance,
  null-lemma encoding, and change detection.

## Task 2 — Governed OSHB acquisition: COMPLETED

- `openscriptures/morphhb` acquired at the pinned commit
  `3d15126fb1ef74867fc1434be1942e837932691f` under the canonical-byte policy
  (`core.autocrlf=false`, `* -text`, bytes hashed as received): 42 files
  (39 `wlc` OSIS book files, `wlc/VerseMap.xml`, README, LICENSE).
- Manifest entry moved planned → acquired → validated with download date,
  expected files, and receipt. The three anchors were externally verified
  against raw.githubusercontent.com at the pinned commit and match exactly:
  `README.md 2da25acf…`, `LICENSE.md 9bf4a289…`, `wlc/2Kgs.xml 056db539…`.
- `echoes validate-sources` recomputes canonical hashes for all three locally
  present sources and passes.
- The sparse-checkout heuristic was fixed additively (suffix-less include
  paths are directories) so top-level directories like `wlc` acquire
  correctly; prior acquisitions are unaffected.

## Task 3 — Ketiv/Qere supplement per ADR 0009: COMPLETED

**Keying premise verified corpus-wide before implementation** (all stop
conditions cleared with enormous margin):

- 1,108/1,108 K/Q verses frame-match: MACULA's present word numbers equal
  OSHB's slot walk minus ketiv slots, exactly.
- 0 gap violations: every OSHB ketiv keys into a vacant MACULA slot; 0 loci
  where ketiv appears without a MACULA gap (stop threshold: isolated
  exceptions only).
- 1,254/1,254 qere surfaces match MACULA **exactly** under NFC — a 0.0%
  mismatch rate against the 5% stop threshold. Zero MACULA gaps exist outside
  OSHB K/Q verses.
- The only three structurally unusual loci (Jer 48:44, Job 38:1, Job 40:6)
  are intervening *non-variant* notes (one exegesis, two Masora); the
  adjacency rule skips them, and all 1,268 ketiv words attach cleanly.

**Deliverables:**

- Adapter `src/echoes/ingest/oshb_ketiv_qere.py`: slot-walks OSHB OSIS markup
  (`<w type="x-ketiv">` inline; qere in `<note type="variant"><rdg
  type="x-qere">`), emits 1,268 `variant_type=ketiv` canonical schema v2
  tokens with OSHB provenance. Token IDs are generated through the existing
  identity module at the vacant source word positions with source-record
  disambiguation. The initial canonical-book example
  `HB_2KI_008_010_0006~94c99d606560` is superseded by the corrected
  source-native `HB_2KGS_008_010_0006~94c99d606560`; zero collisions
  proven against both corpora (475,911 Hebrew + 137,779 Greek IDs).
- Book-code mapping `src/echoes/align/book_codes.py`: 39-book bijection with
  tests (2Kgs→2KI, Ps→PSA, Song→SNG, Nah→NAM, Joel→JOL, …).
- K/Q locus registry (`kq_locus_registry.parquet` /
  `hebrew_kq_locus_registry`): 1,260 loci with book, chapter, verse, word
  slots, readings, per-locus `alignment_method=vacant_slot_adjacency` and
  confidence, source refs — the queryable artifact for Milestone 7
  `data_quality_status` flagging. A DuckDB view
  (`hebrew_kq_variant_groups`) pairs each ketiv token with its referenced —
  never modified — MACULA qere token.
- Conflict preservation: consonantal or mismatched surfaces produce conflict
  rows with both values and lowered confidence (0.7/0.3), never reconciled.
  **No conflicts exist in the pinned sources** (0 rows); the conflict paths
  are proven by synthetic fixtures instead.
- Reading-flip determinism: `analysis_reading=ketiv` yields a deterministic
  supplemented stream substituting OSHB ketiv readings at all 1,245 paired
  loci with continuous positions; the six ketiv-wela-qere readings join only
  the ketiv stream; the qere stream is **byte-identical** to its
  pre-supplement state (asserted by frame equality in validation and tests).
- Scripted spot checks (asserted in the opt-in regression): 2KI 8:10 ketiv
  `לא` (negative particle, `oshb_morph=HTn`) at vacant slot !6 paired against
  the prepositional qere reading at !7 (MACULA tokens
  `HB_2KI_008_010_0007.01/.02`); plus GEN 8:17, DEU 5:10 (Torah), ISA 3:16
  (Prophets), PSA 5:9 and RUT 2:1 (Writings), all paired/exact/1.0. No
  conflict example exists to record.
- Superseded run ID `oshb-kq-c464b2dbc5818b2532f8`; corrected schema-v2 run
  ID `oshb-kq-0fed79a1841208ff4d77`; validation: 0 errors, 120 warnings
  (all `language-inferred` for ketiv tokens inside documented Aramaic
  passages of Daniel and Ezra).

**Locus statistics** (loci per MACULA book; 1,260 total = 1,245 paired +
6 ketiv-only + 9 qere-only; 1,268 ketiv tokens because eight loci carry
two-word ketiv runs):

| Book | Loci | | Book | Loci | | Book | Loci |
|---|---:|---|---|---:|---|---|---:|
| GEN | 16 | | 2KI | 73 | | PSA | 68 |
| EXO | 12 | | 1CH | 41 | | PRO | 69 |
| LEV | 5 | | 2CH | 38 | | JOB | 53 |
| NUM | 9 | | EZR | 37 | | SNG | 4 |
| DEU | 25 | | NEH | 23 | | RUT | 13 |
| JOS | 32 | | EST | 12 | | LAM | 22 |
| JDG | 20 | | ISA | 53 | | ECC | 12 |
| 1SA | 70 | | JER | 141 | | DAN | 116 |
| 2SA | 89 | | EZK | 134 | | HOS/JOL/AMO/OBA | 5+1+3+1 |
| 1KI | 45 | | MIC/NAM/HAB | 4+4+1 | | ZEP/HAG/ZEC | 2+1+6 |

**Sanity discussion of the total:** 1,260 loci (1,268 ketiv words) sits at
the low end of, but comfortably within, the range commonly cited for the
Leningrad Ketiv/Qere tradition (roughly 1,300–1,600 depending on edition and
counting method — counts differ over qere-wela-ketiv, ketiv-wela-qere,
multi-word loci, and perpetual qere, which editions mark inconsistently).
OSHB encodes 1,260 variant notes for WLC 4.20; MACULA's gap structure
corroborates precisely this set (no unexplained gaps exist on either side).
Whether OSHB's encoding exhausts the tradition — e.g., perpetual qere forms
are *not* marked as variants in either source — is recorded as an open
scholarly question in the manifest, not decided here.

## Task 4 — Annotation-alignment infrastructure: COMPLETED

- Generalized supplementary-annotation schema
  (`src/echoes/align/supplementary.py`): values beside primary annotations
  with per-value source attribution, agreement flag, alignment method, and
  confidence. OSHB is the first tenant: 1,254 `qere_surface` annotation rows
  (all agreeing) derived from the registry, materialized as
  `hebrew_kq_supplementary_annotations`.
- The beside-not-over contract is enforced in validation: rows must
  reference real primary tokens, must faithfully quote the primary value
  (a misquoted primary column is an attempted overwrite and is rejected),
  must not hide disagreement, and must carry method and in-range confidence.
  Synthetic-fixture tests cover every failure path.
- The versification-crosswalk schema gained an additive `book_mappings`
  section, and `data/alignments/oshb-macula-crosswalk.yaml` is the first
  governed crosswalk instance: 39 mappings, `rule_based`, confidence 1.0,
  empirically corroborated by 1,108/1,108 K/Q verse frame matches. Verse-level
  rows remain empty; STEPBible crosswalk tables remain out of scope (owner-
  side licensing questions untouched). A narrowly scoped `.gitignore`
  exception tracks this one metadata file, with the reason recorded inline.

## Task 5 — Disputed-passage segmentation policy: CORRECTED

- The initial `non_contiguous_verse_adjacencies` declaration was removed
  because it conflated source order with analytical continuity.
- Schema version 2 records `MRK 16:20 -> MRK 16:99` separately as an
  alternate-ending source successor and as an analytical boundary prohibiting
  both two-verse and five-verse windows.
- The owner-approved `edition_complete`/`critical_core`, reference-gap,
  no-fabrication, alternate-reading, and disputed-candidate rules are now
  schema-validated. ADR 0011 records the decision. Passage generation remains
  Milestone 5 scope.

## Superseded artifacts

- The `docs/limitations.md` qere-only limitation: superseded in place
  (marked SUPERSEDED with strikethrough, original text retained) by the
  post-supplement state and its confidence caveats.
- The manifest's open question about OSHB K/Q coverage was replaced by a
  sharper post-ingestion question (whether OSHB's 1,260 loci exhaust the
  tradition); the alignment-confidence question is resolved empirically and
  recorded per locus.

## Flagged items for human review

1. **Perpetual qere and tradition coverage:** neither OSHB nor MACULA marks
   perpetual qere forms as variants; whether the 1,260 encoded loci exhaust
   the Leningrad K/Q tradition needs a scholarly cross-check (manifest
   unresolved question).
2. **Disputed-passage implementation:** the owner policy is resolved and
   validated declaratively in this PR. Materializing both profiles, enforcing
   boundaries/reference gaps in passage output, and applying candidate flags
   remain their registered future-milestone work.
3. **Milestone 7 obligation:** candidates whose evidence tokens intersect a
   registry locus must set `data_quality_status`; the registry is ready, the
   flagging is not yet implemented.
4. **STEPBible:** all seven subset-audit licensing questions remain
   owner-side; nothing STEPBible-related was acquired or resolved.
5. **Ketiv lemma namespace:** ketiv tokens carry OSHB lemma/morph in an
   OSHB-namespaced field, not the MACULA lemma column; whether to map OSHB
   Strong-style lemmas into a comparable namespace is future supplementary
   work, not attempted here.

## Repair verification

- `uv sync`: 39 packages resolved and checked.
- Ruff lint and format check: passed; 77 files formatted.
- Mypy: passed; 49 source files.
- Default pytest suite: 207 passed, 8 opt-in full-corpus tests skipped by
  design.
- Opt-in full-corpus regression: 8 passed.
- Configuration validation: 14 files passed.
- Source governance and canonical-hash audit: 12 records and all three locally
  present acquired sources passed.
- Corpus validation: Hebrew 475,911 tokens / 39 books / 929 chapters / zero
  errors; Greek 137,779 / 27 / 260 / zero errors; unified validation passed
  both.
- Full supplement validation: 1,268 Ketiv tokens, zero errors, 120 documented
  Aramaic-language inference warnings; two consecutive physical and logical
  builds identical.

## Commits on this branch

1. `4973ac8` Add content-level corpus digest baseline
2. `586fa4f` Acquire OSHB morphhb at pinned commit with canonical bytes
3. `fb1ba19` Implement the OSHB Ketiv/Qere supplement per ADR 0009
4. `e3c6b2d` Add supplementary annotation-alignment infrastructure
5. `8a4affa` Record the Mark-ending segmentation contiguity constraint
6. `4445020` Milestone 4 Part 1 summary, changelog, and experiment log
7. (this repair commit) Correct source identity, Ketiv structure, disputed
   passage policy, and analytical digests
