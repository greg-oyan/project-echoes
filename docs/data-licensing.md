# Data licensing and publication governance

Status: **validated source boundaries retained; `final-discovery-v1` LXX bridge
deferred; optional embedding model governed**
Review date: 2026-08-08

This document records operational governance, not legal advice. Technical accessibility, a public Git repository, or an online reading interface does not by itself grant permission to copy, process in bulk, redistribute, or publish derived data. Uncertainty blocks source approval.

The repository software/documentation license remains pending owner selection. That decision is separate from every external dataset license.

## Review procedure

1. Identify the provider, rights holder, edition, exact files, and upstream components.
2. Read the provider's official license, terms, rights page, attribution instructions, and component notices; preserve URLs and review date.
3. Classify redistribution and machine processing separately. A right to read, query, or use academically is not necessarily a right to redistribute.
4. Record required attribution, notice preservation, modification marking, noncommercial or ShareAlike conditions, and any permission correspondence.
5. Decide raw-data Git policy independently. Project Echoes defaults to local ignored storage even for permissive sources.
6. Define which derived outputs may be public and whether they could reconstruct protected source content.
7. Have ambiguous or proprietary cases reviewed by the repository owner and, where material, the provider or qualified counsel.
8. Update the manifest through a reviewed commit and decision record. Preserve the prior determination in Git history.

## Fields required before approval

An approved source needs a non-unknown license and official URL, completed review status, explicit attribution, non-unknown redistribution and machine-processing classifications, safe raw-data policy, edition where it is a primary source, and notes describing limitations. Acquisition additionally requires an immutable version or commit, acquisition date, expected files, and SHA-256 hashes. The Pydantic schema enforces these minimum blockers.

## Attribution

Attribution is preserved in source manifests, data lineage, generated reports, public tables, and release notices. It identifies the source name, provider, edition/version, URL, license, required wording, modifications, and access or acquisition date. Mixed-source outputs include every applicable attribution rather than citing only the final aggregator.

## Raw-data Git policy

- `trackable` is allowed by schema only when redistribution and machine processing are both permitted; project policy may still choose not to track it.
- `metadata_only` permits only manifests, checksums, instructions, and related metadata.
- `ignored_local_only` requires raw files to stay under excluded local storage.
- `prohibited` means the repository must not store or acquire raw content absent a new determination.

Restricted biblical text, apparatus data, licensed exports, and credentials never enter Git history, fixtures, CI caches, logs, GitHub issues, or releases.

## Restricted datasets

Restricted sources require an authorized acquisition path, access controls consistent with their terms, local-only storage, a record of who obtained the data and under what grant, and reproducible processing instructions that do not expose the source. If a collaborator lacks access, the pipeline must fail with an acquisition instruction rather than silently substitute another edition.

## Derived outputs

A derived result is not automatically free of source restrictions. Review considers whether it contains recoverable text, dense annotations, apparatus decisions, aligned excerpts, or a substantial database adaptation. Permitted results retain attribution, transformation documentation, input hashes, and license notices. ShareAlike conditions are evaluated for database adaptations. Restricted evidence may require aggregate-only publication, short quotation under an applicable exception, or no public output.

## Public releases

Before a release, generate an inventory of included files and their input sources; verify every manifest and output determination; scan for raw/restricted data and secrets; include notices and citations; distinguish code, original documentation, external data, and derived-data licenses; and record the exact release commit. Unknown or conflicting rights remove the affected material from the release.

## Proprietary critical editions

BHQ/BHS, Nestle-Aland, UBS, ECM, and other modern apparatuses are treated as proprietary research sources unless the rights holder grants explicit relevant permission. A subscription or browser interface does not authorize scraping. No apparatus is acquired through Milestone 2. Later use requires exact edition/coverage, written machine-processing terms, local-storage rules, citation requirements, extraction limits, and a derived-output agreement.

The same rule applies to copyrighted UBS, Nestle-Aland, and comparable quotation or allusion appendices. Lawful manual consultation may be cited in a review record, but does not authorize ingestion, transcription, systematic extraction, reconstructed ordering, or copied benchmark data. Repository ingestion requires explicit permission covering the proposed machine use and publication.

## Citation and provenance

