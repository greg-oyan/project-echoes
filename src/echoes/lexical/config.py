"""Strict Milestone 7 lexical configuration and preregistration contracts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

LEXICAL_CONFIG_PATH = Path("config/lexical.yaml")
LEXICAL_PREREGISTRATION_PATH = Path("config/experiments/m7-lexical-baseline.yaml")

_SHA256_PATTERN = r"^[a-f0-9]{64}$"

CorpusName = Literal["hebrew", "greek"]
AnalysisProfile = Literal["edition_complete", "critical_core"]
AnalysisReading = Literal["qere", "ketiv", "source"]
Granularity = Literal["clause", "sentence", "verse", "two_verse", "five_verse"]
CorpusPair = Literal["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]
FeatureFamily = Literal[
    "lemma",
    "root",
    "normalized_surface",
    "part_of_speech",
    "morphology",
    "lemma_ngram",
    "root_ngram",
    "lemma_skipgram",
    "root_skipgram",
    "english_gloss",
]
DetectorName = Literal[
    "jaccard",
    "weighted_jaccard",
    "tfidf_cosine",
    "bm25",
    "rare_lemma_root",
    "phrase_association",
    "longest_common_subsequence",
    "weighted_sequence_alignment",
    "pos_morphology_support",
]


class LexicalConfigError(ValueError):
    """Raised when a lexical configuration cannot be loaded safely."""


class LexicalConfigModel(BaseModel):
    """Strict immutable base for governed lexical settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class PrimaryScopeConfig(LexicalConfigModel):
    """The only exhaustive Milestone 7 retrieval scope."""

    granularity: Literal["verse"]
    analysis_profile: Literal["edition_complete"]
    hebrew_reading: Literal["qere"]
    greek_reading: Literal["source"]


class EnabledReadingsConfig(LexicalConfigModel):
    """Governed primary reading streams."""

    hebrew: list[Literal["qere"]] = Field(min_length=1, max_length=1)
    greek: list[Literal["source"]] = Field(min_length=1, max_length=1)


class CriticalCoreSensitivityConfig(LexicalConfigModel):
    """Bounded profile sensitivity that is evaluated but never null-calibrated."""

    enabled: Literal[True]
    analysis_profile: Literal["critical_core"]
    hebrew_reading: Literal["qere"]
    greek_reading: Literal["source"]
    granularity: Literal["verse"]
    corpus_pairs: list[Literal["gnt_gnt", "hb_gnt_english_bridge"]] = Field(
        min_length=2, max_length=2
    )
    full_tier3_evaluation: Literal[True]
    repeated_nulls: Literal[False]

    @model_validator(mode="after")
    def governed_pairs_are_complete(self) -> Self:
        if self.corpus_pairs != ["gnt_gnt", "hb_gnt_english_bridge"]:
            raise ValueError("critical-core sensitivity must evaluate GNT and the English bridge")
        return self


class HebrewReadingSensitivityConfig(LexicalConfigModel):
    """Qere/Ketiv comparison confined to registered OSHB-affected verse loci."""

    enabled: Literal[True]
    analysis_profile: Literal["edition_complete"]
    baseline_reading: Literal["qere"]
    comparison_reading: Literal["ketiv"]
    granularity: Literal["verse"]
    corpus_pair: Literal["hb_hb"]
    query_scope: Literal["oshb_affected_verse_references"]
    target_scope: Literal["full_hebrew_verse_corpus"]
    repeated_nulls: Literal[False]


class SensitivityScopesConfig(LexicalConfigModel):
    """Required Milestone 7 sensitivity experiments outside the primary null scope."""

    critical_core_greek: CriticalCoreSensitivityConfig
    hebrew_qere_ketiv: HebrewReadingSensitivityConfig


class RepresentationConfig(LexicalConfigModel):
    """Transparent representations available to registered detectors."""

    original_language_lemma: Literal[True]
    original_language_root: Literal[True]
    normalized_surface: Literal[True]
    part_of_speech_sequence: Literal[True]
    morphology_sequence: Literal[True]
    english_gloss_bridge: Literal[True]
    original_and_english_composites_separate: Literal[True]


class FeatureNamespaceConfig(LexicalConfigModel):
    """Language-prefixed namespaces that prevent source-language conflation."""

    hebrew_lemma: Literal["hb:lemma"]
    hebrew_root: Literal["hb:root"]
    hebrew_surface: Literal["hb:surface"]
    hebrew_pos: Literal["hb:pos"]
    hebrew_morphology: Literal["hb:morph"]
    greek_lemma: Literal["gk:lemma"]
    greek_root: Literal["gk:root"]
    greek_surface: Literal["gk:surface"]
    greek_pos: Literal["gk:pos"]
    greek_morphology: Literal["gk:morph"]
    english_gloss: Literal["en:gloss"]
    require_language_prefix: Literal[True]
    direct_hebrew_greek_lemma_matching: Literal[False]


