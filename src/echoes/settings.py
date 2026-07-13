"""Typed configuration loading for Project Echoes."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes.manifests.experiments import ExperimentManifest


class ConfigLoadError(ValueError):
    """Raised when a configuration file cannot be loaded or validated."""


class EchoesModel(BaseModel):
    """Base model that rejects undocumented configuration keys."""

    model_config = ConfigDict(extra="forbid")


class CorpusSpec(EchoesModel):
    """A planned or active corpus layer."""

    corpus_id: str = Field(min_length=1)
    role: Literal["primary", "bridge", "supplementary"]
    languages: list[Literal["hebrew", "aramaic", "greek", "english"]]
    status: Literal["planned", "blocked", "active"]
    activation_prerequisites: list[str] = Field(default_factory=list)


class CorporaConfig(EchoesModel):
    """Top-level corpus activation configuration."""

    schema_version: Literal[1]
    corpora: list[CorpusSpec]

    @model_validator(mode="after")
    def corpus_ids_are_unique(self) -> Self:
        ids = [corpus.corpus_id for corpus in self.corpora]
        if len(ids) != len(set(ids)):
            msg = "corpus_id values must be unique"
            raise ValueError(msg)
        return self


class HebrewTransformations(EchoesModel):
    """Explicit transformations used to derive Hebrew analytical forms."""

    unicode_normalization: Literal["NFD", "NFC"]
    collapse_whitespace: bool
    remove_combining_grapheme_joiner: bool
    normalized_remove_cantillation: bool
    normalized_remove_vowel_points: bool
    unpointed_remove_cantillation: bool
    unpointed_remove_vowel_points: bool
    split_maqqef: Literal[False]
    remove_paseq: Literal[False]
    remove_sof_pasuq: Literal[False]
    remove_punctuation: Literal[False]
    normalize_final_letters: Literal[False]
    collapse_orthographic_variants: Literal[False]
    segment_prefixes: Literal[False]
    segment_suffixes: Literal[False]
    collapse_ketiv_qere: Literal[False]
    normalize_divine_names: Literal[False]


class HebrewNormalization(EchoesModel):
    """Active, information-preserving Hebrew and Aramaic normalization policy."""

    status: Literal["active"]
    preserve_source_form: Literal[True]
    lemma_namespace: Literal["macula"]
    transformations: HebrewTransformations


class KetivQerePolicy(EchoesModel):
    """Selects the derived reading stream without mutating preserved records."""

    analysis_reading: Literal["qere", "ketiv"] = "qere"


class GreekTransformations(EchoesModel):
    """Explicit transformations used to derive Greek analytical forms.

    The surface form is immutable.  ``normalized_form`` is the
    punctuation-separated word core; ``folded_form`` is the case-folded,
    accent-insensitive comparison form.  Destructive options are pinned off.
    """

    unicode_normalization: Literal["NFC", "NFD"]
    collapse_whitespace: bool
    separate_punctuation: Literal[True]
    preserve_elision_mark: Literal[True]
    restore_elided_letters: Literal[False]
    decompose_crasis: Literal[False]
    folded_case_fold: Literal[True]
    folded_remove_accents: bool
    folded_remove_breathings: bool
    folded_remove_diaeresis: bool
    normalize_final_sigma_outside_folding: Literal[False]
    enclitic_accent_policy: Literal["preserve_source"]


class GreekNormalization(EchoesModel):
    """Active, information-preserving Greek normalization policy."""

    status: Literal["active"]
    preserve_source_form: Literal[True]
    lemma_namespace: Literal["macula"]
    transformations: GreekTransformations


class NormalizationConfig(EchoesModel):
    """Normalization configuration for the primary source languages."""

    schema_version: Literal[4]
    ketiv_qere: KetivQerePolicy
    hebrew: HebrewNormalization
    greek: GreekNormalization


class HebrewSpotCheck(EchoesModel):
    """One reproducible manual-inspection target and its required facets."""

    reference: str = Field(pattern=r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$")
    category: str = Field(min_length=1)
    expected_language: Literal["hebrew", "aramaic"]
    check: list[
        Literal[
            "token_order",
            "surface_forms",
            "lemmas",
            "morphology",
            "clause_or_phrase_ids",
            "language",
            "canonical_reference",
            "source_provenance",
            "normalized_forms",
            "ketiv_qere",
            "segmentation",
        ]
    ] = Field(min_length=1)


class HebrewIngestionConfig(EchoesModel):
    """Governed full-corpus expectations and manual spot-check registry."""

    schema_version: Literal[1]
    source_id: Literal["macula-hebrew"]
    status: Literal["blocked", "ready"]
    expected_books: Literal[39]
    expected_chapters: Literal[929]
    expected_tokens: Literal[475911]
    spot_checks: list[HebrewSpotCheck] = Field(min_length=10)

    @model_validator(mode="after")
    def spot_check_references_are_unique(self) -> Self:
        references = [item.reference for item in self.spot_checks]
        if len(references) != len(set(references)):
            raise ValueError("Hebrew spot-check references must be unique")
        return self


class GreekSpotCheck(EchoesModel):
    """One reproducible Greek manual-inspection target and its required facets."""

    reference: str = Field(pattern=r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$")
    category: str = Field(min_length=1)
    check: list[
        Literal[
            "token_order",
            "surface_forms",
            "lemmas",
            "morphology",
            "clause_or_phrase_ids",
            "canonical_reference",
            "source_provenance",
            "normalized_forms",
            "punctuation_separation",
            "elision",
            "enclitics",
            "disputed_passage",
            "versification",
        ]
    ] = Field(min_length=1)


class GreekIngestionConfig(EchoesModel):
    """Governed full-corpus Greek expectations and manual spot-check registry."""

    schema_version: Literal[1]
    source_id: Literal["macula-greek"]
    status: Literal["blocked", "ready"]
    expected_books: Literal[27]
    expected_chapters: Literal[260]
    expected_tokens: Literal[137779]
    expected_missing_verses: list[str] = Field(min_length=1)
    expected_out_of_sequence_verses: list[str] = Field(default_factory=list)
    spot_checks: list[GreekSpotCheck] = Field(min_length=8)

    @model_validator(mode="after")
    def references_are_well_formed_and_unique(self) -> Self:
        reference_pattern = r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$"
        for values in (self.expected_missing_verses, self.expected_out_of_sequence_verses):
            for reference in values:
                if re.fullmatch(reference_pattern, reference) is None:
                    raise ValueError(f"malformed verse reference: {reference}")
            if len(values) != len(set(values)):
                raise ValueError("verse reference lists must be unique")
        references = [item.reference for item in self.spot_checks]
        if len(references) != len(set(references)):
            raise ValueError("Greek spot-check references must be unique")
        return self


CorpusName = Literal["hebrew", "greek"]
AnalysisProfileName = Literal["edition_complete", "critical_core"]
Granularity = Literal["clause", "sentence", "verse", "two_verse", "five_verse"]
WindowGranularity = Literal["two_verse", "five_verse"]
_VERSE_REFERENCE_PATTERN = r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$"


def _reference_coordinates(reference: str) -> tuple[str, int, int]:
    """Return the book, chapter, and verse from a validated verse reference."""

    book, location = reference.split(" ", maxsplit=1)
    chapter, verse = location.split(":", maxsplit=1)
    return book, int(chapter), int(verse)


class SourceVerseSuccessor(EchoesModel):
    """A physical verse-to-verse succession in a pinned source edition.

    Source succession records file or edition order only. It does not grant
    permission for an analytical passage to cross the same boundary.
    """

    source_id: str = Field(min_length=1)
    corpus: CorpusName
    from_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    to_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    relation: Literal["edition_sequence", "alternate_ending"]
    reference_gap: bool
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def successor_is_within_one_book_and_directed(self) -> Self:
        from_book = _reference_coordinates(self.from_reference)[0]
        to_book = _reference_coordinates(self.to_reference)[0]
        if from_book != to_book:
            raise ValueError("source successor must stay inside one book")
        if self.from_reference == self.to_reference:
            raise ValueError("source successor requires two distinct references")
        return self


class AnalyticalBoundaryBreak(EchoesModel):
    """A source boundary that configured verse windows may not cross."""

    corpus: CorpusName
    from_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    to_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    prohibited_window_granularities: list[WindowGranularity] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def boundary_is_within_one_book_and_directed(self) -> Self:
        from_book = _reference_coordinates(self.from_reference)[0]
        to_book = _reference_coordinates(self.to_reference)[0]
        if from_book != to_book:
            raise ValueError("analytical boundary must stay inside one book")
        if self.from_reference == self.to_reference:
            raise ValueError("analytical boundary requires two distinct references")
        if len(self.prohibited_window_granularities) != len(
            set(self.prohibited_window_granularities)
        ):
            raise ValueError("prohibited window granularities must be unique")
        return self


class AnalyticalContinuity(EchoesModel):
    """A positively declared analytical connection between source verses."""

    corpus: CorpusName
    from_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    to_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def continuity_is_within_one_book_and_directed(self) -> Self:
        from_book = _reference_coordinates(self.from_reference)[0]
        to_book = _reference_coordinates(self.to_reference)[0]
        if from_book != to_book:
            raise ValueError("analytical continuity must stay inside one book")
        if self.from_reference == self.to_reference:
            raise ValueError("analytical continuity requires two distinct references")
        return self


class DisputedPassage(EchoesModel):
    """An inline source range requiring explicit analytical treatment."""

    passage_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    corpus: CorpusName
    start_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    end_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    classification: Literal["longer_ending", "alternate_ending", "pericope_adulterae"]
    source_presence: Literal["inline"]
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def range_is_ordered_inside_one_book(self) -> Self:
        start = _reference_coordinates(self.start_reference)
        end = _reference_coordinates(self.end_reference)
        if start[0] != end[0]:
            raise ValueError("disputed passage must stay inside one book")
        if start[1:] > end[1:]:
            raise ValueError("disputed passage references must be ordered")
        return self


class AnalysisProfile(EchoesModel):
    """A named selection of the source edition's inline token stream."""

    name: AnalysisProfileName
    base_stream: Literal["source_inline"]
    excluded_disputed_passage_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def exclusions_are_unique(self) -> Self:
        if len(self.excluded_disputed_passage_ids) != len(set(self.excluded_disputed_passage_ids)):
            raise ValueError("profile exclusions must be unique")
        return self


