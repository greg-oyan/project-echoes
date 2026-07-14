from __future__ import annotations

from dataclasses import replace

import pytest

from echoes.lexical.evaluation import (
    REQUIRED_BASELINES,
    TIER3_DISPLAY_LABEL,
    TIER3_LABEL_QUALITY,
    BaselineRankings,
    Tier3EvaluationContractError,
    Tier3EvaluationQuery,
    build_required_baseline_rankings,
    deterministic_random_ranking,
    evaluate_tier3_recovery,
    length_matched_ranking,
    unweighted_overlap_ranking,
    validate_leakage_partitions,
)


def _query(index: int, *, excluded: bool = False) -> Tier3EvaluationQuery:
    return Tier3EvaluationQuery(
        query_id=f"query-{index:02d}",
        relevant_passage_ids=frozenset({f"relevant-{index:02d}"}),
        relationship_ids=frozenset({f"relationship-{index:02d}"}),
        analysis_profile="edition_complete",
        mapping_status="mapped_verified",
        corpus_pair="hb_hb",
        split_strategy="held_out_book",
        partition="test",
        source_book="GEN",
        target_book="EXO",
        broad_genre="torah",
        passage_length=10,
        vote_stratum="three_to_five",
        disputed_passage=False,
        reference_gap=False,
        leakage_group_id=f"leakage-{index:02d}",
        exclusion_reason="mapping_gap" if excluded else None,
    )


def test_required_baseline_builders_are_transparent_and_deterministic() -> None:
    query = _query(1)
    candidates = ("a", "b", "c")

    random_first = deterministic_random_ranking(candidates, query_id=query.query_id, seed=42)
    random_second = deterministic_random_ranking(
        tuple(reversed(candidates)), query_id=query.query_id, seed=42
    )
    assert random_first == random_second
    assert length_matched_ranking(
        candidates,
        query_length=5,
        target_lengths={"a": 5, "b": 4, "c": 20},
    ) == ("a", "b", "c")
    assert unweighted_overlap_ranking(
        candidates,
        query_features=("x", "y"),
        target_features={"a": (), "b": ("x",), "c": ("x", "y")},
    ) == ("c", "b", "a")

    built = build_required_baseline_rankings(
        (query,),
        candidate_passage_ids_by_query={query.query_id: candidates},
        target_lengths={"a": 5, "b": 4, "c": 20},
        query_features={query.query_id: ("x", "y")},
        target_features={"a": (), "b": ("x",), "c": ("x", "y")},
        random_seed=42,
    )
    assert set(built) == set(REQUIRED_BASELINES)
    assert built["length_matched"][query.query_id] == ("a", "b", "c")
    assert built["unweighted_overlap"][query.query_id] == ("c", "b", "a")


def test_leakage_groups_cannot_cross_partitions_within_a_split() -> None:
    first = _query(1)
    second = replace(first, query_id="query-02", partition="train")

    with pytest.raises(Tier3EvaluationContractError, match="leakage group crosses"):
        validate_leakage_partitions((first, second))


def _rankings(
    queries: tuple[Tier3EvaluationQuery, ...],
) -> tuple[dict[str, tuple[str, ...]], BaselineRankings]:
    method: dict[str, tuple[str, ...]] = {}
    baselines: BaselineRankings = {name: {} for name in REQUIRED_BASELINES}
    for query in queries:
        relevant = next(iter(query.relevant_passage_ids))
        distractors = tuple(f"{query.query_id}-distractor-{index:02d}" for index in range(25))
        method[query.query_id] = (relevant, *distractors)
        poor_ranking = (*distractors, relevant)
        for baseline in REQUIRED_BASELINES:
            baselines[baseline][query.query_id] = poor_ranking
    return method, baselines