class TokenEligibilityConfig(LexicalConfigModel):
    """Rules for deriving features from authoritative passage membership."""

    use_authoritative_passage_membership: Literal[True]
    reparse_reconstructed_text: Literal[False]
    include_zero_width_in_membership: Literal[True]
    zero_width_contributes_lexical_feature: Literal[False]
    require_nonempty_feature_value: Literal[True]
    exclude_punctuation_only: Literal[True]
    preserve_source_positions: Literal[True]


class FrequencyScopeConfig(LexicalConfigModel):
    """Nonduplicating frequency and document scopes."""

    corpus_scope: Literal["language_and_representation"]
    document_scope: Literal["primary_verse_passage"]
    count_nonderived_token_stream_once: Literal[True]
    calculate_book_frequency: Literal[True]
    calculate_genre_frequency: Literal[True]
    mix_language_vocabularies: Literal[False]


class FeatureFrequencyThresholdConfig(LexicalConfigModel):
    """Configured high-frequency, formulaic, and proposal-index thresholds."""

    high_document_frequency_ratio: float = Field(gt=0.0, le=1.0)
    formulaic_document_frequency_ratio: float = Field(gt=0.0, le=1.0)
    formulaic_minimum_corpus_count: int = Field(ge=2)
    proposal_maximum_document_frequency_ratio: float = Field(gt=0.0, le=1.0)
    proposal_filter_preserves_persisted_evidence: Literal[True]

    @model_validator(mode="after")
    def thresholds_are_ordered(self) -> Self:
        if self.formulaic_document_frequency_ratio > self.high_document_frequency_ratio:
            raise ValueError("formulaic DF threshold cannot exceed high-frequency DF threshold")
        if self.high_document_frequency_ratio > self.proposal_maximum_document_frequency_ratio:
            raise ValueError("proposal maximum DF cannot be below high-frequency threshold")
        return self


class TfidfConfig(LexicalConfigModel):
    """Pinned sparse TF-IDF definition."""

    dtype: Literal["float64"]
    sublinear_tf: Literal[True]
    smooth_idf: Literal[True]
    norm: Literal["l2"]
    idf_formula: Literal["log((1+n_documents)/(1+document_frequency))+1"]


class Bm25Config(LexicalConfigModel):
    """Pinned BM25 definition."""

    dtype: Literal["float64"]
    k1: float = Field(gt=0.0)
    b: float = Field(ge=0.0, le=1.0)
    idf_formula: Literal["log(1+(n_documents-document_frequency+0.5)/(document_frequency+0.5))"]
    query_term_frequency: Literal["binary"]


class JaccardConfig(LexicalConfigModel):
    """Binary and IDF-weighted Jaccard behavior."""

    binary_enabled: Literal[True]
    weighted_enabled: Literal[True]
    weight: Literal["inverse_document_frequency"]
    empty_union_score: float = Field(ge=0.0, le=0.0)


class PhraseConfig(LexicalConfigModel):
    """Contiguous original-language phrase features and association scores."""

    lemma_ngram_sizes: list[Literal[2, 3]] = Field(min_length=2, max_length=2)
    root_ngram_sizes: list[Literal[2, 3]] = Field(min_length=2, max_length=2)
    minimum_corpus_count: int = Field(ge=2)
    pmi_cap: float = Field(gt=0.0)
    association_methods: list[Literal["pmi", "log_likelihood"]] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def phrase_contract_is_complete(self) -> Self:
        if self.lemma_ngram_sizes != [2, 3] or self.root_ngram_sizes != [2, 3]:
            raise ValueError("lemma and root n-gram sizes must be exactly [2, 3]")
        if self.association_methods != ["pmi", "log_likelihood"]:
            raise ValueError("phrase association methods must be PMI and log-likelihood")
        return self


class SkipgramConfig(LexicalConfigModel):
    """Bounded skip-gram generation."""

    enabled: Literal[True]
    maximum_gap: int = Field(ge=1)
    minimum_corpus_count: int = Field(ge=2)
    cross_passage_boundary: Literal[False]


class SequenceConfig(LexicalConfigModel):
    """Bounded sequence evidence applied only to retrieved candidates."""

    lcs_enabled: Literal[True]
    weighted_alignment_enabled: Literal[True]
    apply_only_to_candidate_union: Literal[True]
    match_weight: float = Field(gt=0.0)
    rarity_weight_enabled: Literal[True]
    pos_morphology_support_enabled: Literal[True]
    mismatch_penalty: float = Field(le=0.0)
    gap_penalty: float = Field(le=0.0)


