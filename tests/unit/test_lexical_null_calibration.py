from __future__ import annotations

from collections import Counter

import pytest

from echoes.lexical.null_calibration import (
    CALIBRATION_PAIR_SAMPLE_SIZE,
    CANDIDATE_UNION_SAMPLE_SCOPE,
    NO_GLOBAL_ALL_PAIRS_CLAIM,
    CandidateUnionSample,
    GovernedScoringStratum,
    NullCalibrationContractError,
    NullReplicatePlanEntry,
    NullReplicateThresholdSummary,
    build_null_replicate_plan,
    calibrate_governed_thresholds,
    calibrate_threshold_grid,
    sample_candidate_union_pairs,
    summarize_null_replicate_scores,
    validate_null_replicate_conservation,
)
from echoes.lexical.nulls import (
    NullFamily,
    NullValidationResult,
    PassageFeatures,
    within_book_reassignment,
)


def _pair_ids(count: int = CALIBRATION_PAIR_SAMPLE_SIZE) -> tuple[str, ...]:
    return tuple(f"pair-{index:05d}" for index in range(count))


def _sample() -> CandidateUnionSample:
    return sample_candidate_union_pairs(_pair_ids(), seed=7001)


def test_candidate_union_sample_is_fixed_scoped_and_order_invariant() -> None:
    candidates = _pair_ids(CALIBRATION_PAIR_SAMPLE_SIZE + 17)

    first = sample_candidate_union_pairs(candidates, seed=7001)
    second = sample_candidate_union_pairs(tuple(reversed(candidates)), seed=7001)

    assert first == second
    assert len(first.pair_ids) == 20_000
    assert first.source_candidate_count == 20_017
    assert first.scope == CANDIDATE_UNION_SAMPLE_SCOPE
    assert first.global_all_pairs_claim_allowed is False
    assert first.scope_note == NO_GLOBAL_ALL_PAIRS_CLAIM

    with pytest.raises(NullCalibrationContractError, match="exactly 20000"):
        sample_candidate_union_pairs(_pair_ids(19_999), seed=7001)
    with pytest.raises(NullCalibrationContractError, match="exactly 20,000"):
        sample_candidate_union_pairs(candidates, seed=7001, sample_size=1_000)


def test_plan_has_two_complete_unique_deterministic_seed_series_per_stratum() -> None:
    strata = (
        GovernedScoringStratum("hb_hb", "hb:lemma", "bm25"),
        GovernedScoringStratum("gnt_gnt", "gk:lemma", "composite_rrf"),
    )
    seeds = {
        "within_book_reassignment": 7101,
        "frequency_preserving_synthetic": 7102,
    }

    first = build_null_replicate_plan(strata, family_base_seeds=seeds)
    second = build_null_replicate_plan(tuple(reversed(strata)), family_base_seeds=seeds)

    assert first == second
    assert len(first) == 400
    assert len({entry.seed for entry in first}) == 400
    counts = Counter((entry.stratum, entry.family) for entry in first)
    assert set(counts.values()) == {100}
    assert all(
        {entry.iteration for entry in first if (entry.stratum, entry.family) == key}
        == set(range(1, 101))
        for key in counts
    )

    with pytest.raises(NullCalibrationContractError, match="at least 100"):
        build_null_replicate_plan(
            strata,
            family_base_seeds=seeds,
            iterations_per_family=99,
        )


def test_scored_replicate_retains_conservation_and_sample_scope() -> None:
    source = (
        PassageFeatures("p1", "hebrew", "GEN", "torah", "hb:lemma", ("a", "b")),
        PassageFeatures("p2", "hebrew", "GEN", "torah", "hb:lemma", ("c", "d")),
    )
    stratum = GovernedScoringStratum("hb_hb", "hb:lemma", "jaccard")
    plan = build_null_replicate_plan(
        (stratum,),
        family_base_seeds={
            "within_book_reassignment": 7101,
            "frequency_preserving_synthetic": 7102,
        },
    )[0]
    replicate = within_book_reassignment(source, seed=plan.seed)
    validation = validate_null_replicate_conservation(source, replicate)
    sample = _sample()

    summary = summarize_null_replicate_scores(
        plan=plan,
        replicate=replicate,
        validation=validation,
        scores=(0.75,) * len(sample.pair_ids),
        thresholds=(0.5, 0.9),
        sample=sample,
    )

    assert summary.validation.is_valid
    assert summary.threshold_counts == ((0.5, 20_000), (0.9, 0))
    assert summary.candidate_sample_digest == sample.logical_digest
    assert summary.selection_scope == CANDIDATE_UNION_SAMPLE_SCOPE
    assert summary.global_all_pairs_claim_allowed is False


