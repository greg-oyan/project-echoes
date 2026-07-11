# Project Echoes research charter

Status: **Accepted for Milestone 1 governance**
Date: 2026-07-10

This charter fixes the project's research boundaries and evidentiary standards before corpus acquisition or exploratory results can influence them. The [master plan](master-plan.md) remains the governing specification; this charter operationalizes its research commitments.

## Purpose

Project Echoes is a reproducible computational biblical-studies research program. Its purpose is to analyze linguistically annotated original-language biblical texts at token and passage level, recover established relationships as validation, and generate traceable candidate lexical, semantic, grammatical, structural, narrative, or intertextual relationships for disciplined human investigation.

The project is not a Bible chatbot, devotional or sermon generator, theological authority, authorship oracle, or generic verse-similarity product. Computation ranks evidence for review; it does not settle historical intention or interpretation.

## Research questions

### Primary question

> Can an undirected computational analysis of every token in the Hebrew Bible and Greek New Testament identify strong lexical, semantic, grammatical, structural, narrative, or intertextual relationships that are absent from major cross-reference collections and underdocumented in accessible scholarship?

### Secondary questions

1. Which transparent lexical and phrase methods recover held-out established relationships, and which relationship classes do they miss?
2. Which candidate pairs receive support from genuinely independent detector families rather than correlated variants of one similarity signal?
3. How much value do original-language semantic, syntactic, participant, narrative, structural, and anomaly features add beyond lexical baselines?
4. Which apparent relationships are explained by common vocabulary, formula, genre, adjacency, passage length, translation, annotation, or chance?
5. Which New Testament relationships become stronger or weaker when Septuagint wording is introduced as a controlled bridge to the Hebrew text?
6. How well do existing reference collections cover different computationally detectable relationship types?
7. Can a blinded and persistent review process distinguish known links, hard negatives, data artifacts, and new candidates without preferential treatment?
8. Which methods fail, and what do their false positives and false negatives reveal about computational biblical intertextuality?

## Corpus policy

### Primary discovery corpus

The initial discovery boundary is the 66-book Protestant canon: the Hebrew and Aramaic Old Testament and the Greek New Testament. MACULA Hebrew and MACULA Greek are the intended primary annotated sources, subject to edition verification, component-level provenance review, licensing review, pinned versions, reproducible acquisition, and corpus validation.

The boundary is a scope decision for a first reproducible experiment, not a theological judgment about other canons. Original-language evidence is primary. English may support reading, glossing, baselines, or optional features, but English similarity alone cannot support a candidate.

### English-feature ablation

Any candidate whose supporting evidence includes English translations, English glosses, or any other English-derived feature must survive a registered ablation that removes every English-derived feature before it may retain the label **strong candidate**. The ablation records the candidate score before and after removal, the original-language evidence that remains, whether review eligibility survives, and whether the relationship classification changes. English may assist discovery or interpretation, but it cannot conceal the absence of original-language support.

### Septuagint bridge corpus

The Septuagint is a later bridge layer, not an initial independent discovery target. It may be activated only after the Hebrew and Greek primary pipelines pass their quality gates and transparent known-link recovery demonstrates value. Its role is direct Greek comparison, Hebrew–Greek–New Testament triangulation, translation-sensitive analysis, and testing whether a relationship is stronger in Greek tradition than in the surviving Hebrew text.

### Supplementary annotation layers

STEPBible and other approved resources may add glosses, lexical mappings, semantic information, names, morphology comparisons, dictionary identifiers, and versification evidence. They remain source-specific parallel annotations. A disagreement never silently overwrites the primary source; both values and their provenance remain queryable.

### Deferred textual-validation layers

Biblical Dead Sea Scrolls, textual-variant datasets, critical apparatuses, and alternative witnesses may later test the stability and history of wording that supports an existing candidate. They do not independently prove intertextuality. Proprietary apparatus material remains restricted unless explicit machine-processing and publication rights are established.

### Deferred reception-history layers

Targums, non-biblical Dead Sea Scrolls, deuterocanonical literature, pseudepigrapha, rabbinic literature, Church Fathers, and later commentary traditions are excluded from initial candidate generation. If activated later, they address reception: whether an interpreter recognized, transmitted, or developed a relationship. Reception evidence is not direct proof of original authorial dependence.

