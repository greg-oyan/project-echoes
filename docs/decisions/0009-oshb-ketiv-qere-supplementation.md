# 0009 - Supply Ketiv readings from OSHB keyed to MACULA word-number gaps

- Status: Proposed
- Date: 2026-07-11
- executing_agent: Claude

## Context

The validated MACULA Hebrew snapshot (release `25.08.11`, commit
`7ab368fcb14e4ad2e0f784138241a098fb516ec4`) presents its preferred Qere reading
and does not carry a complete parallel Ketiv layer. The corpus is therefore
qere-only in practice: zero Ketiv/Qere-marked rows exist in the full build even
though the underlying Leningrad tradition contains roughly 1,500 Ketiv/Qere
loci. The canonical schema v2 already preserves paired readings when a source
supplies them (`variant_type`, `variant_group_id`, `is_default_reading`, and
the configuration-selected derived analysis stream), and the master plan
requires that both readings be retained as separate stable records when
available.

Local verification confirms that MACULA preserves the source word numbering of
skipped Ketiv slots rather than renumbering around them. At 2 Kings 8:10 the
verse's source word identifiers run `!1`–`!14` with slot `!6` absent and the
verse resuming at the qere-only word `!7`; no record in the verse carries a
variant marking. These preserved gaps are exactly the coordinates a paired
Ketiv layer can key into without renumbering or re-identifying any existing
token.

The Open Scriptures Hebrew Bible (morphhb) publishes the WLC with lemma and
morphology markup, including Ketiv/Qere data, under CC BY 4.0 for the
annotations with the WLC text itself in the public domain. The pinned commit
is `3d15126fb1ef74867fc1434be1942e837932691f` (the repository's default
`master` branch head observed on 2026-07-11); see the `oshb-morphhb` manifest
entry.

## Decision (proposed)

Adopt OSHB morphhb as a supplementary Ketiv/Qere layer for Milestone 4, under
these rules:

1. **Keying.** OSHB ketiv records are keyed into the word-number gaps that
   MACULA preserves in `source_word_id` (for example, 2KI 8:10 slot `!6`).
   The MACULA source edition's own coordinates remain the identity anchor;
   the OSHB layer never renumbers, rewrites, or re-identifies a MACULA token.
2. **Token production.** Each supplied Ketiv reading becomes a
   `variant_type=ketiv` token per canonical schema v2, with its own stable
   token ID (source-record disambiguation enabled), its own source and
   normalized forms, OSHB provenance (source ID, pinned commit, file, native
   OSHB immutable word `id`), a shared `variant_group_id` linking it to the
   corresponding Qere token, and `is_default_reading=false` while the
   configured analysis reading remains `qere`.
3. **Qere stream unchanged.** The existing Qere token records, their IDs,
   forms, positions, and the configured derived analysis stream are not
   modified. Adding, correcting, or removing the OSHB layer must leave every
   existing MACULA-derived token identity byte-identical.
4. **Alignment confidence.** Every OSHB-to-MACULA keying carries an explicit
   alignment method and an alignment-confidence field. Straightforward cases
   (a single OSHB ketiv aligned to a single preserved MACULA gap inside the
   same verse) may record high confidence; segmentation disagreements,
   multi-word readings, or verse-numbering divergences must record lower
   confidence and remain queryable as unresolved rather than being forced.
5. **Conflict preservation.** Where OSHB and MACULA disagree (word division,
   lemma, morphology, or the reading itself), both values are preserved with
   their sources per master plan section 10.4. No silent reconciliation.
6. **Adapter path.** The existing MACULA Hebrew adapter already detects
   Ketiv/Qere via the source `type` attribute and emits paired records when a
   source supplies both readings. The OSHB layer either (a) maps its records
   into that same detection path by presenting `type`-equivalent variant
   marking, or (b) lands through a dedicated supplement adapter that emits
   canonical-schema tokens directly. The choice is an implementation decision
   for Milestone 4; either path must satisfy rules 1–5 and the existing
   variant-group validation.

## Rationale

Keying into preserved word-number gaps uses coordinates that already exist in
the primary source edition, so supplementation cannot disturb primary token
identity — the same guarantee the versification-crosswalk rules give: a
supplementary layer is an external mapping, never an identity rewrite. The
canonical schema v2 variant semantics were designed for exactly this pairing,
and the derived analysis stream already switches between readings
deterministically in fixture tests.

## Consequences

- Until the layer lands, the corpus remains qere-only with Ketiv readings
  silently absent; `docs/limitations.md` records the interim data-quality
  obligation for candidates whose evidence intersects known K/Q loci.
- Milestone 4 must add an OSHB acquisition specification (canonical-byte
  hashes, pinned commit) before any download; this decision authorizes no
  acquisition.
- The preserved-row count will grow when Ketiv records land; token counts for
  the MACULA-only base table must remain unchanged and separately reportable.
- Alignment-confidence and conflict records add columns or tables that the
  Milestone 4 schema work must define before ingestion.

## Alternatives considered

- **Reconstruct Ketiv readings from the MACULA text or secondary lists**:
  rejected; the project does not fabricate source records, and reconstruction
  would have no upstream provenance.
- **Upgrade to a newer MACULA release hoping for Ketiv coverage**: rejected;
  2026 releases carry additional SILHA licensing terms and would silently
  replace the pinned edition, and no evidence shows they add a complete
  parallel Ketiv layer.
- **Renumber MACULA tokens to close the gaps and interleave OSHB records**:
  rejected outright; it would mutate primary token identity, violating the
  source-edition-only identity rule.
- **Treat OSHB as a replacement primary source**: rejected; MACULA remains the
  primary annotated edition, and OSHB is a supplementary annotation layer with
  its own segmentation that must not overwrite primary values.