Citation and license are separate obligations. Every processed record retains stable project ID, source ID, source version, file and row reference, input hash, adapter version, and transformation run. Live resources record access date, but cannot become active without an authorized reproducible snapshot. Provider-requested citations supplement—not replace—edition-level scholarly citations.

## Changing a determination

A change requires new official evidence, a manifest update, reviewer and date, an explanatory decision record when publication behavior changes, revalidation, and assessment of existing raw/derived artifacts. Rights are never broadened by inference from a repository's visibility. A more restrictive determination triggers quarantine and release review; a less restrictive determination does not retroactively alter prior source versions without documentation.

## MACULA Hebrew 25.08.11 determination

The Milestone 2 review applies only to MACULA Hebrew release `25.08.11`, immutable commit `7ab368fcb14e4ad2e0f784138241a098fb516ec4`, and the acquired `WLC/nodes` representation. The official notice identifies the relevant components as follows:

- Westminster Leningrad Codex text: unrestricted/public-domain use as stated upstream.
- Open Scriptures Hebrew Bible morphology: CC BY 4.0.
- Groves Center/Westminster syntax: CC BY 4.0.
- Cherith Analytics English glosses: CC BY 4.0.
- Clear Bible/Biblica integrated annotations: the MACULA aggregate is offered under CC BY 4.0.
- Enumerated SDBH-derived attributes: included in that aggregate with permission from United Bible Societies; this project does not infer broader independent rights in the underlying SDBH resource.

This evidence supports reproducible local machine processing with all component notices and attribution retained. Project policy is deliberately narrower than the broadest possible reading of the aggregate license: redistribution is classified as `acquisition_instructions_only`, raw files are `ignored_local_only`, and complete processed token/annotation tables are not approved for public release. The repository may track acquisition instructions, source and transformation metadata, hashes, schemas, aggregate statistics, non-textual validation findings, and limited reports that do not reconstruct the corpus.

The required attribution names the MACULA Hebrew Linguistic Datasets and links the official repository, while preserving the WLC, Open Scriptures Hebrew Bible Project, Groves Center, Cherith Analytics, and UBS/SDBH notices applicable to the fields used. Any public derived artifact requires a fresh field-level review of its included columns, reconstructability, notices, and modification statement.

The selected release intentionally predates the SILHA gloss integration found in later 2026 releases. SILHA terms therefore are not imported into this snapshot, but a future upgrade must repeat the component and publication review rather than silently inherit this determination.

## OpenBible.info Tier 3 determination

