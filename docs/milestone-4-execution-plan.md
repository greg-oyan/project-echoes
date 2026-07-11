# Milestone 4 execution plan

Status: **Preparation only — nothing in this plan is authorized to run yet**
Date: 2026-07-11

Milestone 4 (supplementary annotations) builds the STEPBible adapter,
annotation-alignment tables, conflict-preservation logic, and the separate
versification-crosswalk mapping layer. This plan enumerates the ordered work
and, critically, the licensing questions that require human judgment before
any STEPBible acquisition. It resolves none of them.

## Ordered work

1. Resolve the STEPBible subset-audit questions below (human licensing
   judgment) and record the outcome in an ADR and the source manifest.
2. Pin an exact STEPBible-Data commit; design the governed acquisition
   (canonical-byte pattern, expected files, anchor hashes) for only the
   approved files.
3. Implement the OSHB Ketiv/Qere supplement per ADR 0009 (Proposed): keying
   into MACULA word-number gaps, `variant_type=ketiv` tokens, alignment
   confidence, conflicts preserved. ADR 0009 must be accepted first, and OSHB
   needs its own acquisition specification.
4. Build annotation-alignment tables that store supplementary values beside,
   never over, primary annotations, with source ID, source version, field
   name, original value, alignment method, and confidence.
5. Wire the versification-crosswalk validator (schema already implemented) to
   CLI and storage, then populate crosswalk rows with per-row provenance.
6. Extend validation: supplementary data never overwrites primary annotations;
   annotation conflicts are queryable; crosswalk rows preserve
   edition-specific references; the corpus identity digest and all token IDs
   are byte-identical before and after activation.

## STEPBible subset-audit questions requiring human licensing judgment

The STEPBible-Data repository states CC BY 4.0 at repository level, but the
project's activation rule requires file-level provenance review. A human must
decide each of the following; none is resolvable by automation:

1. **Which exact files are in scope?** The repository mixes tagged texts,
   lexicons, name databases, and versification resources with different
   upstream derivations. Which specific files measurably improve the core
   pipeline (glosses, lexical mappings, semantic domains, names,
   versification), and is each individually cleared?
2. **Do any selected files derive from commercial or restricted editions?**
   Some STEPBible resources encode data derived from modern editions or
   lexicons whose upstream terms may constrain fields even under a CC BY
   repository notice. Which fields inherit upstream restrictions, and what may
   a derivative expose?
3. **Which versification tables may seed the crosswalk?** STEPBible's
   versification data (for example the TVTMS-derived tables) has its own
   provenance chain. Is the chain's licensing compatible with a project
   crosswalk whose rows would be redistributable, and what attribution does
   each table require?
4. **How should AI-authored or partially generated descriptions be treated?**
   The repository documents that some resources contain AI-authored
   descriptions. The project already excludes them from primary linguistic
   evidence; the human question is whether they may be stored at all, and
   under what labeling.
5. **What attribution text satisfies both STEPBible and any named upstream
   contributors** for the specific files selected, and where must it appear
   in derived outputs?
6. **Redistribution boundary:** which supplementary-derived columns, if any,
   may appear in published derived tables, given that the primary corpus
   tables themselves remain unpublished pending their own field-level review?
7. **Snapshot policy:** the repository updates continuously without formal
   releases for every change. Which commit is pinned, and does any selected
   file's changelog indicate recent upstream corrections that argue for a
   different pin?

## Explicitly out of scope for this document

- Any acquisition or ingestion of STEPBible or OSHB data.
- Any crosswalk data rows.
- Any resolution of the questions above; they are recorded for a human
  decision-maker.
