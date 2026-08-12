# Limitations and unresolved issues

## State after canonical Milestone 7 closure

- Milestone 7 is technically complete and canonically sealed with 1,248,779
  candidates, a zero-row strict review queue, zero strict-validation errors or
  warnings, complete critical-core and Qere/Ketiv sensitivities, and a verified
  18,606-file Backblaze B2 archive. The applicable sufficiently powered Tier 3
  strata passed the registered recovery comparison, but `gnt_gnt` was
  insufficient for a recovery claim and no applicable frozen RRF threshold
  satisfied the maximum empirical-FDR policy under both required null
  families. The original scientific acceptance gate therefore remains unmet.
  This is a valid negative/incomplete result, not permission to retune M7 and
  not evidence that no underdocumented relationships exist.
- The canonical artifact has composite production provenance. Frozen
  scientific configuration and logical content were preserved across
  authenticated checkpoints and recovery, but final repair, portable index
  regeneration, validator-contract reconciliation, promotion receipts, and B2
  verification cannot be simplistically attributed to one pristine launch
  commit. Retained scripts are provenance records; supported source and tests
  own the permanent contracts.
- ADR 0018 authorizes the separate `final-discovery-v1` experiment. It reuses
  M7 as one lexical family, requires independent later families, and separates
  statistically eligible Tier A from exploratory Tier B. Tier B rank never
  confers statistical acceptance or novelty.

### `final-discovery-v1` preproduction limitations

- No production campaign has run. There are no final candidate counts, Tier A
  or Tier B identities, expected-noise estimates, review decisions, dossiers,
  or discovery claims. Local fixture and validation runs demonstrate software
  contracts only and must not be described as corpus results. No paid compute
  or production cloud resource was launched during this implementation.
- The registered primary scope is verse-only across the 66-book corpus.
  Critical-core Greek and Ketiv are sensitivity profiles. Existing clause,
  sentence, two-verse, and five-verse interfaces or smoke tests do not support
  final-discovery performance claims at those granularities, and verse
  boundaries can hide or divide relationships that operate at another scale.
- Calibration and multiple-testing claims are conditional on the complete
  retained candidate universe produced by the frozen top-k union of sparse,
  embedding, structural, and bounded M7 retrieval. They do not cover every
  mathematically possible passage pair. A pair not retrieved into that union
  receives no final-ensemble test, so absence from the ledger is not evidence
  of absence from the corpus.
- The pinned `multilingual-e5-small` model transfers from modern multilingual
  web pretraining; independent validity for Biblical Hebrew, Biblical Aramaic,
  and Ancient Greek is unestablished. Its tokenizer, truncation, and semantic
  geometry may erase morphology or import modern-language assumptions.
  Possible pretraining exposure to biblical text, translations, commentary,
  and benchmark relationships is unquantified.
- Literal-English-gloss features add translation and annotation choices to
  cross-language retrieval. They cannot count as original-language support
  and must be removed by the registered English ablation. That ablation tests
  explicit campaign features only: it cannot remove latent English or biblical
  exposure from pretrained model weights and cannot validate ancient-language
  transfer by itself.
- The UBS positive-control adaptation has only 24 reference pairs in eight
  leakage groups. Its 15/3/6 split is descriptive; all six test rows are one
  correlated `PCL_LAST_SUPPER` leakage group. References were checked against
  the pinned source, but no independent scholar adjudicated original-language
  wording, relationship class, strength, or direction. Its recovery cannot be
  generalized as an independent ancient-language benchmark result.

