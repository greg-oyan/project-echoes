"""Governed repeated-null execution and threshold calibration.

Calibration in Milestone 7 is scoped to a frozen deterministic sample of
candidate-union pairs.  It is deliberately not an all-pairs experiment and
must never be reported as global all-pairs false-discovery control.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Final

from echoes.lexical.nulls import (
    NullFamily,
    NullReplicate,
    NullSourceContext,
    NullValidationResult,
    PassageFeatures,
    frequency_preserving_synthetic,
    validate_frequency_preserving_synthetic,
    validate_within_book_reassignment,
    within_book_reassignment,
)
from echoes.lexical.statistics import NullThresholdCalibration, calibrate_null_counts

CALIBRATION_PAIR_SAMPLE_SIZE: Final = 20_000
MINIMUM_REPLICATES_PER_FAMILY: Final = 100
CANDIDATE_UNION_SAMPLE_SCOPE: Final = "deterministic_candidate_union_sample"
NO_GLOBAL_ALL_PAIRS_CLAIM: Final = (
    "Calibration applies only to the preregistered deterministic 20,000-pair "
    "candidate-union sample; it is not global all-pairs FDR control."
)
REQUIRED_NULL_FAMILIES: Final[tuple[NullFamily, ...]] = (
    "within_book_reassignment",
    "frequency_preserving_synthetic",
)


class NullCalibrationContractError(ValueError):
    """A governed null-calibration invariant was not satisfied."""


@dataclass(frozen=True, slots=True, order=True)
class GovernedScoringStratum:
    """One preregistered corpus/representation/detector scoring experiment."""

    corpus_pair: str
    representation_id: str
    detector: str

    def __post_init__(self) -> None:
        if not all((self.corpus_pair, self.representation_id, self.detector)):
            raise NullCalibrationContractError("governed stratum fields cannot be empty")

    @property
    def key(self) -> str:
        """Return the stable, human-readable stratum key."""

        return "|".join((self.corpus_pair, self.representation_id, self.detector))


def _digest_strings(values: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class CandidateUnionSample:
    """The exact fixed-size candidate-union sample used by calibration."""

    pair_ids: tuple[str, ...]
    source_candidate_count: int
    seed: int
    logical_digest: str
    scope: str = CANDIDATE_UNION_SAMPLE_SCOPE
    global_all_pairs_claim_allowed: bool = False
    scope_note: str = NO_GLOBAL_ALL_PAIRS_CLAIM

    def __post_init__(self) -> None:
        if len(self.pair_ids) != CALIBRATION_PAIR_SAMPLE_SIZE:
            raise NullCalibrationContractError(
                f"candidate-union calibration sample must contain exactly "
                f"{CALIBRATION_PAIR_SAMPLE_SIZE} pairs"
            )
        if len(set(self.pair_ids)) != len(self.pair_ids) or any(
            not value for value in self.pair_ids
        ):
            raise NullCalibrationContractError(
                "candidate-union sample IDs must be nonempty and unique"
            )
        if self.pair_ids != tuple(sorted(self.pair_ids)):
            raise NullCalibrationContractError(
                "candidate-union sample IDs must be canonically sorted"
            )
        if self.source_candidate_count < len(self.pair_ids):
            raise NullCalibrationContractError(
                "source candidate count cannot be smaller than sample"
            )
        if self.seed < 0:
            raise NullCalibrationContractError("candidate sample seed cannot be negative")
        if self.logical_digest != _digest_strings(self.pair_ids):
            raise NullCalibrationContractError(
                "candidate-union sample digest does not match its IDs"
            )
        if self.scope != CANDIDATE_UNION_SAMPLE_SCOPE:
            raise NullCalibrationContractError(
                "candidate sample has an unregistered selection scope"
            )
        if self.global_all_pairs_claim_allowed:
            raise NullCalibrationContractError(
                "candidate-union calibration cannot make a global claim"
            )
        if self.scope_note != NO_GLOBAL_ALL_PAIRS_CLAIM:
            raise NullCalibrationContractError(
                "candidate sample must retain the no-global-claim caveat"
            )


def sample_candidate_union_pairs(
    candidate_pair_ids: Sequence[str],
    *,
    seed: int,
    sample_size: int = CALIBRATION_PAIR_SAMPLE_SIZE,
) -> CandidateUnionSample:
    """Select the fixed 20,000-pair sample independently of input ordering."""

    if sample_size != CALIBRATION_PAIR_SAMPLE_SIZE:
        raise NullCalibrationContractError(
            "the frozen Milestone 7 calibration sample size is exactly 20,000"
        )
    if seed < 0:
        raise NullCalibrationContractError("candidate sample seed cannot be negative")
    pair_ids = tuple(candidate_pair_ids)
    if any(not pair_id for pair_id in pair_ids):
        raise NullCalibrationContractError("candidate pair IDs cannot be empty")
    if len(pair_ids) != len(set(pair_ids)):
        raise NullCalibrationContractError("candidate-union pair IDs must be unique")
    if len(pair_ids) < sample_size:
        raise NullCalibrationContractError(
            f"candidate union contains {len(pair_ids)} pairs; exactly {sample_size} are required"
        )

    return _sample_unique_candidate_union_pairs(pair_ids, seed=seed, sample_size=sample_size)


def _sample_unique_candidate_union_pairs(
    candidate_pair_ids: Iterable[str],
    *,
    seed: int,
    sample_size: int = CALIBRATION_PAIR_SAMPLE_SIZE,
) -> CandidateUnionSample:
    """Boundedly sample IDs whose uniqueness is guaranteed by their mapping source."""

    if sample_size != CALIBRATION_PAIR_SAMPLE_SIZE:
        raise NullCalibrationContractError(
            "the frozen Milestone 7 calibration sample size is exactly 20,000"
        )
    if seed < 0:
        raise NullCalibrationContractError("candidate sample seed cannot be negative")
    source_candidate_count = 0

    def validated_ids() -> Iterable[str]:
        nonlocal source_candidate_count
        for pair_id in candidate_pair_ids:
            if not pair_id:
                raise NullCalibrationContractError("candidate pair IDs cannot be empty")
            source_candidate_count += 1
            yield pair_id

    def sampling_key(pair_id: str) -> tuple[bytes, str]:
        payload = f"{seed}\x1f{pair_id}".encode()
        return (hashlib.sha256(payload).digest(), pair_id)

    selected = tuple(sorted(heapq.nsmallest(sample_size, validated_ids(), key=sampling_key)))
    if source_candidate_count < sample_size:
        raise NullCalibrationContractError(
            f"candidate union contains {source_candidate_count} pairs; "
            f"exactly {sample_size} are required"
        )
    return CandidateUnionSample(
        pair_ids=selected,
        source_candidate_count=source_candidate_count,
        seed=seed,
        logical_digest=_digest_strings(selected),
    )


@dataclass(frozen=True, slots=True)
class NullReplicatePlanEntry:
    """One unique deterministic replicate requested by the frozen design."""

    stratum: GovernedScoringStratum
    family: NullFamily
    iteration: int
    seed: int

    def __post_init__(self) -> None:
        if self.family not in REQUIRED_NULL_FAMILIES:
            raise NullCalibrationContractError(f"unregistered null family: {self.family}")
        if self.iteration < 1:
            raise NullCalibrationContractError("null iteration numbers start at one")
        if self.seed < 1:
            raise NullCalibrationContractError("null replicate seeds must be positive")


def _derived_positive_seed(base_seed: int, *parts: str) -> int:
    payload = "\x1f".join((str(base_seed), *parts)).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)
    return seed or 1


def build_null_replicate_plan(
    strata: Sequence[GovernedScoringStratum],
    *,
    family_base_seeds: Mapping[NullFamily, int],
    iterations_per_family: int = MINIMUM_REPLICATES_PER_FAMILY,
) -> tuple[NullReplicatePlanEntry, ...]:
    """Build two complete, deterministic, globally unique seed series per stratum."""

    canonical_strata = tuple(sorted(strata))
    if not canonical_strata:
        raise NullCalibrationContractError("at least one governed scoring stratum is required")
    if len(canonical_strata) != len(set(canonical_strata)):
        raise NullCalibrationContractError("governed scoring strata must be unique")
    if iterations_per_family < MINIMUM_REPLICATES_PER_FAMILY:
        raise NullCalibrationContractError(
            f"each null family requires at least {MINIMUM_REPLICATES_PER_FAMILY} replicates"
        )
    if set(family_base_seeds) != set(REQUIRED_NULL_FAMILIES):
        raise NullCalibrationContractError(
            "both and only the two registered null families are required"
        )
    base_seeds = tuple(family_base_seeds[family] for family in REQUIRED_NULL_FAMILIES)
    if any(seed < 1 for seed in base_seeds) or len(set(base_seeds)) != len(base_seeds):
        raise NullCalibrationContractError("null family base seeds must be positive and distinct")

    plan = tuple(
        NullReplicatePlanEntry(
            stratum=stratum,
            family=family,
            iteration=iteration,
            seed=_derived_positive_seed(
                family_base_seeds[family],
                stratum.key,
                family,
                str(iteration),
            ),
        )
        for stratum in canonical_strata
        for family in REQUIRED_NULL_FAMILIES
        for iteration in range(1, iterations_per_family + 1)
    )
    seeds = tuple(entry.seed for entry in plan)
    if len(seeds) != len(set(seeds)):
        raise NullCalibrationContractError("derived null replicate seeds are not globally unique")
    return plan


def validate_null_replicate_conservation(
    source_passages: Sequence[PassageFeatures] | NullSourceContext,
    replicate: NullReplicate,
    *,
    retain_frequency_deviation_details: bool = True,
) -> NullValidationResult:
    """Dispatch the family-specific conservation audit and require it to pass."""

    if replicate.family == "within_book_reassignment":
        validation = validate_within_book_reassignment(source_passages, replicate)
    elif replicate.family == "frequency_preserving_synthetic":
        validation = validate_frequency_preserving_synthetic(
            source_passages,
            replicate,
            retain_frequency_deviation_details=retain_frequency_deviation_details,
        )
    else:  # pragma: no cover - NullReplicate's type contract prevents this branch.
        raise NullCalibrationContractError(f"unregistered null family: {replicate.family}")
    if not validation.is_valid:
        errors = ", ".join(validation.errors)
        raise NullCalibrationContractError(f"null conservation validation failed: {errors}")
    return validation


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise NullCalibrationContractError("score quantiles require at least one score")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _replicate_length_digest(replicate: NullReplicate) -> str:
    values = tuple(
        f"{passage.corpus}|{passage.representation}|{passage.source_passage_id}|"
        f"{len(passage.features)}"
        for passage in sorted(
            replicate.passages,
            key=lambda item: (item.corpus, item.representation, item.source_passage_id),
        )
    )
    return _digest_strings(values)


def _replicate_frequency_digest(replicate: NullReplicate) -> str:
    counts: Counter[tuple[str, str, str, str]] = Counter()
    for passage in replicate.passages:
        for feature in passage.features:
            counts[(passage.corpus, passage.representation, passage.book, feature)] += 1
    values = tuple("|".join((*key, str(count))) for key, count in sorted(counts.items()))
    return _digest_strings(values)


@dataclass(frozen=True, slots=True)
class NullReplicateThresholdSummary:
    """Retained score/count evidence for one fully validated null replicate."""

    plan: NullReplicatePlanEntry
    candidate_sample_digest: str
    candidate_sample_size: int
    mean_score: float
    score_quantiles: tuple[tuple[str, float], ...]
    threshold_counts: tuple[tuple[float, int], ...]
    passage_count: int
    token_count: int
    length_digest: str
    frequency_digest: str
    logical_output_hash: str
    validation: NullValidationResult
    selection_scope: str = CANDIDATE_UNION_SAMPLE_SCOPE
    global_all_pairs_claim_allowed: bool = False
    scope_note: str = NO_GLOBAL_ALL_PAIRS_CLAIM

    def __post_init__(self) -> None:
        if self.candidate_sample_size != CALIBRATION_PAIR_SAMPLE_SIZE:
            raise NullCalibrationContractError(
                "null summary does not use the fixed 20,000-pair sample"
            )
        if not self.validation.is_valid:
            raise NullCalibrationContractError("invalid null replicate cannot enter calibration")
        if self.validation.family != self.plan.family:
            raise NullCalibrationContractError("null validation family differs from its plan")
        if not math.isfinite(self.mean_score):
            raise NullCalibrationContractError("null mean score must be finite")
        thresholds = tuple(threshold for threshold, _ in self.threshold_counts)
        if thresholds != tuple(sorted(set(thresholds))):
            raise NullCalibrationContractError("summary thresholds must be strictly increasing")
        if any(
            count < 0 or count > self.candidate_sample_size for _, count in self.threshold_counts
        ):
            raise NullCalibrationContractError("null threshold counts are outside the sample")
        counts = tuple(count for _, count in self.threshold_counts)
        if any(left < right for left, right in pairwise(counts)):
            raise NullCalibrationContractError(
                "candidate counts cannot increase as score thresholds increase"
            )
        if self.passage_count < 0 or self.token_count < 0:
            raise NullCalibrationContractError("null passage and token counts cannot be negative")
        for digest in (
            self.candidate_sample_digest,
            self.length_digest,
            self.frequency_digest,
            self.logical_output_hash,
        ):
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise NullCalibrationContractError("null summary hashes must be lowercase SHA-256")
        if self.selection_scope != CANDIDATE_UNION_SAMPLE_SCOPE:
            raise NullCalibrationContractError("null summary has an unregistered selection scope")
        if self.global_all_pairs_claim_allowed or self.scope_note != NO_GLOBAL_ALL_PAIRS_CLAIM:
            raise NullCalibrationContractError(
                "null summary must preserve the scoped no-global claim"
            )


def summarize_null_replicate_scores(
    *,
    plan: NullReplicatePlanEntry,
    replicate: NullReplicate,
    validation: NullValidationResult,
    scores: Sequence[float],
    thresholds: Sequence[float],
    sample: CandidateUnionSample,
) -> NullReplicateThresholdSummary:
    """Reduce one scored replicate to deterministic retained calibration evidence."""

    if replicate.family != plan.family or replicate.seed != plan.seed:
        raise NullCalibrationContractError("generated null does not match its replicate plan entry")
    if not validation.is_valid or validation.family != replicate.family:
        raise NullCalibrationContractError(
            "generated null lacks valid family conservation evidence"
        )
    score_values = tuple(float(score) for score in scores)
    if len(score_values) != len(sample.pair_ids):
        raise NullCalibrationContractError("null scorer must return one score per sampled pair")
    threshold_values = tuple(float(threshold) for threshold in thresholds)
    if threshold_values != tuple(sorted(set(threshold_values))) or not threshold_values:
        raise NullCalibrationContractError(
            "calibration threshold grid must be nonempty and increasing"
        )
    if any(not math.isfinite(value) for value in (*score_values, *threshold_values)):
        raise NullCalibrationContractError("null scores and thresholds must be finite")
    threshold_counts = tuple(
        (threshold, sum(score >= threshold for score in score_values))
        for threshold in threshold_values
    )
    quantiles = tuple(
        (name, _quantile(score_values, probability))
        for name, probability in (("q025", 0.025), ("q50", 0.5), ("q975", 0.975))
    )
    length_digest = _replicate_length_digest(replicate)
    frequency_digest = _replicate_frequency_digest(replicate)
    logical_payload = {
        "candidate_sample_digest": sample.logical_digest,
        "family": plan.family,
        "frequency_digest": frequency_digest,
        "iteration": plan.iteration,
        "length_digest": length_digest,
        "mean_score": math.fsum(score_values) / len(score_values),
        "quantiles": quantiles,
        "seed": plan.seed,
        "stratum": plan.stratum.key,
        "threshold_counts": threshold_counts,
    }
    logical_hash = hashlib.sha256(
        json.dumps(
            logical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return NullReplicateThresholdSummary(
        plan=plan,
        candidate_sample_digest=sample.logical_digest,
        candidate_sample_size=len(sample.pair_ids),
        mean_score=math.fsum(score_values) / len(score_values),
        score_quantiles=quantiles,
        threshold_counts=threshold_counts,
        passage_count=len(replicate.passages),
        token_count=sum(len(passage.features) for passage in replicate.passages),
        length_digest=length_digest,
        frequency_digest=frequency_digest,
        logical_output_hash=logical_hash,
        validation=validation,
    )


NullScorer = Callable[
    [GovernedScoringStratum, NullReplicate, tuple[str, ...]],
    Sequence[float],
]


def execute_null_replicate_plan(
    source_passages: Sequence[PassageFeatures],
    *,
    plan: Sequence[NullReplicatePlanEntry],
    sample: CandidateUnionSample,
    thresholds: Sequence[float],
    scorer: NullScorer,
    minimum_book_token_count: int,
) -> tuple[NullReplicateThresholdSummary, ...]:
    """Generate, validate, score, and retain every planned null replicate."""

    entries = tuple(plan)
    if not entries:
        raise NullCalibrationContractError("null execution plan cannot be empty")
    if len({entry.stratum for entry in entries}) != 1:
        raise NullCalibrationContractError("one execution call must contain exactly one stratum")
    if minimum_book_token_count < 1:
        raise NullCalibrationContractError("synthetic book support threshold must be positive")
    summaries: list[NullReplicateThresholdSummary] = []
    for entry in entries:
        if entry.family == "within_book_reassignment":
            replicate = within_book_reassignment(source_passages, seed=entry.seed)
        else:
            replicate = frequency_preserving_synthetic(
                source_passages,
                seed=entry.seed,
                minimum_book_token_count=minimum_book_token_count,
            )
        validation = validate_null_replicate_conservation(source_passages, replicate)
        scores = scorer(entry.stratum, replicate, sample.pair_ids)
        summaries.append(
            summarize_null_replicate_scores(
                plan=entry,
                replicate=replicate,
                validation=validation,
                scores=scores,
                thresholds=thresholds,
                sample=sample,
            )
        )
    return tuple(summaries)


@dataclass(frozen=True, slots=True)
class FamilyThresholdCalibration:
    """Calibration at one threshold within one registered null family."""

    family: NullFamily
    calibration: NullThresholdCalibration


@dataclass(frozen=True, slots=True)
class CalibratedThreshold:
    """Pooled and family-specific evidence at one preregistered threshold."""

    threshold_id: str
    stratum: GovernedScoringStratum
    score_threshold: float
    observed_candidate_count: int
    pooled_calibration: NullThresholdCalibration
    family_calibrations: tuple[FamilyThresholdCalibration, ...]
    eligible_candidate_count: int
    candidate_sample_digest: str
    threshold_selection_scope: str
    frozen_before_test: bool
    global_all_pairs_claim_allowed: bool
    qualifies_empirical_fdr: bool
    selected: bool
    notes: str


@dataclass(frozen=True, slots=True)
class ThresholdGridCalibration:
    """Complete calibration grid and deterministic selection for one stratum."""

    stratum: GovernedScoringStratum
    thresholds: tuple[CalibratedThreshold, ...]
    selected_threshold: float | None
    maximum_empirical_fdr: float
    replicate_count_per_family: int
    candidate_sample_digest: str
    scope_note: str = NO_GLOBAL_ALL_PAIRS_CLAIM


def _validate_summary_coverage(
    *,
    stratum: GovernedScoringStratum,
    summaries: Sequence[NullReplicateThresholdSummary],
    sample: CandidateUnionSample,
    thresholds: tuple[float, ...],
    required_replicates_per_family: int,
) -> None:
    if required_replicates_per_family < MINIMUM_REPLICATES_PER_FAMILY:
        raise NullCalibrationContractError(
            "calibration requires at least 100 replicates per family"
        )
    if any(summary.plan.stratum != stratum for summary in summaries):
        raise NullCalibrationContractError("null summaries mix governed scoring strata")
    seeds = tuple(summary.plan.seed for summary in summaries)
    if len(seeds) != len(set(seeds)):
        raise NullCalibrationContractError("null summary seeds must be unique")
    expected_iterations = set(range(1, required_replicates_per_family + 1))
    for family in REQUIRED_NULL_FAMILIES:
        family_summaries = tuple(summary for summary in summaries if summary.plan.family == family)
        if len(family_summaries) != required_replicates_per_family:
            raise NullCalibrationContractError(
                f"{family} has {len(family_summaries)} summaries; "
                f"{required_replicates_per_family} are required"
            )
        if {summary.plan.iteration for summary in family_summaries} != expected_iterations:
            raise NullCalibrationContractError(f"{family} iteration coverage is incomplete")
    for summary in summaries:
        if (
            summary.candidate_sample_digest != sample.logical_digest
            or summary.candidate_sample_size != len(sample.pair_ids)
        ):
            raise NullCalibrationContractError("null summary candidate sample identity changed")
        if tuple(threshold for threshold, _ in summary.threshold_counts) != thresholds:
            raise NullCalibrationContractError("null summary threshold grid changed")


def calibrate_threshold_grid(
    *,
    stratum: GovernedScoringStratum,
    observed_scores: Sequence[float],
    summaries: Sequence[NullReplicateThresholdSummary],
    thresholds: Sequence[float],
    sample: CandidateUnionSample,
    maximum_empirical_fdr: float,
    required_replicates_per_family: int = MINIMUM_REPLICATES_PER_FAMILY,
) -> ThresholdGridCalibration:
    """Calibrate and select a frozen grid using both complete null families."""

    threshold_values = tuple(float(threshold) for threshold in thresholds)
    if not threshold_values or threshold_values != tuple(sorted(set(threshold_values))):
        raise NullCalibrationContractError(
            "threshold grid must be nonempty and strictly increasing"
        )
    scores = tuple(float(score) for score in observed_scores)
    if len(scores) != len(sample.pair_ids):
        raise NullCalibrationContractError("observed scorer must return one score per sampled pair")
    if any(not math.isfinite(value) for value in (*scores, *threshold_values)):
        raise NullCalibrationContractError("observed scores and thresholds must be finite")
    if not 0.0 < maximum_empirical_fdr <= 1.0:
        raise NullCalibrationContractError("maximum empirical FDR must be in (0, 1]")
    summary_values = tuple(summaries)
    _validate_summary_coverage(
        stratum=stratum,
        summaries=summary_values,
        sample=sample,
        thresholds=threshold_values,
        required_replicates_per_family=required_replicates_per_family,
    )

    rows: list[CalibratedThreshold] = []
    for threshold_index, threshold in enumerate(threshold_values):
        observed_count = sum(score >= threshold for score in scores)
        family_results: list[FamilyThresholdCalibration] = []
        pooled_counts: list[int] = []
        for family in REQUIRED_NULL_FAMILIES:
            counts = tuple(
                summary.threshold_counts[threshold_index][1]
                for summary in summary_values
                if summary.plan.family == family
            )
            pooled_counts.extend(counts)
            family_results.append(
                FamilyThresholdCalibration(
                    family=family,
                    calibration=calibrate_null_counts(threshold, observed_count, counts),
                )
            )
        pooled = calibrate_null_counts(threshold, observed_count, pooled_counts)
        qualifies = observed_count > 0 and all(
            result.calibration.raw_empirical_fdr is not None
            and result.calibration.raw_empirical_fdr <= maximum_empirical_fdr
            for result in family_results
        )
        threshold_payload = f"{stratum.key}\x1f{threshold:.17g}\x1f{sample.logical_digest}"
        rows.append(
            CalibratedThreshold(
                threshold_id=f"threshold_{hashlib.sha256(threshold_payload.encode()).hexdigest()}",
                stratum=stratum,
                score_threshold=threshold,
                observed_candidate_count=observed_count,
                pooled_calibration=pooled,
                family_calibrations=tuple(family_results),
                eligible_candidate_count=observed_count,
                candidate_sample_digest=sample.logical_digest,
                threshold_selection_scope=CANDIDATE_UNION_SAMPLE_SCOPE,
                frozen_before_test=True,
                global_all_pairs_claim_allowed=False,
                qualifies_empirical_fdr=qualifies,
                selected=False,
                notes=NO_GLOBAL_ALL_PAIRS_CLAIM,
            )
        )
    selected_threshold = next(
        (row.score_threshold for row in rows if row.qualifies_empirical_fdr),
        None,
    )
    selected_rows = tuple(
        replace(row, selected=row.score_threshold == selected_threshold) for row in rows
    )
    return ThresholdGridCalibration(
        stratum=stratum,
        thresholds=selected_rows,
        selected_threshold=selected_threshold,
        maximum_empirical_fdr=maximum_empirical_fdr,
        replicate_count_per_family=required_replicates_per_family,
        candidate_sample_digest=sample.logical_digest,
    )


def calibrate_governed_thresholds(
    *,
    observed_scores_by_stratum: Mapping[GovernedScoringStratum, Sequence[float]],
    summaries: Sequence[NullReplicateThresholdSummary],
    samples_by_stratum: Mapping[GovernedScoringStratum, CandidateUnionSample],
    thresholds_by_detector: Mapping[str, Sequence[float]],
    maximum_empirical_fdr: float,
    required_replicates_per_family: int = MINIMUM_REPLICATES_PER_FAMILY,
) -> tuple[ThresholdGridCalibration, ...]:
    """Require and calibrate every governed detector/composite scoring stratum."""

    strata = set(observed_scores_by_stratum)
    if not strata or set(samples_by_stratum) != strata:
        raise NullCalibrationContractError(
            "observed scores and samples must cover identical strata"
        )
    summary_strata = {summary.plan.stratum for summary in summaries}
    if summary_strata != strata:
        raise NullCalibrationContractError("null summaries do not cover every governed stratum")
    missing_detectors = {stratum.detector for stratum in strata}.difference(thresholds_by_detector)
    if missing_detectors:
        raise NullCalibrationContractError(
            "missing threshold grids for detectors: " + ", ".join(sorted(missing_detectors))
        )
    return tuple(
        calibrate_threshold_grid(
            stratum=stratum,
            observed_scores=observed_scores_by_stratum[stratum],
            summaries=tuple(summary for summary in summaries if summary.plan.stratum == stratum),
            thresholds=thresholds_by_detector[stratum.detector],
            sample=samples_by_stratum[stratum],
            maximum_empirical_fdr=maximum_empirical_fdr,
            required_replicates_per_family=required_replicates_per_family,
        )
        for stratum in sorted(strata)
    )
