"""Frozen transparent ensemble, empirical calibration, and disjoint tiering."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from echoes.final_discovery.config import FinalDiscoveryConfig
from echoes.final_discovery.features import (
    empirical_percentile,
    empirical_upper_tail,
    evidence_id,
)
from echoes.final_discovery.knownness import KnownnessIndex
from echoes.final_discovery.models import (
    EvidenceFamily,
    EvidenceRow,
    FinalCandidate,
    KnownnessStatus,
    OutputLabel,
    PassageRecord,
    QualityFlags,
    RawEvidence,
)
from echoes.final_discovery.nulls import DetectorCalibration, EnsembleNullCalibrationRow
from echoes.lexical.statistics import benjamini_hochberg


class EnsembleError(ValueError):
    """Raised when ensemble inputs cannot satisfy the frozen contract."""


@dataclass(frozen=True, slots=True)
class _Draft:
    pair_id: str
    passage_a: PassageRecord
    passage_b: PassageRecord
    evidence: tuple[EvidenceRow, ...]
    group_scores: dict[str, float]
    ensemble_score: float
    score_without_english: float
    empirical_p_value: float
    empirical_fdr: float
    null_stratum_sufficient_for_bh: bool
    english_ablation_empirical_p_value: float
    english_ablation_empirical_fdr: float
    english_ablation_null_available: bool
    english_ablation_null_stratum_sufficient_for_bh: bool
    knownness_status: KnownnessStatus
    known_relationship_ids: tuple[str, ...]
    quality: QualityFlags
    qualifying_groups: tuple[str, ...]
    original_groups: tuple[str, ...]
    original_families: tuple[EvidenceFamily, ...]
    contains_english: bool


def _normal_score(value: float, reference: Sequence[float]) -> float:
    mean = math.fsum(reference) / len(reference)
    variance = math.fsum((item - mean) ** 2 for item in reference) / len(reference)
    if variance == 0.0:
        return 0.5
    z_score = (value - mean) / math.sqrt(variance)
    return 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))


def calibrate_detector_evidence(
    raw_evidence: Sequence[RawEvidence],
    *,
    config: FinalDiscoveryConfig,
    reference_scores: Mapping[str, Sequence[float]] | None = None,
    null_scores: Mapping[str, Sequence[float]] | None = None,
    calibration: DetectorCalibration | None = None,
) -> tuple[EvidenceRow, ...]:
    """Apply each detector's registered normalization and empirical null."""

    if calibration is None and (reference_scores is None or null_scores is None):
        raise EnsembleError("detector calibration distributions are required")
    if calibration is not None and (reference_scores is not None or null_scores is not None):
        raise EnsembleError("supply either production calibration or fixture distributions")
    registrations = {item.detector_id: item for item in config.detectors}
    calibrated: list[EvidenceRow] = []
    for raw in raw_evidence:
        calibration_p_value: float | None = None
        try:
            registration = registrations[raw.detector_id]
            if calibration is None:
                assert reference_scores is not None and null_scores is not None
                reference = tuple(float(value) for value in reference_scores[raw.detector_id])
                null = tuple(float(value) for value in null_scores[raw.detector_id])
            else:
                provenance = calibration.provenance_by_detector[raw.detector_id]
                if provenance.get(
                    "registered_null_family"
                ) != registration.null_family or provenance.get(
                    "registered_seed"
                ) != config.calibration.seeds.get(registration.null_family):
                    raise EnsembleError(
                        f"production calibration provenance mismatch: {raw.detector_id}"
                    )
                calibration_row = calibration.rows_by_detector[raw.detector_id][
                    raw.candidate_pair_id
                ]
                if (
                    calibration_row.null_family != registration.null_family
                    or calibration_row.seed
                    != config.calibration.seeds.get(registration.null_family)
                    or not math.isclose(
                        calibration_row.observed_score,
                        raw.raw_score,
                        rel_tol=0.0,
                        abs_tol=1e-15,
                    )
                ):
                    raise EnsembleError(f"production calibration row mismatch: {raw.detector_id}")
                calibration_p_value = calibration_row.empirical_p_value
                reference = tuple(
                    float(value)
                    for value in calibration.reference_scores_by_detector_and_stratum[
                        raw.detector_id
                    ][calibration_row.stratum]
                )
                null = ()
        except KeyError as exc:
            raise EnsembleError(f"missing detector registration/calibration: {exc}") from exc
        if not reference or (calibration is None and not null):
            raise EnsembleError(
                f"detector {raw.detector_id} requires nonempty reference and null scores"
            )
        if (
            raw.family != registration.family
            or raw.independence_group != registration.independence_group
        ):
            raise EnsembleError(
                f"raw evidence lineage disagrees with registration: {raw.detector_id}"
            )
        if raw.counts_for_independence and not registration.counts_for_independence:
            raise EnsembleError(f"raw evidence escalates independence: {raw.detector_id}")
        if registration.normalization in {"empirical_percentile", "rank_percentile"}:
            normalized = empirical_percentile(raw.raw_score, reference)
        else:
            normalized = _normal_score(raw.raw_score, reference)
        ablated_normalized: float | None = None
        if raw.english_ablation_raw_score is not None:
            if registration.normalization in {"empirical_percentile", "rank_percentile"}:
                ablated_normalized = empirical_percentile(raw.english_ablation_raw_score, reference)
            else:
                ablated_normalized = _normal_score(raw.english_ablation_raw_score, reference)
        calibrated.append(
            EvidenceRow(
                evidence_id=evidence_id(
                    raw.candidate_pair_id, raw.detector_id, raw.source_artifact_sha256
                ),
                candidate_pair_id=raw.candidate_pair_id,
                passage_a_id=raw.passage_a_id,
                passage_b_id=raw.passage_b_id,
                detector_id=raw.detector_id,
                family=raw.family,
                independence_group=raw.independence_group,
                raw_score=raw.raw_score,
                normalized_score=normalized,
                normalization_method=registration.normalization,
                empirical_p_value=(
                    calibration_p_value
                    if calibration_p_value is not None
                    else empirical_upper_tail(raw.raw_score, null)
                ),
                null_method=registration.null_family,
                contains_english_derived_evidence=raw.contains_english_derived_evidence,
                english_ablation_normalized_score=ablated_normalized,
                original_language_evidence_remains=raw.original_language_evidence_remains,
                counts_for_independence=raw.counts_for_independence,
                trace_json=raw.trace_json,
                source_artifact_id=raw.source_artifact_id,
                source_artifact_sha256=raw.source_artifact_sha256,
                source_quality=raw.source_quality,
                source_knownness_status=raw.source_knownness_status,
                source_known_relationship_ids=raw.source_known_relationship_ids,
            )
        )
    ids = [row.evidence_id for row in calibrated]
    if len(ids) != len(set(ids)):
        raise EnsembleError("detector evidence IDs collide within the retained evidence set")
    return tuple(calibrated)