class ReferenceGapPolicy(EchoesModel):
    """How future passage generation handles edition-level numbering gaps."""

    fabricate_omitted_references: Literal[False]
    allow_source_order_adjacency_across_numbering_gaps: Literal[True]
    mark_reference_gap: Literal[True]
    concatenate_alternate_readings_from_source_order: Literal[False]


class DisputedCandidatePolicy(EchoesModel):
    """Future candidate safeguards for evidence intersecting disputed text."""

    flag_candidates: Literal[True]
    candidate_flag_field: Literal["disputed_passage_flag"]
    strong_candidate_requires: Literal[
        "survives_disputed_text_exclusion_or_completed_textual_criticism_review"
    ]


class EnabledAnalysisReadings(EchoesModel):
    """Reading streams materialized for each primary corpus."""

    hebrew: list[Literal["qere", "ketiv"]] = Field(min_length=2)
    greek: list[Literal["source"]] = Field(min_length=1)

    @model_validator(mode="after")
    def all_required_readings_are_enabled_once(self) -> Self:
        if len(self.hebrew) != len(set(self.hebrew)) or set(self.hebrew) != {
            "qere",
            "ketiv",
        }:
            raise ValueError("Hebrew analysis readings must be exactly qere and ketiv")
        if self.greek != ["source"]:
            raise ValueError("Greek analysis reading must be exactly source")
        return self