class RetrievalConfig(LexicalConfigModel):
    """Sparse candidate-union and persistence depths."""

    candidate_union_k: int = Field(ge=1)
    persisted_top_k: int = Field(ge=1)
    evaluation_k: int = Field(ge=20)
    expensive_sequence_rerank_k: int = Field(ge=1)
    persisted_candidate_pool_k: int = Field(ge=1)
    sparse_only: Literal[True]
    dense_all_pairs_allowed: Literal[False]
    tie_break: Literal["score_desc_passage_id_asc"]

    @model_validator(mode="after")
    def depths_are_ordered(self) -> Self:
        if self.candidate_union_k < self.persisted_top_k:
            raise ValueError("candidate union K cannot be smaller than persisted top K")
        if self.persisted_top_k < self.evaluation_k:
            raise ValueError("persisted top K cannot be smaller than evaluation K")
        if self.expensive_sequence_rerank_k > self.candidate_union_k:
            raise ValueError("expensive sequence rerank K cannot exceed candidate union K")
        if self.persisted_candidate_pool_k > self.persisted_top_k:
            raise ValueError("persisted candidate pool K cannot exceed directional ranking K")
        if self.persisted_candidate_pool_k < self.expensive_sequence_rerank_k:
            raise ValueError("persisted candidate pool K cannot be below sequence rerank K")
        return self


class CompositeConfig(LexicalConfigModel):
    """Transparent reciprocal-rank fusion contract."""

    method: Literal["reciprocal_rank_fusion"]
    rrf_k: int = Field(gt=0)
    learned_model_allowed: Literal[False]
    preserve_detector_contributions: Literal[True]
    mix_english_with_original_language: Literal[False]


class RareEvidenceConfig(LexicalConfigModel):
    """Conjunctive rare-evidence guardrail."""

    maximum_corpus_frequency: int = Field(ge=1)
    threshold_source: Literal["configuration"]
    require_independent_co_signal: Literal[True]
    single_rare_item_sufficient: Literal[False]
    proper_name_only_sufficient: Literal[False]
    allowed_co_signals: list[
        Literal[
            "second_distinct_rare_lemma_or_root",
            "phrase_with_additional_lexical_material",
            "ordered_sequence_with_two_additional_features",
            "independent_pos_or_morphology_sequence",
            "non_restatement_detector_family",
        ]
    ] = Field(min_length=5, max_length=5)
    disallowed_correlated_signals: list[
        Literal[
            "tfidf_bm25_same_item",
            "lemma_surface_same_token",
            "rare_item_plus_removed_stop_feature",
            "lemma_root_same_item",
            "forward_reverse_same_evidence",
            "english_translation_same_item",
        ]
    ] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def co_signal_lists_are_complete_and_unique(self) -> Self:
        for name, values, expected in (
            ("allowed", self.allowed_co_signals, 5),
            ("disallowed", self.disallowed_correlated_signals, 6),
        ):
            if len(values) != len(set(values)) or len(values) != expected:
                raise ValueError(
                    f"{name} rare-evidence co-signal rules must be complete and unique"
                )
        return self


class NullFamilyConfig(LexicalConfigModel):
    """One registered deterministic repeated null family."""

    enabled: Literal[True]
    seed: int = Field(ge=1)
    method: Literal[
        "within_book_feature_token_reassignment",
        "frequency_preserving_synthetic_passages",
    ]
    preserve_passage_counts: Literal[True]
    preserve_passage_lengths: Literal[True]
    preserve_language_namespace: Literal[True]
    label_or_order_shuffle: Literal[False]


class NullModelsConfig(LexicalConfigModel):
    """Both mandatory null families and their conditioning contracts."""

    iterations_per_family: int = Field(ge=100)
    calibration_pair_sample_size: int = Field(ge=1000)
    calibration_pair_scope: Literal["deterministic_candidate_union_sample"]
    global_all_pairs_calibration_claim_allowed: Literal[False]
    within_book_reassignment: NullFamilyConfig
    frequency_preserving_synthetic: NullFamilyConfig
    english_features_reassigned_by_source_corpus_and_book: Literal[True]
    synthetic_primary_conditioning: Literal["book_then_genre_when_sparse"]
    synthetic_minimum_book_token_count: int = Field(ge=1)
    retain_every_replicate: Literal[True]

    @model_validator(mode="after")
    def null_families_are_distinct_and_correct(self) -> Self:
        if self.within_book_reassignment.method != "within_book_feature_token_reassignment":
            raise ValueError("within-book null must reassign feature tokens")
        if self.frequency_preserving_synthetic.method != "frequency_preserving_synthetic_passages":
            raise ValueError("synthetic null must generate frequency-preserving passages")
        if self.within_book_reassignment.seed == self.frequency_preserving_synthetic.seed:
            raise ValueError("null family seeds must be distinct")
        return self


class StatisticsConfig(LexicalConfigModel):
    """Calibration, resampling, multiplicity, and numeric stability settings."""

    bootstrap_iterations: int = Field(ge=1000)
    bootstrap_seed: int = Field(ge=1)
    multiple_testing: Literal["benjamini_hochberg"]
    score_quantization_decimals: int = Field(ge=1, le=15)
    empirical_tail_correction: Literal["(exceedances+1)/(iterations+1)"]
    estimated_empirical_fdr: Literal["mean_null_count/observed_count"]
    hypergeometric_role: Literal["analytical_baseline_only"]
    empirical_null_has_priority: Literal[True]