def _group_score(
    evidence: Sequence[EvidenceRow], *, remove_all_english: bool = False
) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in evidence:
        score = row.normalized_score
        if remove_all_english and row.contains_english_derived_evidence:
            if row.english_ablation_normalized_score is None:
                continue
            score = row.english_ablation_normalized_score
        values[row.independence_group] = max(values.get(row.independence_group, 0.0), score)
    return values


def ensemble_group_scores_by_pair(
    evidence: Sequence[EvidenceRow], *, remove_all_english: bool = False
) -> dict[str, dict[str, float]]:
    """Return deterministic group maxima for full or English-ablated evidence."""

    grouped: dict[str, list[EvidenceRow]] = defaultdict(list)
    for row in evidence:
        grouped[row.candidate_pair_id].append(row)
    return {
        pair_id: _group_score(rows, remove_all_english=remove_all_english)
        for pair_id, rows in sorted(grouped.items())
    }


def _ensemble_score(group_scores: Mapping[str, float], config: FinalDiscoveryConfig) -> float:
    return math.fsum(
        weight * group_scores.get(group, config.ensemble.missing_group_score)
        for group, weight in config.ensemble.group_weights.items()
    )


def _quality(
    left: PassageRecord, right: PassageRecord, evidence: Sequence[EvidenceRow]
) -> QualityFlags:
    source = tuple(row.source_quality for row in evidence if row.source_quality is not None)

    def source_flag(name: str) -> bool:
        return any(bool(getattr(flags, name)) for flags in source)

    return QualityFlags(
        disputed_passage=(
            left.disputed_passage or right.disputed_passage or source_flag("disputed_passage")
        ),
        reference_gap=left.reference_gap or right.reference_gap or source_flag("reference_gap"),
        ketiv_uncertainty=(
            left.ketiv_uncertainty or right.ketiv_uncertainty or source_flag("ketiv_uncertainty")
        ),
        formulaic_language=(
            left.formulaic_language or right.formulaic_language or source_flag("formulaic_language")
        ),
        overlapping_passages=source_flag("overlapping_passages"),
        unresolved_data_error=source_flag("unresolved_data_error"),
        invalid_trace=source_flag("invalid_trace"),
        local_context=source_flag("local_context"),
        exact_or_near_duplicate=source_flag("exact_or_near_duplicate"),
        same_reference_sensitivity=(
            source_flag("same_reference_sensitivity")
            or (
                left.reference == right.reference
                and (
                    left.passage_id != right.passage_id
                    or left.analysis_profile != right.analysis_profile
                    or left.analysis_reading != right.analysis_reading
                )
            )
        ),
    )


