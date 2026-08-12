"""Strict scientific and checkpoint validation for final-discovery outputs."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, computed_field

from echoes.final_discovery.config import FinalDiscoveryConfig
from echoes.final_discovery.features import (
    candidate_pair_id,
    canonical_json,
    evidence_id,
)
from echoes.final_discovery.knownness import KnownnessIndex
from echoes.final_discovery.models import (
    EvidenceFamily,
    EvidenceRow,
    FinalCandidate,
    KnownnessStatus,
    PassageRecord,
    QualityFlags,
)
from echoes.final_discovery.nulls import EnsembleNullCalibrationRow
from echoes.final_discovery.stages import (
    FINAL_DISCOVERY_STAGE_IDS,
    StageRegistrationLike,
    StageStore,
    StageStoreError,
    assert_stage_registrations,
)
from echoes.lexical.statistics import benjamini_hochberg


class FinalDiscoveryValidationError(ValueError):
    """Raised when validation itself cannot execute safely."""


class ValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    candidate_pair_id: str | None = None


class FinalDiscoveryValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: str
    evidence_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    tier_a_count: int = Field(ge=0)
    tier_b_count: int = Field(ge=0)
    authenticated_stage_count: int = Field(ge=0, le=11)
    findings: tuple[ValidationFinding, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_count(self) -> int:
        return len(self.findings)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return not self.findings


def _finding(
    findings: list[ValidationFinding],
    code: str,
    message: str,
    candidate_pair_id: str | None = None,
) -> None:
    findings.append(
        ValidationFinding(
            code=code,
            message=message,
            candidate_pair_id=candidate_pair_id,
        )
    )


NullCalibrationInput = (
    Mapping[str, EnsembleNullCalibrationRow] | Sequence[EnsembleNullCalibrationRow]
)


@dataclass(frozen=True, slots=True)
class _ScientificDraft:
    pair_id: str
    passage_a: PassageRecord
    passage_b: PassageRecord
    evidence: tuple[EvidenceRow, ...]
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


def _close(left: float, right: float, *, tolerance: float = 1e-12) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def _trace_object(
    row: EvidenceRow,
    *,
    require_canonical: bool,
    findings: list[ValidationFinding],
) -> dict[str, object] | None:
    try:
        parsed = json.loads(row.trace_json)
    except (json.JSONDecodeError, TypeError) as exc:
        _finding(
            findings,
            "invalid-evidence-trace-json",
            f"evidence {row.evidence_id} trace is not valid JSON: {exc}",
            row.candidate_pair_id,
        )
        return None
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        _finding(
            findings,
            "invalid-evidence-trace-object",
            f"evidence {row.evidence_id} trace must be a string-keyed object",
            row.candidate_pair_id,
        )
        return None
    if require_canonical:
        try:
            serialized = canonical_json(parsed)
        except (TypeError, ValueError) as exc:
            _finding(
                findings,
                "invalid-evidence-trace-value",
                f"evidence {row.evidence_id} trace is not canonicalizable: {exc}",
                row.candidate_pair_id,
            )
            return None
        if serialized != row.trace_json:
            _finding(
                findings,
                "noncanonical-evidence-trace",
                f"evidence {row.evidence_id} trace is not canonical JSON",
                row.candidate_pair_id,
            )
    return cast(dict[str, object], parsed)


def _validate_m7_trace(
    row: EvidenceRow,
    trace: Mapping[str, object],
    *,
    config: FinalDiscoveryConfig,
    findings: list[ValidationFinding],
) -> None:
    m7_input = next(item for item in config.inputs if item.role == "canonical_m7")
    if row.source_artifact_id != m7_input.artifact_id:
        _finding(
            findings,
            "m7-source-artifact-id",
            f"M7 evidence {row.evidence_id} does not identify the registered M7 artifact",
            row.candidate_pair_id,
        )
    if trace.get("representation") != "canonical_m7_reciprocal_rank_fusion":
        _finding(
            findings,
            "m7-trace-representation",
            f"M7 evidence {row.evidence_id} has the wrong representation trace",
            row.candidate_pair_id,
        )
    if (
        config.calibration.require_both_m7_null_families
        and trace.get("m7_both_null_families_present") is not True
    ):
        _finding(
            findings,
            "m7-null-family-authentication",
            f"M7 evidence {row.evidence_id} does not authenticate both source null families",
            row.candidate_pair_id,
        )
    traced_ids = trace.get("m7_openbible_relationship_ids")
    if not isinstance(traced_ids, list) or tuple(traced_ids) != row.source_known_relationship_ids:
        _finding(
            findings,
            "m7-knownness-trace",
            f"M7 evidence {row.evidence_id} knownness IDs disagree with its trace",
            row.candidate_pair_id,
        )
    status = trace.get("m7_known_link_status")
    expected_status: KnownnessStatus | None = (
        "known_m7_snapshot" if status == "represented_in_openbible_snapshot" else None
    )
    if (
        status
        not in {
            "represented_in_openbible_snapshot",
            "not_represented_in_openbible_snapshot",
            "mapping_unresolved",
        }
        or row.source_knownness_status != expected_status
    ):
        _finding(
            findings,
            "m7-knownness-status-trace",
            f"M7 evidence {row.evidence_id} knownness status disagrees with its trace",
            row.candidate_pair_id,
        )
    traced_quality = trace.get("m7_quality")
    expected_quality = (
        row.source_quality.model_dump(mode="json") if row.source_quality is not None else None
    )
    if traced_quality != expected_quality:
        _finding(
            findings,
            "m7-quality-trace",
            f"M7 evidence {row.evidence_id} quality flags disagree with its trace",
            row.candidate_pair_id,
        )


def _validate_embedding_trace(
    row: EvidenceRow,
    trace: Mapping[str, object],
    *,
    config: FinalDiscoveryConfig,
    findings: list[ValidationFinding],
) -> None:
    pin = config.embedding_model
    expected = {
        "model_id": pin.model_id,
        "model_revision": pin.revision,
        "tokenizer": pin.tokenizer,
        "pooling": pin.pooling,
        "maximum_tokens": pin.maximum_tokens,
        "symmetric_prefix": pin.symmetric_prefix,
    }
    if any(trace.get(name) != value for name, value in expected.items()):
        _finding(
            findings,
            "embedding-model-trace",
            f"embedding evidence {row.evidence_id} disagrees with the pinned model",
            row.candidate_pair_id,
        )
    expected_representation = (
        "pinned_multilingual_e5_literal_english_gloss"
        if row.detector_id == "multilingual_e5_english_gloss"
        else "pinned_multilingual_e5_original_text"
    )
    if trace.get("representation") != expected_representation:
        _finding(
            findings,
            "embedding-representation-trace",
            f"embedding evidence {row.evidence_id} has the wrong representation trace",
            row.candidate_pair_id,
        )
    if row.source_artifact_id != f"{pin.model_id}@{pin.revision}":
        _finding(
            findings,
            "embedding-source-artifact-id",
            f"embedding evidence {row.evidence_id} has the wrong source artifact ID",
            row.candidate_pair_id,
        )
    inventory_hash = trace.get("model_inventory_sha256")
    projection_hash = trace.get("passage_projection_sha256")
    composite_hash = trace.get("composite_source_sha256")
    if not all(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
        for value in (inventory_hash, projection_hash, composite_hash)
    ):
        _finding(
            findings,
            "embedding-source-hash-trace",
            f"embedding evidence {row.evidence_id} lacks complete SHA-256 lineage",
            row.candidate_pair_id,
        )
        return
    recomputed = _sha256_json(
        {
            "model_inventory_sha256": inventory_hash,
            "passage_projection_sha256": projection_hash,
        }
    )
    if composite_hash != recomputed or row.source_artifact_sha256 != recomputed:
        _finding(
            findings,
            "embedding-composite-source-hash",
            f"embedding evidence {row.evidence_id} has an invalid composite source hash",
            row.candidate_pair_id,
        )
    if row.detector_id == "multilingual_e5_english_gloss" and (
        trace.get("supplemental_english_derived") is not True
        or not row.contains_english_derived_evidence
        or row.original_language_evidence_remains
        or row.counts_for_independence
    ):
        _finding(
            findings,
            "embedding-english-semantics",
            f"English embedding evidence {row.evidence_id} violates supplemental-only semantics",
            row.candidate_pair_id,
        )


def _validate_evidence_contract(
    evidence: Sequence[EvidenceRow],
    *,
    config: FinalDiscoveryConfig,
    strict_lineage: bool,
    expected_source_artifact_sha256: Mapping[str, str] | None,
    findings: list[ValidationFinding],
) -> tuple[dict[str, EvidenceRow], dict[str, list[EvidenceRow]]]:
    evidence_by_id: dict[str, EvidenceRow] = {}
    evidence_by_pair: dict[str, list[EvidenceRow]] = defaultdict(list)
    registrations = {registration.detector_id: registration for registration in config.detectors}
    source_hash_by_id: dict[str, str] = {}
    detector_pairs: set[tuple[str, str]] = set()
    for row in evidence:
        if row.evidence_id in evidence_by_id:
            _finding(findings, "duplicate-evidence-id", "evidence IDs are not unique")
        evidence_by_id[row.evidence_id] = row
        evidence_by_pair[row.candidate_pair_id].append(row)
        expected_pair_id = candidate_pair_id(row.passage_a_id, row.passage_b_id)
        if row.candidate_pair_id != expected_pair_id:
            _finding(
                findings,
                "evidence-candidate-pair-id",
                f"evidence {row.evidence_id} has a noncanonical candidate-pair ID",
                row.candidate_pair_id,
            )
        expected_evidence_id = evidence_id(
            row.candidate_pair_id, row.detector_id, row.source_artifact_sha256
        )
        if row.evidence_id != expected_evidence_id:
            _finding(
                findings,
                "evidence-id",
                f"evidence {row.evidence_id} does not match its hashed identity payload",
                row.candidate_pair_id,
            )
        detector_pair = (row.candidate_pair_id, row.detector_id)
        if detector_pair in detector_pairs:
            _finding(
                findings,
                "duplicate-pair-detector",
                f"pair {row.candidate_pair_id} has multiple {row.detector_id} evidence rows",
                row.candidate_pair_id,
            )
        detector_pairs.add(detector_pair)
        prior_hash = source_hash_by_id.setdefault(
            row.source_artifact_id, row.source_artifact_sha256
        )
        if prior_hash != row.source_artifact_sha256:
            _finding(
                findings,
                "source-artifact-hash-conflict",
                f"source artifact {row.source_artifact_id} carries multiple SHA-256 values",
                row.candidate_pair_id,
            )
        if expected_source_artifact_sha256 is not None:
            expected_hash = expected_source_artifact_sha256.get(row.source_artifact_id)
            if expected_hash is not None and expected_hash != row.source_artifact_sha256:
                _finding(
                    findings,
                    "source-artifact-hash",
                    (
                        f"source artifact {row.source_artifact_id} does not match its "
                        "authenticated hash"
                    ),
                    row.candidate_pair_id,
                )
        if not math.isfinite(row.raw_score):
            _finding(
                findings,
                "nonfinite-raw-score",
                f"evidence {row.evidence_id} has a non-finite raw score",
                row.candidate_pair_id,
            )
        registration = registrations.get(row.detector_id)
        if registration is None:
            _finding(
                findings,
                "unregistered-detector",
                f"evidence {row.evidence_id} uses unregistered detector {row.detector_id}",
                row.candidate_pair_id,
            )
        else:
            registered_values = (
                registration.family,
                registration.independence_group,
                registration.normalization,
                registration.null_family,
            )
            observed_values = (
                row.family,
                row.independence_group,
                row.normalization_method,
                row.null_method,
            )
            if observed_values != registered_values:
                _finding(
                    findings,
                    "detector-registration-lineage",
                    f"evidence {row.evidence_id} disagrees with detector registration",
                    row.candidate_pair_id,
                )
            expected_independence = registration.counts_for_independence and (
                not row.contains_english_derived_evidence or row.original_language_evidence_remains
            )
            if row.counts_for_independence != expected_independence:
                _finding(
                    findings,
                    "detector-independence-registration",
                    f"evidence {row.evidence_id} has unregistered independence semantics",
                    row.candidate_pair_id,
                )
            if (
                row.contains_english_derived_evidence
                and not registration.contains_english_derived_evidence
            ) or (
                row.original_language_evidence_remains
                and not registration.original_language_capable
            ):
                _finding(
                    findings,
                    "detector-language-registration",
                    f"evidence {row.evidence_id} has unregistered language semantics",
                    row.candidate_pair_id,
                )
        trace = _trace_object(
            row,
            require_canonical=strict_lineage,
            findings=findings,
        )
        if strict_lineage and trace is not None:
            if row.detector_id == "m7_lexical_rrf":
                _validate_m7_trace(row, trace, config=config, findings=findings)
            elif row.detector_id in {
                "multilingual_e5_original_language",
                "multilingual_e5_english_gloss",
            }:
                _validate_embedding_trace(row, trace, config=config, findings=findings)
    return evidence_by_id, evidence_by_pair


def _index_null_calibration(
    calibration: NullCalibrationInput,
    *,
    scope_name: str,
    findings: list[ValidationFinding],
) -> dict[str, EnsembleNullCalibrationRow]:
    indexed: dict[str, EnsembleNullCalibrationRow] = {}
    items = (
        calibration.items()
        if isinstance(calibration, Mapping)
        else ((row.candidate_pair_id, row) for row in calibration)
    )
    for supplied_pair_id, row in items:
        if supplied_pair_id != row.candidate_pair_id:
            _finding(
                findings,
                f"{scope_name}-null-index-key",
                f"null map key {supplied_pair_id} disagrees with row {row.candidate_pair_id}",
                row.candidate_pair_id,
            )
        if row.candidate_pair_id in indexed:
            _finding(
                findings,
                f"duplicate-{scope_name}-null-row",
                f"duplicate {scope_name} null row for {row.candidate_pair_id}",
                row.candidate_pair_id,
            )
        indexed[row.candidate_pair_id] = row
    return indexed


def _validate_null_calibration_rows(
    calibration_by_pair: Mapping[str, EnsembleNullCalibrationRow],
    observed_scores: Mapping[str, float],
    *,
    scope: Literal["full", "remove_all_english"],
    config: FinalDiscoveryConfig,
    findings: list[ValidationFinding],
) -> None:
    scope_name = "full" if scope == "full" else "english-ablation"
    pair_ids = set(observed_scores)
    if set(calibration_by_pair) != pair_ids:
        missing = sorted(pair_ids - set(calibration_by_pair))
        extra = sorted(set(calibration_by_pair) - pair_ids)
        _finding(
            findings,
            f"{scope_name}-null-coverage",
            f"{scope_name} null coverage mismatch; missing={missing[:3]}, extra={extra[:3]}",
        )
    hypothesis_count = len(pair_ids)
    expected_seed = config.calibration.seeds["stratified_permutation"]
    permitted_iterations = {
        config.calibration.fixture_iterations,
        config.calibration.production_iterations,
    }
    stratum_counts: dict[str, int] = defaultdict(int)
    for pair_id, row in calibration_by_pair.items():
        if pair_id in pair_ids:
            stratum_counts[row.stratum] += 1
    global_by_threshold: dict[float, tuple[int, float, int, float, float]] = {}
    stratum_by_threshold: dict[tuple[str, float], tuple[int, int, float]] = {}
    raw_fdr_by_threshold: dict[float, float] = {}
    for pair_id, row in calibration_by_pair.items():
        if pair_id not in pair_ids:
            continue
        expected_score = observed_scores[pair_id]
        if row.calibration_scope != scope:
            _finding(
                findings,
                f"{scope_name}-null-scope",
                f"{scope_name} null row has scope {row.calibration_scope}",
                pair_id,
            )
        if not _close(row.observed_score, expected_score, tolerance=1e-15):
            _finding(
                findings,
                f"{scope_name}-null-observed-score",
                f"{scope_name} null observed score differs from recomputed ensemble score",
                pair_id,
            )
        if (
            row.null_method != config.ensemble.final_null_method
            or row.seed != expected_seed
            or row.iterations not in permitted_iterations
            or row.hypothesis_count != hypothesis_count
            or row.stratum_size != stratum_counts[row.stratum]
        ):
            _finding(
                findings,
                f"{scope_name}-null-provenance",
                f"{scope_name} null row has inconsistent registered provenance",
                pair_id,
            )
        expected_effective_cells = row.stratum_size * row.iterations
        valid_denominators = (
            expected_effective_cells >= 1
            and row.iterations >= 1
            and row.observed_discovery_count >= 1
        )
        if valid_denominators:
            expected_p = (row.null_exceedance_count + 1) / (expected_effective_cells + 1)
            expected_mean = (row.null_discovery_count_sum + 1) / (row.iterations + 1)
            expected_raw_fdr = min(expected_mean / row.observed_discovery_count, 1.0)
            expected_minimum_p = 1 / (expected_effective_cells + 1)
        else:
            expected_p = math.nan
            expected_mean = math.nan
            expected_raw_fdr = math.nan
            expected_minimum_p = math.nan
        expected_minimum_draws = (
            config.calibration.minimum_effective_null_draws
            if row.iterations == config.calibration.production_iterations
            else row.iterations
        )
        expected_sufficient = expected_effective_cells >= expected_minimum_draws
        if (
            row.effective_null_cell_count != expected_effective_cells
            or row.null_exceedance_count > expected_effective_cells
            or not valid_denominators
            or not _close(row.empirical_p_value, expected_p, tolerance=1e-15)
            or not _close(row.minimum_attainable_p_value, expected_minimum_p, tolerance=1e-15)
        ):
            _finding(
                findings,
                f"{scope_name}-null-p-value-invariant",
                f"{scope_name} null p-value/count invariants fail",
                pair_id,
            )
        if (
            row.null_discovery_count_sum > row.iterations * row.hypothesis_count
            or not _close(row.mean_null_discovery_count, expected_mean, tolerance=1e-15)
            or not _close(row.raw_empirical_fdr, expected_raw_fdr, tolerance=1e-15)
            or row.empirical_fdr + 1e-15 < row.raw_empirical_fdr
        ):
            _finding(
                findings,
                f"{scope_name}-null-fdr-invariant",
                f"{scope_name} null discovery/FDR invariants fail",
                pair_id,
            )
        expected_observed_count = sum(
            score >= row.observed_score for score in observed_scores.values()
        )
        if row.observed_discovery_count != expected_observed_count:
            _finding(
                findings,
                f"{scope_name}-null-observed-discoveries",
                f"{scope_name} null observed discovery count is not reproducible",
                pair_id,
            )
        if (
            row.minimum_effective_null_draws != expected_minimum_draws
            or row.stratum_sufficient_for_bh != expected_sufficient
        ):
            _finding(
                findings,
                f"{scope_name}-null-resolution",
                f"{scope_name} null BH-resolution fields violate the execution mode",
                pair_id,
            )
        global_signature = (
            row.null_discovery_count_sum,
            row.mean_null_discovery_count,
            row.observed_discovery_count,
            row.raw_empirical_fdr,
            row.empirical_fdr,
        )
        prior_global = global_by_threshold.setdefault(row.observed_score, global_signature)
        if prior_global != global_signature:
            _finding(
                findings,
                f"{scope_name}-null-threshold-global-state",
                f"equal {scope_name} thresholds carry different global null statistics",
                pair_id,
            )
        stratum_signature = (
            row.null_exceedance_count,
            row.effective_null_cell_count,
            row.empirical_p_value,
        )
        prior_stratum = stratum_by_threshold.setdefault(
            (row.stratum, row.observed_score), stratum_signature
        )
        if prior_stratum != stratum_signature:
            _finding(
                findings,
                f"{scope_name}-null-threshold-stratum-state",
                f"equal stratum thresholds carry different {scope_name} p-value state",
                pair_id,
            )
        raw_fdr_by_threshold.setdefault(row.observed_score, row.raw_empirical_fdr)
    running_fdr = 0.0
    expected_fdr_by_threshold: dict[float, float] = {}
    for threshold in sorted(raw_fdr_by_threshold, reverse=True):
        running_fdr = max(running_fdr, raw_fdr_by_threshold[threshold])
        expected_fdr_by_threshold[threshold] = running_fdr
    for pair_id, row in calibration_by_pair.items():
        expected_fdr = expected_fdr_by_threshold.get(row.observed_score)
        if expected_fdr is not None and not _close(
            row.empirical_fdr, expected_fdr, tolerance=1e-15
        ):
            _finding(
                findings,
                f"{scope_name}-null-monotone-fdr",
                f"{scope_name} null FDR is not the exact monotone envelope",
                pair_id,
            )


def _group_scores(evidence: Sequence[EvidenceRow], *, remove_all_english: bool) -> dict[str, float]:
    maxima: dict[str, float] = {}
    for row in evidence:
        score = row.normalized_score
        if remove_all_english and row.contains_english_derived_evidence:
            if row.english_ablation_normalized_score is None:
                continue
            score = row.english_ablation_normalized_score
        maxima[row.independence_group] = max(maxima.get(row.independence_group, 0.0), score)
    return maxima


def _english_ablated_row_score(row: EvidenceRow) -> float | None:
    if not row.contains_english_derived_evidence:
        return row.normalized_score
    return row.english_ablation_normalized_score


def _weighted_score(group_scores: Mapping[str, float], config: FinalDiscoveryConfig) -> float:
    return math.fsum(
        weight * group_scores.get(group, config.ensemble.missing_group_score)
        for group, weight in config.ensemble.group_weights.items()
    )


def _recomputed_quality(
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


def _recomputed_knownness(
    left: PassageRecord,
    right: PassageRecord,
    evidence: Sequence[EvidenceRow],
    knownness: KnownnessIndex,
) -> tuple[KnownnessStatus, tuple[str, ...]]:
    indexed_status, indexed_ids = knownness.classify(left.passage_id, right.passage_id)
    statuses = {
        row.source_knownness_status
        for row in evidence
        if row.source_knownness_status not in {None, "unknown"}
    }
    if indexed_status != "unknown":
        statuses.add(indexed_status)
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
    if not statuses:
        return "unknown", ()
    if "known_both" in statuses or {"known_forward", "known_reverse"}.issubset(statuses):
        return "known_both", relationship_ids
    directional = statuses & {"known_forward", "known_reverse"}
    if directional == {"known_forward"}:
        return "known_forward", relationship_ids
    if directional == {"known_reverse"}:
        return "known_reverse", relationship_ids
    return "known_m7_snapshot", relationship_ids


def _build_scientific_drafts(
    evidence_by_pair: Mapping[str, Sequence[EvidenceRow]],
    passages: Mapping[str, PassageRecord],
    knownness: KnownnessIndex,
    full_null_by_pair: Mapping[str, EnsembleNullCalibrationRow],
    ablated_null_by_pair: Mapping[str, EnsembleNullCalibrationRow] | None,
    *,
    config: FinalDiscoveryConfig,
    findings: list[ValidationFinding],
) -> tuple[_ScientificDraft, ...]:
    contains_any_english = any(
        row.contains_english_derived_evidence
        for pair_rows in evidence_by_pair.values()
        for row in pair_rows
    )
    effective_ablated_null = ablated_null_by_pair
    ablation_null_available = effective_ablated_null is not None
    if effective_ablated_null is None and not contains_any_english:
        effective_ablated_null = full_null_by_pair
        ablation_null_available = True
    drafts: list[_ScientificDraft] = []
    threshold = config.ensemble.qualifying_group_normalized_score
    for pair_id in sorted(evidence_by_pair):
        rows = tuple(sorted(evidence_by_pair[pair_id], key=lambda row: row.evidence_id))
        passage_pairs = {(row.passage_a_id, row.passage_b_id) for row in rows}
        if len(passage_pairs) != 1:
            _finding(
                findings,
                "evidence-passage-pair-conflict",
                "retained evidence for a candidate points to multiple passage pairs",
                pair_id,
            )
            continue
        passage_a_id, passage_b_id = next(iter(passage_pairs))
        left = passages.get(passage_a_id)
        right = passages.get(passage_b_id)
        if left is None or right is None:
            _finding(
                findings,
                "evidence-passage-missing",
                f"candidate evidence references absent passages {passage_a_id}/{passage_b_id}",
                pair_id,
            )
            continue
        if left.passage_id != passage_a_id or right.passage_id != passage_b_id:
            _finding(
                findings,
                "passage-index-key",
                "passage mapping keys disagree with persisted passage IDs",
                pair_id,
            )
            continue
        full_null = full_null_by_pair.get(pair_id)
        if full_null is None:
            continue
        group_scores = _group_scores(rows, remove_all_english=False)
        ablated_group_scores = _group_scores(rows, remove_all_english=True)
        score = _weighted_score(group_scores, config)
        ablated_score = _weighted_score(ablated_group_scores, config)
        qualifying = {
            row.independence_group
            for row in rows
            if row.counts_for_independence and row.normalized_score >= threshold
        }
        original: set[str] = set()
        for row in rows:
            ablated_row_score = _english_ablated_row_score(row)
            if (
                row.counts_for_independence
                and row.original_language_evidence_remains
                and ablated_row_score is not None
                and ablated_row_score >= threshold
            ):
                original.add(row.independence_group)
        original_families = {
            row.family
            for row in rows
            if row.independence_group in original
            and row.counts_for_independence
            and row.original_language_evidence_remains
        }
        status, relationship_ids = _recomputed_knownness(left, right, rows, knownness)
        if effective_ablated_null is None:
            ablated_p_value = 1.0
            ablated_fdr = 1.0
            ablated_sufficient = False
        else:
            ablated_null = effective_ablated_null.get(pair_id)
            if ablated_null is None:
                continue
            ablated_p_value = ablated_null.empirical_p_value
            ablated_fdr = ablated_null.empirical_fdr
            ablated_sufficient = ablated_null.stratum_sufficient_for_bh
        drafts.append(
            _ScientificDraft(
                pair_id=pair_id,
                passage_a=left,
                passage_b=right,
                evidence=rows,
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
                quality=_recomputed_quality(left, right, rows),
                qualifying_groups=tuple(sorted(qualifying)),
                original_groups=tuple(sorted(original)),
                original_families=tuple(sorted(original_families)),
                contains_english=any(row.contains_english_derived_evidence for row in rows),
            )
        )
    return tuple(drafts)


def _quality_is_eligible(draft: _ScientificDraft, config: FinalDiscoveryConfig) -> bool:
    return not draft.quality.basic_exclusion and not any(
        bool(getattr(draft.quality, flag)) for flag in config.tiers.tier_a_quality_exclusions
    )


def _english_ablation_survives(
    draft: _ScientificDraft,
    ablated_q_value: float,
    config: FinalDiscoveryConfig,
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
    draft: _ScientificDraft,
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


def _compare_value(
    findings: list[ValidationFinding],
    *,
    code: str,
    field: str,
    observed: object,
    expected: object,
    pair_id: str,
) -> None:
    equal = (
        _close(observed, expected)
        if isinstance(observed, float) and isinstance(expected, float)
        else observed == expected
    )
    if not equal:
        _finding(
            findings,
            code,
            f"stored {field}={observed!r} differs from recomputed {expected!r}",
            pair_id,
        )


def _validate_scientific_candidates(
    candidates: Sequence[FinalCandidate],
    drafts: Sequence[_ScientificDraft],
    *,
    config: FinalDiscoveryConfig,
    findings: list[ValidationFinding],
) -> None:
    q_values = benjamini_hochberg([draft.empirical_p_value for draft in drafts])
    ablated_q_values = benjamini_hochberg(
        [draft.english_ablation_empirical_p_value for draft in drafts]
    )
    q_by_pair = {draft.pair_id: q_value for draft, q_value in zip(drafts, q_values, strict=True)}
    ablated_q_by_pair = {
        draft.pair_id: q_value for draft, q_value in zip(drafts, ablated_q_values, strict=True)
    }
    survival_by_pair = {
        draft.pair_id: _english_ablation_survives(draft, ablated_q_by_pair[draft.pair_id], config)
        for draft in drafts
    }
    reasons_by_pair = {
        draft.pair_id: _exclusion_reasons(
            draft,
            q_by_pair[draft.pair_id],
            survival_by_pair[draft.pair_id],
            config,
        )
        for draft in drafts
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
    expected_tier_b_size = min(config.tiers.tier_b_size, len(tier_b_pool))
    observed_tier_b_ids = {
        candidate.candidate_pair_id for candidate in candidates if candidate.tier_b_rank is not None
    }
    if len(observed_tier_b_ids) != expected_tier_b_size:
        _finding(
            findings,
            "tier-b-exact-size",
            f"Tier B has {len(observed_tier_b_ids)} rows; expected {expected_tier_b_size}",
        )
    expected_order = tuple(
        draft.pair_id
        for draft in sorted(
            drafts,
            key=lambda item: (-item.ensemble_score, item.pair_id),
        )
    )
    observed_order = tuple(candidate.candidate_pair_id for candidate in candidates)
    if observed_order != expected_order:
        _finding(
            findings,
            "candidate-output-order",
            "candidate ledger is not sorted by descending score and stable pair ID",
        )
    candidate_by_pair = {candidate.candidate_pair_id: candidate for candidate in candidates}
    for draft in drafts:
        candidate = candidate_by_pair.get(draft.pair_id)
        if candidate is None:
            continue
        expected_pair_id = candidate_pair_id(draft.passage_a.passage_id, draft.passage_b.passage_id)
        comparisons = (
            ("candidate-id", "candidate_pair_id", candidate.candidate_pair_id, expected_pair_id),
            (
                "candidate-passage",
                "passage_a_id",
                candidate.passage_a_id,
                draft.passage_a.passage_id,
            ),
            (
                "candidate-passage",
                "passage_b_id",
                candidate.passage_b_id,
                draft.passage_b.passage_id,
            ),
            (
                "candidate-reference",
                "passage_a_reference",
                candidate.passage_a_reference,
                draft.passage_a.reference,
            ),
            (
                "candidate-reference",
                "passage_b_reference",
                candidate.passage_b_reference,
                draft.passage_b.reference,
            ),
            ("ensemble-score", "ensemble_score", candidate.ensemble_score, draft.ensemble_score),
            (
                "full-null-candidate-values",
                "empirical_p_value",
                candidate.empirical_p_value,
                draft.empirical_p_value,
            ),
            ("bh-reconciliation", "bh_q_value", candidate.bh_q_value, q_by_pair[draft.pair_id]),
            (
                "full-null-candidate-values",
                "empirical_fdr",
                candidate.empirical_fdr,
                draft.empirical_fdr,
            ),
            (
                "knownness-reconciliation",
                "knownness_status",
                candidate.knownness_status,
                draft.knownness_status,
            ),
            (
                "knownness-reconciliation",
                "known_relationship_ids",
                candidate.known_relationship_ids,
                draft.known_relationship_ids,
            ),
            ("quality-reconciliation", "quality", candidate.quality, draft.quality),
            (
                "evidence-trace",
                "evidence_ids",
                candidate.evidence_ids,
                tuple(row.evidence_id for row in draft.evidence),
            ),
            (
                "detector-summary",
                "detector_ids",
                candidate.detector_ids,
                tuple(sorted({row.detector_id for row in draft.evidence})),
            ),
            (
                "family-summary",
                "families",
                candidate.families,
                tuple(sorted({row.family for row in draft.evidence})),
            ),
            (
                "qualifying-group-reconciliation",
                "qualifying_independence_groups",
                candidate.qualifying_independence_groups,
                draft.qualifying_groups,
            ),
            (
                "original-group-reconciliation",
                "original_language_independence_groups",
                candidate.original_language_independence_groups,
                draft.original_groups,
            ),
            (
                "english-evidence-reconciliation",
                "contains_english_derived_evidence",
                candidate.contains_english_derived_evidence,
                draft.contains_english,
            ),
            (
                "english-ablation-score",
                "score_without_english",
                candidate.score_without_english,
                draft.score_without_english,
            ),
            (
                "english-ablation-null-candidate-values",
                "english_ablation_empirical_p_value",
                candidate.english_ablation_empirical_p_value,
                draft.english_ablation_empirical_p_value,
            ),
            (
                "english-ablation-bh-reconciliation",
                "english_ablation_bh_q_value",
                candidate.english_ablation_bh_q_value,
                ablated_q_by_pair[draft.pair_id],
            ),
            (
                "english-ablation-null-candidate-values",
                "english_ablation_empirical_fdr",
                candidate.english_ablation_empirical_fdr,
                draft.english_ablation_empirical_fdr,
            ),
            (
                "english-ablation-survival",
                "english_ablation_survives",
                candidate.english_ablation_survives,
                survival_by_pair[draft.pair_id],
            ),
            (
                "tier-a-reconciliation",
                "tier_a_eligible",
                candidate.tier_a_eligible,
                draft.pair_id in tier_a_ids,
            ),
            (
                "tier-a-exclusion-reasons",
                "tier_a_exclusion_reasons",
                candidate.tier_a_exclusion_reasons,
                reasons_by_pair[draft.pair_id],
            ),
            (
                "tier-b-exact-membership",
                "tier_b_rank",
                candidate.tier_b_rank,
                tier_b_ranks.get(draft.pair_id),
            ),
        )
        for code, field, observed, expected in comparisons:
            _compare_value(
                findings,
                code=code,
                field=field,
                observed=observed,
                expected=expected,
                pair_id=draft.pair_id,
            )
        expected_label = (
            "statistically_eligible"
            if draft.pair_id in tier_a_ids
            else "exploratory_not_statistically_accepted"
            if draft.pair_id in tier_b_ranks
            else "retained_excluded"
        )
        _compare_value(
            findings,
            code="output-label-reconciliation",
            field="output_label",
            observed=candidate.output_label,
            expected=expected_label,
            pair_id=draft.pair_id,
        )


def _validate_stage_store(
    store: StageStore | None,
    *,
    require_all_stages: bool,
    findings: list[ValidationFinding],
) -> int:
    if store is None:
        if require_all_stages:
            _finding(findings, "stage-store-missing", "all-stage authentication was requested")
        return 0
    if require_all_stages:
        try:
            completions = store.authenticate_all_completions()
        except StageStoreError as exc:
            _finding(
                findings,
                "stage-authentication",
                f"the full stage graph is not authenticated: {exc}",
            )
            return 0
        if len(completions) != 11:
            _finding(
                findings,
                "stage-count",
                f"expected 11 authenticated stages, found {len(completions)}",
            )
        return len(completions)
    authenticated = 0
    for stage_id in FINAL_DISCOVERY_STAGE_IDS:
        try:
            store.authenticate_completion(stage_id)
        except StageStoreError as exc:
            if require_all_stages:
                _finding(
                    findings,
                    "stage-authentication",
                    f"stage {stage_id} is not authenticated: {exc}",
                )
            break
        authenticated += 1
    return authenticated


def validate_final_discovery(
    evidence: Sequence[EvidenceRow],
    candidates: Sequence[FinalCandidate],
    *,
    config: FinalDiscoveryConfig,
    stage_store: StageStore | None = None,
    require_all_stages: bool = False,
    passages: Mapping[str, PassageRecord] | None = None,
    knownness: KnownnessIndex | None = None,
    null_calibration_by_pair: NullCalibrationInput | None = None,
    english_ablation_null_calibration_by_pair: NullCalibrationInput | None = None,
    expected_source_artifact_sha256: Mapping[str, str] | None = None,
) -> FinalDiscoveryValidationReport:
    """Validate traceability, tier labels, statistical controls, and checkpoints.

    Supplying passages, knownness, and the full ensemble-null ledger enables the
    independent scientific-contract audit. The English-ablation ledger is also
    required whenever retained evidence contains an English-derived row. Omitting
    all of those optional inputs preserves the lightweight fixture API.
    """

    findings: list[ValidationFinding] = []
    try:
        assert_stage_registrations(cast(Sequence[StageRegistrationLike], config.stages))
    except ValueError as exc:
        _finding(findings, "stage-registration", str(exc))
    scientific_inputs = (
        passages,
        knownness,
        null_calibration_by_pair,
    )
    strict_requested = any(value is not None for value in scientific_inputs)
    strict_ready = all(value is not None for value in scientific_inputs)
    if strict_requested and not strict_ready:
        missing = tuple(
            name
            for name, value in zip(
                ("passages", "knownness", "null_calibration_by_pair"),
                scientific_inputs,
                strict=True,
            )
            if value is None
        )
        _finding(
            findings,
            "scientific-validation-inputs-incomplete",
            f"strict scientific validation requires all core inputs; missing={missing}",
        )
    evidence_by_id, evidence_by_pair = _validate_evidence_contract(
        evidence,
        config=config,
        strict_lineage=(strict_requested or expected_source_artifact_sha256 is not None),
        expected_source_artifact_sha256=expected_source_artifact_sha256,
        findings=findings,
    )
    candidate_ids = [row.candidate_pair_id for row in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        _finding(findings, "duplicate-candidate-id", "candidate IDs are not unique")
    for candidate in candidates:
        expected_candidate_id = candidate_pair_id(candidate.passage_a_id, candidate.passage_b_id)
        if candidate.candidate_pair_id != expected_candidate_id:
            _finding(
                findings,
                "candidate-id",
                "candidate-pair ID does not match the persisted passage identity",
                candidate.candidate_pair_id,
            )
    q_values = benjamini_hochberg([candidate.empirical_p_value for candidate in candidates])
    for candidate, recomputed_q in zip(candidates, q_values, strict=True):
        pair_rows = evidence_by_pair.get(candidate.candidate_pair_id, [])
        expected_ids = {row.evidence_id for row in pair_rows}
        if set(candidate.evidence_ids) != expected_ids:
            _finding(
                findings,
                "evidence-trace",
                "candidate evidence IDs do not match the retained pair evidence",
                candidate.candidate_pair_id,
            )
        for evidence_id_value in candidate.evidence_ids:
            traced = evidence_by_id.get(evidence_id_value)
            if traced is None or (
                traced.passage_a_id != candidate.passage_a_id
                or traced.passage_b_id != candidate.passage_b_id
            ):
                _finding(
                    findings,
                    "passage-trace",
                    f"evidence {evidence_id_value} does not trace to candidate passages",
                    candidate.candidate_pair_id,
                )
        if not math.isclose(candidate.bh_q_value, recomputed_q, abs_tol=1e-12):
            _finding(
                findings,
                "bh-reconciliation",
                f"stored q={candidate.bh_q_value} differs from recomputed q={recomputed_q}",
                candidate.candidate_pair_id,
            )
        qualifying_family_by_group = {
            row.independence_group: row.family
            for row in pair_rows
            if row.independence_group in candidate.original_language_independence_groups
            and row.counts_for_independence
            and row.original_language_evidence_remains
            and row.normalized_score >= config.ensemble.qualifying_group_normalized_score
        }
        if candidate.tier_a_eligible:
            if candidate.knownness_status != "unknown":
                _finding(
                    findings,
                    "tier-a-knownness",
                    "known relationship was labeled Tier A",
                    candidate.candidate_pair_id,
                )
            if len(set(qualifying_family_by_group.values())) < (
                config.calibration.minimum_independent_families
            ):
                _finding(
                    findings,
                    "tier-a-independence",
                    "Tier A candidate lacks two independent original-language families",
                    candidate.candidate_pair_id,
                )
            if candidate.bh_q_value > config.calibration.maximum_bh_q_value:
                _finding(
                    findings,
                    "tier-a-q-value",
                    "Tier A candidate exceeds the frozen BH limit",
                    candidate.candidate_pair_id,
                )
            if candidate.empirical_fdr > config.calibration.maximum_empirical_fdr:
                _finding(
                    findings,
                    "tier-a-fdr",
                    "Tier A candidate exceeds the frozen empirical-FDR limit",
                    candidate.candidate_pair_id,
                )
            if candidate.contains_english_derived_evidence and not (
                candidate.english_ablation_survives
            ):
                _finding(
                    findings,
                    "tier-a-english-ablation",
                    "Tier A candidate fails remove-all-English ablation",
                    candidate.candidate_pair_id,
                )
    tier_a = [candidate for candidate in candidates if candidate.tier_a_eligible]
    tier_b = [candidate for candidate in candidates if candidate.tier_b_rank is not None]
    if {item.candidate_pair_id for item in tier_a} & {item.candidate_pair_id for item in tier_b}:
        _finding(findings, "tier-overlap", "Tier A and Tier B are not disjoint")
    observed_tier_b_ranks = sorted(
        candidate.tier_b_rank for candidate in tier_b if candidate.tier_b_rank is not None
    )
    if observed_tier_b_ranks != list(range(1, len(tier_b) + 1)):
        _finding(findings, "tier-b-ranks", "Tier B ranks are not contiguous from one")
    if len(tier_b) > config.tiers.tier_b_size:
        _finding(findings, "tier-b-size", "Tier B exceeds the preregistered top-100 cap")
    for candidate in tier_b:
        if candidate.knownness_status != "unknown" or candidate.tier_a_eligible:
            _finding(
                findings,
                "tier-b-eligibility",
                "Tier B must contain unknown, non-Tier-A candidates only",
                candidate.candidate_pair_id,
            )
    if strict_ready:
        assert passages is not None
        assert knownness is not None
        assert null_calibration_by_pair is not None
        evidence_pair_ids = set(evidence_by_pair)
        if set(candidate_ids) != evidence_pair_ids:
            missing_pairs = sorted(evidence_pair_ids - set(candidate_ids))
            extra_pairs = sorted(set(candidate_ids) - evidence_pair_ids)
            _finding(
                findings,
                "candidate-population",
                (
                    "candidate/evidence population mismatch; "
                    f"missing={missing_pairs[:3]}, extra={extra_pairs[:3]}"
                ),
            )
        full_null = _index_null_calibration(
            null_calibration_by_pair,
            scope_name="full",
            findings=findings,
        )
        full_scores = {
            pair_id: _weighted_score(_group_scores(pair_rows, remove_all_english=False), config)
            for pair_id, pair_rows in evidence_by_pair.items()
        }
        ablated_scores = {
            pair_id: _weighted_score(_group_scores(pair_rows, remove_all_english=True), config)
            for pair_id, pair_rows in evidence_by_pair.items()
        }
        _validate_null_calibration_rows(
            full_null,
            full_scores,
            scope="full",
            config=config,
            findings=findings,
        )
        ablated_null: dict[str, EnsembleNullCalibrationRow] | None = None
        if english_ablation_null_calibration_by_pair is not None:
            ablated_null = _index_null_calibration(
                english_ablation_null_calibration_by_pair,
                scope_name="english-ablation",
                findings=findings,
            )
            _validate_null_calibration_rows(
                ablated_null,
                ablated_scores,
                scope="remove_all_english",
                config=config,
                findings=findings,
            )
        elif any(row.contains_english_derived_evidence for row in evidence):
            _finding(
                findings,
                "english-ablation-null-missing",
                "English-derived evidence requires a complete remove-all-English null ledger",
            )
        drafts = _build_scientific_drafts(
            evidence_by_pair,
            passages,
            knownness,
            full_null,
            ablated_null,
            config=config,
            findings=findings,
        )
        if (
            len(drafts) == len(evidence_pair_ids)
            and len(candidate_ids) == len(set(candidate_ids))
            and set(candidate_ids) == evidence_pair_ids
        ):
            _validate_scientific_candidates(
                candidates,
                drafts,
                config=config,
                findings=findings,
            )
    authenticated_stages = _validate_stage_store(
        stage_store,
        require_all_stages=require_all_stages,
        findings=findings,
    )
    return FinalDiscoveryValidationReport(
        experiment_id=config.experiment_id,
        evidence_count=len(evidence),
        candidate_count=len(candidates),
        tier_a_count=len(tier_a),
        tier_b_count=len(tier_b),
        authenticated_stage_count=authenticated_stages,
        findings=tuple(findings),
    )
