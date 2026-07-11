# Corpus scope and layered data roles

Status: **Accepted for Milestone 1 governance**
Date: 2026-07-10

Project Echoes separates discovery texts, bridge texts, supplementary annotations, textual witnesses, reception history, benchmarks, and references. Adding a dataset creates a parallel governed layer; it does not automatically expand the primary discovery corpus.

## Layer map

| Layer | Initial content | Function | Activation boundary |
|---|---|---|---|
| Primary discovery | Hebrew/Aramaic Old Testament; Greek New Testament | Candidate generation and benchmark retrieval in original languages | After source approval, acquisition, ingestion, and corpus QA |
| Bridge | Septuagint | Hebrew–Greek–New Testament triangulation and translation-sensitive evidence | Only after primary corpus and known-link gates |
| Supplementary annotation | STEPBible and comparable approved resources | Glosses, mappings, semantics, names, morphology comparison, versification | Only selected fields with parallel provenance and conflict preservation |
| Textual validation | Biblical DSS, variants, apparatuses, alternative witnesses | Test stability and history of candidate wording | Only after strong candidates exist and rights are established |
| Reception history | Targums, other ancient and later interpretation | Test whether interpreters recognized or developed a relationship | Excluded from initial candidate generation |
| Benchmark/reference | Cross-reference and curated parallel collections | Recovery evaluation, knownness, and exclusion | After provenance, license, label, and leakage review |

## Primary discovery corpus

The first discovery boundary is the 66-book Protestant canon:

- Hebrew and Aramaic Old Testament.
- Greek New Testament.

This is a controlled first-experiment scope, not a claim about the legitimacy of other canonical traditions. Book names, order, chapter divisions, and verse numbering are normalized through explicit crosswalks without erasing source conventions.

MACULA Hebrew and MACULA Greek are the intended primary annotated sources because they expose token-level text, morphology, syntax, semantic information, participant references, and related annotations. Intention is not activation: both require a verified textual edition, field-level component provenance, pinned release or commit, licensing approval, reproducible acquisition, deterministic ingestion, and corpus validation. Hebrew/Aramaic and Greek source provenance remains distinct even in unified tables.

English translations may be displayed or used for glosses and comparison baselines. They are not primary evidence, and translation similarity alone cannot make a candidate eligible.

## Septuagint bridge corpus

The Septuagint is a Greek bridge between the Hebrew Bible and Greek New Testament. It is added only after:

1. Hebrew and Greek primary corpora pass completeness, provenance, tokenization, and reconstruction checks.
2. Transparent lexical methods recover held-out established relationships above baseline.
3. A separate Septuagint edition, provenance, license, morphology, tokenization, versification, and alignment review passes.

Its uses are direct Greek Old Testament–New Testament comparison, identifying Greek wording that mediates a relationship, mapping Hebrew and Greek lexemes, and distinguishing Hebrew-supported from translation-sensitive evidence. It is not initially searched as an independent additional canon. Books or passages outside the 66-book boundary remain excluded unless a later decision explicitly activates them for a defined purpose.

## Supplementary annotation layers

STEPBible and similarly permissive resources may contribute:

- English glosses and lexical definitions.
- Hebrew/Greek lexical mappings and reference identifiers.
- Semantic-domain or sense comparisons.
- Morphological comparison.
- Proper names, participants, and entity candidates.
- Versification evidence and book-name crosswalks.

These are annotations, not automatically independent textual witnesses. Each value retains source ID, version, source row, and confidence. If MACULA and a supplementary source disagree, both remain queryable. Reconciliation, if necessary, is a separate explicit layer selected by experiment configuration.

## Deferred textual-validation layers

The following remain inactive until strong candidates exist:

- Biblical Dead Sea Scrolls.
- Accessible textual-variant datasets.
- Hebrew and Greek critical apparatus information.
- Alternative ancient biblical witnesses.

Their role is to ask whether candidate-supporting wording is early, stable, variant, disputed, or a later development. Fragmentary witnesses require alignment confidence and uncertainty representation. Apparatuses are selective scholarly products and may be proprietary. Neither a variant nor an early witness independently proves literary dependence.

## Deferred reception-history layers

The following are excluded from initial candidate generation:

- Targums.
- Non-biblical Dead Sea Scrolls.
- Deuterocanonical literature.
- Pseudepigrapha.
- Rabbinic literature.
- Church Fathers and patristic commentary.
- Medieval and modern commentary traditions.

They may later show that an interpreter recognized, transmitted, or developed a proposed relationship. That is reception-history evidence, not direct evidence of original authorial intent. Deuterocanonical material may also be relevant to canonical or literary context, but activating it would be a separately governed research expansion.

## Parallel-layer rule

Availability never changes corpus role automatically. A new source must declare one role in its manifest and meet the activation rule in the [research charter](research-charter.md). Experiments state exactly which source and annotation layer they use. Derived tables preserve disagreements, source editions, licenses, and alignment confidence rather than collapsing them into an undocumented composite text.
