"""Exactness and fail-closed tests for compact final-null calibration."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from echoes.final_discovery.compact_nulls import (
    CompactGroupScoreRow,
    CompactNullCalibrationError,
    calibrate_compact_ensemble_nulls,
    open_compact_group_scores,
    open_compact_null_calibration,
    write_compact_group_scores,
)
from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.nulls import (
    EnsembleNullThresholdSummary,
    build_ensemble_null_threshold_report,
    build_ensemble_null_threshold_summary,
    stratified_ensemble_null_calibration_with_reporting,
)

CONFIG = load_final_discovery_config()
PRODUCTION_CONFIG = CONFIG.model_copy(
    update={"calibration": CONFIG.calibration.model_copy(update={"production_iterations": 100})}
)


def _randomized_tied_population() -> tuple[
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
    dict[str, str],
]:
    source = random.Random(81_191)
    groups = tuple(PRODUCTION_CONFIG.ensemble.group_weights)
    values = (0.0, 0.2, 0.4, 0.4, 0.6, 0.8, 1.0)
    full_by_pair: dict[str, dict[str, float]] = {}
    ablated_by_pair: dict[str, dict[str, float]] = {}
    strata: dict[str, str] = {}
    for index in range(173):
        pair_id = f"pair-{index:04d}"
        full: dict[str, float] = {}
        ablated: dict[str, float] = {}
        for group in groups:
            score = source.choice(values)
            if score > 0.0:
                full[group] = score
            ablated_score = source.choice(tuple(value for value in values if value <= score))
            if ablated_score > 0.0:
                ablated[group] = ablated_score
        full_by_pair[pair_id] = full
        ablated_by_pair[pair_id] = ablated
        strata[pair_id] = ("alpha", "middle", "zeta")[source.randrange(3)]
    return full_by_pair, ablated_by_pair, strata


def _compact_rows(
    full_by_pair: dict[str, dict[str, float]],
    ablated_by_pair: dict[str, dict[str, float]],
    strata: dict[str, str],
) -> list[CompactGroupScoreRow]:
    groups = tuple(PRODUCTION_CONFIG.ensemble.group_weights)
    missing = PRODUCTION_CONFIG.ensemble.missing_group_score
    return [
        CompactGroupScoreRow(
            candidate_pair_id=pair_id,
            stratum=strata[pair_id],
            full_scores=tuple(full_by_pair[pair_id].get(group, missing) for group in groups),
            remove_all_english_scores=tuple(
                ablated_by_pair[pair_id].get(group, missing) for group in groups
            ),
        )
        for pair_id in sorted(full_by_pair)
    ]


def test_compact_production_rows_exactly_match_reference_on_ties_and_strata(
    tmp_path: Path,
) -> None:
    full_by_pair, ablated_by_pair, strata = _randomized_tied_population()
    seed = PRODUCTION_CONFIG.calibration.seeds["stratified_permutation"]
    iterations = PRODUCTION_CONFIG.calibration.production_iterations
    expected_full, expected_full_summaries = stratified_ensemble_null_calibration_with_reporting(
        full_by_pair,
        strata,
        config=PRODUCTION_CONFIG,
        iterations=iterations,
        seed=seed,
        calibration_scope="full",
    )
    expected_ablated, expected_ablated_summaries = (
        stratified_ensemble_null_calibration_with_reporting(
            ablated_by_pair,
            strata,
            config=PRODUCTION_CONFIG,
            iterations=iterations,
            seed=seed,
            calibration_scope="remove_all_english",
        )
    )
    expected_report = build_ensemble_null_threshold_report(
        (*expected_full_summaries, *expected_ablated_summaries),
        config=PRODUCTION_CONFIG,
        hypothesis_count=len(strata),
        iterations=iterations,
        seed=seed,
    )
    dataset = write_compact_group_scores(
        _compact_rows(full_by_pair, ablated_by_pair, strata),
        tmp_path / "scores",
        group_ids=tuple(PRODUCTION_CONFIG.ensemble.group_weights),
        missing_group_score=PRODUCTION_CONFIG.ensemble.missing_group_score,
    )
    result = calibrate_compact_ensemble_nulls(
        dataset,
        tmp_path / "calibration",
        config=PRODUCTION_CONFIG,
        iterations=iterations,
        seed=seed,
    )

    compact_full = tuple(result.iter_rows("full"))
    compact_ablated = tuple(result.iter_rows("remove_all_english"))
    assert [row.candidate_pair_id for row in compact_full] == sorted(full_by_pair)
    assert [row.candidate_pair_id for row in compact_ablated] == sorted(ablated_by_pair)
    assert [row.model_dump() for row in compact_full] == [row.model_dump() for row in expected_full]
    assert [row.model_dump() for row in compact_ablated] == [
        row.model_dump() for row in expected_ablated
    ]
    assert result.threshold_report() == expected_report


def test_compact_receipts_bind_resources_and_stream_rows(tmp_path: Path) -> None:
    full_by_pair, ablated_by_pair, strata = _randomized_tied_population()
    rows = _compact_rows(full_by_pair, ablated_by_pair, strata)[:12]
    dataset = write_compact_group_scores(
        rows,
        tmp_path / "scores",
        group_ids=tuple(PRODUCTION_CONFIG.ensemble.group_weights),
        missing_group_score=PRODUCTION_CONFIG.ensemble.missing_group_score,
    )
    result = calibrate_compact_ensemble_nulls(
        dataset,
        tmp_path / "calibration",
        config=PRODUCTION_CONFIG,
        iterations=PRODUCTION_CONFIG.calibration.production_iterations,
        seed=PRODUCTION_CONFIG.calibration.seeds["stratified_permutation"],
    )
    bounds = result.receipt.resource_bounds

    assert dataset.receipt.nested_pair_group_mappings_persisted is False
    assert dataset.receipt.maximum_builder_row_buffer_bytes == (
        2 * len(PRODUCTION_CONFIG.ensemble.group_weights) * 8
    )
    assert bounds.pair_iteration_matrix_persisted is False
    assert bounds.reporting_threshold_count == 1
    assert bounds.reporting_count_vector_cells_per_scope == (
        PRODUCTION_CONFIG.calibration.production_iterations
    )
    assert bounds.reporting_count_vectors_persisted_in_authenticated_receipt is True
    assert bounds.output_rows_retained_in_memory is False
    assert bounds.row_emission == "one_pydantic_row_at_a_time"
    assert bounds.pair_iteration_matrix_bytes_if_materialized == (
        len(rows) * PRODUCTION_CONFIG.calibration.production_iterations * 8
    )
    assert bounds.maximum_explicit_numpy_working_bytes_upper_bound > 0
    assert not any("matrix" in path.name for path in result.root.rglob("*"))
    iterator = result.iter_rows("full")
    assert iter(iterator) is iterator
    assert next(iterator).candidate_pair_id == rows[0].candidate_pair_id
    reopened = open_compact_null_calibration(result.root, input_dataset=dataset)
    assert reopened.receipt == result.receipt


def test_threshold_summary_retains_exact_counts_and_rejects_derived_tamper() -> None:
    summary = build_ensemble_null_threshold_summary(
        scope="full",
        threshold=0.65,
        observed_count=2,
        null_counts=(0, 2, 0),
        hypothesis_count=3,
    )

    assert summary.null_discovery_counts == (0, 2, 0)
    assert summary.mean_null_discovery_count == pytest.approx(0.75)
    assert summary.empirical_interval_2_5_percentile == pytest.approx(0.0)
    assert summary.empirical_interval_97_5_percentile == pytest.approx(1.9)
    assert summary.observed_to_null_enrichment == pytest.approx(8 / 3)
    assert summary.empirical_upper_tail_probability == pytest.approx(0.5)
    assert summary.estimated_empirical_fdr == pytest.approx(0.375)

    with pytest.raises(ValueError, match="mean null count"):
        EnsembleNullThresholdSummary.model_validate(
            {**summary.model_dump(mode="json"), "mean_null_discovery_count": 0.5}
        )


def test_compact_input_fails_closed_on_order_shape_ablation_and_tamper(
    tmp_path: Path,
) -> None:
    groups = tuple(PRODUCTION_CONFIG.ensemble.group_weights)
    missing = PRODUCTION_CONFIG.ensemble.missing_group_score
    zeros = (0.0,) * len(groups)
    with pytest.raises(CompactNullCalibrationError, match="strictly lexically sorted"):
        write_compact_group_scores(
            [
                CompactGroupScoreRow("pair-b", "s", zeros, zeros),
                CompactGroupScoreRow("pair-a", "s", zeros, zeros),
            ],
            tmp_path / "unordered",
            group_ids=groups,
            missing_group_score=missing,
        )
    assert not (tmp_path / "unordered" / "compact-group-scores.json").exists()

    with pytest.raises(CompactNullCalibrationError, match="vector width differs"):
        write_compact_group_scores(
            [CompactGroupScoreRow("pair-a", "s", (0.0,), (0.0,))],
            tmp_path / "wrong-width",
            group_ids=groups,
            missing_group_score=missing,
        )
    with pytest.raises(CompactNullCalibrationError, match="exceeds full score"):
        write_compact_group_scores(
            [
                CompactGroupScoreRow(
                    "pair-a",
                    "s",
                    zeros,
                    (1.0, *zeros[1:]),
                )
            ],
            tmp_path / "bad-ablation",
            group_ids=groups,
            missing_group_score=missing,
        )

    dataset = write_compact_group_scores(
        [CompactGroupScoreRow("pair-a", "s", zeros, zeros)],
        tmp_path / "valid",
        group_ids=groups,
        missing_group_score=missing,
    )
    score_path = dataset.root / "full-scores.f64"
    payload = bytearray(score_path.read_bytes())
    payload[0] ^= 1
    score_path.write_bytes(payload)
    with pytest.raises(CompactNullCalibrationError, match="size or SHA-256 differs"):
        open_compact_group_scores(dataset.root)


def test_compact_calibration_rejects_fixture_iterations_and_wrong_seed(
    tmp_path: Path,
) -> None:
    groups = tuple(PRODUCTION_CONFIG.ensemble.group_weights)
    zeros = (0.0,) * len(groups)
    dataset = write_compact_group_scores(
        [CompactGroupScoreRow("pair-a", "s", zeros, zeros)],
        tmp_path / "scores",
        group_ids=groups,
        missing_group_score=PRODUCTION_CONFIG.ensemble.missing_group_score,
    )
    with pytest.raises(CompactNullCalibrationError, match="production iteration count"):
        calibrate_compact_ensemble_nulls(
            dataset,
            tmp_path / "fixture-output",
            config=PRODUCTION_CONFIG,
            iterations=PRODUCTION_CONFIG.calibration.fixture_iterations,
            seed=PRODUCTION_CONFIG.calibration.seeds["stratified_permutation"],
        )
    with pytest.raises(CompactNullCalibrationError, match="permutation seed"):
        calibrate_compact_ensemble_nulls(
            dataset,
            tmp_path / "wrong-seed-output",
            config=PRODUCTION_CONFIG,
            iterations=PRODUCTION_CONFIG.calibration.production_iterations,
            seed=PRODUCTION_CONFIG.calibration.seeds["stratified_permutation"] + 1,
        )
