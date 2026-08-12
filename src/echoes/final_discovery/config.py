"""Strict preregistration schema for the consolidated final-discovery campaign."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

FINAL_DISCOVERY_EXPERIMENT = "final-discovery-v1"
DEFAULT_FINAL_DISCOVERY_CONFIG = Path("config/experiments/final-discovery-v1.yaml")


class FinalDiscoveryConfigError(ValueError):
    """Raised when the final-discovery preregistration is absent or invalid."""


class FrozenModel(BaseModel):
    """Reject undocumented preregistration keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class InputArtifact(FrozenModel):
    artifact_id: str = Field(min_length=1)
    role: Literal["canonical_m7", "passages", "tokens", "benchmark", "knownness"]
    source: str = Field(min_length=1)
    required: bool = True
    authentication: list[
        Literal["object_inventory", "manifest_sha256", "table_hashes", "file_hashes"]
    ] = Field(min_length=1)
    expected_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    expected_hashes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def expected_hashes_are_portable(self) -> Self:
        for name, digest in self.expected_hashes.items():
            path = Path(name)
            if (
                not name
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("input expected hashes require safe POSIX paths and SHA-256")
        return self


class ModelPin(FrozenModel):
    model_id: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    license: str = Field(min_length=1)
    tokenizer: str = Field(min_length=1)
    dimensions: int = Field(ge=1)
    maximum_tokens: int = Field(ge=1)
    pooling: Literal["mean_l2"]
    symmetric_prefix: str
    allowed_files: dict[str, str] = Field(min_length=1)
    possible_training_or_benchmark_exposure: str = Field(min_length=1)
    dependency_versions: dict[str, str] = Field(min_length=1)
    optional: bool = True

    @model_validator(mode="after")
    def hashes_and_versions_are_pinned(self) -> Self:
        if any(
            not name or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
            for name, digest in self.allowed_files.items()
        ):
            raise ValueError("every allowlisted model file requires a lowercase SHA-256")
        if any(
            not package or not version or any(char in version for char in "*<>")
            for package, version in self.dependency_versions.items()
        ):
            raise ValueError("model dependencies require exact versions")
        return self


class DetectorRegistration(FrozenModel):
    detector_id: str = Field(min_length=1)
    family: Literal["lexical", "semantic", "grammar_syntax", "structure_narrative", "anomaly"]
    independence_group: str = Field(min_length=1)
    original_language_capable: bool
    contains_english_derived_evidence: bool
    counts_for_independence: bool
    normalization: Literal["empirical_percentile", "zscore_within_stratum", "rank_percentile"]
    null_family: Literal[
        "within_book_reassignment",
        "stratified_score_bootstrap",
        "stratified_permutation",
    ]

    @model_validator(mode="after")
    def english_only_cannot_be_independent(self) -> Self:
        if (
            self.contains_english_derived_evidence
            and not self.original_language_capable
            and self.counts_for_independence
        ):
            raise ValueError("English-only detectors cannot count as an independent family")
        return self


class CalibrationPolicy(FrozenModel):
    seeds: dict[str, int] = Field(min_length=3)
    fixture_iterations: int = Field(ge=10)
    production_iterations: int = Field(ge=100)
    minimum_effective_null_draws: int = Field(ge=10_000)
    maximum_empirical_fdr: float = Field(gt=0.0, le=1.0)
    maximum_bh_q_value: float = Field(gt=0.0, le=1.0)
    minimum_independent_families: int = Field(ge=2)
    require_both_m7_null_families: bool
    multiple_testing_method: Literal["benjamini_hochberg"]
    threshold_selection: Literal["frozen_before_identity_review"]

    @model_validator(mode="after")
    def seeds_are_valid(self) -> Self:
        if any(not key or value < 0 for key, value in self.seeds.items()):
            raise ValueError("calibration seeds require names and nonnegative values")
        return self


class RetrievalPolicy(FrozenModel):
    """Frozen bounded candidate-universe construction."""

    sparse_top_k: int = Field(ge=1, le=100)
    embedding_top_k: int = Field(ge=1, le=100)
    block_size: int = Field(ge=16, le=4096)
    maximum_m7_seed_pairs: int = Field(ge=1_000, le=1_000_000)
    candidate_universe: Literal[
        "union_sparse_embedding_structure_and_top_m7_with_benchmark_evaluation"
    ]
    positive_controls_always_evaluated_outside_discovery_tiers: Literal[True]
    multiple_testing_scope: Literal["complete_preregistered_retained_candidate_universe"]


class FormulaicControlPolicy(FrozenModel):
    method: Literal["primary_corpus_high_df_lemma_root_ngrams"]
    ngram_sizes: list[Literal[2, 3]] = Field(min_length=2, max_length=2)
    minimum_document_frequency_fraction: float = Field(gt=0.0, le=1.0)
    minimum_document_count: int = Field(ge=2)
    minimum_distinct_high_df_features: int = Field(ge=1)
    minimum_high_df_feature_fraction: float = Field(gt=0.0, le=1.0)
    sensitivity_uses_primary_vocabulary: Literal[True]

    @model_validator(mode="after")
    def ngrams_are_exact(self) -> Self:
        if self.ngram_sizes != [2, 3]:
            raise ValueError("formulaic control requires exact lemma/root bigrams and trigrams")
        return self


class TierPolicy(FrozenModel):
    tier_a_label: Literal["statistically_eligible"]
    tier_b_label: Literal["exploratory_not_statistically_accepted"]
    tier_b_size: Literal[100]
    retain_known_pairs: bool
    known_pairs_tier_a_eligible: Literal[False]
    require_bidirectional_knownness_check: bool
    require_remove_all_english_ablation: bool
    tier_a_quality_exclusions: list[
        Literal["disputed_passage", "reference_gap", "ketiv_uncertainty"]
    ] = Field(min_length=3, max_length=3)
    basic_exclusions: list[
        Literal[
            "self_pair",
            "overlapping_passages",
            "unresolved_data_error",
            "invalid_trace",
            "local_context",
            "exact_or_near_duplicate",
            "same_reference_sensitivity",
        ]
    ] = Field(min_length=7, max_length=7)


class EnsemblePolicy(FrozenModel):
    method: Literal["weighted_mean_max_within_independence_group"]
    group_weights: dict[str, float] = Field(min_length=5)
    missing_group_score: float = Field(ge=0.0, le=0.0)
    qualifying_group_normalized_score: float = Field(gt=0.0, le=1.0)
    minimum_tier_a_ensemble_score: float = Field(gt=0.0, le=1.0)
    english_ablation_keeps_registered_denominator: Literal[True]
    anomaly_is_diagnostic_not_independent: Literal[True]
    final_null_method: Literal["stratified_candidate_pair_permutation"]

    @model_validator(mode="after")
    def weights_form_probability_distribution(self) -> Self:
        if any(not key or value <= 0.0 for key, value in self.group_weights.items()):
            raise ValueError("ensemble group weights require positive named values")
        if abs(sum(self.group_weights.values()) - 1.0) > 1e-12:
            raise ValueError("ensemble group weights must sum to one")
        return self


class ReviewPolicy(FrozenModel):
    formats: list[Literal["csv", "parquet", "dossier_markdown", "output_j_template"]]
    tier_a_dossier_limit: Literal[100]
    preserve_rejections: bool
    require_original_language_trace: bool
    glosses_are_supplemental: bool
    reviewer_classes: list[str] = Field(min_length=3)
    rejection_categories: list[str] = Field(min_length=3)


class StageRegistration(FrozenModel):
    number: int = Field(ge=1, le=11)
    stage_id: str = Field(min_length=1)
    dependencies: list[int]
    expensive: bool
    upload_after_completion: bool

    @model_validator(mode="after")
    def dependencies_precede_stage(self) -> Self:
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("stage dependencies must be unique")
        if any(dependency >= self.number or dependency < 1 for dependency in self.dependencies):
            raise ValueError("stage dependencies must precede their stage")
        return self


class CloudPolicy(FrozenModel):
    production_operating_system: Literal["linux"]
    production_requires_explicit_environment_authorization: bool
    authorization_environment_variable: Literal["ECHOES_AUTHORIZE_PRODUCTION"]
    authorization_value: Literal["final-discovery-v1"]
    credentials_via_environment_only: bool
    hard_budget_usd: float = Field(gt=0.0)
    no_automatic_provisioning: bool
    direct_b2_upload_before_cleanup: bool


class LxxDecision(FrozenModel):
    activation: Literal["deferred_non_blocking"]
    reason: str = Field(min_length=1)
    final_experiment_valid_without_lxx: Literal[True]


class FinalDiscoveryConfig(FrozenModel):
    """Complete frozen scientific and operational contract."""

    schema_version: Literal[1]
    experiment_id: Literal["final-discovery-v1"]
    status: Literal["preregistered_preproduction"]
    research_question: str = Field(min_length=1)
    random_seed: int = Field(ge=0)
    passage_scope: Literal["whole_canon_verse_primary_with_registered_sensitivities"]
    inputs: list[InputArtifact] = Field(min_length=4)
    embedding_model: ModelPin
    retrieval: RetrievalPolicy
    formulaic_control: FormulaicControlPolicy
    detectors: list[DetectorRegistration] = Field(min_length=8)
    calibration: CalibrationPolicy
    ensemble: EnsemblePolicy
    tiers: TierPolicy
    review: ReviewPolicy
    stages: list[StageRegistration] = Field(min_length=11, max_length=11)
    cloud: CloudPolicy
    lxx: LxxDecision
    lexical_reuse_policy: Literal["authenticate_and_reuse_canonical_m7_never_recompute"]
    learned_ensemble_allowed: Literal[False]
    cosine_alone_can_create_tier_a: Literal[False]
    post_identity_threshold_changes_allowed: Literal[False]
    stop_after_canonical_run_and_review: Literal[True]

    @model_validator(mode="after")
    def governed_registries_are_complete(self) -> Self:
        detector_ids = [item.detector_id for item in self.detectors]
        if len(detector_ids) != len(set(detector_ids)):
            raise ValueError("detector IDs must be unique")
        families = {item.family for item in self.detectors}
        if families != {"lexical", "semantic", "grammar_syntax", "structure_narrative", "anomaly"}:
            raise ValueError("all five registered evidence families are required")
        if not any(item.contains_english_derived_evidence for item in self.detectors):
            raise ValueError("the supplemental English representation must be registered")
        registered_groups = {item.independence_group for item in self.detectors}
        if set(self.ensemble.group_weights) != registered_groups:
            raise ValueError("ensemble weights must cover the exact registered independence groups")
        stage_numbers = [stage.number for stage in self.stages]
        if stage_numbers != list(range(1, 12)):
            raise ValueError("the exact ordered eleven-stage campaign is required")
        if len({stage.stage_id for stage in self.stages}) != 11:
            raise ValueError("stage IDs must be unique")
        input_ids = [item.artifact_id for item in self.inputs]
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("input artifact IDs must be unique")
        m7 = [item for item in self.inputs if item.role == "canonical_m7"]
        if len(m7) != 1 or m7[0].expected_manifest_sha256 is None:
            raise ValueError("one manifest-pinned canonical M7 input is required")
        unpinned = [
            item.artifact_id
            for item in self.inputs
            if item.role != "canonical_m7" and not item.expected_hashes
        ]
        if unpinned:
            raise ValueError(f"required non-M7 inputs lack exact hash anchors: {unpinned}")
        return self


def _canonical_payload(config: FinalDiscoveryConfig) -> bytes:
    payload = config.model_dump(mode="json", exclude_none=False)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def final_discovery_config_sha256(config: FinalDiscoveryConfig) -> str:
    """Hash the validated semantic configuration, independent of YAML formatting."""

    return hashlib.sha256(_canonical_payload(config)).hexdigest()


def load_final_discovery_config(
    path: Path = DEFAULT_FINAL_DISCOVERY_CONFIG,
) -> FinalDiscoveryConfig:
    """Load and strictly validate the frozen preregistration."""

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise FinalDiscoveryConfigError(
            f"could not load final-discovery config {path}: {exc}"
        ) from exc
    if not isinstance(loaded, Mapping) or not all(isinstance(key, str) for key in loaded):
        raise FinalDiscoveryConfigError(
            "final-discovery config root must be a string-keyed mapping"
        )
    try:
        return FinalDiscoveryConfig.model_validate(cast(dict[str, object], dict(loaded)))
    except ValidationError as exc:
        raise FinalDiscoveryConfigError(f"invalid final-discovery config {path}:\n{exc}") from exc
