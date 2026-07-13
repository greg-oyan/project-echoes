# Data sources and provenance

Status: **Milestone 5 passage segmentation complete; unactivated sources remain preliminary**
Review date: 2026-07-12

The authoritative machine-readable register is [`data/manifests/sources.yaml`](../data/manifests/sources.yaml). MACULA Hebrew and MACULA Greek are the validated primary sources: their pinned snapshots have been acquired, ingested, and checked locally, and the unified DuckDB tables expose both corpora with distinct corpus and provenance values. OSHB is the validated Ketiv/Qere supplementary source. Milestone 5 derives passages only from these approved inputs; it activates no new dataset. Other records document intent and review state rather than activation. Raw biblical data, full processed token tables, passage Parquet, and the local database remain Git-ignored.

## Layered corpus strategy

Project Echoes treats datasets as governed layers with distinct research functions:

1. **Primary discovery** — MACULA Hebrew and Greek, subject to edition, component, license, acquisition, and corpus validation.
2. **Bridge** — a later Septuagint source for controlled Hebrew–Greek–New Testament triangulation.
3. **Supplementary annotation** — future selected STEPBible fields or comparable resources, if activated, stored alongside, never over, primary annotations.
4. **Benchmark/reference** — known cross-references and curated parallels for held-out recovery, leakage control, and knownness.
5. **Textual validation** — DSS, variants, and apparatuses used only to test wording behind existing candidates.
6. **Reception history** — Targums and later interpretive corpora, excluded from primary discovery.

The detailed boundary is fixed in [corpus-scope.md](corpus-scope.md).

## Source register

| Source | Purpose | Confirmed at this review | Outstanding boundary |
|---|---|---|---|
| MACULA Hebrew | Primary Hebrew/Aramaic tokens and linguistic annotations | Validated `WLC/nodes` snapshot from release `25.08.11`, commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`; 475,911 records across 39 books and 929 chapters | Full processed-table publication remains unapproved; preferred-Qere representation has no complete parallel Ketiv layer; any source upgrade requires renewed review |
| MACULA Greek | Primary Greek NT tokens and linguistic annotations | Validated `Nestle1904/nodes` snapshot from release `24.06.17`, commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`; 137,779 records across 27 books and 260 chapters, matching the upstream test expectation | Full processed-table publication remains unapproved; MARBLE-derived LN/LexDomain fields need a field-level derived-output review; any source upgrade requires renewed review |
| STEPBible Data | Eligible future supplementary glosses, lexical/semantic mappings, names, morphology, or versification | Repository-level CC BY 4.0 statement and UTF-8 tabular-resource availability are recorded; activation is deferred under [ADR 0012](decisions/0012-defer-stepbible-activation.md) | No file is selected, approved, blocked, acquired, or validated; all seven file-level provenance and licensing questions remain unresolved |
| CATSS Septuagint | Later bridge morphology and Hebrew–Greek alignment | Official CATSS materials describe Rahlfs-based Greek morphology, Stuttgart Hebrew parallel data, and a source-specific user agreement | Confirm current acquisition agreement, exact modules and revisions, redistribution limits, Beta Code handling, variants, and versification |
| OpenBible cross-references | Broad known-link and weak-supervision layer | Official page describes about 340,000 downloadable links, primarily from TSK, under a CC Attribution notice | Inspect archive contents; ensure no ESV quotations are imported; create stable date/hash snapshot and versification mapping |
| UBS Parallel Passages | Curated parallels and OT-in-NT benchmark/reference | UBS publishes structured data with a dedicated CC BY-SA 4.0 license | Pin commit; map labels/token numbering; separate training, evaluation, and knownness uses; propagate ShareAlike obligations |
| ETCBC DSS | Deferred early-witness validation | Official repository supplies Text-Fabric transcriptions/annotations, archived releases, an MIT repository license, and acknowledges Abegg data | Confirm upstream transcription rights; select biblical subset; represent fragments/reconstruction; align with confidence |
| Hebrew critical apparatus | Deferred Hebrew variant validation | German Bible Society describes BHQ/BHS scholarly apparatuses and their edition scope | Select edition/fascicles; obtain machine-processing rights; define local access, citation, extraction, and derived-output limits |
| Greek critical apparatus | Deferred Greek NT variant validation | German Bible Society publishes NA/UBS/ECM critical editions | Select source and coverage; obtain written machine-processing and publication terms; pin edition |
| CAL Targum category | Deferred reception-history checking | CAL is an institutional live Aramaic text base and requires access dates in citations | Select exact Targum editions; obtain versioned lawful bulk access and reuse terms; keep out of primary discovery |

