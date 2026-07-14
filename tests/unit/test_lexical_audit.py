"""Sanitized lexical-feature audit contracts."""

from __future__ import annotations

from echoes.lexical.audit import _qere_ketiv_frequency_changes, _sanitized_feature_rows
from echoes.lexical.sequences import FeatureOccurrence, PassageLexicalSequence


def _occurrence(value: str, position: int) -> FeatureOccurrence:
    return FeatureOccurrence(
        value=value,
        token_id=f"T{position}",
        position_in_passage=position,
        source_word_id=f"W{position}",
    )


def _passage(
    passage_id: str,
    reference: str,
    lemmas: tuple[str, ...],
    *,
    reading: str = "qere",
) -> PassageLexicalSequence:
    occurrences = tuple(_occurrence(value, index) for index, value in enumerate(lemmas))
    return PassageLexicalSequence(
        passage_id=passage_id,
        corpus="hebrew",
        book="GEN",
        book_order=1,
        analysis_profile="edition_complete",
        analysis_reading=reading,
        granularity="verse",
        start_reference=reference,
        end_reference=reference,
        source_passage_digest="a" * 64,
        start_stream_position_in_corpus=0,
        token_count=len(lemmas),
        disputed_passage_flag=False,
        reference_gap=False,
        ketiv_structural_uncertainty=reading == "ketiv",
        lemma=occurrences,
        root=(),
        surface=occurrences,
        folded_surface=occurrences,
        part_of_speech=(),
        morphology=(),
        english_gloss=(),
        provenance_token_ids=tuple(item.token_id for item in occurrences),
        zero_width_token_ids=(),
        punctuation_token_ids=(),
        elided_token_ids=(),
    )


def test_sanitized_feature_tables_expose_ids_and_counts_not_values() -> None:
    source_value = "restricted-lemma-value"
    sequences = (
        _passage("P1", "GEN 1:1", (source_value, "common")),
        _passage("P2", "GEN 1:2", (source_value, "common")),
    )

    tables = _sanitized_feature_rows(
        (("hebrew", "hb", sequences),),
        formulaic_ratio=0.5,
        formulaic_minimum_count=2,
        rare_maximum_count=3,
    )
    serialized = repr(tables)

    assert source_value not in serialized
    assert "LF_" in serialized
    assert any(row[1] == "lemma_2gram" for row in tables[0])


def test_qere_ketiv_frequency_changes_are_reference_paired_and_id_only() -> None:
    source_value = "changed-restricted-lemma"
    qere = (_passage("Q1", "GEN 1:1", (source_value, "stable")),)
    ketiv = (
        _passage("K1", "GEN 1:1", ("replacement", "stable"), reading="ketiv"),
        _passage("K2", "GEN 1:2", ("unpaired",), reading="ketiv"),
    )

    rows = _qere_ketiv_frequency_changes(qere, ketiv)

    assert len(rows) == 2
    assert all(str(row[0]).startswith("LF_") for row in rows)
    assert source_value not in repr(rows)
    assert {int(row[3]) for row in rows} == {-1, 1}
