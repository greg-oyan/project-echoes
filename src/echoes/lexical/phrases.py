"""Deterministic phrase extraction and transparent association statistics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

Feature = str


@dataclass(frozen=True, slots=True)
class PhraseOccurrence:
    """One ordered phrase occurrence with zero-based source positions."""

    features: tuple[Feature, ...]
    positions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PMIResult:
    """Generalized n-gram PMI with minimum-count and upper-cap controls."""

    value: float
    raw_value: float | None
    joint_count: int
    marginal_counts: tuple[int, ...]
    total_count: int
    minimum_count: int
    cap: float | None
    log_base: float
    eligible: bool
    capped: bool


@dataclass(frozen=True, slots=True)
class LogLikelihoodResult:
    """Dunning-style two-by-two log-likelihood association evidence."""

    statistic: float
    signed_statistic: float
    observed_cells: tuple[int, int, int, int]
    expected_cells: tuple[float, float, float, float]
    expected_joint: float


def _validated_features(features: Sequence[Feature]) -> tuple[Feature, ...]:
    values = tuple(features)
    if any(not value for value in values):
        raise ValueError("feature sequences cannot contain empty values")
    return values


def contiguous_ngrams(features: Sequence[Feature], n: int) -> tuple[PhraseOccurrence, ...]:
    """Return every contiguous n-gram in source order."""

    sequence = _validated_features(features)
    if n < 1:
        raise ValueError("n must be positive")
    return tuple(
        PhraseOccurrence(
            features=sequence[start : start + n],
            positions=tuple(range(start, start + n)),
        )
        for start in range(len(sequence) - n + 1)
    )


def skip_grams(
    features: Sequence[Feature],
    n: int,
    *,
    max_gap: int,
    include_contiguous: bool = False,
) -> tuple[PhraseOccurrence, ...]:
    """Return ordered skip-grams with at most ``max_gap`` skipped tokens per step.

    Contiguous n-grams are excluded by default because they are represented by
    their own feature family.  Output order is the lexicographic order of the
    source-position tuples.
    """

    sequence = _validated_features(features)
    if n < 2:
        raise ValueError("skip-gram n must be at least two")
    if max_gap < 0:
        raise ValueError("max_gap cannot be negative")
    position_tuples: list[tuple[int, ...]] = []

    def extend(prefix: tuple[int, ...]) -> None:
        if len(prefix) == n:
            is_contiguous = all(right == left + 1 for left, right in pairwise(prefix))
            if include_contiguous or not is_contiguous:
                position_tuples.append(prefix)
            return
        start = prefix[-1] + 1 if prefix else 0
        stop = min(len(sequence), prefix[-1] + max_gap + 2) if prefix else len(sequence)
        remaining_after_choice = n - len(prefix) - 1
        for position in range(start, stop):
            if len(sequence) - position - 1 < remaining_after_choice:
                break
            extend((*prefix, position))

    extend(())
    return tuple(
        PhraseOccurrence(
            features=tuple(sequence[position] for position in positions),
            positions=positions,
        )
        for positions in position_tuples
    )


def pointwise_mutual_information(
    joint_count: int,
    marginal_counts: Sequence[int],
    total_count: int,
    *,
    minimum_count: int = 2,
    cap: float | None = None,
    log_base: float = 2.0,
) -> PMIResult:
    """Calculate generalized PMI for an n-gram.

    For ``m`` marginal events the formula is
    ``log(joint * total**(m-1) / product(marginals), base)``.  Counts below the
    registered minimum receive zero weight, preventing unbounded one-off PMI.
    """

    marginals = tuple(marginal_counts)
    if len(marginals) < 2:
        raise ValueError("PMI requires at least two marginal counts")
    if joint_count < 0 or total_count < 1 or minimum_count < 1:
        raise ValueError("PMI counts and minimum_count are out of range")
    if any(count < joint_count or count > total_count for count in marginals):
        raise ValueError("each marginal must contain the joint and fit the corpus total")
    if not math.isfinite(log_base) or log_base <= 0.0 or log_base == 1.0:
        raise ValueError("log_base must be finite, positive, and not one")
    if cap is not None and (not math.isfinite(cap) or cap <= 0.0):
        raise ValueError("PMI cap must be finite and positive")
    if joint_count < minimum_count:
        return PMIResult(
            value=0.0,
            raw_value=None,
            joint_count=joint_count,
            marginal_counts=marginals,
            total_count=total_count,
            minimum_count=minimum_count,
            cap=cap,
            log_base=log_base,
            eligible=False,
            capped=False,
        )
    log_ratio = math.log(joint_count)
    log_ratio += (len(marginals) - 1) * math.log(total_count)
    log_ratio -= math.fsum(math.log(count) for count in marginals)
    raw_value = log_ratio / math.log(log_base)
    value = min(raw_value, cap) if cap is not None else raw_value
    return PMIResult(
        value=value,
        raw_value=raw_value,
        joint_count=joint_count,
        marginal_counts=marginals,
        total_count=total_count,
        minimum_count=minimum_count,
        cap=cap,
        log_base=log_base,
        eligible=True,
        capped=cap is not None and raw_value > cap,
    )


def _deviance_term(observed: int, expected: float) -> float:
    return observed * math.log(observed / expected) if observed else 0.0


def log_likelihood_ratio(
    cell_11: int,
    cell_12: int,
    cell_21: int,
    cell_22: int,
) -> LogLikelihoodResult:
    """Calculate a two-by-two independence likelihood-ratio statistic (G²)."""

    observed = (cell_11, cell_12, cell_21, cell_22)
    if any(cell < 0 for cell in observed):
        raise ValueError("contingency cells cannot be negative")
    total = sum(observed)
    if total == 0:
        raise ValueError("contingency table cannot be empty")
    row_1 = cell_11 + cell_12
    row_2 = cell_21 + cell_22
    column_1 = cell_11 + cell_21
    column_2 = cell_12 + cell_22
    expected = (
        row_1 * column_1 / total,
        row_1 * column_2 / total,
        row_2 * column_1 / total,
        row_2 * column_2 / total,
    )
    for observed_cell, expected_cell in zip(observed, expected, strict=True):
        if observed_cell and expected_cell == 0.0:
            raise ValueError("positive observed cells require positive expected counts")
    statistic = 2.0 * math.fsum(
        _deviance_term(observed_cell, expected_cell)
        for observed_cell, expected_cell in zip(observed, expected, strict=True)
    )
    expected_joint = expected[0]
    sign = 1.0 if cell_11 >= expected_joint else -1.0
    return LogLikelihoodResult(
        statistic=max(statistic, 0.0),
        signed_statistic=sign * max(statistic, 0.0),
        observed_cells=observed,
        expected_cells=expected,
        expected_joint=expected_joint,
    )


def bigram_log_likelihood(
    joint_count: int,
    first_count: int,
    second_count: int,
    total_count: int,
) -> LogLikelihoodResult:
    """Construct and score the standard bigram two-by-two contingency table."""

    if joint_count < 0 or first_count < 0 or second_count < 0 or total_count < 1:
        raise ValueError("bigram counts are out of range")
    if joint_count > min(first_count, second_count):
        raise ValueError("joint_count cannot exceed either marginal")
    neither_count = total_count - first_count - second_count + joint_count
    if neither_count < 0 or first_count > total_count or second_count > total_count:
        raise ValueError("bigram marginals are inconsistent with total_count")
    return log_likelihood_ratio(
        joint_count,
        first_count - joint_count,
        second_count - joint_count,
        neither_count,
    )
