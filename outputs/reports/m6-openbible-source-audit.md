# Milestone 6 OpenBible source and archive audit

- Audit date: 2026-07-12 (America/Los_Angeles)
- Official source: <https://www.openbible.info/labs/cross-references/>
- Official history and field semantics:
  <https://www.openbible.info/blog/2010/04/new-in-labs-cross-references/>
- Direct archive: <https://a.openbible.info/data/cross-references.zip>
- License: Creative Commons Attribution 4.0,
  <https://creativecommons.org/licenses/by/4.0/>
- Decision: approved for governed Tier 3 weak supervision and knownness support;
  no source-audit stop condition fired.

## Transport and snapshot

The direct archive returned HTTP 200 without an observed redirect. Response
metadata at audit time was:

| Field | Value |
| --- | --- |
| Content-Type | `application/zip` |
| Content-Length | `1,980,519` |
| Last-Modified | `Mon, 06 Jul 2026 08:40:07 GMT` |
| ETag | `"5268fa7dd429853c74ec6ce54ccef90e"` |
| Accept-Ranges | `bytes` |

Two independent binary downloads were byte-identical. The authoritative archive
SHA-256 is
`18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492`.
The ETag happened to equal the archive MD5, but Project Echoes does not use ETag
as identity.

## Archive integrity and inventory

The ZIP integrity/CRC check passed. Its inventory contains exactly one regular
file and no directory payloads, symlinks, encrypted entries, comments, nested
archives, or executable content.

| Entry | Compressed bytes | Extracted bytes | CRC32 | SHA-256 |
| --- | ---: | ---: | --- | --- |
| `cross_references.txt` | 1,980,329 | 8,301,510 | `931445fc` | `eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37` |

The member is valid UTF-8 and entirely ASCII, with no byte-order mark or NUL,
LF-only newlines, a final LF, and no blank or trailing-whitespace lines.

## Observed source schema

The first line is:

```text
From Verse<TAB>To Verse<TAB>Votes<TAB>#www.openbible.info CC-BY 2026-07-06
```

The fourth header token is an embedded attribution notice. Each of the 344,799
data rows has exactly three tab-separated fields: source reference, target
reference, and a signed decimal integer vote. References use
`Book.Chapter.Verse`; ranges use fully qualified
`Book.Chapter.Verse-Book.Chapter.Verse`. Source references are always single
verses. Target endpoints include 256,649 single verses and 88,150 ranges:
87,495 within one chapter, 637 across chapters in one book, and 18 across books.
All 66 Protestant-canon book codes occur.

Every one of 344,799 rows passed structural column, reference-syntax, and integer
parsing in the audit; there was no unexplained row loss. Semantic chapter, verse,
versification, omission, and target-edition validity remain the responsibility of
the governed reference mapper rather than this structural statement.

## Graph and weight audit

| Measure | Count or value |
| --- | ---: |
| Raw data rows | 344,799 |
| Unique directed pairs | 344,799 |
| Exact duplicate rows | 0 |
| Duplicate directed pairs | 0 |
| Unordered pairs represented in both directions | 29,878 |
| Directed rows participating in reverse pairs | 59,756 |
| Self-links | 0 |
| Minimum vote | -86 |
| First quartile | 2 |
| Median | 3 |
| Third quartile | 6 |
| Maximum vote | 1,281 |
| Negative / zero / positive votes | 1,239 / 2,277 / 341,283 |
| Distinct vote values | 418 |

Direction is preserved exactly. Reverse relationships remain distinct directed
relationships with a shared unordered-pair identity. The current absence of
duplicates or self-links is a snapshot observation, not permission for the parser
to discard such records in a future snapshot. Votes are mutable ranking evidence,
not calibrated confidence or probability of literary dependence.

## Material identity, licensing, and scope

The official page describes about 340,000 cross references, primarily derived
from the public-domain Treasury of Scripture Knowledge with Topical Bible and
Twitter Bible Search seeds, and links a roughly 2 MB regularly updated archive.
The audited artifact matches that description. The official page applies CC BY
4.0 unless otherwise indicated; compliant use must credit OpenBible.info, link the
material and license, and identify modifications.

The page separately displays copyrighted ESV quotations. The ZIP contains only
reference identifiers, integer votes, and its attribution header. Strict grammar
and content scans found no biblical quotation, ESV text, or other modern
translation text. No additional or mixed-rights dataset occurs in the archive.
Project Echoes will nevertheless keep the raw ZIP, extracted member, acquisition
receipt, and full normalized dataset in ignored local storage.

## Stop-condition assessment

No stop condition fired:

- no prohibited biblical, ESV, or modern-translation text was present;
- the official license and intended Tier 3 use are compatible;
- the artifact is the described cross-reference graph;
- two downloads reproduced the complete archive hash;
- the safe one-file inventory and all source rows were structurally reconciled;
- attribution is identifiable; and
- no additional dataset requires a separate rights decision.

Approval does not make OpenBible scholarly truth. It remains Tier 3 weak
supervision and broad knownness support, cannot populate Tier 1, is ineligible for
primary evaluation, and supplies no lexical or semantic feature.
