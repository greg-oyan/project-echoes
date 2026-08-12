"""Auditable hard cardinality bounds for the whole-canon campaign."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.final_discovery.config import FinalDiscoveryConfig

CANONICAL_M7_CANDIDATE_COUNT = 1_248_779
EXPECTED_PRIMARY_PASSAGE_COUNT = 31_156
EXPECTED_PRIMARY_BOOK_COUNT = 66


class CampaignScaleError(ValueError):
    """Raised when the frozen retrieval graph has no valid finite bound."""


class CampaignScaleContract(BaseModel):
    """Conservative exact upper bounds implied by top-k retrieval registrations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    method: Literal["union_of_registered_directional_top_k_bounds"] = (
        "union_of_registered_directional_top_k_bounds"
    )
    primary_passage_count: int = Field(ge=2)
    maximum_undirected_all_pairs: int = Field(ge=1)
    sparse_top_k: int = Field(ge=1)
    embedding_top_k: int = Field(ge=1)
    maximum_m7_seed_pairs: int = Field(ge=1)
    canonical_m7_candidate_count: int = Field(ge=1)
    semantic_retrieval_representation_count: Literal[3] = 3
    semantic_detector_count: Literal[4] = 4
    grammar_detector_count: Literal[2] = 2
    structure_detector_count: Literal[1] = 1
    anomaly_detector_count: Literal[1] = 1
    registered_detector_count: Literal[9] = 9
    calibration_length_bucket_count: Literal[3] = 3
    maximum_calibration_pair_strata: int = Field(ge=1)
    maximum_calibration_detector_strata: int = Field(ge=1)
    maximum_pairs_per_sparse_retrieval: int = Field(ge=1)
    maximum_pairs_per_embedding_retrieval: int = Field(ge=1)
    maximum_stage_two_semantic_pairs: int = Field(ge=1)
    maximum_stage_three_pairs: int = Field(ge=1)
    maximum_stage_four_pairs: int = Field(ge=1)
    maximum_stage_five_pairs: int = Field(ge=1)
    maximum_retained_candidate_pairs: int = Field(ge=1)
    maximum_stage_three_raw_evidence_rows: int = Field(ge=1)
    maximum_stage_four_raw_evidence_rows: int = Field(ge=1)
    maximum_stage_five_raw_evidence_rows: int = Field(ge=1)
    maximum_stage_six_raw_evidence_rows: int = Field(ge=1)
    maximum_total_raw_evidence_rows: int = Field(ge=1)
    maximum_permutation_like_calibration_rows: int = Field(ge=1)
    maximum_bootstrap_calibration_rows: int = Field(ge=1)
    maximum_evidence_rows_per_pair: Literal[9] = 9
    bounds_are_caps_not_expected_counts: Literal[True] = True

    @model_validator(mode="after")
    def unions_fit_the_complete_pair_space(self) -> Self:
        pair_bounds = (
            self.maximum_stage_two_semantic_pairs,
            self.maximum_stage_three_pairs,
            self.maximum_stage_four_pairs,
            self.maximum_stage_five_pairs,
            self.maximum_retained_candidate_pairs,
        )
        if any(value > self.maximum_undirected_all_pairs for value in pair_bounds):
            raise ValueError("retrieval bound exceeds the complete undirected pair space")
        component_total = sum(
            (
                self.maximum_stage_three_raw_evidence_rows,
                self.maximum_stage_four_raw_evidence_rows,
                self.maximum_stage_five_raw_evidence_rows,
                self.maximum_stage_six_raw_evidence_rows,
            )
        )
        if component_total != self.maximum_total_raw_evidence_rows:
            raise ValueError("raw-evidence component bounds do not reconcile")
        if (
            self.maximum_permutation_like_calibration_rows + self.maximum_bootstrap_calibration_rows
            != self.maximum_total_raw_evidence_rows
        ):
            raise ValueError("calibration null-family row bounds do not reconcile")
        if self.maximum_calibration_detector_strata != (
            self.maximum_calibration_pair_strata * self.registered_detector_count
        ):
            raise ValueError("detector-stratum bound does not reconcile")
        return self


def directional_top_k_pair_bound(passage_count: int, top_k: int) -> int:
    """Maximum unique undirected pairs from one directional top-k retrieval."""

    if passage_count < 2 or top_k < 1:
        raise CampaignScaleError("pair bounds require at least two passages and positive k")
    all_pairs = passage_count * (passage_count - 1) // 2
    directed_slots = passage_count * min(top_k, passage_count - 1)
    return min(all_pairs, directed_slots)