class ThresholdConfig(LexicalConfigModel):
    """Preregistered threshold-selection grid and queue freeze rule."""

    selection_method: Literal["preregistered_grid_with_empirical_fdr"]
    detector_score_grid: list[float] = Field(min_length=1)
    rrf_score_grid: list[float] = Field(min_length=1)
    maximum_empirical_fdr: float = Field(gt=0.0, le=1.0)
    require_both_null_families: Literal[True]
    calibrate_every_threshold: Literal[True]
    inspect_candidate_identities_before_selection: Literal[False]
    weaken_to_meet_queue_quota: Literal[False]
    freeze_before_queue: Literal[True]

    @model_validator(mode="after")
    def threshold_grid_is_strictly_increasing(self) -> Self:
        if any(value < 0.0 for value in self.detector_score_grid):
            raise ValueError("detector threshold values must be nonnegative")
        if self.detector_score_grid != sorted(set(self.detector_score_grid)):
            raise ValueError("detector threshold grid must be strictly increasing and unique")
        if any(value < 0.0 for value in self.rrf_score_grid):
            raise ValueError("RRF threshold values must be nonnegative")
        if self.rrf_score_grid != sorted(set(self.rrf_score_grid)):
            raise ValueError("RRF threshold grid must be strictly increasing and unique")
        return self


class EnglishFeaturesConfig(LexicalConfigModel):
    """English-derived bridge labeling and ablation controls."""

    source: Literal["macula_english_gloss"]
    namespace: Literal["en:gloss"]
    evidence_class: Literal["english_derived"]
    mark_all_derived_evidence: Literal[True]
    require_ablation: Literal[True]
    permit_unablated_strong_label: Literal[False]
    report_separately_from_original_language: Literal[True]


class AblationPolicyConfig(LexicalConfigModel):
    """Detector and penalty ablations fixed before held-out evaluation."""

    names: list[
        Literal[
            "remove_tfidf",
            "remove_bm25",
            "remove_rare_evidence",
            "remove_phrase_evidence",
            "remove_ordered_sequence",
            "remove_formulaic_penalty",
            "remove_local_context_penalty",
            "remove_all_english_derived_features",
        ]
    ] = Field(min_length=8, max_length=8)
    select_new_model_from_ablation_results: Literal[False]

    @model_validator(mode="after")
    def ablations_are_unique(self) -> Self:
        if len(self.names) != len(set(self.names)):
            raise ValueError("preregistered ablations must be unique")
        return self


class PenaltyConfig(LexicalConfigModel):
    """Explicit penalties and inspectable exclusion flags."""

    preserve_raw_scores: Literal[True]
    formulaic_penalty: float = Field(ge=0.0, le=1.0)
    local_context_penalty: float = Field(ge=0.0, le=1.0)
    short_passage_penalty: float = Field(ge=0.0, le=1.0)
    nearby_verse_distance: int = Field(ge=1)
    short_passage_token_count: int = Field(ge=1)
    self_pairs: Literal["exclude"]
    exact_overlap: Literal["exclude"]
    overlapping_windows: Literal["exclude"]
    adjacency: Literal["retain_flag_normally_ineligible"]
    same_book: Literal["retain_flag"]
    formulaic: Literal["retain_score_and_penalty"]
    disputed_text: Literal["retain_flag_require_sensitivity"]
    reference_gap: Literal["retain_flag"]
    ketiv_uncertainty: Literal["retain_flag"]


class BenchmarkEvaluationConfig(LexicalConfigModel):
    """Tier 3-only, leakage-aware recovery contract."""

    source_id: Literal["openbible-cross-references"]
    tier: Literal[3]
    role: Literal["tier3_weak_supervision_recovery"]
    primary_evaluation_eligible: Literal[False]
    high_confidence_benchmark: Literal[False]
    eligible_mapping_statuses: list[
        Literal["mapped_verified", "mapped_provisional", "mapped_partial"]
    ] = Field(min_length=1)
    split_strategies: list[
        Literal[
            "held_out_book",
            "held_out_book_pair",
            "held_out_source_passage",
            "held_out_genre",
        ]
    ] = Field(min_length=4, max_length=4)
    enforce_governed_splits: Literal[True]
    enforce_leakage_groups: Literal[True]
    test_set_tuning_allowed: Literal[False]
    votes_are_calibrated_confidence: Literal[False]
    presumed_negatives_are_proven_negatives: Literal[False]
    minimum_eligible_queries_per_primary_stratum: int = Field(ge=1)
    minimum_eligible_relationships_per_primary_stratum: int = Field(ge=1)
    insufficient_stratum_action: Literal["report_no_claim_and_exempt_composite_gate"]

    @model_validator(mode="after")
    def governed_splits_are_complete(self) -> Self:
        expected = [
            "held_out_book",
            "held_out_book_pair",
            "held_out_source_passage",
            "held_out_genre",
        ]
        if self.split_strategies != expected:
            raise ValueError("all governed benchmark split strategies must be configured")
        if len(self.eligible_mapping_statuses) != len(set(self.eligible_mapping_statuses)):
            raise ValueError("eligible mapping statuses must be unique")
        return self


