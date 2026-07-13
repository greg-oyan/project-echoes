# PROJECT ECHOES

## Master Research and Implementation Plan for Codex

## 1. Codex Mission

Build a reproducible computational biblical-studies research repository that analyzes the complete Hebrew and Aramaic Old Testament and Greek New Testament at token level to identify candidate lexical, semantic, grammatical, structural, narrative, and intertextual relationships.

The project is not a commercial product, Bible chatbot, devotional application, sermon generator, or generic semantic-search interface.

The purpose is to conduct rigorous computational analysis that can surface relationships and anomalies that may be difficult or impossible to identify manually at whole-corpus scale.

The final system must:

1. Ingest and normalize linguistically annotated original-language biblical corpora.
2. Preserve every token and its provenance.
3. Represent biblical passages at multiple levels of granularity.
4. Recover known biblical relationships as a validation benchmark.
5. Generate new candidate relationships through several independent computational methods.
6. distinguish strong textual evidence from generic thematic similarity.
7. Filter candidates against existing cross-reference and research collections.
8. Support methodical human investigation.
9. Record accepted and rejected candidates.
10. Produce reproducible datasets, visualizations, research dossiers, and publishable analysis.

The central research question is:

> Can an undirected computational analysis of every token in the Hebrew Bible and Greek New Testament identify strong lexical, semantic, grammatical, structural, narrative, or intertextual relationships that are absent from major cross-reference collections and underdocumented in accessible scholarship?

The system must generate candidate discoveries. It must not claim to prove authorial intent, theological meaning, literary dependence, or universal scholarly novelty.

---

# 2. Codex Operating Instructions

Codex must treat this project as a staged research program.

This document is the sole governing implementation specification for Project Echoes. Amend requirements within the existing milestone numbers rather than creating a competing plan or renumbering milestones. A requirement added to a future milestone changes that milestone's specification; it does not authorize early implementation before the current milestone and acceptance gate are complete.

## 2.1 General execution rules

Codex must:

* Work milestone by milestone.
* Complete and validate each milestone before proceeding.
* Keep the repository runnable after every milestone.
* Write tests alongside implementation.
* Record assumptions in documentation.
* Pin all dependencies and source-data versions.
* Prefer transparent methods before complex machine-learning methods.
* Preserve intermediate outputs.
* Make every generated candidate traceable to its source data and algorithm.
* Separate exploratory notebooks from production code.
* Use configuration files rather than hard-coded experiment settings.
* Produce deterministic results where technically possible.
* Record random seeds wherever stochastic methods are used.
* Record failures, rejected approaches, and unresolved data problems.

Codex must not:

* Build a polished public-facing product.
* Build authentication, payments, accounts, or SaaS infrastructure.
* use an LLM as the primary discovery engine.
* declare relationships novel based on model output.
* treat cosine similarity as sufficient evidence.
* silently alter corpus normalization.
* silently replace one textual edition with another.
* combine datasets without documenting provenance and licensing.
* make theological conclusions automatically.
* remove rejected candidates from the research record.
* optimize prematurely for cloud deployment.
* add additional ancient corpora before the core pipeline passes its validation gates.
* claim that “no one has ever seen” a relationship.

## 2.2 Coding workflow

For each milestone, Codex must:

1. Read the current research charter and relevant configuration files.
2. Inspect the existing repository before changing code.
3. Implement the smallest complete version of the milestone.
4. Add unit tests and integration tests.
5. Run formatting, linting, type checking, and tests.
6. Generate the milestone’s required artifacts.
7. Update the changelog and methodology documentation.
8. Record unresolved issues.
9. Stop at the milestone gate if acceptance criteria are not satisfied.

## 2.3 Required quality commands

Use equivalent commands if the final tooling differs, but the repository should support:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run echoes validate-corpus
uv run echoes validate-config
```

Each experiment should also support a command such as:

```bash
uv run echoes run-experiment --config config/experiments/<experiment>.yaml
```

---

# 3. Research Boundaries

## 3.1 Primary discovery corpus

The primary discovery target is the 66-book Protestant canon:

* Hebrew and Aramaic Old Testament
* Greek New Testament

Use MACULA linguistic datasets as the initial primary source for token-level morphology, syntax, semantic information, participant references, and related annotations where available.

The core analysis must remain grounded in the original-language texts.

English translations may be used only as:

* Human-readable reference text
* Supplemental glossing
* A comparison baseline
* An optional semantic feature source

English translation similarity must never be the sole evidence supporting a candidate relationship.

Any candidate whose supporting evidence includes English translations, English glosses, or other English-derived features must survive a registered ablation that removes all English-derived features before the candidate may retain the label `strong candidate`. The ablation must record:

* Candidate score before removal
* Candidate score after removal
* Remaining original-language evidence
* Whether review eligibility survives
* Whether the relationship classification changes

## 3.2 Greek bridge corpus

The Septuagint must be added after the primary Hebrew and Greek pipelines pass corpus-quality and known-link-recovery gates.

The Septuagint is a bridge corpus, not initially a separate primary discovery target.

It will support:

* Direct Greek Old Testament–Greek New Testament comparison
* Identification of New Testament language that appears to follow Greek Old Testament wording
* Hebrew–Greek–New Testament triangulation
* Cross-language lexical mappings
* Improved analysis of quotations, allusions, and semantic echoes
* Evaluation of whether a relationship is stronger in the Greek textual tradition than in the surviving Hebrew text

Before acquisition or activation, the Septuagint source must receive a separate edition-selection and licensing decision. That decision must evaluate separately:

1. Copyright status of the printed edition
2. License of the electronic transcription
3. License of morphology or linguistic annotation
4. License of Hebrew-Greek alignment data
5. Raw-text redistribution
6. Derived-output redistribution
7. Required attribution

The review must not assume that related resources share one license. In particular:

* Swete's printed edition is public domain, but each electronic transcription still requires separate review.
* Rahlfs-Hanhart is a copyrighted modern edition.
* CATSS text, morphology, parallel data, and related modules may have different terms and must be verified individually rather than assigned one blanket license.

The eventual source decision and redistribution consequences must be recorded in `docs/data-licensing.md` and an ADR. Before activation, the selected Septuagint source must also receive a technical review covering:

* Provenance
* Textual edition
* Licensing
* Redistribution rights
* Morphological annotation quality
* Tokenization
* Versification
* Alignment with the Hebrew text
* Alignment with New Testament references

If redistribution rights are unclear, keep the raw data outside the public repository and provide acquisition instructions.

Version 1 aligns the Hebrew and Septuagint corpora at passage or verse level through the separate Milestone 4 versification-crosswalk layer, supplemented by statistical lemma-level alignment with explicit confidence scores. Token-level Hebrew-Septuagint alignment is out of scope for version 1.

## 3.3 Supplementary annotation layers

STEPBible and comparable datasets may be evaluated as future supplementary
sources. If activated under Section 3.6 after the required licensing and
provenance review, they may supplement the primary corpus with:

* English glosses
* Lexical information
* Semantic-domain annotations
* Morphological comparison
* Hebrew and Greek lexical mappings
* Proper-name information
* Participant and entity resolution
* Versification crosswalks
* Dictionary identifiers
* Strong’s or other reference identifiers where useful

These resources enrich analysis but do not automatically constitute independent textual witnesses.

Conflicts between annotations must be preserved and documented rather than silently reconciled.

STEPBible activation is deferred under ADR 0012 and is not required to close
Milestone 4. This deferral is neither a rejection of STEPBible nor a licensing
determination. A later milestone may activate an exact, approved subset only
after it identifies a specific missing field or capability, names the exact
files required, demonstrates a measurable benefit, completes file-level
licensing and provenance review, and defines a conflict-preserving integration
design. Until then, STEPBible remains optional future supplementary work and
its unresolved file-level licensing questions remain open.

## 3.4 Later textual-validation layers

The following may be added after strong candidates exist:

* Biblical Dead Sea Scrolls
* Accessible textual-variant datasets
* Critical apparatus information
* Alternative ancient biblical witnesses

Their purpose is to test whether the wording supporting a candidate:

* Appears in early textual witnesses
* Changes across manuscript traditions
* Depends on a disputed reading
* Remains stable enough to sustain the proposed relationship
* Represents a later textual development

These sources do not independently prove an intertextual relationship. They test the textual stability and history of the evidence.

Commercial critical editions and apparatuses must be treated as licensed research sources unless explicit machine-processing and redistribution rights are established.

## 3.5 Later reception-history layers

The following are excluded from initial candidate generation:

* Targums
* Non-biblical Dead Sea Scrolls
* Deuterocanonical books
* Pseudepigrapha
* Rabbinic literature
* Church Fathers
* Patristic commentaries
* Medieval commentary traditions
* Modern commentaries
* Modern translations as primary evidence

These may later be used to ask whether ancient or later interpreters:

* Recognized a proposed relationship
* Developed the relationship
* Transmitted a shared interpretation
* Connected two passages in reception history

A relationship identified in a Targum, commentary, or patristic source must be classified as reception-history evidence rather than direct evidence of original authorial dependence.

## 3.6 Activation rule for new datasets

No dataset may be activated merely because it is available.

Each new source requires:

1. A defined research purpose
2. Documented provenance
3. Documented licensing
4. A pinned version or commit
5. A reproducible ingestion process
6. Alignment with the core corpus
7. Corpus-quality validation
8. Evidence that the source improves retrieval, interpretation, or validation
9. A documented decision about whether derived outputs may be published

---

# 4. Research Claims and Terminology

The project must use calibrated language.

## 4.1 Permitted claims

The project may claim that:

* A relationship was detected computationally.
* A relationship is statistically unusual under a specified model.
* Two passages share rare lexical, grammatical, semantic, or structural features.
* A relationship was not found in the explicitly listed sources searched.
* A candidate merits further scholarly investigation.
* A result reproduces or extends known computational methods.
* A finding remains tentative.

## 4.2 Prohibited claims without additional evidence

The project must not automatically claim that:

* One biblical author intentionally quoted another.
* One author had direct access to a particular written source.
* A relationship proves theological unity.
* A relationship proves separate authorship.
* A relationship is divinely intended.
* A relationship has never been seen by any person.
* A linguistic anomaly proves interpolation or redaction.
* Semantic similarity proves literary dependence.

## 4.3 Candidate relationship taxonomy

Every reviewed relationship must be assigned one of the following classifications:

### Direct quotation

Substantial wording is reused, normally with identifiable source language or explicit quotation framing.

### Probable literary allusion

Distinctive words, order, syntax, imagery, or structure strongly suggest textual interaction.

### Possible literary echo

Several meaningful features correspond, but direct literary dependence remains uncertain.

### Narrative or structural parallel

Passages share a sequence, structure, event pattern, or role configuration without substantial verbal reuse.

### Thematic relationship

Passages address similar concepts but provide limited evidence of direct textual interaction.

### Formal coincidence

The apparent relationship is adequately explained by common vocabulary, grammar, genre, formula, or chance.

### Data artifact

The relationship results from tokenization, annotation, alignment, translation, or implementation error.

---

# 5. Core Methodological Principle

The system must not simply embed every verse and rank cosine similarity.

The central methodology is:

> A candidate becomes important when multiple independent methods detect it, the evidence can be identified directly in the text, and existing reference collections do not already adequately explain it.

The pipeline is:

```text
Original-language sources
→ source manifests
→ token-level normalized corpus
→ aligned supplementary layers
→ multi-scale passage representations
→ independent candidate-generation engines
→ benchmark validation
→ candidate ensemble
→ surprise and knownness scoring
→ manual investigation
→ research dossiers
→ publication outputs
```

The large language model is used only after candidate generation and evidence retrieval.

---

# 6. Repository Architecture

Create the repository as follows:

```text
project-echoes/
├── README.md
├── LICENSE
├── CITATION.cff
├── CHANGELOG.md
├── CONTRIBUTING.md
├── pyproject.toml
├── uv.lock
├── Makefile
├── .gitignore
├── .env.example
├── config/
│   ├── corpora.yaml
│   ├── normalization.yaml
│   ├── segmentation.yaml
│   ├── scoring.yaml
│   ├── review.yaml
│   ├── models.yaml
│   └── experiments/
│       ├── lexical_baseline.yaml
│       ├── known_link_recovery.yaml
│       ├── semantic_baseline.yaml
│       ├── cross_testament.yaml
│       ├── pauline_case_study.yaml
│       └── whole_canon.yaml
├── data/
│   ├── raw/
│   ├── external/
│   ├── interim/
│   ├── processed/
│   ├── benchmarks/
│   ├── manifests/
│   ├── alignments/
│   └── review/
├── docs/
│   ├── research-charter.md
│   ├── methodology.md
│   ├── corpus-scope.md
│   ├── data-sources.md
│   ├── data-licensing.md
│   ├── normalization.md
│   ├── segmentation.md
│   ├── benchmark-design.md
│   ├── scoring.md
│   ├── novelty-review.md
│   ├── limitations.md
│   ├── experiment-log.md
│   └── decisions/
├── src/
│   └── echoes/
│       ├── __init__.py
│       ├── cli.py
│       ├── settings.py
│       ├── logging.py
│       ├── ingest/
│       ├── normalize/
│       ├── align/
│       ├── segment/
│       ├── features/
│       ├── retrieval/
│       ├── benchmarks/
│       ├── scoring/
│       ├── novelty/
│       ├── review/
│       ├── experiments/
│       ├── reports/
│       └── visualization/
├── notebooks/
│   ├── exploratory/
│   └── published/
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── regression/
├── outputs/
│   ├── experiments/
│   ├── candidates/
│   ├── dossiers/
│   ├── figures/
│   ├── tables/
│   └── publications/
└── app/
    └── review_console/