def _reconcile_knownness(
    left: PassageRecord,
    right: PassageRecord,
    evidence: Sequence[EvidenceRow],
    knownness: KnownnessIndex,
) -> tuple[KnownnessStatus, tuple[str, ...]]:
    indexed_status, indexed_ids = knownness.classify(left.passage_id, right.passage_id)
    source_statuses = {
        row.source_knownness_status
        for row in evidence
        if row.source_knownness_status not in {None, "unknown"}
    }
    relationship_ids = tuple(
        sorted(
            {
                *indexed_ids,
                *(
                    relationship_id
                    for row in evidence
                    for relationship_id in row.source_known_relationship_ids
                ),
            }
        )
    )
    statuses = set(source_statuses)
    if indexed_status != "unknown":
        statuses.add(indexed_status)
    if not statuses:
        return "unknown", ()
    if "known_both" in statuses or {
        "known_forward",
        "known_reverse",
    }.issubset(statuses):
        return "known_both", relationship_ids
    directional = statuses & {"known_forward", "known_reverse"}
    if directional == {"known_forward"}:
        return "known_forward", relationship_ids
    if directional == {"known_reverse"}:
        return "known_reverse", relationship_ids
    return "known_m7_snapshot", relationship_ids


def _validate_null_calibration(
    pair_ids: Sequence[str],
    calibration_by_pair: Mapping[str, EnsembleNullCalibrationRow],
    *,
    scope: Literal["full", "remove_all_english"],
    config: FinalDiscoveryConfig,
) -> None:
    if set(pair_ids) != set(calibration_by_pair):
        raise EnsembleError("final null calibration must cover the exact candidate population")
    expected_seed = config.calibration.seeds["stratified_permutation"]
    permitted_iterations = {
        config.calibration.fixture_iterations,
        config.calibration.production_iterations,
    }
    stratum_counts: dict[str, int] = defaultdict(int)
    for row in calibration_by_pair.values():
        stratum_counts[row.stratum] += 1
    for pair_id in pair_ids:
        row = calibration_by_pair[pair_id]
        if (
            row.candidate_pair_id != pair_id
            or row.calibration_scope != scope
            or row.null_method != config.ensemble.final_null_method
            or row.seed != expected_seed
            or row.iterations not in permitted_iterations
            or row.hypothesis_count != len(pair_ids)
            or row.stratum_size != stratum_counts[row.stratum]
        ):
            raise EnsembleError(f"final null calibration provenance mismatch: {pair_id}")
    fdr_by_threshold: dict[float, float] = {}
    for row in calibration_by_pair.values():
        prior = fdr_by_threshold.setdefault(row.observed_score, row.empirical_fdr)
        if not math.isclose(prior, row.empirical_fdr, rel_tol=0.0, abs_tol=1e-15):
            raise EnsembleError("equal null thresholds must carry equal monotone FDR values")
    prior_fdr = 0.0
    for threshold in sorted(fdr_by_threshold, reverse=True):
        current = fdr_by_threshold[threshold]
        if current + 1e-15 < prior_fdr:
            raise EnsembleError("loosening the score threshold cannot improve empirical FDR")
        prior_fdr = current


def _english_ablated_row_score(row: EvidenceRow) -> float | None:
    if not row.contains_english_derived_evidence:
        return row.normalized_score
    return row.english_ablation_normalized_score


