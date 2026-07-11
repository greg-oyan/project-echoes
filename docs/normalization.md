# Hebrew, Aramaic, and Greek normalization

Status: Hebrew/Aramaic active for Milestone 2; Greek active for Milestone 3

Configuration: `config/normalization.yaml`, schema version `4`

Implementation: `src/echoes/normalize/hebrew.py` and `src/echoes/normalize/greek.py`

Project Echoes stores source text and analytical forms separately. Normalization
is deterministic and deliberately conservative: it creates derived forms without
changing the pinned MACULA surface value, its token boundaries, or its reading.

## Three form layers

| Form | Purpose | Milestone 2 transformation |
| --- | --- | --- |
| `surface_form` | Source evidence and visual inspection | Exact `<m>` text. No Unicode normalization, mark removal, whitespace rewrite, or orthographic substitution. |
| `normalized_form` | Pointed analytical form | Unicode NFD, removal of U+034F COMBINING GRAPHEME JOINER, and whitespace collapse. Vowels and cantillation remain. |
| `unpointed_form` | Consonantal-form comparison | The same base transformation, followed by removal of the configured Hebrew cantillation and vowel-point code points. |

An explicitly annotated zero-width morpheme is retained as a token with
`is_zero_width=true` and all three form strings empty. It is not sent through the
normalizer and is not dropped.

## Base transformation

The base transformation applied to each nonempty derived token and to each
nonempty lemma is, in order:

1. Apply Unicode Normalization Form D (`NFD`).
2. Remove U+034F COMBINING GRAPHEME JOINER.
3. Collapse each Unicode whitespace run to one ASCII space and trim its ends.

`surface_form` bypasses this transformation. This distinction is important for
the pinned 25.08.11 source, which predates later upstream Unicode and
combining-grapheme-joiner fixes.

## Mark removal

`normalized_form` currently removes neither cantillation nor vowel points.
`unpointed_form` removes both groups after the base transformation.

The implementation uses explicit code-point sets rather than deleting every
Unicode combining mark:

- Cantillation: U+0591 through U+05AF, plus U+05BD.
- Vowel and related pointing marks: U+05B0 through U+05BC, plus U+05BF,
  U+05C1, U+05C2, U+05C4, U+05C5, and U+05C7.

Characters outside those sets remain. In particular, Milestone 2 preserves
maqqef, paseq, sof pasuq, other punctuation, consonants, and final letter forms.

## Explicit non-transformations

The configuration and its strict Pydantic schema require the following values to
remain false in Milestone 2:

- split maqqef;
- remove paseq or sof pasuq;
- remove punctuation generally;
- normalize final letters;
- collapse orthographic variants;
- segment prefixes or suffixes independently of the source;
- collapse Ketiv and Qere;
- normalize divine names.

These are research-bearing choices, not implementation omissions. A method that
needs another view must add a separately named, configured representation and a
documented decision; it must not overwrite any of the three current forms.

## Lemmas

The lemma namespace is `macula`. Lemmas receive only the base transformation:
NFD, combining-grapheme-joiner removal, and whitespace collapse. They are not
mapped to Strong's numbers, roots, another lexicon, or an inferred spelling.
Missing or blank source lemmas remain null.

## Hebrew and Aramaic labels

Normalization rules are shared by the Hebrew and Aramaic rows in the MACULA
Hebrew corpus. Language identity is stored separately:

1. Recognized native `lang` values are authoritative.
2. If native language is absent or unknown, the adapter uses an explicit passage
   fallback for the Aramaic sections of Ezra, Daniel, and Jeremiah 10:11.
3. Every fallback emits a `language-inferred` warning.

The fallback is a data-recovery safeguard, not a license to replace supplied
language annotation. In a verse containing a language transition, the native
token-level label remains necessary for precision.

## Ketiv/Qere and segmentation

Normalization never collapses Ketiv and Qere. When the source supplies both
readings, each remains a separate canonical record with its own stable token ID,
exact `surface_form`, independently derived `normalized_form` and
`unpointed_form`, source provenance, `variant_type`, and a shared
`variant_group_id`. Within a complete source pair, Qere is marked as the source
default and Ketiv is not; this base metadata does not change when an analytical
preference changes.

The preference is a derived-stream policy at the root of the configuration:

```yaml
ketiv_qere:
  analysis_reading: qere
```

The supported values are `qere` and `ketiv`, with Qere as the default. Only the
selected member of a complete pair enters `analysis_tokens.parquet` and the
DuckDB `hebrew_analysis_stream` view. The view assigns deterministic
`analysis_position_in_verse`, `analysis_position_in_clause`, and
`analysis_position_in_corpus` values after selection. A lone supplied reading
remains in either stream because no alternate source record exists. Switching the
setting changes the derived stream and its positions, never the base token count,
token IDs, source forms, normalized forms, or provenance.