```

The `data/raw` and restricted external-source directories must be gitignored where licensing requires.

---

# 7. Technology Stack

Use:

* Python 3.12
* `uv` for environment and dependency management
* DuckDB for analytical storage and SQL
* Parquet for processed tables
* Polars as the primary dataframe engine
* pandas only where required by external libraries
* NumPy
* SciPy
* scikit-learn
* PyArrow
* Pydantic for schemas and validation
* Typer for command-line interfaces
* Sentence Transformers for embedding experiments
* FAISS or an equivalent nearest-neighbor index only after baseline validation
* NetworkX or igraph for graph analysis
* Plotly for interactive research visualizations
* Matplotlib for static publication figures
* Streamlit only for the local review console
* pytest
* Ruff
* mypy
* pre-commit
* structured logging

Do not introduce distributed systems, Kubernetes, cloud databases, or microservices.

The biblical corpus is small enough to analyze locally.

---

# 8. Reproducibility Requirements

Every experiment must produce a run manifest containing:

```text
run_id
experiment_name
timestamp
git_commit
working_tree_status
python_version
dependency_lock_hash
config_hash
dataset_manifest_hash
dataset_versions
random_seed
model_names
model_versions
input_table_hashes
output_table_hashes
runtime
hardware_summary
warnings
errors
```

The project must also preserve:

* Source file checksums
* Processed table checksums
* Normalization configuration
* Segmentation configuration
* Model configuration
* Scoring configuration
* Training data lineage
* Evaluation splits
* Exact candidate-generation method
* Human-review history

A command should reproduce an experiment from configuration:

```bash
uv run echoes reproduce <run_id>
```

If exact reproduction is impossible because of an external API or nondeterministic hardware, the limitation must be recorded.

---

# 9. Core Data Model

## 9.1 Source manifest table

```text
source_id
source_name
corpus
edition
repository_or_location
version_or_commit
download_date
license
redistribution_status
file_path
file_hash
ingest_adapter
notes
```

## 9.2 Token table

Every token receives a stable project identifier.

```text
token_id
corpus
source_id
source_token_id
source_record_identity
source_edition_book_id
source_edition_chapter
source_edition_verse
source_edition_verse_id
source_position_in_verse
source_position_in_word
book
book_order
chapter
verse
subverse
sentence_id
clause_id
phrase_id
paragraph_id
position_in_verse
position_in_clause
position_in_corpus
surface_form
normalized_form
unpointed_form
lemma
lexical_root
part_of_speech
morphology_json
syntactic_function
syntactic_head_token_id
semantic_domain
word_sense
participant_id
speaker_id
entity_id
english_gloss
language
is_punctuation
is_variant
variant_type
variant_group_id
is_default_reading
source_row_reference
```

Every processed token must trace back to the original source row.

Canonical token identity must derive only from the source edition's own book identifier, chapter, verse, source token or subtoken position, and, where required to distinguish variants, source-record identity. Token IDs must never depend on:

* A versification crosswalk
* English versification
* Septuagint alignment
* External canonical mappings
* Any later supplementary dataset

The source edition's own verse identifiers and coordinates must remain preserved separately from all later mappings. Adding, removing, or changing a crosswalk must not change any underlying token ID.

Where the source supplies Ketiv and Qere, retain both readings as separate records. Each record must have its own stable `token_id`, source and normalized forms, provenance, `variant_type`, shared `variant_group_id`, and `is_default_reading` value. `variant_type` is `ketiv`, `qere`, or null. A configuration change must never mutate, delete, merge, or re-identify either preserved record.

Downstream analysis uses a separately derived token stream or view containing only the configured reading and positions such as:

```text
analysis_position_in_verse
analysis_position_in_clause
analysis_position_in_corpus
```

These analysis positions are derived data, not source-edition identity, and must be deterministic for either configured reading.

## 9.3 Passage table

Generate overlapping passage units:

* Clause
* Sentence
* Half-verse where reliable
* Verse
* Two-verse window
* Five-verse window
* Paragraph
* Pericope later

Fields:

```text
passage_id
corpus
granularity
analysis_profile
book
start_reference
end_reference
start_token_id
end_token_id
token_count
clause_count
sentence_count
surface_text
normalized_text
lemma_sequence
root_sequence
part_of_speech_sequence
entity_ids
participant_ids
semantic_domains
predicate_argument_sequence
source_ids
reference_gap
contains_disputed_text
disputed_passage_ids
ketiv_structural_uncertainty
```

## 9.4 Passage-feature table

```text
passage_id
feature_family
feature_name
feature_version
feature_value
feature_metadata_json
run_id
```

## 9.5 Known-relationship table

```text
known_relationship_id
passage_a
passage_b
relationship_type
source_collection
source_reference
confidence
directionality
notes
is_training_eligible
is_evaluation_eligible
```

## 9.6 Candidate relationship table

```text
candidate_id
passage_a
passage_b
generation_method
generation_run_id
lexical_score
rare_lemma_score
phrase_score
semantic_score
syntax_score
entity_score
narrative_score
structural_score
anomaly_score
detector_agreement_score
evidence_strength
surprise_score
knownness_score
ensemble_score
candidate_type
training_exposure_status
data_quality_status
disputed_passage_flag
disputed_passage_ids
disputed_text_exclusion_status
textual_criticism_review_status
created_at
```

## 9.7 Candidate evidence table

```text
evidence_id
candidate_id
evidence_type
token_ids_a
token_ids_b
feature_name
feature_value
corpus_frequency
local_frequency
statistical_measure
expected_cooccurrence_independence
hypergeometric_p_value
null_model_empirical_rate
multiple_testing_adjustment
explanation
run_id
```

`hypergeometric_p_value` is a simple independence baseline, not a calibrated probability of literary dependence. Biblical vocabulary is not independently distributed; book- or genre-conditioned permutation results take precedence for empirical calibration.

## 9.8 Human-review table

```text
review_id
candidate_id
reviewer
review_date
review_status
relationship_class
evidence_strength
novelty_status
directionality
context_support
alternative_explanation
data_artifact_status
scholarship_checked
search_queries_used
review_notes
final_disposition
```

## 9.9 Literature-search table

```text
search_id
candidate_id
database_or_source
search_date
query
filters
results_reviewed
relevant_result_count
relevant_citations
conclusion
reviewer
```

---

# 10. Corpus Normalization Requirements

## 10.1 Preserve original forms

Never overwrite source forms.

Maintain:

* Original surface text
* A minimally normalized representation
* Method-specific normalized representations

## 10.2 Hebrew normalization

Create configurable transformations for:

* Cantillation removal
* Vowel-point removal
* Maqqef handling
* Prefix and suffix segmentation
* Ketiv/Qere preservation
* Final letter handling
* Divine-name handling
* Aramaic identification
* Lemma namespace normalization

Do not normalize final forms or orthographic variants unless the method requires it and the decision is documented.

Lock the Ketiv/Qere policy at ingestion. When the source supplies both readings:

* Preserve Ketiv and Qere as separate stable token records.
* Give each record its own source form, normalized form, provenance, and token ID.
* Link both records with a stable variant-group identifier.
* Never overwrite one reading with the other or delete either reading.

Select only the derived analysis stream through `config/normalization.yaml`:

```yaml
ketiv_qere:
  analysis_reading: qere
