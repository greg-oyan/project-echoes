# Overnight run summary

Date: 2026-07-11
Branch: `feature/canonical-hashes-and-m3-greek`
Executing agent: Claude (unattended overnight run)

All four tasks completed with green gates. Every commit passed
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, and
`uv run pytest` (enforced additionally by pre-commit hooks), plus
`validate-config` and `validate-sources`. No blocker report was needed.

## Task 1 — Canonical-byte checksum remediation (Hebrew): COMPLETED

- Root cause confirmed: the acquisition sparse checkout inherited the global
  `core.autocrlf=true`, so Git rewrote LF to CRLF in text-classified files
  before hashing (`data/raw/.../README.md` had CRLF terminators and 2,297
  bytes versus 2,275 canonical bytes). The acquisition clone does not retain a
  `.git` object store, so the source was re-fetched at pinned commit
  `7ab368fcb14e4ad2e0f784138241a098fb516ec4`.
- Fix: acquisition checkouts now set `core.autocrlf=false` and declare
  `* -text` in `.git/info/attributes`; HTTP acquisitions already hashed the
  download stream (verified).
- The full 932-file inventory was recomputed from canonical bytes
  (381,774,487 total bytes). The three manifest anchors were externally
  verified against `raw.githubusercontent.com` at the pinned commit:
  `README.md eab7e833…`, `LICENSE.md df45ba32…`,
  `WLC/nodes/macula-hebrew.xml 050c0616…`.
- `echoes validate-sources` now recomputes canonical hashes for
  manifest-hashed files whose raw data is present locally; synthetic-fixture
  unit and CLI tests cover matching bytes, CRLF-rewritten bytes, missing
  files, and absent local data.
- The Milestone 2 ingestion report was regenerated with the canonical
  inventory and scripted spot checks; the superseded text-mode inventory is
  retained, marked superseded, as an appendix inside the regenerated report.
- **Gate evidence (stop condition satisfied):** re-ingestion from
  canonical-byte raw data produced 475,911 tokens with zero validation
  findings; the corpus identity digest equals
  `91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6`
  exactly, and the opt-in full-corpus regression now asserts the digest and
  token count permanently. `ECHOES_RUN_FULL_CORPUS=1 uv run pytest
  tests/regression` and `echoes validate-corpus` both passed.
- New Hebrew run ID `hebrew-9e089f330652392a0dff` (run IDs incorporate
  raw-file hashes, so the change is expected and documented).

## Task 2 — OSHB Ketiv/Qere governance (manifest and docs only): COMPLETED

- Pinned `openscriptures/morphhb` at `3d15126fb1ef74867fc1434be1942e837932691f`
  (the default branch is named `master`, not `main`; recorded as a known
  limitation). License verified from canonical bytes at the pinned commit:
  CC BY 4.0 for lemma/morphology data, public-domain WLC text, exact
  attribution sentence recorded; LICENSE.md canonical-byte SHA-256
  `9bf4a289…`.
- Added the `oshb-morphhb` manifest entry: role `supplementary_annotation`,
  purpose "paired Ketiv/Qere layer for Milestone 4", full license fields,
  lifecycle `planned`, `raw_data_git_policy: ignored_local_only`, and no
  acquisition (none authorized).
- ADR 0009 (status Proposed, executing_agent Claude) records the strategy:
  OSHB ketiv records key into the word-number gaps MACULA preserves —
  re-verified locally at 2KI 8:10, where word numbers run !1–!14 with slot !6
  absent and the qere-only reading at !7 — producing `variant_type=ketiv`
  tokens per canonical schema v2 with the qere stream unchanged, an
  alignment-confidence field, and conflicts preserved per master plan 10.4.
  The existing adapter's `type`-attribute detection path and a dedicated
  supplement adapter are both left open.
- `docs/limitations.md` now states the corpus is qere-only with Ketiv
  readings silently absent until the layer lands and that candidates whose
  evidence intersects known K/Q loci must set `data_quality_status`
  (Milestone 7 scope); `docs/novelty-review.md` mirrors the rule as
  textual-variant exposure under review rubric question 14.

## Task 3 — Milestone 3 MACULA Greek ingestion: COMPLETED

