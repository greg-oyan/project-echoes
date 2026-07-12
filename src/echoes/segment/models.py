"""Typed passage-segmentation rows and ordered Polars storage schemas.

The Pydantic models define row-level interchange and validation contracts.  The
matching Polars schemas define stable on-disk column order.  Full-corpus code is
expected to enforce these contracts with vectorized Polars checks rather than
constructing a Pydantic object for every membership row.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PASSAGE_SCHEMA_VERSION = 1
PASSAGE_ID_SCHEMA_VERSION = 1

Corpus = Literal["hebrew", "greek"]
AnalysisProfile = Literal["edition_complete", "critical_core"]
AnalysisReading = Literal["qere", "ketiv", "source"]
Granularity = Literal["clause", "sentence", "verse", "two_verse", "five_verse"]
MembershipBasis = Literal[
    "source_native",
    "qere_primary",
    "ketiv_verse_stream",
    "ketiv_sentence_alignment",
    "ketiv_clause_alignment",
    "window_composition",
]
StructuralResolutionStatus = Literal[
    "source_native",
    "resolved",
    "partially_resolved",
    "unresolved",
]

_REFERENCE_PATTERN = r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$"
_SHA256_PATTERN = r"^[a-f0-9]{64}$"
_PASSAGE_ID_PATTERN = r"^P_(?:HB|GNT)_[A-Z0-9_]+~[a-f0-9]{64}$"


class SegmentationSeverity(StrEnum):
    """Severity levels persisted by passage validation."""

    ERROR = "error"
    WARNING = "warning"
    INFORMATIONAL = "informational"


class SegmentationRow(BaseModel):
    """Strict common behavior for persisted segmentation rows."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