```

Supported values are `qere` and `ketiv`; `qere` is the default. Switching the setting must change derived analytical positions and stream membership deterministically without changing an underlying token ID, token count, source form, or normalized form.

## 10.3 Greek normalization

Create configurable transformations for:

* Case folding
* Accent-insensitive form
* Breathing-mark removal
* Punctuation separation
* Elision handling
* Lemma normalization
* Enclitic and clitic handling
* Variant preservation
* Text-edition tracking

## 10.4 Annotation conflicts

Where MACULA and supplementary datasets disagree:

* Preserve both values.
* Record the source of each annotation.
* Create an explicit reconciliation layer only when necessary.
* Never silently choose one source.
* Allow experiments to specify which annotation source they use.

Supplementary annotation-alignment tables store source values beside primary
annotations with their source identity, version, alignment method, confidence,
conflict status, and resolution status. OSHB Ketiv/Qere supplementation must
preserve the OSHB/OSIS source book identifier separately from the canonical
MACULA book code. Neither canonical-book mapping nor a versification crosswalk
may participate in an OSHB token ID.

Ketiv structural mappings are derived, queryable alignment records rather than
source-native structure. They must identify the Ketiv token, the primary
structural anchor tokens, each proposed sentence, clause, and phrase unit, the
alignment method and confidence, and the resolution status. An unresolved
mapping remains explicitly unresolved; it must never be replaced with a
fabricated clause or phrase value.

## 10.5 Versification

Create a versification-crosswalk table.

The crosswalk is introduced as a separate mapping layer in Milestone 4. It may map edition-specific references for comparison, but it must not participate in source-edition token-ID generation or rewrite the source edition's own verse identifiers. Token identity must remain unchanged when crosswalk rows are added, removed, or corrected.

Do not assume:

* Hebrew, Greek, and English editions number all passages identically.
* Septuagint book and chapter divisions match the Masoretic Text.
* Every source uses the same book abbreviations.
* Psalm numbering is consistent.

Every cross-corpus alignment must record the alignment method and confidence.

---

# 11. Phase 0: Research Charter and Literature Review

## Objective

Fix the project’s scope and evaluation standards before exploratory results can bias the methodology.

## Tasks

Create `docs/research-charter.md` containing:

* Primary research question
* Secondary research questions
* Included corpora
* Excluded corpora
* Relationship taxonomy
* Definition of candidate
* Definition of evidence
* Definition of knownness
* Definition of novelty status
* Evaluation metrics
* LLM-use restrictions
* Publication claims
* Stop rules
* Change-control process

The charter must register the English-feature ablation rule: a candidate supported by English translations, glosses, or other English-derived features cannot retain `strong candidate` status unless it remains eligible after all English-derived features are removed. The recorded ablation must contain the score before removal, score after removal, remaining original-language evidence, whether review eligibility survives, and whether the relationship classification changes.

The charter must also register the chronological guardrail for Pauline work. The Pauline letters predate the written canonical Gospels; therefore, a Paul-Jesus relationship must not automatically be described as Paul drawing from a written Gospel text. Initially evaluate such relationships as possible relationships to:

* Jesus sayings traditions
* Shared early Christian traditions
* Common scriptural sources
* Septuagint wording
* Hebrew scriptural wording
* Other demonstrated mediation

A claim of direct dependence on a written Gospel requires separate historical evidence.

Create a literature matrix with:

```text
citation
year
research field
corpus
languages
phenomenon
textual unit
method
supervised_or_unsupervised
training_data
benchmark
evaluation_method
expert_review
code_available
data_available
claimed_novelty
limitations
relevance_to_project_echoes
```

Cover:

* Biblical quotation detection
* Intertextuality detection
* Semantic retrieval in ancient languages
* Narrative type-scene detection
* Chiasmus detection
* Stylometry
* Authorship analysis
* Hebrew–Greek alignment
* Septuagint studies
* Translation effects
* Cross-reference graph analysis
* Ancient-language embeddings
* LLM-assisted textual scholarship
* Computational literary studies
* Statistical phrase detection
* Formulaic-language detection

Identify the five closest prior projects and write a comparison explaining:

* What each project analyzes
* What data it uses
* What methods it uses
* Whether it performs directed or undirected discovery
* Whether it searches the whole canon
* Whether it integrates multiple detector families
* Whether it filters against known relationships
* Whether it records rejected findings
* How Project Echoes differs

## Exit gate

Do not proceed until:

* The research charter exists.
* The five closest prior projects are identified.
* At least three methodological traps are documented.
* Every planned data source has a preliminary licensing status.
* The initial novelty statement is defensible.

Use this provisional novelty statement:

> Project Echoes integrates multiple computational methods to conduct an undirected, whole-corpus search for candidate biblical relationships that are not represented in the reference collections checked by the project.

---

# 12. Phase 1: Source Acquisition and Data Governance

## Objective

Create a controlled, versioned, legally documented source-data foundation.

## Tasks

Create `data/manifests/sources.yaml`.

For each source, record:

* Name
* Corpus
* Edition
* Provider
* Repository or acquisition location
* Commit or version
* Download date
* License
* Required attribution
* Redistribution status
* Machine-processing status
* Raw-file hashes
* Expected files
* Ingestion adapter
* Known limitations

Build source-acquisition scripts that:

* Never overwrite existing raw data silently
* Verify checksums
* Fail when expected files are missing
* Record source versions
* Support offline reprocessing after acquisition

Do not commit restricted raw text.

## Exit gate

* Every initial corpus source has a manifest.
* All licenses have been reviewed and classified.
* Raw files have checksums.
* Acquisition is reproducible.
* Restricted files are correctly excluded from version control.

---

# 13. Phase 2: Core Corpus Ingestion

## Objective

Ingest MACULA Hebrew and Greek into one normalized analytical schema while preserving source-specific information.

## Tasks

Implement separate adapters:

```text
ingest_macula_hebrew.py
ingest_macula_greek.py
```

Supplementary-source adapters are governed separately by the activation rule
in Section 3.6 and the applicable milestone decision record. They are not part
of primary-corpus ingestion merely because a source is available.

Each adapter must:

* Parse the native format.
* Validate required fields.
* Generate stable token identifiers.
* Preserve source identifiers.
* Map source fields to the canonical schema.
* Record unmapped fields.
* Write Parquet outputs.
* Load DuckDB tables.
* Produce an ingestion report.

Token IDs must use only source-edition identity: the source's own book identifier, chapter, verse, source token or subtoken position, and source-record identity when needed to distinguish variants. Ingestion code must not import, query, or otherwise depend on a versification crosswalk, English reference system, Septuagint alignment, external canonical mapping, or supplementary dataset to generate token IDs.

When the source supplies both Ketiv and Qere, the Hebrew adapter must emit both as separate linked token records and build the configured derived analysis stream without mutating the preserved records.

Generate stable IDs such as:

```text
HB_GEN_001_001_0001
GNT_JHN_001_001_0001
```

IDs must not depend solely on source row numbers.

## Validation tests

Automated checks:

* Every token has a valid corpus.
* Every token has a canonical reference.
* Token positions are unique.
* Canonical IDs are unique.
* Token order is continuous.
* Source references exist.
* Books, chapters, and verses are valid.
* Lemma values are present where expected.
* Morphological fields follow documented vocabularies.
* Re-running ingestion produces identical outputs.
* Processed token counts remain stable unless a source version changes.
* Token-ID generation imports or queries no crosswalk code or table.
* Adding, removing, or changing a crosswalk cannot change a token ID.
* Identical source-edition records generate identical IDs across reruns.
* Token-ID collisions fail clearly.
* Source-edition verse identifiers remain preserved separately from later mappings.
* Both Ketiv and Qere are retrievable in a representative legally safe fixture.
* Alternate readings retain stable, distinct IDs and normalized forms.
* Switching the configured reading changes only the derived analysis stream.
* Derived analytical positions are deterministic for both reading selections.

Manual spot checks:

* Torah
* Historical narrative
* Psalms
* Wisdom literature
* Major prophets
* Minor prophets
* Aramaic sections
* Synoptic Gospels
* John
* Pauline letters
* General letters
* Revelation
* Ketiv/Qere examples
* Prefix and suffix segmentation
* Greek punctuation and enclitics
* Known versification differences

## Exit gate

Do not proceed until:

* The complete Hebrew and Greek primary corpus parses.
* Every processed token traces to a source row.
* No unexplained passages are missing.
* Token counts and reference ranges are documented.
* Manual checks reveal no systematic errors.
* Corpus validation runs through one CLI command.
* Token identity is demonstrably independent of all crosswalk data.
* Ketiv and Qere preservation and stream-switching tests pass.

---

# 14. Phase 3: Segmentation and Passage Generation

## Objective

Create consistent comparison units at multiple scales.

## Passage granularities

Generate:

* Clause
* Sentence
* Verse
* Two-verse sliding window
* Five-verse sliding window

Add paragraph and pericope units later if source segmentation is reliable.

## Requirements

Each generated passage must:

* Reference its exact token range.
* Preserve canonical location.
* Preserve original surface text.
* Include normalized token sequences.
* Record corpus and source.
* Be reproducible from configuration.
* Avoid crossing book boundaries.
* Allow configurable crossing of chapter boundaries.
* Record overlap with neighboring windows.
* Distinguish physical source succession from analytical continuity.
* Never fabricate a verse record or passage unit for an edition-omitted verse number.
* Allow extant verses around an omitted number to remain source-order adjacent where configured, while setting `reference_gap` on every affected passage.
* Never concatenate alternate readings or endings merely because they are consecutive in source or file order.
* Treat `MRK 16:20` to `MRK 16:99` as a physical source successor and a separate analytical boundary break; no two-verse or five-verse window may cross that boundary.
* Support an `edition_complete` profile containing all text present inline in the pinned edition.
* Support a `critical_core` profile excluding `MRK 16:9-16:20`, `MRK 16:99`, and `JHN 7:53-8:11` without deleting or renumbering source tokens.
* Mark passages that contain declared disputed text and retain the applicable disputed-passage identifiers.
* Retain complete primary MACULA structure in the default Qere stream.
* Include every Ketiv token in verse-level Ketiv analysis.
* Sentence-level Ketiv analysis may use the completed Ketiv sentence mappings.
* Never fabricate clause or phrase membership where a Ketiv structural mapping is unresolved.
* Set `ketiv_structural_uncertainty` on every passage that intersects an unresolved Ketiv clause or phrase mapping.
* If an unresolved Ketiv mapping is excluded from that granularity's sensitivity analysis, record the exclusion explicitly while retaining the token in the corpus and verse-level analysis; no token may disappear silently.
* Treat the disputed-passage and reference-gap policy in ADR 0011 as binding.

## Validation

* Every token belongs to at least one passage.
* Clause and sentence passage boundaries match source annotations.
* Sliding windows have correct start and end points.
* No passage contains tokens from two books.
* Passage generation is deterministic.
* Source-order windows that span omitted verse numbers retain the extant references and set `reference_gap` rather than fabricating the missing number.
* No two-verse or five-verse window combines `MRK 16:20` with the alternate ending at `MRK 16:99`.
* No multi-verse passage at any granularity contains both `MRK 16:20` and `MRK 16:99`.
* Edition-complete and critical-core passage membership matches the registered disputed-passage policy exactly.
* The default Qere stream retains complete primary sentence, clause, and phrase membership.
* Verse-level Ketiv passages contain every Ketiv token, and sentence-level Ketiv passages may use the completed sentence mappings.
* Unresolved Ketiv clause and phrase mappings are never assigned fabricated membership; every intersecting passage carries `ketiv_structural_uncertainty`.
* Every granularity-specific sensitivity exclusion is explicit and traceable, and excluded tokens remain present in verse-level analysis.

## Exit gate

* All core granularities exist.
* Passage counts are documented.
* Random samples have been manually checked.
* Passage reconstruction reproduces source text.
* Both registered analysis profiles reproduce deterministically without mutating the underlying corpus.
* Both Qere and Ketiv passage handling satisfy the structural-uncertainty contract without deleting or re-identifying tokens.

---

# 15. Phase 4: Known-Relationship Benchmark

## Objective

Prove that the system can recover established relationships before searching for undocumented ones.

## Benchmark sources

Create machine-readable benchmark sets for:

* Explicit New Testament quotations of the Old Testament
* Strongly accepted Old Testament allusions
* Synoptic parallels
* Repeated passages in Samuel, Kings, and Chronicles
* Repeated Psalms
* Known formulaic passages
* Known narrative type-scenes
* Known structural parallels
* Broad cross-reference collections

Broad crowd-sourced or aggregated cross-reference datasets must be treated as weak supervision, not scholarly ground truth.

Use the existing OpenBible cross-reference source as a Tier 3 resource only. Its planned role is weak supervision and broad knownness filtering, not scholarly ground truth and never the sole positive benchmark. Record that it contains approximately 340,000 broad cross-reference links derived primarily from the Treasury of Scripture Knowledge and related sources. Its planned license classification is Creative Commons Attribution, subject to confirmation and recorded attribution for the exact acquired artifact; do not infer missing license facts.

Create a future project-curated Tier 1 explicit New Testament quotation benchmark at `data/benchmarks/tier1_quotations.csv`. Begin with schema and header only; do not invent or prepopulate the approximately 300 expected human-curated rows. The schema must include:

```text
quotation_id
nt_reference
ot_reference
ot_source_tradition
relationship_class
quotation_marker
curation_source
source_public_domain_status
curator
review_status
notes
```

Create `docs/tier1-quotation-curation.md` as the curation-instructions document. It must define:

* Allowed public-domain source indexes
* Row-level provenance requirements
* Review procedure
* Relationship classifications
* Duplicate handling
* Ambiguous source handling
* Hebrew-versus-Septuagint source identification
* Required human verification
* Project licensing for the resulting curated dataset

Copyrighted UBS, Nestle-Aland, or comparable quotation and allusion appendices must not be ingested into the repository without explicit permission. They may be consulted manually where lawful, but that consultation must not become copied benchmark data.

## Benchmark tiers

### Tier 1: High-confidence relationships

Manually curated, strongly accepted examples with row-level provenance and required human verification. The project-curated explicit New Testament quotation benchmark belongs here after population and review; an empty schema is not yet benchmark evidence.

### Tier 2: Moderate-confidence relationships

Commonly proposed allusions and thematic parallels.

### Tier 3: Broad cross-reference links

Useful for training or retrieval evaluation but too heterogeneous to function as definitive truth.

OpenBible broad cross-reference links belong here and may support weak supervision or broad knownness filtering only.

## Split strategy

Do not rely on random pair splitting.

Create:

* Held-out-book splits
* Held-out-book-pair splits
* Held-out-source-passage splits
* Held-out-relationship-family splits
* Held-out-genre splits

Example:

* Train on cross-testament relationships excluding Isaiah–Romans.
* Evaluate specifically on Isaiah–Romans.

## Negative examples

Create:

1. Length-matched random pairs
2. Common-vocabulary hard negatives
3. Same-theme but non-intertextual pairs
4. Same-genre formulaic pairs
5. Nearby-context negatives where appropriate

Call these “presumed negatives” or “contrastive examples,” not proven negatives.

## Metrics

Track:

* Recall@5
* Recall@10
* Recall@20
* Mean reciprocal rank
* nDCG@20
* Precision@10
* Precision among manually reviewed top candidates
* Performance by genre
* Performance by book
* Performance by passage length
* Performance by relationship class
* Hebrew-to-Greek performance
* Septuagint-mediated performance once activated

## Exit gate

* The benchmark is versioned.
* Evaluation splits are reproducible.
* A transparent lexical baseline has been evaluated.
* Results are documented.
* The project can identify known relationships above random and common-vocabulary baselines.
* The OpenBible source is classified as Tier 3 and its exact license and attribution are verified in the manifest.
* The project-curated Tier 1 quotation benchmark schema validates before any rows are curated.
* No copyrighted quotation or allusion appendix has been copied into benchmark data without explicit permission.

---

# 16. Phase 5: Discovery Engine A — Lexical and Phrase Analysis

## Objective

Identify transparent relationships based on rare words, roots, phrases, and ordered sequences.

## Features

Calculate:

* Lemma frequency
* Root frequency
* Surface-form frequency
* Document frequency
* Inverse document frequency
* Lemma bigrams
* Lemma trigrams
* Root n-grams
* Skip-grams
* Ordered-subsequence overlap
* Morphological sequences
* Part-of-speech sequences
* Shared proper names
* Shared predicate–argument combinations
* Shared rare semantic-domain combinations
* Shared formulaic expressions
* Shared hapax or near-hapax vocabulary

## Baseline methods

Implement:

* Jaccard overlap
* Weighted Jaccard
* TF-IDF cosine similarity
* BM25
* Rare-lemma overlap
* Log-likelihood phrase association
* Pointwise mutual information with frequency controls
* Longest common subsequence
* Weighted sequence alignment

## Null-model calibration

Every lexical scoring experiment must run repeated simulations from both required null families.

### Within-book reassignment null

Preserve:

* Book-level token or lemma frequencies
* Passage counts
* Passage lengths

Break meaningful passage relationships by randomly reassigning tokens or lemmas among passages within the same book. Merely shuffling passage order or labels is not an acceptable null because it leaves pairwise similarities unchanged.

### Frequency-preserving synthetic-passage null

Generate synthetic passages that preserve, at minimum:

* Passage lengths
* Book- or genre-conditioned lemma frequencies

Stricter registered variants may also preserve part-of-speech distributions, morphological distributions, or local n-gram characteristics.

At every review threshold, each scoring run must report:

* Observed candidate count
* Mean null candidate count
* 95% empirical null interval
* Observed-to-null enrichment
* Empirical tail probability where appropriate
* Estimated empirical false-discovery rate

All stochastic null runs must record seeds, iteration counts, conditioning choices, and configuration hashes.

## Conjunctive rare-evidence rule

A shared lemma or root with total corpus frequency of three or fewer cannot by itself make a candidate review-eligible. The maximum frequency is a configuration value, with `3` as the initial default, and must not be hard-coded.

Such evidence requires at least one independent co-signal:

* Ordered sequence similarity
* Shared rare phrase
* Syntactic match
* A second rare lexical item
* Another independently defined detector-family signal

This conjunctive rule must be implemented and validated before Milestone 8 human review begins.

## Scoring concept

```text
lexical_strength =
    weighted_lemma_overlap
  + rare_root_overlap
  + rare_phrase_overlap
  + ordered_sequence_similarity
  + morphological_pattern_similarity
  + entity_configuration_similarity
  - common_formula_penalty
  - local_context_penalty
