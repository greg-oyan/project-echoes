from __future__ import annotations

import math

import pytest

from echoes.lexical.composite import (
    EvidenceSignal,
    independent_cosignals,
    rank_scored_candidates,
    reciprocal_rank_fusion,
)
from echoes.lexical.phrases import (
    bigram_log_likelihood,
    contiguous_ngrams,
    log_likelihood_ratio,
    pointwise_mutual_information,
    skip_grams,
)


def test_ngram_and_skipgram_positions_are_exact_and_stable() -> None:
    ngrams = contiguous_ngrams(("a", "b", "c", "d"), 3)
    assert [(item.features, item.positions) for item in ngrams] == [
        (("a", "b", "c"), (0, 1, 2)),
        (("b", "c", "d"), (1, 2, 3)),
    ]

    skipped = skip_grams(("a", "b", "c", "d"), 2, max_gap=1)
    assert [(item.features, item.positions) for item in skipped] == [
        (("a", "c"), (0, 2)),
        (("b", "d"), (1, 3)),
    ]
    with_contiguous = skip_grams(("a", "b", "c"), 2, max_gap=1, include_contiguous=True)
    assert [item.positions for item in with_contiguous] == [(0, 1), (0, 2), (1, 2)]


def test_pmi_matches_hand_calculation_and_controls_one_offs_and_caps() -> None:
    result = pointwise_mutual_information(2, (4, 5), 20, minimum_count=2)
    assert result.raw_value == pytest.approx(1.0)
    assert result.value == pytest.approx(1.0)
    assert result.eligible is True

    one_off = pointwise_mutual_information(1, (2, 2), 100, minimum_count=2)
    assert one_off.value == 0.0
    assert one_off.raw_value is None
    assert one_off.eligible is False

    capped = pointwise_mutual_information(2, (2, 2), 100, minimum_count=2, cap=3.0)
    assert capped.raw_value is not None and capped.raw_value > 3.0
    assert capped.value == 3.0
    assert capped.capped is True


def test_log_likelihood_matches_explicit_contingency_calculation() -> None:
    result = log_likelihood_ratio(10, 5, 5, 80)
    observed = result.observed_cells
    expected = result.expected_cells
    hand = 2.0 * sum(
        cell * math.log(cell / expected_cell) if cell else 0.0
        for cell, expected_cell in zip(observed, expected, strict=True)
    )
    assert result.statistic == pytest.approx(hand)
    assert result.signed_statistic > 0.0

    constructed = bigram_log_likelihood(10, 15, 15, 100)
    assert constructed.observed_cells == (10, 5, 5, 80)
    assert constructed.statistic == pytest.approx(result.statistic)


def test_score_ties_resolve_by_candidate_id() -> None:
    assert rank_scored_candidates({"candidate-b": 1.0, "candidate-a": 1.0, "z": 0.5}) == (
        "candidate-a",
        "candidate-b",
        "z",
    )


def test_rrf_reconciles_contributions_and_suppresses_correlated_family_votes() -> None:
    result = reciprocal_rank_fusion(
        {
            "tfidf": ("a", "b"),
            "bm25": ("b", "a"),
            "phrase": ("a", "b"),
        },
        {"tfidf": "vector", "bm25": "vector", "phrase": "phrase"},
        rrf_k=10,
    )

    candidate_a = result.candidates[0]
    assert candidate_a.candidate_id == "a"
    assert candidate_a.score == pytest.approx(1.0 / 11.0 + 1.0 / 11.0)
    assert {item.detector for item in candidate_a.contributions} == {"tfidf", "phrase"}
    assert [item.detector for item in candidate_a.suppressed_contributions] == ["bm25"]
    assert candidate_a.score == pytest.approx(sum(item.value for item in candidate_a.contributions))

    all_votes = reciprocal_rank_fusion(
        {"tfidf": ("a",), "bm25": ("a",)},
        {"tfidf": "vector", "bm25": "vector"},
        rrf_k=10,
        family_policy="all",
    )
    assert all_votes.candidates[0].score == pytest.approx(2.0 / 11.0)


def test_independent_cosignal_guard_rejects_correlated_restatements() -> None:
    primary = frozenset({"hb:lemma:rare-a"})
    signals = (
        EvidenceSignal(
            "tfidf",
            "vector",
            "rare-a-only",
            frozenset({"hb:lemma:rare-a"}),
        ),
        EvidenceSignal(
            "bm25",
            "vector",
            "rare-a-only",
            frozenset({"hb:lemma:rare-a"}),
        ),
        EvidenceSignal(
            "phrase",
            "phrase",
            "lexical-extra",
            frozenset({"hb:lemma:rare-a", "hb:lemma:additional"}),
        ),
        EvidenceSignal(
            "sequence",
            "ordered_sequence",
            "lexical-extra",
            frozenset({"hb:lemma:rare-a", "hb:lemma:other"}),
        ),
        EvidenceSignal(
            "second-rare",
            "rare_lexical",
            "second-rare",
            frozenset({"hb:lemma:rare-a", "hb:lemma:rare-b"}),
        ),
        EvidenceSignal(
            "same-token-root",
            "rare_lexical",
            "source-token-1",
            frozenset({"hb:root:duplicate-of-rare-a"}),
        ),
        EvidenceSignal(
            "english-gloss",
            "english_bridge",
            "english",
            frozenset({"hb:lemma:rare-a", "en:gloss:item"}),
            english_derived=True,
        ),
    )

    result = independent_cosignals(
        primary,
        signals,
        primary_independence_keys=frozenset({"source-token-1"}),
    )
    assert [signal.signal_id for signal in result.accepted] == ["phrase", "second-rare"]
    reasons = {item.signal.signal_id: item.reason for item in result.rejected}
    assert reasons == {
        "bm25": "deterministic_restatement",
        "english-gloss": "english_derived",
        "same-token-root": "deterministic_restatement",
        "sequence": "correlated_duplicate",
        "tfidf": "deterministic_restatement",
    }
