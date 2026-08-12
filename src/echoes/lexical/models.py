"""Typed rows and stable Polars schemas for Milestone 7 lexical artifacts."""

from __future__ import annotations

import json
import math
from enum import StrEnum
from typing import Any, Literal, Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LEXICAL_SCHEMA_VERSION = 1
CANDIDATE_PAIR_SCHEMA_VERSION = 1


class LexicalSeverity(StrEnum):
    """Governed lexical validation severities."""

    ERROR = "error"
    WARNING = "warning"
    INFORMATIONAL = "informational"


class LexicalRow(BaseModel):
    """Strict common behavior for persisted lexical rows."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    @field_validator("*", mode="after")
    @classmethod
    def reject_nan(cls, value: Any) -> Any:
        """Reject non-reflexive numeric values while retaining meaningful infinity ratios."""

        if isinstance(value, float) and math.isnan(value):
            raise ValueError("NaN is not a valid persisted lexical value")
        return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _canonical_json(value: str) -> object:
    return json.loads(value, parse_constant=_reject_json_constant)


def _json_array(value: str) -> str:
    parsed = _canonical_json(value)
    if not isinstance(parsed, list):
        raise ValueError("must encode a JSON array")
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_object(value: str) -> str:
    parsed = _canonical_json(value)
    if not isinstance(parsed, dict):
        raise ValueError("must encode a JSON object")
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _runtime_seconds_object(value: str) -> str:
    canonical = _json_object(value)
    parsed = json.loads(canonical)
    if not parsed:
        raise ValueError("must retain at least one named stage runtime")
    if any(
        not isinstance(name, str)
        or not name
        or isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(float(seconds))
        or float(seconds) < 0.0
        for name, seconds in parsed.items()
    ):
        raise ValueError("stage runtimes must be finite nonnegative numbers keyed by stage name")
    return canonical


def _matrix_shape(value: str) -> str:
    canonical = _json_array(value)
    parsed = json.loads(canonical)
    if len(parsed) != 2 or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in parsed
    ):
        raise ValueError("must encode exactly two nonnegative integer dimensions")
    return canonical


class FeatureVocabularyRow(LexicalRow):
    feature_id: str = Field(min_length=1)
    lexical_schema_version: Literal[1] = 1
    feature_family: str = Field(min_length=1)
    language_namespace: Literal["hb", "gk", "en"]
    feature_value: str = Field(min_length=1)
    feature_order: int = Field(ge=1)
    corpus_frequency: int = Field(ge=0)
    document_frequency: int = Field(ge=0)
    inverse_document_frequency: float = Field(ge=0.0)
    book_frequency: int = Field(ge=0)
    genre_frequency: int = Field(ge=0)
    is_rare: bool
    is_high_frequency: bool
    is_formulaic: bool
    contains_english_derived_content: bool
    normalization_method: str = Field(min_length=1)
    notes: str

    @model_validator(mode="after")
    def english_namespace_is_explicit(self) -> Self:
        expected = self.language_namespace == "en"
        if self.contains_english_derived_content != expected:
            raise ValueError("only en-namespaced features may be marked English-derived")
        if expected and self.feature_family != "english_gloss":
            raise ValueError("the en namespace is reserved for English gloss features")
        if not expected and self.feature_family == "english_gloss":
            raise ValueError("English gloss features require the en namespace")
        return self


class PassageFeatureStatisticsRow(LexicalRow):
    passage_id: str = Field(min_length=1)
    analysis_profile: str = Field(min_length=1)
    analysis_reading: str = Field(min_length=1)
    granularity: str = Field(min_length=1)
    corpus: str = Field(min_length=1)
    book: str = Field(min_length=1)
    token_count: int = Field(ge=0)
    eligible_token_count: int = Field(ge=0)
    distinct_lemma_count: int = Field(ge=0)
    distinct_root_count: int = Field(ge=0)
    distinct_surface_count: int = Field(ge=0)
    lemma_sequence_length: int = Field(ge=0)
    root_sequence_length: int = Field(ge=0)
    english_gloss_sequence_length: int = Field(ge=0)
    formulaic_feature_count: int = Field(ge=0)
    rare_feature_count: int = Field(ge=0)
    feature_vector_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_passage_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class LexicalIndexMetadataRow(LexicalRow):
    index_id: str = Field(min_length=1)
    experiment_run_id: str = Field(min_length=1)
    representation_id: str = Field(min_length=1)
    corpus_scope: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    reading: str = Field(min_length=1)
    granularity: str = Field(min_length=1)
    feature_family: str = Field(min_length=1)
    matrix_shape_json: str
    nonzero_count: int = Field(ge=0)
    vocabulary_size: int = Field(ge=0)
    document_count: int = Field(ge=0)
    index_config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    logical_matrix_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    physical_file_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dtype: str = Field(min_length=1)
    storage_format: str = Field(min_length=1)
    notes: str

    _shape_is_array = field_validator("matrix_shape_json")(_matrix_shape)


class DirectionalRankingRow(LexicalRow):
    ranking_id: str = Field(min_length=1)
    experiment_run_id: str = Field(min_length=1)
    query_passage_id: str = Field(min_length=1)
    target_passage_id: str = Field(min_length=1)
    corpus_pair: Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
    experiment_scope: str = Field(min_length=1)
    analysis_profile: Literal["edition_complete", "critical_core"]
    query_reading: str = Field(min_length=1)
    target_reading: str = Field(min_length=1)
    granularity: Literal["clause", "sentence", "verse", "two_verse", "five_verse"]
    representation_id: str = Field(min_length=1)
    detector: str = Field(min_length=1)
    rank: int = Field(ge=1)
    raw_score: float
    quantized_score: float
    query_split: str
    target_split: str
    mapping_scope: str
    is_self: bool
    passage_overlap: bool
    nearby_context: bool
    same_book: bool
    contains_english_derived_evidence: bool
    query_gloss_feature_count: int = Field(ge=0)
    target_gloss_feature_count: int = Field(ge=0)
    query_gloss_coverage: float = Field(ge=0.0, le=1.0)
    target_gloss_coverage: float = Field(ge=0.0, le=1.0)
    gloss_overlap_count: int = Field(ge=0)
    score_after_removing_all_english_features: float | None = None
    rank_after_removing_all_english_features: int | None = Field(default=None, ge=1)
    non_english_evidence_remains: bool
    english_ablation_survives: bool
    classification_after_english_ablation: str = Field(min_length=1)
    tie_break_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def ranking_is_directional_and_not_self(self) -> Self:
        if self.query_passage_id == self.target_passage_id or self.is_self:
            raise ValueError("persisted directional rankings cannot contain self-pairs")
        if self.tie_break_key != self.target_passage_id:
            raise ValueError("ranking tie_break_key must be the target passage ID")
        is_bridge = self.corpus_pair == "hb_gnt_english_bridge"
        if self.contains_english_derived_evidence != is_bridge:
            raise ValueError("only cross-testament bridge rankings may be English-derived")
        if is_bridge:
            if (
                self.score_after_removing_all_english_features != 0.0
                or self.rank_after_removing_all_english_features is not None
                or self.non_english_evidence_remains
                or self.english_ablation_survives
            ):
                raise ValueError(
                    "English-only bridge rankings must fail remove-all-English ablation"
                )
        elif (
            self.score_after_removing_all_english_features != self.raw_score
            or self.rank_after_removing_all_english_features != self.rank
            or not self.non_english_evidence_remains
            or not self.english_ablation_survives
        ):
            raise ValueError("original-language rankings must be unchanged by English ablation")
        return self


class CandidatePairRow(LexicalRow):
    candidate_pair_id: str = Field(min_length=1)
    canonical_unordered_pair_id: str = Field(min_length=1)
    experiment_run_id: str = Field(min_length=1)
    passage_a_id: str = Field(min_length=1)
    passage_b_id: str = Field(min_length=1)
    passage_a_reference: str = Field(min_length=1)
    passage_b_reference: str = Field(min_length=1)
    passage_a_book: str = Field(min_length=1)
    passage_b_book: str = Field(min_length=1)
    passage_a_reading: str = Field(min_length=1)
    passage_b_reading: str = Field(min_length=1)
    passage_a_token_count: int = Field(ge=0)
    passage_b_token_count: int = Field(ge=0)
    corpus_pair: Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
    analysis_profile: Literal["edition_complete", "critical_core"]
    granularity: Literal["clause", "sentence", "verse", "two_verse", "five_verse"]
    directional_support_count: int = Field(ge=1)
    detector_support_count: int = Field(ge=1)
    known_link_status: Literal[
        "represented_in_openbible_snapshot",
        "not_represented_in_openbible_snapshot",
        "mapping_unresolved",
    ]
    openbible_relationship_ids_json: str
    highest_openbible_vote: int | None
    benchmark_tier: int | None = Field(default=None, ge=1, le=3)
    mapping_quality: str
    disputed_passage_flag: bool
    reference_gap: bool
    ketiv_structural_uncertainty: bool
    direct_adjacency: bool
    nearby_context: bool
    same_book: bool
    exact_duplicate: bool
    near_exact_duplicate: bool
    formulaic_evidence_flag: bool
    genealogical_formula_pattern_flag: bool
    legal_formula_pattern_flag: bool
    formula_pattern_annotation_status: str = Field(min_length=1)
    proper_name_only_flag: bool
    proper_name_annotation_status: str = Field(min_length=1)
    contains_english_derived_evidence: bool
    passage_a_gloss_feature_count: int = Field(ge=0)
    passage_b_gloss_feature_count: int = Field(ge=0)
    passage_a_gloss_coverage: float = Field(ge=0.0, le=1.0)
    passage_b_gloss_coverage: float = Field(ge=0.0, le=1.0)
    gloss_overlap_count: int = Field(ge=0)
    score_with_english_features: float | None = None
    score_after_removing_all_english_features: float | None = None
    rank_with_english_features: int | None = Field(default=None, ge=1)
    rank_after_removing_all_english_features: int | None = Field(default=None, ge=1)
    non_english_evidence_remains: bool
    english_ablation_survives: bool
    classification_after_english_ablation: str = Field(min_length=1)
    review_eligible: bool
    eligibility_reason: str = Field(min_length=1)

    _relationships_are_array = field_validator("openbible_relationship_ids_json")(_json_array)

    @model_validator(mode="after")
    def pair_is_canonical_and_english_is_separate(self) -> Self:
        if self.passage_a_id >= self.passage_b_id:
            raise ValueError("candidate passage IDs must be distinct and canonically ordered")
        is_bridge = self.corpus_pair == "hb_gnt_english_bridge"
        if self.contains_english_derived_evidence != is_bridge:
            raise ValueError(
                "only the cross-testament gloss bridge is English-derived in Milestone 7"
            )
        if is_bridge and self.review_eligible and not self.english_ablation_survives:
            raise ValueError(
                "English-only evidence cannot be review-eligible after failed ablation"
            )
        if is_bridge and (
            self.score_with_english_features is None
            or self.score_after_removing_all_english_features != 0.0
            or self.rank_with_english_features is None
            or self.rank_after_removing_all_english_features is not None
            or self.non_english_evidence_remains
            or self.english_ablation_survives
        ):
            raise ValueError("bridge candidates require a complete failed English ablation")
        if self.proper_name_only_flag and self.proper_name_annotation_status != "available":
            raise ValueError(
                "proper-name-only cannot be inferred when source annotation is unavailable"
            )
        return self


class CandidateDetectorScoreRow(LexicalRow):
    candidate_pair_id: str = Field(min_length=1)
    detector: str = Field(min_length=1)
    representation_id: str = Field(min_length=1)
    score: float
    quantized_score: float
    direction: Literal["a_to_b", "b_to_a"]
    query_rank: int | None = Field(default=None, ge=1)
    reverse_rank: int | None = Field(default=None, ge=1)
    normalization_method: str = Field(min_length=1)
    score_contribution: float
    penalty_contribution: float
    adjusted_score: float
    score_components_json: str
    score_trace_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    _components_are_object = field_validator("score_components_json")(_json_object)


class CandidateEvidenceRow(LexicalRow):
    candidate_pair_id: str = Field(min_length=1)
    shared_lemma_count: int = Field(ge=0)
    shared_root_count: int = Field(ge=0)
    shared_surface_count: int = Field(ge=0)
    shared_rare_lemma_count: int = Field(ge=0)
    shared_rare_root_count: int = Field(ge=0)
    shared_phrase_count: int = Field(ge=0)
    shared_skipgram_count: int = Field(ge=0)
    lcs_length: int = Field(ge=0)
    normalized_lcs: float = Field(ge=0.0, le=1.0)
    weighted_alignment_score: float
    weighted_jaccard_score: float
    tfidf_score: float
    bm25_score: float
    rare_overlap_score: float
    phrase_score: float
    ordered_sequence_score: float
    raw_rrf_score: float
    rrf_score: float
    expected_overlap_independence: float = Field(ge=0.0)
    hypergeometric_p_value: float = Field(ge=0.0, le=1.0)
    benjamini_hochberg_q_value: float = Field(ge=0.0, le=1.0)
    hypergeometric_population_size: int = Field(ge=0)
    hypergeometric_success_states: int = Field(ge=0)
    hypergeometric_draws: int = Field(ge=0)
    hypergeometric_observed_overlap: int = Field(ge=0)
    hypothesis_family_id: str = Field(min_length=1)
    hypothesis_family_size: int = Field(ge=1)
    hypothesis_selection_scope: str = Field(min_length=1)
    null_model_empirical_rate: float = Field(ge=0.0)
    estimated_empirical_fdr: float = Field(ge=0.0)
    selected_score_threshold: float
    both_null_families_present: bool
    calibration_selection_scope: str = Field(min_length=1)
    independent_co_signal_count: int = Field(ge=0)
    rare_rule_passed: bool
    formulaic_penalty: float = Field(ge=0.0)
    local_context_penalty: float = Field(ge=0.0)
    short_passage_penalty: float = Field(ge=0.0)
    total_penalty_contribution: float = Field(le=0.0)
    overlap_exclusion: bool
    detector_trace_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    ablation_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class SharedEvidenceRow(LexicalRow):
    evidence_id: str = Field(min_length=1)
    candidate_pair_id: str = Field(min_length=1)
    evidence_family: str = Field(min_length=1)
    feature_id: str = Field(min_length=1)
    feature_value: str = Field(min_length=1)
    passage_a_positions_json: str
    passage_b_positions_json: str
    corpus_frequency: int = Field(ge=0)
    document_frequency: int = Field(ge=0)
    passage_a_local_frequency: int = Field(ge=0)
    passage_b_local_frequency: int = Field(ge=0)
    association_score: float
    pmi: float | None = None
    log_likelihood: float | None = None
    frequency_control: float | None = Field(default=None, ge=0.0)
    score_formula: str = Field(min_length=1)
    detector_contributions_json: str
    independence_expected_count: float = Field(ge=0.0)
    contains_primary_rare_item: bool
    counts_as_independent_co_signal: bool
    english_derived: bool
    notes: str

    _a_positions_array = field_validator("passage_a_positions_json")(_json_array)
    _b_positions_array = field_validator("passage_b_positions_json")(_json_array)
    _contributions_are_object = field_validator("detector_contributions_json")(_json_object)


class NullReplicateSummaryRow(LexicalRow):
    null_run_id: str = Field(min_length=1)
    experiment_run_id: str = Field(min_length=1)
    null_family: str = Field(min_length=1)
    iteration: int = Field(ge=0)
    seed: int = Field(ge=0)
    corpus_pair: Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
    representation_id: str = Field(min_length=1)
    detector: str = Field(min_length=1)
    threshold_id: str = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    mean_score: float
    score_quantiles_json: str
    conditioning_json: str
    passage_count: int = Field(ge=0)
    token_count: int = Field(ge=0)
    length_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    frequency_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    logical_output_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_seconds: float = Field(ge=0.0)

    _quantiles_are_object = field_validator("score_quantiles_json")(_json_object)
    _conditioning_is_object = field_validator("conditioning_json")(_json_object)


class ThresholdCalibrationRow(LexicalRow):
    threshold_id: str = Field(min_length=1)
    experiment_run_id: str = Field(min_length=1)
    corpus_pair: Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
    representation_id: str = Field(min_length=1)
    detector: str = Field(min_length=1)
    score_threshold: float
    observed_candidate_count: int = Field(ge=0)
    mean_null_candidate_count: float = Field(ge=0.0)
    null_interval_low: float = Field(ge=0.0)
    null_interval_high: float = Field(ge=0.0)
    observed_to_null_enrichment: float | None = None
    empirical_tail_probability: float = Field(ge=0.0, le=1.0)
    estimated_empirical_fdr: float | None = Field(default=None, ge=0.0)
    eligible_candidate_count: int = Field(ge=0)
    threshold_selection_scope: str = Field(min_length=1)
    qualifies_empirical_fdr: bool
    selected: bool
    selection_reason: str = Field(min_length=1)
    frozen_before_test: bool
    notes: str


class EvaluationResultRow(LexicalRow):
    evaluation_id: str = Field(min_length=1)
    experiment_run_id: str = Field(min_length=1)
    detector: str = Field(min_length=1)
    representation_id: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    benchmark_tier: Literal[3] = 3
    label_quality: str = Field(min_length=1)
    analysis_profile: Literal["edition_complete", "critical_core"]
    ranking_name: str = Field(min_length=1)
    ranking_role: Literal["system", "baseline"]
    comparison_baseline: str = Field(min_length=1)
    comparison_count: int = Field(ge=0)
    stratum_dimension: str = Field(min_length=1)
    stratum_value: str = Field(min_length=1)
    mapping_status: str = Field(min_length=1)
    corpus_pair: Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
    split_strategy: str = Field(min_length=1)
    partition: str = Field(min_length=1)
    vote_stratum: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    k: int | None = Field(default=None, ge=1)
    value: float
    bootstrap_interval_low: float
    bootstrap_interval_high: float
    bootstrap_iterations: int = Field(ge=1)
    bootstrap_seed: int = Field(ge=1)
    eligible_query_count: int = Field(ge=0)
    eligible_relationship_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    exclusion_reasons_json: str
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preregistration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    frozen_before_test: bool
    notes: str

    _exclusions_are_object = field_validator("exclusion_reasons_json")(_json_object)


class CandidateReviewQueueRow(LexicalRow):
    queue_rank: int = Field(ge=1)
    candidate_pair_id: str = Field(min_length=1)
    passage_a_reference: str = Field(min_length=1)
    passage_b_reference: str = Field(min_length=1)
    corpus_pair: Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
    raw_rrf_score: float
    rrf_score: float
    total_penalty_contribution: float = Field(le=0.0)
    detector_support_count: int = Field(ge=1)
    rare_rule_passed: bool
    estimated_empirical_fdr: float = Field(ge=0.0)
    known_link_status: Literal[
        "represented_in_openbible_snapshot",
        "not_represented_in_openbible_snapshot",
        "mapping_unresolved",
    ]
    contains_english_derived_evidence: bool
    english_ablation_survives: bool
    disputed_passage_flag: bool
    reference_gap: bool
    ketiv_structural_uncertainty: bool
    review_eligible: bool


class AblationResultRow(LexicalRow):
    """One preregistered score/removal result for a ranking or candidate."""

    ablation_result_id: str = Field(min_length=1)
    experiment_run_id: str = Field(min_length=1)
    ablation_name: Literal[
        "remove_tfidf",
        "remove_bm25",
        "remove_rare_evidence",
        "remove_phrase_evidence",
        "remove_ordered_sequence",
        "remove_formulaic_penalty",
        "remove_local_context_penalty",
        "remove_all_english_derived_features",
    ]
    subject_type: Literal["directional_ranking", "candidate_pair"]
    subject_id: str = Field(min_length=1)
    candidate_pair_id: str | None = None
    ranking_id: str | None = None
    corpus_pair: Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
    representation_id: str = Field(min_length=1)
    detector: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    query_passage_id: str = Field(min_length=1)
    target_passage_id: str = Field(min_length=1)
    query_gloss_feature_count: int = Field(ge=0)
    target_gloss_feature_count: int = Field(ge=0)
    query_token_count: int = Field(ge=0)
    target_token_count: int = Field(ge=0)
    query_gloss_coverage: float = Field(ge=0.0, le=1.0)
    target_gloss_coverage: float = Field(ge=0.0, le=1.0)
    gloss_overlap_count: int = Field(ge=0)
    score_before: float
    score_after: float | None = None
    rank_before: int | None = Field(default=None, ge=1)
    rank_after: int | None = Field(default=None, ge=1)
    penalty_before: float = Field(ge=0.0)
    penalty_after: float = Field(ge=0.0)
    contains_english_derived_evidence: bool
    non_english_evidence_remains: bool
    review_eligible_before: bool
    review_eligible_after: bool
    classification_before: str = Field(min_length=1)
    classification_after: str = Field(min_length=1)
    downgrade_required: bool
    changed: bool
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def subject_foreign_key_is_exact(self) -> Self:
        if self.subject_type == "directional_ranking":
            if self.ranking_id != self.subject_id or self.candidate_pair_id is not None:
                raise ValueError("directional ablations require only their ranking ID")
        elif self.candidate_pair_id != self.subject_id or self.ranking_id is not None:
            raise ValueError("candidate ablations require only their candidate-pair ID")
        if (
            self.ablation_name == "remove_all_english_derived_features"
            and self.contains_english_derived_evidence
            and (self.score_after != 0.0 or self.rank_after is not None)
        ):
            raise ValueError(
                "remove-all-English ablation must remove the English-only score and rank"
            )
        return self


class SensitivityResultRow(LexicalRow):
    """One paired profile/reading sensitivity result without source text."""

    sensitivity_id: str = Field(min_length=1)
    experiment_run_id: str = Field(min_length=1)
    sensitivity_type: Literal["critical_core_profile", "hebrew_qere_ketiv"]
    corpus_pair: Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
    detector: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    baseline_profile: str = Field(min_length=1)
    comparison_profile: str = Field(min_length=1)
    baseline_reading: str = Field(min_length=1)
    comparison_reading: str = Field(min_length=1)
    query_reference: str = Field(min_length=1)
    target_reference: str = Field(min_length=1)
    baseline_query_passage_id: str | None = None
    comparison_query_passage_id: str | None = None
    baseline_target_passage_id: str | None = None
    comparison_target_passage_id: str | None = None
    baseline_representation_id: str = Field(min_length=1)
    comparison_representation_id: str = Field(min_length=1)
    baseline_score: float | None = None
    comparison_score: float | None = None
    score_delta: float | None = None
    baseline_rank: int | None = Field(default=None, ge=1)
    comparison_rank: int | None = Field(default=None, ge=1)
    rank_delta: int | None = None
    top_k_overlap: float | None = Field(default=None, ge=0.0, le=1.0)
    affected_locus_count: int = Field(ge=0)
    excluded_reason: str | None = None
    baseline_sequence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    comparison_sequence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preregistration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class LexicalIssueRow(LexicalRow):
    issue_id: str = Field(min_length=1)
    severity: LexicalSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    artifact: str
    record_id: str
    experiment_run_id: str = Field(min_length=1)
    details_json: str

    _details_are_object = field_validator("details_json")(_json_object)


class LexicalMetadataRow(LexicalRow):
    experiment_run_id: str = Field(min_length=1)
    experiment_version: str = Field(min_length=1)
    lexical_schema_version: Literal[1] = 1
    candidate_pair_schema_version: Literal[1] = 1
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preregistration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_corpus_hashes_json: str
    passage_hashes_json: str
    benchmark_hashes_json: str
    feature_vocabulary_hashes_json: str
    sparse_index_hashes_json: str
    table_logical_hashes_json: str
    table_physical_hashes_json: str
    ranking_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    null_iteration_count: int = Field(ge=0)
    evaluation_count: int = Field(ge=0)
    runtime_seconds: float = Field(ge=0.0)
    stage_runtime_seconds_json: str
    peak_memory_bytes: int = Field(ge=0)
    storage_footprint_bytes: int = Field(ge=0)
    numerical_environment_json: str
    thread_controls_json: str
    acceptance_status: str = Field(min_length=1)
    notes: str

    _json_fields = field_validator(
        "input_corpus_hashes_json",
        "passage_hashes_json",
        "benchmark_hashes_json",
        "feature_vocabulary_hashes_json",
        "sparse_index_hashes_json",
        "table_logical_hashes_json",
        "table_physical_hashes_json",
        "numerical_environment_json",
        "thread_controls_json",
    )(_json_object)
    _stage_runtimes_are_nonnegative = field_validator("stage_runtime_seconds_json")(
        _runtime_seconds_object
    )


FEATURE_VOCABULARY_SCHEMA = pl.Schema(
    {
        "feature_id": pl.String,
        "lexical_schema_version": pl.Int16,
        "feature_family": pl.String,
        "language_namespace": pl.String,
        "feature_value": pl.String,
        "feature_order": pl.Int16,
        "corpus_frequency": pl.Int64,
        "document_frequency": pl.Int64,
        "inverse_document_frequency": pl.Float64,
        "book_frequency": pl.Int32,
        "genre_frequency": pl.Int32,
        "is_rare": pl.Boolean,
        "is_high_frequency": pl.Boolean,
        "is_formulaic": pl.Boolean,
        "contains_english_derived_content": pl.Boolean,
        "normalization_method": pl.String,
        "notes": pl.String,
    }
)

PASSAGE_FEATURE_STATISTICS_SCHEMA = pl.Schema(
    {
        "passage_id": pl.String,
        "analysis_profile": pl.String,
        "analysis_reading": pl.String,
        "granularity": pl.String,
        "corpus": pl.String,
        "book": pl.String,
        "token_count": pl.Int64,
        "eligible_token_count": pl.Int64,
        "distinct_lemma_count": pl.Int64,
        "distinct_root_count": pl.Int64,
        "distinct_surface_count": pl.Int64,
        "lemma_sequence_length": pl.Int64,
        "root_sequence_length": pl.Int64,
        "english_gloss_sequence_length": pl.Int64,
        "formulaic_feature_count": pl.Int64,
        "rare_feature_count": pl.Int64,
        "feature_vector_digest": pl.String,
        "source_passage_digest": pl.String,
    }
)

LEXICAL_INDEX_METADATA_SCHEMA = pl.Schema(
    {
        "index_id": pl.String,
        "experiment_run_id": pl.String,
        "representation_id": pl.String,
        "corpus_scope": pl.String,
        "profile": pl.String,
        "reading": pl.String,
        "granularity": pl.String,
        "feature_family": pl.String,
        "matrix_shape_json": pl.String,
        "nonzero_count": pl.Int64,
        "vocabulary_size": pl.Int64,
        "document_count": pl.Int64,
        "index_config_hash": pl.String,
        "logical_matrix_hash": pl.String,
        "physical_file_hash": pl.String,
        "dtype": pl.String,
        "storage_format": pl.String,
        "notes": pl.String,
    }
)

DIRECTIONAL_RANKINGS_SCHEMA = pl.Schema(
    {
        "ranking_id": pl.String,
        "experiment_run_id": pl.String,
        "query_passage_id": pl.String,
        "target_passage_id": pl.String,
        "corpus_pair": pl.String,
        "experiment_scope": pl.String,
        "analysis_profile": pl.String,
        "query_reading": pl.String,
        "target_reading": pl.String,
        "granularity": pl.String,
        "representation_id": pl.String,
        "detector": pl.String,
        "rank": pl.Int32,
        "raw_score": pl.Float64,
        "quantized_score": pl.Float64,
        "query_split": pl.String,
        "target_split": pl.String,
        "mapping_scope": pl.String,
        "is_self": pl.Boolean,
        "passage_overlap": pl.Boolean,
        "nearby_context": pl.Boolean,
        "same_book": pl.Boolean,
        "contains_english_derived_evidence": pl.Boolean,
        "query_gloss_feature_count": pl.Int64,
        "target_gloss_feature_count": pl.Int64,
        "query_gloss_coverage": pl.Float64,
        "target_gloss_coverage": pl.Float64,
        "gloss_overlap_count": pl.Int64,
        "score_after_removing_all_english_features": pl.Float64,
        "rank_after_removing_all_english_features": pl.Int32,
        "non_english_evidence_remains": pl.Boolean,
        "english_ablation_survives": pl.Boolean,
        "classification_after_english_ablation": pl.String,
        "tie_break_key": pl.String,
    }
)

CANDIDATE_PAIRS_SCHEMA = pl.Schema(
    {
        "candidate_pair_id": pl.String,
        "canonical_unordered_pair_id": pl.String,
        "experiment_run_id": pl.String,
        "passage_a_id": pl.String,
        "passage_b_id": pl.String,
        "passage_a_reference": pl.String,
        "passage_b_reference": pl.String,
        "passage_a_book": pl.String,
        "passage_b_book": pl.String,
        "passage_a_reading": pl.String,
        "passage_b_reading": pl.String,
        "passage_a_token_count": pl.Int64,
        "passage_b_token_count": pl.Int64,
        "corpus_pair": pl.String,
        "analysis_profile": pl.String,
        "granularity": pl.String,
        "directional_support_count": pl.Int16,
        "detector_support_count": pl.Int16,
        "known_link_status": pl.String,
        "openbible_relationship_ids_json": pl.String,
        "highest_openbible_vote": pl.Int64,
        "benchmark_tier": pl.Int8,
        "mapping_quality": pl.String,
        "disputed_passage_flag": pl.Boolean,
        "reference_gap": pl.Boolean,
        "ketiv_structural_uncertainty": pl.Boolean,
        "direct_adjacency": pl.Boolean,
        "nearby_context": pl.Boolean,
        "same_book": pl.Boolean,
        "exact_duplicate": pl.Boolean,
        "near_exact_duplicate": pl.Boolean,
        "formulaic_evidence_flag": pl.Boolean,
        "genealogical_formula_pattern_flag": pl.Boolean,
        "legal_formula_pattern_flag": pl.Boolean,
        "formula_pattern_annotation_status": pl.String,
        "proper_name_only_flag": pl.Boolean,
        "proper_name_annotation_status": pl.String,
        "contains_english_derived_evidence": pl.Boolean,
        "passage_a_gloss_feature_count": pl.Int64,
        "passage_b_gloss_feature_count": pl.Int64,
        "passage_a_gloss_coverage": pl.Float64,
        "passage_b_gloss_coverage": pl.Float64,
        "gloss_overlap_count": pl.Int64,
        "score_with_english_features": pl.Float64,
        "score_after_removing_all_english_features": pl.Float64,
        "rank_with_english_features": pl.Int64,
        "rank_after_removing_all_english_features": pl.Int64,
        "non_english_evidence_remains": pl.Boolean,
        "english_ablation_survives": pl.Boolean,
        "classification_after_english_ablation": pl.String,
        "review_eligible": pl.Boolean,
        "eligibility_reason": pl.String,
    }
)

CANDIDATE_DETECTOR_SCORES_SCHEMA = pl.Schema(
    {
        "candidate_pair_id": pl.String,
        "detector": pl.String,
        "representation_id": pl.String,
        "score": pl.Float64,
        "quantized_score": pl.Float64,
        "direction": pl.String,
        "query_rank": pl.Int32,
        "reverse_rank": pl.Int32,
        "normalization_method": pl.String,
        "score_contribution": pl.Float64,
        "penalty_contribution": pl.Float64,
        "adjusted_score": pl.Float64,
        "score_components_json": pl.String,
        "score_trace_digest": pl.String,
        "config_hash": pl.String,
    }
)

CANDIDATE_EVIDENCE_SCHEMA = pl.Schema(
    {
        "candidate_pair_id": pl.String,
        "shared_lemma_count": pl.Int32,
        "shared_root_count": pl.Int32,
        "shared_surface_count": pl.Int32,
        "shared_rare_lemma_count": pl.Int32,
        "shared_rare_root_count": pl.Int32,
        "shared_phrase_count": pl.Int32,
        "shared_skipgram_count": pl.Int32,
        "lcs_length": pl.Int32,
        "normalized_lcs": pl.Float64,
        "weighted_alignment_score": pl.Float64,
        "weighted_jaccard_score": pl.Float64,
        "tfidf_score": pl.Float64,
        "bm25_score": pl.Float64,
        "rare_overlap_score": pl.Float64,
        "phrase_score": pl.Float64,
        "ordered_sequence_score": pl.Float64,
        "raw_rrf_score": pl.Float64,
        "rrf_score": pl.Float64,
        "expected_overlap_independence": pl.Float64,
        "hypergeometric_p_value": pl.Float64,
        "benjamini_hochberg_q_value": pl.Float64,
        "hypergeometric_population_size": pl.Int64,
        "hypergeometric_success_states": pl.Int64,
        "hypergeometric_draws": pl.Int64,
        "hypergeometric_observed_overlap": pl.Int64,
        "hypothesis_family_id": pl.String,
        "hypothesis_family_size": pl.Int64,
        "hypothesis_selection_scope": pl.String,
        "null_model_empirical_rate": pl.Float64,
        "estimated_empirical_fdr": pl.Float64,
        "selected_score_threshold": pl.Float64,
        "both_null_families_present": pl.Boolean,
        "calibration_selection_scope": pl.String,
        "independent_co_signal_count": pl.Int32,
        "rare_rule_passed": pl.Boolean,
        "formulaic_penalty": pl.Float64,
        "local_context_penalty": pl.Float64,
        "short_passage_penalty": pl.Float64,
        "total_penalty_contribution": pl.Float64,
        "overlap_exclusion": pl.Boolean,
        "detector_trace_digest": pl.String,
        "ablation_digest": pl.String,
        "evidence_digest": pl.String,
    }
)

SHARED_EVIDENCE_SCHEMA = pl.Schema(
    {
        "evidence_id": pl.String,
        "candidate_pair_id": pl.String,
        "evidence_family": pl.String,
        "feature_id": pl.String,
        "feature_value": pl.String,
        "passage_a_positions_json": pl.String,
        "passage_b_positions_json": pl.String,
        "corpus_frequency": pl.Int64,
        "document_frequency": pl.Int64,
        "passage_a_local_frequency": pl.Int64,
        "passage_b_local_frequency": pl.Int64,
        "association_score": pl.Float64,
        "pmi": pl.Float64,
        "log_likelihood": pl.Float64,
        "frequency_control": pl.Float64,
        "score_formula": pl.String,
        "detector_contributions_json": pl.String,
        "independence_expected_count": pl.Float64,
        "contains_primary_rare_item": pl.Boolean,
        "counts_as_independent_co_signal": pl.Boolean,
        "english_derived": pl.Boolean,
        "notes": pl.String,
    }
)

NULL_REPLICATE_SUMMARIES_SCHEMA = pl.Schema(
    {
        "null_run_id": pl.String,
        "experiment_run_id": pl.String,
        "null_family": pl.String,
        "iteration": pl.Int32,
        "seed": pl.Int64,
        "corpus_pair": pl.String,
        "representation_id": pl.String,
        "detector": pl.String,
        "threshold_id": pl.String,
        "candidate_count": pl.Int64,
        "mean_score": pl.Float64,
        "score_quantiles_json": pl.String,
        "conditioning_json": pl.String,
        "passage_count": pl.Int64,
        "token_count": pl.Int64,
        "length_digest": pl.String,
        "frequency_digest": pl.String,
        "logical_output_hash": pl.String,
        "runtime_seconds": pl.Float64,
    }
)

THRESHOLD_CALIBRATION_SCHEMA = pl.Schema(
    {
        "threshold_id": pl.String,
        "experiment_run_id": pl.String,
        "corpus_pair": pl.String,
        "representation_id": pl.String,
        "detector": pl.String,
        "score_threshold": pl.Float64,
        "observed_candidate_count": pl.Int64,
        "mean_null_candidate_count": pl.Float64,
        "null_interval_low": pl.Float64,
        "null_interval_high": pl.Float64,
        "observed_to_null_enrichment": pl.Float64,
        "empirical_tail_probability": pl.Float64,
        "estimated_empirical_fdr": pl.Float64,
        "eligible_candidate_count": pl.Int64,
        "threshold_selection_scope": pl.String,
        "qualifies_empirical_fdr": pl.Boolean,
        "selected": pl.Boolean,
        "selection_reason": pl.String,
        "frozen_before_test": pl.Boolean,
        "notes": pl.String,
    }
)

EVALUATION_RESULTS_SCHEMA = pl.Schema(
    {
        "evaluation_id": pl.String,
        "experiment_run_id": pl.String,
        "detector": pl.String,
        "representation_id": pl.String,
        "benchmark_version": pl.String,
        "benchmark_tier": pl.Int8,
        "label_quality": pl.String,
        "analysis_profile": pl.String,
        "ranking_name": pl.String,
        "ranking_role": pl.String,
        "comparison_baseline": pl.String,
        "comparison_count": pl.Int64,
        "stratum_dimension": pl.String,
        "stratum_value": pl.String,
        "mapping_status": pl.String,
        "corpus_pair": pl.String,
        "split_strategy": pl.String,
        "partition": pl.String,
        "vote_stratum": pl.String,
        "metric": pl.String,
        "k": pl.Int32,
        "value": pl.Float64,
        "bootstrap_interval_low": pl.Float64,
        "bootstrap_interval_high": pl.Float64,
        "bootstrap_iterations": pl.Int32,
        "bootstrap_seed": pl.Int64,
        "eligible_query_count": pl.Int64,
        "eligible_relationship_count": pl.Int64,
        "excluded_count": pl.Int64,
        "exclusion_reasons_json": pl.String,
        "config_hash": pl.String,
        "preregistration_hash": pl.String,
        "frozen_before_test": pl.Boolean,
        "notes": pl.String,
    }
)

CANDIDATE_REVIEW_QUEUE_SCHEMA = pl.Schema(
    {
        "queue_rank": pl.Int64,
        "candidate_pair_id": pl.String,
        "passage_a_reference": pl.String,
        "passage_b_reference": pl.String,
        "corpus_pair": pl.String,
        "raw_rrf_score": pl.Float64,
        "rrf_score": pl.Float64,
        "total_penalty_contribution": pl.Float64,
        "detector_support_count": pl.Int16,
        "rare_rule_passed": pl.Boolean,
        "estimated_empirical_fdr": pl.Float64,
        "known_link_status": pl.String,
        "contains_english_derived_evidence": pl.Boolean,
        "english_ablation_survives": pl.Boolean,
        "disputed_passage_flag": pl.Boolean,
        "reference_gap": pl.Boolean,
        "ketiv_structural_uncertainty": pl.Boolean,
        "review_eligible": pl.Boolean,
    }
)

ABLATION_RESULTS_SCHEMA = pl.Schema(
    {
        "ablation_result_id": pl.String,
        "experiment_run_id": pl.String,
        "ablation_name": pl.String,
        "subject_type": pl.String,
        "subject_id": pl.String,
        "candidate_pair_id": pl.String,
        "ranking_id": pl.String,
        "corpus_pair": pl.String,
        "representation_id": pl.String,
        "detector": pl.String,
        "direction": pl.String,
        "query_passage_id": pl.String,
        "target_passage_id": pl.String,
        "query_gloss_feature_count": pl.Int64,
        "target_gloss_feature_count": pl.Int64,
        "query_token_count": pl.Int64,
        "target_token_count": pl.Int64,
        "query_gloss_coverage": pl.Float64,
        "target_gloss_coverage": pl.Float64,
        "gloss_overlap_count": pl.Int64,
        "score_before": pl.Float64,
        "score_after": pl.Float64,
        "rank_before": pl.Int64,
        "rank_after": pl.Int64,
        "penalty_before": pl.Float64,
        "penalty_after": pl.Float64,
        "contains_english_derived_evidence": pl.Boolean,
        "non_english_evidence_remains": pl.Boolean,
        "review_eligible_before": pl.Boolean,
        "review_eligible_after": pl.Boolean,
        "classification_before": pl.String,
        "classification_after": pl.String,
        "downgrade_required": pl.Boolean,
        "changed": pl.Boolean,
        "config_hash": pl.String,
        "evidence_digest": pl.String,
    }
)

SENSITIVITY_RESULTS_SCHEMA = pl.Schema(
    {
        "sensitivity_id": pl.String,
        "experiment_run_id": pl.String,
        "sensitivity_type": pl.String,
        "corpus_pair": pl.String,
        "detector": pl.String,
        "direction": pl.String,
        "baseline_profile": pl.String,
        "comparison_profile": pl.String,
        "baseline_reading": pl.String,
        "comparison_reading": pl.String,
        "query_reference": pl.String,
        "target_reference": pl.String,
        "baseline_query_passage_id": pl.String,
        "comparison_query_passage_id": pl.String,
        "baseline_target_passage_id": pl.String,
        "comparison_target_passage_id": pl.String,
        "baseline_representation_id": pl.String,
        "comparison_representation_id": pl.String,
        "baseline_score": pl.Float64,
        "comparison_score": pl.Float64,
        "score_delta": pl.Float64,
        "baseline_rank": pl.Int64,
        "comparison_rank": pl.Int64,
        "rank_delta": pl.Int64,
        "top_k_overlap": pl.Float64,
        "affected_locus_count": pl.Int64,
        "excluded_reason": pl.String,
        "baseline_sequence_digest": pl.String,
        "comparison_sequence_digest": pl.String,
        "config_hash": pl.String,
        "preregistration_hash": pl.String,
    }
)

LEXICAL_ISSUES_SCHEMA = pl.Schema(
    {
        "issue_id": pl.String,
        "severity": pl.String,
        "code": pl.String,
        "message": pl.String,
        "artifact": pl.String,
        "record_id": pl.String,
        "experiment_run_id": pl.String,
        "details_json": pl.String,
    }
)

LEXICAL_METADATA_SCHEMA = pl.Schema(
    {
        "experiment_run_id": pl.String,
        "experiment_version": pl.String,
        "lexical_schema_version": pl.Int16,
        "candidate_pair_schema_version": pl.Int16,
        "configuration_hash": pl.String,
        "preregistration_hash": pl.String,
        "input_corpus_hashes_json": pl.String,
        "passage_hashes_json": pl.String,
        "benchmark_hashes_json": pl.String,
        "feature_vocabulary_hashes_json": pl.String,
        "sparse_index_hashes_json": pl.String,
        "table_logical_hashes_json": pl.String,
        "table_physical_hashes_json": pl.String,
        "ranking_count": pl.Int64,
        "candidate_count": pl.Int64,
        "null_iteration_count": pl.Int64,
        "evaluation_count": pl.Int64,
        "runtime_seconds": pl.Float64,
        "stage_runtime_seconds_json": pl.String,
        "peak_memory_bytes": pl.Int64,
        "storage_footprint_bytes": pl.Int64,
        "numerical_environment_json": pl.String,
        "thread_controls_json": pl.String,
        "acceptance_status": pl.String,
        "notes": pl.String,
    }
)

type LexicalArtifactName = Literal[
    "feature_vocabulary",
    "passage_feature_statistics",
    "lexical_index_metadata",
    "directional_rankings",
    "candidate_pairs",
    "candidate_detector_scores",
    "candidate_evidence",
    "shared_evidence",
    "null_replicate_summaries",
    "threshold_calibration",
    "evaluation_results",
    "ablation_results",
    "sensitivity_results",
    "candidate_review_queue",
    "lexical_issues",
    "lexical_metadata",
]

LEXICAL_ARTIFACT_NAMES: tuple[LexicalArtifactName, ...] = (
    "feature_vocabulary",
    "passage_feature_statistics",
    "lexical_index_metadata",
    "directional_rankings",
    "candidate_pairs",
    "candidate_detector_scores",
    "candidate_evidence",
    "shared_evidence",
    "null_replicate_summaries",
    "threshold_calibration",
    "evaluation_results",
    "ablation_results",
    "sensitivity_results",
    "candidate_review_queue",
    "lexical_issues",
    "lexical_metadata",
)

LEXICAL_ARTIFACT_SCHEMAS: dict[LexicalArtifactName, pl.Schema] = {
    "feature_vocabulary": FEATURE_VOCABULARY_SCHEMA,
    "passage_feature_statistics": PASSAGE_FEATURE_STATISTICS_SCHEMA,
    "lexical_index_metadata": LEXICAL_INDEX_METADATA_SCHEMA,
    "directional_rankings": DIRECTIONAL_RANKINGS_SCHEMA,
    "candidate_pairs": CANDIDATE_PAIRS_SCHEMA,
    "candidate_detector_scores": CANDIDATE_DETECTOR_SCORES_SCHEMA,
    "candidate_evidence": CANDIDATE_EVIDENCE_SCHEMA,
    "shared_evidence": SHARED_EVIDENCE_SCHEMA,
    "null_replicate_summaries": NULL_REPLICATE_SUMMARIES_SCHEMA,
    "threshold_calibration": THRESHOLD_CALIBRATION_SCHEMA,
    "evaluation_results": EVALUATION_RESULTS_SCHEMA,
    "ablation_results": ABLATION_RESULTS_SCHEMA,
    "sensitivity_results": SENSITIVITY_RESULTS_SCHEMA,
    "candidate_review_queue": CANDIDATE_REVIEW_QUEUE_SCHEMA,
    "lexical_issues": LEXICAL_ISSUES_SCHEMA,
    "lexical_metadata": LEXICAL_METADATA_SCHEMA,
}

LEXICAL_ARTIFACT_COLUMNS: dict[LexicalArtifactName, tuple[str, ...]] = {
    name: tuple(schema) for name, schema in LEXICAL_ARTIFACT_SCHEMAS.items()
}

LEXICAL_ARTIFACT_SORT_COLUMNS: dict[LexicalArtifactName, tuple[str, ...]] = {
    "feature_vocabulary": ("feature_id",),
    "passage_feature_statistics": ("passage_id",),
    "lexical_index_metadata": ("index_id",),
    "directional_rankings": ("query_passage_id", "detector", "rank", "target_passage_id"),
    "candidate_pairs": ("candidate_pair_id",),
    "candidate_detector_scores": (
        "candidate_pair_id",
        "detector",
        "representation_id",
        "direction",
    ),
    "candidate_evidence": ("candidate_pair_id",),
    "shared_evidence": ("candidate_pair_id", "evidence_family", "evidence_id"),
    "null_replicate_summaries": (
        "null_family",
        "corpus_pair",
        "representation_id",
        "detector",
        "threshold_id",
        "iteration",
        "null_run_id",
    ),
    "threshold_calibration": (
        "corpus_pair",
        "representation_id",
        "detector",
        "threshold_id",
    ),
    "evaluation_results": (
        "analysis_profile",
        "corpus_pair",
        "representation_id",
        "stratum_dimension",
        "stratum_value",
        "split_strategy",
        "partition",
        "mapping_status",
        "vote_stratum",
        "detector",
        "metric",
        "k",
        "evaluation_id",
    ),
    "ablation_results": (
        "subject_type",
        "subject_id",
        "ablation_name",
        "ablation_result_id",
    ),
    "sensitivity_results": (
        "sensitivity_type",
        "corpus_pair",
        "detector",
        "direction",
        "sensitivity_id",
    ),
    "candidate_review_queue": ("queue_rank", "candidate_pair_id"),
    "lexical_issues": ("severity", "code", "issue_id"),
    "lexical_metadata": ("experiment_run_id",),
}

LEXICAL_ROW_MODELS: dict[LexicalArtifactName, type[LexicalRow]] = {
    "feature_vocabulary": FeatureVocabularyRow,
    "passage_feature_statistics": PassageFeatureStatisticsRow,
    "lexical_index_metadata": LexicalIndexMetadataRow,
    "directional_rankings": DirectionalRankingRow,
    "candidate_pairs": CandidatePairRow,
    "candidate_detector_scores": CandidateDetectorScoreRow,
    "candidate_evidence": CandidateEvidenceRow,
    "shared_evidence": SharedEvidenceRow,
    "null_replicate_summaries": NullReplicateSummaryRow,
    "threshold_calibration": ThresholdCalibrationRow,
    "evaluation_results": EvaluationResultRow,
    "ablation_results": AblationResultRow,
    "sensitivity_results": SensitivityResultRow,
    "candidate_review_queue": CandidateReviewQueueRow,
    "lexical_issues": LexicalIssueRow,
    "lexical_metadata": LexicalMetadataRow,
}

METADATA_NONDETERMINISTIC_COLUMNS = frozenset(
    {
        "runtime_seconds",
        "stage_runtime_seconds_json",
        "peak_memory_bytes",
        "storage_footprint_bytes",
        "table_physical_hashes_json",
    }
)
