# Hebrew and Aramaic normalization

Status: active for Milestone 2

Configuration: `config/normalization.yaml`, schema version `2`

Implementation: `src/echoes/normalize/hebrew.py`

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

Normalization never collapses Ketiv and Qere. When the source marks a record's
`type` as Ketiv/Kethiv or Qere, the canonical variant fields retain that source
form. The selected node representation commonly exposes the preferred Qere
without a complete parallel Ketiv layer, so absence of a variant row is not
evidence that the textual tradition has no variant.

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
configuration must reproduce the same run ID and logical tables.

To change normalization safely:

1. change the typed configuration and implementation together;
2. add focused examples for every changed code-point or boundary rule;
3. record the methodological reason in a new ADR that supersedes the active rule;
4. rerun full-corpus validation and determinism checks;
5. treat changed configuration hashes and derived-table hashes as expected,
   documented corpus-version changes.

Greek normalization remains `planned` and is outside Milestone 2. See
[ADR 0007](decisions/0007-hebrew-normalization-policy.md) for the governing decision.