- **Licensing and edition selection:** current release identified as tag
  `24.06.17`, commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`. LICENSE.md
  and README.md read from canonical bytes: MACULA Greek aggregate © 2022-2024
  Biblica, Inc under CC BY 4.0 with required attribution, plus per-component
  terms as they appear (Nestle1904 text; SBLGNT data from Logos with the
  license noting its update to CC BY 4.0; MARBLE word senses used with
  permission; Berean glosses public domain as of 2023-04-30; Cherith glosses
  CC BY 4.0). Terms clearly permit local machine processing with attribution
  — the stop condition did not fire. ADR 0010 (Accepted) selects the
  **Nestle1904** node dataset, superseding the provisional SBLGNT v1.2
  intent, because the release's own SBLGNT README documents unmapped nodes
  with missing Gloss/LN/Domain values.
- **Governed acquisition:** disk checked (36 GB free ≫ 2 GB); canonical-byte
  sparse checkout of 29 files at the pinned commit via the existing
  `acquire-source`/`verify-acquisition` CLI; three anchor hashes externally
  verified against the pinned commit's raw bytes; Git-ignored receipt for all
  files; download date recorded.
- **Normalization:** greek block activated in `config/normalization.yaml`
  (schema v4) with explicit typed transformations — lossless punctuation
  separation (validated per token by reconstruction), elision marks kept in
  the word core, no elision restoration, no crasis decomposition, case-folded
  accent- and breathing-insensitive folded form, diaeresis retained, enclitic
  accents preserved in surface with the edition's accent-regularized
  `NormalizedForm` preserved in a separate column. Documented in
  `docs/normalization.md`; `preserve_source_form` remains true.
- **Adapter:** `src/echoes/ingest/macula_greek.py` emits `GNT_` token IDs
  through the same source-edition-only identity module (new additive
  `corpus_prefix` parameter; Hebrew identity semantics untouched — the
  identity digest proves it). AST import-whitelist and crosswalk-invariance
  tests extended to Greek ID generation. Source fields mapped to the
  canonical schema; unmapped fields preserved in canonical JSON extras;
  native identifiers and provenance retained one-to-one.
- **Unified tables:** Greek Parquet/DuckDB tables load transactionally beside
  Hebrew; the `unified_tokens` view exposes the shared canonical columns with
  distinct corpus and provenance values. Storage and integration tests cover
  cross-corpus queries, duplicate prevention, transactional reruns, and
  loader-order independence.
- **Gate evidence:** 137,779 source records → 137,779 tokens across 27 books,
  260 chapters, 7,943 verses; zero validation errors and warnings; run ID
  `greek-c35c0121a2fea8b057cd`. Token count equals the upstream published
  expectation asserted by the pinned repository's own test suite
  (`test/test_nestle1904_nodes.py`, cited in the report). 17/17 scripted spot
  checks passed with expected values recorded (Synoptic samples, John,
  Romans, James, Revelation, enclitic/punctuation/elision cases, pericope
  adulterae, endings of Mark, ACT 8:37 omission). Unified totals: 613,690
  rows = 475,911 Hebrew + 137,779 Greek, no token-ID collisions.
  `ECHOES_RUN_FULL_CORPUS=1` regression runs all four gates green.
- Milestone 3 ingestion report committed at
  `outputs/reports/milestone-3-greek-ingestion-report.md` with the
  canonical-byte inventory, coverage and annotation percentages,
  limitations, and flagged items. CHANGELOG updated.

## Task 4 — Milestone 4 preparation (docs/schema/tests only): COMPLETED

- Versification-crosswalk schema and validator
  (`src/echoes/align/versification.py`) with alignment method and confidence
  fields, cardinality-constrained mapping types (one-to-one, one-to-many,
  many-to-one, unmatched, addition, alternate structure), and **no data
  rows**; synthetic-fixture tests prove invalid crosswalks fail and that the
  module never imports token-identity or ingest code.
- `docs/versification-crosswalk.md` covers the section 10.5 hazards,
  grounded in the edition facts already observed (Nestle 1904 omitted
  verses, MRK 16:99).
- `docs/milestone-4-execution-plan.md` enumerates seven STEPBible
  subset-audit questions requiring human licensing judgment; none resolved.
- No acquisition and no ingestion were performed for this task.

## Superseded artifacts

- The Milestone 2 text-mode (CRLF) SHA-256 inventory: retained, marked
  superseded, as an appendix inside the regenerated Milestone 2 ingestion
  report. Its values must never be used for verification.
- The provisional "SBLGNT v1.2" MACULA Greek edition selection: superseded by
  ADR 0010 (Nestle1904 dataset); recorded in the manifest, ADR, and
  limitations.
- Hebrew ingestion run IDs derived from text-mode raw hashes (for example
  `hebrew-7db8035c6ae1c3268074`): obsolete; the canonical-byte run ID is
  `hebrew-9e089f330652392a0dff`. Token identity itself is unchanged.

## Flagged items for human review

1. **Pericope adulterae:** the pinned Nestle 1904 representation includes
   JHN 7:53–8:11 inline (190 tokens) without a variant marker. Whether
   analyses should treat the passage separately is an interpretation
   question, not decided by ingestion.
2. **Endings of Mark:** the longer ending is inline at MRK 16:9–20 and the
   shorter ending is encoded at out-of-sequence verse MRK 16:99 (33 tokens).
   Analytical treatment is flagged, not decided.
3. **MARBLE-derived Greek fields (LN, LexDomain):** included upstream by
   permission; whether they may appear in redistributable derived outputs
   requires a field-level human licensing review (manifest unresolved
   question).
4. **ADR 0009 (OSHB Ketiv/Qere supplementation) is Proposed** and needs human
   acceptance before Milestone 4 implements it; OSHB coverage of the ~1,500
   K/Q loci and the alignment-confidence policy are open questions.
5. **STEPBible subset audit:** seven licensing questions enumerated in
   `docs/milestone-4-execution-plan.md` require human judgment before any
   STEPBible acquisition.
6. **K/Q data-quality rule:** candidates whose evidence tokens intersect
   known Ketiv/Qere loci must set `data_quality_status`; implementation is
   Milestone 7 scope and does not exist yet.

## Commits on this branch

1. `273cfbd` Remediate Milestone 2 checksums to canonical bytes
2. `0535b08` Add OSHB Ketiv/Qere governance (manifest and docs only)
3. `9f73062` Implement Milestone 3 MACULA Greek ingestion
4. `c2efee4` Prepare Milestone 4 versification-crosswalk schema and plan
5. (this commit) Overnight run summary