class OutputConfig(LexicalConfigModel):
    """Atomic local artifact layout."""

    format: Literal["parquet"]
    schema_directory: Literal["data/processed/lexical/schema-v1"]
    partition_by: list[
        Literal["analysis_profile", "granularity", "corpus_pair", "representation", "detector"]
    ] = Field(min_length=1)
    compression: Literal["zstd"]
    atomic_writes: Literal[True]
    overwrite_requires_force: Literal[True]
    include_local_paths_in_logical_identity: Literal[False]
    include_runtime_in_logical_identity: Literal[False]

    @model_validator(mode="after")
    def partitions_are_unique(self) -> Self:
        if len(self.partition_by) != len(set(self.partition_by)):
            raise ValueError("lexical output partition fields must be unique")
        return self


class ValidationSeverityConfig(LexicalConfigModel):
    """Strict lexical validation failure policy."""

    allowed_severities: list[Literal["error", "warning", "informational"]] = Field(
        min_length=3, max_length=3
    )
    errors_fail_validation: Literal[True]
    warnings_fail_strict_validation: Literal[True]
    informational_fail_validation: Literal[False]

    @model_validator(mode="after")
    def severity_order_is_fixed(self) -> Self:
        if self.allowed_severities != ["error", "warning", "informational"]:
            raise ValueError("lexical severities must be error, warning, informational")
        return self


class ResourceLimitsConfig(LexicalConfigModel):
    """Positive local resource ceilings checked before full builds."""

    maximum_memory_bytes: int = Field(gt=0)
    minimum_free_disk_bytes: int = Field(gt=0)
    block_passage_count: int = Field(gt=0)
    thread_count: int = Field(gt=0)
    check_disk_before_build: Literal[True]


class LexicalConfig(LexicalConfigModel):
    """Complete governed Milestone 7 lexical configuration."""

    schema_version: Literal[1]
    candidate_pair_schema_version: Literal[1]
    representation_schema_version: Literal[1]
    ranking_schema_version: Literal[1]
    experiment_version: Literal["m7-lexical-baseline-v1"]
    status: Literal["active"]
    enabled_corpora: list[CorpusName] = Field(min_length=2, max_length=2)
    enabled_profiles: list[Literal["edition_complete"]] = Field(min_length=1, max_length=1)
    enabled_readings: EnabledReadingsConfig
    primary_scope: PrimaryScopeConfig
    sensitivity_scopes: SensitivityScopesConfig
    smoke_test_granularities: list[Literal["clause", "sentence", "two_verse", "five_verse"]] = (
        Field(min_length=4, max_length=4)
    )
    feature_families: list[FeatureFamily] = Field(min_length=10, max_length=10)
    enabled_detectors: list[DetectorName] = Field(min_length=9, max_length=9)
    representations: RepresentationConfig
    feature_namespaces: FeatureNamespaceConfig
    token_eligibility: TokenEligibilityConfig
    frequency_scopes: FrequencyScopeConfig
    feature_frequency_thresholds: FeatureFrequencyThresholdConfig
    tfidf: TfidfConfig
    bm25: Bm25Config
    jaccard: JaccardConfig
    phrases: PhraseConfig
    skipgrams: SkipgramConfig
    sequence: SequenceConfig
    retrieval: RetrievalConfig
    composite: CompositeConfig
    rare_evidence: RareEvidenceConfig
    null_models: NullModelsConfig
    statistics: StatisticsConfig
    candidate_thresholds: ThresholdConfig
    english_features: EnglishFeaturesConfig
    ablations: AblationPolicyConfig
    penalties: PenaltyConfig
    benchmark_evaluation: BenchmarkEvaluationConfig
    output: OutputConfig
    validation_severity_policy: ValidationSeverityConfig
    resource_limits: ResourceLimitsConfig

    @model_validator(mode="after")
    def complete_contract_is_coherent(self) -> Self:
        if self.enabled_corpora != ["hebrew", "greek"]:
            raise ValueError("enabled corpora must be Hebrew then Greek")
        if self.enabled_profiles != ["edition_complete"]:
            raise ValueError("edition_complete must be the only exhaustive lexical profile")
        if self.sensitivity_scopes.critical_core_greek.repeated_nulls:
            raise ValueError("critical-core sensitivity must not repeat primary null simulations")
        if self.sensitivity_scopes.hebrew_qere_ketiv.repeated_nulls:
            raise ValueError("Qere/Ketiv sensitivity must not repeat primary null simulations")
        if self.smoke_test_granularities != ["clause", "sentence", "two_verse", "five_verse"]:
            raise ValueError("all and only four non-primary granularities must be smoke tested")
        required_families: set[FeatureFamily] = {
            "lemma",
            "root",
            "normalized_surface",
            "part_of_speech",
            "morphology",
            "lemma_ngram",
            "root_ngram",
            "lemma_skipgram",
            "root_skipgram",
            "english_gloss",
        }
        if len(self.feature_families) != len(set(self.feature_families)):
            raise ValueError("lexical feature families must be unique")
        if set(self.feature_families) != required_families:
            raise ValueError("all governed lexical feature families must be configured")
        if len(self.enabled_detectors) != len(set(self.enabled_detectors)):
            raise ValueError("enabled lexical detectors must be unique")
        return self


