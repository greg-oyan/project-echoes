from __future__ import annotations

import math

import pytest
from scipy.spatial.distance import cosine

from echoes.lexical.detectors import (
    bm25_idf,
    bm25_score,
    jaccard_similarity,
    longest_common_subsequence,
    rare_feature_overlap,
    tfidf_cosine_similarity,
    tfidf_idf,
    weighted_jaccard_similarity,
    weighted_sequence_alignment,
)


def test_jaccard_retains_distinct_shared_features_and_positions() -> None:
    result = jaccard_similarity(("a", "b", "a", "c"), ("b", "c", "d"))

    assert result.score == 0.5
    assert result.intersection_size == 2
    assert result.union_size == 4
    assert [
        (item.feature, item.positions_a, item.positions_b) for item in result.shared_features
    ] == [
        ("b", (1,), (0,)),
        ("c", (3,), (1,)),
    ]
    assert jaccard_similarity((), ()).score == 0.0


def test_weighted_multiset_jaccard_matches_hand_calculation() -> None:
    result = weighted_jaccard_similarity(
        ("a", "a", "b"),
        ("a", "b", "b", "c"),
        {"a": 2.0, "b": 1.0, "c": 3.0},
    )

    assert result.numerator == 3.0
    assert result.denominator == 9.0
    assert result.score == pytest.approx(1.0 / 3.0)
    assert sum(item.numerator for item in result.contributions) == result.numerator
    with pytest.raises(ValueError, match="missing weight"):
        weighted_jaccard_similarity(("a",), ("a",), {})


def test_explicit_tfidf_cosine_matches_hand_calculation() -> None:
    frequencies = {"a": 1, "b": 2, "c": 2}
    result = tfidf_cosine_similarity(
        {"a": 1, "b": 1},
        {"a": 1, "c": 1},
        frequencies,
        3,
        sublinear_tf=False,
        smooth_idf=False,
    )

    idf_a = math.log(3.0) + 1.0
    idf_other = math.log(1.5) + 1.0
    expected = idf_a**2 / (idf_a**2 + idf_other**2)
    assert result.score == pytest.approx(expected)
    assert result.dot_product == pytest.approx(idf_a**2)
    assert sum(item.dot_contribution for item in result.contributions) == pytest.approx(
        result.score
    )
    assert result.score == pytest.approx(
        1.0 - cosine((idf_a, idf_other, 0.0), (idf_a, 0.0, idf_other))
    )
    assert tfidf_idf(1, 3, smooth_idf=True) == pytest.approx(math.log(2.0) + 1.0)


def test_bm25_matches_explicit_fixture_and_query_tf_modes() -> None:
    result = bm25_score(
        {"a": 2, "b": 1},
        {"a": 3},
        {"a": 2, "b": 5},
        10,
        document_length=5,
        average_document_length=4.0,
        k1=1.2,
        b=0.75,
        query_term_frequency_mode="binary",
    )

    length_normalizer = 1.2 * (1.0 - 0.75 + 0.75 * 5.0 / 4.0)
    saturation = 3.0 * 2.2 / (3.0 + length_normalizer)
    expected = bm25_idf(2, 10) * saturation
    assert result.score == pytest.approx(expected)
    assert result.contributions[0].contribution == pytest.approx(expected)
    assert result.contributions[1].contribution == 0.0

    linear = bm25_score(
        {"a": 2},
        {"a": 3},
        {"a": 2},
        10,
        document_length=5,
        average_document_length=4.0,
        query_term_frequency_mode="linear",
    )
    binary = bm25_score(
        {"a": 2},
        {"a": 3},
        {"a": 2},
        10,
        document_length=5,
        average_document_length=4.0,
    )
    assert linear.score == pytest.approx(2.0 * binary.score)


def test_rare_overlap_is_decomposed_but_does_not_decide_eligibility() -> None:
    result = rare_feature_overlap(
        ("rare-a", "common", "rare-b"),
        ("rare-b", "rare-a"),
        {"rare-a": 1, "rare-b": 3, "common": 20},
        {"rare-a": 1, "rare-b": 2, "common": 10},
        maximum_corpus_frequency=3,
        feature_passage_ids={
            "rare-a": ("p1", "p2"),
            "rare-b": ("p1", "p2", "p3"),
        },
        passage_a_id="p1",
        passage_b_id="p2",
    )

    assert result.score == pytest.approx(1.0 + 1.0 / 3.0)
    assert [item.feature for item in result.evidence] == ["rare-a", "rare-b"]
    assert result.evidence[1].alternative_passage_ids == ("p3",)


def test_lcs_has_stable_traceback_and_all_registered_normalizations() -> None:
    tie = longest_common_subsequence(("a", "b"), ("b", "a"))
    assert tie.features == ("a",)
    assert tie.positions_a == (0,)
    assert tie.positions_b == (1,)

    result = longest_common_subsequence(
        ("a", "x", "b", "c"), ("a", "b", "c"), normalization="geometric"
    )
    assert result.features == ("a", "b", "c")
    assert result.positions_a == (0, 2, 3)
    assert result.positions_b == (0, 1, 2)
    assert result.normalized_by_shorter == 1.0
    assert result.normalized_score == pytest.approx(3.0 / math.sqrt(12.0))


def test_weighted_sequence_alignment_matches_hand_traceback() -> None:
    result = weighted_sequence_alignment(
        ("a", "x", "b"),
        ("a", "b"),
        {"a": 2.0, "x": 1.0, "b": 3.0},
        gap_penalty=0.5,
        mismatch_score=-2.0,
        mode="local",
    )

    assert result.score == pytest.approx(4.5)
    assert result.normalized_score == pytest.approx(4.5 / 5.0)
    assert [step.operation for step in result.steps] == ["match", "gap_in_b", "match"]
    assert result.matched_features == ("a", "b")
    assert result.matched_positions_a == (0, 2)
    assert result.matched_positions_b == (0, 1)
    assert sum(step.contribution for step in result.steps) == pytest.approx(result.score)


def test_weighted_sequence_alignment_ties_are_stable() -> None:
    result = weighted_sequence_alignment(
        ("a", "b"),
        ("b", "a"),
        {"a": 1.0, "b": 1.0},
        gap_penalty=1.0,
        mismatch_score=0.0,
    )

    assert result.matched_features == ("a",)
    assert result.matched_positions_a == (0,)
    assert result.matched_positions_b == (1,)
