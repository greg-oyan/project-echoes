# 0008 - Apply approved methodological amendments

- Status: Accepted
- Date: 2026-07-10
- executing_agent: Codex

## Context

Milestone 2 established a deterministic Hebrew/Aramaic corpus, but several
methodological choices needed to be fixed before Greek ingestion could begin.
Token identity had to be insulated from later versification mappings; a
non-destructive Ketiv/Qere analysis policy was needed; and the benchmark,
Septuagint, statistical-calibration, semantic, chronology, output, and handoff
rules needed more explicit acceptance gates. Deferring these choices would allow
later data or model decisions to alter primary identity or bias evaluation.

## Approved methodological amendments

Project Echoes adopts the following rules:

1. Primary token identity derives only from the source edition's book, chapter,
   verse, source token/subtoken position, and source-record identity when needed
   to distinguish variants. A Milestone 4 versification crosswalk is a separate
   mapping layer and can never rename a primary token.
2. Ketiv and Qere records supplied by a source are both preserved with distinct
   stable identities, forms, provenance, a shared variant group, and an explicit
   default-reading flag. A configurable `qere` or `ketiv` analysis stream derives
   analytical positions without mutating stored records.
3. OpenBible cross-references are future Tier 3 weak supervision and broad
   knownness evidence, not scholarly ground truth or a sufficient positive
   benchmark. A separate project-curated Tier 1 quotation dataset will require
   row-level provenance and human verification.
4. Copyrighted quotation/allusion appendices are not copied into the benchmark
   without permission. Lawful manual consultation does not create reusable rows.
5. Version 1 Septuagint work uses verse/passage mappings through the separate
   crosswalk plus confidence-scored statistical lemma alignment. Token-level
   Hebrew-Septuagint alignment is out of scope. Printed-edition, transcription,
   morphology, alignment, raw-redistribution, derived-output, and attribution
   rights are reviewed separately before acquisition.
6. Lexical scoring requires repeated within-book reassignment and
   frequency-preserving synthetic-passage nulls. Reports include observed and
   null candidate counts, a 95% empirical interval, enrichment, empirical tail
   probability where appropriate, and estimated empirical false-discovery rate.
7. A lemma or root occurring at most the configured rare-evidence threshold
   cannot by itself create a review-eligible candidate; an independent co-signal
   is required. Hypergeometric values are simple baselines, while book- or
   genre-conditioned empirical calibration takes precedence.
8. English-derived supporting features must survive a registered no-English
   ablation before a candidate may remain `strong candidate`. Training a custom
   contrastive encoder is optional stretch work, not a Milestone 10 prerequisite.
9. Paul predates the written canonical Gospels. Paul-Jesus relationships begin as
   possible sayings-tradition, shared-tradition, scriptural, Septuagint, Hebrew,
   or other mediated relationships; direct written-Gospel dependence requires
   separate historical evidence.
10. Milestone 8 produces standalone Output J, documenting its Top-100 review,
    expected-noise baseline, accepted and rejected candidates, false-positive
    taxonomy, scoring lessons, and limitations.
11. `docs/master-plan.md` remains the sole implementation specification. Agent
    handoff files stay thin, every milestone exposes a blank owner-assigned time
    budget, and new decisions identify the executing agent.

## Corrections to the original amendment proposal

The approved form corrects potentially destructive or overbroad interpretations:

- it separates source-edition identity from later canonical crosswalks;
- it selects an analysis reading through a derived stream instead of deleting,
  rewriting, or renaming Ketiv/Qere records;
- it classifies OpenBible as Tier 3 rather than treating broad links as a sole
  high-confidence benchmark;
- it replaces similarity-invariant label or passage-order shuffles with nulls
  that actually break passage relationships while preserving stated marginals;
- it removes token-level Hebrew-Septuagint alignment from the version 1 promise;
- it treats a hypergeometric score as an uncalibrated baseline rather than a
  probability of literary dependence; and
- it makes the custom semantic encoder optional and qualifies Paul-Gospel
  directionality historically.

## Effect on milestones

- **Milestone 2:** schema and fixture behavior now guarantee source-edition-only
  identity and non-destructive Ketiv/Qere preservation plus derived positions.
- **Milestone 4:** owns versification crosswalks as external mappings that cannot
  change primary token IDs.
- **Milestone 6:** owns tiered benchmark governance, including empty Tier 1
  curation infrastructure and OpenBible Tier 3 classification.
- **Milestone 7:** must implement the specified repeated null families,
  calibration report, and configurable conjunctive rare-evidence rule.
- **Milestone 8:** must display expected noise and draft Output J before its gate.
- **Milestone 9:** must pass the edition/component licensing decision and use only
  version 1 passage/verse and confidence-scored lemma alignment.
- **Milestone 10:** must enforce English ablation while treating custom encoder
  training as optional.

No Greek, Septuagint, benchmark population, scoring, semantic, or review engine
is implemented by this decision.

## Consequences

The canonical schema version changes when the new variant and analysis-position
semantics enter storage. Existing full-corpus IDs must remain identical because
the pinned MACULA release supplies no paired Ketiv/Kethiv records. A future source
that supplies both readings can increase preserved-row counts without making the
analysis stream ambiguous. Later experiments carry stronger calibration and
ablation obligations, and the narrower Septuagint promise reduces version 1
alignment risk. New governance artifacts remain placeholders until their assigned
milestones; the Tier 1 CSV intentionally has no data rows.

## Alternatives rejected

- Use an English or crosswalk reference in token IDs: rejected because later
  mappings would mutate primary identity.
- Keep only the configured preferred Ketiv/Qere reading: rejected because it
  destroys source evidence and changes identity when configuration changes.
- Treat one rare word or an uncalibrated p-value as sufficient evidence: rejected
  because biblical vocabulary is structured and multiply tested.
- Use OpenBible or copyrighted appendices as definitive benchmark truth: rejected
  because their scope, curation, and rights do not support that claim.
- Require token-level Hebrew-Septuagint alignment or a custom encoder in version
  1: rejected as unnecessary for the stated milestone outcomes.