class CorpusAnchor(LexicalConfigModel):
    """One immutable upstream corpus identity triple."""

    token_count: int = Field(gt=0)
    identity_sha256: str = Field(pattern=_SHA256_PATTERN)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)
    analytical_sha256: str = Field(pattern=_SHA256_PATTERN)


class PassageAnchor(LexicalConfigModel):
    """Validated passage run and six logical hashes."""

    run_id: Literal["passages-v1-00e261abea9ed44ef087"]
    passage_count: Literal[914497]
    membership_count: Literal[21530271]
    adjacency_count: Literal[913445]
    exclusion_count: Literal[148948]
    logical_hashes: dict[str, str]

    @model_validator(mode="after")
    def six_passage_hashes_are_named_and_valid(self) -> Self:
        expected = {
            "passages",
            "passage_membership",
            "passage_adjacency",
            "segmentation_exclusions",
            "segmentation_issues",
            "segmentation_metadata",
        }
        if set(self.logical_hashes) != expected:
            raise ValueError("all six passage logical hashes must be frozen")
        if any(
            re.fullmatch(_SHA256_PATTERN, value) is None for value in self.logical_hashes.values()
        ):
            raise ValueError("passage logical hashes must be lowercase SHA-256 digests")
        return self


class BenchmarkAnchor(LexicalConfigModel):
    """Validated Tier 3 benchmark run and ten logical hashes."""

    run_id: Literal["benchmark-v1-dff1d3ef650c8ccd4930"]
    version: Literal["known-links-v1-dff1d3ef650c"]
    tier1_row_count: Literal[0]
    logical_hashes: dict[str, str]

    @model_validator(mode="after")
    def ten_benchmark_hashes_are_named_and_valid(self) -> Self:
        expected = {
            "benchmark_source_records",
            "benchmark_relationships",
            "benchmark_relationship_source_records",
            "benchmark_endpoints",
            "benchmark_endpoint_mappings",
            "benchmark_leakage_groups",
            "benchmark_split_assignments",
            "benchmark_presumed_negatives",
            "benchmark_issues",
            "benchmark_metadata",
        }
        if set(self.logical_hashes) != expected:
            raise ValueError("all ten benchmark logical hashes must be frozen")
        if any(
            re.fullmatch(_SHA256_PATTERN, value) is None for value in self.logical_hashes.values()
        ):
            raise ValueError("benchmark logical hashes must be lowercase SHA-256 digests")
        return self


class PreregisteredInputs(LexicalConfigModel):
    """Every upstream identity frozen before held-out evaluation."""

    hebrew: CorpusAnchor
    greek: CorpusAnchor
    oshb_supplement_hashes: dict[str, str]
    passages: PassageAnchor
    benchmark: BenchmarkAnchor

    @model_validator(mode="after")
    def oshb_hashes_are_complete(self) -> Self:
        if set(self.oshb_supplement_hashes) != {
            "ketiv_tokens",
            "locus_registry",
            "structural_alignments",
        }:
            raise ValueError("all three OSHB supplement hashes must be frozen")
        if any(
            re.fullmatch(_SHA256_PATTERN, value) is None
            for value in self.oshb_supplement_hashes.values()
        ):
            raise ValueError("OSHB hashes must be lowercase SHA-256 digests")
        return self


class PreregisteredScope(LexicalConfigModel):
    """Frozen exhaustive and bounded smoke-test scope."""

    profile: Literal["edition_complete"]
    granularity: Literal["verse"]
    hebrew_reading: Literal["qere"]
    greek_reading: Literal["source"]
    corpus_pairs: list[CorpusPair] = Field(min_length=3, max_length=3)
    smoke_test_granularities: list[Literal["clause", "sentence", "two_verse", "five_verse"]] = (
        Field(min_length=4, max_length=4)
    )
    exhaustive_smoke_test_calibration_allowed: Literal[False]


