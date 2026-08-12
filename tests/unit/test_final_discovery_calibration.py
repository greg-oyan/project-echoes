"""Regression tests for registered production null calibration."""

from __future__ import annotations

import json
import math
import random

import pytest

from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.ensemble import calibrate_detector_evidence
from echoes.final_discovery.features import candidate_pair_id
from echoes.final_discovery.models import RawEvidence
from echoes.final_discovery.nulls import (
    NullControlError,
    detector_reference_and_null_scores,
    production_detector_calibration,
    stratified_ensemble_null_calibration,
)

CONFIG = load_final_discovery_config()
REGISTRATIONS = {item.detector_id: item for item in CONFIG.detectors}
SOURCE_HASH = "d" * 64


def _raw(
    detector_id: str,
    left: str,
    right: str,
    score: float,
    *,
    m7_nulls_present: bool = True,
) -> RawEvidence:
    registration = REGISTRATIONS[detector_id]
    pair_id = candidate_pair_id(left, right)
    trace = (
        {"m7_both_null_families_present": m7_nulls_present}
        if detector_id == "m7_lexical_rrf"
        else {"fixture": detector_id}
    )
    return RawEvidence(
        candidate_pair_id=pair_id,
        passage_a_id=min(left, right),
        passage_b_id=max(left, right),
        detector_id=detector_id,
        family=registration.family,
        independence_group=registration.independence_group,
        raw_score=score,
        contains_english_derived_evidence=False,
        original_language_evidence_remains=True,
        counts_for_independence=registration.counts_for_independence,
        trace_json=json.dumps(trace),
        source_artifact_id="fixture",
        source_artifact_sha256=SOURCE_HASH,
    )


def test_production_detector_calibration_dispatches_registered_families_and_seeds() -> None:
    raw = (
        _raw("m7_lexical_rrf", "A", "B", 0.9),
        _raw("m7_lexical_rrf", "C", "D", 0.4),
        _raw("lemma_root_sequence_semantic", "A", "B", 0.8),
        _raw("lemma_root_sequence_semantic", "C", "D", 0.3),
        _raw("semantic_domain_overlap", "A", "B", 0.7),
        _raw("semantic_domain_overlap", "C", "D", 0.2),
    )
    strata = {candidate_pair_id("A", "B"): "books-1", candidate_pair_id("C", "D"): "books-1"}

    result = production_detector_calibration(
        raw,
        strata,
        config=CONFIG,
        iterations=CONFIG.calibration.production_iterations,
    )
    repeated = production_detector_calibration(
        raw,
        strata,
        config=CONFIG,
        iterations=CONFIG.calibration.production_iterations,
    )

    assert result == repeated
    m7 = result.provenance_by_detector["m7_lexical_rrf"]
    synthetic = result.provenance_by_detector["lemma_root_sequence_semantic"]
    permutation = result.provenance_by_detector["semantic_domain_overlap"]
    assert (m7["registered_null_family"], m7["registered_seed"]) == (
        "within_book_reassignment",
        CONFIG.calibration.seeds["within_book_reassignment"],
    )
    assert m7["source_null_families"] == (
        "within_book_reassignment",
        "frequency_preserving_synthetic",
    )
    assert m7["source_null_validation"] == ("authenticated_m7_both_null_families_present_trace")
    assert (synthetic["registered_null_family"], synthetic["registered_seed"]) == (
        "stratified_score_bootstrap",
        CONFIG.calibration.seeds["stratified_score_bootstrap"],
    )
    assert (permutation["registered_null_family"], permutation["registered_seed"]) == (
        "stratified_permutation",
        CONFIG.calibration.seeds["stratified_permutation"],
    )
    assert "null_scores" not in result.as_json_object()
    assert len(result.rows()) == len(raw)

    calibrated = calibrate_detector_evidence(raw, config=CONFIG, calibration=result)
    result_rows = {(row.detector_id, row.candidate_pair_id): row for row in result.rows()}
    assert all(
        row.empirical_p_value
        == result_rows[(row.detector_id, row.candidate_pair_id)].empirical_p_value
        for row in calibrated
    )
    assert all(row.null_method == REGISTRATIONS[row.detector_id].null_family for row in calibrated)


def test_production_rejects_unverified_m7_nulls_and_fixture_fallback() -> None:
    raw = (_raw("m7_lexical_rrf", "A", "B", 0.9, m7_nulls_present=False),)
    with pytest.raises(NullControlError, match="both canonical M7 null families"):
        production_detector_calibration(
            raw,
            {candidate_pair_id("A", "B"): "books-1"},
            config=CONFIG,
            iterations=CONFIG.calibration.production_iterations,
        )

    with pytest.raises(NullControlError, match="fixture-only"):
        detector_reference_and_null_scores(
            {"detector": [0.1, 0.2]},
            iterations=20,
            seed=1,
            execution_mode="production",  # type: ignore[arg-type]
        )