def _json_array(value: str) -> list[object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("must contain valid JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("must encode a JSON array")
    return parsed


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("must contain valid JSON") from exc
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise ValueError("must encode a JSON object with string keys")
    return parsed


class PassageRow(SegmentationRow):
    """One reconstructed passage with convenience boundary fields.

    Exact passage-to-token membership lives in :class:`PassageMembershipRow`;
    ``start_token_id`` and ``end_token_id`` are deliberately non-authoritative.
    """

    schema_version: Literal[1] = 1
    passage_id: str = Field(pattern=_PASSAGE_ID_PATTERN)
    identity_payload_sha256: str = Field(pattern=_SHA256_PATTERN)
    segmentation_run_id: str = Field(min_length=1)
    corpus: Corpus
    analysis_profile: AnalysisProfile
    analysis_reading: AnalysisReading
    granularity: Granularity
    book: str = Field(pattern=r"^[A-Z0-9]{3}$")
    book_order: int = Field(ge=1)
    start_reference: str = Field(pattern=_REFERENCE_PATTERN)
    end_reference: str = Field(pattern=_REFERENCE_PATTERN)
    reference_sequence_json: str
    source_unit_id: str | None = None
    start_token_id: str = Field(min_length=1)
    end_token_id: str = Field(min_length=1)
    token_count: int = Field(ge=1)
    visible_token_count: int = Field(ge=0)
    zero_width_token_count: int = Field(ge=0)
    punctuation_token_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    sentence_count: int = Field(ge=0)
    clause_count: int = Field(ge=0)
    source_ids_json: str
    source_versions_json: str
    surface_text: str
    normalized_text: str
    unpointed_text: str | None = None
    folded_text: str | None = None
    lemma_sequence_json: str
    root_sequence_json: str
    part_of_speech_sequence_json: str
    semantic_domain_sequence_json: str
    entity_ids_json: str
    participant_ids_json: str
    disputed_passage_flag: bool
    disputed_passage_ids_json: str
    reference_gap: bool
    ketiv_structural_uncertainty: bool
    profile_truncated: bool
    sensitivity_exclusion_count: int = Field(ge=0)
    previous_passage_id: str | None = Field(default=None, pattern=_PASSAGE_ID_PATTERN)
    next_passage_id: str | None = Field(default=None, pattern=_PASSAGE_ID_PATTERN)
    overlap_with_previous_token_count: int = Field(ge=0)
    overlap_with_next_token_count: int = Field(ge=0)
    segmentation_config_hash: str = Field(pattern=_SHA256_PATTERN)
    created_by_schema_version: Literal[1] = 1

    @field_validator(
        "reference_sequence_json",
        "source_ids_json",
        "source_versions_json",
        "lemma_sequence_json",
        "root_sequence_json",
        "part_of_speech_sequence_json",
        "semantic_domain_sequence_json",
        "entity_ids_json",
        "participant_ids_json",
        "disputed_passage_ids_json",
    )
    @classmethod
    def json_fields_are_arrays(cls, value: str) -> str:
        _json_array(value)
        return value

    @model_validator(mode="after")
    def passage_fields_are_consistent(self) -> Self:
        if self.corpus == "hebrew" and self.analysis_reading not in {"qere", "ketiv"}:
            raise ValueError("Hebrew passages require qere or ketiv analysis_reading")
        if self.corpus == "greek" and self.analysis_reading != "source":
            raise ValueError("Greek passages require source analysis_reading")
        if self.visible_token_count + self.zero_width_token_count != self.token_count:
            raise ValueError("visible and zero-width token counts must sum to token_count")
        if self.punctuation_token_count > self.visible_token_count:
            raise ValueError("punctuation_token_count cannot exceed visible_token_count")
        if self.overlap_with_previous_token_count > self.token_count:
            raise ValueError("previous overlap cannot exceed token_count")
        if self.overlap_with_next_token_count > self.token_count:
            raise ValueError("next overlap cannot exceed token_count")
        references = _json_array(self.reference_sequence_json)
        if not references or not all(isinstance(item, str) for item in references):
            raise ValueError("reference_sequence_json requires a nonempty string array")
        if references[0] != self.start_reference or references[-1] != self.end_reference:
            raise ValueError("start/end references must match the ordered reference sequence")
        for field_name in (
            "lemma_sequence_json",
            "root_sequence_json",
            "part_of_speech_sequence_json",
            "semantic_domain_sequence_json",
            "entity_ids_json",
            "participant_ids_json",
        ):
            values = _json_array(str(getattr(self, field_name)))
            if len(values) != self.token_count:
                raise ValueError(f"{field_name} length must equal token_count")
            if not all(item is None or isinstance(item, str) for item in values):
                raise ValueError(f"{field_name} values must be strings or null")
        source_ids = _json_array(self.source_ids_json)
        source_versions = _json_array(self.source_versions_json)
        if not source_ids or not all(isinstance(item, str) and item for item in source_ids):
            raise ValueError("source_ids_json requires a nonempty string array")
        if not source_versions or not all(
            isinstance(item, str) and item for item in source_versions
        ):
            raise ValueError("source_versions_json requires a nonempty string array")
        disputed_ids = _json_array(self.disputed_passage_ids_json)
        if not all(isinstance(item, str) and item for item in disputed_ids):
            raise ValueError("disputed_passage_ids_json values must be nonempty strings")
        if self.disputed_passage_flag != bool(disputed_ids):
            raise ValueError("disputed_passage_flag must match disputed_passage_ids_json")
        if self.corpus == "hebrew":
            if self.unpointed_text is None or self.folded_text is not None:
                raise ValueError("Hebrew passages require unpointed_text and no folded_text")
        elif self.folded_text is None or self.unpointed_text is not None:
            raise ValueError("Greek passages require folded_text and no unpointed_text")
        return self


PASSAGE_POLARS_SCHEMA = pl.Schema(
    {
        "schema_version": pl.Int16,
        "passage_id": pl.String,
        "identity_payload_sha256": pl.String,
        "segmentation_run_id": pl.String,
        "corpus": pl.String,
        "analysis_profile": pl.String,
        "analysis_reading": pl.String,
        "granularity": pl.String,
        "book": pl.String,
        "book_order": pl.Int16,
        "start_reference": pl.String,
        "end_reference": pl.String,
        "reference_sequence_json": pl.String,
        "source_unit_id": pl.String,
        "start_token_id": pl.String,
        "end_token_id": pl.String,
        "token_count": pl.Int64,
        "visible_token_count": pl.Int64,
        "zero_width_token_count": pl.Int64,
        "punctuation_token_count": pl.Int64,
        "word_count": pl.Int64,
        "sentence_count": pl.Int64,
        "clause_count": pl.Int64,
        "source_ids_json": pl.String,
        "source_versions_json": pl.String,
        "surface_text": pl.String,
        "normalized_text": pl.String,
        "unpointed_text": pl.String,
        "folded_text": pl.String,
        "lemma_sequence_json": pl.String,
        "root_sequence_json": pl.String,
        "part_of_speech_sequence_json": pl.String,
        "semantic_domain_sequence_json": pl.String,
        "entity_ids_json": pl.String,
        "participant_ids_json": pl.String,
        "disputed_passage_flag": pl.Boolean,
        "disputed_passage_ids_json": pl.String,
        "reference_gap": pl.Boolean,
        "ketiv_structural_uncertainty": pl.Boolean,
        "profile_truncated": pl.Boolean,
        "sensitivity_exclusion_count": pl.Int64,
        "previous_passage_id": pl.String,
        "next_passage_id": pl.String,
        "overlap_with_previous_token_count": pl.Int64,
        "overlap_with_next_token_count": pl.Int64,
        "segmentation_config_hash": pl.String,
        "created_by_schema_version": pl.Int16,
    }
)
PASSAGE_COLUMNS: tuple[str, ...] = tuple(PASSAGE_POLARS_SCHEMA)


class PassageMembershipRow(SegmentationRow):
    """Authoritative passage-to-token membership with both order domains."""

    passage_id: str = Field(pattern=_PASSAGE_ID_PATTERN)
    token_id: str = Field(min_length=1)
    position_in_passage: int = Field(ge=1)
    source_position_in_corpus: int = Field(ge=1)
    source_reference: str = Field(pattern=_REFERENCE_PATTERN)
    source_id: str = Field(min_length=1)
    variant_type: Literal["ketiv", "qere"] | None = None
    membership_basis: MembershipBasis
    structural_resolution_status: StructuralResolutionStatus
    segmentation_run_id: str = Field(min_length=1)
    corpus: Corpus
    analysis_profile: AnalysisProfile
    analysis_reading: AnalysisReading
    granularity: Granularity
    stream_position_in_corpus: int = Field(ge=1)
    source_edition_reference: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    locus_id: str | None = None

    @model_validator(mode="after")
    def reading_matches_corpus(self) -> Self:
        if self.corpus == "hebrew" and self.analysis_reading not in {"qere", "ketiv"}:
            raise ValueError("Hebrew membership requires qere or ketiv analysis_reading")
        if self.corpus == "greek" and self.analysis_reading != "source":
            raise ValueError("Greek membership requires source analysis_reading")
        return self


PASSAGE_MEMBERSHIP_POLARS_SCHEMA = pl.Schema(
    {
        "passage_id": pl.String,
        "token_id": pl.String,
        "position_in_passage": pl.Int64,
        "source_position_in_corpus": pl.Int64,
        "source_reference": pl.String,
        "source_id": pl.String,
        "variant_type": pl.String,
        "membership_basis": pl.String,
        "structural_resolution_status": pl.String,
        "segmentation_run_id": pl.String,
        "corpus": pl.String,
        "analysis_profile": pl.String,
        "analysis_reading": pl.String,
        "granularity": pl.String,
        "stream_position_in_corpus": pl.Int64,
        "source_edition_reference": pl.String,
        "source_version": pl.String,
        "locus_id": pl.String,
    }
)
PASSAGE_MEMBERSHIP_COLUMNS: tuple[str, ...] = tuple(PASSAGE_MEMBERSHIP_POLARS_SCHEMA)


class PassageAdjacencyRow(SegmentationRow):
    """A passage relationship separating source succession from continuity."""

    corpus: Corpus
    analysis_profile: AnalysisProfile
    analysis_reading: AnalysisReading
    granularity: Granularity
    from_passage_id: str = Field(pattern=_PASSAGE_ID_PATTERN)
    to_passage_id: str = Field(pattern=_PASSAGE_ID_PATTERN)
    source_successor: bool
    analytically_continuous: bool
    reference_gap: bool
    boundary_break: bool
    relation: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    segmentation_run_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def relationship_is_consistent(self) -> Self:
        if self.from_passage_id == self.to_passage_id:
            raise ValueError("adjacency requires two distinct passages")
        if self.analytically_continuous and self.boundary_break:
            raise ValueError("a boundary break cannot be analytically continuous")
        return self


PASSAGE_ADJACENCY_POLARS_SCHEMA = pl.Schema(
    {
        "corpus": pl.String,
        "analysis_profile": pl.String,
        "analysis_reading": pl.String,
        "granularity": pl.String,
        "from_passage_id": pl.String,
        "to_passage_id": pl.String,
        "source_successor": pl.Boolean,
        "analytically_continuous": pl.Boolean,
        "reference_gap": pl.Boolean,
        "boundary_break": pl.Boolean,
        "relation": pl.String,
        "reason": pl.String,
        "segmentation_run_id": pl.String,
    }
)
PASSAGE_ADJACENCY_COLUMNS: tuple[str, ...] = tuple(PASSAGE_ADJACENCY_POLARS_SCHEMA)


class SegmentationExclusionRow(SegmentationRow):
    """One explicit granularity-specific token exclusion."""

    exclusion_id: str = Field(min_length=1)
    segmentation_run_id: str = Field(min_length=1)
    corpus: Corpus
    analysis_profile: AnalysisProfile
    analysis_reading: AnalysisReading
    granularity: Granularity
    token_id: str = Field(min_length=1)
    locus_id: str | None = None
    source_reference: str = Field(pattern=_REFERENCE_PATTERN)
    reason_code: str = Field(min_length=1)
    resolution_status: str = Field(min_length=1)
    related_passage_ids_json: str
    notes: str
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_edition_reference: str = Field(min_length=1)
    stream_position_in_corpus: int = Field(ge=1)

    @field_validator("related_passage_ids_json")
    @classmethod
    def related_passage_ids_are_an_array(cls, value: str) -> str:
        values = _json_array(value)
        if not all(isinstance(item, str) and item for item in values):
            raise ValueError("related passage IDs must be nonempty strings")
        return value


SEGMENTATION_EXCLUSION_POLARS_SCHEMA = pl.Schema(
    {
        "exclusion_id": pl.String,
        "segmentation_run_id": pl.String,
        "corpus": pl.String,
        "analysis_profile": pl.String,
        "analysis_reading": pl.String,
        "granularity": pl.String,
        "token_id": pl.String,
        "locus_id": pl.String,
        "source_reference": pl.String,
        "reason_code": pl.String,
        "resolution_status": pl.String,
        "related_passage_ids_json": pl.String,
        "notes": pl.String,
        "source_id": pl.String,
        "source_version": pl.String,
        "source_edition_reference": pl.String,
        "stream_position_in_corpus": pl.Int64,
    }
)
SEGMENTATION_EXCLUSION_COLUMNS: tuple[str, ...] = tuple(SEGMENTATION_EXCLUSION_POLARS_SCHEMA)


class SegmentationIssueRow(SegmentationRow):
    """One deterministic segmentation or validation finding."""

    issue_id: str = Field(min_length=1)
    segmentation_run_id: str = Field(min_length=1)
    severity: SegmentationSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    corpus: Corpus | None = None
    analysis_profile: AnalysisProfile | None = None
    analysis_reading: AnalysisReading | None = None
    granularity: Granularity | None = None
    passage_id: str | None = Field(default=None, pattern=_PASSAGE_ID_PATTERN)
    token_id: str | None = None
    source_reference: str | None = Field(default=None, pattern=_REFERENCE_PATTERN)
    details_json: str

    @field_validator("details_json")
    @classmethod
    def details_are_an_object(cls, value: str) -> str:
        _json_object(value)
        return value


SEGMENTATION_ISSUE_POLARS_SCHEMA = pl.Schema(
    {
        "issue_id": pl.String,
        "segmentation_run_id": pl.String,
        "severity": pl.String,
        "code": pl.String,
        "message": pl.String,
        "corpus": pl.String,
        "analysis_profile": pl.String,
        "analysis_reading": pl.String,
        "granularity": pl.String,
        "passage_id": pl.String,
        "token_id": pl.String,
        "source_reference": pl.String,
        "details_json": pl.String,
    }
)
SEGMENTATION_ISSUE_COLUMNS: tuple[str, ...] = tuple(SEGMENTATION_ISSUE_POLARS_SCHEMA)


class SegmentationMetadataRow(SegmentationRow):
    """Run-level provenance, deterministic hashes, and execution telemetry."""

    segmentation_run_id: str = Field(min_length=1)
    passage_schema_version: Literal[1] = 1
    passage_id_schema_version: Literal[1] = 1
    segmentation_config_hash: str = Field(pattern=_SHA256_PATTERN)
    input_source_versions_json: str
    input_primary_identity_digests_json: str
    input_surface_lemma_digests_json: str
    input_analytical_digests_json: str
    input_oshb_supplement_digests_json: str
    enabled_corpora_json: str
    analysis_profiles_json: str
    analysis_readings_json: str
    granularities_json: str
    table_counts_json: str
    table_logical_hashes_json: str
    table_physical_hashes_json: str
    processing_environment_json: str
    runtime_seconds: float = Field(ge=0)
    approximate_peak_memory_bytes: int | None = Field(default=None, ge=0)

    @field_validator(
        "input_source_versions_json",
        "input_primary_identity_digests_json",
        "input_surface_lemma_digests_json",
        "input_analytical_digests_json",
        "input_oshb_supplement_digests_json",
        "table_counts_json",
        "table_logical_hashes_json",
        "table_physical_hashes_json",
        "processing_environment_json",
    )
    @classmethod
    def object_fields_are_objects(cls, value: str) -> str:
        _json_object(value)
        return value

    @field_validator(
        "enabled_corpora_json",
        "analysis_profiles_json",
        "analysis_readings_json",
        "granularities_json",
    )
    @classmethod
    def list_fields_are_arrays(cls, value: str) -> str:
        _json_array(value)
        return value


SEGMENTATION_METADATA_POLARS_SCHEMA = pl.Schema(
    {
        "segmentation_run_id": pl.String,
        "passage_schema_version": pl.Int16,
        "passage_id_schema_version": pl.Int16,
        "segmentation_config_hash": pl.String,
        "input_source_versions_json": pl.String,
        "input_primary_identity_digests_json": pl.String,
        "input_surface_lemma_digests_json": pl.String,
        "input_analytical_digests_json": pl.String,
        "input_oshb_supplement_digests_json": pl.String,
        "enabled_corpora_json": pl.String,
        "analysis_profiles_json": pl.String,
        "analysis_readings_json": pl.String,
        "granularities_json": pl.String,
        "table_counts_json": pl.String,
        "table_logical_hashes_json": pl.String,
        "table_physical_hashes_json": pl.String,
        "processing_environment_json": pl.String,
        "runtime_seconds": pl.Float64,
        "approximate_peak_memory_bytes": pl.Int64,
    }
)
SEGMENTATION_METADATA_COLUMNS: tuple[str, ...] = tuple(SEGMENTATION_METADATA_POLARS_SCHEMA)