```

## Penalties

Penalize:

* Extremely common religious vocabulary
* Formulaic speech introductions
* Genealogical formulas
* Standard legal formulas
* Shared proper names without supporting evidence
* Adjacent passages
* Known duplicate passages
* Same-book repetition that is already obvious
* Short passages with unstable scores

## Required evidence output

For every candidate, store:

* Shared words and roots
* Token positions
* Order information
* Corpus frequencies
* Passage-local frequencies
* Alternative passages containing the same features
* Statistical measures
* Independence-baseline expected co-occurrence
* Hypergeometric baseline value
* Empirical null-model rate
* Multiple-testing adjustment
* Contribution of each feature to the score

## Exit gate

* Known quotations are recovered at useful rates.
* Candidate evidence is human-readable.
* Frequency controls reduce obvious false positives.
* Top unknown candidates can be inspected without an LLM.
* Repeated null simulations from both required families are reproducible.
* Every review threshold reports observed counts, null counts and intervals, enrichment, empirical tail probabilities where appropriate, and estimated empirical false-discovery rate.
* The configurable conjunctive rare-evidence rule prevents a single very rare lemma or root from qualifying a candidate without an independent co-signal.

---

# 17. Phase 6: Septuagint Bridge

## Objective

Enable direct Hebrew–Greek–New Testament triangulation.

## Activation prerequisite

Do not start this phase until:

* Hebrew and Greek corpus QA passes.
* The lexical baseline works.
* Known-link recovery is documented.
* The separate Milestone 4 versification crosswalk is validated.
* A Septuagint edition-selection and licensing ADR is approved before acquisition.
* Printed-edition copyright, electronic-transcription license, annotation licenses, alignment-data license, raw and derived redistribution, and attribution have each been evaluated separately.

## Tasks

Build a Septuagint ingestion adapter.

Create:

* Septuagint token table
* Septuagint passage table
* Hebrew-to-Septuagint passage- or verse-alignment table using the Milestone 4 crosswalk
* Statistical Hebrew-to-Septuagint lemma-alignment table
* Septuagint-to-New-Testament comparison features
* Alignment-confidence values

The passage or verse alignment and statistical lemma alignment must support:

* One-to-one mappings
* One-to-many mappings
* Many-to-one mappings
* Unmatched material
* Additions
* Alternate chapter or book structures
* Alignment method
* Alignment confidence
* Edition-specific references

Token-level Hebrew-Septuagint alignment is explicitly out of scope for version 1. Statistical lemma correspondences must be presented with explicit confidence and must not be represented as manually verified token equivalences.

Distinguish:

* Direct Greek lexical overlap
* Greek semantic similarity
* Hebrew conceptual similarity
* Greek wording that differs from the Hebrew source
* Relationships dependent on translation choices

## Triangulation output

For a New Testament candidate, report:

```text
New Testament passage
Closest Septuagint passage
Corresponding Hebrew passage
Shared Greek lemmas
Shared Hebrew concepts
Translation differences
Alternative Septuagint sources
Known quotation or allusion status
```

## Exit gate

* Hebrew-Septuagint passage or verse alignments are validated against the Milestone 4 crosswalk.
* Statistical lemma alignments expose method and confidence and are evaluated separately from passage mappings.
* One-to-many, many-to-one, unmatched, added, and alternate-structure cases are represented without forced equivalence.
* Known New Testament quotations following the Septuagint are recovered.
* The system distinguishes Greek-mediated evidence from direct Hebrew evidence.
* The edition-selection ADR and separate license review are complete before acquisition, and publication restrictions are documented.
* No token-level Hebrew-Septuagint alignment is required or claimed for version 1.

---

# 18. Phase 7: Discovery Engine B — Semantic Retrieval

## Objective

Identify relationships expressed through different vocabulary.

## Representations to test

Evaluate independently:

1. Literal English gloss embeddings
2. Original Hebrew embeddings
3. Original Greek embeddings
4. Lemma-sequence embeddings
5. Root-sequence embeddings
6. Multilingual embeddings
7. Septuagint-mediated Greek comparison
8. Corpus-specific contrastive encoder as optional stretch work
9. Semantic-domain vectors
10. Sparse concept vectors

Do not assume one representation is best.

The corpus-specific contrastive encoder is not on the critical path. This phase and Milestone 10 must be completable without training a custom encoder.

## Evaluation requirements

Each representation must be benchmarked against:

* BM25
* TF-IDF
* Rare-lemma baseline
* Random retrieval
* Known quotations
* Known allusions
* Same-theme non-intertextual pairs

For any candidate supported by literal English gloss embeddings or another English-derived representation, run the registered English-feature ablation before it may retain `strong candidate` status. Record the score before and after removal, remaining original-language evidence, whether review eligibility survives, and whether the classification changes.

## Corpus-specific training

If training an encoder:

* Use known links as positive pairs.
* Use hard negatives.
* Record every training pair.
* Prevent book-level leakage.
* Preserve held-out relationship families.
* Mark candidate pairs that were exposed during training.

A relationship used during training cannot be presented as an independently discovered relationship.

## Candidate evidence

Semantic candidates must include:

* Model name
* Model version
* Representation
* Similarity score
* Nearest alternative passages
* Agreement with lexical or structural engines
* Whether the candidate was present in training data
* Human-readable textual evidence

## Exit gate

* At least one semantic method outperforms generic embeddings or adds complementary recall.
* Training leakage is controlled.
* Semantic retrieval does not dominate the final ensemble without interpretable support.
* Every English-supported `strong candidate` has a complete registered ablation and remains eligible without English-derived features.

---

# 19. Phase 8: Discovery Engine C — Grammatical and Syntactic Patterns

## Objective

Identify passages that share unusual grammatical or syntactic configurations.

## Features

Create representations for:

* Part-of-speech sequences
* Morphological sequences
* Clause types
* Dependency relations
* Predicate–argument structures
* Agent–patient configurations
* Speech framing
* Negation
* Tense and aspect patterns
* Imperative structures
* Conditional structures
* Repeated syntactic templates
* Rare grammatical combinations

## Methods

Use:

* Sequence alignment
* Tree-kernel approximations
* Dependency-subgraph matching
* Graph edit distance
* Frequent-pattern mining
* Weighted syntactic feature overlap

## Interpretation rule

A syntactic match alone does not establish literary dependence.

Its value is highest when combined with:

* Rare vocabulary
* Shared entities
* Similar narrative order
* Similar semantic structure

## Exit gate

* Known grammatical parallels are recoverable.
* Common genre syntax is properly downweighted.
* Candidate evidence includes the exact structures that match.

---

# 20. Phase 9: Discovery Engine D — Narrative and Event Structure

## Objective

Find passages that share event sequences or role configurations despite different wording.

## Event representation

Transform clauses into abstract structures such as:

```text
AGENT receives COMMAND
AGENT travels to LOCATION
AGENT encounters PERSON
AGENT objects
DIVINE_AGENT reassures AGENT
PROMISE is given
```

Use fields such as:

```text
predicate
agent
patient
recipient
location
instrument
source
goal
negation
tense_aspect
speech_status
event_order
```

## Methods

Test:

* Sequence alignment
* Dynamic time warping
* Graph edit distance
* Frequent-subgraph mining
* Event-sequence embeddings
* Predicate-role overlap
* Motif detection
* Role-preserving similarity

## Genre controls

Create common narrative-template labels for:

* Birth announcements
* Call narratives
* Journey stories
* Covenant scenes
* Battle reports
* Royal succession
* Miracle stories
* Trial and accusation scenes
* Wilderness testing
* Hospitality scenes
* Betrothal scenes
* Legal instruction
* Prophetic commission

A candidate may represent a meaningful type-scene without representing direct literary dependence.

## Exit gate

* The engine recovers known narrative parallels.
* Generic narrative templates are identified.
* Strong candidates contain more than vague event similarity.
* Narrative evidence can be inspected manually.

---

# 21. Phase 10: Discovery Engine E — Structural Analysis

## Objective

Search for repeated macro-structures, mirrored patterns, and potentially chiastic arrangements.

## Methods

Test:

* Repeated thematic sequence detection
* Mirrored entity and motif sequences
* Symmetry scoring
* Reversal-pattern detection
* Motif-distance comparison
* Hierarchical segmentation
* Recurrence matrices
* Graph-based motif alignment

## Guardrails

Do not treat every symmetrical sequence as chiasmus.

Require:

* Stable unit boundaries
* Multiple aligned elements
* Controlled probability of coincidental symmetry
* Comparison against shuffled or genre-matched baselines
* Clear textual labels for each proposed element
* Manual contextual review

## Exit gate

* Known strong structural patterns can be detected.
* Randomized controls demonstrate that the score is not trivially produced.
* Proposed structures remain understandable without model-generated labels.

---

# 22. Phase 11: Discovery Engine F — Anomaly Detection

## Objective

Identify linguistically or structurally unusual passages within relevant comparison groups.

## Comparison groups

Allow comparison against:

* Same book
* Same authorial corpus
* Same genre
* Same testament
* Same speaker
* Immediate context
* Entire corpus

## Signals

Detect:

* Unusual lemma frequency
* Unusual semantic-domain clusters
* Rare grammatical constructions
* Sudden stylistic shifts
* Unexpected foreign vocabulary
* Unusual entity-role configurations
* Passages whose nearest linguistic neighbors are outside their book
* Abrupt change points
* Vocabulary resembling another corpus more than surrounding text

## Methods

Use:

* Log-odds ratios
* Bayesian frequency comparisons
* Change-point detection
* Local outlier factor
* Isolation forest only as an exploratory method
* Mahalanobis distance
* Stylometric distance
* Nearest-neighbor disagreement
* Topic-distribution shifts

## Guardrail

Output:

> This passage is unusual relative to comparison set X under method Y.

Do not output:

> A different author wrote this passage.

## Exit gate

* Anomaly scores are calibrated against passage length and genre.
* Known unusual passages can be recovered.
* False positives caused by quotations and speech changes are documented.

---

# 23. Phase 12: Candidate Ensemble

## Objective

Combine independent evidence without allowing one opaque model to dominate.

## Evidence strength

Calculate from:

* Rare lexical overlap
* Phrase similarity
* Word order
* Semantic similarity
* Syntactic similarity
* Entity overlap
* Event-structure similarity
* Narrative structure
* Structural similarity
* Multiple-detector agreement

## Surprise score

Calculate from:

* Feature rarity
* Canonical distance
* Different books
* Different genres
* Different languages
* Absence from known cross-references
* Absence from ordinary nearest neighbors
* Low frequency of the matching pattern
* Unusual combination of otherwise common features

## Detector independence

Do not treat three similar embedding models as three independent detectors.

Group detectors into families:

* Lexical
* Semantic
* Syntactic
* Narrative
* Structural
* Anomaly
* Entity-based
* Cross-language

## Ensemble concept

```text
candidate_score =
    evidence_strength
    × surprise
    × detector_independence
    × interpretability
    × data_quality
    × (1 - knownness_penalty)