class WindowPolicy(EchoesModel):
    """Safe construction rules for complete sliding verse windows."""

    cross_chapter_boundaries: Literal[True]
    cross_book_boundaries: Literal[False]
    emit_partial_windows: Literal[False]
    bridge_profile_exclusions: Literal[False]
    bridge_analytical_boundary_breaks: Literal[False]
    allow_source_order_reference_gaps: Literal[True]
    mark_reference_gaps: Literal[True]
    minimum_verse_count: int = Field(ge=2)
    maximum_verse_count: int = Field(ge=2)
    window_sizes: dict[WindowGranularity, int]

    @model_validator(mode="after")
    def enabled_window_sizes_are_exact_and_bounded(self) -> Self:
        expected = {"two_verse": 2, "five_verse": 5}
        if self.window_sizes != expected:
            raise ValueError("window sizes must be exactly two_verse=2 and five_verse=5")
        if self.minimum_verse_count > self.maximum_verse_count:
            raise ValueError("minimum window size cannot exceed maximum window size")
        if self.minimum_verse_count != min(
            self.window_sizes.values()
        ) or self.maximum_verse_count != max(self.window_sizes.values()):
            raise ValueError("window size bounds must match the configured window sizes")
        return self


class CriticalCoreExclusion(EchoesModel):
    """A critical-core range resolved to one declared disputed passage."""

    disputed_passage_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    start_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)
    end_reference: str = Field(pattern=_VERSE_REFERENCE_PATTERN)

    @model_validator(mode="after")
    def exclusion_range_is_ordered_inside_one_book(self) -> Self:
        start = _reference_coordinates(self.start_reference)
        end = _reference_coordinates(self.end_reference)
        if start[0] != end[0]:
            raise ValueError("critical-core exclusion must stay inside one book")
        if start[1:] > end[1:]:
            raise ValueError("critical-core exclusion references must be ordered")
        return self