Links, exact license fields, attribution text, and recorded uncertainties are in the source manifest. “Confirmed” means verified on an official provider page during this review, not that every legal or scholarly question is resolved.

## Validated MACULA Hebrew snapshot

Milestone 2 selects the official [Clear Bible MACULA Hebrew repository](https://github.com/Clear-Bible/macula-hebrew), release `25.08.11`, resolved to immutable commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`. The adapter consumes `WLC/nodes`, not `WLC/lowfat` or the reduced tabular exports, because the node representation retains the required token, morphology, syntax, semantic, participant, and provenance attributes. The selected snapshot represents Westminster Leningrad Codex 4.20.

The acquisition is a sparse Git checkout of `README.md`, `LICENSE.md`, and `WLC/nodes`. Its expected inventory is 932 files: the two notices plus 929 chapter node files and the node XInclude index. The tracked manifest records the immutable revision and three anchor SHA-256 hashes; the Git-ignored receipt records the hash and size of every acquired file. The acquisition command rejects unapproved or unpinned records, validates the inventory, and does not overwrite an existing destination unless `--force` is explicit.

```bash
uv run echoes acquire-source macula-hebrew
uv run echoes verify-acquisition macula-hebrew
```

Ingestion maps the 475,911 upstream morpheme records one-to-one to 475,911 canonical records: 468,362 Hebrew and 7,549 Aramaic tokens across all 39 expected books and 929 chapters. Each output row retains the source ID and commit, source file and row, native identifier or documented fallback, source word identifier, source-edition verse reference and position, original surface form, language, morphology, syntax ancestry, semantic and participant annotations, gloss, source attributes, normalization version, and ingestion run identity as applicable. Stable project IDs derive exclusively from source-edition book/chapter/verse/token/subtoken identity, plus native record identity when required for variants; later crosswalks and alignments are separate mapping layers.

Versioned Parquet tables and the corresponding DuckDB tables are written under Git-ignored `data/processed/`. The corpus validator checks source-to-token identity, ID collisions, duplicate canonical positions, position continuity, book/chapter/verse coverage, language, normalization, annotation completeness, stored hashes, and Parquet/DuckDB row and logical agreement. Independent full builds from the same acquisition receipt and configuration produced run ID `hebrew-7db8035c6ae1c3268074` and identical logical table hashes.

MACULA represents its preferred Qere reading where available and does not provide a complete parallel Ketiv layer in this snapshot. Consequently, zero Ketiv/Qere-marked tokens is a source-representation limitation, not evidence that the underlying text has no variants. The schema nevertheless preserves both records when supplied and exposes a configuration-selected derived Qere/Ketiv analysis stream without changing the base table. Zero-width morphemes supplied by the source are retained explicitly rather than discarded or converted to visible text.

## Validated MACULA Greek snapshot

Milestone 3 selects the official [Clear Bible MACULA Greek repository](https://github.com/Clear-Bible/macula-greek), release `24.06.17`, resolved to immutable commit `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`. The adapter consumes `Nestle1904/nodes` — the release's native, annotation-complete representation — rather than the SBLGNT representation, whose own README documents unmapped nodes with missing Gloss, Louw-Nida, and Domain values. The textual edition is the Nestle 1904 Greek New Testament. The selection decision, superseding the provisional SBLGNT v1.2 intent, is [ADR 0010](decisions/0010-macula-greek-source-selection.md).

The acquisition is a canonical-byte sparse Git checkout of `README.md`, `LICENSE.md`, and `Nestle1904/nodes`: 29 files (two notices plus 27 book node files). The tracked manifest records the immutable revision and three anchor SHA-256 hashes, externally verified against the pinned commit's raw bytes; the Git-ignored receipt records the hash and size of every acquired file.

```bash
uv run echoes acquire-source macula-greek
uv run echoes verify-acquisition macula-greek
uv run echoes ingest-greek
uv run echoes validate-corpus --corpus greek
uv run echoes validate-corpus --corpus unified
```

Ingestion maps the 137,779 upstream leaf word records one-to-one to 137,779 canonical `GNT_` tokens across all 27 books and 260 chapters, matching the count the pinned upstream test suite asserts. Stable project IDs derive exclusively from source-edition book/chapter/verse/word identity through the same source-edition-only identity module as Hebrew. Edition-level versification is recorded exactly: fifteen verses the Nestle 1904 edition omits are declared and verified, the pericope adulterae is present inline (JHN 7:53-8:11, 190 tokens), and the shorter ending of Mark is encoded at out-of-sequence verse MRK 16:99 (33 tokens); the disputed-passage handling is flagged for human interpretation, not decided by ingestion.

Punctuation attached to word text is separated losslessly into derived columns, elision marks remain part of the word core (1,223 elided tokens), crasis forms remain single tokens, and the source's accent-regularized `NormalizedForm` is preserved in a separate column. The unified `unified_tokens` DuckDB view exposes the shared canonical columns of both corpora with distinct corpus and provenance values and no token-ID collisions.

## OSHB Ketiv/Qere supplementary layer

The pinned Open Scriptures Hebrew Bible (`oshb-morphhb`, commit
`3d15126fb1ef74867fc1434be1942e837932691f`) supplies the separate Ketiv
records missing from the primary MACULA representation. Every locus preserves
the exact OSIS `source_book_identifier` and the mapped Project Echoes/MACULA
`canonical_book` as distinct values. Source-native identifiers drive only
identity and source references: for example, OSHB `2Kgs` normalizes to `2KGS`
inside `HB_2KGS_008_010_0006~94c99d606560`, while
`source_edition_reference` remains `2Kgs 8:10` and the analytical `book`/join
key remains `2KI`. Normalization accepts one through sixteen ASCII
alphanumerics, applies uppercase only inside the token namespace, and rejects
punctuation or whitespace rather than collapsing it. Existing three-character
MACULA Hebrew and Greek namespaces are byte-identical under this rule.

Inherited MACULA sentence, clause, and phrase membership is never written into
OSHB source-native fields. It resides in a separate structural-alignment table
with ordered anchors, method, confidence, status, and field-level resolution
notes. Paired loci require unanimous replaced-Qere anchors; Ketiv-only loci
require agreeing nearest primary tokens on both sides within the same verse.

## Validated passage-derivation provenance

Passage run `passages-v1-00e261abea9ed44ef087` records the exact MACULA Hebrew
commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`, MACULA Greek commit
`b5b7ecec0882a3e9a609ecac99e157391e5d9b46`, OSHB commit
`3d15126fb1ef74867fc1434be1942e837932691f`, and their established identity,
surface/lemma, analytical, and supplement digests. The six derived stream
contexts preserve source ID and version on membership rows and never overwrite
the source tables. Two complete strict runs produced the same run ID, 914,497
passages, 21,530,271 exact membership rows, and deterministic logical hashes.
Each run reported 627,780,157 bytes of generated passage output. These locally
validated derived artifacts are not a new textual witness and are not approved
for public redistribution.

## STEPBible activation deferral

[ADR 0012](decisions/0012-defer-stepbible-activation.md) records the
owner-approved decision to defer STEPBible rather than require it for
Milestone 4 closure. MACULA Hebrew and Greek already supply the primary
linguistic foundation, OSHB supplies the required Ketiv/Qere supplement, and
the repository now has generic supplementary-annotation,
conflict-preservation, structural-alignment, and versification-crosswalk
infrastructure. No current downstream capability identifies a STEPBible file
that it needs. Acquiring one now would add file-level provenance, licensing,
namespace, and annotation-conflict work without a demonstrated analytical
benefit.

STEPBible remains an eligible future supplementary source. Activation requires
all of the following: a specific missing field or capability, the exact files
required, a measurable benefit, completed file-level licensing and provenance
review, and a conflict-preserving integration design. Deferral is neither
rejection nor a licensing determination. The manifest therefore remains
`under_review`, with no version, download date, expected files, hashes,
acquisition specification, or adapter, and preserves all seven unresolved
questions documented in [data-licensing.md](data-licensing.md).

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

MACULA Hebrew is pinned to the immutable commit above and may be marked validated because its acquisition receipt, inventory, hashes, adapter, and corpus checks exist. `null` version and date fields for every other unacquired source remain deliberate and prevent those records from being marked acquired. A future MACULA Hebrew upgrade is a new source version and must not silently replace 25.08.11; in particular, 2026 releases require a fresh review of the later SILHA integration and licensing terms.

## Canonical-byte hashing policy

All recorded source hashes are canonical-byte SHA-256 values: they are computed over the
exact bytes of the pinned upstream revision, byte-for-byte as published. Windows
text-mode Git checkouts (`core.autocrlf=true`) rewrite LF line endings to CRLF in files
Git classifies as text, silently altering the bytes on disk; such mutated working-tree
files must never feed the hasher. The governance mechanisms are:

- Git-based acquisitions disable every text conversion: the acquisition checkout sets
  `core.autocrlf=false` and declares `* -text` in `.git/info/attributes` (the
  highest-precedence gitattributes source), so working-tree files carry the pinned
  commit's exact blob bytes.
- Direct HTTP fetches hash the download stream itself as it is received, before any
  local filesystem interpretation.
- `echoes validate-sources` recomputes canonical hashes for every manifest-hashed file
  whose raw acquisition directory is present locally and fails on any divergence.
- When an acquisition clone retains its `.git` object store, `git cat-file blob` at the
  pinned commit provides canonical bytes without re-downloading; a working tree checked
  out under text-mode settings is never a trustworthy hashing input.

The original Milestone 2 inventory was computed on a text-mode checkout and is
superseded; it is retained, marked superseded, inside the regenerated Milestone 2
ingestion report. The corpus identity digest
`91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6` and the 475,911
token count were identical before and after remediation, confirming the line-ending
rewrite never reached parsed XML content or token identity.

### Corpus digests

Three whole-corpus SHA-256 fingerprints guard the processed primary tables;
one implementation serves both corpora (`echoes.corpus.validation`):

- **Identity digest** (`corpus_identity_digest`): corpus-position-ordered
  `token_id\0source_record_id\0source_word_id\n` rows, UTF-8.
- **Surface/lemma compatibility digest** (`corpus_content_digest`):
  corpus-position-ordered
  `token_id\0surface_form\0normalized_form\0lemma\n` rows, UTF-8, with a null
  lemma encoded as the empty string. The historical function name is retained
  for compatibility; it is not a comprehensive annotation digest.
- **Analytical digest** (`corpus_analytical_digest`): a versioned canonical
  serialization of every stable, downstream-relevant field present in the
  Hebrew or Greek primary schema, including source identity, all forms,
  lexical, morphological, structural, syntactic, semantic, participant,
  language, and variant fields. Rows are ordered by preserved corpus position
  and token identity, JSON objects are parsed and key-sorted, and null remains
  distinct from an empty string. Relative/local path fields, timestamps, and
  raw preservation envelopes are excluded.

Recorded constants, asserted by the opt-in full-corpus regression:

| Corpus | Tokens | Identity digest | Surface/lemma digest | Analytical digest |
|---|---:|---|---|---|
| Hebrew (`macula-hebrew` 25.08.11) | 475,911 | `91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6` | `7fb443c3f0c42ada5d89f3abad61dd304145863044107ac86277c9f05f76cc82` | `9464a106684b63ff57bcd9dd754bcd0c875d7ea8157fc7bfe643d7eb66dab173` |
| Greek (`macula-greek` 24.06.17) | 137,779 | `9035fea8d73a2b2078ad2adc70f8389040dbe2051ee535b2ce88412f551df6f2` | `a5ede58d287c2d29d5dacc7adeb07ff5c6a10587e2949875928b2dd935c8c683` | `31404eb29a1f71855f3670f6f895e3fadc3ab0b39e2685c3cf672620df08a2a1` |

These constants are stop-condition anchors for supplementary-annotation work:
the base MACULA tables must remain byte-identical through all Milestone 4
layering, and any change is a corpus migration, never a side effect.

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
