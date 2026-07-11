# Versification crosswalk design note

Status: **Milestone 4 preparation — schema and validator only, no data rows**
Date: 2026-07-11

Implementation: `src/echoes/align/versification.py`
Tests: `tests/unit/test_versification_crosswalk.py`

## Role and boundary

The versification crosswalk is a separate mapping layer (master plan section
10.5). It maps edition-specific references between named reference schemes for
comparison. It must never:

- participate in source-edition token-ID generation;
- rewrite a source edition's own verse identifiers;
- change any token identity when crosswalk rows are added, removed, or
  corrected.

Those invariants are enforced structurally (the identity module imports no
crosswalk code, and the crosswalk module imports no identity or ingest code)
and by tests that add, change, and remove crosswalk data while asserting token
IDs are byte-identical.

## Schema

A crosswalk document declares `schema_version`, a `source_scheme` and
`target_scheme` (which must differ), document `provenance`, and rows. Every
row carries:

- `crosswalk_id` — stable row identity (`vx-…`);
- `source_references` / `target_references` — edition-specific reference
  lists validated against the `BOOK C:V[subverse]` pattern;
- `mapping_type` — one of `one_to_one`, `one_to_many`, `many_to_one`,
  `unmatched_source`, `addition_in_target`, `alternate_structure`, with
  cardinality constraints enforced per type;
- `alignment_method` — `published_crosswalk_table`, `rule_based`,
  `statistical`, or `manual`; required on every row;
- `alignment_confidence` — required, in [0, 1];
- optional free-text `notes`.

No data rows ship with this preparation: an empty `rows` list validates, and
synthetic-fixture tests prove that malformed references, invalid confidence
values, unknown methods, cardinality violations, duplicate row IDs, and
identical schemes all fail.

## Known hazards (from master plan section 10.5)

The schema exists because the following must never be assumed:

1. **Editions do not number all passages identically.** Both validated primary
   corpora already prove this: the Nestle 1904 edition omits fifteen
   later-numbered verses (for example ACT 8:37) and encodes the shorter
   ending of Mark at the out-of-sequence verse MRK 16:99.
2. **Septuagint book and chapter divisions do not match the Masoretic Text.**
   Jeremiah's chapter order diverges substantially; Psalm and chapter
   boundaries shift; some books have alternate structures. The
   `alternate_structure`, `one_to_many`, and `many_to_one` types exist for
   these cases, and forced one-to-one equivalence is a modeling error.
3. **Book abbreviations differ between sources.** Reference strings are
   scheme-qualified: a row maps references *between named schemes*, and a bare
   reference string is never treated as a universal identifier.
4. **Psalm numbering is not consistent.** Masoretic and Septuagint Psalm
   numbers diverge by one across most of the Psalter, superscriptions are
   verse 1 in some schemes and unnumbered in others, and Psalm 151 exists only
   in some traditions (`addition_in_target`).
5. **Hebrew verse 0/superscription and split-verse conventions differ**, which
   is why references admit an optional subverse letter and why `one_to_many`
   and `many_to_one` are first-class.
6. **Absence is meaningful.** `unmatched_source` and `addition_in_target`
   record material without a counterpart instead of dropping it or inventing
   an equivalence.

Every cross-corpus alignment records its method and confidence so downstream
consumers can distinguish a published scholarly table from a statistical
guess.

## What Milestone 4 execution still owes

- CLI wiring (`validate-crosswalk` or equivalent) and storage layout under
  `data/alignments/`.
- Actual crosswalk data with per-row provenance, after the STEPBible
  subset-audit licensing questions are resolved by a human (see the
  [Milestone 4 execution plan](milestone-4-execution-plan.md)).
- Integration validation that crosswalk activation leaves both corpora's
  token identities and the corpus identity digest unchanged.