def campaign_scale_contract(
    config: FinalDiscoveryConfig,
    *,
    primary_passage_count: int,
    canonical_m7_candidate_count: int = CANONICAL_M7_CANDIDATE_COUNT,
) -> CampaignScaleContract:
    """Derive the production population caps without reading candidate identities."""

    if canonical_m7_candidate_count < 1:
        raise CampaignScaleError("canonical M7 candidate count must be positive")
    detector_ids = {registration.detector_id for registration in config.detectors}
    required = {
        "m7_lexical_rrf",
        "semantic_domain_overlap",
        "lemma_root_sequence_semantic",
        "multilingual_e5_original_language",
        "multilingual_e5_english_gloss",
        "grammar_sequence_alignment",
        "grammar_rare_pattern",
        "participant_frame_progression",
        "stratified_representation_anomaly",
    }
    if detector_ids != required:
        raise CampaignScaleError("scale contract requires the exact registered detector inventory")
    all_pairs = primary_passage_count * (primary_passage_count - 1) // 2
    sparse_bound = directional_top_k_pair_bound(
        primary_passage_count, config.retrieval.sparse_top_k
    )
    embedding_bound = directional_top_k_pair_bound(
        primary_passage_count, config.retrieval.embedding_top_k
    )
    stage_two = min(all_pairs, sparse_bound + 2 * embedding_bound)
    stage_three = min(
        all_pairs,
        stage_two + config.retrieval.maximum_m7_seed_pairs,
    )
    stage_four = sparse_bound
    stage_five = sparse_bound
    retained = min(all_pairs, stage_three + stage_four + stage_five)
    stage_three_evidence = 4 * stage_three + min(canonical_m7_candidate_count, stage_three)
    stage_four_evidence = 2 * stage_four
    stage_five_evidence = stage_five
    # Every candidate could conservatively acquire the one diagnostic anomaly
    # row.  The actual two-family eligibility constraint can only reduce this.
    stage_six_evidence = retained
    # The governed passage projection assigns exactly one corpus and broad
    # genre to each of the 66 books.  The unordered book pair therefore fixes
    # corpus and genre; only the three registered length-ratio buckets remain.
    maximum_pair_strata = EXPECTED_PRIMARY_BOOK_COUNT * (EXPECTED_PRIMARY_BOOK_COUNT + 1) // 2 * 3
    bootstrap_calibration_rows = stage_three
    return CampaignScaleContract(
        primary_passage_count=primary_passage_count,
        maximum_undirected_all_pairs=all_pairs,
        sparse_top_k=config.retrieval.sparse_top_k,
        embedding_top_k=config.retrieval.embedding_top_k,
        maximum_m7_seed_pairs=config.retrieval.maximum_m7_seed_pairs,
        canonical_m7_candidate_count=canonical_m7_candidate_count,
        maximum_calibration_pair_strata=maximum_pair_strata,
        maximum_calibration_detector_strata=maximum_pair_strata * 9,
        maximum_pairs_per_sparse_retrieval=sparse_bound,
        maximum_pairs_per_embedding_retrieval=embedding_bound,
        maximum_stage_two_semantic_pairs=stage_two,
        maximum_stage_three_pairs=stage_three,
        maximum_stage_four_pairs=stage_four,
        maximum_stage_five_pairs=stage_five,
        maximum_retained_candidate_pairs=retained,
        maximum_stage_three_raw_evidence_rows=stage_three_evidence,
        maximum_stage_four_raw_evidence_rows=stage_four_evidence,
        maximum_stage_five_raw_evidence_rows=stage_five_evidence,
        maximum_stage_six_raw_evidence_rows=stage_six_evidence,
        maximum_total_raw_evidence_rows=(
            stage_three_evidence + stage_four_evidence + stage_five_evidence + stage_six_evidence
        ),
        maximum_permutation_like_calibration_rows=(
            stage_three_evidence
            + stage_four_evidence
            + stage_five_evidence
            + stage_six_evidence
            - bootstrap_calibration_rows
        ),
        maximum_bootstrap_calibration_rows=bootstrap_calibration_rows,
    )


__all__ = [
    "CANONICAL_M7_CANDIDATE_COUNT",
    "EXPECTED_PRIMARY_BOOK_COUNT",
    "EXPECTED_PRIMARY_PASSAGE_COUNT",
    "CampaignScaleContract",
    "CampaignScaleError",
    "campaign_scale_contract",
    "directional_top_k_pair_bound",
]
