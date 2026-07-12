"""Source-edition identity must remain isolated from later mapping layers."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import polars as pl
import pytest

import echoes.corpus.token_ids as token_ids
from echoes.corpus.token_ids import (
    TokenIdentityError,
    generate_source_edition_token_id,
    normalize_source_book_identifier,
)
from echoes.corpus.validation import (
    CorpusValidationError,
    corpus_analytical_digest,
    corpus_identity_digest,
)


def _identity() -> str:
    return generate_source_edition_token_id(
        book_identifier="GEN",
        chapter=1,
        verse=2,
        source_token_position=3,
        source_subtoken_position=1,
        source_record_id="source-record-1",
        disambiguate_with_source_record=True,
    )


def _greek_identity() -> str:
    return generate_source_edition_token_id(
        book_identifier="JHN",
        chapter=1,
        verse=1,
        source_token_position=1,
        corpus_prefix="GNT",
    )


def test_token_identity_module_imports_no_crosswalk_layer() -> None:
    tree = ast.parse(inspect.getsource(token_ids))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert imported_modules == {"__future__", "hashlib", "re"}
    assert "crosswalk" not in inspect.signature(generate_source_edition_token_id).parameters


def test_crosswalk_file_add_change_and_removal_cannot_change_identity(
    tmp_path: Path,
) -> None:
    before = _identity()
    greek_before = _greek_identity()
    crosswalk = tmp_path / "versification-crosswalk.yaml"
    crosswalk.write_text("GEN 1:2: GEN 1:3\n", encoding="utf-8")
    after_add = _identity()
    greek_after_add = _greek_identity()
    crosswalk.write_text("GEN 1:2: EXO 2:1\nJHN 1:1: JHN 1:2\n", encoding="utf-8")
    after_change = _identity()
    greek_after_change = _greek_identity()
    crosswalk.unlink()
    after_removal = _identity()
    greek_after_removal = _greek_identity()

    assert {before, after_add, after_change, after_removal} == {before}
    assert {greek_before, greek_after_add, greek_after_change, greek_after_removal} == {
        greek_before
    }


def test_greek_ids_use_the_same_source_edition_identity_module() -> None:
    assert _greek_identity() == "GNT_JHN_001_001_0001"
    assert _greek_identity() == _greek_identity()
    hebrew_style = generate_source_edition_token_id(
        book_identifier="JHN",
        chapter=1,
        verse=1,
        source_token_position=1,
    )
    assert hebrew_style == "HB_JHN_001_001_0001"
    with pytest.raises(TokenIdentityError, match="corpus_prefix"):
        generate_source_edition_token_id(
            book_identifier="JHN",
            chapter=1,
            verse=1,
            source_token_position=1,
            corpus_prefix="gnt",
        )


def test_source_identity_is_stable_and_requires_explicit_variant_disambiguation() -> None:
    assert _identity() == _identity()
    with pytest.raises(TokenIdentityError, match="source_record_id is required"):
        generate_source_edition_token_id(
            book_identifier="GEN",
            chapter=1,
            verse=2,
            source_token_position=3,
            disambiguate_with_source_record=True,
        )


def test_source_book_identifiers_are_normalized_without_canonical_mapping() -> None:
    assert normalize_source_book_identifier("2Kgs") == "2KGS"
    assert normalize_source_book_identifier("Ps") == "PS"
    assert normalize_source_book_identifier("GEN") == "GEN"
    assert (
        generate_source_edition_token_id(
            book_identifier="2Kgs",
            chapter=8,
            verse=10,
            source_token_position=6,
        )
        == "HB_2KGS_008_010_0006"
    )
    assert (
        generate_source_edition_token_id(
            book_identifier="GEN",
            chapter=1,
            verse=1,
            source_token_position=1,
        )
        == "HB_GEN_001_001_0001"
    )


def test_changing_oshb_canonical_mapping_cannot_change_source_identity(monkeypatch) -> None:
    from echoes.align.book_codes import OSHB_TO_MACULA_BOOK

    arguments = {
        "book_identifier": "2Kgs",
        "chapter": 8,
        "verse": 10,
        "source_token_position": 6,
        "source_record_id": "2kings-ketiv-record",
        "disambiguate_with_source_record": True,
    }
    before = generate_source_edition_token_id(**arguments)
    monkeypatch.setitem(OSHB_TO_MACULA_BOOK, "2Kgs", "GEN")
    after = generate_source_edition_token_id(**arguments)

    assert before == after
    assert before.startswith("HB_2KGS_008_010_0006~")


@pytest.mark.parametrize(
    "identifier",
    ["", "2 Kgs", "2-Kgs", "2_Kgs", "Psalms/MT", "A" * 17],
)
def test_source_book_identifier_rejects_lossy_or_unsafe_normalization(identifier: str) -> None:
    with pytest.raises(TokenIdentityError, match="one to sixteen ASCII letters or digits"):
        normalize_source_book_identifier(identifier)


def test_corpus_content_digest_covers_forms_and_encodes_null_lemma_as_empty() -> None:
    from echoes.corpus.validation import corpus_content_digest

    frame = pl.DataFrame(
        {
            "position_in_corpus": [1, 2],
            "token_id": ["HB_GEN_001_001_0001", "HB_GEN_001_001_0002"],
            "surface_form": ["אָ", "בְּ"],
            "normalized_form": ["א", "ב"],
            "lemma": ["למ", None],
        }
    )
    reordered = frame.sort("token_id", descending=True)

    digest = corpus_content_digest(frame)
    assert digest == corpus_content_digest(reordered)

    # A null lemma hashes identically to an explicit empty string.
    empty_lemma = frame.with_columns(
        pl.when(pl.col("lemma").is_null())
        .then(pl.lit(""))
        .otherwise(pl.col("lemma"))
        .alias("lemma")
    )
    assert corpus_content_digest(empty_lemma) == digest

    changed_form = frame.with_columns(pl.col("surface_form").str.replace("א", "ג"))
    assert corpus_content_digest(changed_form) != digest

    changed_lemma = frame.with_columns(pl.lit("אחר").alias("lemma"))
    assert corpus_content_digest(changed_lemma) != digest


def test_corpus_identity_digest_orders_by_corpus_position_and_detects_changes() -> None:
    frame = pl.DataFrame(
        {
            "position_in_corpus": [2, 1],
            "token_id": ["HB_GEN_001_001_0002", "HB_GEN_001_001_0001"],
            "source_record_id": ["o2", "o1"],
            "source_word_id": ["GEN 1:1!2", "GEN 1:1!1"],
        }
    )
    reordered = frame.sort("token_id")

    digest = corpus_identity_digest(frame)
    assert digest == corpus_identity_digest(reordered)

    changed = frame.with_columns(pl.col("source_record_id").str.replace("o2", "different"))
    assert corpus_identity_digest(changed) != digest


def _analytical_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "schema_version": [2, 2],
            "position_in_corpus": [2, 1],
            "token_id": ["HB_GEN_001_001_0002", "HB_GEN_001_001_0001"],
            "source_record_id": ["o2", "o1"],
            "source_word_id": ["GEN 1:1!2", "GEN 1:1!1"],
            "surface_form": ["second", "first"],
            "normalized_form": ["second", "first"],
            "lemma": ["lemma-2", "lemma-1"],
            "part_of_speech": ["noun", "verb"],
            "morphology_json": ['{"number":"sg","case":"nom"}', None],
            "sentence_id": ["s1", "s1"],
            "clause_id": ["c1", "c1"],
            "phrase_id": ["p2", "p1"],
            "syntactic_function": ["subject", "predicate"],
            "syntactic_head_source_id": [None, "o2"],
            "semantic_domain": ["person", "action"],
            "word_sense": ["1", "2"],
            "participant_id": ["participant-1", None],
            "language": ["hebrew", "hebrew"],
            "is_variant": [False, False],
            "variant_type": [None, None],
            "variant_group_id": [None, None],
            "is_default_reading": [True, True],
        }
    )


def test_analytical_digest_ignores_row_and_json_object_order() -> None:
    frame = _analytical_frame()
    reordered_rows = frame.sort("token_id", descending=True)
    reordered_json = frame.with_columns(
        pl.when(pl.col("morphology_json").is_not_null())
        .then(pl.lit('{"case":"nom","number":"sg"}'))
        .otherwise(pl.col("morphology_json"))
        .alias("morphology_json")
    )

    digest = corpus_analytical_digest(frame)
    assert corpus_analytical_digest(reordered_rows) == digest
    assert corpus_analytical_digest(reordered_json) == digest


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("morphology_json", '{"number":"pl","case":"nom"}'),
        ("syntactic_function", "object"),
        ("semantic_domain", "location"),
    ],
)
def test_analytical_digest_detects_annotation_changes(column: str, replacement: str) -> None:
    frame = _analytical_frame()
    changed = frame.with_columns(
        pl.when(pl.col("token_id") == "HB_GEN_001_001_0002")
        .then(pl.lit(replacement))
        .otherwise(pl.col(column))
        .alias(column)
    )

    assert corpus_analytical_digest(changed) != corpus_analytical_digest(frame)


def test_analytical_digest_canonicalizes_null_distinctly_from_empty_string() -> None:
    frame = _analytical_frame()
    changed = frame.with_columns(pl.col("participant_id").fill_null(""))

    assert corpus_analytical_digest(changed) != corpus_analytical_digest(frame)


def test_analytical_digest_rejects_invalid_serialized_json() -> None:
    frame = _analytical_frame().with_columns(pl.lit("not-json").alias("morphology_json"))

    with pytest.raises(CorpusValidationError, match="cannot parse morphology_json"):
        corpus_analytical_digest(frame)
