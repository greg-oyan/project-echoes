"""Deterministic, traceable review exports for ``final-discovery-v1``.

The review bundle is deliberately a persistent research artifact rather than a
public application.  It retains every candidate state, keeps statistically
eligible Tier A separate from exploratory Tier B, and makes English-derived
evidence visibly supplemental in every machine-readable record.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from echoes.final_discovery.models import (
    EvidenceRow,
    FinalCandidate,
    PassageRecord,
    ReviewClassification,
    ReviewRecord,
)
from echoes.final_discovery.nulls import EnsembleNullThresholdReport

REVIEW_SCHEMA_VERSION: Final = "final-discovery-review-v1"
STREAMING_REVIEW_SCHEMA_VERSION: Final = "final-discovery-review-stream-v2"
OUTPUT_J_PLACEHOLDER: Final = "[COMPLETE AFTER THE GOVERNED PRODUCTION REVIEW]"
ENGLISH_SUPPLEMENTAL_LABEL: Final = (
    "supplemental English-derived evidence; never an independent original-language family"
)
REVIEW_COLUMNS: Final[tuple[str, ...]] = (
    "candidate_pair_id",
    "output_label",
    "tier_b_rank",
    "passage_a_id",
    "passage_b_id",
    "passage_a_reference",
    "passage_b_reference",
    "passage_a_original_text",
    "passage_b_original_text",
    "passage_a_normalized_text",
    "passage_b_normalized_text",
    "passage_a_english_gloss",
    "passage_b_english_gloss",
    "ensemble_score",
    "knownness_status",
    "detector_contributions_json",
    "original_language_evidence_json",
    "supplemental_gloss_evidence_json",
    "null_fdr_status_json",
    "ablation_status_json",
    "quality_flags_json",
    "reviewer_classification",
    "rejection_category",
    "reviewer_notes",
)
_MUTABLE_REVIEW_FIELDS: Final = {
    "reviewer_classification",
    "rejection_category",
    "reviewer_notes",
}
_REVIEW_SCHEMA: Final = pl.Schema(
    {
        "candidate_pair_id": pl.String,
        "output_label": pl.String,
        "tier_b_rank": pl.Int64,
        "passage_a_id": pl.String,
        "passage_b_id": pl.String,
        "passage_a_reference": pl.String,
        "passage_b_reference": pl.String,
        "passage_a_original_text": pl.String,
        "passage_b_original_text": pl.String,
        "passage_a_normalized_text": pl.String,
        "passage_b_normalized_text": pl.String,
        "passage_a_english_gloss": pl.String,
        "passage_b_english_gloss": pl.String,
        "ensemble_score": pl.Float64,
        "knownness_status": pl.String,
        "detector_contributions_json": pl.String,
        "original_language_evidence_json": pl.String,
        "supplemental_gloss_evidence_json": pl.String,
        "null_fdr_status_json": pl.String,
        "ablation_status_json": pl.String,
        "quality_flags_json": pl.String,
        "reviewer_classification": pl.String,
        "rejection_category": pl.String,
        "reviewer_notes": pl.String,
    }
)
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class ReviewTraceabilityError(ValueError):
    """Raised when candidate, evidence, and review records do not join exactly."""


class ReviewOutputError(RuntimeError):
    """Raised when a review bundle cannot be published atomically."""


@dataclass(frozen=True, slots=True)
class ReviewArtifacts:
    """Paths and counts for one atomically published review bundle."""

    output_directory: Path
    csv_path: Path
    parquet_path: Path
    manifest_path: Path
    output_j_path: Path
    dossier_paths: tuple[Path, ...]
    candidate_count: int
    evidence_count: int
    tier_a_count: int
    tier_b_count: int
    tier_a_dossier_count: int
    tier_b_dossier_count: int
    actual_reviewed_count: int
    retained_excluded_count: int


@dataclass(frozen=True, slots=True)
class StreamingReviewSummary:
    """Authenticated population summary from the bounded-memory exporter."""

    candidate_count: int
    evidence_count: int
    tier_a_count: int
    tier_b_count: int
    tier_a_dossier_count: int
    tier_b_dossier_count: int
    actual_reviewed_count: int
    retained_excluded_count: int
    candidate_stream_sha256: str
    evidence_stream_sha256: str
    review_stream_sha256: str


@dataclass(frozen=True, slots=True)
class StreamingReviewArtifacts:
    """Paths and bounded summary for one streamed review bundle."""

    output_directory: Path
    csv_path: Path
    parquet_path: Path
    manifest_path: Path
    output_j_path: Path
    dossier_directory: Path
    summary: StreamingReviewSummary


type CandidateEvidenceLookup = Callable[[FinalCandidate], Iterable[EvidenceRow]]
type SelectedEvidencePreparer = Callable[
    [FinalCandidate, tuple[EvidenceRow, ...]], Iterable[EvidenceRow]
]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parsed_json_object(value: str, *, field: str, identity: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ReviewTraceabilityError(
            f"{field} for {identity} is not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ReviewTraceabilityError(f"{field} for {identity} must be a JSON object")
    return parsed


def _selection_key(candidate: FinalCandidate) -> tuple[int, int, float, str]:
    if candidate.tier_a_eligible:
        return (0, 0, -candidate.ensemble_score, candidate.candidate_pair_id)
    if candidate.tier_b_rank is not None:
        return (1, candidate.tier_b_rank, -candidate.ensemble_score, candidate.candidate_pair_id)
    return (2, 0, -candidate.ensemble_score, candidate.candidate_pair_id)


def iter_bounded_dossier_candidates(
    candidates: Iterable[FinalCandidate],
    *,
    tier_a_dossier_limit: int,
) -> Iterator[FinalCandidate]:
    """Yield the frozen dossier selection without retaining the Tier A population."""

    if tier_a_dossier_limit < 1:
        raise ValueError("tier_a_dossier_limit must be positive")
    tier_a_seen = 0
    for candidate in candidates:
        if candidate.tier_a_eligible:
            tier_a_seen += 1
            if tier_a_seen <= tier_a_dossier_limit:
                yield candidate
        elif candidate.tier_b_rank is not None:
            yield candidate


def _evidence_key(row: EvidenceRow) -> tuple[str, str, str]:
    return (row.family, row.detector_id, row.evidence_id)


def _unique_by_id[T](
    rows: Sequence[T], *, identity: str, get_id: Callable[[T], str]
) -> dict[str, T]:
    result: dict[str, T] = {}
    for row in rows:
        value = get_id(row)
        if value in result:
            raise ReviewTraceabilityError(f"duplicate {identity}: {value}")
        result[value] = row
    return result


def _validated_indexes(
    candidates: Sequence[FinalCandidate],
    evidence: Sequence[EvidenceRow],
    *,
    require_complete_tier_b_ranking: bool = True,
) -> tuple[dict[str, FinalCandidate], dict[str, EvidenceRow]]:
    candidate_by_id = _unique_by_id(
        candidates,
        identity="candidate_pair_id",
        get_id=lambda row: row.candidate_pair_id,
    )
    evidence_by_id = _unique_by_id(
        evidence,
        identity="evidence_id",
        get_id=lambda row: row.evidence_id,
    )

    if require_complete_tier_b_ranking:
        tier_b_ranks = sorted(
            candidate.tier_b_rank for candidate in candidates if candidate.tier_b_rank is not None
        )
        if tier_b_ranks != list(range(1, len(tier_b_ranks) + 1)):
            raise ReviewTraceabilityError("Tier B ranks must be unique and contiguous from one")

    referenced_evidence: list[str] = []
    for candidate in candidates:
        if (candidate.output_label == "exploratory_not_statistically_accepted") != (
            candidate.tier_b_rank is not None
        ):
            raise ReviewTraceabilityError(
                f"candidate {candidate.candidate_pair_id} has an ambiguous Tier B label/rank"
            )
        if candidate.output_label == "retained_excluded" and candidate.tier_a_eligible:
            raise ReviewTraceabilityError(
                f"candidate {candidate.candidate_pair_id} is both retained-excluded and Tier A"
            )
        if len(candidate.known_relationship_ids) != len(set(candidate.known_relationship_ids)):
            raise ReviewTraceabilityError(
                f"candidate {candidate.candidate_pair_id} repeats known-relationship IDs"
            )

        rows: list[EvidenceRow] = []
        for evidence_id in candidate.evidence_ids:
            try:
                row = evidence_by_id[evidence_id]
            except KeyError as exc:
                raise ReviewTraceabilityError(
                    f"candidate {candidate.candidate_pair_id} references missing evidence "
                    f"{evidence_id}"
                ) from exc
            if row.candidate_pair_id != candidate.candidate_pair_id:
                raise ReviewTraceabilityError(
                    f"evidence {evidence_id} points to {row.candidate_pair_id}, not "
                    f"{candidate.candidate_pair_id}"
                )
            if (row.passage_a_id, row.passage_b_id) != (
                candidate.passage_a_id,
                candidate.passage_b_id,
            ):
                raise ReviewTraceabilityError(
                    f"evidence {evidence_id} passage IDs disagree with its candidate"
                )
            _parsed_json_object(row.trace_json, field="trace_json", identity=evidence_id)
            rows.append(row)
        referenced_evidence.extend(candidate.evidence_ids)

        actual_detectors = tuple(sorted({row.detector_id for row in rows}))
        if candidate.detector_ids != actual_detectors:
            raise ReviewTraceabilityError(
                f"candidate {candidate.candidate_pair_id} detector IDs do not exactly "
                "match evidence"
            )
        actual_families = tuple(sorted({row.family for row in rows}))
        if candidate.families != actual_families:
            raise ReviewTraceabilityError(
                f"candidate {candidate.candidate_pair_id} families do not exactly match evidence"
            )
        contains_english = any(row.contains_english_derived_evidence for row in rows)
        if candidate.contains_english_derived_evidence != contains_english:
            raise ReviewTraceabilityError(
                f"candidate {candidate.candidate_pair_id} English-evidence flag is stale"
            )
        independence_backing = {
            row.independence_group for row in rows if row.counts_for_independence
        }
        if set(candidate.qualifying_independence_groups) - independence_backing:
            raise ReviewTraceabilityError(
                f"candidate {candidate.candidate_pair_id} has an unbacked independence group"
            )
        original_backing = {
            row.independence_group
            for row in rows
            if row.counts_for_independence and row.original_language_evidence_remains
        }
        if set(candidate.original_language_independence_groups) - original_backing:
            raise ReviewTraceabilityError(
                f"candidate {candidate.candidate_pair_id} has an unbacked original-language group"
            )

    if len(referenced_evidence) != len(set(referenced_evidence)):
        raise ReviewTraceabilityError("an evidence row is referenced by more than one candidate")
    referenced_ids = set(referenced_evidence)
    supplied_ids = set(evidence_by_id)
    if referenced_ids != supplied_ids:
        missing = sorted(supplied_ids - referenced_ids)
        raise ReviewTraceabilityError(
            "supplied evidence must be consumed exactly once; orphan evidence IDs: "
            + ", ".join(missing)
        )
    return candidate_by_id, evidence_by_id


def _trace_projection(row: EvidenceRow) -> dict[str, object]:
    return {
        "evidence_id": row.evidence_id,
        "detector_id": row.detector_id,
        "family": row.family,
        "independence_group": row.independence_group,
        "raw_score": row.raw_score,
        "normalized_score": row.normalized_score,
        "english_ablation_normalized_score": row.english_ablation_normalized_score,
        "normalization_method": row.normalization_method,
        "empirical_p_value": row.empirical_p_value,
        "null_method": row.null_method,
        "contains_english_derived_evidence": row.contains_english_derived_evidence,
        "original_language_evidence_remains": row.original_language_evidence_remains,
        "counts_for_independence": row.counts_for_independence,
        "source_artifact_id": row.source_artifact_id,
        "source_artifact_sha256": row.source_artifact_sha256,
        "source_quality": (
            row.source_quality.model_dump(mode="json") if row.source_quality is not None else None
        ),
        "source_knownness_status": row.source_knownness_status,
        "source_known_relationship_ids": row.source_known_relationship_ids,
        "trace": _parsed_json_object(
            row.trace_json,
            field="trace_json",
            identity=row.evidence_id,
        ),
    }


def _review_record(
    candidate: FinalCandidate,
    rows: Sequence[EvidenceRow],
    passages: Mapping[str, PassageRecord],
    *,
    prior: ReviewRecord | None = None,
) -> ReviewRecord:
    try:
        passage_a = passages[candidate.passage_a_id]
        passage_b = passages[candidate.passage_b_id]
    except KeyError as exc:
        raise ReviewTraceabilityError(
            f"review candidate references a missing passage: {exc}"
        ) from exc
    if (
        passage_a.reference != candidate.passage_a_reference
        or passage_b.reference != candidate.passage_b_reference
    ):
        raise ReviewTraceabilityError(
            f"review candidate {candidate.candidate_pair_id} passage references are stale"
        )
    ordered_rows = tuple(sorted(rows, key=_evidence_key))
    projections = tuple(_trace_projection(row) for row in ordered_rows)
    original = tuple(
        projection
        for projection, row in zip(projections, ordered_rows, strict=True)
        if row.original_language_evidence_remains
    )
    supplemental = tuple(
        projection
        for projection, row in zip(projections, ordered_rows, strict=True)
        if row.contains_english_derived_evidence
    )
    if candidate.tier_a_eligible:
        tier = "tier_a_statistically_eligible"
    elif candidate.tier_b_rank is not None:
        tier = "tier_b_exploratory_not_statistically_accepted"
    else:
        tier = "retained_excluded"

    return ReviewRecord(
        candidate_pair_id=candidate.candidate_pair_id,
        output_label=candidate.output_label,
        tier_b_rank=candidate.tier_b_rank,
        passage_a_id=candidate.passage_a_id,
        passage_b_id=candidate.passage_b_id,
        passage_a_reference=candidate.passage_a_reference,
        passage_b_reference=candidate.passage_b_reference,
        passage_a_original_text=passage_a.original_text,
        passage_b_original_text=passage_b.original_text,
        passage_a_normalized_text=passage_a.normalized_text,
        passage_b_normalized_text=passage_b.normalized_text,
        passage_a_english_gloss=passage_a.english_gloss or "",
        passage_b_english_gloss=passage_b.english_gloss or "",
        ensemble_score=candidate.ensemble_score,
        knownness_status=candidate.knownness_status,
        detector_contributions_json=_canonical_json(
            {
                "candidate_pair_id": candidate.candidate_pair_id,
                "passage_a_id": candidate.passage_a_id,
                "passage_b_id": candidate.passage_b_id,
                "detector_ids": candidate.detector_ids,
                "families": candidate.families,
                "evidence": projections,
            }
        ),
        original_language_evidence_json=_canonical_json(
            {
                "label": "original-language evidence",
                "qualifying_independence_groups": (candidate.original_language_independence_groups),
                "evidence": original,
            }
        ),
        supplemental_gloss_evidence_json=_canonical_json(
            {
                "label": ENGLISH_SUPPLEMENTAL_LABEL,
                "present": candidate.contains_english_derived_evidence,
                "counts_as_an_independent_original_language_family": False,
                "evidence": supplemental,
            }
        ),
        null_fdr_status_json=_canonical_json(
            {
                "selection_tier": tier,
                "candidate_empirical_p_value": candidate.empirical_p_value,
                "benjamini_hochberg_q_value": candidate.bh_q_value,
                "empirical_fdr": candidate.empirical_fdr,
                "tier_a_eligible": candidate.tier_a_eligible,
                "tier_a_exclusion_reasons": candidate.tier_a_exclusion_reasons,
                "knownness": {
                    "status": candidate.knownness_status,
                    "relationship_ids": candidate.known_relationship_ids,
                    "checked_both_directions": True,
                },
            }
        ),
        ablation_status_json=_canonical_json(
            {
                "policy": "remove all English-derived features",
                "required": candidate.contains_english_derived_evidence,
                "score_with_all_features": candidate.ensemble_score,
                "score_without_all_english_derived_features": (candidate.score_without_english),
                "english_removed_empirical_p_value": (candidate.english_ablation_empirical_p_value),
                "english_removed_benjamini_hochberg_q_value": (
                    candidate.english_ablation_bh_q_value
                ),
                "english_removed_empirical_fdr": candidate.english_ablation_empirical_fdr,
                "survives": candidate.english_ablation_survives,
                "original_language_evidence_remains": bool(original),
            }
        ),
        quality_flags_json=_canonical_json(
            {
                **candidate.quality.model_dump(mode="json"),
                "basic_exclusion": candidate.quality.basic_exclusion,
            }
        ),
        reviewer_classification=(
            prior.reviewer_classification
            if prior is not None
            else ReviewClassification.NOT_REVIEWED
        ),
        rejection_category=prior.rejection_category if prior is not None else "",
        reviewer_notes=prior.reviewer_notes if prior is not None else "",
    )


def _assert_prior_identity(candidate: FinalCandidate, prior: ReviewRecord) -> None:
    expected = {
        "output_label": candidate.output_label,
        "tier_b_rank": candidate.tier_b_rank,
        "passage_a_reference": candidate.passage_a_reference,
        "passage_b_reference": candidate.passage_b_reference,
        "ensemble_score": candidate.ensemble_score,
        "knownness_status": candidate.knownness_status,
    }
    stale = [field for field, value in expected.items() if getattr(prior, field) != value]
    if stale:
        raise ReviewTraceabilityError(
            f"prior review for {candidate.candidate_pair_id} has stale identity fields: "
            + ", ".join(stale)
        )


def build_review_records(
    candidates: Sequence[FinalCandidate],
    evidence: Sequence[EvidenceRow],
    *,
    passages: Mapping[str, PassageRecord],
    prior_reviews: Sequence[ReviewRecord] = (),
) -> tuple[ReviewRecord, ...]:
    """Build all review rows without dropping exclusions or prior reviewer decisions."""

    candidate_by_id, evidence_by_id = _validated_indexes(candidates, evidence)
    prior_by_id = _unique_by_id(
        prior_reviews,
        identity="prior review candidate_pair_id",
        get_id=lambda row: row.candidate_pair_id,
    )
    unknown_prior_ids = set(prior_by_id) - set(candidate_by_id)
    if unknown_prior_ids:
        raise ReviewTraceabilityError(
            "prior reviews refer to absent candidates: " + ", ".join(sorted(unknown_prior_ids))
        )

    records: list[ReviewRecord] = []
    for candidate in sorted(candidates, key=_selection_key):
        prior = prior_by_id.get(candidate.candidate_pair_id)
        if prior is not None:
            _assert_prior_identity(candidate, prior)
        rows = tuple(evidence_by_id[evidence_id] for evidence_id in candidate.evidence_ids)
        records.append(_review_record(candidate, rows, passages, prior=prior))
    result = tuple(records)
    validate_review_traceability(candidates, evidence, result, passages=passages)
    return result


def validate_review_traceability(
    candidates: Sequence[FinalCandidate],
    evidence: Sequence[EvidenceRow],
    records: Sequence[ReviewRecord] | None = None,
    *,
    passages: Mapping[str, PassageRecord],
    require_complete_tier_b_ranking: bool = True,
) -> None:
    """Require exact candidate/evidence/review joins and immutable review projections.

    A complete review set must have contiguous Tier-B ranks.  A single-candidate
    dossier still authenticates its persisted global rank, but cannot establish
    contiguity for candidates that are intentionally outside that dossier.
    """

    candidate_by_id, evidence_by_id = _validated_indexes(
        candidates,
        evidence,
        require_complete_tier_b_ranking=require_complete_tier_b_ranking,
    )
    if records is None:
        return
    record_by_id = _unique_by_id(
        records,
        identity="review candidate_pair_id",
        get_id=lambda row: row.candidate_pair_id,
    )
    if set(record_by_id) != set(candidate_by_id):
        missing = sorted(set(candidate_by_id) - set(record_by_id))
        extra = sorted(set(record_by_id) - set(candidate_by_id))
        raise ReviewTraceabilityError(
            f"review rows do not exactly cover candidates; missing={missing}, extra={extra}"
        )
    for candidate_id, candidate in candidate_by_id.items():
        record = record_by_id[candidate_id]
        rows = tuple(evidence_by_id[evidence_id] for evidence_id in candidate.evidence_ids)
        expected = _review_record(candidate, rows, passages, prior=record)
        for field in REVIEW_COLUMNS:
            if field in _MUTABLE_REVIEW_FIELDS:
                continue
            if getattr(record, field) != getattr(expected, field):
                raise ReviewTraceabilityError(
                    f"review row {candidate_id} has stale traceability field {field}"
                )


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _dossier_filename(candidate_pair_id: str) -> str:
    slug = _SAFE_FILENAME.sub("-", candidate_pair_id).strip("-._") or "candidate"
    slug = slug[:72]
    digest = hashlib.sha256(candidate_pair_id.encode("utf-8")).hexdigest()[:12]
    return f"{slug}--{digest}.md"


def _review_tier(candidate: FinalCandidate) -> str:
    if candidate.tier_a_eligible:
        return "Tier A — statistically eligible; not human-accepted by that fact alone"
    if candidate.tier_b_rank is not None:
        return (
            f"Tier B rank {candidate.tier_b_rank} — exploratory; not statistically accepted, "
            "novel, or a discovery"
        )
    return "Retained excluded candidate"


def _token_identity_table(passage: PassageRecord) -> tuple[str, ...]:
    """Render the governed source-token mapping without inventing fixture IDs."""

    if not passage.token_ids:
        return ("_Source token IDs are absent from this backward-compatible synthetic fixture._",)
    lines = ["| Position | Source token ID |", "| ---: | --- |"]
    lines.extend(
        f"| {position} | `{_markdown_cell(token_id)}` |"
        for position, token_id in enumerate(passage.token_ids, start=1)
    )
    return tuple(lines)


def _assert_dossier_m7_evidence_is_hydrated(row: EvidenceRow) -> None:
    """Fail closed when a final dossier lacks exact canonical M7 detail rows."""

    if row.detector_id != "m7_lexical_rrf":
        return
    trace = _parsed_json_object(row.trace_json, field="trace_json", identity=row.evidence_id)
    if trace.get("fixture") is True:
        return
    count = trace.get("m7_shared_evidence_count")
    evidence_ids = trace.get("m7_shared_evidence_ids")
    shared = trace.get("m7_shared_evidence")
    source_candidate_id = trace.get("m7_candidate_pair_id")
    if (
        trace.get("m7_shared_evidence_hydrated") is not True
        or not isinstance(count, int)
        or count < 0
        or not isinstance(evidence_ids, list)
        or not isinstance(shared, list)
        or len(evidence_ids) != count
        or len(shared) != count
        or not isinstance(source_candidate_id, str)
        or not source_candidate_id
    ):
        raise ReviewTraceabilityError(
            f"M7 evidence {row.evidence_id} must be hydrated before dossier export"
        )
    observed_ids: list[str] = []
    for detail in shared:
        if (
            not isinstance(detail, dict)
            or detail.get("candidate_pair_id") != source_candidate_id
            or not isinstance(detail.get("evidence_id"), str)
        ):
            raise ReviewTraceabilityError(
                f"M7 evidence {row.evidence_id} has an invalid hydrated detail row"
            )
        observed_ids.append(str(detail["evidence_id"]))
    if observed_ids != evidence_ids or len(observed_ids) != len(set(observed_ids)):
        raise ReviewTraceabilityError(
            f"M7 evidence {row.evidence_id} hydrated IDs disagree with its compact index"
        )


def render_candidate_dossier(
    candidate: FinalCandidate,
    evidence: Sequence[EvidenceRow],
    review: ReviewRecord,
    *,
    passages: Mapping[str, PassageRecord],
) -> str:
    """Render a concise reproducible dossier from persisted candidate evidence."""

    validate_review_traceability(
        (candidate,),
        evidence,
        (review,),
        passages=passages,
        require_complete_tier_b_ranking=False,
    )
    evidence_by_id = {row.evidence_id: row for row in evidence}
    rows = tuple(
        sorted((evidence_by_id[item] for item in candidate.evidence_ids), key=_evidence_key)
    )
    for row in rows:
        _assert_dossier_m7_evidence_is_hydrated(row)
    passage_a = passages[candidate.passage_a_id]
    passage_b = passages[candidate.passage_b_id]
    quality = candidate.quality.model_dump(mode="json")
    lines = [
        f"# Candidate dossier: {_markdown_cell(candidate.candidate_pair_id)}",
        "",
        "> This is a reproducible computational review record. Tier status is not a claim of "
        "novelty, discovery, literary dependence, or authorial intent.",
        "",
        "## Identification",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Candidate ID | {_markdown_cell(candidate.candidate_pair_id)} |",
        f"| Passage A | {_markdown_cell(candidate.passage_a_reference)} |",
        f"| Passage B | {_markdown_cell(candidate.passage_b_reference)} |",
        f"| Passage A ID | `{_markdown_cell(candidate.passage_a_id)}` |",
        f"| Passage B ID | `{_markdown_cell(candidate.passage_b_id)}` |",
        f"| Review tier | {_markdown_cell(_review_tier(candidate))} |",
        f"| Output label | `{candidate.output_label}` |",
        f"| Ensemble score | {candidate.ensemble_score:.12g} |",
        f"| Knownness | `{candidate.knownness_status}` |",
        f"| Reviewer classification | `{review.reviewer_classification.value}` |",
        f"| Rejection category | {_markdown_cell(review.rejection_category or '—')} |",
        "",
        "## Statistical and policy controls",
        "",
        f"- Empirical p-value: `{candidate.empirical_p_value:.12g}`",
        f"- Benjamini-Hochberg q-value: `{candidate.bh_q_value:.12g}`",
        f"- Empirical FDR: `{candidate.empirical_fdr:.12g}`",
        "- Qualifying independence groups: "
        + (", ".join(f"`{item}`" for item in candidate.qualifying_independence_groups) or "none"),
        "- Original-language independence groups: "
        + (
            ", ".join(f"`{item}`" for item in candidate.original_language_independence_groups)
            or "none"
        ),
        f"- English-derived evidence present: `{candidate.contains_english_derived_evidence}`",
        f"- Score after removing all English-derived features: "
        f"`{candidate.score_without_english:.12g}`",
        f"- English-feature ablation survives: `{candidate.english_ablation_survives}`",
        f"- English-removed empirical p-value: "
        f"`{candidate.english_ablation_empirical_p_value:.12g}`",
        f"- English-removed BH q-value: `{candidate.english_ablation_bh_q_value:.12g}`",
        f"- English-removed empirical FDR: `{candidate.english_ablation_empirical_fdr:.12g}`",
    ]
    if candidate.contains_english_derived_evidence:
        lines.extend(("", f"> English label: **{ENGLISH_SUPPLEMENTAL_LABEL}.**"))
    if candidate.tier_a_exclusion_reasons:
        lines.extend(
            (
                "",
                "Tier A exclusion reasons: "
                + ", ".join(f"`{item}`" for item in candidate.tier_a_exclusion_reasons),
            )
        )

    lines.extend(
        (
            "",
            "## Passage text",
            "",
            "### Passage A original language",
            "",
            review.passage_a_original_text,
            "",
            "### Passage B original language",
            "",
            review.passage_b_original_text,
            "",
            "### Normalized analysis forms",
            "",
            f"- A: `{_markdown_cell(review.passage_a_normalized_text)}`",
            f"- B: `{_markdown_cell(review.passage_b_normalized_text)}`",
            "",
            "### Passage A governed source-token identities",
            "",
            *_token_identity_table(passage_a),
            "",
            "### Passage B governed source-token identities",
            "",
            *_token_identity_table(passage_b),
        )
    )
    if review.passage_a_english_gloss or review.passage_b_english_gloss:
        lines.extend(
            (
                "",
                f"> **{ENGLISH_SUPPLEMENTAL_LABEL}.**",
                "",
                f"- A gloss: {_markdown_cell(review.passage_a_english_gloss or '—')}",
                f"- B gloss: {_markdown_cell(review.passage_b_english_gloss or '—')}",
            )
        )

    lines.extend(("", "## Quality flags", "", "| Flag | Value |", "| --- | --- |"))
    lines.extend(f"| `{key}` | `{value}` |" for key, value in quality.items())
    lines.extend(
        (
            "",
            "## Detector evidence",
            "",
            "| Evidence | Detector | Family | Independence group | Normalized | Empirical p | "
            "Language role | Source artifact |",
            "| --- | --- | --- | --- | ---: | ---: | --- | --- |",
        )
    )
    for row in rows:
        language_role = (
            ENGLISH_SUPPLEMENTAL_LABEL
            if row.contains_english_derived_evidence
            else "original-language/non-English-derived evidence"
        )
        if row.contains_english_derived_evidence and row.original_language_evidence_remains:
            language_role += "; original-language evidence also remains"
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{_markdown_cell(row.evidence_id)}`",
                    f"`{_markdown_cell(row.detector_id)}`",
                    f"`{row.family}`",
                    f"`{_markdown_cell(row.independence_group)}`",
                    f"{row.normalized_score:.12g}",
                    f"{row.empirical_p_value:.12g}",
                    _markdown_cell(language_role),
                    f"`{_markdown_cell(row.source_artifact_id)}` / `{row.source_artifact_sha256}`",
                )
            )
            + " |"
        )
    lines.extend(("", "## Exact detector traces", ""))
    for row in rows:
        trace = _canonical_json(
            _parsed_json_object(row.trace_json, field="trace_json", identity=row.evidence_id)
        )
        lines.extend((f"### `{_markdown_cell(row.evidence_id)}`", "", f"    {trace}", ""))
    lines.extend(("## Human review", ""))
    if review.reviewer_notes:
        lines.extend(
            "> " + line if line else ">"
            for line in review.reviewer_notes.replace("\r\n", "\n").split("\n")
        )
    else:
        lines.append(OUTPUT_J_PLACEHOLDER)
    lines.extend(("", "## Publication analysis still required", ""))
    lines.extend(
        f"- {item}: {OUTPUT_J_PLACEHOLDER}"
        for item in (
            "Exact textual features and rarity",
            "Surrounding context and genre alternative",
            "Directionality or mediation",
            "Closer alternative sources",
            "Scholarship searches and citations",
            "Strongest counterargument and falsifier",
            "Textual-variant considerations",
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def _candidate_table_row(candidate: FinalCandidate, review: ReviewRecord) -> str:
    dossier = f"dossiers/{_dossier_filename(candidate.candidate_pair_id)}"
    return (
        "| "
        + " | ".join(
            (
                f"`{_markdown_cell(candidate.candidate_pair_id)}`",
                f"{_markdown_cell(candidate.passage_a_reference)} ↔ "
                f"{_markdown_cell(candidate.passage_b_reference)}",
                f"{candidate.ensemble_score:.12g}",
                f"`{review.reviewer_classification.value}`",
                f"[dossier]({dossier})",
            )
        )
        + " |"
    )


def _candidate_table(
    candidates: Sequence[FinalCandidate], records: Mapping[str, ReviewRecord]
) -> list[str]:
    if not candidates:
        return [OUTPUT_J_PLACEHOLDER]
    lines = [
        "| Candidate | Passages | Score | Review state | Dossier |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for candidate in sorted(candidates, key=_selection_key):
        lines.append(_candidate_table_row(candidate, records[candidate.candidate_pair_id]))
    return lines


def _iter_candidate_table_lines(rows: Iterable[str], *, row_count: int) -> Iterator[str]:
    if row_count == 0:
        yield OUTPUT_J_PLACEHOLDER
        return
    yield "| Candidate | Passages | Score | Review state | Dossier |"
    yield "| --- | --- | ---: | --- | --- |"
    yield from rows


def _threshold_reporting_table(
    report: EnsembleNullThresholdReport | None,
) -> list[str]:
    """Render exact Stage-7 expected-noise summaries or a preproduction placeholder."""

    if report is None:
        return [
            OUTPUT_J_PLACEHOLDER,
            "",
            "Populate observed count, finite-sample-corrected mean null count, empirical "
            "2.5/97.5% interval, enrichment, corrected upper-tail probability, and estimated "
            "empirical FDR for both final-null scopes after production.",
        ]
    lines = [
        "The Stage 7 threshold-count vectors are retained in the authenticated null report; "
        "the table below is populated without rerunning either null scope.",
        "",
        "| Ensemble threshold | Scope | Observed | Mean null | Empirical 2.5/97.5% interval "
        "| Enrichment | Upper-tail probability | Estimated empirical FDR |",
        "| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for summary in report.summaries:
        enrichment = (
            "not estimable"
            if summary.observed_to_null_enrichment is None
            else f"{summary.observed_to_null_enrichment:.12g}"
        )
        empirical_fdr = (
            "not estimable"
            if summary.estimated_empirical_fdr is None
            else f"{summary.estimated_empirical_fdr:.12g}"
        )
        lines.append(
            f"| {summary.score_threshold:.12g} | `{summary.calibration_scope}` | "
            f"{summary.observed_discovery_count} | {summary.mean_null_discovery_count:.12g} | "
            f"[{summary.empirical_interval_2_5_percentile:.12g}, "
            f"{summary.empirical_interval_97_5_percentile:.12g}] | {enrichment} | "
            f"{summary.empirical_upper_tail_probability:.12g} | {empirical_fdr} |"
        )
    lines.extend(
        (
            "",
            "Mean null count and empirical FDR use the frozen finite-sample correction "
            "`(sum + 1) / (iterations + 1)`; interval endpoints are linear empirical "
            "quantiles of the retained per-iteration discovery counts.",
        )
    )
    return lines


def render_output_j_template(
    candidates: Sequence[FinalCandidate],
    records: Sequence[ReviewRecord],
    *,
    threshold_report: EnsembleNullThresholdReport | None = None,
    tier_a_dossier_limit: int = 100,
) -> str:
    """Render the publication Output J shell, including populated review state."""

    if tier_a_dossier_limit < 1:
        raise ValueError("tier_a_dossier_limit must be positive")
    record_by_id = {record.candidate_pair_id: record for record in records}
    if len(record_by_id) != len(records) or set(record_by_id) != {
        candidate.candidate_pair_id for candidate in candidates
    }:
        raise ReviewTraceabilityError("Output J records must cover candidate IDs exactly once")
    tier_a_complete = tuple(
        sorted(
            (candidate for candidate in candidates if candidate.tier_a_eligible),
            key=_selection_key,
        )
    )
    tier_a = tier_a_complete[:tier_a_dossier_limit]
    tier_b = tuple(
        sorted(
            (candidate for candidate in candidates if candidate.tier_b_rank is not None),
            key=_selection_key,
        )
    )
    retained = tuple(
        candidate
        for candidate in candidates
        if not candidate.tier_a_eligible and candidate.tier_b_rank is None
    )
    selected_ids = {candidate.candidate_pair_id for candidate in (*tier_a, *tier_b)}
    selected_records = tuple(record_by_id[candidate_id] for candidate_id in selected_ids)
    classifications = Counter(record.reviewer_classification.value for record in selected_records)
    rejection_categories = Counter(
        record.rejection_category.strip()
        for record in selected_records
        if record.rejection_category.strip()
    )
    return _render_output_j_from_summary(
        tier_a_total_count=len(tier_a_complete),
        tier_a=tier_a,
        tier_b=tier_b,
        retained_excluded_count=len(retained),
        review_ledger_count=len(records),
        actual_reviewed_count=sum(
            record.reviewer_classification != ReviewClassification.NOT_REVIEWED
            for record in selected_records
        ),
        record_by_id=record_by_id,
        classifications=classifications,
        rejection_categories=rejection_categories,
        threshold_report=threshold_report,
        tier_a_dossier_limit=tier_a_dossier_limit,
    )


def _iter_output_j_lines(
    *,
    tier_a_total_count: int,
    tier_a_rows: Iterable[str],
    tier_a_dossier_count: int,
    tier_b_rows: Iterable[str],
    tier_b_dossier_count: int,
    retained_excluded_count: int,
    review_ledger_count: int,
    actual_reviewed_count: int,
    classifications: Mapping[str, int],
    rejection_categories: Mapping[str, int],
    threshold_report: EnsembleNullThresholdReport | None,
    tier_a_dossier_limit: int,
) -> Iterator[str]:
    selection_count = tier_a_dossier_count + tier_b_dossier_count
    yield from (
        "# Output J — `final-discovery-v1` Bounded Tier A/Tier B Review and "
        "False-Positive Taxonomy",
        "",
        "> **Publication template.** Statistical eligibility, bounded review selection, human "
        "classification, novelty, and discovery are distinct. Complete every marked field only "
        "after the governed production review.",
        "",
        "## Artifact status",
        "",
        f"- Tier A statistically eligible candidates in the complete ledger: "
        f"**{tier_a_total_count}**",
        f"- Tier A dossier/review-selection rows (first score-ranked, cap "
        f"{tier_a_dossier_limit}): **{tier_a_dossier_count}**",
        f"- Tier B exploratory dossier/review-selection rows: **{tier_b_dossier_count}**",
        f"- Retained excluded candidates in the complete ledger: **{retained_excluded_count}**",
        f"- Complete review-ledger rows preserved in CSV/Parquet: **{review_ledger_count}**",
        f"- Bounded dossier/review-selection rows: **{selection_count}**",
        f"- Rows with completed human classification in that selection: "
        f"**{actual_reviewed_count}**",
        "- Production run ID and manifest hash: " + OUTPUT_J_PLACEHOLDER,
        "- Frozen configuration and preregistration hashes: " + OUTPUT_J_PLACEHOLDER,
        "",
        "## Candidate-selection procedure",
        "",
        "The complete Tier A ledger contains every candidate that passed the frozen statistical, "
        "independence, original-language, knownness, ablation, and quality gates. Dossiers and "
        f"Output J rows are restricted to its first {tier_a_dossier_limit} candidates in the "
        "authenticated ensemble-score-descending, candidate-ID-ascending order. Tier A candidates "
        "outside that bound remain in `review.csv`, `review.parquet`, and the Tier A ledger.",
        "",
        "Tier B is the distinct configured top-100 exploratory unknown set after basic "
        "exclusions. Every Tier B row is selected for a dossier; its rank never implies "
        "statistical acceptance, novelty, or discovery.",
        "",
        "Exact stage inputs, detector versions, and selection query: " + OUTPUT_J_PLACEHOLDER,
        "",
        "## Frozen thresholds and expected noise",
        "",
    )
    yield from _threshold_reporting_table(threshold_report)
    yield from (
        "",
        "## Tier A — bounded score-ranked dossier selection, not automatically accepted",
        "",
    )
    yield from _iter_candidate_table_lines(
        tier_a_rows,
        row_count=tier_a_dossier_count,
    )
    yield from (
        "",
        "## Tier B — exploratory top 100, not statistically accepted",
        "",
    )
    yield from _iter_candidate_table_lines(
        tier_b_rows,
        row_count=tier_b_dossier_count,
    )
    yield from (
        "",
        "## Complete ledger outside the bounded dossier selection",
        "",
        f"The complete {review_ledger_count}-row decision ledger, including "
        f"{retained_excluded_count} retained/excluded rows and any Tier A candidates beyond the "
        "dossier cap, is preserved in `review.csv` and `review.parquet`.",
        "",
        "## Human-review dispositions — bounded selection only",
        "",
        f"The counts below cover only the {selection_count} dossier/review-selection rows. They "
        "include selected rows still marked `not_reviewed` and exclude every unselected default "
        "ledger row.",
        "",
    )
    if classifications:
        yield from (
            f"- `{classification}`: {count}"
            for classification, count in sorted(classifications.items())
        )
    else:
        yield OUTPUT_J_PLACEHOLDER
    yield from ("", "## Accepted and plausible candidates", "", OUTPUT_J_PLACEHOLDER)
    yield from ("", "## Rejected candidates and false-positive categories", "")
    if rejection_categories:
        yield from (
            f"- `{category}`: {count}" for category, count in sorted(rejection_categories.items())
        )
    else:
        yield OUTPUT_J_PLACEHOLDER
    yield from (
        "",
        "## Data artifacts",
        "",
        OUTPUT_J_PLACEHOLDER,
        "",
        "## Formulaic-language effects",
        "",
        OUTPUT_J_PLACEHOLDER,
        "",
        "## Genre effects",
        "",
        OUTPUT_J_PLACEHOLDER,
        "",
        "## Common-vocabulary effects",
        "",
        OUTPUT_J_PLACEHOLDER,
        "",
        "## Lessons for scoring revisions",
        "",
        OUTPUT_J_PLACEHOLDER,
        "",
        "## Methodological limitations",
        "",
        OUTPUT_J_PLACEHOLDER,
        "",
        "This document supplements rather than replaces the complete CSV/Parquet candidate "
        "ledger, evidence traces, retained decisions, bounded dossier selection, and run "
        "manifests.",
    )


def _render_output_j_from_summary(
    *,
    tier_a_total_count: int,
    tier_a: Sequence[FinalCandidate],
    tier_b: Sequence[FinalCandidate],
    retained_excluded_count: int,
    review_ledger_count: int,
    actual_reviewed_count: int,
    record_by_id: Mapping[str, ReviewRecord],
    classifications: Mapping[str, int],
    rejection_categories: Mapping[str, int],
    threshold_report: EnsembleNullThresholdReport | None,
    tier_a_dossier_limit: int,
) -> str:
    """Render Output J from bounded counters and the dossier candidate subset."""

    return (
        "\n".join(
            _iter_output_j_lines(
                tier_a_total_count=tier_a_total_count,
                tier_a_rows=(
                    _candidate_table_row(candidate, record_by_id[candidate.candidate_pair_id])
                    for candidate in sorted(tier_a, key=_selection_key)
                ),
                tier_a_dossier_count=len(tier_a),
                tier_b_rows=(
                    _candidate_table_row(candidate, record_by_id[candidate.candidate_pair_id])
                    for candidate in sorted(tier_b, key=_selection_key)
                ),
                tier_b_dossier_count=len(tier_b),
                retained_excluded_count=retained_excluded_count,
                review_ledger_count=review_ledger_count,
                actual_reviewed_count=actual_reviewed_count,
                classifications=classifications,
                rejection_categories=rejection_categories,
                threshold_report=threshold_report,
                tier_a_dossier_limit=tier_a_dossier_limit,
            )
        ).rstrip()
        + "\n"
    )


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.writing-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_write_text_lines(path: Path, lines: Iterable[str]) -> None:
    """Write one deterministic UTF-8 line stream without retaining the document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.writing-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as handle:
            for line in lines:
                handle.write(line.encode("utf-8"))
                handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _csv_bytes(records: Sequence[ReviewRecord]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=REVIEW_COLUMNS,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for record in records:
        writer.writerow(record.model_dump(mode="json"))
    return stream.getvalue().encode("utf-8")


def _write_parquet_atomically(path: Path, records: Sequence[ReviewRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.writing-{uuid.uuid4().hex}")
    rows = [record.model_dump(mode="json") for record in records]
    frame = pl.DataFrame(rows, schema=_REVIEW_SCHEMA).select(REVIEW_COLUMNS)
    try:
        frame.write_parquet(
            temporary,
            compression="zstd",
            compression_level=3,
            statistics=True,
        )
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_parquet_from_csv_atomically(
    path: Path,
    csv_path: Path,
    *,
    row_group_size: int,
) -> None:
    """Write bounded-memory Parquet from the already ordered review CSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.writing-{uuid.uuid4().hex}")
    try:
        frame = pl.scan_csv(
            csv_path,
            schema=_REVIEW_SCHEMA,
            missing_utf8_is_empty_string=True,
            low_memory=True,
        ).select(REVIEW_COLUMNS)
        frame.sink_parquet(
            temporary,
            compression="zstd",
            compression_level=3,
            statistics=True,
            row_group_size=row_group_size,
            maintain_order=True,
        )
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _canonical_model_line(row: FinalCandidate | EvidenceRow | ReviewRecord) -> bytes:
    return (
        json.dumps(
            row.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def _combine_review_csv(partitions: Sequence[Path], output_path: Path) -> None:
    """Join headerless tier partitions into the legacy deterministic CSV order."""

    if output_path.exists():
        raise ReviewOutputError(f"refusing to replace streamed CSV: {output_path}")
    with output_path.open("xb") as output:
        output.write(_csv_bytes(()))
        for partition in partitions:
            with partition.open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())


def _hash_partition_stream(partitions: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for partition in partitions:
        with partition.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _bounded_rows(
    rows: Iterable[EvidenceRow],
    *,
    maximum: int,
    candidate_pair_id: str,
    role: str,
) -> tuple[EvidenceRow, ...]:
    result: list[EvidenceRow] = []
    for row in rows:
        result.append(row)
        if len(result) > maximum:
            raise ReviewTraceabilityError(
                f"{role} for {candidate_pair_id} exceeds the governed per-candidate bound "
                f"of {maximum}"
            )
    if not result:
        raise ReviewTraceabilityError(
            f"{role} for {candidate_pair_id} must contain at least one evidence row"
        )
    return tuple(result)


def _open_identity_database(path: Path) -> sqlite3.Connection:
    """Create an exact disk-backed uniqueness index with a bounded page cache."""

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-32768")
    connection.execute("CREATE TABLE candidate_ids (identity TEXT PRIMARY KEY) WITHOUT ROWID")
    connection.execute("CREATE TABLE evidence_ids (identity TEXT PRIMARY KEY) WITHOUT ROWID")
    connection.execute(
        """
        CREATE TABLE selected_outputs(
            tier_order INTEGER NOT NULL CHECK(tier_order IN (0,1)),
            selection_ordinal INTEGER NOT NULL CHECK(selection_ordinal >= 1),
            candidate_pair_id TEXT NOT NULL UNIQUE,
            dossier_relative_path TEXT NOT NULL UNIQUE,
            output_j_line TEXT NOT NULL,
            PRIMARY KEY(tier_order,selection_ordinal)
        ) WITHOUT ROWID
        """
    )
    connection.execute(
        """
        CREATE TABLE manifest_artifacts(
            relative_path TEXT PRIMARY KEY,
            size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
            sha256 TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    return connection


def _insert_unique_identity(
    connection: sqlite3.Connection,
    *,
    table: str,
    identity: str,
    label: str,
) -> None:
    if table not in {"candidate_ids", "evidence_ids"}:
        raise AssertionError(f"unexpected identity table: {table}")
    try:
        connection.execute(f"INSERT INTO {table} VALUES (?)", (identity,))
    except sqlite3.IntegrityError as exc:
        raise ReviewTraceabilityError(f"duplicate {label}: {identity}") from exc


def _insert_selected_output(
    connection: sqlite3.Connection,
    *,
    tier_order: int,
    selection_ordinal: int,
    candidate: FinalCandidate,
    record: ReviewRecord,
) -> None:
    relative_path = f"dossiers/{_dossier_filename(candidate.candidate_pair_id)}"
    try:
        connection.execute(
            "INSERT INTO selected_outputs VALUES (?,?,?,?,?)",
            (
                tier_order,
                selection_ordinal,
                candidate.candidate_pair_id,
                relative_path,
                _candidate_table_row(candidate, record),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ReviewTraceabilityError(
            f"duplicate or ambiguous selected review output: {candidate.candidate_pair_id}"
        ) from exc


def _selected_output_lines(
    connection: sqlite3.Connection,
    *,
    tier_order: int,
) -> Iterator[str]:
    cursor = connection.execute(
        """
        SELECT output_j_line
        FROM selected_outputs
        WHERE tier_order=?
        ORDER BY selection_ordinal
        """,
        (tier_order,),
    )
    for (line,) in cursor:
        yield str(line)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_payload_sha256(rows: Sequence[FinalCandidate | EvidenceRow | ReviewRecord]) -> str:
    payload = _canonical_json(
        sorted(
            (row.model_dump(mode="json") for row in rows),
            key=lambda item: (
                str(item.get("candidate_pair_id", "")),
                str(item.get("evidence_id", "")),
            ),
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest_payload(
    staging: Path,
    candidates: Sequence[FinalCandidate],
    evidence: Sequence[EvidenceRow],
    records: Sequence[ReviewRecord],
    *,
    dossier_candidates: Sequence[FinalCandidate],
    tier_a_dossier_limit: int,
) -> bytes:
    artifact_rows = []
    for path in sorted(staging.rglob("*"), key=lambda item: item.relative_to(staging).as_posix()):
        if not path.is_file() or path.name == "review-manifest.json":
            continue
        artifact_rows.append(
            {
                "relative_path": path.relative_to(staging).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    dossiers = [
        {
            "candidate_pair_id": candidate.candidate_pair_id,
            "relative_path": f"dossiers/{_dossier_filename(candidate.candidate_pair_id)}",
        }
        for candidate in dossier_candidates
    ]
    source_artifacts = sorted(
        {(row.source_artifact_id, row.source_artifact_sha256) for row in evidence}
    )
    manifest = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_columns": REVIEW_COLUMNS,
        "candidate_count": len(candidates),
        "evidence_count": len(evidence),
        "tier_a_count": sum(candidate.tier_a_eligible for candidate in candidates),
        "tier_a_dossier_count": sum(candidate.tier_a_eligible for candidate in dossier_candidates),
        "tier_a_dossier_limit": tier_a_dossier_limit,
        "tier_b_count": sum(candidate.tier_b_rank is not None for candidate in candidates),
        "tier_b_dossier_count": sum(
            candidate.tier_b_rank is not None for candidate in dossier_candidates
        ),
        "retained_excluded_count": sum(
            not candidate.tier_a_eligible and candidate.tier_b_rank is None
            for candidate in candidates
        ),
        "candidate_ids": [
            candidate.candidate_pair_id for candidate in sorted(candidates, key=_selection_key)
        ],
        "evidence_ids": sorted(row.evidence_id for row in evidence),
        "candidate_payload_sha256": _model_payload_sha256(candidates),
        "evidence_payload_sha256": _model_payload_sha256(evidence),
        "review_payload_sha256": _model_payload_sha256(records),
        "source_artifacts": [
            {"source_artifact_id": item[0], "source_artifact_sha256": item[1]}
            for item in source_artifacts
        ],
        "dossiers": dossiers,
        "artifacts": artifact_rows,
    }
    return (_canonical_json(manifest) + "\n").encode("utf-8")


def _index_streaming_artifacts(
    connection: sqlite3.Connection,
    staging: Path,
    *,
    internal_paths: Sequence[Path],
) -> None:
    """Index generated artifacts on disk without retaining or sorting their paths in Python."""

    excluded = {
        path.relative_to(staging).as_posix()
        for path in internal_paths
        if path.is_relative_to(staging)
    }
    indexed = 0
    for path in staging.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(staging).as_posix()
        if relative_path == "review-manifest.json" or relative_path in excluded:
            continue
        try:
            connection.execute(
                "INSERT INTO manifest_artifacts VALUES (?,?,?)",
                (relative_path, path.stat().st_size, _sha256_file(path)),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - one path cannot repeat on disk
            raise ReviewOutputError(
                f"review artifact inventory repeats a path: {relative_path}"
            ) from exc
        indexed += 1
        if indexed % 10_000 == 0:
            connection.commit()
    connection.commit()


def _manifest_artifact_rows(connection: sqlite3.Connection) -> Iterator[dict[str, object]]:
    cursor = connection.execute(
        "SELECT relative_path,size_bytes,sha256 FROM manifest_artifacts ORDER BY relative_path"
    )
    for relative_path, size_bytes, sha256 in cursor:
        yield {
            "relative_path": str(relative_path),
            "size_bytes": int(size_bytes),
            "sha256": str(sha256),
        }


def _manifest_dossier_rows(connection: sqlite3.Connection) -> Iterator[dict[str, object]]:
    cursor = connection.execute(
        """
        SELECT candidate_pair_id,dossier_relative_path
        FROM selected_outputs
        ORDER BY tier_order,selection_ordinal
        """
    )
    for candidate_pair_id, relative_path in cursor:
        yield {
            "candidate_pair_id": str(candidate_pair_id),
            "relative_path": str(relative_path),
        }


def _write_canonical_json_array(handle: object, rows: Iterable[object]) -> None:
    if not hasattr(handle, "write"):
        raise TypeError("canonical JSON output handle must provide write()")
    writer = handle.write
    writer(b"[")
    first = True
    for row in rows:
        if not first:
            writer(b",")
        writer(_canonical_json(row).encode("utf-8"))
        first = False
    writer(b"]")


def _write_streaming_manifest(
    path: Path,
    *,
    connection: sqlite3.Connection,
    summary: StreamingReviewSummary,
    tier_a_dossier_limit: int,
    tier_b_size: int,
    maximum_evidence_rows_per_candidate: int,
    source_artifacts: Sequence[tuple[str, str]],
) -> None:
    """Atomically stream the canonical manifest from bounded values and SQLite cursors."""

    selection_count = summary.tier_a_dossier_count + summary.tier_b_dossier_count
    fields: dict[str, object] = {
        "actual_reviewed_count": summary.actual_reviewed_count,
        "candidate_count": summary.candidate_count,
        "candidate_stream_ordering": "ensemble_score_desc_candidate_pair_id_asc",
        "candidate_stream_sha256": summary.candidate_stream_sha256,
        "dossier_count": selection_count,
        "dossier_selection_policy": {
            "tier_a": {
                "maximum_size": tier_a_dossier_limit,
                "ranking": "ensemble_score_desc_candidate_pair_id_asc",
                "selection": "first_statistically_eligible_candidates",
            },
            "tier_b": {
                "applies_basic_exclusions": True,
                "excludes_tier_a": True,
                "includes_all_ranked_rows": True,
                "maximum_size": tier_b_size,
                "ranking": "ensemble_score_desc_candidate_pair_id_asc",
                "requires_unknown_knownness": True,
            },
        },
        "evidence_count": summary.evidence_count,
        "evidence_stream_ordering": "candidate_ledger_order_then_candidate_evidence_id_order",
        "evidence_stream_sha256": summary.evidence_stream_sha256,
        "full_identity_lists_omitted": True,
        "identity_uniqueness_method": "sqlite_primary_key_exact",
        "maximum_evidence_rows_per_candidate": maximum_evidence_rows_per_candidate,
        "retained_excluded_count": summary.retained_excluded_count,
        "review_columns": REVIEW_COLUMNS,
        "review_ledger_count": summary.candidate_count,
        "review_selection_count": selection_count,
        "review_summary_scope": "bounded_dossier_selection_only",
        "review_stream_ordering": "tier_a_then_tier_b_then_retained_selection_key",
        "review_stream_sha256": summary.review_stream_sha256,
        "schema_version": STREAMING_REVIEW_SCHEMA_VERSION,
        "source_artifacts": [
            {"source_artifact_id": item[0], "source_artifact_sha256": item[1]}
            for item in source_artifacts
        ],
        "tier_a_count": summary.tier_a_count,
        "tier_a_dossier_count": summary.tier_a_dossier_count,
        "tier_a_dossier_limit": tier_a_dossier_limit,
        "tier_b_count": summary.tier_b_count,
        "tier_b_dossier_count": summary.tier_b_dossier_count,
        "tier_b_policy": {
            "maximum_size": tier_b_size,
            "ranking": "ensemble_score_desc_candidate_pair_id_asc",
            "requires_unknown_knownness": True,
            "excludes_tier_a": True,
            "applies_basic_exclusions": True,
        },
    }
    dynamic_rows: dict[str, Callable[[], Iterable[object]]] = {
        "artifacts": lambda: _manifest_artifact_rows(connection),
        "dossiers": lambda: _manifest_dossier_rows(connection),
    }
    temporary = path.with_name(f".{path.name}.writing-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as handle:
            handle.write(b"{")
            first = True
            for key in sorted((*fields, *dynamic_rows)):
                if not first:
                    handle.write(b",")
                handle.write(_canonical_json(key).encode("utf-8"))
                handle.write(b":")
                if key in dynamic_rows:
                    _write_canonical_json_array(handle, dynamic_rows[key]())
                else:
                    handle.write(_canonical_json(fields[key]).encode("utf-8"))
                first = False
            handle.write(b"}\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _publish_directory(staging: Path, target: Path, *, overwrite: bool) -> None:
    if target.exists() and not overwrite:
        raise FileExistsError(f"review output directory already exists: {target}")
    if target.exists() and not target.is_dir():
        raise ReviewOutputError(f"review output target is not a directory: {target}")
    if target.is_symlink():
        raise ReviewOutputError(f"refusing to replace symlinked review output: {target}")

    backup: Path | None = None
    try:
        if target.exists():
            backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
            target.replace(backup)
        try:
            staging.replace(target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                backup.replace(target)
            raise
        if backup is not None:
            shutil.rmtree(backup)
    except Exception as exc:
        raise ReviewOutputError(
            f"could not atomically publish review bundle {target}: {exc}"
        ) from exc


def write_review_bundle_streaming(
    output_directory: Path,
    candidates: Iterable[FinalCandidate],
    *,
    evidence_for_candidate: CandidateEvidenceLookup,
    passages: Mapping[str, PassageRecord],
    expected_candidate_count: int,
    expected_evidence_count: int,
    tier_b_size: int,
    maximum_evidence_rows_per_candidate: int,
    expected_candidate_ledger_sha256: str,
    prepare_selected_evidence: SelectedEvidencePreparer | None = None,
    prior_review_for_candidate: Callable[[FinalCandidate], ReviewRecord | None] | None = None,
    threshold_report: EnsembleNullThresholdReport | None = None,
    tier_a_dossier_limit: int = 100,
    parquet_row_group_size: int = 10_000,
    maximum_source_artifacts: int = 1_024,
    overwrite: bool = False,
) -> StreamingReviewArtifacts:
    """Publish the exact review population with bounded candidate/evidence memory.

    ``candidates`` must use the Stage-8 ledger order: descending ensemble score
    with ascending candidate ID as the tie break. ``evidence_for_candidate``
    must return exactly the evidence IDs named by that one candidate. A caller
    backed by an offset index, key-value store, or pair-grouped ledger therefore
    retains only one candidate's evidence in memory.

    ``prepare_selected_evidence`` is deliberately invoked only for the first
    score-ranked ``tier_a_dossier_limit`` Tier A candidates and every ranked
    Tier B candidate. It is the integration point for bounded M7 detail
    hydration; its returned rows become both the selected CSV projection and
    the dossier evidence. Population counts from the authenticated Stage-8
    receipt are required so an upstream orphan row cannot be hidden by a
    lookup callback. ``expected_candidate_ledger_sha256`` binds that stream to
    the canonical Stage-8 ledger bytes.
    """

    if tuple(ReviewRecord.model_fields) != REVIEW_COLUMNS:
        raise ReviewOutputError("ReviewRecord fields changed without an explicit export migration")
    if expected_candidate_count < 1:
        raise ValueError("expected_candidate_count must be positive")
    if expected_evidence_count < expected_candidate_count:
        raise ValueError("expected_evidence_count must cover at least one row per candidate")
    if not 1 <= tier_b_size <= 100:
        raise ValueError("tier_b_size must be between one and 100")
    if not 1 <= tier_a_dossier_limit <= 100:
        raise ValueError("tier_a_dossier_limit must be between one and 100")
    if maximum_evidence_rows_per_candidate < 1:
        raise ValueError("maximum_evidence_rows_per_candidate must be positive")
    if re.fullmatch(r"[a-f0-9]{64}", expected_candidate_ledger_sha256) is None:
        raise ValueError("expected_candidate_ledger_sha256 must be lowercase SHA-256")
    if parquet_row_group_size < 1:
        raise ValueError("parquet_row_group_size must be positive")
    if maximum_source_artifacts < 1:
        raise ValueError("maximum_source_artifacts must be positive")
    if output_directory.is_symlink():
        raise ReviewOutputError(f"refusing to replace symlinked review output: {output_directory}")
    target = output_directory.resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"review output directory already exists: {target}")
    if target.exists() and not target.is_dir():
        raise ReviewOutputError(f"review output target is not a directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.writing-", dir=target.parent))

    partition_names = ("tier-a", "tier-b", "retained")
    csv_partitions = tuple(staging / f".{name}.review-rows.csv" for name in partition_names)
    model_partitions = tuple(staging / f".{name}.review-models.jsonl" for name in partition_names)
    identity_path = staging / ".review-identities.sqlite3"
    identity_connection: sqlite3.Connection | None = None
    try:
        identity_connection = _open_identity_database(identity_path)
        dossier_directory = staging / "dossiers"
        dossier_directory.mkdir()
        candidate_digest = hashlib.sha256()
        evidence_digest = hashlib.sha256()
        candidate_count = 0
        evidence_count = 0
        tier_a_count = 0
        tier_b_count = 0
        tier_a_dossier_count = 0
        tier_b_dossier_count = 0
        actual_reviewed_count = 0
        retained_count = 0
        tier_b_pool_count = 0
        prior_order_key: tuple[float, str] | None = None
        source_artifacts: set[tuple[str, str]] = set()
        classifications: Counter[str] = Counter()
        rejection_categories: Counter[str] = Counter()

        with ExitStack() as stack:
            csv_handles = [
                stack.enter_context(path.open("x", encoding="utf-8", newline=""))
                for path in csv_partitions
            ]
            model_handles = [stack.enter_context(path.open("xb")) for path in model_partitions]
            csv_writers = [
                csv.DictWriter(
                    handle,
                    fieldnames=REVIEW_COLUMNS,
                    extrasaction="raise",
                    lineterminator="\n",
                )
                for handle in csv_handles
            ]

            for candidate in candidates:
                candidate_count += 1
                if candidate_count > expected_candidate_count:
                    raise ReviewTraceabilityError(
                        "candidate stream exceeds the authenticated expected count"
                    )
                order_key = (-candidate.ensemble_score, candidate.candidate_pair_id)
                if prior_order_key is not None and order_key <= prior_order_key:
                    raise ReviewTraceabilityError(
                        "candidate ledger must be strictly ordered by descending score and "
                        "ascending candidate ID"
                    )
                prior_order_key = order_key
                _insert_unique_identity(
                    identity_connection,
                    table="candidate_ids",
                    identity=candidate.candidate_pair_id,
                    label="candidate_pair_id",
                )
                candidate_digest.update(_canonical_model_line(candidate))

                in_tier_b_pool = (
                    not candidate.tier_a_eligible
                    and candidate.knownness_status == "unknown"
                    and not candidate.quality.basic_exclusion
                )
                expected_tier_b_rank: int | None = None
                if in_tier_b_pool:
                    tier_b_pool_count += 1
                    if tier_b_pool_count <= tier_b_size:
                        expected_tier_b_rank = tier_b_pool_count
                if candidate.tier_b_rank != expected_tier_b_rank:
                    raise ReviewTraceabilityError(
                        f"candidate {candidate.candidate_pair_id} has Tier B rank "
                        f"{candidate.tier_b_rank!r}; expected {expected_tier_b_rank!r} from "
                        "the complete score-ranked unknown pool"
                    )

                base_rows = _bounded_rows(
                    evidence_for_candidate(candidate),
                    maximum=maximum_evidence_rows_per_candidate,
                    candidate_pair_id=candidate.candidate_pair_id,
                    role="evidence lookup",
                )
                tier_a_selection_ordinal = tier_a_count + 1
                selected_for_dossier = (
                    candidate.tier_a_eligible and tier_a_selection_ordinal <= tier_a_dossier_limit
                ) or candidate.tier_b_rank is not None
                if selected_for_dossier and prepare_selected_evidence is not None:
                    rows = _bounded_rows(
                        prepare_selected_evidence(candidate, base_rows),
                        maximum=maximum_evidence_rows_per_candidate,
                        candidate_pair_id=candidate.candidate_pair_id,
                        role="selected evidence preparation",
                    )
                else:
                    rows = base_rows
                _, evidence_by_id = _validated_indexes(
                    (candidate,),
                    rows,
                    require_complete_tier_b_ranking=False,
                )
                ordered_rows = tuple(
                    evidence_by_id[evidence_id] for evidence_id in candidate.evidence_ids
                )
                for row in ordered_rows:
                    evidence_count += 1
                    if evidence_count > expected_evidence_count:
                        raise ReviewTraceabilityError(
                            "evidence stream exceeds the authenticated expected count"
                        )
                    _insert_unique_identity(
                        identity_connection,
                        table="evidence_ids",
                        identity=row.evidence_id,
                        label="evidence_id",
                    )
                    evidence_digest.update(_canonical_model_line(row))
                    source_artifacts.add((row.source_artifact_id, row.source_artifact_sha256))
                    if len(source_artifacts) > maximum_source_artifacts:
                        raise ReviewTraceabilityError(
                            "evidence exceeds the governed source-artifact identity bound"
                        )

                prior = (
                    prior_review_for_candidate(candidate)
                    if prior_review_for_candidate is not None
                    else None
                )
                if prior is not None:
                    if prior.candidate_pair_id != candidate.candidate_pair_id:
                        raise ReviewTraceabilityError(
                            "prior-review lookup returned a different candidate identity"
                        )
                    _assert_prior_identity(candidate, prior)
                record = _review_record(candidate, ordered_rows, passages, prior=prior)

                if candidate.tier_a_eligible:
                    partition_index = 0
                    tier_a_count += 1
                    if selected_for_dossier:
                        tier_a_dossier_count += 1
                        _insert_selected_output(
                            identity_connection,
                            tier_order=0,
                            selection_ordinal=tier_a_dossier_count,
                            candidate=candidate,
                            record=record,
                        )
                elif candidate.tier_b_rank is not None:
                    partition_index = 1
                    tier_b_count += 1
                    tier_b_dossier_count += 1
                    _insert_selected_output(
                        identity_connection,
                        tier_order=1,
                        selection_ordinal=tier_b_dossier_count,
                        candidate=candidate,
                        record=record,
                    )
                else:
                    partition_index = 2
                    retained_count += 1
                csv_writers[partition_index].writerow(record.model_dump(mode="json"))
                model_handles[partition_index].write(_canonical_model_line(record))

                if selected_for_dossier:
                    classifications[record.reviewer_classification.value] += 1
                    if record.reviewer_classification != ReviewClassification.NOT_REVIEWED:
                        actual_reviewed_count += 1
                    if record.rejection_category.strip():
                        rejection_categories[record.rejection_category.strip()] += 1
                    dossier = render_candidate_dossier(
                        candidate,
                        ordered_rows,
                        record,
                        passages=passages,
                    )
                    _atomic_write_bytes(
                        dossier_directory / _dossier_filename(candidate.candidate_pair_id),
                        dossier.encode("utf-8"),
                    )
                if candidate_count % 10_000 == 0:
                    identity_connection.commit()

            for handle in (*csv_handles, *model_handles):
                handle.flush()
                os.fsync(handle.fileno())

        identity_connection.commit()
        if candidate_count != expected_candidate_count:
            raise ReviewTraceabilityError(
                f"candidate stream has {candidate_count} rows; expected {expected_candidate_count}"
            )
        if evidence_count != expected_evidence_count:
            raise ReviewTraceabilityError(
                f"evidence stream has {evidence_count} rows; expected {expected_evidence_count}"
            )
        expected_tier_b_count = min(tier_b_size, tier_b_pool_count)
        if tier_b_count != expected_tier_b_count:
            raise ReviewTraceabilityError(
                f"Tier B has {tier_b_count} rows; expected {expected_tier_b_count}"
            )
        expected_tier_a_dossier_count = min(tier_a_dossier_limit, tier_a_count)
        if tier_a_dossier_count != expected_tier_a_dossier_count:
            raise ReviewTraceabilityError(
                f"Tier A dossier selection has {tier_a_dossier_count} rows; expected "
                f"{expected_tier_a_dossier_count}"
            )
        if tier_b_dossier_count != tier_b_count:
            raise ReviewTraceabilityError("every Tier B row must receive a dossier")
        database_candidate_count = int(
            identity_connection.execute("SELECT count(*) FROM candidate_ids").fetchone()[0]
        )
        database_evidence_count = int(
            identity_connection.execute("SELECT count(*) FROM evidence_ids").fetchone()[0]
        )
        if database_candidate_count != candidate_count or database_evidence_count != evidence_count:
            raise ReviewTraceabilityError("disk-backed identity index counts disagree")

        review_stream_sha256 = _hash_partition_stream(model_partitions)
        candidate_stream_sha256 = candidate_digest.hexdigest()
        if candidate_stream_sha256 != expected_candidate_ledger_sha256:
            raise ReviewTraceabilityError(
                "candidate stream SHA-256 disagrees with the authenticated Stage-8 receipt"
            )
        summary = StreamingReviewSummary(
            candidate_count=candidate_count,
            evidence_count=evidence_count,
            tier_a_count=tier_a_count,
            tier_b_count=tier_b_count,
            tier_a_dossier_count=tier_a_dossier_count,
            tier_b_dossier_count=tier_b_dossier_count,
            actual_reviewed_count=actual_reviewed_count,
            retained_excluded_count=retained_count,
            candidate_stream_sha256=candidate_stream_sha256,
            evidence_stream_sha256=evidence_digest.hexdigest(),
            review_stream_sha256=review_stream_sha256,
        )
        _combine_review_csv(csv_partitions, staging / "review.csv")
        _write_parquet_from_csv_atomically(
            staging / "review.parquet",
            staging / "review.csv",
            row_group_size=parquet_row_group_size,
        )
        _atomic_write_text_lines(
            staging / "output-j-template.md",
            _iter_output_j_lines(
                tier_a_total_count=tier_a_count,
                tier_a_rows=_selected_output_lines(identity_connection, tier_order=0),
                tier_a_dossier_count=tier_a_dossier_count,
                tier_b_rows=_selected_output_lines(identity_connection, tier_order=1),
                tier_b_dossier_count=tier_b_dossier_count,
                retained_excluded_count=retained_count,
                review_ledger_count=candidate_count,
                actual_reviewed_count=actual_reviewed_count,
                classifications=classifications,
                rejection_categories=rejection_categories,
                threshold_report=threshold_report,
                tier_a_dossier_limit=tier_a_dossier_limit,
            ),
        )

        internal_paths = (
            identity_path,
            identity_path.with_name(identity_path.name + "-journal"),
            identity_path.with_name(identity_path.name + "-shm"),
            identity_path.with_name(identity_path.name + "-wal"),
            *csv_partitions,
            *model_partitions,
        )
        _index_streaming_artifacts(
            identity_connection,
            staging,
            internal_paths=internal_paths,
        )
        _write_streaming_manifest(
            staging / "review-manifest.json",
            connection=identity_connection,
            summary=summary,
            tier_a_dossier_limit=tier_a_dossier_limit,
            tier_b_size=tier_b_size,
            maximum_evidence_rows_per_candidate=maximum_evidence_rows_per_candidate,
            source_artifacts=tuple(sorted(source_artifacts)),
        )
        identity_connection.close()
        identity_connection = None
        identity_path.unlink()
        for suffix in ("-journal", "-shm", "-wal"):
            identity_path.with_name(identity_path.name + suffix).unlink(missing_ok=True)
        for path in (*csv_partitions, *model_partitions):
            path.unlink()
        _publish_directory(staging, target, overwrite=overwrite)
    except Exception:
        if identity_connection is not None:
            identity_connection.close()
        if staging.exists():
            shutil.rmtree(staging)
        raise

    return StreamingReviewArtifacts(
        output_directory=target,
        csv_path=target / "review.csv",
        parquet_path=target / "review.parquet",
        manifest_path=target / "review-manifest.json",
        output_j_path=target / "output-j-template.md",
        dossier_directory=target / "dossiers",
        summary=summary,
    )


def write_review_bundle(
    output_directory: Path,
    candidates: Sequence[FinalCandidate],
    evidence: Sequence[EvidenceRow],
    *,
    passages: Mapping[str, PassageRecord],
    prior_reviews: Sequence[ReviewRecord] = (),
    threshold_report: EnsembleNullThresholdReport | None = None,
    tier_a_dossier_limit: int = 100,
    overwrite: bool = False,
) -> ReviewArtifacts:
    """Atomically publish deterministic CSV, Parquet, dossiers, Output J, and manifest."""

    if tuple(ReviewRecord.model_fields) != REVIEW_COLUMNS:
        raise ReviewOutputError("ReviewRecord fields changed without an explicit export migration")
    if not 1 <= tier_a_dossier_limit <= 100:
        raise ValueError("tier_a_dossier_limit must be between one and 100")
    records = build_review_records(
        candidates,
        evidence,
        passages=passages,
        prior_reviews=prior_reviews,
    )
    if output_directory.is_symlink():
        raise ReviewOutputError(f"refusing to replace symlinked review output: {output_directory}")
    target = output_directory.resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"review output directory already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.writing-", dir=target.parent))
    try:
        _atomic_write_bytes(staging / "review.csv", _csv_bytes(records))
        _write_parquet_atomically(staging / "review.parquet", records)
        dossier_directory = staging / "dossiers"
        dossier_directory.mkdir()
        candidate_by_id = {candidate.candidate_pair_id: candidate for candidate in candidates}
        evidence_by_id = {row.evidence_id: row for row in evidence}
        dossier_candidates = tuple(
            iter_bounded_dossier_candidates(
                sorted(candidates, key=_selection_key),
                tier_a_dossier_limit=tier_a_dossier_limit,
            )
        )
        dossier_candidate_ids = {candidate.candidate_pair_id for candidate in dossier_candidates}
        for record in records:
            candidate = candidate_by_id[record.candidate_pair_id]
            if candidate.candidate_pair_id not in dossier_candidate_ids:
                continue
            rows = tuple(evidence_by_id[item] for item in candidate.evidence_ids)
            dossier = render_candidate_dossier(
                candidate,
                rows,
                record,
                passages=passages,
            )
            _atomic_write_bytes(
                dossier_directory / _dossier_filename(candidate.candidate_pair_id),
                dossier.encode("utf-8"),
            )
        output_j = render_output_j_template(
            candidates,
            records,
            threshold_report=threshold_report,
            tier_a_dossier_limit=tier_a_dossier_limit,
        )
        _atomic_write_bytes(staging / "output-j-template.md", output_j.encode("utf-8"))
        _atomic_write_bytes(
            staging / "review-manifest.json",
            _manifest_payload(
                staging,
                candidates,
                evidence,
                records,
                dossier_candidates=dossier_candidates,
                tier_a_dossier_limit=tier_a_dossier_limit,
            ),
        )
        _publish_directory(staging, target, overwrite=overwrite)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    tier_a_count = sum(candidate.tier_a_eligible for candidate in candidates)
    tier_b_count = sum(candidate.tier_b_rank is not None for candidate in candidates)
    selected_ids = {candidate.candidate_pair_id for candidate in dossier_candidates}
    actual_reviewed_count = sum(
        record.candidate_pair_id in selected_ids
        and record.reviewer_classification != ReviewClassification.NOT_REVIEWED
        for record in records
    )
    return ReviewArtifacts(
        output_directory=target,
        csv_path=target / "review.csv",
        parquet_path=target / "review.parquet",
        manifest_path=target / "review-manifest.json",
        output_j_path=target / "output-j-template.md",
        dossier_paths=tuple(
            target / "dossiers" / _dossier_filename(candidate.candidate_pair_id)
            for candidate in dossier_candidates
        ),
        candidate_count=len(candidates),
        evidence_count=len(evidence),
        tier_a_count=tier_a_count,
        tier_b_count=tier_b_count,
        tier_a_dossier_count=sum(candidate.tier_a_eligible for candidate in dossier_candidates),
        tier_b_dossier_count=sum(
            candidate.tier_b_rank is not None for candidate in dossier_candidates
        ),
        actual_reviewed_count=actual_reviewed_count,
        retained_excluded_count=sum(
            not candidate.tier_a_eligible and candidate.tier_b_rank is None
            for candidate in candidates
        ),
    )


__all__ = [
    "ENGLISH_SUPPLEMENTAL_LABEL",
    "OUTPUT_J_PLACEHOLDER",
    "REVIEW_COLUMNS",
    "REVIEW_SCHEMA_VERSION",
    "STREAMING_REVIEW_SCHEMA_VERSION",
    "CandidateEvidenceLookup",
    "ReviewArtifacts",
    "ReviewOutputError",
    "ReviewTraceabilityError",
    "SelectedEvidencePreparer",
    "StreamingReviewArtifacts",
    "StreamingReviewSummary",
    "build_review_records",
    "render_candidate_dossier",
    "render_output_j_template",
    "validate_review_traceability",
    "write_review_bundle",
    "write_review_bundle_streaming",
]
