"""Exact pure benchmark metric-contract tests."""

from __future__ import annotations

import math

import pytest

from echoes.benchmarks.metrics import (
    OPENBIBLE_LABEL_QUALITY,
    LabelQuality,
    MetricContext,
    RankedQuery,
    evaluate_metrics,
    evaluate_metrics_by_stratum,
    ndcg_at_k,
    passage_length_bucket,
)


def _context(*, label_quality: LabelQuality = OPENBIBLE_LABEL_QUALITY) -> MetricContext:
    return MetricContext(
        benchmark_version="benchmark-v1",
        included_tiers=(3,),
        mapping_eligibility="mapped_provisional_or_better",
        split_strategy="held-book",
        label_quality=label_quality,
        source_ids=("openbible-cross-references",),
    )


def _queries() -> list[RankedQuery]:
    return [
        RankedQuery(
            query_id="q1",
            ranked_passage_ids=("x", "r1", "r2"),
            relevant_passage_ids=frozenset({"r1", "r2"}),
            book="ISA",
            broad_genre="Major Prophets",
            passage_length=4,
            corpus_pair="greek|hebrew",
            relationship_class="broad_cross_reference",
            benchmark_tier=3,
            mapping_confidence="provisional",
        ),
        RankedQuery(
            query_id="q2",
            ranked_passage_ids=("r3",),
            relevant_passage_ids=frozenset({"r3"}),
            book="ROM",
            broad_genre="Pauline Letters",
            passage_length=10,
            corpus_pair="greek|hebrew",
            relationship_class="broad_cross_reference",
            benchmark_tier=3,
            mapping_confidence="verified",
        ),
        RankedQuery(
            query_id="q3",
            ranked_passage_ids=(),
            relevant_passage_ids=frozenset(),
            book="GEN",
            broad_genre="Torah",
            passage_length=20,
            corpus_pair="hebrew|hebrew",
            relationship_class="broad_cross_reference",
            benchmark_tier=3,
            mapping_confidence="provisional",
        ),
        RankedQuery(
            query_id="q4",
            ranked_passage_ids=("r4",),
            relevant_passage_ids=frozenset({"r4"}),
            book="MAT",
            broad_genre="Gospels and Acts",
            passage_length=8,
            corpus_pair="greek|greek",
            relationship_class="broad_cross_reference",
            benchmark_tier=3,
            mapping_confidence="unresolved",
            exclusion_reason="mapping_ineligible",
        ),
    ]


def test_exact_hand_calculated_metrics_and_mandatory_metadata() -> None:
    results = evaluate_metrics(_queries(), _context(), additional_precision_ks=(2,))
    by_name_and_k = {(result.metric_name, result.k): result for result in results}

    assert by_name_and_k[("recall_at_5", 5)].value == 1.0
    assert by_name_and_k[("mean_reciprocal_rank", None)].value == 0.75
    assert by_name_and_k[("precision_at_10", 10)].value == pytest.approx(0.15)
    assert by_name_and_k[("precision_at_k", 2)].value == 0.5
    expected_q1_ndcg = (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert by_name_and_k[("ndcg_at_20", 20)].value == pytest.approx((expected_q1_ndcg + 1) / 2)
    assert by_name_and_k[("coverage", None)].value == pytest.approx(2 / 3)

    recall = by_name_and_k[("recall_at_5", 5)]
    assert recall.benchmark_version == "benchmark-v1"
    assert recall.included_tiers == (3,)
    assert recall.label_quality == OPENBIBLE_LABEL_QUALITY
    assert recall.eligible_queries == 2
    assert recall.excluded_queries == 2
    assert recall.exclusion_reasons == (("mapping_ineligible", 1), ("missing_relevance", 1))
    assert by_name_and_k[("coverage", None)].eligible_queries == 3
    assert by_name_and_k[("coverage", None)].exclusion_reasons == (("mapping_ineligible", 1),)


def test_openbible_only_metric_cannot_be_mislabeled_as_truth() -> None:
    with pytest.raises(ValueError, match="weak-supervision recovery"):
        MetricContext(
            benchmark_version="benchmark-v1",
            included_tiers=(3,),
            mapping_eligibility="mapped_provisional_or_better",
            split_strategy="held-book",
            label_quality="high_confidence",
            source_ids=("openbible-cross-references",),
        )


def test_zero_query_and_missing_relevance_edges_are_explicit() -> None:
    empty_results = evaluate_metrics([], _context())

    assert len(empty_results) == 7
    assert all(result.value == 0.0 for result in empty_results)
    assert all(result.eligible_queries == 0 for result in empty_results)
    assert all(result.excluded_queries == 0 for result in empty_results)


@pytest.mark.parametrize(
    ("dimension", "expected"),
    [
        ("book", {"ISA", "ROM", "GEN", "MAT"}),
        ("broad_genre", {"Major Prophets", "Pauline Letters", "Torah", "Gospels and Acts"}),
        ("passage_length_bucket", {"short_0_5", "medium_6_15", "long_16_plus"}),
        ("corpus_pair", {"greek|hebrew", "hebrew|hebrew", "greek|greek"}),
        ("relationship_class", {"broad_cross_reference"}),
        ("benchmark_tier", {"3"}),
        ("mapping_confidence", {"provisional", "verified", "unresolved"}),
    ],
)
def test_all_required_performance_strata_are_available(dimension: str, expected: set[str]) -> None:
    results = evaluate_metrics_by_stratum(
        _queries(),
        _context(),
        dimension=dimension,  # type: ignore[arg-type]
    )

    assert {result.stratum_value for result in results} == expected
    assert all(result.stratum_dimension == dimension for result in results)


def test_ranked_results_reject_duplicates_and_length_buckets_are_explicit() -> None:
    values = _queries()[0]
    with pytest.raises(ValueError, match="duplicate passage IDs"):
        RankedQuery(
            query_id="duplicate",
            ranked_passage_ids=("x", "x"),
            relevant_passage_ids=values.relevant_passage_ids,
            book=values.book,
            broad_genre=values.broad_genre,
            passage_length=values.passage_length,
            corpus_pair=values.corpus_pair,
            relationship_class=values.relationship_class,
            benchmark_tier=values.benchmark_tier,
            mapping_confidence=values.mapping_confidence,
        )

    assert passage_length_bucket(5) == "short_0_5"
    assert passage_length_bucket(6) == "medium_6_15"
    assert passage_length_bucket(16) == "long_16_plus"
    assert ndcg_at_k(values, 20) > 0