class PreregisteredBenchmark(LexicalConfigModel):
    """Frozen Tier 3 strata, splits, labels, and recovery metrics."""

    included_tiers: list[Literal[3]] = Field(min_length=1, max_length=1)
    eligible_mapping_statuses: list[
        Literal["mapped_verified", "mapped_provisional", "mapped_partial"]
    ] = Field(min_length=1)
    split_strategies: list[
        Literal[
            "held_out_book",
            "held_out_book_pair",
            "held_out_source_passage",
            "held_out_genre",
        ]
    ] = Field(min_length=4, max_length=4)
    vote_strata: list[
        Literal[
            "negative",
            "zero",
            "one_to_two",
            "three_to_five",
            "six_to_ten",
            "eleven_to_twenty_five",
            "twenty_six_plus",
        ]
    ] = Field(min_length=7, max_length=7)
    metrics: list[
        Literal[
            "recall_at_5",
            "recall_at_10",
            "recall_at_20",
            "mean_reciprocal_rank",
            "ndcg_at_20",
            "precision_at_10",
            "coverage",
        ]
    ] = Field(min_length=7, max_length=7)
    comparison_baselines: list[
        Literal["random", "length_matched", "unweighted_overlap", "presumed_negatives"]
    ] = Field(min_length=4, max_length=4)
    enforce_leakage_groups: Literal[True]
    label: Literal["tier3_weak_supervision_recovery"]
    minimum_eligible_queries_per_primary_stratum: int = Field(ge=1)
    minimum_eligible_relationships_per_primary_stratum: int = Field(ge=1)
    insufficient_stratum_action: Literal["report_no_claim_and_exempt_composite_gate"]

    @model_validator(mode="after")
    def frozen_strata_are_complete_and_unique(self) -> Self:
        expected_splits = [
            "held_out_book",
            "held_out_book_pair",
            "held_out_source_passage",
            "held_out_genre",
        ]
        if self.split_strategies != expected_splits:
            raise ValueError("preregistration must freeze every governed split strategy")
        for field_name in (
            "eligible_mapping_statuses",
            "vote_strata",
            "metrics",
            "comparison_baselines",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"preregistered {field_name} values must be unique")
        return self


class PreregisteredExclusions(LexicalConfigModel):
    """Frozen pair and evaluation exclusions."""

    self_pairs: Literal["exclude"]
    exact_overlap: Literal["exclude"]
    overlapping_windows: Literal["exclude"]
    mapping_ineligible: Literal["exclude_with_reason"]
    unresolved_data_error: Literal["exclude_with_reason"]
    represented_openbible_pairs_from_unreviewed_queue: Literal["exclude_either_direction"]
    retain_all_excluded_candidates_with_reason: Literal[True]


class LexicalExperimentPreregistration(LexicalConfigModel):
    """Immutable machine-readable Milestone 7 held-out evaluation declaration."""

    schema_version: Literal[1]
    experiment_name: Literal["m7_lexical_baseline"]
    experiment_version: Literal["m7-lexical-baseline-v1"]
    status: Literal["frozen"]
    frozen_before_held_out_evaluation: Literal[True]
    preregistration_sha256: str = Field(pattern=_SHA256_PATTERN)
    lexical_config_path: Literal["config/lexical.yaml"]
    lexical_config_sha256: str = Field(pattern=_SHA256_PATTERN)
    inputs: PreregisteredInputs
    scope: PreregisteredScope
    sensitivity_scopes: SensitivityScopesConfig
    representations: list[
        Literal[
            "original_language_lemma",
            "original_language_root",
            "normalized_surface",
            "part_of_speech_sequence",
            "morphology_sequence",
            "english_gloss_bridge",
        ]
    ] = Field(min_length=6, max_length=6)
    detectors: list[DetectorName] = Field(min_length=9, max_length=9)
    feature_frequency_thresholds: FeatureFrequencyThresholdConfig
    tfidf: TfidfConfig
    bm25: Bm25Config
    jaccard: JaccardConfig
    phrases: PhraseConfig
    skipgrams: SkipgramConfig
    sequence: SequenceConfig
    retrieval: RetrievalConfig
    composite: CompositeConfig
    score_quantization_decimals: int = Field(ge=1, le=15)
    benchmark: PreregisteredBenchmark
    bootstrap_iterations: int = Field(ge=1000)
    bootstrap_seed: int = Field(ge=1)
    null_models: NullModelsConfig
    candidate_thresholds: ThresholdConfig
    rare_evidence: RareEvidenceConfig
    penalties: PenaltyConfig
    ablations: AblationPolicyConfig
    exclusions: PreregisteredExclusions
    held_out_test_tuning_allowed: Literal[False]
    failed_results_are_preserved: Literal[True]
    methodological_change_requires_new_experiment_version: Literal[True]

    @model_validator(mode="after")
    def preregistration_is_complete_and_self_authenticating(self) -> Self:
        if len(self.representations) != len(set(self.representations)):
            raise ValueError("preregistered representations must be unique")
        if len(self.detectors) != len(set(self.detectors)):
            raise ValueError("preregistered detectors must be unique")
        if self.scope.corpus_pairs != ["hb_hb", "gnt_gnt", "hb_gnt_english_bridge"]:
            raise ValueError("all primary corpus-pair strata must be preregistered")
        expected_digest = _sha256_json(
            self.model_dump(mode="json", exclude={"preregistration_sha256"})
        )
        if self.preregistration_sha256 != expected_digest:
            raise ValueError("preregistration_sha256 does not match the canonical frozen payload")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def canonical_lexical_config_json(config: LexicalConfig) -> str:
    """Return YAML-order-independent canonical JSON for governed lexical settings."""

    return _canonical_json(config.model_dump(mode="json"))