def _explicit_final_null(
    group_scores: dict[str, dict[str, float]],
    strata: dict[str, str],
    *,
    iterations: int,
) -> dict[str, list[float]]:
    groups = tuple(CONFIG.ensemble.group_weights)
    members_by_stratum: dict[str, list[str]] = {}
    for pair_id, stratum in strata.items():
        members_by_stratum.setdefault(stratum, []).append(pair_id)
    source = random.Random(CONFIG.calibration.seeds["stratified_permutation"])
    result = {pair_id: [] for pair_id in group_scores}
    for _ in range(iterations):
        reassigned = {pair_id: {} for pair_id in group_scores}
        for stratum in sorted(members_by_stratum):
            members = sorted(members_by_stratum[stratum])
            for group in groups:
                values = [group_scores[pair_id].get(group, 0.0) for pair_id in members]
                source.shuffle(values)
                for pair_id, value in zip(members, values, strict=True):
                    reassigned[pair_id][group] = value
        for pair_id in sorted(group_scores):
            result[pair_id].append(
                math.fsum(
                    CONFIG.ensemble.group_weights[group] * reassigned[pair_id][group]
                    for group in groups
                )
            )
    return result


def test_streaming_final_null_matches_explicit_tiny_matrix_and_is_monotone() -> None:
    pair_ids = [
        candidate_pair_id("A", "B"),
        candidate_pair_id("C", "D"),
        candidate_pair_id("E", "F"),
    ]
    group_scores = {
        pair_ids[0]: {"lexical_m7": 1.0, "grammar_annotations": 1.0},
        pair_ids[1]: {"lexical_m7": 0.7, "semantic_annotations": 0.8},
        pair_ids[2]: {"grammar_annotations": 0.6, "structural_annotations": 0.9},
    }
    strata = {pair_id: "one-stratum" for pair_id in pair_ids}
    iterations = CONFIG.calibration.fixture_iterations
    rows = stratified_ensemble_null_calibration(
        group_scores,
        strata,
        config=CONFIG,
        iterations=iterations,
        seed=CONFIG.calibration.seeds["stratified_permutation"],
        calibration_scope="full",
    )
    explicit = _explicit_final_null(group_scores, strata, iterations=iterations)
    observed = {
        pair_id: math.fsum(
            CONFIG.ensemble.group_weights[group] * group_scores[pair_id].get(group, 0.0)
            for group in CONFIG.ensemble.group_weights
        )
        for pair_id in pair_ids
    }
    for row in rows:
        pooled = [value for values in explicit.values() for value in values]
        expected_exceedances = sum(value >= observed[row.candidate_pair_id] for value in pooled)
        assert row.null_exceedance_count == expected_exceedances
        assert row.effective_null_cell_count == len(pooled)
        assert row.empirical_p_value == pytest.approx(
            (expected_exceedances + 1) / (len(pooled) + 1)
        )
        per_iteration_false_counts = [
            sum(
                explicit[pair_id][iteration] >= observed[row.candidate_pair_id]
                for pair_id in pair_ids
            )
            for iteration in range(iterations)
        ]
        assert row.null_discovery_count_sum == sum(per_iteration_false_counts)
        assert row.mean_null_discovery_count == pytest.approx(
            (sum(per_iteration_false_counts) + 1) / (iterations + 1)
        )
        assert row.mean_null_discovery_count > 0.0
    ordered = sorted(rows, key=lambda row: row.observed_score, reverse=True)
    assert [row.empirical_fdr for row in ordered] == sorted(row.empirical_fdr for row in ordered)


def test_tiny_null_stratum_reports_insufficient_bh_resolution() -> None:
    strict = CONFIG.model_copy(
        update={
            "calibration": CONFIG.calibration.model_copy(
                update={"production_iterations": CONFIG.calibration.fixture_iterations}
            )
        }
    )
    pair_ids = [candidate_pair_id("A", "B"), candidate_pair_id("C", "D")]
    rows = stratified_ensemble_null_calibration(
        {
            pair_id: {"lexical_m7": score}
            for pair_id, score in zip(pair_ids, (0.9, 0.2), strict=True)
        },
        {pair_id: "tiny" for pair_id in pair_ids},
        config=strict,
        iterations=strict.calibration.fixture_iterations,
        seed=strict.calibration.seeds["stratified_permutation"],
        calibration_scope="full",
    )

    assert all(row.stratum_size == 2 for row in rows)
    assert all(row.effective_null_cell_count == 40 for row in rows)
    assert all(not row.stratum_sufficient_for_bh for row in rows)


def test_vectorized_production_hook_handles_5k_pairs_by_100_iterations() -> None:
    benchmark_config = CONFIG.model_copy(
        update={"calibration": CONFIG.calibration.model_copy(update={"production_iterations": 100})}
    )
    pair_ids = [f"pair-{index:05d}" for index in range(5_000)]
    group_scores = {
        pair_id: {
            "lexical_m7": (index % 101) / 100,
            "semantic_annotations": ((index * 17) % 101) / 100,
            "grammar_annotations": ((index * 29) % 101) / 100,
        }
        for index, pair_id in enumerate(pair_ids)
    }
    rows = stratified_ensemble_null_calibration(
        group_scores,
        {pair_id: "bounded-production-benchmark" for pair_id in pair_ids},
        config=benchmark_config,
        iterations=benchmark_config.calibration.production_iterations,
        seed=benchmark_config.calibration.seeds["stratified_permutation"],
        calibration_scope="full",
    )

    assert len(rows) == 5_000
    assert all(row.iterations == 100 for row in rows)
    assert all(row.effective_null_cell_count == 500_000 for row in rows)
    assert all(row.stratum_sufficient_for_bh for row in rows)
    assert all(math.isfinite(row.empirical_p_value) for row in rows)
