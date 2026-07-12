# 0010 - Select pinned MACULA Greek Nestle1904 node data

- Status: Accepted
- Date: 2026-07-11
- executing_agent: Claude

Edition selection reviewed and ratified by project owner on 2026-07-11.

## Context

Milestone 3 requires a complete Greek New Testament primary corpus with
morphology, syntax, semantic information, source identity, and reproducible
acquisition. The official MACULA Greek repository offers multiple textual
representations (Nestle1904 and SBLGNT directories, each with tei, nodes,
lowfat, and TSV forms), changing releases, and an untagged `sblgnt-trees`
side branch. The prior manifest record provisionally selected an "SBLGNT v1.2
representation" while explicitly leaving the branch, release, and annotation
completeness unverified.

Verification against the pinned release resolved those questions:

- The newest tagged release is `24.06.17`, commit
  [`b5b7ecec0882a3e9a609ecac99e157391e5d9b46`](https://github.com/Clear-Bible/macula-greek/commit/b5b7ecec0882a3e9a609ecac99e157391e5d9b46).
- The release's `LICENSE.md` (read from canonical bytes) licenses the MACULA
  Greek Linguistic Datasets © 2022-2024 Biblica, Inc under CC BY 4.0 with a
  required attribution sentence, and enumerates component datasets: the
  Nestle1904 text (published 1904 by the British and Foreign Bible Society;
  transcription by Diego Santos, morphology by Ulrik Sandborg-Petersen, markup
  by Jonathan Robie), SBLGNT data from Logos (the license notes the SBLGNT
  license "was recently updated to CC-BY-4.0"), MARBLE word-sense data used
  with permission, Berean Interlinear glosses (public domain as of
  2023-04-30), and Cherith glosses (CC BY 4.0).
- The release's `SBLGNT/README.md` documents that the SBLGNT representation
  was produced by migrating word-level data from the N1904 edition, that
  SBLGNT-only readings are marked `status="unmapped"` or
  `status="refs-mapped"`, and that supplying missing `Gloss`, Louw-Nida, and
  `Domain` values for those nodes is listed as future work. The SBLGNT
  representation therefore has documented annotation gaps.
- The upstream test suite at the pinned commit asserts 137,779 leaf word
  nodes for the Nestle1904 nodes dataset
  (`test/test_nestle1904_nodes.py`).
- Sampled Nestle1904 node files carry complete identity and annotation
  attributes on every leaf (xml:id, ref, morphId, UnicodeLemma,
  FunctionalTag, FormalTag, NormalizedForm, Unicode, Cat, Gloss), one leaf
  node per source word reference, and one syntax tree per sentence.

## Decision

Use the official [Clear Bible MACULA Greek repository](https://github.com/Clear-Bible/macula-greek)
at release `24.06.17`, resolved to exact commit
`b5b7ecec0882a3e9a609ecac99e157391e5d9b46`. The textual edition is the
**Nestle 1904 Greek New Testament** as represented by that release's
`Nestle1904` dataset. This supersedes the provisional SBLGNT v1.2 selection.

Acquire only `README.md`, `LICENSE.md`, and `Nestle1904/nodes` through an
exact-commit sparse checkout with canonical-byte handling
(`core.autocrlf=false`, `* -text`). The governed inventory contains 29 files:
the two notices and 27 book node files. Validate the three tracked anchor
hashes (README, LICENSE, and the Jude node file) and record a local
SHA-256-and-size receipt for every file.

Use the node XML representation as the Milestone 3 adapter input, mirroring
the Hebrew decision (ADR 0005). Preserve all leaf attributes and syntax
ancestry in canonical JSON rather than dropping unmapped values.

The source remains governed as follows:

- machine processing is permitted (CC BY 4.0 aggregate with attribution);
- raw files and full processed token tables remain Git-ignored and local;
- public redistribution is limited to acquisition instructions, attribution,
  checksums, aggregate statistics, validation findings, and non-textual
  schema information until a separate field-level review approves more —
  in particular MARBLE-derived `LN` and `LexDomain` values are included
  upstream by permission and need their own derived-output review;
- the Nestle1904, SBLGNT, UBS/MARBLE, Berean, and Cherith notices applicable
  to used fields must be preserved.

## Rationale

The Nestle1904 dataset is the release's native, annotation-complete
representation: its trees, morphology, senses, glosses, and participant data
were authored against the N1904 text, whereas the SBLGNT representation is a
documented partial migration with attribute gaps at unmapped readings. The
base text (Nestle 1904) is a public-domain edition, avoiding the residual
edition-rights questions a modern critical text carries. The pinned release
reproduces the upstream expectation of 137,779 leaf word records, giving the
same auditable count anchor the Hebrew corpus has (475,911).

Selecting the tagged release rather than `main` keeps corpus identity
immutable; selecting nodes rather than lowfat/TSV keeps the syntax hierarchy
required by the canonical mapping, mirroring ADR 0005.

## Consequences

- The corpus base text differs from the provisional SBLGNT intent. Any later
  move to an SBLGNT-based corpus is a new source version requiring a new
  review, new checksums, full validation, and a superseding ADR — never a
  silent replacement.
- Edition-level versification follows Nestle 1904: verses that the edition
  omits and the inline pericope adulterae (JHN 7:53-8:11, 190 leaf tokens at
  the pinned commit) are recorded exactly as the edition supplies them and
  flagged for human interpretation rather than harmonized.
- The node structure has no formal XSD, so the adapter validates the observed
  structure and fails on unrecognized required structure.
- Punctuation is attached to leaf word text in this representation; the
  normalization layer separates it in derived forms while preserving the
  original surface string byte-for-byte.
- Full token tables are reproducible locally but are not approved for
  publication by this decision.

## Alternatives considered

- **Use the SBLGNT representation in the same release**: rejected for
  Milestone 3 because upstream documents incomplete Gloss/LN/Domain coverage
  at `unmapped`/`refs-mapped` nodes, and the SBLGNT text adds a second
  edition-license layer without an annotation-completeness benefit.
- **Use the untagged `sblgnt-trees` branch**: rejected because it is mutable
  and not a governed release.
- **Use the mutable `main` head (8423afe)**: rejected because it would permit
  silent textual, annotation, and licensing changes.
- **Use `lowfat` or `TSV`**: rejected because the node representation better
  preserves the hierarchy required by the canonical mapping, mirroring the
  Hebrew selection.
- **Commit raw or processed corpus data**: rejected under the conservative
  redistribution and provenance policy.