def lexical_config_sha256(config: LexicalConfig) -> str:
    """Hash only validated governed lexical settings, never local YAML formatting."""

    return hashlib.sha256(canonical_lexical_config_json(config).encode("utf-8")).hexdigest()


def canonical_lexical_preregistration_json(
    preregistration: LexicalExperimentPreregistration,
) -> str:
    """Return the canonical frozen preregistration payload, excluding its own digest."""

    return _canonical_json(
        preregistration.model_dump(mode="json", exclude={"preregistration_sha256"})
    )


def lexical_preregistration_sha256(
    preregistration: LexicalExperimentPreregistration,
) -> str:
    """Recompute the digest the held-out evaluation command must require."""

    return hashlib.sha256(
        canonical_lexical_preregistration_json(preregistration).encode("utf-8")
    ).hexdigest()


def preregistration_payload_sha256(values: dict[str, Any]) -> str:
    """Compute a declared digest from raw payload values before model construction."""

    payload = {key: value for key, value in values.items() if key != "preregistration_sha256"}
    return _sha256_json(payload)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise LexicalConfigError(f"configuration file does not exist: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise LexicalConfigError(f"could not parse {path}: {exc}") from exc
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise LexicalConfigError(f"configuration root must be a string-keyed mapping: {path}")
    return cast(dict[str, Any], loaded)


def load_lexical_config(path: Path = LEXICAL_CONFIG_PATH) -> LexicalConfig:
    """Load and strictly validate the governed lexical configuration."""

    try:
        return LexicalConfig.model_validate(_load_yaml_mapping(path))
    except ValidationError as exc:
        raise LexicalConfigError(f"validation failed for {path}:\n{exc}") from exc


def load_lexical_preregistration(
    path: Path = LEXICAL_PREREGISTRATION_PATH,
) -> LexicalExperimentPreregistration:
    """Load and authenticate the frozen held-out evaluation preregistration."""

    try:
        return LexicalExperimentPreregistration.model_validate(_load_yaml_mapping(path))
    except ValidationError as exc:
        raise LexicalConfigError(f"validation failed for {path}:\n{exc}") from exc


def validate_preregistration_against_config(
    preregistration: LexicalExperimentPreregistration,
    config: LexicalConfig,
) -> None:
    """Fail if the frozen preregistration no longer describes the active config."""

    expected_config_digest = lexical_config_sha256(config)
    if preregistration.lexical_config_sha256 != expected_config_digest:
        raise LexicalConfigError(
            "frozen preregistration lexical_config_sha256 does not match active lexical config"
        )
    if preregistration.score_quantization_decimals != config.statistics.score_quantization_decimals:
        raise LexicalConfigError("preregistered score quantization differs from active config")
    for name in (
        "tfidf",
        "bm25",
        "jaccard",
        "phrases",
        "skipgrams",
        "sequence",
        "retrieval",
        "composite",
        "null_models",
        "candidate_thresholds",
        "rare_evidence",
        "penalties",
        "feature_frequency_thresholds",
        "ablations",
    ):
        if getattr(preregistration, name) != getattr(config, name):
            raise LexicalConfigError(f"preregistered {name} differs from active config")
    if preregistration.bootstrap_iterations != config.statistics.bootstrap_iterations:
        raise LexicalConfigError("preregistered bootstrap iterations differ from active config")
    if preregistration.bootstrap_seed != config.statistics.bootstrap_seed:
        raise LexicalConfigError("preregistered bootstrap seed differs from active config")
    if preregistration.detectors != config.enabled_detectors:
        raise LexicalConfigError("preregistered detectors differ from active config")
    if preregistration.sensitivity_scopes != config.sensitivity_scopes:
        raise LexicalConfigError("preregistered sensitivity scopes differ from active config")
    if preregistration.benchmark.split_strategies != config.benchmark_evaluation.split_strategies:
        raise LexicalConfigError("preregistered split strategies differ from active config")
    for field_name in (
        "minimum_eligible_queries_per_primary_stratum",
        "minimum_eligible_relationships_per_primary_stratum",
        "insufficient_stratum_action",
    ):
        if getattr(preregistration.benchmark, field_name) != getattr(
            config.benchmark_evaluation, field_name
        ):
            raise LexicalConfigError(
                f"preregistered benchmark {field_name} differs from active config"
            )
