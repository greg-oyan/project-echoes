"""Transparent statistical controls for the lexical baseline.

The hypergeometric calculation is a simple equal-probability independence
baseline, not a probability of literary dependence.  Conditioned empirical
null models remain the primary calibration because vocabulary, books, genres,
formulae, and speakers are dependent.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HypergeometricResult:
    """Inputs and upper-tail result for a distinct-feature overlap baseline."""

    universe_size: int
    feature_count_a: int
    feature_count_b: int
    observed_overlap: int
    expected_overlap: float
    upper_tail_p_value: float


@dataclass(frozen=True, slots=True)
class BootstrapDifferenceResult:
    """Paired query-bootstrap difference and retained replicate estimates."""

    observed_difference: float
    interval_low: float
    interval_high: float
    confidence_level: float
    iterations: int
    seed: int
    query_count: int
    replicate_differences: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class NullThresholdCalibration:
    """Observed/null candidate-count calibration at one frozen threshold."""

    threshold: float
    observed_count: int
    null_mean_count: float
    null_interval_low: float
    null_interval_high: float
    enrichment: float | None
    empirical_upper_tail_probability: float
    raw_empirical_fdr: float | None
    presentation_empirical_fdr: float | None
    replicate_count: int
    null_counts: tuple[int, ...]


def _log_combination(total: int, selected: int) -> float:
    if selected < 0 or selected > total:
        return -math.inf
    return math.lgamma(total + 1) - math.lgamma(selected + 1) - math.lgamma(total - selected + 1)


def hypergeometric_upper_tail(
    universe_size: int,
    feature_count_a: int,
    feature_count_b: int,
    observed_overlap: int,
) -> HypergeometricResult:
    """Return ``P(X >= observed_overlap)`` under equal-probability sampling."""

    if universe_size < 1:
        raise ValueError("universe_size must be positive")
    if not 0 <= feature_count_a <= universe_size:
        raise ValueError("feature_count_a must fit the universe")
    if not 0 <= feature_count_b <= universe_size:
        raise ValueError("feature_count_b must fit the universe")
    minimum_overlap = max(0, feature_count_b - (universe_size - feature_count_a))
    maximum_overlap = min(feature_count_a, feature_count_b)
    if not minimum_overlap <= observed_overlap <= maximum_overlap:
        raise ValueError("observed_overlap is impossible for the supplied set sizes")
    denominator = _log_combination(universe_size, feature_count_b)
    log_probabilities = [
        _log_combination(feature_count_a, overlap)
        + _log_combination(universe_size - feature_count_a, feature_count_b - overlap)
        - denominator
        for overlap in range(observed_overlap, maximum_overlap + 1)
    ]
    maximum_log = max(log_probabilities)
    tail = math.exp(maximum_log) * math.fsum(
        math.exp(value - maximum_log) for value in log_probabilities
    )
    return HypergeometricResult(
        universe_size=universe_size,
        feature_count_a=feature_count_a,
        feature_count_b=feature_count_b,
        observed_overlap=observed_overlap,
        expected_overlap=feature_count_a * feature_count_b / universe_size,
        upper_tail_p_value=min(max(tail, 0.0), 1.0),
    )


def benjamini_hochberg(p_values: Sequence[float]) -> tuple[float, ...]:
    """Return BH q-values in input order with stable handling of tied p-values."""

    values = tuple(float(value) for value in p_values)
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("p-values must be finite and between zero and one")
    if not values:
        return ()
    ordered_indices = sorted(range(len(values)), key=lambda index: (values[index], index))
    adjusted = [0.0] * len(values)
    running_minimum = 1.0
    for zero_based_rank in range(len(values) - 1, -1, -1):
        index = ordered_indices[zero_based_rank]
        rank = zero_based_rank + 1
        candidate = values[index] * len(values) / rank
        running_minimum = min(running_minimum, candidate, 1.0)
        adjusted[index] = running_minimum
    return tuple(adjusted)


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantiles require at least one value")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("quantile probability must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] + fraction * (ordered[upper_index] - ordered[lower_index])


def paired_bootstrap_difference(
    method_scores: Sequence[float],
    baseline_scores: Sequence[float],
    *,
    iterations: int,
    seed: int,
    confidence_level: float = 0.95,
) -> BootstrapDifferenceResult:
    """Bootstrap the mean paired per-query metric difference."""

    method = tuple(float(value) for value in method_scores)
    baseline = tuple(float(value) for value in baseline_scores)
    if not method or len(method) != len(baseline):
        raise ValueError("paired bootstrap inputs must be nonempty and equally sized")
    if any(not math.isfinite(value) for value in (*method, *baseline)):
        raise ValueError("bootstrap scores must be finite")
    if iterations < 1:
        raise ValueError("bootstrap iterations must be positive")
    if seed < 0:
        raise ValueError("bootstrap seed cannot be negative")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be strictly between zero and one")
    differences = tuple(
        method_value - baseline_value
        for method_value, baseline_value in zip(method, baseline, strict=True)
    )
    random_source = random.Random(seed)
    sample_size = len(differences)
    replicates = tuple(
        math.fsum(differences[random_source.randrange(sample_size)] for _ in range(sample_size))
        / sample_size
        for _ in range(iterations)
    )
    alpha = 1.0 - confidence_level
    return BootstrapDifferenceResult(
        observed_difference=math.fsum(differences) / sample_size,
        interval_low=_quantile(replicates, alpha / 2.0),
        interval_high=_quantile(replicates, 1.0 - alpha / 2.0),
        confidence_level=confidence_level,
        iterations=iterations,
        seed=seed,
        query_count=sample_size,
        replicate_differences=replicates,
    )


def calibrate_null_counts(
    threshold: float,
    observed_count: int,
    null_counts: Sequence[int],
) -> NullThresholdCalibration:
    """Calibrate one observed count against retained null replicate counts."""

    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite")
    counts = tuple(null_counts)
    if observed_count < 0 or not counts or any(count < 0 for count in counts):
        raise ValueError("observed and null counts must be nonnegative, with null replicates")
    null_mean = math.fsum(counts) / len(counts)
    if null_mean > 0.0:
        enrichment: float | None = observed_count / null_mean
    elif observed_count > 0:
        enrichment = math.inf
    else:
        enrichment = None
    raw_fdr = null_mean / observed_count if observed_count else None
    empirical_tail = (1 + sum(count >= observed_count for count in counts)) / (len(counts) + 1)
    return NullThresholdCalibration(
        threshold=threshold,
        observed_count=observed_count,
        null_mean_count=null_mean,
        null_interval_low=_quantile(counts, 0.025),
        null_interval_high=_quantile(counts, 0.975),
        enrichment=enrichment,
        empirical_upper_tail_probability=empirical_tail,
        raw_empirical_fdr=raw_fdr,
        presentation_empirical_fdr=min(raw_fdr, 1.0) if raw_fdr is not None else None,
        replicate_count=len(counts),
        null_counts=counts,
    )


def calibrate_null_thresholds(
    observed_scores: Sequence[float],
    null_score_replicates: Sequence[Sequence[float]],
    thresholds: Sequence[float],
) -> tuple[NullThresholdCalibration, ...]:
    """Count scores at frozen inclusive thresholds and calibrate each count."""

    observed = tuple(float(score) for score in observed_scores)
    replicates = tuple(
        tuple(float(score) for score in replicate) for replicate in null_score_replicates
    )
    threshold_values = tuple(float(threshold) for threshold in thresholds)
    if not replicates:
        raise ValueError("at least one null replicate is required")
    if len(threshold_values) != len(set(threshold_values)):
        raise ValueError("thresholds must be unique")
    if any(
        not math.isfinite(value)
        for value in (
            *observed,
            *threshold_values,
            *(score for replicate in replicates for score in replicate),
        )
    ):
        raise ValueError("scores and thresholds must be finite")
    return tuple(
        calibrate_null_counts(
            threshold,
            sum(score >= threshold for score in observed),
            tuple(sum(score >= threshold for score in replicate) for replicate in replicates),
        )
        for threshold in threshold_values
    )
