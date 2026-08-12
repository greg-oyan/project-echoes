# Data sources and provenance

Status: **validated corpora retained; `final-discovery-v1` activates one
bounded reference-only benchmark, defers LXX, and pins one optional
supplemental model**
Review date: 2026-08-08

The authoritative machine-readable register is
[`data/manifests/sources.yaml`](../data/manifests/sources.yaml). MACULA Hebrew
and MACULA Greek are the validated primary sources: their pinned snapshots
have been acquired, ingested, and checked locally, and the unified DuckDB
tables expose both corpora with distinct corpus and provenance values. OSHB is
the validated Ketiv/Qere supplementary source. Milestone 6 added the
validated, content-addressed OpenBible.info cross-reference snapshot for Tier
3 weak supervision and broad knownness filtering only. Milestone 7 activated
no new source: it derived transparent lexical features from the existing
governed passages and evaluated only against the immutable Tier 3 artifacts.
`final-discovery-v1` activates no new textual corpus. It reuses authenticated
governed corpus inputs, activates only the bounded UBS reference-only
positive-control adaptation described below, records a non-blocking LXX
deferral, and preregisters an optional pinned embedding model. Other source
records document intent and review state rather than activation. Raw source
archives, full processed token tables, passage, benchmark, and lexical
Parquet, sparse indexes, acquisition receipts, model assets, and the local
database remain Git-ignored.

## Milestone 7 derived-feature provenance

The lexical baseline reads authoritative passage membership linked to the pinned MACULA
Hebrew release `25.08.11` at `7ab368fcb14e4ad2e0f784138241a098fb516ec4`, MACULA Greek
release `24.06.17` at `b5b7ecec0882a3e9a609ecac99e157391e5d9b46`, and the OSHB
Ketiv/Qere supplement at `3d15126fb1ef74867fc1434be1942e837932691f`. It does not
replace, reconcile, or overwrite any source lemma, surface, morphology, gloss, or structural
annotation. Every complete run authenticates the accepted corpus, passage, and benchmark
logical hashes before retrieval.

Original-language lemma, normalized-surface, POS, morphology, phrase, and sequence features
remain separately language-prefixed. The governed full snapshots supply no root values, so
root outputs remain empty rather than being inferred from another source. Entity,
participant, predicate-argument, semantic-domain, and embedding fields are outside the
Milestone 7 detector scope even when upstream annotations exist.

The exploratory cross-testament representation uses the English gloss fields already
present in the pinned MACULA aggregates. Those fields are marked `en` and English-derived;
they are neither a new English translation corpus nor direct Hebrew-Greek lexical evidence.
Every such result is reported separately and undergoes removal of all English-derived
features. STEPBible and every Septuagint resource remain unactivated.

OpenBible snapshot `snapshot-2026-07-12-sha256-18e63e370308` remains the sole populated
evaluation reference and retains its Tier 3 weak-supervision role. Its relationship graph,
direction, provisional passage mappings, and descriptive votes do not become source-text
evidence or scholarly ground truth merely because a lexical detector recovers them. Tier 1
remains empty.

## `final-discovery-v1` UBS positive controls

The campaign activates a bounded reference-only adaptation of the **UBS
Parallel Passage Database, copyright 2023 United Bible Societies**, pinned at
commit `3a6edd8212df2e1189037ad39687726990c80d56` and licensed CC BY-SA 4.0.
The governed adaptation contains 24 unordered reference pairs assigned by
leakage group: 15 training rows across six groups, three development rows in
one group, and six test rows in one group. Its CSV SHA-256 is
`58cad772a69e496046b45d24925c764d6b04798fb57cb767b6e633e2aa1eff9d`;
the governing benchmark manifest SHA-256 is
`e9b1721b2618d950e9449d218d8107fdb127ac9bcd0ade5f6c11b0b25b37160e`.

This is a descriptive positive-control set for checking later detector-family
behavior, not a statistically independent gold benchmark. All six test rows
belong to the single `PCL_LAST_SUPPER` leakage group, so they are correlated
examples and cannot support a claim of held-out relationship-family
generalization. The reference pairs were manually checked against the pinned
source record, but no independent scholar adjudicated the underlying Hebrew
or Greek wording, relationship class, direction, or strength. The split must
therefore be reported descriptively, including negative or incomplete
recovery, and must not be used to tune the frozen final campaign after
candidate identities are inspected.

