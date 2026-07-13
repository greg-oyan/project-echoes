"""Language-aware passage reconstruction and ordered-sequence tests."""

from __future__ import annotations

import json
from collections.abc import Mapping

import polars as pl
import pytest

from echoes.segment.reconstruction import (
    ReconstructionError,
    reconstruct_greek,
    reconstruct_hebrew,
    reconstruct_passage,
)


def _hebrew_row(
    token_id: str,
    word_id: str,
    surface: str,
    *,
    normalized: str | None = None,
    unpointed: str | None = None,
    position_in_word: int = 1,
    after: str | None = None,
    zero_width: bool = False,
    language: str = "hebrew",
    reference: str = "GEN 1:1",
    variant_type: str | None = None,
    lemma: str | None = None,
) -> dict[str, object]:
    attributes: dict[str, str] = {}
    if after is not None:
        attributes["after"] = after
    return {
        "token_id": token_id,
        "corpus": "hebrew",
        "language": language,
        "source_word_id": word_id,
        "source_edition_reference": reference,
        "position_in_word": position_in_word,
        "surface_form": surface,
        "normalized_form": surface if normalized is None else normalized,
        "unpointed_form": surface if unpointed is None else unpointed,
        "is_zero_width": zero_width,
        "is_punctuation": surface in {"\u05c3", "\u05c6"},
        "variant_type": variant_type,
        "source_extras_json": json.dumps(
            {"attributes": attributes}, ensure_ascii=False, separators=(",", ":")
        ),
        "lemma": lemma,
        "lexical_root": None,
        "part_of_speech": None,
        "semantic_domain": None,
        "entity_id": None,
        "participant_id": None,
    }


def _greek_row(
    token_id: str,
    surface: str,
    normalized: str,
    folded: str,
    *,
    leading: str = "",
    trailing: str = "",
    punctuation: bool = False,
    elided: bool = False,
    reference: str = "JUD 1:1",
    lemma: str | None = None,
) -> dict[str, object]:
    return {
        "token_id": token_id,
        "corpus": "greek",
        "language": "greek",
        "source_edition_reference": reference,
        "surface_form": surface,
        "normalized_form": normalized,
        "folded_form": folded,
        "leading_punctuation": leading,
        "trailing_punctuation": trailing,
        "is_punctuation": punctuation,
        "is_elided": elided,
        "lemma": lemma,
        "part_of_speech": None,
        "semantic_domain": None,
        "participant_id": None,
    }


def test_hebrew_reconstruction_respects_morphemes_source_after_and_maqqef() -> None:
    rows = [
        _hebrew_row(
            "HB_GEN_001_001_0001.01",
            "GEN 1:1!1",
            "\u05d1\u05bc\u05b0",
            position_in_word=1,
            after="",
        ),
        _hebrew_row(
            "HB_GEN_001_001_0001.02",
            "GEN 1:1!1",
            "\u05e8\u05b5\u05d0\u05e9\u05c1\u05b4\u05d9\u05ea",
            normalized="\u05e8\u05b5\u05d0\u05e9\u05c1\u05b4\u05d9\u05ea",
            unpointed="\u05e8\u05d0\u05e9\u05d9\u05ea",
            position_in_word=2,
            after="\u05be",
        ),
        _hebrew_row(
            "HB_GEN_001_001_0002",
            "GEN 1:1!2",
            "\u05d1\u05bc\u05b8\u05e8\u05b8\u05d0",
            unpointed="\u05d1\u05e8\u05d0",
            after="",
        ),
        _hebrew_row("HB_GEN_001_001_0003", "GEN 1:1!3", "\u05c3", after=" "),
    ]

    result = reconstruct_hebrew(rows)

    assert (
        result.surface_text
        == "\u05d1\u05bc\u05b0\u05e8\u05b5\u05d0\u05e9\u05c1\u05b4\u05d9\u05ea\u05be"
        "\u05d1\u05bc\u05b8\u05e8\u05b8\u05d0\u05c3"
    )
    assert (
        result.unpointed_text
        == "\u05d1\u05bc\u05b0\u05e8\u05d0\u05e9\u05d9\u05ea\u05be\u05d1\u05e8\u05d0\u05c3"
    )
    assert not result.surface_text.endswith(" ")


