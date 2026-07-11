# 0006 - Derive canonical Hebrew token identifiers from reference and segmentation

- Status: Accepted
- Date: 2026-07-10

## Context

Project Echoes needs stable token identifiers for joins, validation, experiments,
and scholarly traceability. MACULA supplies native morpheme IDs, word references,
XML order, and multiple morphemes at some word locations. Native IDs must be
preserved, but using them as project IDs would couple every downstream table to a
source-specific namespace. Generated dataframe row numbers or XML traversal order
would be unstable and would not communicate canonical location.

## Decision

For the Hebrew/Aramaic corpus, derive each project identifier from canonical book,
chapter, verse, native word position, and, only where needed, the deterministic
within-word morpheme position:

```text
HB_<BOOK>_<CHAPTER:3>_<VERSE:3>_<WORD:4>[.<SUBTOKEN:2>]
```

Examples of the shape are `HB_GEN_001_001_0001` for a single-morpheme word
location and `HB_GEN_001_001_0001.01` for the first of multiple morphemes sharing
that location.

Sort native records by registered book order, chapter, verse, native word
position, and native record ID before assigning within-word, verse, clause, and
corpus positions. A multi-morpheme group receives `.01`, `.02`, and later suffixes
in that order. A single-morpheme group keeps the unsuffixed base ID.

Preserve identity from both namespaces on every row:

- `token_id` is the Project Echoes identity;
- `source_record_id` is native `xml:id`, or native `n` through an explicit warning
  fallback;
- `source_word_id` retains the native `BOOK chapter:verse!word` value;
- `source_row_reference` joins the relative source file and record ID;
- `source_id` and exact `source_version` identify the dataset.

Reject duplicate project IDs, native IDs, verse positions, and corpus positions.
Do not append an arbitrary collision counter or silently discard a record.

## Rationale

The chosen identity is readable, canonically located, deterministic under input
file or XML traversal reordering, and independent of generated table row numbers.
The subtoken suffix preserves source segmentation without conflating multiple
morpheme records at one word position. Retaining native identity separately keeps
the complete source trace and allows source-specific investigation without making
downstream project tables use a MACULA-only key.

## Consequences

- `position_in_corpus` and `position_in_verse` are ordering fields, not identity.
  Recomputing row layout does not by itself rename a token.
- A source-edition change that moves a reference, renumbers a word, or changes
  morpheme segmentation may legitimately change token IDs. Such changes require a
  versioned migration and determinism report; IDs are not promised stable across
  different source editions.
- Source-record IDs provide the tie-breaker among morphemes at one word position.
  An upstream change to those IDs can alter subtoken suffix assignment and must be
  reviewed as a corpus change.
- Zero-width morphemes receive normal canonical IDs and positions. Their explicit
  empty form does not make them anonymous or disposable.
- Greek identifiers are deferred to Milestone 3 and must use their own corpus
  prefix while preserving the same provenance principles.

## Alternatives considered

- Use native `xml:id` as `token_id`: rejected because it is source-specific and
  does not encode canonical location; it remains preserved as provenance.
- Use source word references alone: rejected because several morphemes can share
  one word location.
- Use sequential row numbers or `position_in_corpus`: rejected because identity
  would depend on row ordering and insertions elsewhere in the corpus.
- Hash the complete source record: rejected because the IDs would be opaque and
  would change for any annotation edit even if token identity remained the same.
- Silently add suffixes only after a collision occurs: rejected because collisions
  must reveal a data or mapping problem rather than be patched after the fact.
