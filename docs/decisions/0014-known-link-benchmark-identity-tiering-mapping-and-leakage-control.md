# 0014 — Known-link benchmark identity, tiering, mapping, and leakage control

- Status: Accepted
- Date: 2026-07-12
- executing_agent: Codex
- Owner authorization: The project owner authorized this decision and its
  Milestone 6 implementation through the current goal before execution.

## Context

Milestone 6 must create reproducible infrastructure for known-link recovery
without turning a broad cross-reference graph into scholarly ground truth or
starting Milestone 7 retrieval. The selected OpenBible archive is a directed
verse-reference graph with signed ranking votes. It mixes thematic, verbal,
event, and person links, uses an English-reference scheme, and is updated at a
mutable URL. Project Echoes also has a governed but intentionally empty Tier 1
quotation CSV. Both sources therefore require explicit identity, tier, mapping,
leakage, and publication boundaries before they can support experiments.

## Decision

### Tiers and permitted source roles

The benchmark has three evidence tiers. Tier 1 is independently reviewed,
human-curated explicit quotation evidence; its canonical CSV remains header-only
during Milestone 6. Tier 2 is reserved for later curated allusion or literary
relationship evidence. OpenBible is Tier 3 weak supervision and broad knownness
support only. It is eligible for infrastructure splits, weak-supervision recovery,
and known-link filtering, but never primary evaluation, Tier 1 promotion, or
scholarly ground truth. Benchmark sources must have an approved benchmark role,
compatible machine-processing terms, preserved attribution, and a pinned version.

### Stable identity and source provenance

Every raw occurrence receives a source-record identity derived from the identity
schema, source ID, complete snapshot hash, exact canonical record bytes, and a
deterministic duplicate-occurrence ordinal. Source line number remains provenance
and is not identity. Identical occurrences are retained rather than discarded.

A relationship identity is independently derived from its identity-schema
version, source ID and version, preserved reference scheme, normalized ordered
endpoints, and source direction. It excludes passage IDs, weights, mappings,
splits, row numbers, paths, timestamps, and random values. Duplicate directed
records aggregate deterministically into one relationship while retaining every
relationship-to-source-record link and weight statistic.

The source direction is preserved. A separate directed-pair identity supports
exact-pair grouping, while a lexically ordered undirected-pair identity makes
reverse relationships inspectable without silently symmetrizing the graph.
Votes remain signed source ranking fields; they are not calibrated confidence or
probabilities of literary dependence.

Mapping identity is separate from relationship identity and may include endpoint
identity, target corpus/profile/reading/granularity, method, crosswalk version,
and exact ordered target passage IDs. A mapping correction can therefore change a
mapping identity without rewriting source relationships.

### References, ranges, and passage mapping

OpenBible reference strings and their source scheme are always retained. The
Milestone 6 target is the Milestone 5 `edition_complete` verse layer: Hebrew and
Aramaic use the Qere reading, and Greek uses the source reading. No clause,
sentence, two-verse, or five-verse passage becomes a direct benchmark positive.

Single verses and supported ranges map only to exact, ordered, extant verse
passages. Missing verses are never fabricated. A partial range, invalid or
unsupported reference, edition omission, disputed passage, reference gap, and
`critical_core` exclusion remain explicit statuses or flags. Cross-book and
backward ranges are preserved as source evidence but are not forced into a target
mapping.

Identical Old Testament labels are useful mechanical joins but, without an
approved versification crosswalk, are `mapped_provisional` by
`same_label_extant_reference`. They remain limited to Tier 3 weak supervision and
knownness use. New Testament same-label mappings are also conservative unless a
governed scheme crosswalk supports stronger confidence. Crosswalks never rename
source relationships, passages, or tokens.

### Leakage and splits

The benchmark emits distinct leakage groups for directed and undirected pairs,
duplicate provenance families, shared endpoints, overlapping source ranges,
shared or overlapping target passages, canonical book pairs, and relevant source
provenance. Future quotation or relationship-family fields exist as contracts but
are not invented for OpenBible. One unrestricted graph connected component is not
the leakage model because hub verses could collapse most of the graph.

Splits are deterministic, versioned, and group-based. Supported strategies hold
out books, book pairs, source passages, and broad project-defined analysis genres.
The relationship-family strategy reports unsupported when the source lacks those
labels. Unmapped rows are excluded with reasons from mapping-dependent strategies.
No random row-level split is permitted, and every enforced leakage group must stay
within one partition.

### Presumed negatives and metrics

Milestone 6 may generate deterministic verse-level presumed negatives using only
length, book, book-pair, broad genre, source order, and known-link indexes. Every
pair is checked in both directions against known positives, for passage overlap,
and against its split/leakage constraints. Absence from OpenBible and the empty
Tier 1 file is never proof of nonrelationship; the label is always
`presumed_negative`. Lexical, thematic, formulaic, semantic, embedding, and model
features are deferred.