def test_hebrew_zero_width_token_remains_in_sequences_without_visible_garbage() -> None:
    rows = [
        _hebrew_row("HB_EZR_004_001_0001.01", "EZR 4:1!1", "\u05d5\u05b0", position_in_word=1),
        _hebrew_row(
            "HB_EZR_004_001_0001.02",
            "EZR 4:1!1",
            "",
            normalized="",
            unpointed="",
            position_in_word=2,
            after=" ",
            zero_width=True,
            language="aramaic",
            reference="EZR 4:1",
        ),
        _hebrew_row(
            "HB_EZR_004_001_0002",
            "EZR 4:1!2",
            "\u05de\u05b6\u05dc\u05b6\u05da\u05b0",
            unpointed="\u05de\u05dc\u05da",
            language="aramaic",
            reference="EZR 4:1",
        ),
    ]
    rows[0]["language"] = "aramaic"
    rows[0]["source_edition_reference"] = "EZR 4:1"

    result = reconstruct_hebrew(rows)

    assert result.surface_text == "\u05d5\u05b0 \u05de\u05b6\u05dc\u05b6\u05da\u05b0"
    assert json.loads(result.token_ids_json) == [row["token_id"] for row in rows]


def test_hebrew_reconstruction_uses_the_selected_ketiv_stream_verbatim() -> None:
    rows = [
        _hebrew_row("HB_GEN_001_001_0001", "GEN 1:1!1", "\u05d0\u05b8\u05de\u05b7\u05e8"),
        _hebrew_row(
            "HB_GEN_001_001_0002~abcdefabcdef",
            "Gen 1:1!2",
            "\u05db\u05ea\u05d1",
            variant_type="ketiv",
            after=" ",
        ),
    ]

    result = reconstruct_hebrew(rows)

    assert result.surface_text == "\u05d0\u05b8\u05de\u05b7\u05e8 \u05db\u05ea\u05d1"
    assert "\u05e7\u05e8\u05d0" not in result.surface_text


def test_greek_reconstruction_preserves_attached_punctuation_and_elision() -> None:
    rows = [
        _greek_row(
            "GNT_JUD_001_001_0001",
            "(\u03bb\u03cc\u03b3\u03bf\u03c2,",
            "\u03bb\u03cc\u03b3\u03bf\u03c2",
            "\u03bb\u03bf\u03b3\u03bf\u03c3",
            leading="(",
            trailing=",",
        ),
        _greek_row(
            "GNT_JUD_001_001_0002",
            "\u03b4\u03b9\u2019",
            "\u03b4\u03b9\u2019",
            "\u03b4\u03b9\u2019",
            elided=True,
        ),
        _greek_row(
            "GNT_JUD_001_002_0001",
            "\u03b8\u03b5\u03cc\u03bd.",
            "\u03b8\u03b5\u03cc\u03bd",
            "\u03b8\u03b5\u03bf\u03bd",
            trailing=".",
            reference="JUD 1:2",
        ),
    ]

    result = reconstruct_greek(rows)

    assert (
        result.surface_text
        == "(\u03bb\u03cc\u03b3\u03bf\u03c2, \u03b4\u03b9\u2019 \u03b8\u03b5\u03cc\u03bd."
    )
    assert (
        result.normalized_text
        == "\u03bb\u03cc\u03b3\u03bf\u03c2 \u03b4\u03b9\u2019 \u03b8\u03b5\u03cc\u03bd"
    )
    assert (
        result.folded_text
        == "\u03bb\u03bf\u03b3\u03bf\u03c3 \u03b4\u03b9\u2019 \u03b8\u03b5\u03bf\u03bd"
    )
    assert result.unpointed_text is None


def test_greek_standalone_punctuation_never_gets_an_incorrect_inner_space() -> None:
    rows = [
        _greek_row("GNT_JUD_001_001_0001", "(", "(", "(", punctuation=True),
        _greek_row(
            "GNT_JUD_001_001_0002",
            "\u03bb\u03cc\u03b3\u03bf\u03c2",
            "\u03bb\u03cc\u03b3\u03bf\u03c2",
            "\u03bb\u03bf\u03b3\u03bf\u03c3",
        ),
        _greek_row("GNT_JUD_001_001_0003", ")", ")", ")", punctuation=True),
        _greek_row("GNT_JUD_001_001_0004", ".", ".", ".", punctuation=True),
    ]

    result = reconstruct_greek(rows)

    assert result.surface_text == "(\u03bb\u03cc\u03b3\u03bf\u03c2)."
    assert result.normalized_text == "(\u03bb\u03cc\u03b3\u03bf\u03c2)."


