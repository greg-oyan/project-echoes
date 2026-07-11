# Canonical Hebrew token schema

Status: active for Milestone 2

Schema version: `2`

Normative implementation: `src/echoes/corpus/models.py`

The canonical token table is a deterministic, provenance-preserving view of the
MACULA Hebrew morpheme records selected for Project Echoes. One canonical row
corresponds to one selected upstream `<m>` record, including explicitly annotated
zero-width morphemes. The schema does not merge source records into orthographic
words and does not invent annotations that the selected source does not provide.

The Pydantic model is the validation contract. The ordered Polars schema in the
same module is the storage contract for `tokens.parquet` and the DuckDB
`hebrew_tokens` table.

## Fields

`null` below means that a field is nullable in schema version 2. Required strings
must be nonempty unless the row is an explicitly marked zero-width morpheme.

| Field | Type | Null | Meaning and derivation |
| --- | --- | --- | --- |
| `schema_version` | integer | no | Literal `2`; identifies this canonical schema contract. |
| `token_id` | string | no | Stable Project Echoes identifier described under "Identity." |
| `corpus` | string | no | Literal `hebrew` for this Milestone 2 table; it includes Hebrew and Aramaic language rows. |
| `source_id` | string | no | Source-manifest key, currently `macula-hebrew`. |
| `source_version` | string | no | Exact source commit from the manifest. Production ingestion may not use an unpinned source. |
| `source_file` | string | no | POSIX-style path relative to the acquired source root, such as a chapter node file. |
| `source_record_id` | string | no | Native `<m>` `xml:id`, or the native `n` value when `xml:id` is absent. A fallback emits a warning. |
| `source_word_id` | string | no | Native `word` reference in `BOOK chapter:verse!word` form. |
| `source_edition_reference` | string | no | Source edition's own `BOOK chapter:verse` identifier, retained independently of every later crosswalk. |
| `source_row_reference` | string | no | Direct locator formed as `source_file#source_record_id`. |
| `book` | string | no | Three-character canonical book code from the 39-book WLC registry. |
| `book_order` | integer | no | One-based WLC canonical order, constrained to 1 through 39. |
| `chapter` | integer | no | One-based canonical chapter parsed from `source_word_id` and checked against the book registry. |
| `verse` | integer | no | One-based verse parsed from `source_word_id` and checked for continuous chapter coverage. |
| `subverse` | string | yes | Reserved for an explicit source subverse; the current adapter leaves it null. |
| `sentence_id` | string | yes | Source-file-qualified sentence locator constructed from the source sentence ordinal and optional native label. |
| `clause_id` | string | yes | Source-file-qualified nearest syntax node whose `Cat` is `CL`. |
| `phrase_id` | string | yes | Source-file-qualified nearest eligible non-role syntax node. |
| `position_in_verse` | integer | no | One-based morpheme position after deterministic canonical sorting; continuous within each verse. |
| `position_in_clause` | integer | yes | One-based position among rows sharing a clause ID; null when no clause is available. |
| `position_in_corpus` | integer | no | One-based position in deterministic book, chapter, verse, word, and subtoken order. |
| `position_in_word` | integer | no | One-based order among source morphemes sharing a canonical word location. |
| `surface_form` | string | no | Exact `<m>` text from the pinned source; never Unicode-normalized or otherwise rewritten. It is empty only for `is_zero_width=true`. |
| `normalized_form` | string | no | Minimally normalized, pointed derived form governed by `config/normalization.yaml`; empty only for a zero-width row. |
| `unpointed_form` | string | no | Derived form with the configured cantillation and vowel code points removed; empty only for a zero-width row. |
| `is_zero_width` | boolean | no | True when the source explicitly contains an `<m>` record with no surface text. |
| `lemma` | string | yes | MACULA-namespace lemma from the nearest ancestor, falling back to the morpheme attribute, with only base normalization applied. |
| `lexical_root` | string | yes | Reserved canonical field; the current adapter does not infer it and leaves it null. |
| `part_of_speech` | string | yes | Native `pos` value when present. |
| `morphology_json` | JSON-object string | yes | Canonical JSON object containing available native `morph`, `pos`, `type`, `stem`, `person`, `gender`, `number`, and `state` values. |
| `syntactic_function` | string | yes | Nearest recognized source syntax role category. |
| `syntactic_head_source_id` | string | yes | Reserved for a native head reference; the current adapter does not fabricate a head mapping and leaves it null. |
| `semantic_domain` | string | yes | First available contextual, lexical, or core domain attribute, using the adapter's documented priority. |
| `word_sense` | string | yes | Nearest ancestor `SenseNumber`, falling back to the morpheme `sensenumber`. |
| `participant_id` | string | yes | Nearest ancestor `Ref`, falling back to `participantref`. |
| `speaker_id` | string | yes | Nearest ancestor `Speaker` or `speaker` value. |
| `entity_id` | string | yes | Native morpheme `entity` value when present. |
| `english_gloss` | string | yes | Native `english` annotation when present; it is supplemental metadata, not original-language evidence. |
| `language` | enum | no | `hebrew` or `aramaic`; native language metadata is preferred, with a warning-producing passage fallback only when absent or unknown. |
| `is_punctuation` | boolean | no | True only if every surface character has a Unicode punctuation, separator, or symbol category. |
| `is_variant` | boolean | no | True only when the native `type` contains a recognized Ketiv/Kethiv/Qere marker. |
| `variant_type` | enum | yes | Exactly `ketiv`, `qere`, or null after recognizing the native marker. |
| `variant_group_id` | string | yes | Stable source-edition group shared by the supplied Ketiv and Qere records at one source word; null for ordinary records. |
| `is_default_reading` | boolean | no | Source-level default-stream membership. Ordinary and unpaired records are true; within a complete pair Qere is true and Ketiv false. This does not change with analysis configuration. |
| `ketiv_form` | string | yes | Source surface form for a recognized Ketiv/Kethiv record. |
| `qere_form` | string | yes | Source surface form for a recognized Qere record. |
| `source_extras_json` | JSON-object string | no | Canonical JSON containing all native morpheme attributes, retained syntax ancestry, and the number of alternate syntax trees. |