- MACULA Hebrew release `25.08.11` (commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`) and MACULA Greek release `24.06.17` (commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`) are the acquired and validated primary corpus sources. OSHB morphhb at commit `3d15126fb1ef74867fc1434be1942e837932691f` is the active Ketiv/Qere supplementary source. The exact OpenBible.info reference archive is acquired and validated for Tier 3 benchmark processing only. STEPBible, bridge corpora, textual witnesses, apparatuses, and reception sources remain inactive.
- Milestone 5 passage generation is complete on run ID `passages-v1-00e261abea9ed44ef087`. Two full generations each produced 914,497 passages, 21,530,271 membership rows, 913,445 adjacency rows, 148,948 explicit exclusions, zero issues, and one metadata row. Both strict validations passed with zero findings, and all deterministic logical and physical content hashes agreed.
- Milestone 6 code, governance, source lifecycle, two-build local validation, repository audit, and CI acceptance are complete. Both builds reproduced run `benchmark-v1-dff1d3ef650c8ccd4930`, version `known-links-v1-dff1d3ef650c`, all logical hashes, counts, and content-table physical hashes; each strict validation returned zero errors and zero warnings. PR #7 was merged as `b9637ee2de1840cbc2056dfcec6aea163d1e9194`; Milestone 7 began from that verified merge.
- ADR 0012 defers STEPBible activation; it does not reject STEPBible or make a licensing determination. No downstream capability currently demonstrates a need for a particular STEPBible file. The source remains eligible only after a later milestone names the missing field or capability, exact files, measurable benefit, completed file-level provenance and licensing review, and a conflict-preserving integration design. The previously registered STEPBible licensing questions therefore remain unanswered, including the rights and attribution consequences for each exact file, field, transformation, raw artifact, and derived output that might eventually be selected.
- Milestone 5 preserves Ketiv structural uncertainty rather than filling gaps. The Qere stream retains primary MACULA structure; all Ketiv tokens remain visible in verse and sentence analysis; 255 clause-unresolved Ketiv tokens per profile have explicit clause exclusions; and intersecting passages retain clause/phrase uncertainty flags. These records describe alignment limits, not source-native Ketiv syntax. Phrase is not a Milestone 5 passage granularity, so phrase uncertainty is metadata for later feature and sensitivity work rather than a generated phrase-passage table.
- The Greek corpus represents the Nestle 1904 edition. Its edition-level
  versification is preserved exactly: fifteen omitted verse numbers are not
  fabricated, the pericope adulterae is inline, and the alternate ending of
  Mark is encoded at `MRK 16:99` after `MRK 16:20` in source order. The owner
  has approved two future analysis profiles: `edition_complete` retains all
  inline edition text, while `critical_core` excludes `MRK 16:9-20`,
  `MRK 16:99`, and `JHN 7:53-8:11`. Source order does not make alternate
  endings analytically adjacent: every two- and five-verse window breaks
  between `MRK 16:20` and `MRK 16:99`. Extant verses across an edition
  omission remain source-order adjacent only with an explicit `reference_gap`
  flag. The accepted artifacts enforce these rules; they do not resolve the
  underlying textual-critical questions.
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
- Full passage Parquet contains reconstructable source text and remains local and Git-ignored. The Milestone 5 acceptance statistics, IDs, and hashes do not authorize redistribution of the complete passage artifacts.
- Runtime and environment are nondeterministic provenance telemetry. The two accepted runs therefore have different metadata-Parquet physical hashes, while the metadata logical hash and every content-table logical and physical hash agree. This registered exception must not be generalized to content tables.
- Milestone 7 additionally retains measured null-replicate runtimes as provenance while excluding them from logical identity. Telemetry-bearing null or metadata Parquet physical hashes may differ between complete runs; exact equality of every governed logical output remains mandatory, and every physical difference must be disclosed.
- The Milestone 6 builds have the same registered telemetry exception: metadata Parquet physical bytes differ with persisted runtimes of 501.93041979987174 and 479.37766140000895 seconds, while metadata logical content and every content-table logical and physical hash agree. Wall-clock runtime and the common 672,790,515-byte footprint describe this machine and implementation, not a portable performance guarantee.
- The 30 reproducible scripted and manually reviewed spot checks sample genre, language, and structural edge cases but are not an exhaustive scholarly audit of 475,911 records.
- Raw MACULA data, acquisition receipts, complete processed Parquet tables, and the DuckDB database are local and Git-ignored. Another run depends on the pinned upstream commit remaining retrievable or on an independently authorized archive.
- Local machine processing is approved, but public release of full processed token tables is not. A field-level compatibility, attribution, modification, and reconstructability review is still required, especially for SDBH-derived attributes included in the MACULA aggregate by permission.
- The provisional SBLGNT v1.2 MACULA Greek intent was superseded by ADR 0010: the release's SBLGNT representation documents incomplete annotation coverage at unmapped nodes, so the Nestle1904 dataset was selected. A future SBLGNT-based corpus would be a new source version requiring its own review.
- No Septuagint edition has been selected. Printed-edition copyright, electronic-transcription license, morphology/annotation license, Hebrew–Greek alignment license, raw and derived redistribution, and attribution must be decided component by component before acquisition. CATSS modules cannot be assigned one assumed blanket license.
- Septuagint v1 alignment is limited to verse- or passage-level mappings through the separate Milestone 4 versification crosswalk plus statistical lemma-level mappings with explicit confidence. It must represent one-to-one, one-to-many, many-to-one, unmatched, addition, and alternate-structure cases with edition-specific references, method, and confidence. Token-level Hebrew–Septuagint alignment is explicitly out of scope for v1.
- OpenBible snapshot `snapshot-2026-07-12-sha256-18e63e370308` is verified as CC BY 4.0 for the audited reference-and-vote graph. The ZIP contains one tab-delimited file with 344,799 reference records and no biblical or ESV quotation text. This does not cure the source's evidentiary limits: its links are heterogeneous, direction is source behavior rather than demonstrated literary dependence, and signed votes are mutable relevance rankings rather than calibrated confidence. OpenBible remains Tier 3 weak supervision and broad knownness filtering, never scholarly ground truth, primary evaluation truth, a sole positive benchmark, or a source of Tier 1 rows.
- OpenBible uses its own English Protestant reference scheme. Without an independently approved scheme crosswalk, same-label mappings to MACULA verse passages are mechanical and provisional, including where a label exists exactly. Missing targets, partial ranges, cross-book ranges, disputed text, reference gaps, and `critical_core` exclusions remain explicit. Mapping coverage therefore cannot be interpreted as verified versification equivalence.
- The Tier 1 quotation CSV is intentionally header-only, with schema-v1 header-only SHA-256 `7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b` and zero human-curated rows. The placeholder validates a future data contract but supplies no benchmark evidence. Primary high-confidence evaluation remains unavailable until lawful row-level provenance, human original-language review, independent review, leakage grouping, and release validation are completed.
- Current split assignments are Tier 3 weak-supervision infrastructure. The broad genre registry is a project analysis stratification, not an authorship or precise literary-genre taxonomy, and OpenBible provides no trustworthy relationship-family labels; the held-out-family contract therefore remains unsupported rather than populated with invented classifications.
- Generated contrastive pairs are presumed negatives only. They are absent from the checked OpenBible graph in both directions under the configured mapping and leakage rules, but that absence does not prove nonrelationship. Milestone 6 intentionally supplies no common-vocabulary, same-theme, formulaic, lexical, semantic, or embedding-based hard negatives.
- Milestone 6 itself has no retrieval-performance result. Milestone 7 implements the first lexical recovery evaluation, but every OpenBible result remains Tier 3 weak-supervision recovery separated by corpus pair, provisional mapping status, split, and descriptive vote stratum. Tier 1 is still empty, so no high-confidence quotation-recovery result exists regardless of Tier 3 performance.
- Milestone 7 implements both registered repeated null families and the conjunctive rare-evidence rule. Their empirical calibration is scoped to the frozen deterministic 20,000-pair candidate-union sample rather than every possible pair. A hypergeometric value remains an independence baseline, not a calibrated probability of textual dependence; an estimated empirical FDR remains conditional on its registered null and candidate sampling design.
- ETCBC DSS upstream transcription rights remain unresolved, and no machine-processing permission has been established for proprietary Hebrew/Greek apparatuses or a Targum corpus.
- The literature matrix has five verified seed projects, not comprehensive coverage of every field named in the master plan. The closest-project conclusion remains provisional.
- Repository software and original documentation licensing remains pending owner selection.
- Milestone 7 is confined to transparent lexical retrieval, Tier 3 recovery evaluation, repeated empirical null calibration, evidence generation, and its zero-row unreviewed queue. It does not evaluate embeddings, semantic analysis, predicate-argument features, later structural/anomaly engines, or human candidate decisions. Its original positive scientific gate was not satisfied even though the canonical technical validation succeeded. Passage proximity, lexical similarity, or reference-graph membership is never proof of a scholarly relationship.
- The production corpora contain no governed root annotation. Root feature and detector interfaces are fixture-tested, but full-run root vocabulary, matrix nonzeros, and candidate evidence must remain zero; fabricating roots would be a data-provenance failure.
- Full null-calibrated v1 results are verse-level only. Clause, sentence, two-verse, and five-verse interfaces and smoke tests do not establish whole-corpus performance at those scales.
- The HB-GNT bridge uses only explicitly English-derived MACULA glosses. Removing all English-derived features removes the bridge representation, so these results cannot satisfy an original-language gate or a future unqualified `strong candidate` label. They remain English-mediated retrieval leads for possible later Septuagint analysis.
- The historical M7/Milestone 8 handoff is a valid zero-row queue. No M7 top
  100 may be manufactured. In `final-discovery-v1`,
  `not_represented_in_openbible_snapshot` still means only absence from that
  exact reference snapshot; it is not `novel` or `undiscovered`. Exploratory
  Tier B is separately generated and must remain visibly distinct from
  statistically eligible Tier A.

These limitations are acceptance boundaries. They must not be rewritten as evidence that a source, method, or scholarly relationship is absent.