def test_ordered_nullable_sequences_preserve_null_empty_and_unicode_values() -> None:
    rows = [
        _greek_row(
            "GNT_JUD_001_001_0001",
            "\u03bb\u03cc\u03b3\u03bf\u03c2",
            "\u03bb\u03cc\u03b3\u03bf\u03c2",
            "\u03bb\u03bf\u03b3\u03bf\u03c3",
            lemma=None,
        ),
        _greek_row(
            "GNT_JUD_001_002_0001",
            "\u1f10\u03c3\u03c4\u03af\u03bd",
            "\u1f10\u03c3\u03c4\u03af\u03bd",
            "\u03b5\u03c3\u03c4\u03b9\u03bd",
            reference="JUD 1:2",
            lemma="",
        ),
    ]
    rows[0]["semantic_domain"] = "\u03c3\u03b7\u03bc\u03b1\u03c3\u03af\u03b1"

    first = reconstruct_greek(pl.DataFrame(rows))
    second = reconstruct_greek(rows)

    assert first == second
    assert first.lemma_sequence_json == '[null,""]'
    assert (
        first.semantic_domain_sequence_json == '["\u03c3\u03b7\u03bc\u03b1\u03c3\u03af\u03b1",null]'
    )
    assert "\\u" not in first.semantic_domain_sequence_json


def test_dispatch_works_across_verse_or_sentence_membership_without_reordering() -> None:
    rows: list[Mapping[str, object]] = [
        _greek_row(
            "GNT_JUD_001_001_0001",
            "\u03c0\u03c1\u1ff6\u03c4\u03bf\u03c2",
            "\u03c0\u03c1\u1ff6\u03c4\u03bf\u03c2",
            "\u03c0\u03c1\u03c9\u03c4\u03bf\u03c3",
        ),
        _greek_row(
            "GNT_JUD_001_002_0001",
            "\u03b4\u03b5\u03cd\u03c4\u03b5\u03c1\u03bf\u03c2",
            "\u03b4\u03b5\u03cd\u03c4\u03b5\u03c1\u03bf\u03c2",
            "\u03b4\u03b5\u03c5\u03c4\u03b5\u03c1\u03bf\u03c3",
            reference="JUD 1:2",
        ),
    ]

    result = reconstruct_passage(rows)

    assert (
        result.surface_text
        == "\u03c0\u03c1\u1ff6\u03c4\u03bf\u03c2 \u03b4\u03b5\u03cd\u03c4\u03b5\u03c1\u03bf\u03c2"
    )
    assert json.loads(result.token_ids_json) == [
        "GNT_JUD_001_001_0001",
        "GNT_JUD_001_002_0001",
    ]


def test_reconstruction_rejects_uncertain_word_grouping_and_bad_punctuation() -> None:
    hebrew = [
        _hebrew_row("HB_GEN_001_001_0001", "GEN 1:1!1", "\u05d0"),
        _hebrew_row("HB_GEN_001_001_0002", "GEN 1:1!2", "\u05d1"),
        _hebrew_row("HB_GEN_001_001_0003", "GEN 1:1!1", "\u05d2", position_in_word=2),
    ]
    greek = [
        _greek_row(
            "GNT_JUD_001_001_0001",
            "(\u03bb\u03cc\u03b3\u03bf\u03c2)",
            "\u03bb\u03cc\u03b3\u03bf\u03c2",
            "\u03bb\u03bf\u03b3\u03bf\u03c3",
            leading="",
            trailing=")",
        )
    ]

    with pytest.raises(ReconstructionError, match="non-contiguous"):
        reconstruct_hebrew(hebrew)
    with pytest.raises(ReconstructionError, match="punctuation fields"):
        reconstruct_greek(greek)


def test_reconstruction_rejects_empty_passages() -> None:
    with pytest.raises(ReconstructionError, match="empty token sequence"):
        reconstruct_passage([])