def _valid_validation(family: NullFamily) -> NullValidationResult:
    return NullValidationResult(
        family=family,
        passage_count_preserved=True,
        passage_lengths_preserved=True,
        conditioning_labels_preserved=True,
        source_identities_replaced=True,
        representation_isolation_preserved=True,
        exact_feature_totals_preserved=True if family == "within_book_reassignment" else None,
        sequence_digest_changed=True,
        no_original_sequences_copied=(None if family == "within_book_reassignment" else True),
        degenerate_units=(),
        frequency_deviations=(),
        errors=(),
    )


def _summary(
    plan_entry: NullReplicatePlanEntry,
    sample: CandidateUnionSample,
) -> NullReplicateThresholdSummary:
    # The helper remains explicit so calibration is tested independently of scoring cost.
    return NullReplicateThresholdSummary(
        plan=plan_entry,
        candidate_sample_digest=sample.logical_digest,
        candidate_sample_size=len(sample.pair_ids),
        mean_score=0.1,
        score_quantiles=(("q025", 0.0), ("q50", 0.1), ("q975", 0.9)),
        threshold_counts=((0.5, 1_000), (0.9, 50)),
        passage_count=2,
        token_count=4,
        length_digest="a" * 64,
        frequency_digest="b" * 64,
        logical_output_hash=f"{plan_entry.seed:064x}"[-64:],
        validation=_valid_validation(plan_entry.family),
    )


def test_threshold_grid_requires_both_complete_families_and_selects_without_identities() -> None:
    stratum = GovernedScoringStratum("hb_hb", "hb:lemma", "composite_rrf")
    plan = build_null_replicate_plan(
        (stratum,),
        family_base_seeds={
            "within_book_reassignment": 7101,
            "frequency_preserving_synthetic": 7102,
        },
    )
    sample = _sample()
    summaries = tuple(_summary(entry, sample) for entry in plan)
    observed_scores = (0.95,) * 500 + (0.6,) * 2_000 + (0.0,) * 17_500

    result = calibrate_threshold_grid(
        stratum=stratum,
        observed_scores=observed_scores,
        summaries=summaries,
        thresholds=(0.5, 0.9),
        sample=sample,
        maximum_empirical_fdr=0.2,
    )

    assert result.selected_threshold == 0.9
    assert [row.selected for row in result.thresholds] == [False, True]
    assert [row.qualifies_empirical_fdr for row in result.thresholds] == [False, True]
    assert result.thresholds[0].observed_candidate_count == 2_500
    assert result.thresholds[1].observed_candidate_count == 500
    assert result.thresholds[1].pooled_calibration.null_mean_count == 50
    assert result.thresholds[1].pooled_calibration.raw_empirical_fdr == pytest.approx(0.1)
    assert result.thresholds[
        1
    ].pooled_calibration.empirical_upper_tail_probability == pytest.approx(1 / 201)
    assert {item.family for item in result.thresholds[1].family_calibrations} == {
        "within_book_reassignment",
        "frequency_preserving_synthetic",
    }
    assert all(row.global_all_pairs_claim_allowed is False for row in result.thresholds)

    governed = calibrate_governed_thresholds(
        observed_scores_by_stratum={stratum: observed_scores},
        summaries=summaries,
        samples_by_stratum={stratum: sample},
        thresholds_by_detector={"composite_rrf": (0.5, 0.9)},
        maximum_empirical_fdr=0.2,
    )
    assert governed == (result,)

    with pytest.raises(NullCalibrationContractError, match="missing threshold grids"):
        calibrate_governed_thresholds(
            observed_scores_by_stratum={stratum: observed_scores},
            summaries=summaries,
            samples_by_stratum={stratum: sample},
            thresholds_by_detector={},
            maximum_empirical_fdr=0.2,
        )

    with pytest.raises(NullCalibrationContractError, match="has 99 summaries"):
        calibrate_threshold_grid(
            stratum=stratum,
            observed_scores=observed_scores,
            summaries=summaries[:-1],
            thresholds=(0.5, 0.9),
            sample=sample,
            maximum_empirical_fdr=0.2,
        )