## Identity

The identifier format is:

```text
HB_<BOOK>_<CHAPTER:3>_<VERSE:3>_<SOURCE_TOKEN:4>[.<SUBTOKEN:2>][~<SOURCE_RECORD_DIGEST:12>]
```

For example, the first source word location in Genesis 1:1 has the base identity
`HB_GEN_001_001_0001`. When more than one morpheme shares that word location,
each row receives a `.01`, `.02`, and subsequent suffix in deterministic native-ID
order. A word represented by one morpheme has no suffix. A supplied Ketiv or Qere
record also receives a 12-hex-character digest of its native source-record ID so
that alternate readings at one source position remain distinct without using an
external coordinate system.

The identity is derived only from the source edition's book identifier, chapter,
verse, source token position, source subtoken position where present, and native
source-record identity only when variant disambiguation requires it. It does not
depend on XML traversal order, a generated dataframe row number,
`position_in_corpus`, English versification, a versification crosswalk,
Septuagint alignment, external canonical mappings, or supplementary data. Adding,
removing, or correcting a later crosswalk therefore cannot rename a token. Native
identity and the source edition's verse identifier remain independently available
in `source_record_id`, `source_word_id`, and `source_edition_reference`.

An upstream edition may change references, word segmentation, or morpheme IDs.
Such a source change can therefore change project token IDs and must be treated as
an explicit corpus-version migration, not silently reconciled.

See [ADR 0006](decisions/0006-canonical-token-identifiers.md) for the original
identity decision and [ADR 0008](decisions/0008-methodology-amendments.md) for the
source-edition and variant clarification.

## Derived analysis stream

The base canonical table always retains every source record, including both
members of a supplied Ketiv/Qere pair. Reading preference is applied only by the
separate `analysis_tokens.parquet` table and the DuckDB
`hebrew_analysis_stream` view. The derived table contains:

| Field | Meaning |
| --- | --- |
| `schema_version` | Derived-stream schema version. |
| `analysis_reading` | Configured `qere` or `ketiv` selection. |
| `token_id` | Stable base-token identity selected into this stream. |
| `source_edition_reference` | Preserved source-edition verse reference. |
| `variant_group_id` / `variant_type` | Reading relationship when the row is a variant. |
| `analysis_position_in_verse` | Continuous selected-stream position within the source verse. |
| `analysis_position_in_clause` | Continuous selected-stream position within a source clause, or null. |
| `analysis_position_in_corpus` | Continuous selected-stream position across the corpus. |

For a complete pair, only the configured reading enters the derived stream. A
single supplied reading remains analyzable because no alternate record exists to
select. Changing `analysis_reading` changes only this derived artifact and its run
metadata; base token IDs, counts, forms, provenance, and logical/physical token
table hashes remain unchanged.

## Provenance chain

Every token must support this trace:

```text
token_id
  -> source_id + source_version
  -> source_file + source_record_id
  -> source_row_reference
  -> source_records.raw_json + source_records.raw_sha256
  -> acquired file inventory and SHA-256 receipt
```

The companion `source_records.parquet` table stores one row per native record with
`source_record_id`, `source_file`, `source_row_reference`, `source_word_id`, the
same canonical raw JSON payload, and its SHA-256 hash. Full source and processed
tables remain local and Git-ignored under the source redistribution policy.

## Enforced invariants

Ingestion and validation reject rather than silently repair:

- duplicate native record IDs, canonical token IDs, canonical verse positions,
  or corpus positions;
- malformed native word references, invalid books, out-of-range chapters,
  non-positive verses,
  and malformed morphology codes;
- tokens that do not map one-to-one to a companion source record;
- noncontinuous corpus and verse positions;
- JSON fields that do not encode objects;
- non-zero-width tokens with an empty source or derived form;
- zero-width rows with any nonempty source or derived form;
- variant details when `is_variant` is false, or a variant row that loses both
  Ketiv and Qere forms;
- variant records without a stable group, groups with duplicate readings or no
  single default, and a derived analysis stream inconsistent with configuration;
- disagreement between stored derived forms and recomputation from the pinned
  normalization configuration.

For the approved full corpus, validation also requires 39 books, 929 chapters,
and 475,911 source-record-to-token mappings. Those counts are corpus expectations,
not generic constraints of schema version 2.

## Source-specific limitations

- The selected MACULA node representation normally prefers Qere. The variant
  fields and derived-stream machinery preserve alternate records that a source
  supplies, but this pinned full corpus exposes no complete parallel Ketiv layer
  and the adapter cannot reconstruct an absent reading.
- Alternate syntax trees are counted and retained in `source_extras_json`; the
  adapter maps the first upstream tree to canonical syntax fields.
- `lexical_root`, `subverse`, and `syntactic_head_source_id` remain null rather
  than being guessed.
- Prefixes and suffixes remain the source's morpheme records. Milestone 2 does not
  create a second segmentation or join them into words.

## Schema evolution

Changing a field's meaning, identifier rule, nullability, or storage type requires
a schema-version increment, an ADR, migration notes, updated validators, and a
determinism comparison. Adding Greek in Milestone 3 must not silently broaden the
literal Hebrew table contract defined here.