Only reference pairs and Project Echoes metadata are active. Biblical text and
UBS word-match strings from the upstream XML were intentionally omitted and
are inactive as passages, features, match evidence, or publication excerpts.
The tracked adaptation retains CC BY-SA 4.0 attribution, modification, and
ShareAlike notices; the complete boundary is recorded in
[`data-licensing.md`](data-licensing.md).

## `final-discovery-v1` source and model boundary

[ADR 0019](decisions/0019-defer-lxx-and-govern-multilingual-e5.md) records the
campaign-specific source review. The final campaign is valid without an LXX
bridge. It acquires no new LXX corpus and does not merge data from different
Greek editions by reference or ordinal position.

The preferred future raw-text candidate is the Swete TEI corpus in
[OpenGreekAndLatin/First1KGreek at commit
`bfea9acd07ee1b7cea70cdd927c8f092d5637695`](https://github.com/OpenGreekAndLatin/First1KGreek/tree/bfea9acd07ee1b7cea70cdd927c8f092d5637695).
Its relevant path pattern is
`data/tlg0527/**/tlg0527.*.1st1K-grc1.xml`, subject to an explicit reviewed
39-book project-canon allowlist. The TEI preserves Swete edition metadata and
carries an electronic-transcription CC BY-SA 4.0 notice. It does not provide the validated
full-canon morphology, lemmas, Hebrew alignment, token mapping, or
versification crosswalk required for activation. OCR/encoding and markup QA
also remain outstanding.

[Open Scriptures GreekResources at commit
`dd5a2fd530ab3c6b748c174cec38966c356d8111`](https://github.com/openscriptures/GreekResources/tree/dd5a2fd530ab3c6b748c174cec38966c356d8111)
is a possible future CC BY 4.0 lemma source, but its records follow CATSS
`lxxmorph` ordering and a Rahlfs lineage rather than Swete. It cannot be joined
to the Swete files until an evidence-backed cross-edition mapping validates
tokens and references. CATSS/CCAT and Rahlfs-derived paths are deferred for
this campaign because their agreement, component provenance, edition match,
alignment, and redistribution boundaries are unsuitable or unresolved.

[UD Ancient Greek PTNK at commit
`818fb315ff1f6cd95b6e7fa90f3707488d2b010d`](https://github.com/UniversalDependencies/UD_Ancient_Greek-PTNK/tree/818fb315ff1f6cd95b6e7fa90f3707488d2b010d)
contains a CC BY-SA 4.0 Codex Alexandrinus sample of Genesis and Ruth. It may be
used in a later bounded adapter/alignment QA exercise, but its coverage and
edition identity do not make it a production bridge.

The optional semantic model is
[`intfloat/multilingual-e5-small` at immutable revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3),
MIT licensed under its [pinned model card](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md).
The preregistered configuration lineage is SentenceTransformers
modules and mean/L2 pooling, an XLM-R SentencePiece tokenizer, 384 dimensions,
a 512-token maximum, and symmetric `query: ` prefixes. The closed artifact
inventory is:

| Artifact | Bytes when recorded | SHA-256 |
|---|---:|---|
| `1_Pooling/config.json` | 200 | `987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0` |
| `config.json` | 655 | `69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959` |
| `model.safetensors` | 470,641,600 | `1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477` |
| `modules.json` | 387 | `c6e29747481e8b5dd2b58401966aeac910de39092f90cda9a704b1545f902b04` |
| `sentence_bert_config.json` | 57 | `948201d8329907aae938fa62f9ceeed53f5694dacc2b87b9f3b78b37ee986529` |
| `sentencepiece.bpe.model` | 5,069,051 | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` |
| `special_tokens_map.json` | 167 | `d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7` |
| `tokenizer.json` | 17,082,730 | `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39` |
| `tokenizer_config.json` | 443 | `a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b` |

The frozen dependency lineage is `sentence-transformers==5.7.0`,
`transformers==5.14.1`, `torch==2.13.0`, `tokenizers==0.22.2`,
`huggingface-hub==1.27.0`, `safetensors==0.8.0`, and
`scikit-learn==1.9.0`. No model weights or tokenizer assets were downloaded in
this review. A future authorized acquisition must authenticate every file and
may not silently select alternate backend exports.

The model is supplemental retrieval evidence, never philological proof of a
relationship. Its validity for Ancient Greek and Biblical Hebrew is
unestablished, and possible exposure to biblical text, translations,
commentary, or benchmarks during broad multilingual web pretraining is
unquantified. Embedding-only similarity cannot establish Tier A, tokenizer and
truncation diagnostics remain required, and English-derived runs are labeled
and ablated separately.

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
| Swete TEI in First1KGreek | Preferred future raw LXX text candidate | Candidate pinned for review at commit `bfea9acd07ee1b7cea70cdd927c8f092d5637695`; printed Swete volumes treated as public domain in the US; electronic TEI is CC BY-SA 4.0 | Deferred by ADR 0019; no acquisition or adapter; validate allowlist, OCR/markup, morphology, alignment, tokenization, versification, attribution, and derived-output obligations |
| Open Scriptures GreekResources | Possible future LXX lemma candidate | Candidate pinned for review at commit `dd5a2fd530ab3c6b748c174cec38966c356d8111`; repository resources are CC BY 4.0 | Lemmas follow CATSS/Rahlfs `lxxmorph` ordering and cannot be joined to Swete without a validated cross-edition mapping |
| CATSS Septuagint | Potential later bridge morphology and Hebrew–Greek alignment | Official CATSS materials describe Rahlfs-based Greek morphology, Stuttgart Hebrew parallel data, and a source-specific user agreement | Rejected/deferred for `final-discovery-v1`; future work must resolve agreement, exact modules/revisions, redistribution, Beta Code, variants, edition mismatch, and versification |
| UD Ancient Greek PTNK | Bounded future LXX adapter/alignment QA | Candidate pinned for review at commit `818fb315ff1f6cd95b6e7fa90f3707488d2b010d`; CC BY-SA 4.0; Codex Alexandrinus Genesis and Ruth | QA sample only; coverage and edition differ from the preferred Swete production candidate |
| OpenBible cross-references | Tier 3 weak supervision and broad knownness filtering | Validated snapshot `snapshot-2026-07-12-sha256-18e63e370308`; archive SHA-256 `18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492`; two deterministic full benchmark builds; one reference-and-vote file, no biblical quotation or ESV text; CC BY 4.0 determination and attribution recorded | Same-label passage mappings remain provisional without a verified crosswalk; heterogeneous links and votes are not scholarly truth or calibrated confidence; raw and normalized data remain local only by project policy |
| UBS Parallel Passages | Bounded later-family positive controls | Commit `3a6edd8212df2e1189037ad39687726990c80d56`; dedicated CC BY-SA 4.0 license; 24 reference-only rows in eight leakage groups | Active only for the governed reference-only adaptation; test is one correlated group, no independent original-language adjudication, and upstream biblical text/match strings remain inactive; preserve attribution, modification notice, and ShareAlike |
| ETCBC DSS | Deferred early-witness validation | Official repository supplies Text-Fabric transcriptions/annotations, archived releases, an MIT repository license, and acknowledges Abegg data | Confirm upstream transcription rights; select biblical subset; represent fragments/reconstruction; align with confidence |
| Hebrew critical apparatus | Deferred Hebrew variant validation | German Bible Society describes BHQ/BHS scholarly apparatuses and their edition scope | Select edition/fascicles; obtain machine-processing rights; define local access, citation, extraction, and derived-output limits |
| Greek critical apparatus | Deferred Greek NT variant validation | German Bible Society publishes NA/UBS/ECM critical editions | Select source and coverage; obtain written machine-processing and publication terms; pin edition |
| CAL Targum category | Deferred reception-history checking | CAL is an institutional live Aramaic text base and requires access dates in citations | Select exact Targum editions; obtain versioned lawful bulk access and reuse terms; keep out of primary discovery |

Links, exact license fields, attribution text, and recorded uncertainties are in the source manifest. “Confirmed” means verified on an official provider page during this review, not that every legal or scholarly question is resolved.

## Validated OpenBible Tier 3 snapshot

Milestone 6 audited the official [Bible Cross References page](https://www.openbible.info/labs/cross-references/) and the linked archive at
`https://a.openbible.info/data/cross-references.zip`. Two audit downloads were
byte-identical. The governed identity is:

```text
Snapshot label: snapshot-2026-07-12-sha256-18e63e370308
Archive SHA-256: 18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492
Extracted file: cross_references.txt
Extracted SHA-256: eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37
Canonical stream schema: openbible-tsv-v1
```

The safe ZIP contains only `cross_references.txt`. It is UTF-8 TSV reference data with an
internal CC BY notice, directional source and target reference fields, and signed integer
votes. The source audit found no biblical quotation text, ESV quotations, other modern
translation text, executable content, symlinks, or mixed-rights secondary dataset. The
source therefore passes the archive-content stop conditions for its validated Tier 3 role.

Acquisition is approval-gated, content-addressed, atomic, and non-overwriting. It records
the requested and final URL, available HTTP headers, archive and extracted hashes, archive
inventory, and canonical parsed-stream hash in a Git-ignored schema-2 receipt. Verification
recomputes the exact receipt without contacting the network:

```bash
uv run echoes acquire-source openbible-cross-references
uv run echoes verify-acquisition openbible-cross-references
```

Every physical source row remains traceable. Source votes remain ranking metadata, not a
probability or scholarly confidence. References retain the
`openbible-english-protestant-v1` scheme. Mappings target Milestone 5 verse passages, but
same-label mappings without an independently approved versification crosswalk are
provisional. Missing verses are never fabricated, and ranges, profile exclusions,
reference gaps, and disputed text remain explicit.

Two complete schema-v1 builds reproduced run
`benchmark-v1-dff1d3ef650c8ccd4930`, version
`known-links-v1-dff1d3ef650c`, all logical hashes, counts, and content-table
physical hashes. Each strict validation returned zero errors, zero warnings,
and 18 informational findings. The builds materialized 344,799 relationships,
689,598 endpoints, and 1,379,196 conservative profile mappings. That validation
changes the manifest lifecycle from `approved` to `validated`; it does not
upgrade OpenBible beyond Tier 3 or turn same-label mappings into verified
versification equivalence.

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

MACULA Hebrew, MACULA Greek, and OSHB remain pinned to their immutable Git commits. OpenBible is pinned by the complete archive SHA-256 above; the shorter hash in its snapshot label is descriptive, not the authoritative identity. Other unacquired sources retain deliberate `null` versions and dates that prevent premature activation. Any Git or archive update creates a new source version, receipt, processing run, and review. A future MACULA Hebrew upgrade must not silently replace 25.08.11; in particular, 2026 releases require a fresh review of the later SILHA integration and licensing terms.

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

A Septuagint source requires separate review of Greek edition and recension, morphology, tokenization, variants, books within the initial boundary, Hebrew parallel source, alignment method, Psalm numbering, alternate forms, provider agreement, and redistribution. ADR 0019 prefers the pinned Swete TEI as the starting raw-text candidate for later work but does not approve or acquire it. CATSS/Rahlfs paths are rejected for `final-discovery-v1`; GreekResources cannot be positionally mapped to Swete; and UD PTNK remains a bounded QA sample only. A later activation must supersede this deferral with a complete source manifest, file hashes, adapter, cross-edition and versification validation, component notices, and derived-output determination.

## Why deferred corpora remain excluded

Textual witnesses are fragmentary or editorially complex and answer a validation question different from initial discovery. Apparatuses often have restrictive rights. Reception sources can show later interpretation but could be mistaken for original textual dependence if mixed into discovery. Additional canons and literary corpora materially expand the research question and alignment burden. Deferral protects interpretive clarity, evaluation validity, and licensing discipline; it does not imply those corpora lack scholarly importance.
