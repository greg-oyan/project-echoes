"""Deterministic stratified permutation controls for the final ensemble."""

from __future__ import annotations

import json
import math
import random
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.final_discovery.config import (
    FinalDiscoveryConfig,
    final_discovery_config_sha256,
)
from echoes.final_discovery.models import RawEvidence


class NullControlError(ValueError):
    """Raised when a null-control population is incomplete or unstratified."""


_M7_REQUIRED_SOURCE_NULL_FAMILIES = (
    "within_book_reassignment",
    "frequency_preserving_synthetic",
)


class DetectorNullCalibrationRow(BaseModel):
    """One production detector's aggregate null result for one candidate pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_pair_id: str = Field(min_length=1)
    detector_id: str = Field(min_length=1)
    stratum: str = Field(min_length=1)
    observed_score: float
    null_exceedance_count: int = Field(ge=0)
    empirical_p_value: float = Field(ge=0.0, le=1.0)
    iterations: int = Field(ge=1)
    null_family: str = Field(min_length=1)
    seed: int = Field(ge=0)
    mechanism: str = Field(min_length=1)

    @model_validator(mode="after")
    def finite_sample_probability_matches_count(self) -> DetectorNullCalibrationRow:
        expected = (self.null_exceedance_count + 1) / (self.iterations + 1)
        if not math.isclose(self.empirical_p_value, expected, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError("detector empirical p-value does not match its exceedance count")
        return self


class EnsembleNullCalibrationRow(BaseModel):
    """Streaming final-null statistics at one observed candidate threshold."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_pair_id: str = Field(min_length=1)
    calibration_scope: Literal["full", "remove_all_english"]
    stratum: str = Field(min_length=1)
    stratum_size: int = Field(ge=1)
    observed_score: float = Field(ge=0.0, le=1.0)
    null_exceedance_count: int = Field(ge=0)
    effective_null_cell_count: int = Field(ge=1)
    empirical_p_value: float = Field(ge=0.0, le=1.0)
    null_discovery_count_sum: int = Field(ge=0)
    mean_null_discovery_count: float = Field(gt=0.0)
    observed_discovery_count: int = Field(ge=1)
    raw_empirical_fdr: float = Field(gt=0.0, le=1.0)
    empirical_fdr: float = Field(ge=0.0, le=1.0)
    minimum_attainable_p_value: float = Field(gt=0.0, le=1.0)
    minimum_effective_null_draws: int = Field(ge=1)
    stratum_sufficient_for_bh: bool
    hypothesis_count: int = Field(ge=1)
    iterations: int = Field(ge=1)
    seed: int = Field(ge=0)
    null_method: Literal["stratified_candidate_pair_permutation"]

    @model_validator(mode="after")
    def aggregate_statistics_reconcile(self) -> EnsembleNullCalibrationRow:
        if self.effective_null_cell_count != self.stratum_size * self.iterations:
            raise ValueError("effective null cells must equal stratum size times iterations")
        expected_p = (self.null_exceedance_count + 1) / (self.effective_null_cell_count + 1)
        expected_mean_null = (self.null_discovery_count_sum + 1) / (self.iterations + 1)
        expected_raw_fdr = min(self.mean_null_discovery_count / self.observed_discovery_count, 1.0)
        minimum_p = 1 / (self.effective_null_cell_count + 1)
        if not math.isclose(self.empirical_p_value, expected_p, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError("ensemble empirical p-value does not match its exceedance count")
        if not math.isclose(
            self.mean_null_discovery_count,
            expected_mean_null,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("mean null discoveries do not include the finite-sample correction")
        if not math.isclose(
            self.raw_empirical_fdr,
            expected_raw_fdr,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("raw ensemble FDR does not match its null/observed counts")
        if self.empirical_fdr + 1e-15 < self.raw_empirical_fdr:
            raise ValueError("monotone empirical FDR cannot improve on raw empirical FDR")
        if not math.isclose(
            self.minimum_attainable_p_value,
            minimum_p,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("minimum attainable p-value does not match effective null cells")
        expected_sufficiency = self.effective_null_cell_count >= self.minimum_effective_null_draws
        if self.stratum_sufficient_for_bh != expected_sufficiency:
            raise ValueError("null-stratum BH resolution flag is inconsistent")
        return self


class EnsembleNullThresholdSummary(BaseModel):
    """Bounded exact null-count reporting at one frozen ensemble threshold."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calibration_scope: Literal["full", "remove_all_english"]
    score_threshold: float = Field(ge=0.0, le=1.0)
    observed_discovery_count: int = Field(ge=0)
    null_discovery_counts: tuple[int, ...] = Field(min_length=1)
    mean_null_discovery_count: float = Field(gt=0.0)
    empirical_interval_2_5_percentile: float = Field(ge=0.0)
    empirical_interval_97_5_percentile: float = Field(ge=0.0)
    observed_to_null_enrichment: float | None = Field(default=None, ge=0.0)
    empirical_upper_tail_probability: float = Field(gt=0.0, le=1.0)
    estimated_empirical_fdr: float | None = Field(default=None, gt=0.0, le=1.0)
    hypothesis_count: int = Field(ge=1)
    iterations: int = Field(ge=1)
    mean_and_fdr_estimator: Literal["finite_sample_corrected_(sum+1)/(iterations+1)"]
    interval_method: Literal["linear_empirical_quantile_2.5_97.5"]
    tail_probability_method: Literal["finite_sample_corrected_upper_tail"]

    @model_validator(mode="after")
    def exact_statistics_reconcile(self) -> Self:
        if len(self.null_discovery_counts) != self.iterations:
            raise ValueError("threshold null-count vector must contain one count per iteration")
        if any(count < 0 or count > self.hypothesis_count for count in self.null_discovery_counts):
            raise ValueError("threshold null counts must fit the retained hypothesis population")
        if self.observed_discovery_count > self.hypothesis_count:
            raise ValueError("threshold observed count exceeds the retained hypothesis population")
        expected_mean = (sum(self.null_discovery_counts) + 1) / (self.iterations + 1)
        expected_low = _linear_quantile(self.null_discovery_counts, 0.025)
        expected_high = _linear_quantile(self.null_discovery_counts, 0.975)
        expected_tail = (
            1 + sum(count >= self.observed_discovery_count for count in self.null_discovery_counts)
        ) / (self.iterations + 1)
        expected_enrichment = (
            self.observed_discovery_count / expected_mean if self.observed_discovery_count else None
        )
        expected_fdr = (
            min(expected_mean / self.observed_discovery_count, 1.0)
            if self.observed_discovery_count
            else None
        )
        comparisons = (
            (self.mean_null_discovery_count, expected_mean, "mean null count"),
            (
                self.empirical_interval_2_5_percentile,
                expected_low,
                "2.5% empirical interval",
            ),
            (
                self.empirical_interval_97_5_percentile,
                expected_high,
                "97.5% empirical interval",
            ),
            (
                self.empirical_upper_tail_probability,
                expected_tail,
                "empirical upper-tail probability",
            ),
        )
        for observed, expected, label in comparisons:
            if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-15):
                raise ValueError(f"threshold {label} does not match its null-count vector")
        if (self.observed_to_null_enrichment is None) != (expected_enrichment is None):
            raise ValueError("threshold enrichment availability is inconsistent")
        if expected_enrichment is not None and not math.isclose(
            self.observed_to_null_enrichment or 0.0,
            expected_enrichment,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("threshold enrichment does not match its null-count vector")
        if (self.estimated_empirical_fdr is None) != (expected_fdr is None):
            raise ValueError("threshold empirical-FDR availability is inconsistent")
        if expected_fdr is not None and not math.isclose(
            self.estimated_empirical_fdr or 0.0,
            expected_fdr,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("threshold empirical FDR does not match its null-count vector")
        if self.empirical_interval_2_5_percentile > self.empirical_interval_97_5_percentile:
            raise ValueError("threshold empirical interval is reversed")
        return self


class EnsembleNullThresholdReport(BaseModel):
    """Authenticated reporting-only threshold summaries for both final-null scopes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    format_id: Literal["echoes-final-ensemble-null-threshold-report-v1"] = (
        "echoes-final-ensemble-null-threshold-report-v1"
    )
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    threshold_source: Literal["ensemble.minimum_tier_a_ensemble_score"]
    reporting_thresholds: tuple[float, ...] = Field(min_length=1)
    hypothesis_count: int = Field(ge=1)
    iterations: int = Field(ge=1)
    seed: int = Field(ge=0)
    null_method: Literal["stratified_candidate_pair_permutation"]
    summaries: tuple[EnsembleNullThresholdSummary, ...] = Field(min_length=2)
    pair_by_iteration_matrices_persisted: Literal[False]
    threshold_count_vectors_persisted: Literal[True]

    @model_validator(mode="after")
    def scopes_and_thresholds_are_complete(self) -> Self:
        if tuple(sorted(set(self.reporting_thresholds))) != self.reporting_thresholds:
            raise ValueError("reporting thresholds must be finite, unique, and sorted")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in self.reporting_thresholds
        ):
            raise ValueError("reporting thresholds must be finite scores within [0, 1]")
        expected_keys = tuple(
            (scope, threshold)
            for scope in ("full", "remove_all_english")
            for threshold in self.reporting_thresholds
        )
        actual_keys = tuple(
            (summary.calibration_scope, summary.score_threshold) for summary in self.summaries
        )
        if actual_keys != expected_keys:
            raise ValueError("threshold report must cover both scopes in canonical order")
        for summary in self.summaries:
            if (
                summary.hypothesis_count != self.hypothesis_count
                or summary.iterations != self.iterations
            ):
                raise ValueError("threshold summary population differs from its report")
        return self


def _linear_quantile(values: Sequence[int], probability: float) -> float:
    """Return the deterministic linear empirical quantile used by Output J."""

    if not values:
        raise NullControlError("threshold quantiles require at least one null count")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return float(ordered[lower_index])
    fraction = position - lower_index
    return float(ordered[lower_index] + fraction * (ordered[upper_index] - ordered[lower_index]))


def build_ensemble_null_threshold_summary(
    *,
    scope: Literal["full", "remove_all_english"],
    threshold: float,
    observed_count: int,
    null_counts: Sequence[int],
    hypothesis_count: int,
) -> EnsembleNullThresholdSummary:
    """Calculate exact reporting fields from one retained null-count vector."""

    counts = tuple(int(count) for count in null_counts)
    iterations = len(counts)
    if iterations < 1:
        raise NullControlError("threshold reporting requires at least one null iteration")
    corrected_mean = (sum(counts) + 1) / (iterations + 1)
    return EnsembleNullThresholdSummary(
        calibration_scope=scope,
        score_threshold=threshold,
        observed_discovery_count=observed_count,
        null_discovery_counts=counts,
        mean_null_discovery_count=corrected_mean,
        empirical_interval_2_5_percentile=_linear_quantile(counts, 0.025),
        empirical_interval_97_5_percentile=_linear_quantile(counts, 0.975),
        observed_to_null_enrichment=(observed_count / corrected_mean if observed_count else None),
        empirical_upper_tail_probability=(1 + sum(count >= observed_count for count in counts))
        / (iterations + 1),
        estimated_empirical_fdr=(
            min(corrected_mean / observed_count, 1.0) if observed_count else None
        ),
        hypothesis_count=hypothesis_count,
        iterations=iterations,
        mean_and_fdr_estimator="finite_sample_corrected_(sum+1)/(iterations+1)",
        interval_method="linear_empirical_quantile_2.5_97.5",
        tail_probability_method="finite_sample_corrected_upper_tail",
    )


def ensemble_reporting_thresholds(config: FinalDiscoveryConfig) -> tuple[float, ...]:
    """Return the already-preregistered final ensemble reporting threshold."""

    return (config.ensemble.minimum_tier_a_ensemble_score,)


def build_ensemble_null_threshold_report(
    summaries: Sequence[EnsembleNullThresholdSummary],
    *,
    config: FinalDiscoveryConfig,
    hypothesis_count: int,
    iterations: int,
    seed: int,
) -> EnsembleNullThresholdReport:
    """Bind exact bounded threshold counts to frozen final-null provenance."""

    return EnsembleNullThresholdReport(
        config_sha256=final_discovery_config_sha256(config),
        threshold_source="ensemble.minimum_tier_a_ensemble_score",
        reporting_thresholds=ensemble_reporting_thresholds(config),
        hypothesis_count=hypothesis_count,
        iterations=iterations,
        seed=seed,
        null_method=config.ensemble.final_null_method,
        summaries=tuple(summaries),
        pair_by_iteration_matrices_persisted=False,
        threshold_count_vectors_persisted=True,
    )


@dataclass(frozen=True, slots=True)
class DetectorCalibration:
    """Stratified detector references, aggregate null rows, and exact provenance."""

    reference_scores_by_detector_and_stratum: dict[str, dict[str, tuple[float, ...]]]
    rows_by_detector: dict[str, dict[str, DetectorNullCalibrationRow]]
    provenance_by_detector: dict[str, dict[str, object]]

    def as_json_object(self) -> dict[str, object]:
        """Return compact pools/provenance; pair results belong in JSONL."""

        return {
            "reference_scores_by_detector_and_stratum": (
                self.reference_scores_by_detector_and_stratum
            ),
            "provenance_by_detector": self.provenance_by_detector,
        }

    def rows(self) -> tuple[DetectorNullCalibrationRow, ...]:
        return tuple(
            self.rows_by_detector[detector_id][pair_id]
            for detector_id in sorted(self.rows_by_detector)
            for pair_id in sorted(self.rows_by_detector[detector_id])
        )


def _validate_m7_source_nulls(raw: RawEvidence, config: FinalDiscoveryConfig) -> None:
    if raw.detector_id != "m7_lexical_rrf" or not config.calibration.require_both_m7_null_families:
        return
    try:
        trace = json.loads(raw.trace_json)
    except json.JSONDecodeError as exc:
        raise NullControlError("M7 evidence has an invalid JSON trace") from exc
    if not isinstance(trace, dict) or trace.get("m7_both_null_families_present") is not True:
        raise NullControlError(
            "production M7 evidence must authenticate both canonical M7 null families"
        )


def _registered_detector_rows(
    raw_evidence: Sequence[RawEvidence], config: FinalDiscoveryConfig
) -> dict[str, dict[str, RawEvidence]]:
    registrations = {item.detector_id: item for item in config.detectors}
    rows: dict[str, dict[str, RawEvidence]] = defaultdict(dict)
    for raw in raw_evidence:
        try:
            registration = registrations[raw.detector_id]
        except KeyError as exc:
            raise NullControlError(
                f"unregistered detector in production calibration: {exc}"
            ) from exc
        if (
            raw.family != registration.family
            or raw.independence_group != registration.independence_group
        ):
            raise NullControlError(
                f"raw evidence lineage disagrees with registration: {raw.detector_id}"
            )
        if raw.candidate_pair_id in rows[raw.detector_id]:
            raise NullControlError(
                "production detector calibration requires one score per detector/pair: "
                f"{raw.detector_id}/{raw.candidate_pair_id}"
            )
        _validate_m7_source_nulls(raw, config)
        rows[raw.detector_id][raw.candidate_pair_id] = raw
    return dict(rows)


def _vectorized_detector_exceedances(
    observed: np.ndarray,
    *,
    null_family: str,
    iterations: int,
    random_source: np.random.Generator,
) -> np.ndarray:
    """Count detector-null exceedances in bounded compiled batches."""

    bytes_per_iteration = max(len(observed) * 16, 1)
    batch_size = max(1, min(iterations, 64, (64 * 1024**2) // bytes_per_iteration))
    exceedances = np.zeros(len(observed), dtype=np.int64)
    completed = 0
    while completed < iterations:
        current_batch = min(batch_size, iterations - completed)
        if null_family == "stratified_score_bootstrap":
            donor_indices = random_source.integers(
                0, len(observed), size=(current_batch, len(observed)), dtype=np.int64
            )
            reassigned = observed[donor_indices]
        else:
            keys = random_source.random((current_batch, len(observed)), dtype=np.float32)
            reassigned = observed[np.argsort(keys, axis=1)]
        exceedances += np.count_nonzero(reassigned >= observed[None, :], axis=0)
        completed += current_batch
    return exceedances


def production_detector_calibration(
    raw_evidence: Sequence[RawEvidence],
    strata_by_pair: Mapping[str, str],
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
) -> DetectorCalibration:
    """Build registered, seeded detector nulls for the production campaign.

    The reassignment and permutation families retain each detector's observed
    score marginal exactly inside every registered confounder stratum. The
    score-bootstrap family draws observed-score donors from that same stratum
    with the registered family seed, making its empirical resampling mechanism
    explicit without claiming to generate synthetic feature sequences.
    Canonical M7 evidence is accepted only when its trace authenticates the two
    upstream M7 null families; those upstream nulls are never reconstructed.
    """

    if iterations != config.calibration.production_iterations:
        raise NullControlError(
            "production detector calibration must use the preregistered production iterations"
        )
    if not raw_evidence:
        raise NullControlError("production detector calibration requires evidence")
    pair_ids = {raw.candidate_pair_id for raw in raw_evidence}
    if pair_ids != set(strata_by_pair):
        raise NullControlError(
            "production detector strata must cover the exact raw-evidence pair population"
        )
    if any(not value for value in strata_by_pair.values()):
        raise NullControlError("production detector calibration contains an empty stratum")

    registrations = {item.detector_id: item for item in config.detectors}
    rows_by_detector = _registered_detector_rows(raw_evidence, config)
    references: dict[str, dict[str, tuple[float, ...]]] = {}
    calibration_rows: dict[str, dict[str, DetectorNullCalibrationRow]] = {}
    provenance: dict[str, dict[str, object]] = {}
    mechanisms = {
        "within_book_reassignment": "within_stratum_reassignment_without_replacement",
        "stratified_score_bootstrap": "within_stratum_score_resampling_with_replacement",
        "stratified_permutation": "within_stratum_permutation_without_replacement",
    }
    for detector_id in sorted(rows_by_detector):
        registration = registrations[detector_id]
        try:
            seed = config.calibration.seeds[registration.null_family]
        except KeyError as exc:
            raise NullControlError(
                f"registered null family has no registered seed: {registration.null_family}"
            ) from exc
        detector_rows = rows_by_detector[detector_id]
        members_by_stratum: dict[str, list[str]] = defaultdict(list)
        for pair_id in sorted(detector_rows):
            members_by_stratum[strata_by_pair[pair_id]].append(pair_id)
        detector_references: dict[str, tuple[float, ...]] = {}
        exceedances = {pair_id: 0 for pair_id in detector_rows}
        random_source = np.random.default_rng(seed)
        for stratum in sorted(members_by_stratum):
            members = sorted(members_by_stratum[stratum])
            observed_array = np.asarray(
                [float(detector_rows[pair_id].raw_score) for pair_id in members],
                dtype=np.float64,
            )
            if not np.isfinite(observed_array).all():
                raise NullControlError(f"detector {detector_id} has a non-finite score")
            observed = tuple(float(value) for value in observed_array)
            detector_references[stratum] = observed
            stratum_exceedances = _vectorized_detector_exceedances(
                observed_array,
                null_family=registration.null_family,
                iterations=iterations,
                random_source=random_source,
            )
            for pair_id, count in zip(members, stratum_exceedances, strict=True):
                exceedances[pair_id] = int(count)
        references[detector_id] = detector_references
        source_null_families: tuple[str, ...] = ()
        source_null_validation = "not_applicable"
        if detector_id == "m7_lexical_rrf":
            source_null_families = _M7_REQUIRED_SOURCE_NULL_FAMILIES
            source_null_validation = "authenticated_m7_both_null_families_present_trace"
        provenance[detector_id] = {
            "detector_id": detector_id,
            "registered_null_family": registration.null_family,
            "registered_seed": seed,
            "iterations": iterations,
            "mechanism": mechanisms[registration.null_family],
            "mechanism_scope": "detector_score_marginal_within_registered_pair_strata",
            "synthetic_feature_sequences_generated": False,
            "stratum_count": len(members_by_stratum),
            "source_null_families": source_null_families,
            "source_null_validation": source_null_validation,
        }
        calibration_rows[detector_id] = {
            pair_id: DetectorNullCalibrationRow(
                candidate_pair_id=pair_id,
                detector_id=detector_id,
                stratum=strata_by_pair[pair_id],
                observed_score=detector_rows[pair_id].raw_score,
                null_exceedance_count=exceedances[pair_id],
                empirical_p_value=(exceedances[pair_id] + 1) / (iterations + 1),
                iterations=iterations,
                null_family=registration.null_family,
                seed=seed,
                mechanism=mechanisms[registration.null_family],
            )
            for pair_id in sorted(detector_rows)
        }
    return DetectorCalibration(
        reference_scores_by_detector_and_stratum=references,
        rows_by_detector=calibration_rows,
        provenance_by_detector=provenance,
    )


def _vectorized_final_null_counts(
    group_scores_by_pair: Mapping[str, Mapping[str, float]],
    pair_ids: Sequence[str],
    registered_groups: Sequence[str],
    strata: Mapping[str, Sequence[str]],
    observed_scores: Mapping[str, float],
    unique_thresholds: Sequence[float],
    reporting_thresholds: Sequence[float],
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
    seed: int,
) -> tuple[
    dict[str, dict[float, int]],
    dict[float, int],
    dict[float, tuple[int, ...]],
]:
    """Accumulate production permutations in bounded NumPy batches."""

    pair_index = {pair_id: index for index, pair_id in enumerate(pair_ids)}
    weights = np.asarray(
        [config.ensemble.group_weights[group] for group in registered_groups],
        dtype=np.float64,
    )
    threshold_array = np.asarray(unique_thresholds, dtype=np.float64)
    reporting_threshold_array = np.asarray(reporting_thresholds, dtype=np.float64)
    stratum_indices = {
        stratum: np.asarray([pair_index[pair_id] for pair_id in members], dtype=np.int64)
        for stratum, members in strata.items()
    }
    stratum_threshold_arrays = {
        stratum: np.asarray(
            sorted({observed_scores[pair_id] for pair_id in members}), dtype=np.float64
        )
        for stratum, members in strata.items()
    }
    pooled_arrays = {
        stratum: np.zeros(len(thresholds), dtype=np.int64)
        for stratum, thresholds in stratum_threshold_arrays.items()
    }
    global_counts = np.zeros(len(threshold_array), dtype=np.int64)
    reporting_counts = np.empty(
        (len(reporting_threshold_array), iterations),
        dtype=np.int64,
    )
    group_count = max(len(registered_groups), 1)
    bytes_per_iteration = max(len(pair_ids) * group_count * 16, 1)
    batch_size = max(
        1,
        min(iterations, 32, (96 * 1024**2) // bytes_per_iteration),
    )
    random_source = np.random.default_rng(seed)
    completed = 0
    while completed < iterations:
        current_batch = min(batch_size, iterations - completed)
        batch_scores = np.empty((current_batch, len(pair_ids)), dtype=np.float64)
        for stratum in sorted(strata):
            members = tuple(strata[stratum])
            indices = stratum_indices[stratum]
            values = np.asarray(
                [
                    [
                        group_scores_by_pair[pair_id].get(
                            group, config.ensemble.missing_group_score
                        )
                        for pair_id in members
                    ]
                    for group in registered_groups
                ],
                dtype=np.float64,
            )
            random_keys = random_source.random(
                (current_batch, len(registered_groups), len(members)), dtype=np.float32
            )
            order = np.argsort(random_keys, axis=2)
            permuted = np.take_along_axis(values[None, :, :], order, axis=2)
            scores = np.einsum("bgs,g->bs", permuted, weights, optimize=True)
            batch_scores[:, indices] = scores
            flattened = np.sort(scores, axis=None)
            thresholds = stratum_threshold_arrays[stratum]
            pooled_arrays[stratum] += flattened.size - np.searchsorted(
                flattened, thresholds, side="left"
            )
        batch_scores.sort(axis=1)
        for batch_offset, iteration_scores in enumerate(batch_scores):
            global_counts += len(pair_ids) - np.searchsorted(
                iteration_scores, threshold_array, side="left"
            )
            reporting_counts[:, completed + batch_offset] = len(pair_ids) - np.searchsorted(
                iteration_scores,
                reporting_threshold_array,
                side="left",
            )
        completed += current_batch
    return (
        {
            stratum: {
                float(threshold): int(count)
                for threshold, count in zip(
                    stratum_threshold_arrays[stratum], pooled_arrays[stratum], strict=True
                )
            }
            for stratum in sorted(strata)
        },
        {
            float(threshold): int(count)
            for threshold, count in zip(threshold_array, global_counts, strict=True)
        },
        {
            float(threshold): tuple(int(count) for count in reporting_counts[index])
            for index, threshold in enumerate(reporting_threshold_array)
        },
    )


def _stratified_ensemble_null_calibration(
    group_scores_by_pair: Mapping[str, Mapping[str, float]],
    strata_by_pair: Mapping[str, str],
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
    seed: int,
    calibration_scope: Literal["full", "remove_all_english"],
    reporting_thresholds: Sequence[float],
) -> tuple[
    tuple[EnsembleNullCalibrationRow, ...],
    tuple[EnsembleNullThresholdSummary, ...],
]:
    """Break cross-family pair association within registered confounder strata.

    Each independence-group marginal is retained exactly within a stratum, but
    the group values are independently reassigned across candidate pairs. This
    tests whether the observed multi-family conjunction exceeds what the same
    book/genre/length-conditioned detector marginals produce by chance. Null
    matrices are never retained: pair exceedances and threshold discovery counts
    are accumulated one permutation at a time in O(pair-count) memory.
    """

    pair_ids = sorted(group_scores_by_pair)
    if not pair_ids:
        raise NullControlError("final ensemble null requires at least one candidate pair")
    if set(pair_ids) != set(strata_by_pair):
        raise NullControlError("null strata must cover the exact candidate-pair population")
    if iterations < 1 or seed < 0:
        raise NullControlError("null iterations must be positive and seed nonnegative")
    if iterations not in {
        config.calibration.fixture_iterations,
        config.calibration.production_iterations,
    }:
        raise NullControlError("final null iterations must match a preregistered execution mode")
    if seed != config.calibration.seeds.get("stratified_permutation"):
        raise NullControlError("final ensemble null must use the preregistered permutation seed")
    reporting_threshold_values = tuple(float(value) for value in reporting_thresholds)
    if len(reporting_threshold_values) != len(set(reporting_threshold_values)) or any(
        not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in reporting_threshold_values
    ):
        raise NullControlError("final-null reporting thresholds must be unique scores in [0, 1]")
    registered_groups = tuple(config.ensemble.group_weights)
    for pair_id in pair_ids:
        unexpected = set(group_scores_by_pair[pair_id]) - set(registered_groups)
        if unexpected:
            raise NullControlError(f"unregistered null score groups for {pair_id}: {unexpected}")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in group_scores_by_pair[pair_id].values()
        ):
            raise NullControlError(f"non-finite or unbounded group score for {pair_id}")
        if not strata_by_pair[pair_id]:
            raise NullControlError(f"empty null stratum for {pair_id}")
    strata: dict[str, list[str]] = defaultdict(list)
    for pair_id in pair_ids:
        strata[strata_by_pair[pair_id]].append(pair_id)
    observed_scores = {
        pair_id: math.fsum(
            config.ensemble.group_weights[group]
            * group_scores_by_pair[pair_id].get(group, config.ensemble.missing_group_score)
            for group in registered_groups
        )
        for pair_id in pair_ids
    }
    observed_sorted = sorted(observed_scores.values())
    unique_thresholds = sorted(set(observed_scores.values()))
    observed_discoveries = {
        threshold: len(pair_ids) - bisect_left(observed_sorted, threshold)
        for threshold in unique_thresholds
    }
    stratum_thresholds = {
        stratum: sorted({observed_scores[pair_id] for pair_id in members})
        for stratum, members in strata.items()
    }
    pooled_exceedances = {
        stratum: {threshold: 0 for threshold in thresholds}
        for stratum, thresholds in stratum_thresholds.items()
    }
    null_discovery_sums = {threshold: 0 for threshold in unique_thresholds}
    reporting_null_counts: dict[float, tuple[int, ...]] = {
        threshold: () for threshold in reporting_threshold_values
    }
    if iterations == config.calibration.production_iterations:
        (
            pooled_exceedances,
            null_discovery_sums,
            reporting_null_counts,
        ) = _vectorized_final_null_counts(
            group_scores_by_pair,
            pair_ids,
            registered_groups,
            strata,
            observed_scores,
            unique_thresholds,
            reporting_threshold_values,
            config=config,
            iterations=iterations,
            seed=seed,
        )
    else:
        random_source = random.Random(seed)
        reporting_count_lists: dict[float, list[int]] = {
            threshold: [] for threshold in reporting_threshold_values
        }
        for _ in range(iterations):
            reassigned: dict[str, dict[str, float]] = {pair_id: {} for pair_id in pair_ids}
            for stratum in sorted(strata):
                members = sorted(strata[stratum])
                for group in registered_groups:
                    values = [
                        group_scores_by_pair[pair_id].get(
                            group, config.ensemble.missing_group_score
                        )
                        for pair_id in members
                    ]
                    random_source.shuffle(values)
                    for pair_id, value in zip(members, values, strict=True):
                        reassigned[pair_id][group] = value
            iteration_scores = {
                pair_id: math.fsum(
                    config.ensemble.group_weights[group] * reassigned[pair_id][group]
                    for group in registered_groups
                )
                for pair_id in pair_ids
            }
            for stratum, members in strata.items():
                stratum_null_sorted = sorted(iteration_scores[pair_id] for pair_id in members)
                for threshold in stratum_thresholds[stratum]:
                    pooled_exceedances[stratum][threshold] += len(members) - bisect_left(
                        stratum_null_sorted, threshold
                    )
            null_sorted = sorted(iteration_scores.values())
            for threshold in unique_thresholds:
                null_discovery_sums[threshold] += len(pair_ids) - bisect_left(
                    null_sorted, threshold
                )
            for threshold in reporting_threshold_values:
                reporting_count_lists[threshold].append(
                    len(pair_ids) - bisect_left(null_sorted, threshold)
                )
        reporting_null_counts = {
            threshold: tuple(counts) for threshold, counts in reporting_count_lists.items()
        }
    corrected_mean_null = {
        threshold: (null_discovery_sums[threshold] + 1) / (iterations + 1)
        for threshold in unique_thresholds
    }
    raw_fdr = {
        threshold: min(corrected_mean_null[threshold] / observed_discoveries[threshold], 1.0)
        for threshold in unique_thresholds
    }
    monotone_fdr: dict[float, float] = {}
    running_fdr = 0.0
    for threshold in sorted(unique_thresholds, reverse=True):
        running_fdr = max(running_fdr, raw_fdr[threshold])
        monotone_fdr[threshold] = running_fdr
    rows: list[EnsembleNullCalibrationRow] = []
    required_effective_draws = (
        config.calibration.minimum_effective_null_draws
        if iterations == config.calibration.production_iterations
        else iterations
    )
    for pair_id in pair_ids:
        threshold = observed_scores[pair_id]
        stratum = strata_by_pair[pair_id]
        stratum_size = len(strata[stratum])
        effective_cells = stratum_size * iterations
        exceedance_count = pooled_exceedances[stratum][threshold]
        observed_count = observed_discoveries[threshold]
        minimum_p = 1 / (effective_cells + 1)
        rows.append(
            EnsembleNullCalibrationRow(
                candidate_pair_id=pair_id,
                calibration_scope=calibration_scope,
                stratum=stratum,
                stratum_size=stratum_size,
                observed_score=threshold,
                null_exceedance_count=exceedance_count,
                effective_null_cell_count=effective_cells,
                empirical_p_value=(exceedance_count + 1) / (effective_cells + 1),
                null_discovery_count_sum=null_discovery_sums[threshold],
                mean_null_discovery_count=corrected_mean_null[threshold],
                observed_discovery_count=observed_count,
                raw_empirical_fdr=raw_fdr[threshold],
                empirical_fdr=monotone_fdr[threshold],
                minimum_attainable_p_value=minimum_p,
                minimum_effective_null_draws=required_effective_draws,
                stratum_sufficient_for_bh=(effective_cells >= required_effective_draws),
                hypothesis_count=len(pair_ids),
                iterations=iterations,
                seed=seed,
                null_method=config.ensemble.final_null_method,
            )
        )
    reporting_summaries = tuple(
        build_ensemble_null_threshold_summary(
            scope=calibration_scope,
            threshold=threshold,
            observed_count=len(pair_ids) - bisect_left(observed_sorted, threshold),
            null_counts=reporting_null_counts[threshold],
            hypothesis_count=len(pair_ids),
        )
        for threshold in reporting_threshold_values
    )
    return tuple(rows), reporting_summaries


def stratified_ensemble_null_calibration(
    group_scores_by_pair: Mapping[str, Mapping[str, float]],
    strata_by_pair: Mapping[str, str],
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
    seed: int,
    calibration_scope: Literal["full", "remove_all_english"],
) -> tuple[EnsembleNullCalibrationRow, ...]:
    """Return candidate-level calibration without retaining reporting vectors."""

    rows, _summaries = _stratified_ensemble_null_calibration(
        group_scores_by_pair,
        strata_by_pair,
        config=config,
        iterations=iterations,
        seed=seed,
        calibration_scope=calibration_scope,
        reporting_thresholds=(),
    )
    return rows


def stratified_ensemble_null_calibration_with_reporting(
    group_scores_by_pair: Mapping[str, Mapping[str, float]],
    strata_by_pair: Mapping[str, str],
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
    seed: int,
    calibration_scope: Literal["full", "remove_all_english"],
) -> tuple[tuple[EnsembleNullCalibrationRow, ...], tuple[EnsembleNullThresholdSummary, ...]]:
    """Return candidate calibration plus bounded frozen-threshold null counts."""

    return _stratified_ensemble_null_calibration(
        group_scores_by_pair,
        strata_by_pair,
        config=config,
        iterations=iterations,
        seed=seed,
        calibration_scope=calibration_scope,
        reporting_thresholds=ensemble_reporting_thresholds(config),
    )


def detector_reference_and_null_scores(
    raw_scores_by_detector: Mapping[str, Sequence[float]],
    *,
    iterations: int,
    seed: int,
    execution_mode: Literal["fixture"],
) -> tuple[dict[str, tuple[float, ...]], dict[str, tuple[float, ...]]]:
    """Create detector calibration distributions for fixture execution only.

    This bootstrap-like marginal fallback is intentionally impossible to call as
    a production API. Production must use :func:`production_detector_calibration`.
    """

    if execution_mode != "fixture":
        raise NullControlError("marginal detector fallback is fixture-only")
    if iterations < 1 or seed < 0:
        raise NullControlError("detector null iterations must be positive and seeded")
    random_source = random.Random(seed)
    references: dict[str, tuple[float, ...]] = {}
    nulls: dict[str, tuple[float, ...]] = {}
    for detector_id in sorted(raw_scores_by_detector):
        observed = tuple(float(value) for value in raw_scores_by_detector[detector_id])
        if not observed or any(not math.isfinite(value) for value in observed):
            raise NullControlError(f"detector {detector_id} has no finite observed scores")
        generated: list[float] = []
        for _ in range(iterations):
            generated.append(observed[random_source.randrange(len(observed))])
        references[detector_id] = observed
        nulls[detector_id] = tuple(generated)
    return references, nulls
