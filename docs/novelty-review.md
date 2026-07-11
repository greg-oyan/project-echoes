# Literature, knownness, and novelty review

Status: **Milestone 1 procedure**
Date: 2026-07-10

Novelty is a documented search conclusion, not a model prediction. This procedure governs the project-level literature review and the later candidate-specific knownness workflow.

## Literature-review process

1. Search bibliographic databases, publisher indexes, proceedings, repositories, project sites, and citation networks across the fields named in the master plan: quotation/text-reuse detection, semantic retrieval in ancient languages, type-scenes, chiasmus, stylometry/authorship, Hebrew–Greek alignment, Septuagint and translation effects, cross-reference graphs, ancient-language embeddings, LLM-assisted scholarship, computational literature, statistical phrases, and formulaic language.
2. Record every reviewed item in [`data/review/literature_matrix.csv`](../data/review/literature_matrix.csv), including search status, accessible code/data, evaluation, claims, and limitations.
3. Prefer the primary paper, official project page, repository, DOI record, and archived data. Secondary descriptions guide discovery but do not establish project capabilities.
4. Record search database, date, query, filters, results screened, and inclusion/exclusion reason in later literature-search records.
5. Revisit searches before publication because projects, releases, and accessible scholarship change.

The seed matrix contains five verified primary-source precedents. It is not a complete literature review.

## Selecting the five closest prior projects

Candidates are scored qualitatively on overlap with:

- Original-language biblical data.
- Whole-corpus, all-pairs, or otherwise broad computational scale.
- Undirected rather than only source-query-led discovery.
- Lexical, semantic, grammatical, narrative, structural, or anomaly detector families planned by Project Echoes.
- Known-link benchmarks, leakage controls, and hard negatives.
- Reproducible code/data and explicit evaluation.
- Human review, error analysis, and retention of rejected outputs.

The current comparison is in [prior-projects.md](prior-projects.md). A closer project discovered later replaces an entry through a normal documented update; it does not threaten the validity of reproducible component work.

## Candidate-specific knownness review

Later candidate review proceeds through three levels:

1. Versioned machine-readable cross-reference and parallel collections.
2. Curated intertextual resources and book- or corpus-specific indexes.
3. Recorded scholarship searches using passage references, distinctive lemmas/phrases, phenomena, and alternative source passages.

Every search records exact sources, versions or access dates, queries, filters, citations reviewed, relevant results, reviewer, and limitations. Knownness labels K0–K4 are defined in the [research charter](research-charter.md). Search incompleteness defaults to K4 rather than K3.

## Calibrating novelty claims

Project-level novelty may concern an integration, scale, evaluation design, or review workflow even when every component algorithm is established. Conversely, combining familiar methods does not automatically create a meaningful scholarly contribution. The integration must demonstrate reproducibility, complementary detector value, controlled false positives, and useful evidence that previous workflows did not provide.

The provisional statement is therefore deliberately scoped:

> Project Echoes integrates multiple computational methods to conduct an undirected, whole-corpus search for candidate biblical relationships that are not represented in the reference collections checked by the project.

It does not say Project Echoes is the first computational Bible project, that its methods are individually new, or that every returned candidate is new.

## “Not found” is not “never discovered”

A search can miss paywalled scholarship, publications in other languages, print-only commentary, variant references, unpublished teaching, inaccessible databases, or terminology the reviewer did not anticipate. Consequently:

- Say “no match was found in the following sources using the following searches as of this date.”
- Never convert model ignorance or search failure into a universal historical claim.
- Include alternative spellings, references, lemmas, translations, and likely source passages.
- Preserve relevant near-matches and contrary evidence.
- Have the strongest candidates checked by a qualified specialist.

A candidate's scholarly value may lie in stronger linguistic evidence, computational ranking, a new cross-language explanation, or systematic context even when a related interpretive idea is already known.
