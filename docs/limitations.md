# Limitations and unresolved issues

## Current Milestone 3 state

- MACULA Hebrew release `25.08.11` (commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`) and MACULA Greek release `24.06.17` (commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`) are the acquired and validated primary corpus sources. Supplementary annotations, bridge corpora, benchmarks, textual witnesses, apparatuses, and reception sources remain inactive.
- The Greek corpus represents the Nestle 1904 edition. Its edition-level
  versification is preserved exactly: fifteen omitted verse numbers are not
  fabricated, the pericope adulterae is inline, and the alternate ending of
  Mark is encoded at `MRK 16:99` after `MRK 16:20` in source order. The owner
  has approved two future analysis profiles: `edition_complete` retains all
  inline edition text, while `critical_core` excludes `MRK 16:9-20`,
  `MRK 16:99`, and `JHN 7:53-8:11`. Source order does not make alternate
  endings analytically adjacent: Milestone 5 must break every two- and
  five-verse window between `MRK 16:20` and `MRK 16:99`. Extant verses across
  an edition omission may remain source-order adjacent only with an explicit
  `reference_gap` flag. These rules are declarative until Milestone 5; no
  passage generator is implemented here.
- Any future candidate intersecting one of those three disputed passages must
  carry a textually disputed data-quality flag. It cannot retain an
  unqualified `strong candidate` label unless it survives the corresponding
  `critical_core` exclusion analysis or receives explicit, completed
  textual-critical review. The policy prevents unqualified claims; it does
  not itself resolve the underlying textual-critical questions.
- MARBLE-derived Greek word-sense fields (LN, LexDomain) are included upstream by permission; whether they may appear in redistributable derived outputs requires a separate field-level review.
- The selected MACULA `WLC/nodes` representation has no formal XSD. The adapter validates the observed pinned structure and rejects malformed required fields, but upstream structural change requires an explicit adapter and schema review.
- MACULA normally presents its preferred Qere reading and this snapshot has no complete parallel Ketiv representation. Zero Ketiv/Qere-marked output rows therefore cannot support exhaustive variant analysis and must not be interpreted as absence of variants. The base schema and synthetic fixtures preserve both readings when supplied, but the project does not reconstruct missing full-corpus Ketiv records.
- SUPERSEDED (2026-07-11, Milestone 4 Part 1): ~~until the planned OSHB Ketiv/Qere supplementary layer lands, the corpus is qere-only with Ketiv readings silently absent~~. The OSHB K/Q supplement (ADR 0009) is now ingested: 1,260 loci (1,245 paired, 6 ketiv-only, 9 qere-only) supply 1,268 ketiv token records beside the untouched primary tables, with zero surface conflicts against MACULA in the pinned sources. Post-supplement caveats: (a) per-locus alignment confidence is 1.0 only for single-word exact-match pairings; multi-word loci carry 0.9 and any future disagreement drops to 0.7/0.3 with a preserved conflict row; (b) the ketiv layer derives from OSHB, a different (though same-edition WLC 4.20) source than the primary corpus, so ketiv lemma/morphology live in an explicitly OSHB-namespaced field, not the MACULA lemma column; (c) the qere analysis stream is byte-identical to its pre-supplement state, and the six ketiv-wela-qere readings join only the ketiv stream; (d) inherited analytical structure is stored in a separate alignment table, never written into OSHB source-native syntax fields; sentence membership resolves for all 1,251 Ketiv-bearing loci, while clause and phrase boundary disagreements remain explicit partial mappings; (e) candidates whose evidence tokens intersect a locus in the K/Q registry must still set `data_quality_status` — implementing that check remains Milestone 7 scope, and K/Q loci still count as textual-variant exposure under review rubric question 14.
- Release 25.08.11 predates later upstream NFC and combining-grapheme-joiner fixes. Project Echoes preserves the original source values and applies its documented NFD/CGJ rules only to derived forms; a future source upgrade may legitimately change forms and hashes.
- Later 2026 MACULA Hebrew releases incorporate SILHA material under additional terms. They are outside this determination and must not silently replace the pinned pre-SILHA release.
- Some source records omit `xml:id`, contain explicit zero-width morphemes, or occur alongside alternate source trees. The pipeline records deterministic fallbacks and informational findings rather than hiding them; downstream methods must respect those distinctions.
- Stable project IDs depend only on the source edition's book/chapter/verse/token/subtoken coordinates and native record identity where variants require it. They do not depend on a later versification crosswalk. A reviewed source version or source segmentation change can still produce intentionally different identities and must be handled as a corpus migration.
- Validation proves structural consistency, configured completeness, deterministic transformations, and storage agreement; it does not prove that every upstream lemma, morphology, syntax, semantic label, participant annotation, gloss, or canonical reference is philologically correct.
- The twelve manual spot checks sample genre, language, and structural edge cases but are not an exhaustive scholarly audit of 475,911 records.
- Raw MACULA data, acquisition receipts, complete processed Parquet tables, and the DuckDB database are local and Git-ignored. Another run depends on the pinned upstream commit remaining retrievable or on an independently authorized archive.
- Local machine processing is approved, but public release of full processed token tables is not. A field-level compatibility, attribution, modification, and reconstructability review is still required, especially for SDBH-derived attributes included in the MACULA aggregate by permission.
- The provisional SBLGNT v1.2 MACULA Greek intent was superseded by ADR 0010: the release's SBLGNT representation documents incomplete annotation coverage at unmapped nodes, so the Nestle1904 dataset was selected. A future SBLGNT-based corpus would be a new source version requiring its own review.
- No Septuagint edition has been selected. Printed-edition copyright, electronic-transcription license, morphology/annotation license, Hebrew–Greek alignment license, raw and derived redistribution, and attribution must be decided component by component before acquisition. CATSS modules cannot be assigned one assumed blanket license.
- Septuagint v1 alignment is limited to verse- or passage-level mappings through the separate Milestone 4 versification crosswalk plus statistical lemma-level mappings with explicit confidence. It must represent one-to-one, one-to-many, many-to-one, unmatched, addition, and alternate-structure cases with edition-specific references, method, and confidence. Token-level Hebrew–Septuagint alignment is explicitly out of scope for v1.
- The OpenBible license is verified as CC BY 4.0 for the approximately 340,000-link graph, excluding separately copyrighted ESV quotations, but archive fields and reproducible snapshot mechanics remain uninspected. It is Tier 3 weak supervision and broad knownness filtering, not scholarly ground truth or a sole positive benchmark.
- The Tier 1 quotation CSV is intentionally header-only. No human-curated benchmark rows exist yet, so it cannot be used for evaluation until the Milestone 6 provenance, rights, independent-review, and leakage gates pass.
- Null-model simulation and the conjunctive rare-evidence rule are configuration and documentation placeholders only. They must be implemented, tested, and calibrated before Milestone 8 review; a hypergeometric value alone is not a calibrated dependence probability.
- ETCBC DSS upstream transcription rights remain unresolved, and no machine-processing permission has been established for proprietary Hebrew/Greek apparatuses or a Targum corpus.
- The literature matrix has five verified seed projects, not comprehensive coverage of every field named in the master plan. The closest-project conclusion remains provisional.
- Repository software and original documentation licensing remains pending owner selection.
- No downstream segmentation, embedding, semantic analysis, knownness search, candidate generation, evaluation, review console, or substantive research experiment has begun. Corpus similarity or annotation proximity must not be inferred from this infrastructure milestone.

These limitations are acceptance boundaries. They must not be rewritten as evidence that a source, method, or scholarly relationship is absent.