Metric code defines and fixture-tests recall at 5/10/20, reciprocal rank,
nDCG@20, precision at 10/configurable K, coverage, and governed strata. Metric
outputs must state benchmark version, tier, mapping eligibility, split, label
quality, eligible/excluded queries, and exclusion reasons. OpenBible-only metrics
must say “Tier 3 weak-supervision recovery,” not benchmark truth. No real retrieval
model is run in Milestone 6.

### Storage, determinism, and publication

The ten normalized benchmark artifacts use explicit Pydantic and Polars schemas,
stable sorting, typed Parquet, logical and physical hashes, atomic replacement,
and transactionally materialized/indexed DuckDB tables and views. Generated data
lives under ignored local storage; `--force` may replace only generated benchmark
artifacts and never bypass governance or hashes. Raw archives, extracted source,
full normalized tables, local databases, and biblical quotation text are not
committed.

The atomic write boundary includes split assignments and presumed negatives.
`ingest-benchmark` is the sole command that stages, validates, and promotes the
complete artifact set. The separately named `generate-benchmark-splits` and
`generate-presumed-negatives` commands verify the corresponding stages already
materialized by ingestion; they do not independently mutate or replace those
tables. This prevents a benchmark version from combining relationships with
splits or negatives generated under a different configuration.

Run identity includes governed configuration, complete source hashes, the Tier 1
header hash, and fixed corpus/passage anchors. Runtime, local paths, acquisition
timestamps, and environment telemetry do not affect logical identity. Two builds
from the same acquired snapshot must reproduce the run ID and logical hashes.

OpenBible material is attributed to OpenBible.info with its official source URL,
CC BY 4.0 link, snapshot identity, and modification notice. Separately copyrighted
ESV page quotations are excluded; the approved archive contains only references
and integer votes. Project-authored Tier 1 metadata may later be released under
its declared terms, but no third-party biblical text or copyrighted quotation
appendix is relicensed or ingested by this decision.

### Validation record (2026-07-13)

The exact OpenBible snapshot passed two complete builds. Both produced run
`benchmark-v1-dff1d3ef650c8ccd4930`, version
`known-links-v1-dff1d3ef650c`, 344,799 relationships, 689,598 endpoints,
1,379,196 mappings, 4,561,525 leakage memberships, 1,723,995 split assignments,
29,275 presumed negatives, 18 informational issues, and one metadata row.
Mapping statuses were 639 profile exclusions, 781 partial, 1,371,984
provisional, 5,756 missing-target, and 36 unresolved-reference mappings; corpus
pairs were 187,117 OT–OT, 84,369 NT–NT, and 73,313 cross-testament.

The builds had zero logical-hash, count, or content-table physical-hash
differences. Metadata physical bytes differed only by expected runtime telemetry;
wall times were 551.3 and 533.7 seconds, persisted runtimes were
501.93041979987174 and 479.37766140000895 seconds, and each footprint was
672,790,515 bytes. Strict validation returned zero errors, zero warnings, and 18
informational findings on each build. The source manifest therefore advances
from `approved` to `validated` without changing OpenBible's Tier 3 role,
mapping-confidence ceiling, license boundary, or publication policy. Pull-request
and CI evidence remain outside this local validation record until available.

## Consequences

- Milestone 7 can measure recovery by tier and mapping confidence without source
  labels leaking randomly across partitions.
- Tier 3 provides broad knownness evidence but cannot by itself establish a
  quotation, allusion, novelty, or literary dependence claim.
- The project still lacks a populated high-confidence primary benchmark.
- Same-label mappings remain queryable and useful while their versification
  uncertainty is visible.
- Negative sampling and metric contracts can be tested before any retrieval
  features or scores exist.
- Storage is reproducible locally without publishing bulk source or corpus data.

## Alternatives considered

- Treat OpenBible as scholarly truth or primary evaluation: rejected because its
  heterogeneous links and votes do not support those claims.
- Automatically promote OpenBible rows to Tier 1, populate Tier 1, or use an LLM
  to verify them: rejected; Tier 1 requires human curation, independent review,
  and row-level lawful provenance.
- Treat votes as calibrated confidence: rejected; they are mutable relevance
  ranking signals blended from source and user votes.
- Assume all links are inherently directed or undirected, or silently symmetrize
  them: rejected; source direction and a separate unordered view are both kept.
- Drop duplicate records: rejected because source occurrence provenance and
  conflicting weights must remain auditable.
- Call same-number OT references verified mappings: rejected without an approved
  external versification crosswalk.
- Fabricate missing verses or force partial/cross-book ranges: rejected because it
  would falsify the target edition.
- Derive relationship identity from mutable passage IDs: rejected because later
  segmentation changes would rewrite source evidence.
- Use random row-level train/test splits or separate duplicates/leakage families:
  rejected because known evidence would leak across partitions.
- Call unlinked pairs proven negatives: rejected because source absence is not
  evidence of nonrelationship.
- Ingest UBS, Nestle-Aland, or comparable copyrighted quotation appendices:
  rejected without explicit permission.
- Generate lexical similarity, embeddings, retrieval candidates, or other
  Milestone 7 features now: rejected as outside this milestone.
