# Segmentation

Status: **later-milestone placeholder with recorded edition constraints**.
Planned granularities are declared in `config/segmentation.yaml`; no passage
boundaries are generated before Milestone 5.

## Recorded verse-adjacency constraints (Milestone 4 Part 1)

`config/segmentation.yaml` carries a `non_contiguous_verse_adjacencies`
declaration for verse pairs that are numerically distant yet textually
adjacent in a pinned edition. Milestone 5 must enforce these when building
verse windows and spans; this milestone only records them with schema
validation and tests.

Declared constraints and their background:

- **MRK 16:20 -> MRK 16:99 (greek).** The pinned Nestle 1904 edition encodes
  the shorter ending of Mark as the pseudo-verse `16:99` immediately after
  the inline longer ending (16:9-20). Verse numbers 21-98 do not exist;
  sliding windows must treat 16:20 and 16:99 as adjacent or exclude the
  pseudo-verse explicitly. Whether the shorter ending participates in
  analysis at all awaits the owner's disputed-passage policy.

Related edition facts that need Milestone 5 attention but are not adjacency
constraints:

- **Pericope adulterae (JHN 7:53-8:11, greek).** Inline edition text in the
  pinned Nestle 1904 representation (190 tokens, no variant marker); verse
  numbering is continuous, so no adjacency declaration is needed. Whether
  passages spanning the pericope boundary should be flagged or excluded
  awaits the owner's analysis policy.
- **Edition-omitted verses.** Fifteen declared omitted verses in the Greek
  corpus (see `config/greek_ingestion.yaml`) leave gaps inside chapters;
  window generation must decide between bridging and splitting at those
  gaps under the same owner policy.

These are edition-level versification facts, recorded exactly as the pinned
sources supply them; segmentation must never renumber or fabricate verses to
smooth them over.
