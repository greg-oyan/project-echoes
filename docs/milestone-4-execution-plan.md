# Milestone 4 execution plan

Status: **Complete — governance closure recorded 2026-07-12**

Milestone 4 is complete on the basis of the OSHB Ketiv/Qere supplement and the
generic supplementary-alignment infrastructure described below. STEPBible was
not acquired or activated. Its optional future activation is deferred under
ADR 0012 and is not a Milestone 4 acceptance dependency.

## Completed OSHB work

- The pinned OSHB source is acquired reproducibly with file-level provenance,
  licensing metadata, expected-file validation, and checksums.
- Ketiv readings are preserved as 1,268 supplementary token records spanning
  1,251 Ketiv-bearing loci; primary MACULA Qere tokens are not overwritten.
- OSHB/OSIS source book identifiers and canonical MACULA book codes remain
  separate. Token identity derives from the normalized OSHB source identifier,
  not from the canonical mapping or a versification crosswalk.
- Qere and Ketiv analysis streams are deterministic, and primary Hebrew and
  Greek identity, surface/lemma, and analytical digests remain invariant.
- Structural mappings record Ketiv token, primary anchor tokens, sentence,
  clause, and phrase proposals, method, confidence, resolution status, and
  notes. Unresolved values remain null and are reported rather than fabricated.

## Completed generic alignment infrastructure

- Supplementary annotation-alignment tables store source values beside primary
  annotations with source/version provenance, alignment method, confidence,
  conflict status, and resolution status.
- Conflict-preservation validation prevents supplementary values from silently
  replacing primary annotations and keeps disagreements queryable.
- The separate versification-crosswalk layer preserves edition-native
  references and cannot participate in token-ID generation.
- Explicit coverage and unresolved-alignment reports make structural
  uncertainty inspectable for downstream analysis.

## Deferred STEPBible work

STEPBible remains an eligible but inactive supplementary source. ADR 0012
records the owner-approved deferral. The deferral is not a rejection, a license
approval, or a licensing determination. No STEPBible file has been approved,
acquired, ingested, or validated, and the seven file-level questions below
remain unresolved.

## Future activation criteria

A later milestone may activate STEPBible only when it records all of the
following before acquisition:

1. A specific missing field or downstream capability.
2. The exact STEPBible files required.
3. A measurable analytical benefit.
4. Completed file-level licensing and provenance review.
5. A conflict-preserving integration design using the completed generic
   supplementary-alignment infrastructure.

## Unresolved STEPBible subset-audit questions

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

## Closure boundary

- No STEPBible acquisition or ingestion is authorized by this closure.
- None of the seven STEPBible questions is answered by deferral.
- Milestone 5 passage generation, benchmark work, lexical scoring, embeddings,
  and discovery analysis have not begun.
- The Milestone 5 structural-uncertainty handoff is documentation and
  acceptance-criteria work only; it does not generate passage records.
