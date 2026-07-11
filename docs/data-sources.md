# Data sources and provenance

Status: **Milestone 1 preliminary source register**
Review date: 2026-07-10

No biblical corpus data has been downloaded or ingested. The authoritative machine-readable preliminary register is [`data/manifests/sources.yaml`](../data/manifests/sources.yaml). A record documents intent and review state; it does not activate a source.

## Layered corpus strategy

Project Echoes treats datasets as governed layers with distinct research functions:

1. **Primary discovery** — MACULA Hebrew and Greek, subject to edition, component, license, acquisition, and corpus validation.
2. **Bridge** — a later Septuagint source for controlled Hebrew–Greek–New Testament triangulation.
3. **Supplementary annotation** — selected STEPBible fields or comparable resources stored alongside, never over, primary annotations.
4. **Benchmark/reference** — known cross-references and curated parallels for held-out recovery, leakage control, and knownness.
5. **Textual validation** — DSS, variants, and apparatuses used only to test wording behind existing candidates.
6. **Reception history** — Targums and later interpretive corpora, excluded from primary discovery.

The detailed boundary is fixed in [corpus-scope.md](corpus-scope.md).

## Preliminary source register

| Source | Purpose | Confirmed at this review | Unresolved before activation |
|---|---|---|---|
| MACULA Hebrew | Primary Hebrew/Aramaic tokens and linguistic annotations | Official repository identifies WLC, OpenScriptures morphology, syntax, semantic, gloss, and participant layers and a CC BY 4.0 aggregate notice | Pin release/commit and files; audit permission-only components; validate Aramaic, Ketiv/Qere, segmentation, and completeness |
| MACULA Greek | Primary Greek NT tokens and linguistic annotations | Official repository identifies syntax, morphology, semantic and participant layers, N1904/SBLGNT representations, and a CC BY 4.0 aggregate notice | Confirm provisional SBLGNT v1.2 representation and branch; audit mappings and permission-only components |
| STEPBible Data | Supplementary glosses, lexical/semantic mappings, names, morphology, versification | Repository states CC BY 4.0, attribution, modifiability, and UTF-8 tabular resources | Select files and fields; audit each upstream derivation; exclude AI-authored descriptions from primary evidence |
| CATSS Septuagint | Later bridge morphology and Hebrew–Greek alignment | Official CATSS materials describe Rahlfs-based Greek morphology, Stuttgart Hebrew parallel data, and a source-specific user agreement | Confirm current acquisition agreement, exact modules and revisions, redistribution limits, Beta Code handling, variants, and versification |
| OpenBible cross-references | Broad known-link and weak-supervision layer | Official page describes about 340,000 downloadable links, primarily from TSK, under a CC Attribution notice | Inspect archive contents; ensure no ESV quotations are imported; create stable date/hash snapshot and versification mapping |
| UBS Parallel Passages | Curated parallels and OT-in-NT benchmark/reference | UBS publishes structured data with a dedicated CC BY-SA 4.0 license | Pin commit; map labels/token numbering; separate training, evaluation, and knownness uses; propagate ShareAlike obligations |
| ETCBC DSS | Deferred early-witness validation | Official repository supplies Text-Fabric transcriptions/annotations, archived releases, an MIT repository license, and acknowledges Abegg data | Confirm upstream transcription rights; select biblical subset; represent fragments/reconstruction; align with confidence |
| Hebrew critical apparatus | Deferred Hebrew variant validation | German Bible Society describes BHQ/BHS scholarly apparatuses and their edition scope | Select edition/fascicles; obtain machine-processing rights; define local access, citation, extraction, and derived-output limits |
| Greek critical apparatus | Deferred Greek NT variant validation | German Bible Society publishes NA/UBS/ECM critical editions | Select source and coverage; obtain written machine-processing and publication terms; pin edition |
| CAL Targum category | Deferred reception-history checking | CAL is an institutional live Aramaic text base and requires access dates in citations | Select exact Targum editions; obtain versioned lawful bulk access and reuse terms; keep out of primary discovery |

Links, exact preliminary license fields, attribution text, and recorded uncertainties are in the source manifest. “Confirmed” means verified on an official provider page during this review, not that every legal or scholarly question is resolved.