### Pauline chronology and mediation

The Pauline letters predate the written canonical Gospels. A Paul–Jesus relationship therefore cannot automatically be described as Paul drawing from a written Gospel text. It must initially be framed as a possible relationship to Jesus sayings traditions, shared early Christian traditions, common scriptural sources, Septuagint wording, Hebrew scriptural wording, or another demonstrated form of mediation. A claim of direct dependence on a written Gospel requires separate historical evidence.

Review-rubric question 6 is:

> Is the proposed direction of dependence chronologically possible, and does the evidence support a written-text relationship, an oral sayings tradition, a shared scriptural source, or another form of mediation?

## Candidate relationship taxonomy

Every reviewed pair receives one of these classifications:

1. **Direct quotation** — substantial wording is reused, normally with identifiable source language or quotation framing.
2. **Probable literary allusion** — distinctive wording, order, syntax, imagery, or structure strongly suggests textual interaction.
3. **Possible literary echo** — several meaningful features correspond, but direct literary dependence remains uncertain.
4. **Narrative or structural parallel** — event sequence, role configuration, or literary structure corresponds without substantial verbal reuse.
5. **Thematic relationship** — concepts correspond but direct textual interaction has limited support.
6. **Formal coincidence** — common vocabulary, grammar, genre, formula, adjacency, or chance adequately explains the match.
7. **Data artifact** — tokenization, annotation, alignment, translation, versification, or implementation error produces the match.

Classification describes the current evidence; it is revisable and is not a probability of authorial intention.

## Definitions

### Computational candidate

A candidate is a passage pair or structured multi-passage relationship emitted by a documented algorithm from pinned inputs and configuration, with stable identifiers, raw detector scores, directly inspectable feature evidence, generation run, data-quality state, and known-link exposure. It is an item for investigation, not a finding.

### Textual evidence

Textual evidence is a traceable correspondence in source tokens or derived annotations: rare lemmas or roots, ordered phrases, morphology, syntax, predicate–argument roles, entities, semantic domains, event sequences, or structure. Its value depends on frequency, distinctiveness, context, source quality, alternative matches, genre, passage length, translation effects, and textual stability. A scalar similarity score without inspectable evidence is insufficient.

### Knownness

Knownness records whether a relationship appears in explicitly named, versioned, and dated machine-readable references, curated intertextual resources, or documented scholarship searches. It is source-relative and search-relative. The labels are:

- **K0 — widely documented** in broad reference collections.
- **K1 — documented in specialist scholarship**.
- **K2 — related idea documented**, but the exact textual relationship is not established.
- **K3 — no match found in checked sources**.
- **K4 — search incomplete**.

### Novelty status

Novelty is a human-reviewed research status, never a detector output. A candidate may be described only as known, partially documented, not found in specified checked sources, or not yet adequately searched. **K3 does not mean “never discovered.”** Universal novelty claims require evidence beyond the project's accessible search process and are not an automated project output.

## Evidence and evaluation principles

1. Transparent baselines precede complex models.
2. Training, tuning, evaluation, and novelty-filter collections remain separated and versioned.
3. Held-out known relationships, hard negatives, generic thematic similarities, and deliberate artifacts are evaluated with the same rubric.
4. Multiple feature transformations from one token representation are not automatically independent detectors.
5. Evaluation reports retrieval metrics, class-specific errors, calibration, passage-length and genre effects, and exact data splits—not only top examples.
6. Candidate importance requires identifiable evidence and preferably agreement across independent families.
7. Common vocabulary, formulaic language, adjacency, book, genre, passage length, and alternate source passages are controlled.
8. Original-language evidence is checked manually before serious presentation.
9. Accepted, rejected, and artifact classifications remain in a persistent, auditable ledger.
10. Blind review is used before claims about new candidates are compared with known or negative examples.
11. A corpus-specific contrastive encoder is optional stretch work, not a critical-path requirement. Milestone 10 must remain completable without training a custom encoder.

## Permitted claims

