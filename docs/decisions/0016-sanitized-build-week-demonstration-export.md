# 0016 — Sanitized Build Week demonstration export

- Status: Accepted
- Date: 2026-07-17
- executing_agent: Codex
- Owner authorization: The project owner authorized a tracked, versioned
  Build Week demonstration export through the active Milestone 7 continuation
  goal.

## Context

The Build Week handoff needs real Milestone 7 recoveries, unreviewed
candidates, null comparisons, and textual-uncertainty examples in a small
tracked bundle. The full lexical Parquet artifacts, sparse indexes, database,
source tokens, and complete annotations remain local and Git-ignored.

The pinned MACULA source determinations permit local machine processing but
deliberately do not approve tracked publication of complete processed token or
annotation tables. MACULA Greek also retains an unresolved field-level
publication question for permission-only component annotations. A public
demonstration must therefore remain useful without exposing reconstructable
text or annotation values. OpenBible relationship metadata may be redistributed
with attribution under its recorded CC BY 4.0 determination, but the
demonstration does not need its raw graph or any ESV quotation text.

The export occurs only after the frozen experiment has selected thresholds,
evaluated Tier 3 recovery, run both null families, and passed strict artifact
validation. Selecting bounded examples for presentation must not tune the
experiment or become candidate review.

## Decision

Create export schema version 1 at `demo/data/echoes-demo-v1/` with:

- `overview.json`
- `known-recoveries.json`
- `unreviewed-candidates.json`
- `textual-uncertainty-examples.json`
- `manifest.json`

Public lexical evidence is represented by stable feature IDs, feature family,
token-relative positions, corpus and document frequencies, local frequencies,
association and independence values, detector scores and ranks, null
comparisons, candidate/evidence identities, references, mapping quality, and
uncertainty flags. The stable ID is the public representation of a lemma, root,
phrase, or skip-gram. Its source value remains available only in the validated
local research artifacts.

The public schema prohibits:

- lemma, root, surface, morphology, or English-gloss values;
- source or reconstructed biblical text and excerpts;
- raw source or OpenBible records;
- source filenames, local paths, and private processed-data paths;
- detector component payloads or free-form notes that could carry source
  values;
- original Hebrew, Aramaic, or Greek script anywhere in the JSON bundle.

Only original-language HB–HB and GNT–GNT candidates enter the public pair
lists. English-gloss-mediated HB–GNT results remain in the private scientific
reports and are excluded from these lists.

Known recoveries use a fixed corpus-balanced selection: the ten
highest penalty-adjusted RRF pairs in each original-language corpus pair after
requiring representation in the pinned OpenBible snapshot and shared
lemma/root evidence. Unreviewed candidates use the first fifty eligible,
OpenBible-unrepresented original-language rows in the frozen queue, ordered by
queue rank and candidate ID. Requested counts are upper bounds; the exporter
reports the actual count and never fabricates a row.

Textual uncertainty uses the first deterministic Qere/Ketiv sensitivity row
after ordering comparable rows first, then absolute score change, then
sensitivity ID. It applies the same rule to a critical-core row incident to a
governed disputed passage when one exists. These examples expose identities,
scores, ranks, locus counts, exclusions, and sequence digests, not text or a
text-critical interpretation.

Every data file is canonical JSON. `manifest.json` binds the lexical, passage,
and benchmark runs; configuration and preregistration hashes; source
attribution; export counts; and SHA-256 of every other generated file. The
exporter writes behind an atomic directory boundary and refuses silent
overwrite.

A recursive fail-closed validator and tests reject every unexpected or
prohibited field, original-script text, absolute local path, or private
data-path fragment. The bundle states that no candidate review occurred and
that Milestone 8 did not begin.

## Rationale

Stable IDs plus positions, frequencies, scores, and hashes provide auditable
evidence that can be resolved against a validated local run without publishing
recoverable corpus content. Deterministic selection demonstrates the method
without choosing examples for theological interest or changing a held-out
threshold after inspection. A strict allowlist is safer than attempting to
sanitize arbitrary research rows after serialization.

This boundary is deliberately narrower than the broadest possible reading of
the source licenses. It satisfies the current demonstration need without
resolving wider public-release questions prematurely.

## Consequences

- The demo can truthfully show real lexical retrieval and calibration while
  remaining small and non-reconstructive.
- Viewers see feature identities rather than original-language strings. A
  future publication may add limited strings only after a separate
  field-level determination and a new export schema.
- Absence from the pinned OpenBible snapshot is labeled only as bounded
  knownness, never novelty.
- Export selection is presentation, not candidate review; no acceptance,
  rejection, literary classification, or interpretive decision is stored.
- If the frozen scientific or strict validation gate fails, the result remains
  reportable, but the exporter cannot imply Milestone 7 completion.
- The tracked export does not begin Milestone 8.

## Alternatives considered

- Publish source lemma/root strings or short excerpts: rejected for schema
  version 1 because the required field-level publication determination is not
  complete.
- Publish full candidate or shared-evidence rows and remove a short denylist:
  rejected because free-form fields and component payloads can carry
  reconstructable annotations.
- Select examples manually for visual appeal: rejected because it would blur
  the frozen experiment and human-review boundary.
- Reduce the original Milestone 7 experiment for the contest deadline:
  rejected because the full registered implementation is already
  substantially complete.
