# 0005 - Select pinned MACULA Hebrew node data

- Status: Accepted
- Date: 2026-07-10

## Context

Milestone 2 requires a complete Hebrew and Aramaic primary corpus with morphology,
syntax, semantic information, source identity, and reproducible acquisition. The
official MACULA Hebrew repository offers multiple representations and changing
releases. Selecting a mutable branch, silently taking the latest release, or using
a representation that omits hierarchy would make token counts and provenance
unstable.

The current aggregate also contains components with distinct attribution terms.
Releases published after 25.08.11 add SILHA-derived material that requires a new
licensing decision. The raw text and full processed tables therefore need a
conservative local-only policy even though machine processing of the selected
aggregate is permitted.

## Decision

Use the official [Clear Bible MACULA Hebrew repository](https://github.com/Clear-Bible/macula-hebrew)
at release `25.08.11`, resolved to exact commit
[`7ab368fcb14e4ad2e0f784138241a098fb516ec4`](https://github.com/Clear-Bible/macula-hebrew/commit/7ab368fcb14e4ad2e0f784138241a098fb516ec4).
The textual edition is Westminster Leningrad Codex 4.20 as represented by that
MACULA release.

Acquire only `README.md`, `LICENSE.md`, and `WLC/nodes` through an exact-commit
sparse checkout. The governed inventory contains 932 files: the two notices, 929
chapter node files across 39 books, and the node XInclude index. Validate the three
tracked anchor hashes and record a local SHA-256-and-size receipt for every file.

Use the node XML representation as the Milestone 2 adapter input. For a sentence
with multiple upstream syntax analyses, map the first tree and retain the count of
alternatives in source extras. Preserve all morpheme attributes and syntax ancestry
in canonical JSON rather than dropping unmapped values.

The source remains governed as follows:

- machine processing is permitted;
- raw files and full processed token tables remain Git-ignored and local;
- public redistribution is limited to acquisition instructions, attribution,
  checksums, aggregate statistics, validation findings, and non-textual schema
  information until a separate field-level review approves more;
- the WLC, Open Scriptures Hebrew Bible, Groves Center, Cherith Analytics, and
  UBS/SDBH notices applicable to used fields must be preserved.

## Rationale

The node representation retains the syntax hierarchy and source attributes needed
for the canonical token and provenance contracts. The pinned release reproduces
the upstream expectation of 475,911 morpheme records across 39 books and 929
chapters. Its exact commit, complete receipt, typed adapter, and fixed expected
count make acquisition and reprocessing auditable.

Release 25.08.11 deliberately predates the later SILHA integration. This avoids
silently accepting an additional licensing layer during Hebrew ingestion. It also
predates later upstream Unicode fixes, but Project Echoes preserves the original
surface string and applies documented Unicode handling only to derived forms.

## Consequences

- The selected node structure has no formal XSD, so the adapter validates the
  observed filenames, references, identifiers, morphology format, and hierarchy
  and fails on unrecognized required structure.
- Native `xml:id` is preferred; an available native `n` is retained with a
  warning when `xml:id` is absent. Missing both is fatal.
- The representation normally prefers Qere and does not provide a complete
  parallel Ketiv layer. Project Echoes preserves variants that are present but
  does not reconstruct absent readings.
- The release pin is part of corpus identity. Upgrading, including to a 2026
  SILHA-bearing release, requires a new source and license review, new checksums,
  full validation, and a superseding ADR.
- Full token tables are reproducible locally but are not approved for publication
  by this decision.

## Alternatives considered

- Use the mutable default branch or newest release: rejected because it would
  permit silent textual, annotation, Unicode, and licensing changes.
- Use a 2026 release with SILHA glosses: rejected for Milestone 2 because the
  additional terms have not received the required field-level review.
- Use `WLC/tsv`: rejected because it does not retain the node syntax hierarchy
  required by the canonical mapping.
- Use `WLC/lowfat`: rejected because the node representation better preserves the
  selected native hierarchy and because upstream issue
  [#65](https://github.com/Clear-Bible/macula-hebrew/issues/65) documents an ID-loss
  risk in a lowfat conversion path.
- Commit raw or processed corpus data: rejected under the conservative
  redistribution and provenance policy.