The project may report that a relationship was detected computationally; is unusual under a specified model; shares specified rare textual, grammatical, semantic, narrative, or structural features; was absent from explicitly listed sources checked on stated dates; recovers or extends a published method; or merits further expert investigation. Results must be described as tentative where evidence or search coverage is incomplete.

## Prohibited claims

The system may not automatically claim that an author intentionally quoted another source, had direct access to a particular document, proves theological unity or separate authorship, expresses divine intention, contains an interpolation, or presents a relationship never noticed by any person. Semantic similarity does not prove dependence; an anomaly does not prove redaction; textual variants and reception evidence do not independently prove intertextuality.

## LLM-use restrictions

An LLM is not a primary discovery engine, novelty authority, translator of record, or final classifier. It may receive a bounded evidence package only after deterministic candidate generation and may explain supplied evidence, generate counterarguments, suggest searches, compare classifications, or help draft a dossier. Every observation must cite the supplied package. Prompts, responses, provider, model/version, date, cost, and limitations are recorded. The pipeline must remain runnable without a paid LLM API.

## Reproducibility requirements

Every activated source has a manifest, pinned version or commit, acquisition date, expected-file inventory, checksums, license state, raw-data policy, adapter, and limitations. Every experiment preserves configuration and input hashes, Git and lockfile state, random seeds, models and versions, hardware, runtime, warnings, errors, training lineage, evaluation splits, output hashes, and human-review history. Source forms are never overwritten, and every processed token traces to its source row.

## Dataset activation rule

A dataset may be activated only when all nine conditions are documented:

1. Defined research purpose and layer role.
2. Provenance and edition.
3. Licensing, attribution, machine-processing, redistribution, and Git policy.
4. Pinned version or commit and acquisition date.
5. Reproducible, non-overwriting acquisition with file checksums.
6. Alignment plan for the core corpus and versification.
7. Corpus-quality validation.
8. Evidence that the source improves retrieval, interpretation, or validation.
9. Explicit derived-output publication decision.

`planned`, `under_review`, and `blocked` records are not active. Technical availability alone never satisfies this rule.

## Stop rules

Work stops at the active milestone gate if quality checks or acceptance criteria fail. The project does not acquire a source before governance approval; activate the Septuagint before primary and benchmark gates; add large secondary corpora before core validation; use English embeddings as sole evidence; treat cosine similarity as discovery; train and evaluate on the same relationships; discard rejected candidates; silently change source editions, annotations, or normalization; tune weights after inspecting attractive examples without a new recorded experiment; publish restricted data; or build a polished public interface before credible research results.

## Methodology change control

1. Durable scope, source, license, schema, normalization, benchmark, scoring, and claim changes require a dated decision record.
2. The change record states context, evidence, alternatives, consequences, affected configurations, and whether earlier runs remain comparable.
3. Configuration and schema versions change when semantics change; source versions never change silently.
4. A method, threshold, or weight changed after result inspection creates a new experiment and run ID. Earlier results remain preserved.
5. Evaluation splits and primary metrics are fixed before tuning. Any post-hoc analysis is labeled exploratory.
6. Licensing determinations may change only through the documented review procedure; prior determinations remain in history.
7. The charter itself may be superseded only through a decision record and owner-approved commit explaining the change.

## Provisional novelty statement

> Project Echoes integrates multiple computational methods to conduct an undirected, whole-corpus search for candidate biblical relationships that are not represented in the reference collections checked by the project.

This is an integration, scale, and workflow statement, not a claim that component methods are new or that no closer project exists. It remains provisional pending continuing literature review. The five closest projects currently identified are compared in [prior-projects.md](prior-projects.md).

## Initial success criteria

The first target is a verified, reproducible token-level Hebrew and Greek corpus that recovers established relationships with transparent lexical evidence. The second is a ranked set of previously unlisted candidates whose evidence can be inspected and reviewed. Longer-term success requires reliable data, reproducible methods, held-out benchmark value, transparent candidate evidence, calibrated human review, a record of failures and rejections, several candidates that survive linguistic and scholarly review, and at least one publishable case study. A rigorous negative result or false-positive taxonomy is a legitimate contribution.
