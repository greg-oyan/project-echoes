# 0007 - Preserve source forms and derive conservative Hebrew analytical forms

- Status: Accepted
- Date: 2026-07-10

## Context

Hebrew and Aramaic comparison benefits from both pointed and unpointed forms, but
normalization can erase textual, orthographic, segmentation, or variant evidence.
The master plan prohibits overwriting source forms and specifically requires
documented choices for cantillation, vowel points, maqqef, affixes, Ketiv/Qere,
final letters, divine names, Aramaic identity, and lemma namespaces.

The pinned MACULA Hebrew 25.08.11 release also predates later upstream Unicode and
combining-grapheme-joiner corrections. Rewriting its only stored form would hide
that provenance and make future source comparisons ambiguous.

## Decision

Store three explicit form layers for every non-zero-width token:

1. `surface_form` preserves the source `<m>` text exactly.
2. `normalized_form` applies NFD, removes U+034F COMBINING GRAPHEME JOINER, and
   collapses whitespace, while preserving cantillation and vowel points.
3. `unpointed_form` applies the same base transformation and then removes the
   explicitly configured Hebrew cantillation and vowel-point code points.

Keep maqqef, paseq, sof pasuq, other punctuation, final letters, orthographic
variants, prefix and suffix boundaries, Ketiv/Qere distinctions, and divine-name
forms unchanged. Do not split, join, or discard source morphemes. Preserve an
explicit zero-width source morpheme as a token with empty forms and a dedicated
flag.

Keep lemmas in the `macula` namespace and apply only the base Unicode and
whitespace transformation. Do not infer lexical roots or map lemmas to another
identifier system.

Prefer the native token-level language label. If it is absent or unknown, use the
adapter's explicit Aramaic-passage fallback and emit a warning for every inferred
row.

Record the complete normalization-configuration hash in corpus metadata and
validate stored derived forms by recomputing them from `surface_form`.

## Rationale

This policy provides a useful pointed form and a transparent consonantal form
without destroying the source witness. NFD gives deterministic mark handling;
removing only enumerated Hebrew marks is easier to audit than deleting all Unicode
combining characters. Keeping segmentation and reading-level distinctions intact
prevents a general preprocessing step from predetermining later lexical or
intertextual results.

Configuration, hashes, focused tests, and full-corpus recomputation make any
future methodological change visible in both provenance and outputs.

## Consequences

- Exact source-display work must use `surface_form`; derived comparison methods
  must name which analytical form they use.
- Canonically equivalent source strings can share a derived NFD form while their
  original code-point sequences remain distinguishable in `surface_form`.
- The unpointed view is not an unqualified "letters only" field: punctuation and
  nonconfigured marks remain by design.
- Prefix and suffix analysis uses MACULA's morpheme boundaries in Milestone 2.
  Alternative segmentation requires a new, parallel representation.
- The selected node source may provide a preferred Qere without a complete
  parallel Ketiv. Preservation means retaining available source distinctions, not
  reconstructing missing readings.
- A configuration change alters the ingestion run identity and processed hashes.
  It requires tests, a full deterministic rebuild, documentation, and a
  superseding ADR when the research meaning changes.
- Greek normalization remains planned and is not implied by this decision.

## Alternatives considered

- Normalize the source field in place: rejected because it destroys evidence and
  violates the governing provenance rule.
- Remove cantillation from `normalized_form`: rejected for the baseline because a
  separate unpointed view already supports mark-insensitive comparison while the
  minimally transformed form retains more information.
- Normalize final letters or collapse orthographic variants globally: rejected
  because such equivalences are method-dependent and can erase meaningful form
  differences.
- Split maqqef or resegment prefixes and suffixes during ingestion: rejected
  because it would replace rather than preserve the source segmentation.
- Collapse Ketiv/Qere to a preferred reading: rejected because variants must remain
  explicit where the source exposes them.
- Strip every Unicode combining mark: rejected because it is broader than the
  documented Hebrew mark policy and could remove unrelated information silently.
