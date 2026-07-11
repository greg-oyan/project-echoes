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

Before activation, the Septuagint source must receive a separate review covering:

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

## 3.3 Supplementary annotation layers

STEPBible and comparable permissively licensed datasets may supplement the primary corpus with:

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
source_row_reference
```

Every processed token must trace back to the original source row.

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
explanation
run_id
```

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

## 10.5 Versification

Create a versification-crosswalk table.

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
ingest_stepbible.py
```

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

## Validation

* Every token belongs to at least one passage.
* Clause and sentence passage boundaries match source annotations.
* Sliding windows have correct start and end points.
* No passage contains tokens from two books.
* Passage generation is deterministic.

## Exit gate

* All core granularities exist.
* Passage counts are documented.
* Random samples have been manually checked.
* Passage reconstruction reproduces source text.

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

## Benchmark tiers

### Tier 1: High-confidence relationships

Manually curated, strongly accepted examples.

### Tier 2: Moderate-confidence relationships

Commonly proposed allusions and thematic parallels.

### Tier 3: Broad cross-reference links

Useful for training or retrieval evaluation but too heterogeneous to function as definitive truth.

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
* Contribution of each feature to the score

## Exit gate

* Known quotations are recovered at useful rates.
* Candidate evidence is human-readable.
* Frequency controls reduce obvious false positives.
* Top unknown candidates can be inspected without an LLM.

---

# 17. Phase 6: Septuagint Bridge

## Objective

Enable direct Hebrew–Greek–New Testament triangulation.

## Activation prerequisite

Do not start this phase until:

* Hebrew and Greek corpus QA passes.
* The lexical baseline works.
* Known-link recovery is documented.

## Tasks

Build a Septuagint ingestion adapter.

Create:

* Septuagint token table
* Septuagint passage table
* Hebrew-to-Septuagint alignment table
* Septuagint-to-New-Testament comparison features
* Versification crosswalk
* Alignment-confidence values

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

* Hebrew–Septuagint alignments are validated.
* Known New Testament quotations following the Septuagint are recovered.
* The system distinguishes Greek-mediated evidence from direct Hebrew evidence.
* Licensing and publication restrictions are documented.

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
8. Corpus-specific contrastive encoder
9. Semantic-domain vectors
10. Sparse concept vectors

Do not assume one representation is best.

## Evaluation requirements

Each representation must be benchmarked against:

* BM25
* TF-IDF
* Rare-lemma baseline
* Random retrieval
* Known quotations
* Known allusions
* Same-theme non-intertextual pairs

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
* One transparent detector provides exceptionally strong rare evidence
* It is not merely adjacent context
* It passes data-quality checks
* It is not already strongly represented in known-link sources
* It has identifiable textual evidence
* It has no unresolved training-data contamination

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
6. Is the chronology compatible with literary dependence?
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

## Experiment 3: Septuagint bridge

Goal:

Determine which New Testament relationships become stronger when the Greek Old Testament is used as the bridge.

Output:

* Hebrew–Greek–New Testament triangles
* Septuagint-dependent candidates
* Known quotation recovery
* Translation-sensitive cases

## Experiment 4: Semantic retrieval

Goal:

Find conceptually related passages lacking obvious lexical overlap.

Compare:

* Generic embeddings
* Literal-gloss embeddings
* Original-language embeddings
* Corpus-specific embeddings
* Sparse semantic-domain vectors

## Experiment 5: Independent detector agreement

Goal:

Identify candidates supported by lexical evidence plus at least one semantic, syntactic, or narrative detector.

This becomes the first serious candidate set.

## Experiment 6: Pauline case study

Research question:

> Which Pauline passages have strong computational relationships to sayings of Jesus, the Septuagint, and the Hebrew Bible that are weakly represented in conventional cross-reference systems?

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
* Do not conceal annotation disagreements.
* Do not conceal model-training exposure.
* Do not use textual variants as independent proof of intertextuality.
* Do not treat reception-history evidence as proof of original authorial intent.
* Do not optimize for impressive visualizations at the expense of methodological validity.

---

# 34. Milestone Plan for Codex

## Milestone 0: Repository foundation

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

Build:

* Research charter
* Source manifest schema
* Dataset manifest validator
* Licensing documentation
* Decision-log structure
* Literature-matrix template

Acceptance:

* Invalid manifests fail validation.
* Every initial source has a documented status.

## Milestone 2: Hebrew ingestion

Build:

* MACULA Hebrew adapter
* Hebrew normalization
* Token schema
* DuckDB loading
* Validation report

Acceptance:

* Complete Hebrew corpus loads.
* Stable token IDs exist.
* Spot checks pass.
* Reprocessing is deterministic.

## Milestone 3: Greek ingestion

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

Build:

* STEPBible adapter
* Annotation-alignment tables
* Conflict-preservation logic
* Versification crosswalks

Acceptance:

* Supplementary data never overwrites primary annotations.
* Annotation conflicts are queryable.

## Milestone 5: Passage segmentation

Build:

* Clause passages
* Sentence passages
* Verse passages
* Two-verse windows
* Five-verse windows
* Passage reconstruction

Acceptance:

* Passage boundaries validate.
* Every token belongs to expected passage units.

## Milestone 6: Known-link benchmark

Build:

* Known-relationship schema
* Benchmark importers
* Evaluation splits
* Negative examples
* Metrics

Acceptance:

* Benchmark can be generated and versioned.
* Leakage checks pass.

## Milestone 7: Lexical baseline

Build:

* TF-IDF
* BM25
* Rare-lemma scoring
* Phrase scoring
* Ordered-sequence scoring
* Candidate evidence generation

Acceptance:

* Known-link recovery exceeds random and simple overlap baselines.
* Candidate evidence is interpretable.

## Milestone 8: First unknown-candidate review

Build:

* Known-link exclusion
* Candidate-ranking output
* Manual-review CSV or basic console
* False-positive taxonomy

Acceptance:

* Top 100 candidates reviewed.
* Main false-positive patterns documented.
* Scoring changes, if any, are recorded as a new experiment.

## Milestone 9: Septuagint bridge

Build:

* Septuagint adapter
* Alignment tables
* Cross-language retrieval
* Triangulated evidence reports

Acceptance:

* Known Septuagint-mediated relationships are recovered.
* Alignment quality is documented.

## Milestone 10: Semantic retrieval

Build:

* Representation pipeline
* Embedding benchmarks
* Nearest-neighbor index
* Hard-negative evaluation
* Training-lineage tracking

Acceptance:

* Semantic methods add measurable value beyond lexical methods.
* No evaluation leakage exists.

## Milestone 11: Syntactic and narrative engines

Build:

* Predicate–argument representation
* Syntactic features
* Event sequences
* Narrative similarity

Acceptance:

* Known structural or narrative relationships are recoverable.
* Generic genre templates are controlled.

## Milestone 12: Anomaly and structural engines

Build:

* Anomaly features
* Change-point analysis
* Structural sequence analysis
* Randomized controls

Acceptance:

* Scores are calibrated.
* Results are not dominated by passage length or genre.

## Milestone 13: Candidate ensemble

Build:

* Score normalization
* Detector-family grouping
* Surprise scoring
* Knownness penalty
* Candidate eligibility logic

Acceptance:

* Ensemble results retain raw evidence.
* No opaque model dominates without explanation.

## Milestone 14: Review console

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

Build:

* Study-specific configuration
* Jesus–Paul analysis
* Hebrew Bible–Paul analysis
* Septuagint–Paul analysis
* Pauline anomaly analysis
* Research dossiers

Acceptance:

* Findings meet minimum publishability standards.
* Strong candidates receive outside linguistic review where possible.

## Milestone 16: Whole-canon run

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
9. Implement Hebrew validation.
10. Add MACULA Greek acquisition instructions.
11. Implement Greek ingestion.
12. Implement Greek validation.
13. Create the unified token table.
14. Add STEPBible supplementary annotations.
15. Build the annotation-conflict layer.
16. Build the versification crosswalk.
17. Generate clause, sentence, verse, two-verse, and five-verse passages.
18. Create benchmark schemas.
19. Import known relationships.
20. Create evaluation splits.
21. Implement TF-IDF.
22. Implement BM25.
23. Implement rare-lemma scoring.
24. Implement phrase and sequence scoring.
25. Evaluate known-link recovery.
26. Generate unknown lexical candidates.
27. Review the top 100.
28. Document false positives.
29. Audit and ingest the Septuagint.
30. Build Hebrew–Septuagint alignments.
31. Build Septuagint–New-Testament comparison.
32. Evaluate Septuagint-mediated known links.
33. Add semantic models.
34. Evaluate semantic models.
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