def test_tier3_evaluation_reports_all_metrics_paired_baselines_and_strict_gate() -> None:
    queries = tuple(_query(index, excluded=index == 11) for index in range(12))
    method, baselines = _rankings(queries)

    report = evaluate_tier3_recovery(
        queries,
        detector="composite_rrf",
        representation_id="hb:lemma",
        method_rankings=method,
        baseline_rankings=baselines,
        benchmark_version="known-links-v1-test",
        config_hash="a" * 64,
        preregistration_digest="b" * 64,
        bootstrap_iterations=1_000,
        bootstrap_seed=7201,
        minimum_eligible_queries=10,
        minimum_eligible_relationships=10,
    )
    repeated = evaluate_tier3_recovery(
        queries,
        detector="composite_rrf",
        representation_id="hb:lemma",
        method_rankings=method,
        baseline_rankings=baselines,
        benchmark_version="known-links-v1-test",
        config_hash="a" * 64,
        preregistration_digest="b" * 64,
        bootstrap_iterations=1_000,
        bootstrap_seed=7201,
        minimum_eligible_queries=10,
        minimum_eligible_relationships=10,
    )

    assert report == repeated

    global_system = {
        row.metric: row
        for row in report.metrics
        if row.stratum_dimension == "global" and row.ranking_role == "system"
    }
    assert set(global_system) == {
        "recall_at_5",
        "recall_at_10",
        "recall_at_20",
        "mean_reciprocal_rank",
        "ndcg_at_20",
        "precision_at_10",
        "coverage",
    }
    assert global_system["recall_at_20"].value == 1.0
    assert global_system["recall_at_20"].eligible_query_count == 11
    assert global_system["recall_at_20"].excluded_count == 1
    assert global_system["recall_at_20"].exclusion_reasons == (("mapping_gap", 1),)
    assert all(row.bootstrap_iterations == 1_000 for row in report.metrics)
    assert all(row.label_quality == TIER3_LABEL_QUALITY for row in report.metrics)
    assert all(row.display_label == TIER3_DISPLAY_LABEL for row in report.metrics)
    assert {row.ranking_name for row in report.metrics if row.ranking_role == "baseline"} == set(
        REQUIRED_BASELINES
    )

    recall_comparisons = [
        row
        for row in report.baseline_comparisons
        if row.stratum_dimension == "corpus_pair"
        and row.stratum_value == "hb_hb"
        and row.metric == "recall_at_20"
    ]
    assert {row.baseline for row in recall_comparisons} == set(REQUIRED_BASELINES)
    assert all(row.bootstrap_interval_low > 0.0 for row in recall_comparisons)

    gates = {gate.corpus_pair: gate for gate in report.primary_stratum_gates}
    assert gates["hb_hb"].status == "passes"
    assert gates["hb_hb"].recall_at_20_beats_random is True
    assert gates["hb_hb"].recall_at_20_beats_unweighted_overlap is True
    assert gates["gnt_gnt"].status == "insufficient_data_no_claim"
    assert gates["gnt_gnt"].recall_at_20_beats_random is None
    assert gates["gnt_gnt"].high_confidence_claim_allowed is False
    assert report.tier1_claim_tested is False


def test_sufficient_gate_fails_when_method_does_not_beat_simple_overlap() -> None:
    queries = tuple(_query(index) for index in range(10))
    method, baselines = _rankings(queries)
    baselines["unweighted_overlap"] = dict(method)

    report = evaluate_tier3_recovery(
        queries,
        detector="bm25",
        representation_id="hb:lemma",
        method_rankings=method,
        baseline_rankings=baselines,
        benchmark_version="known-links-v1-test",
        config_hash="a" * 64,
        preregistration_digest="b" * 64,
        bootstrap_iterations=1_000,
        bootstrap_seed=7201,
        minimum_eligible_queries=10,
        minimum_eligible_relationships=10,
        primary_original_language_corpus_pairs=("hb_hb",),
    )

    gate = report.primary_stratum_gates[0]
    assert gate.sufficient_data
    assert gate.recall_at_20_beats_random is True
    assert gate.recall_at_20_beats_unweighted_overlap is False
    assert gate.status == "fails"
