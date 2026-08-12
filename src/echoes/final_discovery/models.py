"""Typed in-memory and persisted contracts for final-discovery evidence."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EvidenceFamily = Literal["lexical", "semantic", "grammar_syntax", "structure_narrative", "anomaly"]
KnownnessStatus = Literal[
    "known_forward",
    "known_reverse",
    "known_both",
    "known_m7_snapshot",
    "unknown",
]
OutputLabel = Literal[
    "statistically_eligible",
    "exploratory_not_statistically_accepted",
    "retained_excluded",
]


def _validate_source_knownness(
    status: KnownnessStatus | None, relationship_ids: tuple[str, ...]
) -> None:
    if len(relationship_ids) != len(set(relationship_ids)):
        raise ValueError("source known-relationship IDs must be unique")
    if status in {None, "unknown"} and relationship_ids:
        raise ValueError("unknown or absent source knownness cannot carry relationship IDs")


class FinalDiscoveryRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="after")
    @classmethod
    def finite_numbers_only(cls, value: object) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("persisted final-discovery numbers must be finite")
        return value


class PassageRecord(FinalDiscoveryRow):
    """Smallest governed passage projection needed by the new engines."""

    passage_id: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    corpus: Literal["hebrew", "greek"]
    book: str = Field(min_length=1)
    genre: str = Field(min_length=1)
    analysis_profile: Literal["edition_complete", "critical_core"]
    analysis_reading: Literal["qere", "ketiv", "source"]
    granularity: Literal["verse"]
    token_count: int = Field(ge=1)
    # Older synthetic fixtures predate the governed M5 token projection and may
    # omit this field.  Production projections always populate it; when it is
    # present, the validator below requires an exact one-to-one alignment.
    token_ids: tuple[str, ...] = ()
    original_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    lemma_sequence: tuple[str | None, ...]
    root_sequence: tuple[str | None, ...]
    pos_sequence: tuple[str | None, ...]
    morphology_sequence: tuple[str | None, ...]
    semantic_domains: tuple[str | None, ...]
    entities: tuple[str | None, ...]
    participants: tuple[str | None, ...]
    frames: tuple[str | None, ...]
    english_gloss: str | None = None
    disputed_passage: bool = False
    reference_gap: bool = False
    ketiv_uncertainty: bool = False
    formulaic_language: bool = False
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def aligned_sequences_and_reading(self) -> Self:
        sequences = (
            self.lemma_sequence,
            self.root_sequence,
            self.pos_sequence,
            self.morphology_sequence,
            self.semantic_domains,
            self.entities,
            self.participants,
            self.frames,
        )
        if any(len(sequence) != self.token_count for sequence in sequences):
            raise ValueError("every passage feature sequence must align to token_count")
        if self.token_ids:
            if len(self.token_ids) != self.token_count:
                raise ValueError("passage token IDs must align to token_count")
            if any(not token_id for token_id in self.token_ids):
                raise ValueError("passage token IDs must be nonempty")
            if len(self.token_ids) != len(set(self.token_ids)):
                raise ValueError("passage token IDs must be unique within a passage")
        if self.corpus == "hebrew" and self.analysis_reading not in {"qere", "ketiv"}:
            raise ValueError("Hebrew passage records require qere or ketiv")
        if self.corpus == "greek" and self.analysis_reading != "source":
            raise ValueError("Greek passage records require source reading")
        return self


class EvidenceRow(FinalDiscoveryRow):
    """One raw detector trace with explicit lineage and independence semantics."""

    evidence_id: str = Field(min_length=1)
    candidate_pair_id: str = Field(min_length=1)
    passage_a_id: str = Field(min_length=1)
    passage_b_id: str = Field(min_length=1)
    detector_id: str = Field(min_length=1)
    family: EvidenceFamily
    independence_group: str = Field(min_length=1)
    raw_score: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    normalization_method: str = Field(min_length=1)
    empirical_p_value: float = Field(ge=0.0, le=1.0)
    null_method: str = Field(min_length=1)
    contains_english_derived_evidence: bool
    english_ablation_normalized_score: float | None = Field(default=None, ge=0.0, le=1.0)
    original_language_evidence_remains: bool
    counts_for_independence: bool
    trace_json: str = Field(min_length=2)
    source_artifact_id: str = Field(min_length=1)
    source_artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_quality: QualityFlags | None = None
    source_knownness_status: KnownnessStatus | None = None
    source_known_relationship_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def pair_and_independence_are_consistent(self) -> Self:
        if self.passage_a_id >= self.passage_b_id:
            raise ValueError("evidence passage IDs must use canonical lexical ordering")
        if (
            self.contains_english_derived_evidence
            and not self.original_language_evidence_remains
            and self.counts_for_independence
        ):
            raise ValueError("English-only evidence cannot count for independence")
        if (
            self.english_ablation_normalized_score is not None
            and self.english_ablation_normalized_score > self.normalized_score
        ):
            raise ValueError("English ablation cannot increase a normalized evidence score")
        _validate_source_knownness(self.source_knownness_status, self.source_known_relationship_ids)
        return self


class RawEvidence(FinalDiscoveryRow):
    """Detector output before frozen empirical normalization and null calibration."""

    candidate_pair_id: str = Field(min_length=1)
    passage_a_id: str = Field(min_length=1)
    passage_b_id: str = Field(min_length=1)
    detector_id: str = Field(min_length=1)
    family: EvidenceFamily
    independence_group: str = Field(min_length=1)
    raw_score: float
    contains_english_derived_evidence: bool
    english_ablation_raw_score: float | None = None
    original_language_evidence_remains: bool
    counts_for_independence: bool
    trace_json: str = Field(min_length=2)
    source_artifact_id: str = Field(min_length=1)
    source_artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_quality: QualityFlags | None = None
    source_knownness_status: KnownnessStatus | None = None
    source_known_relationship_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def direction_and_independence_are_valid(self) -> Self:
        if self.passage_a_id >= self.passage_b_id:
            raise ValueError("raw evidence passage IDs must use canonical lexical ordering")
        if (
            self.contains_english_derived_evidence
            and not self.original_language_evidence_remains
            and self.counts_for_independence
        ):
            raise ValueError("English-only raw evidence cannot count for independence")
        if (
            self.english_ablation_raw_score is not None
            and self.english_ablation_raw_score > self.raw_score
        ):
            raise ValueError("English ablation cannot increase a raw evidence score")
        _validate_source_knownness(self.source_knownness_status, self.source_known_relationship_ids)
        return self


class QualityFlags(FinalDiscoveryRow):
    disputed_passage: bool
    reference_gap: bool
    ketiv_uncertainty: bool
    formulaic_language: bool
    overlapping_passages: bool
    unresolved_data_error: bool
    invalid_trace: bool
    local_context: bool = False
    exact_or_near_duplicate: bool = False
    same_reference_sensitivity: bool = False

    @property
    def basic_exclusion(self) -> bool:
        return (
            self.overlapping_passages
            or self.unresolved_data_error
            or self.invalid_trace
            or self.local_context
            or self.exact_or_near_duplicate
            or self.same_reference_sensitivity
        )


class FinalCandidate(FinalDiscoveryRow):
    """Complete retained candidate including accepted and rejected states."""

    candidate_pair_id: str = Field(min_length=1)
    passage_a_id: str = Field(min_length=1)
    passage_b_id: str = Field(min_length=1)
    passage_a_reference: str = Field(min_length=1)
    passage_b_reference: str = Field(min_length=1)
    ensemble_score: float = Field(ge=0.0, le=1.0)
    empirical_p_value: float = Field(ge=0.0, le=1.0)
    bh_q_value: float = Field(ge=0.0, le=1.0)
    empirical_fdr: float = Field(ge=0.0, le=1.0)
    knownness_status: KnownnessStatus
    known_relationship_ids: tuple[str, ...]
    quality: QualityFlags
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    detector_ids: tuple[str, ...] = Field(min_length=1)
    families: tuple[EvidenceFamily, ...] = Field(min_length=1)
    qualifying_independence_groups: tuple[str, ...]
    original_language_independence_groups: tuple[str, ...]
    contains_english_derived_evidence: bool
    score_without_english: float = Field(ge=0.0, le=1.0)
    english_ablation_empirical_p_value: float = Field(ge=0.0, le=1.0)
    english_ablation_bh_q_value: float = Field(ge=0.0, le=1.0)
    english_ablation_empirical_fdr: float = Field(ge=0.0, le=1.0)
    english_ablation_survives: bool
    tier_a_eligible: bool
    tier_a_exclusion_reasons: tuple[str, ...]
    tier_b_rank: int | None = Field(default=None, ge=1, le=100)
    output_label: OutputLabel

    @model_validator(mode="after")
    def tiers_are_disjoint_and_traceable(self) -> Self:
        if self.passage_a_id >= self.passage_b_id:
            raise ValueError("candidate passage IDs must use canonical lexical ordering")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("candidate evidence IDs must be unique")
        if set(self.original_language_independence_groups) - set(
            self.qualifying_independence_groups
        ):
            raise ValueError("original-language groups must be qualifying groups")
        if self.tier_a_eligible:
            if self.tier_a_exclusion_reasons:
                raise ValueError("Tier A candidates cannot carry Tier A exclusions")
            if self.output_label != "statistically_eligible" or self.tier_b_rank is not None:
                raise ValueError("Tier A and Tier B are mutually exclusive")
        elif not self.tier_a_exclusion_reasons:
            raise ValueError("non-Tier-A candidates require explicit exclusion reasons")
        if (
            self.tier_b_rank is not None
            and self.output_label != "exploratory_not_statistically_accepted"
        ):
            raise ValueError("Tier B rank requires the exploratory label")
        return self


class ReviewClassification(StrEnum):
    DIRECT_QUOTATION = "direct_quotation"
    PROBABLE_LITERARY_ALLUSION = "probable_literary_allusion"
    POSSIBLE_LITERARY_ECHO = "possible_literary_echo"
    NARRATIVE_OR_STRUCTURAL_PARALLEL = "narrative_or_structural_parallel"
    THEMATIC_RELATIONSHIP = "thematic_relationship"
    FORMAL_COINCIDENCE = "formal_coincidence"
    DATA_ARTIFACT = "data_artifact"
    NOT_REVIEWED = "not_reviewed"


class ReviewRecord(FinalDiscoveryRow):
    candidate_pair_id: str = Field(min_length=1)
    output_label: str = Field(min_length=1)
    tier_b_rank: int | None = Field(default=None, ge=1, le=100)
    passage_a_id: str = Field(min_length=1)
    passage_b_id: str = Field(min_length=1)
    passage_a_reference: str = Field(min_length=1)
    passage_b_reference: str = Field(min_length=1)
    passage_a_original_text: str = Field(min_length=1)
    passage_b_original_text: str = Field(min_length=1)
    passage_a_normalized_text: str = Field(min_length=1)
    passage_b_normalized_text: str = Field(min_length=1)
    passage_a_english_gloss: str = ""
    passage_b_english_gloss: str = ""
    ensemble_score: float = Field(ge=0.0, le=1.0)
    knownness_status: KnownnessStatus
    detector_contributions_json: str = Field(min_length=2)
    original_language_evidence_json: str = Field(min_length=2)
    supplemental_gloss_evidence_json: str = Field(min_length=2)
    null_fdr_status_json: str = Field(min_length=2)
    ablation_status_json: str = Field(min_length=2)
    quality_flags_json: str = Field(min_length=2)
    reviewer_classification: ReviewClassification = ReviewClassification.NOT_REVIEWED
    rejection_category: str = ""
    reviewer_notes: str = ""

    @model_validator(mode="after")
    def passage_identity_is_canonical(self) -> Self:
        if self.passage_a_id >= self.passage_b_id:
            raise ValueError("review passage IDs must use canonical lexical ordering")
        return self


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