class DisputedPassagePolicy(EchoesModel):
    """Passage-level treatment of inline textually disputed ranges."""

    flag_passages: Literal[True]
    passage_flag_field: Literal["disputed_passage_flag"]
    passage_ids_field: Literal["disputed_passage_ids_json"]
    profile_exclusions_break_continuity: Literal[True]
    truncate_source_units_at_profile_boundaries: Literal[False]


class KetivStructuralPolicy(EchoesModel):
    """Conservative use of supplementary Ketiv structural mappings."""

    verse_include_every_token: Literal[True]
    sentence_use_resolved_mapping: Literal[True]
    clause_use_resolved_mapping_only: Literal[True]
    unresolved_clause_action: Literal["explicit_exclusion"]
    unresolved_phrase_action: Literal["flag_only"]
    never_fabricate_structure: Literal[True]
    uncertainty_flag_field: Literal["ketiv_structural_uncertainty"]
    preserve_excluded_tokens_in_verse_analysis: Literal[True]
    record_affected_token_ids: Literal[True]


class ReconstructionPolicy(EchoesModel):
    """Language-aware, deterministic passage reconstruction contract."""

    language_aware: Literal[True]
    preserve_surface_text: Literal[True]
    preserve_null_distinct_from_empty: Literal[True]
    deterministic_unicode: Literal[True]
    universal_space_join: Literal[False]
    hebrew_strategy: Literal["source_word_and_morpheme_order"]
    greek_strategy: Literal["punctuation_metadata_and_source_order"]


class ZeroWidthTokenPolicy(EchoesModel):
    """Membership and rendering rules for source-native zero-width rows."""

    include_in_membership: Literal[True]
    preserve_source_order: Literal[True]
    contributes_visible_text: Literal[False]


class PunctuationReconstructionPolicy(EchoesModel):
    """Greek punctuation and elision reconstruction rules."""

    use_leading_punctuation: Literal[True]
    use_trailing_punctuation: Literal[True]
    preserve_elision_metadata: Literal[True]
    avoid_space_before_closing_punctuation: Literal[True]
    preserve_opening_punctuation: Literal[True]


PassageIdentityField = Literal[
    "passage_id_schema_version",
    "corpus",
    "analysis_profile",
    "analysis_reading",
    "granularity",
    "book",
    "source_unit_id",
    "reference_sequence",
    "token_ids",
]


class PassageIdentityPolicy(EchoesModel):
    """Canonical payload and collision behavior for stable passage IDs."""

    schema_version: Literal[1]
    prefix: Literal["P"]
    digest_algorithm: Literal["sha256"]
    digest_hex_length: Literal[64]
    canonical_payload_fields: list[PassageIdentityField] = Field(min_length=9)
    include_segmentation_config_hash: Literal[False]
    collision_action: Literal["error"]

    @model_validator(mode="after")
    def canonical_fields_are_complete_and_ordered(self) -> Self:
        expected: list[PassageIdentityField] = [
            "passage_id_schema_version",
            "corpus",
            "analysis_profile",
            "analysis_reading",
            "granularity",
            "book",
            "source_unit_id",
            "reference_sequence",
            "token_ids",
        ]
        if self.canonical_payload_fields != expected:
            raise ValueError("passage identity canonical payload fields must match schema v1")
        return self


