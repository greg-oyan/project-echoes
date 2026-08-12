"""Stratified representation-disagreement and unexpected-neighbor diagnostics."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.final_discovery.config import DetectorRegistration
from echoes.final_discovery.features import canonical_json
from echoes.final_discovery.models import EvidenceFamily, PassageRecord, RawEvidence


class AnomalyError(ValueError):
    """Raised when anomaly inputs cannot be stratified safely."""


class PairFamilyScores(BaseModel):
    """One retained pair's already normalized non-anomaly family scores."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_pair_id: str = Field(min_length=1)
    passage_a_id: str = Field(min_length=1)
    passage_b_id: str = Field(min_length=1)
    family_scores: dict[EvidenceFamily, float] = Field(min_length=2)
    formulaic_control: bool = False

    @model_validator(mode="after")
    def scores_and_pair_are_valid(self) -> PairFamilyScores:
        if self.passage_a_id >= self.passage_b_id:
            raise ValueError("anomaly pair IDs must use canonical ordering")
        if "anomaly" in self.family_scores:
            raise ValueError("anomaly inputs cannot recursively contain anomaly scores")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in self.family_scores.values()
        ):
            raise ValueError("family scores must be finite probabilities")
        return self


def _length_bucket(left: int, right: int) -> str:
    ratio = max(left, right) / min(left, right)
    if ratio <= 1.25:
        return "matched"
    if ratio <= 2.0:
        return "moderate_mismatch"
    return "large_mismatch"


def _stratum(left: PassageRecord, right: PassageRecord) -> str:
    corpus_pair = "_".join(sorted((left.corpus, right.corpus)))
    book_pair = "_".join(sorted((left.book, right.book)))
    genre_pair = "_".join(sorted((left.genre, right.genre)))
    return (
        f"{corpus_pair}|{book_pair}|{genre_pair}|"
        f"{_length_bucket(left.token_count, right.token_count)}"
    )


def _disagreement(scores: Mapping[EvidenceFamily, float]) -> float:
    values = tuple(scores.values())
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _median_absolute_deviation(values: Sequence[float]) -> tuple[float, float]:
    median = statistics.median(values)
    deviation = statistics.median(abs(value - median) for value in values)
    return median, deviation


def _robust_upper_probability(value: float, reference: Sequence[float]) -> float:
    median, deviation = _median_absolute_deviation(reference)
    if deviation == 0.0:
        below = sum(item < value for item in reference)
        tied = sum(item == value for item in reference)
        return (below + 0.5 * tied) / len(reference)
    robust_z = (value - median) / (1.4826 * deviation)
    return 0.5 * (1.0 + math.erf(robust_z / math.sqrt(2.0)))


def anomaly_evidence(
    observations: Sequence[PairFamilyScores],
    passages: Mapping[str, PassageRecord],
    *,
    registrations: Mapping[str, DetectorRegistration],
    source_artifact_id: str,
    source_artifact_sha256: str,
) -> tuple[RawEvidence, ...]:
    """Calibrate disagreements only against length/corpus/genre-matched pairs."""

    detector_id = "stratified_representation_anomaly"
    try:
        registration = registrations[detector_id]
    except KeyError as exc:
        raise AnomalyError(f"unregistered anomaly detector: {detector_id}") from exc
    if registration.family != "anomaly" or registration.counts_for_independence:
        raise AnomalyError("anomaly is a diagnostic family and cannot count as independent proof")
    grouped: dict[str, list[float]] = defaultdict(list)
    details: dict[str, tuple[str, float]] = {}
    for observation in observations:
        try:
            left = passages[observation.passage_a_id]
            right = passages[observation.passage_b_id]
        except KeyError as exc:
            raise AnomalyError(f"missing passage for anomaly pair: {exc}") from exc
        stratum = _stratum(left, right)
        disagreement = _disagreement(observation.family_scores)
        grouped[stratum].append(disagreement)
        details[observation.candidate_pair_id] = stratum, disagreement
    results: list[RawEvidence] = []
    for observation in observations:
        left = passages[observation.passage_a_id]
        right = passages[observation.passage_b_id]
        stratum, disagreement = details[observation.candidate_pair_id]
        reference = grouped[stratum]
        calibrated = _robust_upper_probability(disagreement, reference)
        lexical = observation.family_scores.get("lexical")
        semantic = observation.family_scores.get("semantic")
        lexical_semantic_gap = (
            abs(lexical - semantic) if lexical is not None and semantic is not None else None
        )
        unexpected_context = {
            "different_book": left.book != right.book,
            "different_genre": left.genre != right.genre,
            "cross_corpus": left.corpus != right.corpus,
        }
        formulaic_control = (
            observation.formulaic_control or left.formulaic_language or right.formulaic_language
        )
        score = calibrated * (0.75 if formulaic_control else 1.0)
        results.append(
            RawEvidence(
                candidate_pair_id=observation.candidate_pair_id,
                passage_a_id=observation.passage_a_id,
                passage_b_id=observation.passage_b_id,
                detector_id=registration.detector_id,
                family="anomaly",
                independence_group=registration.independence_group,
                raw_score=score,
                contains_english_derived_evidence=False,
                original_language_evidence_remains=True,
                counts_for_independence=False,
                trace_json=canonical_json(
                    {
                        "representation": "stratified_family_score_disagreement",
                        "stratum": stratum,
                        "stratum_pair_count": len(reference),
                        "family_scores": observation.family_scores,
                        "score_standard_deviation": disagreement,
                        "lexical_semantic_absolute_gap": lexical_semantic_gap,
                        "unexpected_neighbor_context": unexpected_context,
                        "formulaic_downweight_applied": formulaic_control,
                        "diagnostic_not_independent_proof": True,
                    }
                ),
                source_artifact_id=source_artifact_id,
                source_artifact_sha256=source_artifact_sha256,
            )
        )
    return tuple(results)
