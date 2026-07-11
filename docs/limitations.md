# Limitations and unresolved issues

## Current Milestone 2 state

- MACULA Hebrew release `25.08.11`, commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`, is the only acquired and validated corpus source. MACULA Greek, supplementary annotations, bridge corpora, benchmarks, textual witnesses, apparatuses, and reception sources remain inactive.
- The selected MACULA `WLC/nodes` representation has no formal XSD. The adapter validates the observed pinned structure and rejects malformed required fields, but upstream structural change requires an explicit adapter and schema review.
- MACULA normally presents its preferred Qere reading and this snapshot has no complete parallel Ketiv representation. Zero Ketiv/Qere-marked output rows therefore cannot support exhaustive variant analysis and must not be interpreted as absence of variants.
- Release 25.08.11 predates later upstream NFC and combining-grapheme-joiner fixes. Project Echoes preserves the original source values and applies its documented NFD/CGJ rules only to derived forms; a future source upgrade may legitimately change forms and hashes.
- Later 2026 MACULA Hebrew releases incorporate SILHA material under additional terms. They are outside this determination and must not silently replace the pinned pre-SILHA release.
- Some source records omit `xml:id`, contain explicit zero-width morphemes, or occur alongside alternate source trees. The pipeline records deterministic fallbacks and informational findings rather than hiding them; downstream methods must respect those distinctions.
- Stable project IDs depend on canonical reference and source segmentation. They are deterministic for this governed snapshot, but a reviewed source version or segmentation change can produce intentionally different identities and must be handled as a corpus migration.
- Validation proves structural consistency, configured completeness, deterministic transformations, and storage agreement; it does not prove that every upstream lemma, morphology, syntax, semantic label, participant annotation, gloss, or canonical reference is philologically correct.
- The twelve manual spot checks sample genre, language, and structural edge cases but are not an exhaustive scholarly audit of 475,911 records.
- Raw MACULA data, acquisition receipts, complete processed Parquet tables, and the DuckDB database are local and Git-ignored. Another run depends on the pinned upstream commit remaining retrievable or on an independently authorized archive.
- Local machine processing is approved, but public release of full processed token tables is not. A field-level compatibility, attribution, modification, and reconstructability review is still required, especially for SDBH-derived attributes included in the MACULA aggregate by permission.
- The provisional SBLGNT v1.2 MACULA Greek selection still requires branch, edition, component-license, and annotation-completeness verification before Milestone 3 acquisition.
- CATSS requires exact module, agreement, downstream-control, version, encoding, and versification review and remains blocked by later primary-corpus gates.
- OpenBible archive contents and reproducible snapshot mechanics remain uninspected; ETCBC DSS upstream transcription rights remain unresolved; and no machine-processing permission has been established for proprietary Hebrew/Greek apparatuses or a Targum corpus.
- The literature matrix has five verified seed projects, not comprehensive coverage of every field named in the master plan. The closest-project conclusion remains provisional.
- Repository software and original documentation licensing remains pending owner selection.
- No downstream segmentation, embedding, semantic analysis, knownness search, candidate generation, evaluation, review console, or substantive research experiment has begun. Corpus similarity or annotation proximity must not be inferred from this infrastructure milestone.

These limitations are acceptance boundaries. They must not be rewritten as evidence that a source, method, or scholarly relationship is absent.