PartitionField = Literal["corpus", "analysis_profile", "analysis_reading", "granularity"]


class OutputPartitioning(EchoesModel):
    """Deterministic, recoverable storage layout for passage artifacts."""

    format: Literal["parquet"]
    schema_directory: str = Field(min_length=1)
    partition_by: list[PartitionField] = Field(min_length=4)
    compression: Literal["zstd"]
    write_statistics: Literal[True]
    atomic_writes: Literal[True]
    overwrite_requires_force: Literal[True]
    refuse_silent_overwrite: Literal[True]

    @model_validator(mode="after")
    def directory_is_portable_and_partitions_are_complete(self) -> Self:
        path = Path(self.schema_directory)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("passage output directory must be a repository-relative path")
        expected: list[PartitionField] = [
            "corpus",
            "analysis_profile",
            "analysis_reading",
            "granularity",
        ]
        if self.partition_by != expected:
            raise ValueError("passage outputs must use the canonical partition order")
        return self


IssueSeverity = Literal["error", "warning", "informational"]


class ValidationSeverityPolicy(EchoesModel):
    """Failure behavior for segmentation issues and strict validation."""

    allowed_severities: list[IssueSeverity] = Field(min_length=3)
    errors_fail_validation: Literal[True]
    warnings_fail_strict_validation: Literal[True]
    informational_fail_validation: Literal[False]
    unknown_severity_action: Literal["error"]

    @model_validator(mode="after")
    def severities_are_complete_and_unique(self) -> Self:
        if self.allowed_severities != ["error", "warning", "informational"]:
            raise ValueError("validation severities must be error, warning, informational")
        return self