The pinned MACULA node representation commonly exposes the preferred Qere without
a complete parallel Ketiv layer, so absence of a paired variant is not evidence
that the textual tradition has no variant. Legally safe synthetic fixtures prove
both-record preservation and stream switching; they do not manufacture a missing
reading in the full corpus.

Likewise, normalization neither splits nor joins morphemes. Prefixes, suffixes,
and zero-width annotations retain the boundaries supplied by MACULA. Word and
subtoken identity is handled by the canonical token schema, not by this module.

## Punctuation classification

The adapter marks a token as punctuation only when it is nonempty and every
character has a Unicode category beginning with `P`, `Z`, or `S`. This flag does
not remove the token or any character from its forms.

## Reproducibility and validation

The ingestion run records a SHA-256 hash of the complete normalization
configuration in corpus metadata. Full validation recomputes every non-zero-width
`normalized_form`, `unpointed_form`, and punctuation flag and reports any mismatch
as an error. Reprocessing the same source receipt, schema, and normalization
configuration must reproduce the same run ID and logical tables. Changing only
`ketiv_qere.analysis_reading` legitimately changes the configuration hash,
derived analysis table, and run metadata while leaving the base token table
unchanged.

To change normalization safely:

1. change the typed configuration and implementation together;
2. add focused examples for every changed code-point or boundary rule;
3. record the methodological reason in a new ADR that supersedes the active rule;
4. rerun full-corpus validation and determinism checks;
5. treat changed configuration hashes and derived-table hashes as expected,
   documented corpus-version changes.

See [ADR 0007](decisions/0007-hebrew-normalization-policy.md) for the original
normalization decision and [ADR 0008](decisions/0008-methodology-amendments.md) for
the non-destructive reading-stream policy.

# Greek normalization

Status: active for Milestone 3

Implementation: `src/echoes/normalize/greek.py`; source selection in
[ADR 0010](decisions/0010-macula-greek-source-selection.md).

The MACULA Greek Nestle1904 node representation attaches punctuation to the
word text (for example a trailing comma inside the leaf text) and marks
elision with U+2019. Greek normalization is deterministic and conservative:
derived forms never alter the surface string.

## Three form layers plus preserved source forms

| Form | Purpose | Milestone 3 transformation |
| --- | --- | --- |
| `surface_form` | Source evidence and visual inspection | Exact leaf text, including attached punctuation, original accentuation, elision marks, and casing. |
| `normalized_form` | Punctuation-separated word core | Leading/trailing punctuation split off (stored in `leading_punctuation` and `trailing_punctuation`); Unicode NFC. Reconstruction `leading + normalized + trailing == surface` is validated for every token. |
| `folded_form` | Accent-insensitive comparison form | NFD decomposition; removal of acute, grave, and perispomeni accents and both breathing marks; case folding (final sigma folds to medial sigma); NFC recomposition. Diaeresis is phonemic and retained. |

The source edition's own accent-regularized `NormalizedForm` attribute (which,
for example, regularizes grave to acute) is preserved unchanged in the separate
`source_normalized_form` column. It is never overwritten and never replaces the
deterministic derived forms.

## Explicit policies

- **Punctuation separation**: the observed punctuation set (comma, full stop,
  semicolon/Greek question mark, middle dot/ano teleia, parentheses, brackets,
  dashes, guillemets, and quotation marks) is split from the word core.
  Standalone punctuation tokens do not occur in this representation
  (validated: zero `is_punctuation` rows in the full corpus).
- **Elision**: the elision mark (U+2019 and variants) after a letter is part
  of the word core, never separated; elided tokens carry `is_elided=true`
  (1,223 tokens in the pinned corpus). Elided vowels are never restored
  (`restore_elided_letters` is pinned false).
- **Crasis**: crasis forms remain single tokens exactly as the source
  tokenizes them (`decompose_crasis` is pinned false).
- **Enclitics**: enclitic-driven accent variation (double accents, enclitic
  accent shifts) is preserved in `surface_form`; the edition's regularized
  accentuation is available in `source_normalized_form`; `folded_form` is
  fully accent-insensitive (`enclitic_accent_policy: preserve_source`).
- **Lemmas**: namespace `macula`; the `UnicodeLemma` value receives NFC and
  whitespace collapse only; homograph disambiguators (for example a trailing
  Roman-numeral marker) are preserved verbatim.

## Reproducibility and validation

Full Greek validation recomputes every `normalized_form`, `folded_form`,
punctuation split, and elision flag from `surface_form` under the pinned
configuration and reports any mismatch as an error, and verifies lossless
punctuation reconstruction for every token.