```

Do not hard-code weights permanently.

Store:

* Raw component scores
* Normalized component scores
* Weight configuration
* Score version
* Calibration method

## Candidate eligibility

A candidate enters human review when:

* Two independent detector families support it, or
* One transparent detector provides exceptionally strong evidence that satisfies every applicable conjunctive-evidence rule
* It is not merely adjacent context
* It passes data-quality checks
* It is not already strongly represented in known-link sources
* It has identifiable textual evidence
* It has no unresolved training-data contamination

A shared lemma or root at or below the configured rare-evidence frequency threshold cannot satisfy eligibility alone. It requires ordered sequence similarity, a shared rare phrase, a syntactic match, a second rare lexical item, or another independently defined detector-family co-signal. The configured threshold, evidence fields, and empirical null calibration must be retained with the candidate.

Every candidate whose evidence intersects a declared disputed passage must set `disputed_passage_flag` and record the affected passage identifiers. Such a candidate may retain `strong candidate` status only if it survives exclusion of the disputed text or receives a completed textual-criticism review; source-file adjacency is never evidence that alternate readings form one passage.

---

# 24. Phase 13: Knownness and Novelty Filtering

## Objective

Prevent the project from repeatedly rediscovering famous relationships and overstating novelty.

## Knownness Level 1: Machine-readable references

Check candidates against:

* Broad cross-reference collections
* Explicit quotation datasets
* Parallel-passage datasets
* Known synoptic relationships
* Existing computational datasets
* The project literature matrix

## Knownness Level 2: Curated intertextual resources

Check strong candidates against curated intertextual collections where licensing and access allow.

Do not bulk-republish restricted data.

## Knownness Level 3: Scholarship search

For serious candidates, search:

* Both passage references together
* Reversed passage-reference order
* Shared rare lemmas
* English and transliterated terms
* “allusion”
* “echo”
* “intertextual”
* “quotation”
* “parallel”
* “type-scene”
* “chiasm”
* Relevant journal databases
* Dissertations
* Commentaries
* Books
* Non-English search terms where practical

Record every query and review date.

## Knownness labels

### K0 — Widely documented

Appears in ordinary cross-reference systems or standard scholarship.

### K1 — Documented in specialist scholarship

Not widely known, but clearly discussed in academic work.

### K2 — Related idea documented

A broader thematic or textual connection is discussed, but the exact computationally identified relationship is unclear.

### K3 — No match found in checked sources

No discussion of the exact relationship was located in the sources and searches recorded.

### K4 — Search incomplete

Insufficient access, ambiguous terminology, or incomplete review prevents a conclusion.

Never translate K3 into “nobody has ever seen this.”

Use:

> No discussion of this exact relationship was found in the specified sources using the recorded searches as of the review date.

---

# 25. Phase 14: Human Review Console

## Objective

Provide a local research instrument for evaluating candidates systematically.

This is not a public product.

## Required interface

Display:

* Passage A
* Passage B
* Original-language text
* Transliteration
* Literal gloss
* Optional reference translation
* Surrounding context
* Highlighted shared lemmas
* Shared roots
* Morphology
* Syntax
* Semantic domains
* Participant roles
* Narrative features
* Detector scores
* Corpus frequencies
* Observed candidate count at the active threshold
* Null-model expected-noise baseline beside the observed count
* Mean null count, 95% empirical interval, enrichment, and estimated empirical false-discovery rate
* Alternative source passages
* Known cross-references
* Training-exposure warning
* Data-quality warnings
* Knownness-search status
* Review fields

## Review actions

Allow:

* Accept as strong candidate
* Accept as plausible candidate
* Mark as interesting but weak
* Mark as known relationship
* Mark as generic similarity
* Mark as formulaic-language effect
* Mark as data artifact
* Reject
* Defer
* Add notes
* Add citations
* Record alternative explanations
* Record literature searches
* Export dossier

## Manual review rubric

For every candidate, answer:

1. What exact textual features connect the passages?
2. Are those features rare?
3. Does their order matter?
4. Does the surrounding context strengthen the relationship?
5. Is the similarity better explained by genre?
6. Is the proposed direction of dependence chronologically possible, and does the evidence support a written-text relationship, an oral sayings tradition, a shared scriptural source, or another form of mediation?
7. Does the New Testament language follow the Septuagint, Hebrew, or neither?
8. Are there closer alternative sources?
9. Is the proposed relationship meaningful without theological overstatement?
10. Has the exact relationship already been documented?
11. What evidence would weaken or falsify the proposal?
12. What is the weakest part of the argument?
13. Could the result arise from translation or annotation choices?
14. Does the relationship survive alternate textual witnesses?
15. Which relationship classification best fits?

## Exit gate

* Reviews persist reliably.
* Review history is preserved.
* Rejected candidates remain searchable.
* Candidate dossiers export reproducibly.
* The console can be launched locally through one command.

---

# 26. Phase 15: LLM-Assisted Analysis

## Objective

Use an LLM as a bounded research assistant after computational detection.

## Permitted uses

The LLM may:

* Explain supplied evidence
* Generate counterarguments
* Suggest alternative source passages
* Suggest literature-search queries
* Identify methodological weaknesses
* Compare possible classifications
* Summarize review evidence
* Convert technical evidence into readable prose
* Help draft research dossiers
* Identify areas requiring Hebrew or Greek expertise

## Prohibited uses

The LLM may not:

* Generate primary candidates from unrestricted prompting
* Decide final novelty
* Invent quotations
* silently translate original-language text
* Use internal memory as proof of scholarship
* assign final scholarly significance
* infer authorial intent automatically
* override deterministic evidence
* classify a relationship without citing supplied evidence

## Evidence package

Send only bounded candidate packages:

```text
candidate_id
passage_a
passage_b
original_text_a
original_text_b
literal_glosses
lemmas
morphology
syntax
shared_features
feature_frequencies
context
detector_scores
alternative_matches
known_sources_checked
review_questions
```

Require structured output:

```text
observations
supporting_evidence
alternative_explanations
weaknesses
recommended_search_queries
questions_for_human_review
```

Every observation must reference supplied evidence.

## Cost controls

* Do not send the entire Bible repeatedly.
* Use local code and local models for candidate generation.
* Send only top candidates for LLM review.
* Cache model outputs.
* Record prompts and model versions.
* Allow experiments to run without paid APIs.

---

# 27. Phase 16: Blind Evaluation

## Objective

Determine whether new candidates are being judged more generously than known or negative examples.

## Blind set

Construct a hidden mixture of:

* Known strong relationships
* Known moderate relationships
* Hard negatives
* Generic thematic similarities
* New candidate relationships
* Deliberate data artifacts

Hide category labels during review.

Use the same rubric for every pair.

## Metrics

Track:

* Acceptance rate by hidden class
* Reviewer confidence
* False-positive rate
* Inter-reviewer agreement where a second reviewer exists
* Relationship-class confusion
* Evidence-strength calibration
* Novelty-label calibration

## External review

For strongest candidates, seek review from someone competent in Hebrew, Greek, biblical intertextuality, or the relevant book.

The external reviewer should evaluate:

* Whether the linguistic evidence is correct
* Whether the relationship has a plausible scholarly basis
* Whether stronger alternative sources exist
* Whether the proposed novelty is overstated

---

# 28. Minimum Publishability Standard

A candidate must not be presented as a serious finding unless:

* Source data has been manually checked.
* Tokenization has been verified.
* At least two evidence types support it, unless one rare transparent feature is exceptionally strong.
* Common vocabulary has been controlled.
* Genre explanations have been considered.
* Surrounding context has been examined.
* Alternative source passages have been compared.
* Existing cross-references have been checked.
* A scholarship search has been recorded.
* Training-data exposure has been ruled out or disclosed.
* Textual variants have been considered where relevant.
* The conclusion uses calibrated language.
* The strongest counterargument is included.
* The analysis can be reproduced from a run manifest.
* Any English-supported `strong candidate` survives its registered all-English-feature ablation.
* Proposed direction and mediation are chronologically possible and independently supported.
* Any disputed-text-supported `strong candidate` survives exclusion of the disputed text or has a completed textual-criticism review.

---

# 29. Planned Experimental Sequence

## Experiment 1: Transparent known-link recovery

Goal:

Recover known cross-testament relationships using rare lexical evidence.

Methods:

* BM25
* TF-IDF
* Weighted lemma overlap
* Rare-root overlap
* Phrase-order scoring

Output:

* Benchmark metrics
* Error analysis
* Top false positives
* Top false negatives

## Experiment 2: New lexical candidates

Goal:

Find strong lexical relationships absent from imported known-link collections.

Process:

* Remove known relationships.
* Remove adjacent context.
* Rank rare-phrase and ordered-lemma candidates.
* Manually review the top 100.
* Categorize false positives.
* Display the null-model expected-noise baseline beside observed candidate counts.
* Draft Output J as the standalone review and false-positive taxonomy.

## Experiment 3: Septuagint bridge

Goal:

Determine which New Testament relationships become stronger when the Greek Old Testament is used as the bridge.

Output:

* Hebrew–Greek–New Testament triangles
* Passage- or verse-level Hebrew-Septuagint mappings
* Statistical lemma alignments with explicit confidence
* Septuagint-dependent candidates
* Known quotation recovery
* Translation-sensitive cases

Token-level Hebrew-Septuagint alignment is not part of the version 1 experiment.

## Experiment 4: Semantic retrieval

Goal:

Find conceptually related passages lacking obvious lexical overlap.

Compare:

* Generic embeddings
* Literal-gloss embeddings
* Original-language embeddings
* Corpus-specific embeddings
* Sparse semantic-domain vectors

Training a corpus-specific contrastive encoder is optional stretch work; this experiment must be completable without it. Any result supported by English-derived representations must undergo the registered English-feature ablation before retaining `strong candidate` status.

## Experiment 5: Independent detector agreement

Goal:

Identify candidates supported by lexical evidence plus at least one semantic, syntactic, or narrative detector.

This becomes the first serious candidate set.

## Experiment 6: Pauline case study

Research question:

> Which Pauline passages have strong computational relationships to sayings of Jesus, the Septuagint, and the Hebrew Bible that are weakly represented in conventional cross-reference systems?

Chronological interpretation rule:

The Pauline letters predate the written canonical Gospels. A detected Paul-Jesus relationship therefore must not automatically be framed as Paul's dependence on a written Gospel. First evaluate possible Jesus sayings traditions, shared early Christian traditions, common scriptural sources, Septuagint wording, Hebrew scriptural wording, and other demonstrated mediation. Direct dependence on a written Gospel requires separate historical evidence.

Subquestions:

* Which concepts attributed to Paul appear in earlier biblical corpora?
* Which Pauline phrases are lexically unusual?
* Which Pauline themes have strong semantic but weak lexical predecessors?
* Which apparent relationships are mediated through the Septuagint?
* Which Pauline passages remain genuine outliers?

## Experiment 7: Narrative-pattern analysis

Goal:

Find repeated event structures across distant books and genres.

## Experiment 8: Anomaly analysis

Goal:

Identify passages whose linguistic or semantic nearest neighbors fall outside their expected corpus.

## Experiment 9: Whole-canon discovery

Goal:

Run the complete ensemble across the primary corpus.

Only begin after earlier phases establish:

* Corpus reliability
* Benchmark value
* False-positive controls
* Review workflow
* Knownness filtering

---

# 30. Visualizations

Produce research visualizations only after the underlying data is validated.

## Required outputs

* Book-to-book relationship heat map
* Whole-canon passage network
* Cross-testament relationship network
* Hebrew–Septuagint–New Testament triangle graph
* Rare-phrase network
* Pauline source map
* Known versus candidate relationship map
* Detector-agreement chart
* Candidate score distribution
* False-positive taxonomy
* Anomaly map
* Relationship-class distribution
* Knownness distribution

Every visualization must:

* Link back to the underlying candidate IDs.
* Record filters and score thresholds.
* Avoid visually implying certainty beyond the data.
* Support publication-quality static export.

---

# 31. Research Dossier Format

Each strong candidate receives a dossier containing:

## Identification

* Candidate ID
* Passage A
* Passage B
* Relationship classification
* Confidence
* Knownness status

## Text

* Original-language passage A
* Original-language passage B
* Transliteration
* Literal gloss
* Surrounding context

## Computational evidence

* Shared lemmas
* Shared roots
* Phrase-order evidence
* Semantic score
* Syntactic score
* Narrative score
* Structural score
* Feature frequencies
* Detector agreement
* Alternative nearest passages

## Cross-language evidence

* Septuagint wording
* Hebrew correspondence
* Greek New Testament wording
* Translation differences
* Alignment confidence

## Interpretive analysis

* Proposed relationship
* Contextual significance
* Relationship classification
* Directionality
* Alternative explanations
* Strongest counterargument
* What would falsify the proposal

## Knownness analysis

* Cross-reference sources checked
* Scholarly sources checked
* Search queries
* Relevant citations
* Knownness label
* Search limitations

## Conclusion

Use calibrated language:

* Strong candidate
* Plausible candidate
* Interesting but weak
* Known relationship
* Generic similarity
* Rejected
* Requires expert review

---

# 32. Final Project Outputs

## Output A: Reproducible repository

Must include:

* Source code
* Configurations
* Tests
* Environment lock
* Corpus-processing instructions
* Experiment commands
* Data manifests
* Methodology
* Limitations

## Output B: Processed corpus architecture

Publish only data and derived outputs permitted by source licenses.

## Output C: Benchmark report

Include:

* Known-link datasets
* Splits
* Baselines
* Metrics
* Error analysis
* Leakage controls

## Output D: Candidate ledger

Include:

* All reviewed candidates
* Accepted candidates
* Rejected candidates
* Data artifacts
* Known relationships
* Review history

## Output E: Research dossiers

Create detailed reports for the strongest candidates.

## Output F: Visual atlas

Produce the validated network and corpus visualizations.

## Output G: Pauline case study

Potential title:

> Computationally Tracing Pauline Language Through Jesus, the Septuagint, and the Hebrew Bible

## Output H: General methods paper

Potential title:

> Searching for Undocumented Biblical Echoes: An Undirected Computational Analysis of the Hebrew Bible and Greek New Testament

## Output I: Public-facing essay

Potential title:

> I Compared Every Passage in the Bible Against Every Other Passage. Here Is What the Computer Found.

## Output J: Milestone 8 Top-100 Review and False-Positive Taxonomy

Create a standalone writeup under `outputs/publications/` containing:

* Candidate-selection procedure
* Thresholds
* Null-model expected-noise baseline
* Accepted candidates
* Rejected candidates
* False-positive categories
* Data artifacts
* Formulaic-language effects
* Genre effects
* Common-vocabulary effects
* Lessons for scoring revisions
* Methodological limitations

The drafted Output J is an acceptance artifact for Milestone 8, not a substitute for the complete candidate ledger or later publication review.

---

# 33. Stop Rules

Codex must enforce the following:

* Do not build a polished public interface before credible candidate results exist.
* Do not use English embeddings as sole evidence.
* Do not treat cosine similarity as a discovery.
* Do not train and evaluate on the same relationships.
* Do not add large secondary corpora before the core corpus passes validation.
* Do not call a relationship novel because an LLM does not recognize it.
* Do not make theological conclusions automatically.
* Do not interpret every anomaly as evidence of different authorship.
* Do not discard rejected candidates.
* Do not modify scoring weights after inspecting individual attractive results without recording a new experiment.
* Do not publish restricted source data.
* Do not ingest copyrighted quotation or allusion appendices without explicit permission or turn lawful manual consultation into copied benchmark data.
* Do not conceal annotation disagreements.
* Do not conceal model-training exposure.
* Do not use textual variants as independent proof of intertextuality.
* Do not treat reception-history evidence as proof of original authorial intent.
* Do not optimize for impressive visualizations at the expense of methodological validity.
* Do not claim token-level Hebrew-Septuagint alignment in version 1.
* Do not retain `strong candidate` status for English-supported evidence without the registered English-feature ablation.

---

# 34. Milestone Plan for Codex

## Milestone 0: Repository foundation

time_budget:

Build:

* Repository structure
* Python environment
* CLI skeleton
* Logging
* Configuration loading
* Test framework
* Linting
* Type checking
* CI
* Documentation skeleton

Acceptance:

* All quality commands pass.
* CLI launches.
* Empty experiment manifest can be generated.

## Milestone 1: Research and source governance

time_budget:

Build:

* Research charter
* Registered English-feature ablation and Pauline chronology guardrails
* Source manifest schema
* Dataset manifest validator
* Licensing documentation
* Decision-log structure
* Literature-matrix template

Acceptance:

* Invalid manifests fail validation.
* Every initial source has a documented status.
* The research charter contains the English-feature ablation and Pauline chronology requirements.

## Milestone 2: Hebrew ingestion

time_budget:

Build:

* MACULA Hebrew adapter
* Hebrew normalization
* Token schema
* Source-edition-only token-ID generation
* Separate Ketiv and Qere records with stable variant grouping
* Configurable derived Ketiv/Qere analysis stream and deterministic analysis positions
* DuckDB loading
* Validation report

Acceptance:

* Complete Hebrew corpus loads.
* Stable token IDs derive only from source-edition coordinates and source-record identity where variants require it.
* Token-ID generation imports or queries no crosswalk, and crosswalk changes cannot change an ID.
* Source-edition verse identifiers remain separate from later mappings, and token-ID collisions fail clearly.
* Both Ketiv and Qere records are retained with distinct stable IDs, forms, and provenance in a legally safe fixture.
* Switching the configured analysis reading changes only the derived stream and produces deterministic positions.
* Spot checks pass.
* Reprocessing is deterministic.

## Milestone 3: Greek ingestion

time_budget:

Build:

* MACULA Greek adapter
* Greek normalization
* Unified corpus tables
* Validation report

Acceptance:

* Complete Greek New Testament loads.
* Unified queries work across corpora.
* Source provenance remains distinct.

## Milestone 4: Supplementary annotations

time_budget:

Status: **Complete as of 2026-07-12** on the acceptance basis below; STEPBible
activation is deferred under ADR 0012 and is not a closure dependency.

Build:

* OSHB Ketiv/Qere supplementary tokens and deterministic Qere/Ketiv streams
* Supplementary annotation-alignment tables that store source values beside primary annotations
* Conflict-preservation and uncertainty-query logic
* Ketiv structural-alignment mappings with explicit anchors, methods, confidence, and resolution status
* Separate versification-crosswalk mapping layer
* Source-native identity preservation, including separate OSHB/OSIS and canonical book identifiers
* Explicit unresolved-alignment reporting
* Deferred optional STEPBible activation governed by ADR 0012 and the source-activation rule

Acceptance:

* Supplementary data never overwrites primary annotations.
* Annotation conflicts and uncertainty are queryable.
* Crosswalk rows preserve edition-specific references and cannot change token identity or source-edition verse identifiers.
* OSHB source-native and canonical book identifiers remain separate, and canonical mapping changes cannot change OSHB token IDs.
* Qere and Ketiv derived streams are deterministic and preserve all underlying reading records.
* Ketiv structural mappings expose resolution status instead of fabricating sentence, clause, or phrase values.
* Primary Hebrew and Greek identity, surface/lemma, and analytical digests remain unchanged by supplementary activation.
* Every unresolved structural alignment is explicitly reportable.
* Any future supplementary source requires a demonstrated downstream need, exact source approval, completed licensing and provenance review, and a conflict-preserving integration design.

## Milestone 5: Passage segmentation

time_budget:

Status: **Complete as of 2026-07-12**. Two strict full-corpus generations
reproduced run ID `passages-v1-00e261abea9ed44ef087`, 914,497 passages,
21,530,271 membership rows, 913,445 adjacency rows, 148,948 explicit
exclusions, zero issues, all six logical table hashes, all five deterministic
content-table physical hashes, and all 3,570 non-metadata leaf hashes. The
metadata physical hash differs only because runtime is registered telemetry;
its telemetry-excluding logical hash is stable. The validated run satisfies
every acceptance item below under ADRs 0011 and 0013 without changing the
pinned corpus or supplement digests.

The exact next task is Milestone 6 only: begin the known-link benchmark with
the known-relationship schema, the governed OpenBible Tier 3 manifest review,
and validation of the still-header-only project-curated Tier 1 quotation CSV.
No Milestone 6 acquisition, import, or benchmark implementation began during
Milestone 5.

Build:

* Clause passages
* Sentence passages
* Verse passages
* Two-verse windows
* Five-verse windows
* Passage reconstruction
* Separate source-successor and analytical-boundary declarations
* Edition-complete and critical-core analysis profiles
* Reference-gap and disputed-passage metadata
* Ketiv structural-uncertainty metadata and explicit granularity-specific sensitivity exclusions

Acceptance:

* Passage boundaries validate.
* Every token belongs to expected passage units.
* Edition-omitted verse numbers are never fabricated; source-order windows crossing such a numbering gap set `reference_gap`.
* `MRK 16:20` physically precedes `MRK 16:99`, but no two-verse or five-verse analytical window combines the longer and alternate endings.
* No multi-verse passage at any granularity contains both `MRK 16:20` and `MRK 16:99`.
* `edition_complete` includes all inline edition text, while `critical_core` excludes `MRK 16:9-16:20`, `MRK 16:99`, and `JHN 7:53-8:11` exactly.
* Disputed-passage membership is retained for future candidate flagging and strong-candidate review gates.
* The default Qere stream retains complete primary MACULA sentence, clause, and phrase structure.
* Verse-level Ketiv analysis includes every Ketiv token; sentence-level Ketiv analysis may use the completed sentence mappings.
* Clause- and phrase-level Ketiv passages never fabricate membership for unresolved mappings, and every passage intersecting an unresolved Ketiv clause or phrase mapping carries `ketiv_structural_uncertainty`.
* A sensitivity analysis may exclude unresolved Ketiv mappings only at the affected granularity, with an explicit exclusion record; tokens remain visible in the corpus and verse-level analysis.
* ADR 0011 remains binding for disputed passages, reference gaps, and the `MRK 16:20` to `MRK 16:99` analytical boundary.

## Milestone 6: Known-link benchmark

time_budget:

Build:

* Known-relationship schema
* Updated OpenBible Tier 3 manifest record for weak supervision and broad knownness filtering
* Empty project-curated Tier 1 quotation-benchmark schema and curation instructions
* Benchmark importers
* Evaluation splits
* Negative examples
* Metrics

Acceptance:

* Benchmark can be generated and versioned.
* Leakage checks pass.
* OpenBible is not used as scholarly ground truth or the sole positive benchmark, and its exact license and attribution are verified.
* The Tier 1 quotation CSV contains only its validated header until human curation begins; no rows are invented.
* Copyrighted quotation and allusion appendices are not copied without explicit permission.

## Milestone 7: Lexical baseline

time_budget:

Build:

* TF-IDF
* BM25
* Rare-lemma scoring
* Phrase scoring
* Ordered-sequence scoring
* Candidate evidence generation
* Repeated within-book reassignment null simulations
* Repeated frequency-preserving synthetic-passage null simulations
* Configurable conjunctive rare-evidence rule and co-signal evidence fields

Acceptance:

* Known-link recovery exceeds random and simple overlap baselines.
* Candidate evidence is interpretable.
* Within-book reassignment preserves book frequency, passage counts, and passage lengths while breaking passage relationships; label or order shuffling alone is rejected.
* Synthetic passages preserve passage lengths and book- or genre-conditioned lemma frequencies.
* At every review threshold, reports include observed count, mean null count, 95% empirical interval, enrichment, empirical tail probability where appropriate, and estimated empirical false-discovery rate.
* A lemma or root at or below the configured frequency threshold cannot qualify a candidate without an independent co-signal.

## Milestone 8: First unknown-candidate review

time_budget:

Build:

* Known-link exclusion
* Candidate-ranking output
* Manual-review CSV or basic console
* False-positive taxonomy
* Expected-noise display beside observed candidate counts
* Draft standalone Output J

Acceptance:

* Top 100 candidates reviewed.
* Main false-positive patterns documented.
* The review output shows the relevant null-model expected-noise baseline beside each observed candidate-count threshold.
* The Milestone 7 conjunctive rare-evidence rule is implemented before review eligibility is calculated.
* Output J is drafted under `outputs/publications/` with selection procedure, thresholds, expected noise, accepted and rejected candidates, false-positive categories, data artifacts, formulaic-language, genre, and common-vocabulary effects, scoring lessons, and limitations.
* Scoring changes, if any, are recorded as a new experiment.

## Milestone 9: Septuagint bridge

time_budget:

Build:

* Septuagint edition-selection and licensing ADR before any acquisition
* Septuagint adapter
* Passage- or verse-level Hebrew-Septuagint alignment through the Milestone 4 crosswalk
* Statistical lemma alignment with explicit confidence
* Cross-language retrieval
* Triangulated evidence reports

Acceptance:

* Known Septuagint-mediated relationships are recovered.
* Printed edition, electronic transcription, annotations, alignment data, raw and derived redistribution, and attribution are each licensed and documented separately before acquisition.
* Passage and verse mappings support one-to-one, one-to-many, many-to-one, unmatched, additions, and alternate book or chapter structures.
* Statistical lemma-alignment method and confidence are documented.
* Token-level Hebrew-Septuagint alignment remains explicitly out of scope for version 1.

## Milestone 10: Semantic retrieval

time_budget:

Build:

* Representation pipeline
* Embedding benchmarks
* Nearest-neighbor index
* Hard-negative evaluation
* Training-lineage tracking
* Registered English-feature ablation
* Optional corpus-specific contrastive encoder as stretch work only

Acceptance:

* Semantic methods add measurable value beyond lexical methods.
* No evaluation leakage exists.
* The milestone is complete without requiring a custom contrastive encoder.
* Every `strong candidate` supported by an English-derived feature survives a recorded all-English-feature ablation or is downgraded.

## Milestone 11: Syntactic and narrative engines

time_budget:

Build:

* Predicate–argument representation
* Syntactic features
* Event sequences
* Narrative similarity

Acceptance:

* Known structural or narrative relationships are recoverable.
* Generic genre templates are controlled.

## Milestone 12: Anomaly and structural engines

time_budget:

Build:

* Anomaly features
* Change-point analysis
* Structural sequence analysis
* Randomized controls

Acceptance:

* Scores are calibrated.
* Results are not dominated by passage length or genre.

## Milestone 13: Candidate ensemble

time_budget:

Build:

* Score normalization
* Detector-family grouping
* Surprise scoring
* Knownness penalty
* Candidate eligibility logic

Acceptance:

* Ensemble results retain raw evidence.
* No opaque model dominates without explanation.
* Rare-evidence eligibility retains the configured threshold, required independent co-signal, independence baseline, empirical null rate, and multiple-testing adjustment.

## Milestone 14: Review console

time_budget:

Build:

* Local Streamlit console
* Original-language display
* Evidence highlighting
* Review forms
* Search records
* Dossier export

Acceptance:

* Reviews persist.
* Rejected candidates remain available.
* Dossiers reproduce from stored data.

## Milestone 15: Pauline case study

time_budget:

Build:

* Study-specific configuration
* Jesus–Paul analysis
* Hebrew Bible–Paul analysis
* Septuagint–Paul analysis
* Pauline anomaly analysis
* Research dossiers
* Chronology- and mediation-aware relationship classification in the case-study documentation

Acceptance:

* Findings meet minimum publishability standards.
* Strong candidates receive outside linguistic review where possible.
* Paul-Jesus relationships distinguish possible oral sayings tradition, shared early Christian tradition, common scriptural source, Septuagint or Hebrew wording, and written-text dependence.
* Direct dependence on a written canonical Gospel is claimed only with separate historical evidence.

## Milestone 16: Whole-canon run

time_budget:

Build:

* Full experiment configuration
* Batch candidate generation
* Ensemble ranking
* Knownness workflow
* Visual outputs
* Final candidate ledger

Acceptance:

* Run is fully reproducible.
* Candidates are traceable.
* Methodology and limitations are complete.

---

# 35. Exact Initial Build Order

Codex must begin in this order:

1. Create the repository.
2. Create the Python environment.
3. Create the CLI and configuration framework.
4. Create the research charter.
5. Create source and experiment manifest schemas.
6. Create licensing and provenance documentation.
7. Add MACULA Hebrew acquisition instructions.
8. Implement Hebrew ingestion.
9. Implement Hebrew validation, including source-edition-only token IDs, separate Ketiv/Qere preservation, and both deterministic derived reading streams.
10. Add MACULA Greek acquisition instructions.
11. Implement Greek ingestion.
12. Implement Greek validation.
13. Create the unified token table.
14. Add OSHB Ketiv/Qere supplementary tokens and structural mappings without changing primary token identity.
15. Build the generic supplementary annotation-alignment and conflict-preservation layers.
16. Build the separate versification crosswalk without changing primary token identity; defer STEPBible unless ADR 0012's future activation criteria are satisfied.
17. Generate clause, sentence, verse, two-verse, and five-verse passages.
18. Create benchmark schemas, including the empty project-curated Tier 1 quotation schema.
19. Verify the OpenBible Tier 3 manifest and import permitted known relationships without copying restricted appendices.
20. Create evaluation splits.
21. Implement TF-IDF.
22. Implement BM25.
23. Implement rare-lemma scoring and the configurable conjunctive co-signal rule.
24. Implement phrase and sequence scoring plus both repeated lexical null families.
25. Evaluate known-link recovery and report empirical null metrics at review thresholds.
26. Generate unknown lexical candidates with expected-noise baselines.
27. Review the top 100.
28. Draft Output J with the false-positive taxonomy and scoring lessons.
29. Complete the Septuagint edition-selection and separate licensing decision, then ingest only the approved source.
30. Build passage- or verse-level Hebrew-Septuagint mappings and statistical lemma alignments with confidence.
31. Build Septuagint–New-Testament comparison.
32. Evaluate Septuagint-mediated known links.
33. Add semantic models; treat a custom contrastive encoder as optional stretch work.
34. Evaluate semantic models and run registered English-feature ablations where applicable.
35. Add syntactic features.
36. Add narrative event structures.
37. Add structural analysis.
38. Add anomaly analysis.
39. Build candidate ensemble.
40. Build knownness filtering.
41. Build local review console.
42. Run the Pauline case study.
43. Produce candidate dossiers.
44. Seek external review.
45. Run the whole-canon experiment.
46. Produce final visualizations.
47. Publish methods, code, limitations, rejected results, and qualified findings.

---

# 36. First Completion Target

The first meaningful milestone is not:

> AI analyzes the entire Bible.

It is:

> A verified, reproducible token-level Hebrew and Greek corpus that recovers established biblical relationships using transparent lexical evidence.

The second meaningful milestone is:

> A ranked set of previously unlisted candidate relationships whose exact textual evidence can be inspected and manually evaluated.

The project should not advance to whole-canon claims until those two milestones are complete.

---

# 37. Final Definition of Success

Project Echoes succeeds if it produces:

1. A reliable token-level biblical corpus.
2. Reproducible computational methods.
3. Strong benchmark performance on known relationships.
4. Transparent candidate evidence.
5. A disciplined human-review process.
6. A record of both discoveries and failures.
7. Several candidates that remain plausible after linguistic, contextual, statistical, and scholarly review.
8. At least one publishable case study.
9. A research repository that another technically competent researcher can reproduce.
10. A defensible contribution to computational biblical studies, even if many apparent discoveries are ultimately rejected.

The intellectual value of the project does not depend on producing sensational findings. A rigorous demonstration of which methods work, which produce false positives, and which types of relationships can be detected computationally would itself be a legitimate result.