class SegmentationConfig(EchoesModel):
    """Active passage-unit, stream, continuity, and storage policies."""

    schema_version: Literal[3]
    status: Literal["active"]
    enabled_corpora: list[CorpusName] = Field(min_length=2)
    enabled_analysis_profiles: list[AnalysisProfileName] = Field(min_length=2)
    enabled_analysis_readings: EnabledAnalysisReadings
    granularities: list[Granularity]
    preserve_token_boundaries: Literal[True]
    default_analysis_profile: AnalysisProfileName
    window_policy: WindowPolicy
    source_successors: list[SourceVerseSuccessor] = Field(default_factory=list)
    analytical_continuities: list[AnalyticalContinuity] = Field(default_factory=list)
    analytical_boundary_breaks: list[AnalyticalBoundaryBreak] = Field(default_factory=list)
    disputed_passages: list[DisputedPassage] = Field(default_factory=list)
    analysis_profiles: list[AnalysisProfile] = Field(min_length=1)
    critical_core_exclusions: list[CriticalCoreExclusion] = Field(min_length=1)
    reference_gap_policy: ReferenceGapPolicy
    disputed_passage_policy: DisputedPassagePolicy
    disputed_candidate_policy: DisputedCandidatePolicy
    ketiv_policy: KetivStructuralPolicy
    reconstruction_policy: ReconstructionPolicy
    zero_width_token_policy: ZeroWidthTokenPolicy
    punctuation_reconstruction_policy: PunctuationReconstructionPolicy
    passage_identity: PassageIdentityPolicy
    output_partitioning: OutputPartitioning
    validation_severity_policy: ValidationSeverityPolicy

    @model_validator(mode="after")
    def declarations_are_consistent(self) -> Self:
        if len(self.enabled_corpora) != len(set(self.enabled_corpora)) or set(
            self.enabled_corpora
        ) != {"hebrew", "greek"}:
            raise ValueError("enabled corpora must be exactly hebrew and greek")

        if len(self.enabled_analysis_profiles) != len(set(self.enabled_analysis_profiles)):
            raise ValueError("enabled analysis profiles must be unique")
        if set(self.enabled_analysis_profiles) != {"edition_complete", "critical_core"}:
            raise ValueError(
                "enabled analysis profiles must be exactly edition_complete and critical_core"
            )

        if len(self.granularities) != len(set(self.granularities)):
            raise ValueError("segmentation granularities must be unique")
        required_granularities = {"clause", "sentence", "verse", "two_verse", "five_verse"}
        if set(self.granularities) != required_granularities:
            raise ValueError("all five Milestone 5 granularities must be enabled")

        successor_pairs = [
            (item.source_id, item.corpus, item.from_reference, item.to_reference)
            for item in self.source_successors
        ]
        if len(successor_pairs) != len(set(successor_pairs)):
            raise ValueError("source_successors must be unique")

        boundary_pairs = [
            (item.corpus, item.from_reference, item.to_reference)
            for item in self.analytical_boundary_breaks
        ]
        if len(boundary_pairs) != len(set(boundary_pairs)):
            raise ValueError("analytical_boundary_breaks must be unique")

        continuity_pairs = [
            (item.corpus, item.from_reference, item.to_reference)
            for item in self.analytical_continuities
        ]
        if len(continuity_pairs) != len(set(continuity_pairs)):
            raise ValueError("analytical_continuities must be unique")
        contradictory_boundaries = set(continuity_pairs) & set(boundary_pairs)
        if contradictory_boundaries:
            raise ValueError("the same boundary cannot be both analytically continuous and broken")

        disputed_ids = [item.passage_id for item in self.disputed_passages]
        if len(disputed_ids) != len(set(disputed_ids)):
            raise ValueError("disputed passage IDs must be unique")
        declared_disputed_ids = set(disputed_ids)

        profile_names = [profile.name for profile in self.analysis_profiles]
        profiles = {profile.name: profile for profile in self.analysis_profiles}
        if self.default_analysis_profile not in profiles:
            raise ValueError("default analysis profile must be declared")
        if len(profile_names) != len(set(profile_names)):
            raise ValueError("analysis profile names must be unique")
        if set(profiles) != {"edition_complete", "critical_core"}:
            raise ValueError("edition_complete and critical_core profiles are required")
        if set(profiles) != set(self.enabled_analysis_profiles):
            raise ValueError("declared analysis profiles must match enabled profiles")

        for profile in self.analysis_profiles:
            unknown = set(profile.excluded_disputed_passage_ids) - declared_disputed_ids
            if unknown:
                raise ValueError(
                    f"profile excludes unknown disputed passage IDs: {sorted(unknown)}"
                )
        if profiles["edition_complete"].excluded_disputed_passage_ids:
            raise ValueError("edition_complete must include all inline disputed passages")
        if set(profiles["critical_core"].excluded_disputed_passage_ids) != declared_disputed_ids:
            raise ValueError("critical_core must exclude every declared disputed passage")

        critical_ids = [item.disputed_passage_id for item in self.critical_core_exclusions]
        if len(critical_ids) != len(set(critical_ids)):
            raise ValueError("critical-core exclusions must be unique")
        if set(critical_ids) != declared_disputed_ids:
            raise ValueError("critical-core exclusions must resolve every disputed passage")
        disputed_by_id = {item.passage_id: item for item in self.disputed_passages}
        for exclusion in self.critical_core_exclusions:
            disputed = disputed_by_id[exclusion.disputed_passage_id]
            if (
                exclusion.start_reference != disputed.start_reference
                or exclusion.end_reference != disputed.end_reference
            ):
                raise ValueError(
                    "critical-core exclusion references must resolve to the declared "
                    "disputed passage"
                )

        blocked_windows = set(self.window_policy.window_sizes)
        boundary_windows = {
            (item.corpus, item.from_reference, item.to_reference): set(
                item.prohibited_window_granularities
            )
            for item in self.analytical_boundary_breaks
        }
        for successor in self.source_successors:
            if successor.relation != "alternate_ending":
                continue
            key = (successor.corpus, successor.from_reference, successor.to_reference)
            if boundary_windows.get(key) != blocked_windows:
                raise ValueError(
                    "alternate-ending source successors must prohibit two-verse "
                    "and five-verse windows at a matching analytical boundary"
                )
        for key, prohibited_windows in boundary_windows.items():
            if prohibited_windows != blocked_windows:
                raise ValueError(
                    f"analytical boundary {key} must prohibit every enabled window granularity"
                )
        return self