The official [Bible Cross References page](https://www.openbible.info/labs/cross-references/) states that the graph contains approximately 340,000 cross references, draws primarily from public-domain sources—especially the *Treasury of Scripture Knowledge*—and provides a downloadable archive. The same page states that its content is licensed under the [Creative Commons Attribution 4.0 license](https://creativecommons.org/licenses/by/4.0/) unless otherwise indicated. It separately identifies displayed ESV Scripture quotations as copyrighted; those page quotations are outside this determination and must not be copied into Project Echoes.

The Milestone 6 review pins `snapshot-2026-07-12-sha256-18e63e370308`. The complete
archive SHA-256 is
`18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492`; its only
member is `cross_references.txt`, SHA-256
`eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37`.
The archive contains reference strings, signed vote integers, and an internal CC BY notice.
It contains no biblical quotation text, ESV text, other modern-translation text, executable
content, or additional mixed-rights dataset. The downloadable artifact therefore falls
within the official page's CC BY 4.0 determination; the separately copyrighted quotations
displayed on the page were neither acquired nor copied.

Redistribution and machine processing of this exact reference graph are classified as
permitted with attribution. Required attribution identifies “Bible Cross References” and
OpenBible.info, links the official source and CC BY 4.0 license, preserves the source
notice, identifies the exact snapshot, and indicates Project Echoes transformations. This
determination does not relicense ESV text, biblical editions, TSK editions, or other
third-party works.

Project policy is deliberately more conservative than the license permits: raw archive
bytes, extracted source data, the acquisition receipt, normalized benchmark tables, local
Parquet, and DuckDB remain Git-ignored. Trackable outputs are limited to acquisition
instructions, exact hashes, schemas, attribution, aggregate statistics, reference-only
structural reports, and project-authored code and documentation unless a later publication
review authorizes more.

OpenBible is validated only as Tier 3 weak supervision and broad knownness filtering. Its
heterogeneous links are not scholarly ground truth, primary evaluation truth, a sole
positive benchmark, or a basis for Tier 1 promotion. Signed votes are source ranking
metadata, not calibrated confidence or probabilities of literary dependence. Its source
reference scheme and direction are preserved, and any same-label mapping to MACULA verse
passages remains provisional without an independently approved versification crosswalk.

Two complete local builds reproduced benchmark run
`benchmark-v1-dff1d3ef650c8ccd4930`, version
`known-links-v1-dff1d3ef650c`, every logical hash, row count, and content-table
physical hash; strict validation returned zero errors and zero warnings in each
build. This technical validation supports the manifest lifecycle transition but
does not broaden the license determination, publication permission, source role,
or evidentiary claims above.

## UBS reference-only positive-control determination

Review date: 2026-08-08. The governed source is the **UBS Parallel Passage
Database, copyright 2023 United Bible Societies**, at immutable commit
`3a6edd8212df2e1189037ad39687726990c80d56`. Its pinned
[`LICENSE.md`](https://github.com/ubsicap/ubs-open-license/blob/3a6edd8212df2e1189037ad39687726990c80d56/parallel%20passages/LICENSE.md)
applies [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
The exact XML and license hashes are recorded in
[`data/manifests/sources.yaml`](../data/manifests/sources.yaml).

The only UBS-derived artifact activated for `final-discovery-v1` is the
24-row reference-only adaptation governed by
[`data/benchmarks/positive_controls.yaml`](../data/benchmarks/positive_controls.yaml).
Project Echoes selected unordered reference pairs and added project IDs,
conservative relationship labels, verification metadata, leakage groups, and
deterministic splits. It omitted upstream biblical text and UBS word-match
strings. Those omitted fields are inactive as corpus text, detector features,
evidence excerpts, review text, and publication content; the primary
original-language passages still come exclusively from the separately
governed MACULA sources.

The tracked adaptation remains CC BY-SA 4.0. A redistributed copy or further
adaptation must identify the UBS Parallel Passage Database and United Bible
Societies, link the pinned source and CC BY-SA 4.0 license, retain a notice that
Project Echoes modified the material, and license shared adaptations under the
same or a CC-compatible license as the license permits. The required notice is
in `data/benchmarks/POSITIVE_CONTROLS_NOTICE.md`; the machine-readable
attribution and modification statement are in the benchmark manifest. This
ShareAlike boundary attaches to the UBS-derived adaptation and further
adaptations of it. It does not silently relicense independently governed
MACULA text, Project Echoes software, or unrelated outputs merely stored
beside it; any combined public artifact still requires a component-level
publication review.

The full upstream XML, README, and license remain metadata-only/local source
material under project policy and are not committed. Activating biblical text,
word-match strings, additional relationship fields, or a larger systematic
subset would require a new source-purpose, leakage, evidentiary, and
publication review even where CC BY-SA permits reuse.

## Private ephemeral cloud-processing determination

Review date: 2026-07-30. Reviewer: project owner, recorded by Codex under ADR
0017 for the Milestone 7 recovery and later fresh determinism run only.

The four activated third-party inputs used by Milestone 7 all have completed
license review and `machine_processing_status: permitted`. The governed Tier 1
file is project-authored and header-only. For these two runs, the conservative
“local-only” project policy is clarified to include one nonpublic,
owner-controlled ephemeral compute server acting only as a research processor.
This does not approve public redistribution, publication, provider snapshots,
backups, buckets, or a durable cloud corpus.

The source-specific determination is:

- `macula-hebrew`: the pinned CC BY 4.0 aggregate and its recorded component
  notices permit machine processing. Only existing derived database, passage,
  and lexical-recovery artifacts are transferred; the 932 raw acquisition
  files are excluded. Full processed tables remain unapproved for public
  release, and the SDBH limitation is unchanged.
- `macula-greek`: the pinned CC BY 4.0 aggregate permits machine processing.
  Raw acquisition files are excluded. The MARBLE and other permission-only
  component caveats still block public derived-table release; private
  computation does not resolve or broaden that publication question.
- `oshb-morphhb`: the pinned WLC/OSHB layer permits processing and
  redistribution with attribution. Raw OSIS acquisition files are excluded;
  only derived tables, passage artifacts, and the non-textual hash manifest
  needed by the run are transferred.
- `openbible-cross-references`: the exact reference/vote snapshot is CC BY 4.0
  and permits processing. The raw ZIP and extracted TSV are excluded. The
  normalized benchmark inside the private DuckDB remains Tier 3 weak
  supervision and is not publicized by this decision.
- `project-echoes-tier1-quotations`: the transferred file contains only its
  project-authored validated header and no third-party quotation rows.

This is not a metadata-only transfer. The DuckDB, passage Parquet, and lexical
staging contain reconstructable surface and normalized text, lemmas, roots,
semantic domains, word-sense values, English gloss-derived features, and
MACULA Greek LN/LexDomain-derived fields. The determination above is therefore
an explicit artifact assessment of those integrated derived files. It relies
on the completed aggregate-license and machine-processing reviews already
recorded for the exact pinned versions; it does not infer independent rights
in SDBH, MARBLE, or any other component and does not approve publication of
those fields.

The transfer is an explicit file allowlist authenticated by size and SHA-256.
It uses host-key-verified SSH/SFTP and key-only access; server data and logs
have restrictive POSIX permissions; no public service, snapshot, image,
backup, or secondary cloud store is created. The server lifecycle is at most
72 hours per run, after which the owner verifies retrieval and explicitly
deletes the server or records a new authorization before incurring more
retention. Source notices and attribution remain in the transferred manifest
and repository. Credentials, raw acquisitions, unrelated processed outputs,
and secrets are excluded. Any different provider, persistent remote storage,
collaborator access, or public output requires a new review.

## STEPBible activation deferral

[ADR 0012](decisions/0012-defer-stepbible-activation.md) defers STEPBible
activation because MACULA Hebrew and Greek already provide the required
primary linguistic foundation, OSHB provides the required Ketiv/Qere
supplement, generic supplementary-annotation and conflict-preservation
infrastructure exists, and structural-alignment and versification-crosswalk
layers are implemented. No specific downstream capability currently requires
a STEPBible file. Acquisition now would create file-level provenance,
licensing, namespace, and annotation-conflict work without a demonstrated
analytical benefit.

This is a scheduling and evidence decision, not rejection of STEPBible or a
licensing determination. STEPBible remains eligible for future supplementary
use and retains its current `under_review` manifest state. No file is selected,
approved, blocked, acquired, validated, or covered by a completed file-level
review. Later activation requires all five of the following:

1. A specific missing field or capability.
2. The exact STEPBible files required.
3. A measurable benefit.
4. Completed file-level licensing and provenance review.
5. A conflict-preserving integration design.

The seven subset-audit questions remain unresolved:

1. Which exact tagged-text, lexicon, name, semantic, or versification files
   measurably improve the core pipeline, and is each individually cleared?
2. Do any selected files or fields derive from commercial or restricted
   editions, and which upstream restrictions constrain derived exposure?
3. Which versification tables may seed a redistributable crosswalk, is each
   provenance chain compatible, and what attribution does each require?
4. May AI-authored or partially generated descriptions be stored at all, how
   must they be labeled, and how will they remain excluded from primary
   linguistic evidence?
5. What attribution satisfies STEPBible and every named upstream contributor
   for the exact selected files, and where must it appear in derived outputs?
6. Which supplementary-derived columns, if any, may be published when the
   primary corpus tables remain unpublished pending field-level review?
7. Which immutable commit should be pinned, and do selected-file changelogs
   contain corrections that justify a different snapshot?

## Septuagint edition and component gate

Before any Septuagint acquisition, the project must select an exact edition and separately determine:

1. copyright status of the printed edition;
2. license of the electronic transcription;
3. license of morphology or other linguistic annotation;
4. license of Hebrew–Greek alignment data;
5. permission to redistribute raw text;
6. permission to redistribute each proposed derived output; and
7. required attribution and notice language for every component.

No blanket conclusion may be inferred across layers. Swete's printed edition may be public domain, while a particular electronic transcription can still have separate terms that require review. Rahlfs-Hanhart is a copyrighted modern edition. CATSS text, morphology, parallel data, alignment material, and related modules may carry different agreements and must be evaluated individually. The eventual decision must identify edition-specific references, versions, access dates, component provenance, publication consequences, and an ADR before acquisition.

### `final-discovery-v1` LXX deferral determination

[ADR 0019](decisions/0019-defer-lxx-and-govern-multilingual-e5.md) completes
the campaign-specific review and defers LXX activation without blocking
`final-discovery-v1`. No LXX source was acquired, registered as active,
processed, aligned, or copied into the repository.

The preferred future raw-text candidate is the Swete TEI transcription in
[OpenGreekAndLatin/First1KGreek at immutable commit
`bfea9acd07ee1b7cea70cdd927c8f092d5637695`](https://github.com/OpenGreekAndLatin/First1KGreek/tree/bfea9acd07ee1b7cea70cdd927c8f092d5637695).
The relevant files follow
`data/tlg0527/**/tlg0527.*.1st1K-grc1.xml`; any acquisition would use an
explicit reviewed 39-book project-canon allowlist rather than the repository
as a whole. The
TEI bibliographic headers identify Swete's 1896, 1901, and 1905 printed
volumes, treated as public domain in the United States. The independent
electronic transcription and encoding are
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) under the
[pinned repository license](https://github.com/OpenGreekAndLatin/First1KGreek/blob/bfea9acd07ee1b7cea70cdd927c8f092d5637695/license.md)
and file-level notices.

That license permits raw copying and adaptation subject to its conditions; it
does not erase the project's publication review. A redistributed copy must
identify the creators and source, link the material and license, preserve the
notice, state modifications, and apply ShareAlike where required. A public
normalized, tokenized, aligned, indexed, or mixed-source derivative requires a
new determination of adaptation and database obligations before release. The
candidate currently lacks a validated full-canon lemma/morphology layer and a
validated Hebrew alignment; its OCR/encoding, markup, edition identity,
tokenization, book coverage, and versification also require QA.

[Open Scriptures GreekResources at commit
`dd5a2fd530ab3c6b748c174cec38966c356d8111`](https://github.com/openscriptures/GreekResources/tree/dd5a2fd530ab3c6b748c174cec38966c356d8111)
is a possible future CC BY 4.0 lemma resource. Its own
[lemma documentation](https://github.com/openscriptures/GreekResources/blob/dd5a2fd530ab3c6b748c174cec38966c356d8111/LxxLemmas/readme.md)
ties record ordering to CCAT `lxxmorph`. Because that is a CATSS/Rahlfs rather
than Swete lineage, no positional join is permitted without a validated
cross-edition token and versification mapping.

CATSS/CCAT and Rahlfs-derived activation are rejected for this campaign. The
[CATSS description](https://ccat.sas.upenn.edu/rak/catss.html) and
[component user declaration](https://ccat.sas.upenn.edu/gopher/text/religion/biblical/lxxmorph/0-user-declaration.txt)
do not establish a clean open redistribution boundary for every text,
morphology, parallel, and alignment component, and they do not match the Swete
candidate edition. Rahlfs-Hanhart is a modern copyrighted critical edition and
is not substituted. This is a campaign deferral, not a claim that every lawful
private use of CATSS is impossible.

[UD Ancient Greek PTNK at commit
`818fb315ff1f6cd95b6e7fa90f3707488d2b010d`](https://github.com/UniversalDependencies/UD_Ancient_Greek-PTNK/tree/818fb315ff1f6cd95b6e7fa90f3707488d2b010d)
is CC BY-SA 4.0, but its Codex Alexandrinus material covers only Genesis and
Ruth. It is eligible only as a bounded future adapter/alignment QA sample, not
as the campaign's full bridge corpus.

### Optional `multilingual-e5-small` model determination

The optional semantic baseline is
[`intfloat/multilingual-e5-small` revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3),
whose [pinned model card](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)
declares the MIT license. The closed allowlist and SHA-256 values are recorded
verbatim in
[`config/experiments/final-discovery-v1.yaml`](../config/experiments/final-discovery-v1.yaml)
and ADR 0019. It consists only of the SentenceTransformers module and pooling
configuration, XLM-R model/tokenizer configuration, SentencePiece/tokenizer
assets, and `model.safetensors`; alternate ONNX, OpenVINO, mutable-branch, or
hosted-endpoint representations are not approved substitutes.

The three large binary identities are `model.safetensors`
`1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477`,
`sentencepiece.bpe.model`
`cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865`,
and `tokenizer.json`
`0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39`.
Every configuration hash is likewise mandatory; authentic weights with drifted
pooling, prefixing, maximum length, or tokenizer configuration do not
reproduce the preregistered model.

No model weights or tokenizer assets were downloaded during this review. If
later acquired for the authorized production preparation, they remain
Git-ignored, must match the complete allowed-file inventory and hashes, and
must retain the MIT notice. The model is supplemental retrieval evidence only,
not philological proof. Ancient Greek and Biblical Hebrew validity is not
established by its multilingual benchmark results, and broad web pretraining
creates possible, unquantified exposure to biblical text, translations,
commentary, and benchmark relationships. Reports must disclose that exposure;
cosine similarity cannot independently establish Tier A eligibility, and
English-derived embeddings remain separately labeled and ablated.

## Preliminary status table

| Source ID | License review | License/terms recorded | Redistribution | Machine processing | Raw Git policy | Lifecycle |
|---|---|---|---|---|---|---|
| `macula-hebrew` | Complete for 25.08.11 | Composite notices reviewed; CC BY 4.0 aggregate, public-domain/unrestricted WLC, and named component terms | Acquisition instructions only by project policy | Permitted | Ignored local only | Validated |
| `macula-greek` | Complete for 24.06.17 | CC BY 4.0 aggregate and pinned component notices reviewed; permission-only derived-output caveat retained | Acquisition instructions only by project policy | Permitted | Ignored local only | Validated |
| `oshb-morphhb` | Complete for commit `3d15126` | CC BY 4.0 lemma/morphology data; public-domain WLC text; exact attribution recorded | Permitted with attribution, subject to project publication review | Permitted | Ignored local only | Validated |
| `stepbible-data` | In progress; activation deferred by ADR 0012 | CC BY 4.0 repository statement only; seven selected-file questions remain unresolved | Acquisition instructions only pending subset audit | Permitted at repository-statement level; no file activated | Ignored local only | Under review; not approved, blocked, acquired, or validated |
| `septuagint-catss` | In progress; campaign suitability review concluded | Component-specific CCAT/CATSS user declaration; Rahlfs lineage does not match the preferred Swete candidate | Acquisition instructions only | Restricted | Ignored local only | Blocked and deferred for `final-discovery-v1` |
| `openbible-cross-references` | Complete for exact 2026-07-12 snapshot | CC BY 4.0 official page and internal notice; archive contains reference/vote data only; ESV quotations excluded | Permitted with attribution; project keeps raw and normalized data local | Permitted | Ignored local only | Validated for Tier 3; same-label mappings remain provisional |
| `project-echoes-tier1-quotations` | Complete for project-authored metadata | CC BY 4.0; third-party rights remain separate | Permitted with attribution | Permitted | Trackable | Planned, header only |
| `ubs-parallel-passages` | Complete for commit `3a6edd8212df` | CC BY-SA 4.0 dedicated data license; exact attribution and modification notice recorded | Reference-only adaptation permitted with attribution/ShareAlike; omitted fields inactive | Permitted for the bounded reference-only role | Metadata only by project policy | Approved; 24-row adaptation active for `final-discovery-v1` |
| `etcbc-dead-sea-scrolls` | In progress | MIT repository license; upstream transcription scope unresolved | Unknown | Permitted | Ignored local only | Under review |
| `hebrew-critical-apparatus` | Not started | Proprietary; publisher rights page recorded | Prohibited absent permission | Unknown | Prohibited | Planned |
| `greek-critical-apparatus` | Not started | Proprietary; publisher rights page recorded | Prohibited absent permission | Unknown | Prohibited | Planned |
| `targum-corpus` | Not started | No general bulk-reuse license found | Unknown | Unknown | Prohibited | Planned |

These are operational classifications as of the review date. The pinned MACULA
Hebrew, MACULA Greek, OSHB, and exact OpenBible snapshots are acquired and
validated for their approved local roles and for the narrow private ephemeral
Milestone 7 processing boundary above. OpenBible validation authorizes only
Tier 3 acquisition, processing, weak supervision, and broad knownness
filtering under the conservative publication boundary above. The bounded UBS
reference-only adaptation is active for the final campaign under the exact
CC BY-SA boundary above; upstream biblical text, word-match strings, and
additional UBS fields remain inactive. The future Project Echoes-authored
Tier 1 file is still a header-only schema with no curated evidence.
Source-specific unresolved questions and publication boundaries, including the
MACULA Greek permission-only derived-output question, are preserved in the
machine-readable manifest.
