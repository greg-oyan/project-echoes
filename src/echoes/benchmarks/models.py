"""Typed rows and stable Polars schemas for the known-link benchmark.

The Pydantic models are row-level interchange contracts.  Full-source code
must validate large frames with the paired Polars schemas rather than create a
Pydantic object for every row.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BENCHMARK_SCHEMA_VERSION = 1
RELATIONSHIP_ID_SCHEMA_VERSION = 1
MAPPING_SCHEMA_VERSION = 1

_SHA256_PATTERN = r"^[a-f0-9]{64}$"
_ID_PATTERN = r"^B[A-Z]{1,3}_[a-f0-9]{64}$"


class BenchmarkSeverity(StrEnum):
    """Governed benchmark issue severities."""

    ERROR = "error"
    WARNING = "warning"
    INFORMATIONAL = "informational"


class BenchmarkRow(BaseModel):
    """Strict common behavior for persisted benchmark rows."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


def _validate_json_array(value: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("must contain valid JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("must encode a JSON array")
    return value


def _validate_json_object(value: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("must contain valid JSON") from exc
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise ValueError("must encode a JSON object with string keys")
    return value


class BenchmarkSourceRecordRow(BenchmarkRow):
    """One retained occurrence of a raw source record."""

    benchmark_schema_version: Literal[1] = 1
    source_record_id: str = Field(pattern=_ID_PATTERN)
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_archive_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_file: str = Field(min_length=1)
    source_line_number: int = Field(ge=1)
    raw_record_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_reference_a: str
    source_reference_b: str
    source_weight: int | None
    source_direction: str = Field(min_length=1)
    parse_status: str = Field(min_length=1)
    notes: str


BENCHMARK_SOURCE_RECORDS_POLARS_SCHEMA = pl.Schema(
    {
        "benchmark_schema_version": pl.Int16,
        "source_record_id": pl.String,
        "source_id": pl.String,
        "source_version": pl.String,
        "source_archive_sha256": pl.String,
        "source_file": pl.String,
        "source_line_number": pl.Int64,
        "raw_record_sha256": pl.String,
        "source_reference_a": pl.String,
        "source_reference_b": pl.String,
        "source_weight": pl.Int64,
        "source_direction": pl.String,
        "parse_status": pl.String,
        "notes": pl.String,
    }
)
BENCHMARK_SOURCE_RECORDS_COLUMNS = tuple(BENCHMARK_SOURCE_RECORDS_POLARS_SCHEMA)


class BenchmarkRelationshipRow(BenchmarkRow):
    """One normalized, source-specific known relationship."""

    relationship_id: str = Field(pattern=_ID_PATTERN)
    benchmark_schema_version: Literal[1] = 1
    tier: Literal[1, 2, 3]
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_reference_scheme: str = Field(min_length=1)
    source_reference_a: str = Field(min_length=1)
    source_reference_b: str = Field(min_length=1)
    relationship_direction: str = Field(min_length=1)
    relationship_class: str = Field(min_length=1)
    source_record_count: int = Field(ge=1)
    source_weight_sum: int
    source_weight_max: int | None
    canonical_directed_pair_id: str = Field(pattern=_ID_PATTERN)
    canonical_undirected_pair_id: str = Field(pattern=_ID_PATTERN)
    weak_supervision_eligible: bool
    knownness_filter_eligible: bool
    primary_evaluation_eligible: bool
    tier1_eligible: bool
    data_quality_status: str = Field(min_length=1)
    license_status: str = Field(min_length=1)
    provenance_json: str
    notes: str

    _provenance_is_object = field_validator("provenance_json")(_validate_json_object)

    @model_validator(mode="after")
    def tier_three_is_not_primary_or_tier_one(self) -> Self:
        if self.tier == 3 and (self.primary_evaluation_eligible or self.tier1_eligible):
            raise ValueError("Tier 3 relationships cannot be primary evaluation or Tier 1")
        return self


BENCHMARK_RELATIONSHIPS_POLARS_SCHEMA = pl.Schema(
    {
        "relationship_id": pl.String,
        "benchmark_schema_version": pl.Int16,
        "tier": pl.Int8,
        "source_id": pl.String,
        "source_version": pl.String,
        "source_reference_scheme": pl.String,
        "source_reference_a": pl.String,
        "source_reference_b": pl.String,
        "relationship_direction": pl.String,
        "relationship_class": pl.String,
        "source_record_count": pl.Int64,
        "source_weight_sum": pl.Int64,
        "source_weight_max": pl.Int64,
        "canonical_directed_pair_id": pl.String,
        "canonical_undirected_pair_id": pl.String,
        "weak_supervision_eligible": pl.Boolean,
        "knownness_filter_eligible": pl.Boolean,
        "primary_evaluation_eligible": pl.Boolean,
        "tier1_eligible": pl.Boolean,
        "data_quality_status": pl.String,
        "license_status": pl.String,
        "provenance_json": pl.String,
        "notes": pl.String,
    }
)
BENCHMARK_RELATIONSHIPS_COLUMNS = tuple(BENCHMARK_RELATIONSHIPS_POLARS_SCHEMA)


class BenchmarkRelationshipSourceRecordRow(BenchmarkRow):
    """Trace one normalized relationship to one raw record occurrence."""

    relationship_id: str = Field(pattern=_ID_PATTERN)
    source_record_id: str = Field(pattern=_ID_PATTERN)
    link_role: str = Field(min_length=1)


BENCHMARK_RELATIONSHIP_SOURCE_RECORDS_POLARS_SCHEMA = pl.Schema(
    {"relationship_id": pl.String, "source_record_id": pl.String, "link_role": pl.String}
)
BENCHMARK_RELATIONSHIP_SOURCE_RECORDS_COLUMNS = tuple(
    BENCHMARK_RELATIONSHIP_SOURCE_RECORDS_POLARS_SCHEMA
)


class BenchmarkEndpointRow(BenchmarkRow):
    """One parsed source-scheme side of a relationship."""

    endpoint_id: str = Field(pattern=_ID_PATTERN)
    relationship_id: str = Field(pattern=_ID_PATTERN)
    endpoint_side: Literal["a", "b"]
    source_reference: str
    source_reference_scheme: str = Field(min_length=1)
    parsed_book: str | None
    parsed_start_chapter: int | None = Field(default=None, ge=1)
    parsed_start_verse: int | None = Field(default=None, ge=1)
    parsed_end_chapter: int | None = Field(default=None, ge=1)
    parsed_end_verse: int | None = Field(default=None, ge=1)
    is_range: bool
    parse_status: str = Field(min_length=1)

    @model_validator(mode="after")
    def parsed_coordinates_are_complete(self) -> Self:
        coordinates = (
            self.parsed_book,
            self.parsed_start_chapter,
            self.parsed_start_verse,
            self.parsed_end_chapter,
            self.parsed_end_verse,
        )
        populated = sum(value is not None for value in coordinates)
        if populated not in {0, len(coordinates)}:
            raise ValueError("parsed endpoint coordinates must be wholly present or absent")
        return self


BENCHMARK_ENDPOINTS_POLARS_SCHEMA = pl.Schema(
    {
        "endpoint_id": pl.String,
        "relationship_id": pl.String,
        "endpoint_side": pl.String,
        "source_reference": pl.String,
        "source_reference_scheme": pl.String,
        "parsed_book": pl.String,
        "parsed_start_chapter": pl.Int32,
        "parsed_start_verse": pl.Int32,
        "parsed_end_chapter": pl.Int32,
        "parsed_end_verse": pl.Int32,
        "is_range": pl.Boolean,
        "parse_status": pl.String,
    }
)
BENCHMARK_ENDPOINTS_COLUMNS = tuple(BENCHMARK_ENDPOINTS_POLARS_SCHEMA)


MappingStatus = Literal[
    "mapped_verified",
    "mapped_provisional",
    "mapped_partial",
    "unresolved_reference",
    "unresolved_versification",
    "unresolved_missing_target",
    "excluded_by_profile",
    "invalid",
]


class BenchmarkEndpointMappingRow(BenchmarkRow):
    """A separate, uncertainty-bearing endpoint-to-passage mapping."""

    mapping_id: str = Field(pattern=_ID_PATTERN)
    endpoint_id: str = Field(pattern=_ID_PATTERN)
    target_corpus: Literal["hebrew", "greek"]
    target_analysis_profile: Literal["edition_complete", "critical_core"]
    target_analysis_reading: Literal["qere", "source"]
    target_granularity: Literal["verse"]
    target_passage_ids_json: str
    target_reference_sequence_json: str
    mapping_method: str = Field(min_length=1)
    mapping_confidence: str = Field(min_length=1)
    mapping_status: MappingStatus
    reference_gap: bool
    disputed_passage_flag: bool
    disputed_passage_ids_json: str
    crosswalk_source: str | None
    crosswalk_version: str | None
    ambiguity_reason: str | None
    notes: str

    _passage_ids_are_array = field_validator("target_passage_ids_json")(_validate_json_array)
    _references_are_array = field_validator("target_reference_sequence_json")(_validate_json_array)
    _disputed_ids_are_array = field_validator("disputed_passage_ids_json")(_validate_json_array)

    @model_validator(mode="after")
    def mapping_fields_are_consistent(self) -> Self:
        passage_ids = json.loads(self.target_passage_ids_json)
        references = json.loads(self.target_reference_sequence_json)
        disputed_ids = json.loads(self.disputed_passage_ids_json)
        if len(passage_ids) != len(references):
            raise ValueError("target passage IDs and references must have equal length")
        if self.disputed_passage_flag != bool(disputed_ids):
            raise ValueError("disputed flag must match disputed passage IDs")
        if self.target_corpus == "hebrew" and self.target_analysis_reading != "qere":
            raise ValueError("Hebrew benchmark mappings require the qere reading")
        if self.target_corpus == "greek" and self.target_analysis_reading != "source":
            raise ValueError("Greek benchmark mappings require the source reading")
        return self


BENCHMARK_ENDPOINT_MAPPINGS_POLARS_SCHEMA = pl.Schema(
    {
        "mapping_id": pl.String,
        "endpoint_id": pl.String,
        "target_corpus": pl.String,
        "target_analysis_profile": pl.String,
        "target_analysis_reading": pl.String,
        "target_granularity": pl.String,
        "target_passage_ids_json": pl.String,
        "target_reference_sequence_json": pl.String,
        "mapping_method": pl.String,
        "mapping_confidence": pl.String,
        "mapping_status": pl.String,
        "reference_gap": pl.Boolean,
        "disputed_passage_flag": pl.Boolean,
        "disputed_passage_ids_json": pl.String,
        "crosswalk_source": pl.String,
        "crosswalk_version": pl.String,
        "ambiguity_reason": pl.String,
        "notes": pl.String,
    }
)
BENCHMARK_ENDPOINT_MAPPINGS_COLUMNS = tuple(BENCHMARK_ENDPOINT_MAPPINGS_POLARS_SCHEMA)


class BenchmarkLeakageGroupRow(BenchmarkRow):
    """One relationship membership in one explicit leakage group."""

    leakage_group_id: str = Field(pattern=_ID_PATTERN)
    relationship_id: str = Field(pattern=_ID_PATTERN)
    group_type: str = Field(min_length=1)
    group_key: str = Field(min_length=1)
    group_method: str = Field(min_length=1)
    notes: str


BENCHMARK_LEAKAGE_GROUPS_POLARS_SCHEMA = pl.Schema(
    {
        "leakage_group_id": pl.String,
        "relationship_id": pl.String,
        "group_type": pl.String,
        "group_key": pl.String,
        "group_method": pl.String,
        "notes": pl.String,
    }
)
BENCHMARK_LEAKAGE_GROUPS_COLUMNS = tuple(BENCHMARK_LEAKAGE_GROUPS_POLARS_SCHEMA)


class BenchmarkSplitAssignmentRow(BenchmarkRow):
    """One relationship assignment for one governed split strategy."""

    split_assignment_id: str = Field(pattern=_ID_PATTERN)
    benchmark_version: str = Field(min_length=1)
    relationship_id: str = Field(pattern=_ID_PATTERN)
    split_strategy: str = Field(min_length=1)
    partition: Literal["train", "development", "test", "excluded"]
    leakage_group_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    seed: int | None = Field(default=None, ge=0)
    eligibility_status: str = Field(min_length=1)
    exclusion_reason: str | None
    config_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def excluded_assignments_have_reasons(self) -> Self:
        if self.partition == "excluded" and not self.exclusion_reason:
            raise ValueError("excluded split assignments require an exclusion reason")
        return self


BENCHMARK_SPLIT_ASSIGNMENTS_POLARS_SCHEMA = pl.Schema(
    {
        "split_assignment_id": pl.String,
        "benchmark_version": pl.String,
        "relationship_id": pl.String,
        "split_strategy": pl.String,
        "partition": pl.String,
        "leakage_group_id": pl.String,
        "seed": pl.Int64,
        "eligibility_status": pl.String,
        "exclusion_reason": pl.String,
        "config_hash": pl.String,
    }
)
BENCHMARK_SPLIT_ASSIGNMENTS_COLUMNS = tuple(BENCHMARK_SPLIT_ASSIGNMENTS_POLARS_SCHEMA)


class BenchmarkPresumedNegativeRow(BenchmarkRow):
    """One governed contrastive pair that is never called a proven negative."""

    contrastive_id: str = Field(pattern=_ID_PATTERN)
    benchmark_version: str = Field(min_length=1)
    passage_a_id: str = Field(min_length=1)
    passage_b_id: str = Field(min_length=1)
    corpus_pair: str = Field(min_length=1)
    negative_strategy: str = Field(min_length=1)
    presumed_negative: Literal[True]
    positive_graph_checked: Literal[True]
    reverse_pair_checked: Literal[True]
    passage_overlap_checked: Literal[True]
    leakage_checked: Literal[True]
    length_difference: int = Field(ge=0)
    book_pair: str = Field(min_length=1)
    genre_pair: str = Field(min_length=1)
    split_strategy: str = Field(min_length=1)
    partition: Literal["train", "development", "test"]
    seed: int = Field(ge=0)
    generation_config_hash: str = Field(pattern=_SHA256_PATTERN)
    notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def passages_are_distinct(self) -> Self:
        if self.passage_a_id == self.passage_b_id:
            raise ValueError("presumed-negative passages must be distinct")
        return self


BENCHMARK_PRESUMED_NEGATIVES_POLARS_SCHEMA = pl.Schema(
    {
        "contrastive_id": pl.String,
        "benchmark_version": pl.String,
        "passage_a_id": pl.String,
        "passage_b_id": pl.String,
        "corpus_pair": pl.String,
        "negative_strategy": pl.String,
        "presumed_negative": pl.Boolean,
        "positive_graph_checked": pl.Boolean,
        "reverse_pair_checked": pl.Boolean,
        "passage_overlap_checked": pl.Boolean,
        "leakage_checked": pl.Boolean,
        "length_difference": pl.Int64,
        "book_pair": pl.String,
        "genre_pair": pl.String,
        "split_strategy": pl.String,
        "partition": pl.String,
        "seed": pl.Int64,
        "generation_config_hash": pl.String,
        "notes": pl.String,
    }
)
BENCHMARK_PRESUMED_NEGATIVES_COLUMNS = tuple(BENCHMARK_PRESUMED_NEGATIVES_POLARS_SCHEMA)


class BenchmarkIssueRow(BenchmarkRow):
    """One deterministic build or validation issue."""

    issue_id: str = Field(pattern=_ID_PATTERN)
    benchmark_run_id: str | None
    severity: BenchmarkSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    artifact: str | None
    source_record_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    relationship_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    endpoint_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    details_json: str

    _details_are_object = field_validator("details_json")(_validate_json_object)


BENCHMARK_ISSUES_POLARS_SCHEMA = pl.Schema(
    {
        "issue_id": pl.String,
        "benchmark_run_id": pl.String,
        "severity": pl.String,
        "code": pl.String,
        "message": pl.String,
        "artifact": pl.String,
        "source_record_id": pl.String,
        "relationship_id": pl.String,
        "endpoint_id": pl.String,
        "details_json": pl.String,
    }
)
BENCHMARK_ISSUES_COLUMNS = tuple(BENCHMARK_ISSUES_POLARS_SCHEMA)


class BenchmarkMetadataRow(BenchmarkRow):
    """One benchmark run's deterministic inputs, outputs, and telemetry."""

    benchmark_run_id: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    benchmark_schema_version: Literal[1] = 1
    relationship_id_schema_version: Literal[1] = 1
    mapping_schema_version: Literal[1] = 1
    source_versions_json: str
    source_archive_hashes_json: str
    source_file_hashes_json: str
    source_audit_json: str
    tier1_header_sha256: str = Field(pattern=_SHA256_PATTERN)
    passage_input_run_id: str = Field(min_length=1)
    passage_logical_hashes_json: str
    relationship_count: int = Field(ge=0)
    endpoint_count: int = Field(ge=0)
    mapping_count: int = Field(ge=0)
    leakage_group_counts_json: str
    split_counts_json: str
    negative_counts_json: str
    configuration_hash: str = Field(pattern=_SHA256_PATTERN)
    logical_table_hashes_json: str
    physical_table_hashes_json: str
    processing_environment_json: str
    runtime_seconds: float = Field(ge=0.0)
    storage_footprint_bytes: int = Field(ge=0)

    _objects_are_json = field_validator(
        "source_versions_json",
        "source_archive_hashes_json",
        "source_file_hashes_json",
        "source_audit_json",
        "passage_logical_hashes_json",
        "leakage_group_counts_json",
        "split_counts_json",
        "negative_counts_json",
        "logical_table_hashes_json",
        "physical_table_hashes_json",
        "processing_environment_json",
    )(_validate_json_object)


BENCHMARK_METADATA_POLARS_SCHEMA = pl.Schema(
    {
        "benchmark_run_id": pl.String,
        "benchmark_version": pl.String,
        "benchmark_schema_version": pl.Int16,
        "relationship_id_schema_version": pl.Int16,
        "mapping_schema_version": pl.Int16,
        "source_versions_json": pl.String,
        "source_archive_hashes_json": pl.String,
        "source_file_hashes_json": pl.String,
        "source_audit_json": pl.String,
        "tier1_header_sha256": pl.String,
        "passage_input_run_id": pl.String,
        "passage_logical_hashes_json": pl.String,
        "relationship_count": pl.Int64,
        "endpoint_count": pl.Int64,
        "mapping_count": pl.Int64,
        "leakage_group_counts_json": pl.String,
        "split_counts_json": pl.String,
        "negative_counts_json": pl.String,
        "configuration_hash": pl.String,
        "logical_table_hashes_json": pl.String,
        "physical_table_hashes_json": pl.String,
        "processing_environment_json": pl.String,
        "runtime_seconds": pl.Float64,
        "storage_footprint_bytes": pl.Int64,
    }
)
BENCHMARK_METADATA_COLUMNS = tuple(BENCHMARK_METADATA_POLARS_SCHEMA)


BenchmarkArtifactName = Literal[
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
]

BENCHMARK_ARTIFACT_NAMES: tuple[BenchmarkArtifactName, ...] = (
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
)

BENCHMARK_ARTIFACT_SCHEMAS: dict[BenchmarkArtifactName, pl.Schema] = {
    "benchmark_source_records": BENCHMARK_SOURCE_RECORDS_POLARS_SCHEMA,
    "benchmark_relationships": BENCHMARK_RELATIONSHIPS_POLARS_SCHEMA,
    "benchmark_relationship_source_records": BENCHMARK_RELATIONSHIP_SOURCE_RECORDS_POLARS_SCHEMA,
    "benchmark_endpoints": BENCHMARK_ENDPOINTS_POLARS_SCHEMA,
    "benchmark_endpoint_mappings": BENCHMARK_ENDPOINT_MAPPINGS_POLARS_SCHEMA,
    "benchmark_leakage_groups": BENCHMARK_LEAKAGE_GROUPS_POLARS_SCHEMA,
    "benchmark_split_assignments": BENCHMARK_SPLIT_ASSIGNMENTS_POLARS_SCHEMA,
    "benchmark_presumed_negatives": BENCHMARK_PRESUMED_NEGATIVES_POLARS_SCHEMA,
    "benchmark_issues": BENCHMARK_ISSUES_POLARS_SCHEMA,
    "benchmark_metadata": BENCHMARK_METADATA_POLARS_SCHEMA,
}

BENCHMARK_ARTIFACT_COLUMNS: dict[BenchmarkArtifactName, tuple[str, ...]] = {
    name: tuple(schema) for name, schema in BENCHMARK_ARTIFACT_SCHEMAS.items()
}