class ScoreComponent(EchoesModel):
    """A disabled or enabled transparent score component."""

    name: str = Field(min_length=1)
    enabled: bool
    weight: float = Field(ge=0)


NullPreservation = Literal[
    "book_level_token_or_lemma_frequencies",
    "passage_counts",
    "passage_lengths",
    "book_or_genre_conditioned_lemma_frequencies",
]


class NullModelFamily(EchoesModel):
    """One disabled, declarative null family for future lexical experiments."""

    name: Literal["within_book_reassignment", "frequency_preserving_synthetic_passages"]
    enabled: Literal[False]
    required_preservation: list[NullPreservation] = Field(min_length=2)
    optional_preservation: list[
        Literal[
            "part_of_speech_distributions",
            "morphological_distributions",
            "local_ngram_characteristics",
        ]
    ] = Field(default_factory=list)
    invalid_surrogates: list[Literal["passage_order_only", "passage_label_only"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def family_preserves_its_required_marginals(self) -> Self:
        required = set(self.required_preservation)
        if self.name == "within_book_reassignment":
            if required != {
                "book_level_token_or_lemma_frequencies",
                "passage_counts",
                "passage_lengths",
            }:
                raise ValueError("within-book reassignment must preserve all governed marginals")
            if set(self.invalid_surrogates) != {"passage_order_only", "passage_label_only"}:
                raise ValueError("within-book reassignment must reject both invalid surrogates")
        elif required != {
            "passage_lengths",
            "book_or_genre_conditioned_lemma_frequencies",
        }:
            raise ValueError("synthetic passages must preserve length and conditioned frequencies")
        return self


class NullModelsConfig(EchoesModel):
    """Governance-only requirements for later repeated empirical null simulations."""

    status: Literal["planned"]
    enabled: Literal[False]
    repetitions: None = None
    families: list[NullModelFamily] = Field(min_length=2, max_length=2)
    required_threshold_metrics: list[
        Literal[
            "observed_candidate_count",
            "mean_null_candidate_count",
            "empirical_null_interval_95",
            "observed_to_null_enrichment",
            "empirical_tail_probability",
            "estimated_empirical_false_discovery_rate",
        ]
    ] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def required_families_and_metrics_are_unique(self) -> Self:
        families = [family.name for family in self.families]
        if set(families) != {
            "within_book_reassignment",
            "frequency_preserving_synthetic_passages",
        }:
            raise ValueError("both required lexical null-model families must be declared")
        if len(self.required_threshold_metrics) != len(set(self.required_threshold_metrics)):
            raise ValueError("required null-model threshold metrics must be unique")
        return self


class RareEvidenceConfig(EchoesModel):
    """Planned conjunctive evidence rule; no scoring engine is activated here."""

    status: Literal["planned"]
    enabled: Literal[False]
    total_corpus_frequency_max: int = Field(ge=1)
    require_independent_co_signal: Literal[True]
    allowed_co_signals: list[
        Literal[
            "ordered_sequence_similarity",
            "shared_rare_phrase",
            "syntactic_match",
            "second_rare_lexical_item",
            "independent_detector_family",
        ]
    ] = Field(min_length=1)
    planned_evidence_fields: list[
        Literal[
            "expected_cooccurrence_independence",
            "hypergeometric_p_value",
            "null_model_empirical_rate",
            "multiple_testing_adjustment",
        ]
    ] = Field(min_length=4, max_length=4)
    hypergeometric_role: Literal["baseline_only"]
    empirical_calibration_priority: Literal["book_or_genre_conditioned_permutation"]

    @model_validator(mode="after")
    def evidence_lists_are_unique(self) -> Self:
        if len(self.allowed_co_signals) != len(set(self.allowed_co_signals)):
            raise ValueError("rare-evidence co-signals must be unique")
        if len(self.planned_evidence_fields) != len(set(self.planned_evidence_fields)):
            raise ValueError("planned rare-evidence fields must be unique")
        return self


class ScoringConfig(EchoesModel):
    """Typed future-scoring governance without activating an analysis engine."""

    schema_version: Literal[2]
    status: Literal["planned"]
    random_seed: int = Field(ge=0)
    components: list[ScoreComponent]
    null_models: NullModelsConfig
    rare_evidence: RareEvidenceConfig


class ModelSpec(EchoesModel):
    """A pinned model declaration for a later experiment."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["planned", "approved"]


class ModelsConfig(EchoesModel):
    """Model registry; intentionally empty during Milestone 0."""

    schema_version: Literal[1]
    offline_only: bool
    models: list[ModelSpec]


class ReviewConfig(EchoesModel):
    """Placeholder review policy without a review application."""

    schema_version: Literal[1]
    status: Literal["planned"]
    preserve_rejections: Literal[True]
    require_evidence_trace: Literal[True]


CONFIG_SCHEMAS: Mapping[str, type[BaseModel]] = {
    "corpora.yaml": CorporaConfig,
    "normalization.yaml": NormalizationConfig,
    "hebrew_ingestion.yaml": HebrewIngestionConfig,
    "greek_ingestion.yaml": GreekIngestionConfig,
    "segmentation.yaml": SegmentationConfig,
    "scoring.yaml": ScoringConfig,
    "models.yaml": ModelsConfig,
    "review.yaml": ReviewConfig,
}
REQUIRED_CONFIG_FILES: frozenset[str] = frozenset(CONFIG_SCHEMAS)


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Local runtime paths and logging level."""

    config_dir: Path = Path("config")
    output_dir: Path = Path("outputs")
    log_level: str = "INFO"

    ENV_PREFIX: ClassVar[str] = "ECHOES_"

    @classmethod
    def from_environment(cls) -> RuntimeSettings:
        """Build settings from documented environment variables."""
        return cls(
            config_dir=Path(os.getenv("ECHOES_CONFIG_DIR", "config")),
            output_dir=Path(os.getenv("ECHOES_OUTPUT_DIR", "outputs")),
            log_level=os.getenv("ECHOES_LOG_LEVEL", "INFO").upper(),
        )


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ConfigLoadError(f"configuration file does not exist: {path}")

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigLoadError(f"could not parse {path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ConfigLoadError(f"configuration root must be a mapping: {path}")
    if not all(isinstance(key, str) for key in loaded):
        raise ConfigLoadError(f"configuration keys must be strings: {path}")
    return cast(dict[str, object], loaded)


def schema_for_path(path: Path) -> type[BaseModel]:
    """Select the strict schema associated with a configuration path."""
    if path.parent.name == "experiments":
        return ExperimentManifest
    try:
        return CONFIG_SCHEMAS[path.name]
    except KeyError as exc:
        raise ConfigLoadError(f"no configuration schema is registered for {path}") from exc


def load_config(path: Path) -> BaseModel:
    """Load one YAML file and validate it against its registered Pydantic schema."""
    values = _load_yaml_mapping(path)
    schema = schema_for_path(path)
    try:
        return schema.model_validate(values)
    except ValidationError as exc:
        raise ConfigLoadError(f"validation failed for {path}:\n{exc}") from exc


def validate_config_directory(config_dir: Path) -> dict[Path, BaseModel]:
    """Validate every project YAML configuration and require the Milestone 0 set."""
    if not config_dir.is_dir():
        raise ConfigLoadError(f"configuration directory does not exist: {config_dir}")

    paths = sorted(config_dir.rglob("*.yaml"))
    if not paths:
        raise ConfigLoadError(f"no YAML configuration files found in {config_dir}")

    validated = {path: load_config(path) for path in paths}
    experiment_locations: dict[str, Path] = {}
    for path, model in validated.items():
        if not isinstance(model, ExperimentManifest):
            continue
        previous = experiment_locations.get(model.experiment_name)
        if previous is not None:
            raise ConfigLoadError(
                f"duplicate experiment_name '{model.experiment_name}' in {previous} and {path}"
            )
        experiment_locations[model.experiment_name] = path
    present_root_files = {path.name for path in paths if path.parent == config_dir}
    missing = sorted(REQUIRED_CONFIG_FILES - present_root_files)
    if missing:
        missing_list = ", ".join(missing)
        raise ConfigLoadError(f"required configuration files are missing: {missing_list}")
    return validated
