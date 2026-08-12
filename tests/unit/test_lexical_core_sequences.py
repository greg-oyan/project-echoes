from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from echoes.lexical.sequences import (
    LexicalSequenceError,
    coarse_morphology,
    iter_passage_sequences,
    normalize_english_gloss,
)


def _bounded_passage_sequences(database_path: Path, **kwargs: object):
    return iter_passage_sequences(
        database_path,
        duckdb_memory_limit_bytes=128 * 1024**2,
        duckdb_temp_directory=database_path.parent / "sequence-spill",
        **kwargs,
    )


def _create_sequence_database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE passages(
              passage_id VARCHAR, corpus VARCHAR, book VARCHAR, book_order SMALLINT,
              analysis_profile VARCHAR, analysis_reading VARCHAR, granularity VARCHAR,
              start_reference VARCHAR, end_reference VARCHAR,
              identity_payload_sha256 VARCHAR, start_stream_position_in_corpus BIGINT,
              token_count BIGINT, disputed_passage_flag BOOLEAN, reference_gap BOOLEAN,
              ketiv_structural_uncertainty BOOLEAN
            );
            CREATE TABLE passage_membership(
              passage_id VARCHAR, token_id VARCHAR, position_in_passage BIGINT
            );
            CREATE TABLE hebrew_tokens(
              token_id VARCHAR, source_word_id VARCHAR, normalized_form VARCHAR,
              lemma VARCHAR, part_of_speech VARCHAR, morphology_json VARCHAR,
              english_gloss VARCHAR, is_punctuation BOOLEAN, lexical_root VARCHAR,
              is_zero_width BOOLEAN
            );
            CREATE TABLE hebrew_kq_ketiv_tokens AS SELECT * FROM hebrew_tokens WHERE false;
            CREATE TABLE greek_tokens(
              token_id VARCHAR, source_word_id VARCHAR, normalized_form VARCHAR,
              lemma VARCHAR, part_of_speech VARCHAR, morphology_json VARCHAR,
              english_gloss VARCHAR, is_punctuation BOOLEAN, folded_form VARCHAR,
              is_elided BOOLEAN
            );
            """
        )


def _insert_passage(
    connection: duckdb.DuckDBPyConnection,
    *,
    passage_id: str,
    corpus: str,
    reading: str,
    token_ids: tuple[str, ...],
) -> None:
    book = "GEN" if corpus == "hebrew" else "MAT"
    connection.execute(
        "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            passage_id,
            corpus,
            book,
            1,
            "edition_complete",
            reading,
            "verse",
            f"{book}.1.1",
            f"{book}.1.1",
            "a" * 64,
            1,
            len(token_ids),
            False,
            False,
            False,
        ],
    )
    connection.executemany(
        "INSERT INTO passage_membership VALUES (?,?,?)",
        [(passage_id, token_id, index) for index, token_id in enumerate(token_ids, start=1)],
    )


def test_gloss_and_morphology_normalization_are_conservative_and_canonical() -> None:
    assert normalize_english_gloss("  Make, GOOD!  ") == ("make", "good")
    assert normalize_english_gloss(None) == ()
    assert coarse_morphology('{"number":"SINGULAR","case":"Nom"}') == (
        '{"case":"nom","number":"singular"}'
    )
    assert coarse_morphology('{"nested":{"b":2,"a":1}}') is None
    assert coarse_morphology("not-json") is None


def test_hebrew_sequences_derive_from_membership_and_preserve_nonlexical_provenance(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sequences.duckdb"
    _create_sequence_database(database)
    with duckdb.connect(str(database)) as connection:
        _insert_passage(
            connection,
            passage_id="p1",
            corpus="hebrew",
            reading="qere",
            token_ids=("visible", "punctuation", "zero-width"),
        )
        connection.executemany(
            "INSERT INTO hebrew_tokens VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "visible",
                    "word-1",
                    "surface",
                    "lemma",
                    "noun",
                    '{"number":"SINGULAR"}',
                    "Make, GOOD!",
                    False,
                    None,
                    False,
                ),
                ("punctuation", "word-2", ".", None, None, None, None, True, None, False),
                ("zero-width", "word-3", None, None, None, None, None, False, None, True),
            ],
        )

    passages = list(
        _bounded_passage_sequences(
            database,
            corpus="hebrew",
            analysis_profile="edition_complete",
            analysis_reading="qere",
            granularity="verse",
        )
    )

    assert len(passages) == 1
    passage = passages[0]
    assert passage.provenance_token_ids == ("visible", "punctuation", "zero-width")
    assert passage.punctuation_token_ids == ("punctuation",)
    assert passage.zero_width_token_ids == ("zero-width",)
    assert passage.values("lemma") == ("lemma",)
    assert passage.values("root") == ()
    assert passage.values("english_gloss") == ("make", "good")
    assert [item.position_in_passage for item in passage.english_gloss] == [1, 1]
    assert passage.english_gloss[0].source_word_id == "word-1"
    with pytest.raises(LexicalSequenceError, match="unsupported sequence family"):
        passage.values("provenance_token_ids")


def test_greek_elision_is_preserved_but_not_used_as_an_inferred_feature(tmp_path: Path) -> None:
    database = tmp_path / "sequences.duckdb"
    _create_sequence_database(database)
    with duckdb.connect(str(database)) as connection:
        _insert_passage(
            connection,
            passage_id="p1",
            corpus="greek",
            reading="source",
            token_ids=("g1",),
        )
        connection.execute(
            "INSERT INTO greek_tokens VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["g1", "g-word", "λόγος", "λόγος", "noun", "{}", "word", False, "λογοσ", True],
        )

    passage = next(
        _bounded_passage_sequences(
            database,
            corpus="greek",
            analysis_profile="edition_complete",
            analysis_reading="source",
            granularity="verse",
        )
    )
    assert passage.values("lemma") == ("λόγος",)
    assert passage.values("folded_surface") == ("λογοσ",)
    assert passage.elided_token_ids == ("g1",)


def test_unresolved_membership_and_invalid_reading_fail_clearly(tmp_path: Path) -> None:
    database = tmp_path / "sequences.duckdb"
    _create_sequence_database(database)
    with duckdb.connect(str(database)) as connection:
        _insert_passage(
            connection,
            passage_id="p1",
            corpus="hebrew",
            reading="qere",
            token_ids=("missing",),
        )

    with pytest.raises(LexicalSequenceError, match="does not resolve"):
        list(
            _bounded_passage_sequences(
                database,
                corpus="hebrew",
                analysis_profile="edition_complete",
                analysis_reading="qere",
                granularity="verse",
            )
        )
    with pytest.raises(LexicalSequenceError, match="not valid"):
        list(
            _bounded_passage_sequences(
                database,
                corpus="greek",
                analysis_profile="edition_complete",
                analysis_reading="qere",
                granularity="verse",
            )
        )


def test_noncontiguous_membership_positions_fail_instead_of_reordering_silently(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sequences.duckdb"
    _create_sequence_database(database)
    with duckdb.connect(str(database)) as connection:
        _insert_passage(
            connection,
            passage_id="p1",
            corpus="hebrew",
            reading="qere",
            token_ids=("t1", "t2"),
        )
        connection.execute(
            "UPDATE passage_membership SET position_in_passage=3 WHERE token_id='t2'"
        )
        connection.executemany(
            "INSERT INTO hebrew_tokens VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("t1", "w1", "a", "a", "noun", "{}", "a", False, None, False),
                ("t2", "w2", "b", "b", "noun", "{}", "b", False, None, False),
            ],
        )

    with pytest.raises(LexicalSequenceError, match="not contiguous"):
        list(
            _bounded_passage_sequences(
                database,
                corpus="hebrew",
                analysis_profile="edition_complete",
                analysis_reading="qere",
                granularity="verse",
            )
        )