def _draft_from_pair(
    pair_id: str,
    rows: Sequence[EvidenceRow],
    left: PassageRecord,
    right: PassageRecord,
    *,
    knownness: KnownnessIndex,
    config: FinalDiscoveryConfig,
    full_null: EnsembleNullCalibrationRow,
    ablated_null: EnsembleNullCalibrationRow | None,
    ablation_null_available: bool,
) -> _Draft:
    """Build one pair-local draft without retaining any other hypothesis."""

    ordered_rows = tuple(sorted(rows, key=lambda row: row.evidence_id))
    if not ordered_rows:
        raise EnsembleError(f"candidate pair has no evidence: {pair_id}")
    if {(row.candidate_pair_id, row.passage_a_id, row.passage_b_id) for row in ordered_rows} != {
        (pair_id, left.passage_id, right.passage_id)
    }:
        raise EnsembleError(f"candidate evidence identity disagrees: {pair_id}")
    group_scores = _group_score(ordered_rows)
    ablated_group_scores = _group_score(ordered_rows, remove_all_english=True)
    score = _ensemble_score(group_scores, config)
    ablated_score = _ensemble_score(ablated_group_scores, config)
    threshold = config.ensemble.qualifying_group_normalized_score
    qualifying = {
        row.independence_group
        for row in ordered_rows
        if row.counts_for_independence and row.normalized_score >= threshold
    }
    original = {
        row.independence_group
        for row in ordered_rows
        if row.counts_for_independence
        and row.original_language_evidence_remains
        and (ablated_row_score := _english_ablated_row_score(row)) is not None
        and ablated_row_score >= threshold
    }
    original_families = {
        row.family
        for row in ordered_rows
        if row.independence_group in original
        and row.counts_for_independence
        and row.original_language_evidence_remains
    }
    contains_english = any(row.contains_english_derived_evidence for row in ordered_rows)
    status, relationship_ids = _reconcile_knownness(left, right, ordered_rows, knownness)
    if not math.isclose(full_null.observed_score, score, rel_tol=0.0, abs_tol=1e-15):
        raise EnsembleError(f"full null observed score mismatch: {pair_id}")
    if ablated_null is None:
        ablated_p_value = 1.0
        ablated_fdr = 1.0
        ablated_sufficient = False
    else:
        if not math.isclose(
            ablated_null.observed_score,
            ablated_score,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise EnsembleError(f"English-ablation null observed score mismatch: {pair_id}")
        ablated_p_value = ablated_null.empirical_p_value
        ablated_fdr = ablated_null.empirical_fdr
        ablated_sufficient = ablated_null.stratum_sufficient_for_bh
    return _Draft(
        pair_id=pair_id,
        passage_a=left,
        passage_b=right,
        evidence=ordered_rows,
        group_scores=group_scores,
        ensemble_score=score,
        score_without_english=ablated_score,
        empirical_p_value=full_null.empirical_p_value,
        empirical_fdr=full_null.empirical_fdr,
        null_stratum_sufficient_for_bh=full_null.stratum_sufficient_for_bh,
        english_ablation_empirical_p_value=ablated_p_value,
        english_ablation_empirical_fdr=ablated_fdr,
        english_ablation_null_available=ablation_null_available,
        english_ablation_null_stratum_sufficient_for_bh=ablated_sufficient,
        knownness_status=status,
        known_relationship_ids=relationship_ids,
        quality=_quality(left, right, ordered_rows),
        qualifying_groups=tuple(sorted(qualifying)),
        original_groups=tuple(sorted(original)),
        original_families=tuple(sorted(original_families)),
        contains_english=contains_english,
    )


def _drafts(
    evidence: Sequence[EvidenceRow],
    passages: Mapping[str, PassageRecord],
    knownness: KnownnessIndex,
    config: FinalDiscoveryConfig,
    null_calibration_by_pair: Mapping[str, EnsembleNullCalibrationRow],
    english_ablation_null_calibration_by_pair: Mapping[str, EnsembleNullCalibrationRow] | None,
) -> list[_Draft]:
    grouped: dict[str, list[EvidenceRow]] = defaultdict(list)
    for row in evidence:
        grouped[row.candidate_pair_id].append(row)
    pair_ids = sorted(grouped)
    _validate_null_calibration(pair_ids, null_calibration_by_pair, scope="full", config=config)
    contains_any_english = any(
        row.contains_english_derived_evidence for rows in grouped.values() for row in rows
    )
    ablation_null_available = english_ablation_null_calibration_by_pair is not None
    if english_ablation_null_calibration_by_pair is None and not contains_any_english:
        english_ablation_null_calibration_by_pair = null_calibration_by_pair
        ablation_null_available = True
    if contains_any_english and english_ablation_null_calibration_by_pair is not None:
        _validate_null_calibration(
            pair_ids,
            english_ablation_null_calibration_by_pair,
            scope="remove_all_english",
            config=config,
        )
    prepared: list[
        tuple[
            str,
            PassageRecord,
            PassageRecord,
            tuple[EvidenceRow, ...],
            dict[str, float],
            dict[str, float],
        ]
    ] = []
    for pair_id in pair_ids:
        rows = tuple(sorted(grouped[pair_id], key=lambda row: row.evidence_id))
        passage_pairs = {(row.passage_a_id, row.passage_b_id) for row in rows}
        if len(passage_pairs) != 1:
            raise EnsembleError(f"candidate evidence points to multiple pairs: {pair_id}")
        passage_a_id, passage_b_id = next(iter(passage_pairs))
        try:
            left = passages[passage_a_id]
            right = passages[passage_b_id]
        except KeyError as exc:
            raise EnsembleError(f"candidate evidence references an absent passage: {exc}") from exc
        group_scores = _group_score(rows)
        ablated_group_scores = _group_score(rows, remove_all_english=True)
        prepared.append((pair_id, left, right, rows, group_scores, ablated_group_scores))
    drafts: list[_Draft] = []
    for pair_id, left, right, rows, _, _ in prepared:
        drafts.append(
            _draft_from_pair(
                pair_id,
                rows,
                left,
                right,
                knownness=knownness,
                config=config,
                full_null=null_calibration_by_pair[pair_id],
                ablated_null=(
                    english_ablation_null_calibration_by_pair[pair_id]
                    if english_ablation_null_calibration_by_pair is not None
                    else None
                ),
                ablation_null_available=ablation_null_available,
            )
        )
    return drafts


def _quality_is_eligible(draft: _Draft, config: FinalDiscoveryConfig) -> bool:
    return not draft.quality.basic_exclusion and not any(
        bool(getattr(draft.quality, flag)) for flag in config.tiers.tier_a_quality_exclusions
    )


def _english_ablation_survives(
    draft: _Draft, ablated_q_value: float, config: FinalDiscoveryConfig
) -> bool:
    if not draft.contains_english:
        return True
    return (
        draft.english_ablation_null_available
        and draft.english_ablation_null_stratum_sufficient_for_bh
        and draft.knownness_status == "unknown"
        and draft.score_without_english >= config.ensemble.minimum_tier_a_ensemble_score
        and ablated_q_value <= config.calibration.maximum_bh_q_value
        and draft.english_ablation_empirical_fdr <= config.calibration.maximum_empirical_fdr
        and len(draft.original_families) >= config.calibration.minimum_independent_families
        and _quality_is_eligible(draft, config)
    )


def _exclusion_reasons(
    draft: _Draft,
    q_value: float,
    english_ablation_survives: bool,
    config: FinalDiscoveryConfig,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if draft.knownness_status != "unknown":
        reasons.append("known_relationship_either_direction")
    if draft.ensemble_score < config.ensemble.minimum_tier_a_ensemble_score:
        reasons.append("ensemble_score_below_frozen_threshold")
    if q_value > config.calibration.maximum_bh_q_value:
        reasons.append("bh_q_value_above_frozen_limit")
    if draft.empirical_fdr > config.calibration.maximum_empirical_fdr:
        reasons.append("empirical_fdr_above_frozen_limit")
    if not draft.null_stratum_sufficient_for_bh:
        reasons.append("null_stratum_insufficient_for_bh_resolution")
    if len(draft.original_families) < config.calibration.minimum_independent_families:
        reasons.append("fewer_than_two_independent_original_language_families")
    if not english_ablation_survives:
        reasons.append("remove_all_english_ablation_failed")
    for flag in config.tiers.tier_a_quality_exclusions:
        if bool(getattr(draft.quality, flag)):
            reasons.append(f"quality_{flag}")
    if draft.quality.basic_exclusion:
        reasons.append("basic_data_quality_exclusion")
    return tuple(reasons)


def _final_candidate_from_draft(
    draft: _Draft,
    *,
    q_value: float,
    english_ablation_q_value: float,
    tier_b_rank: int | None,
    config: FinalDiscoveryConfig,
) -> FinalCandidate:
    """Finalize one independently prepared draft using global BH/Tier-B state."""

    english_ablation_survives = _english_ablation_survives(
        draft,
        english_ablation_q_value,
        config,
    )
    reasons = _exclusion_reasons(
        draft,
        q_value,
        english_ablation_survives,
        config,
    )
    tier_a = not reasons
    if tier_a and tier_b_rank is not None:
        raise EnsembleError("a Tier A candidate cannot receive a Tier B rank")
    label: OutputLabel = (
        "statistically_eligible"
        if tier_a
        else "exploratory_not_statistically_accepted"
        if tier_b_rank is not None
        else "retained_excluded"
    )
    return FinalCandidate(
        candidate_pair_id=draft.pair_id,
        passage_a_id=draft.passage_a.passage_id,
        passage_b_id=draft.passage_b.passage_id,
        passage_a_reference=draft.passage_a.reference,
        passage_b_reference=draft.passage_b.reference,
        ensemble_score=draft.ensemble_score,
        empirical_p_value=draft.empirical_p_value,
        bh_q_value=q_value,
        empirical_fdr=draft.empirical_fdr,
        knownness_status=draft.knownness_status,
        known_relationship_ids=draft.known_relationship_ids,
        quality=draft.quality,
        evidence_ids=tuple(row.evidence_id for row in draft.evidence),
        detector_ids=tuple(sorted({row.detector_id for row in draft.evidence})),
        families=tuple(sorted({row.family for row in draft.evidence})),
        qualifying_independence_groups=draft.qualifying_groups,
        original_language_independence_groups=draft.original_groups,
        contains_english_derived_evidence=draft.contains_english,
        score_without_english=draft.score_without_english,
        english_ablation_empirical_p_value=draft.english_ablation_empirical_p_value,
        english_ablation_bh_q_value=english_ablation_q_value,
        english_ablation_empirical_fdr=draft.english_ablation_empirical_fdr,
        english_ablation_survives=english_ablation_survives,
        tier_a_eligible=tier_a,
        tier_a_exclusion_reasons=reasons,
        tier_b_rank=tier_b_rank,
        output_label=label,
    )


def build_final_candidates(
    evidence: Sequence[EvidenceRow],
    passages: Mapping[str, PassageRecord],
    *,
    knownness: KnownnessIndex,
    config: FinalDiscoveryConfig,
    null_calibration_by_pair: Mapping[str, EnsembleNullCalibrationRow],
    english_ablation_null_calibration_by_pair: Mapping[str, EnsembleNullCalibrationRow]
    | None = None,
) -> tuple[FinalCandidate, ...]:
    """Apply frozen Tier A rules and select a distinct unknown Tier B top 100."""

    if not evidence:
        return ()
    drafts = _drafts(
        evidence,
        passages,
        knownness,
        config,
        null_calibration_by_pair,
        english_ablation_null_calibration_by_pair,
    )
    q_values = benjamini_hochberg([draft.empirical_p_value for draft in drafts])
    english_ablation_q_values = benjamini_hochberg(
        [draft.english_ablation_empirical_p_value for draft in drafts]
    )
    ablation_survival_by_pair = {
        draft.pair_id: _english_ablation_survives(draft, ablated_q_value, config)
        for draft, ablated_q_value in zip(drafts, english_ablation_q_values, strict=True)
    }
    reasons_by_pair = {
        draft.pair_id: _exclusion_reasons(
            draft, q_value, ablation_survival_by_pair[draft.pair_id], config
        )
        for draft, q_value in zip(drafts, q_values, strict=True)
    }
    tier_a_ids = {pair_id for pair_id, reasons in reasons_by_pair.items() if not reasons}
    tier_b_pool = [
        draft
        for draft in drafts
        if draft.pair_id not in tier_a_ids
        and draft.knownness_status == "unknown"
        and not draft.quality.basic_exclusion
    ]
    tier_b_pool.sort(key=lambda draft: (-draft.ensemble_score, draft.pair_id))
    tier_b_ranks = {
        draft.pair_id: rank
        for rank, draft in enumerate(tier_b_pool[: config.tiers.tier_b_size], start=1)
    }
    candidates: list[FinalCandidate] = []
    for draft, q_value, ablated_q_value in zip(
        drafts, q_values, english_ablation_q_values, strict=True
    ):
        tier_b_rank = tier_b_ranks.get(draft.pair_id)
        candidates.append(
            _final_candidate_from_draft(
                draft,
                q_value=q_value,
                english_ablation_q_value=ablated_q_value,
                tier_b_rank=tier_b_rank,
                config=config,
            )
        )
    return tuple(
        sorted(candidates, key=lambda item: (-item.ensemble_score, item.candidate_pair_id))
    )