## Dataset activation requirements

A source remains inactive until it has:

- A defined research purpose and role.
- Verified provider, edition, provenance, and component lineage.
- Reviewed license, license URL, attribution, redistribution, machine-processing, and raw-Git policy.
- A pinned immutable release or commit; for undated archives, an acquisition date plus raw-file SHA-256 hashes.
- Expected-file inventory and a reproducible acquisition procedure that never overwrites silently.
- A named adapter and offline reprocessing path.
- Alignment and versification strategy.
- Corpus-quality checks and spot-check protocol.
- Demonstrated value for retrieval, interpretation, or validation.
- An explicit decision about publishable raw and derived outputs.

Only `approved`, `acquired`, and `validated` states may pass later activation gates, and the schema prevents those states from outrunning licensing or version evidence.

## Source-selection criteria

Selection favors original-language fidelity; explicit edition and provenance; token-level morphology and syntax; transparent annotation definitions; stable identifiers; reproducible versioning; documented licensing; cross-corpus alignment potential; inspectable errors; and demonstrated methodological benefit. Availability, popularity, or ease of download alone is insufficient.

When sources conflict, selection is not resolved by silently choosing the most convenient value. The primary source remains identifiable, supplementary values remain parallel, and experiments declare the layer used.

## Version-pinning policy

Git sources use an immutable commit and, when available, a release tag. Mutable web archives use acquisition timestamp, final URL, HTTP metadata when available, archive hash, internal file list, and individual file hashes. Live databases require an authorized snapshot or export; an access date alone is not reproducible enough for activation. Updating a source creates a new manifest version and corpus-processing run. Earlier raw and processed hashes remain in history.

No version has been pinned in Milestone 1 because no acquisition has occurred. `null` version and date fields are deliberate and prevent the records from being marked acquired.

## Raw-data storage policy

Raw biblical and external data live under Git-ignored local paths. Restricted files are never committed, attached to issues, placed in releases, copied into fixtures, or embedded in logs. Manifests, checksums, source URLs, licenses, acquisition instructions, schemas, and synthetic fixtures are trackable. A permissive license does not require raw files to be committed; local-only storage is the conservative default until publication value and component rights are reviewed.

## Derived-output publication policy

Derived outputs are reviewed source by source. A permitted output must avoid reconstructing restricted source text, retain attribution and source/version lineage, comply with ShareAlike or other conditions, document transformations, and identify license boundaries in mixed-source artifacts. Scores, hashes, aggregate statistics, candidate IDs, or short evidence excerpts are not presumed publishable merely because they are derived. Public release requires a recorded determination.

## Annotation-conflict policy

Annotations carry source ID, source version, field name, original value, alignment method, and confidence. Conflicting morphology, lemma, sense, name, participant, or semantic values are stored separately. A reconciled field, if later needed, names its rule and run. Experiments select the source or reconciliation layer in configuration. No import overwrites a primary value in place.

## Versification and reference concerns

Book names, order, chapter and verse boundaries, Psalm numbering, subverses, deuterocanonical additions, and LXX/MT divisions differ. Reference strings are never treated as universal identifiers. Every crosswalk records source and target schemes, alignment method, confidence, and unresolved cases. Benchmark links cannot enter evaluation until their references map unambiguously or carry an explicit uncertainty state.

## Septuagint-specific concerns

A Septuagint source requires separate review of Greek edition and recension, morphology, tokenization, variants, books within the initial boundary, Hebrew parallel source, alignment method, Psalm numbering, alternate forms, provider agreement, and redistribution. CATSS is a candidate, not an approved selection. Its activation remains blocked by primary corpus and known-link gates even if its own source review later passes.

## Why deferred corpora remain excluded

Textual witnesses are fragmentary or editorially complex and answer a validation question different from initial discovery. Apparatuses often have restrictive rights. Reception sources can show later interpretation but could be mistaken for original textual dependence if mixed into discovery. Additional canons and literary corpora materially expand the research question and alignment burden. Deferral protects interpretive clarity, evaluation validity, and licensing discipline; it does not imply those corpora lack scholarly importance.
