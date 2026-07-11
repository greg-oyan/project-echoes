"""Source-manifest schemas, loading, validation, and reporting."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
SOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"


class SourceManifestError(ValueError):
    """Raised when source governance documents cannot be loaded or validated."""


class SourceRole(StrEnum):
    """Research role of a source layer."""

    PRIMARY_DISCOVERY = "primary_discovery"
    BRIDGE = "bridge"
    SUPPLEMENTARY_ANNOTATION = "supplementary_annotation"
    TEXTUAL_VALIDATION = "textual_validation"
    RECEPTION_HISTORY = "reception_history"
    BENCHMARK = "benchmark"
    REFERENCE = "reference"


class SourceStatus(StrEnum):
    """Governance and acquisition lifecycle for a source."""

    PLANNED = "planned"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    BLOCKED = "blocked"
    ACQUIRED = "acquired"
    VALIDATED = "validated"
    DEPRECATED = "deprecated"


class RedistributionStatus(StrEnum):
    """Preliminary or reviewed redistribution classification."""

    PERMITTED = "permitted"
    DERIVED_OUTPUTS_ONLY = "derived_outputs_only"
    ACQUISITION_INSTRUCTIONS_ONLY = "acquisition_instructions_only"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


class MachineProcessingStatus(StrEnum):
    """Whether automated processing has been reviewed as permissible."""

    PERMITTED = "permitted"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class RawDataGitPolicy(StrEnum):
    """Repository policy for raw source files."""

    TRACKABLE = "trackable"
    METADATA_ONLY = "metadata_only"
    IGNORED_LOCAL_ONLY = "ignored_local_only"
    PROHIBITED = "prohibited"


class LicenseReviewStatus(StrEnum):
    """Progress of a source-specific licensing review."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class SourceLanguage(StrEnum):
    """Languages represented by a source."""

    HEBREW = "hebrew"
    ARAMAIC = "aramaic"
    GREEK = "greek"
    ENGLISH = "english"
    MULTILINGUAL = "multilingual"


class SourceManifest(BaseModel):
    """One proposed or activated external source with explicit governance state."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(pattern=SOURCE_ID_PATTERN)
    source_name: str = Field(min_length=1)
    corpus: str = Field(min_length=1)
    role: SourceRole
    language: list[SourceLanguage] = Field(min_length=1)
    edition: str | None
    provider: str = Field(min_length=1)
    repository_or_location: str = Field(min_length=1)
    version_or_commit: str | None
    download_date: date | None
    license: str | None
    license_url: str | None
    license_review_status: LicenseReviewStatus
    required_attribution: str | None
    redistribution_status: RedistributionStatus
    machine_processing_status: MachineProcessingStatus
    raw_data_git_policy: RawDataGitPolicy
    expected_files: list[str]
    file_hashes: dict[str, str]
    ingest_adapter: str | None
    research_purpose: str = Field(min_length=1)
    known_limitations: list[str]
    notes: list[str]
    confirmed_information: list[str]
    unresolved_questions: list[str]
    status: SourceStatus

    @field_validator("file_hashes")
    @classmethod
    def hashes_are_sha256(cls, hashes: dict[str, str]) -> dict[str, str]:
        """Require lowercase or uppercase 64-character hexadecimal SHA-256 values."""
        invalid = [name for name, digest in hashes.items() if not SHA256_PATTERN.fullmatch(digest)]
        if invalid:
            names = ", ".join(sorted(invalid))
            msg = f"file_hashes must contain SHA-256 digests; invalid entries: {names}"
            raise ValueError(msg)
        return {name: digest.lower() for name, digest in hashes.items()}

    @field_validator("download_date", mode="before")
    @classmethod
    def download_date_is_iso_date(cls, value: object) -> object:
        if value is None or (isinstance(value, date) and not isinstance(value, datetime)):
            return value
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                msg = "download_date must use YYYY-MM-DD or null"
                raise ValueError(msg) from exc
            if parsed.isoformat() == value:
                return parsed
        msg = "download_date must use YYYY-MM-DD or null"
        raise ValueError(msg)

    @field_validator("language")
    @classmethod
    def languages_are_unique(cls, languages: list[SourceLanguage]) -> list[SourceLanguage]:
        if len(languages) != len(set(languages)):
            msg = "language values must be unique"
            raise ValueError(msg)
        return languages

    @field_validator("expected_files")
    @classmethod
    def expected_files_are_unique(cls, expected_files: list[str]) -> list[str]:
        if len(expected_files) != len(set(expected_files)):
            msg = "expected_files values must be unique"
            raise ValueError(msg)
        return expected_files

    @model_validator(mode="after")
    def governance_state_is_consistent(self) -> Self:
        """Prevent lifecycle states that exceed the recorded evidence or permissions."""
        if self.role is SourceRole.PRIMARY_DISCOVERY and not _known_value(self.edition):
            msg = "primary_discovery sources must define a textual edition"
            raise ValueError(msg)

        if (
            self.status
            in {
                SourceStatus.APPROVED,
                SourceStatus.ACQUIRED,
                SourceStatus.VALIDATED,
            }
            and not self.licensing_complete
        ):
            msg = f"status '{self.status}' requires a complete licensing review"
            raise ValueError(msg)

        if self.status in {SourceStatus.ACQUIRED, SourceStatus.VALIDATED}:
            if not _known_value(self.version_or_commit):
                msg = f"status '{self.status}' requires version_or_commit"
                raise ValueError(msg)
            if self.download_date is None:
                msg = f"status '{self.status}' requires download_date"
                raise ValueError(msg)

        if self.raw_data_git_policy is RawDataGitPolicy.TRACKABLE and (
            self.redistribution_status is not RedistributionStatus.PERMITTED
            or self.machine_processing_status is not MachineProcessingStatus.PERMITTED
        ):
            msg = (
                "raw data may be Git-trackable only when redistribution and "
                "machine processing are both permitted"
            )
            raise ValueError(msg)

        if self.file_hashes and not self.expected_files:
            msg = "file_hashes cannot be supplied when expected_files is empty"
            raise ValueError(msg)
        unexpected_hashes = sorted(set(self.file_hashes) - set(self.expected_files))
        if unexpected_hashes:
            names = ", ".join(unexpected_hashes)
            msg = f"file_hashes keys must also appear in expected_files: {names}"
            raise ValueError(msg)

        if not self.known_limitations and not self.notes:
            msg = "every source must record notes or known_limitations"
            raise ValueError(msg)
        return self

    @property
    def licensing_complete(self) -> bool:
        """Return whether all approval-blocking licensing fields have been resolved."""
        return (
            self.license_review_status is LicenseReviewStatus.COMPLETE
            and _known_value(self.license)
            and _known_value(self.license_url)
            and _known_value(self.required_attribution)
            and self.redistribution_status is not RedistributionStatus.UNKNOWN
            and self.machine_processing_status is not MachineProcessingStatus.UNKNOWN
        )


class SourceManifestDocument(BaseModel):
    """On-disk YAML document containing one or more source records."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    sources: list[SourceManifest] = Field(min_length=1)


class SourceCatalog(BaseModel):
    """Validated cross-document collection with globally unique source IDs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    sources: list[SourceManifest]

    @model_validator(mode="after")
    def source_ids_are_unique(self) -> Self:
        ids = [source.source_id for source in self.sources]
        duplicates = sorted(source_id for source_id, count in Counter(ids).items() if count > 1)
        if duplicates:
            duplicate_list = ", ".join(duplicates)
            msg = f"duplicate source_id values: {duplicate_list}"
            raise ValueError(msg)
        return self

    def find(self, source_id: str) -> SourceManifest | None:
        """Return one source by stable ID, or None when it is absent."""
        return next((source for source in self.sources if source.source_id == source_id), None)


class SourceSummary(BaseModel):
    """Aggregate counts used by validation and audit output."""

    total: int
    by_role: dict[str, int]
    by_status: dict[str, int]
    by_redistribution: dict[str, int]
    licensing_complete: int
    licensing_incomplete: int


def _known_value(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    return bool(normalized) and normalized not in {
        "unknown",
        "tbd",
        "to be determined",
        "unresolved",
        "pending",
    }


def _manifest_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise SourceManifestError(f"source manifest path does not exist: {path}")
    paths = sorted((*path.rglob("*.yaml"), *path.rglob("*.yml")))
    if not paths:
        raise SourceManifestError(f"no source manifest YAML files found in {path}")
    return paths


def _load_document(path: Path) -> SourceManifestDocument:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SourceManifestError(f"could not parse source manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SourceManifestError(f"source manifest root must be a mapping: {path}")
    try:
        return SourceManifestDocument.model_validate(cast(dict[str, object], raw))
    except ValidationError as exc:
        raise SourceManifestError(f"validation failed for source manifest {path}:\n{exc}") from exc


def load_source_catalog(path: Path) -> SourceCatalog:
    """Load one source-manifest file or merge a directory of manifest documents."""
    sources: list[SourceManifest] = []
    locations: dict[str, Path] = {}
    for manifest_path in _manifest_paths(path):
        document = _load_document(manifest_path)
        for source in document.sources:
            previous = locations.get(source.source_id)
            if previous is not None:
                raise SourceManifestError(
                    f"duplicate source_id '{source.source_id}' in {previous} and {manifest_path}"
                )
            locations[source.source_id] = manifest_path
            sources.append(source)
    try:
        return SourceCatalog(sources=sources)
    except ValidationError as exc:  # defensive: cross-record checks also live on the model
        raise SourceManifestError(f"cross-record source validation failed:\n{exc}") from exc


def summarize_sources(catalog: SourceCatalog) -> SourceSummary:
    """Count source records by governance dimensions."""
    role_counts = Counter(source.role.value for source in catalog.sources)
    status_counts = Counter(source.status.value for source in catalog.sources)
    redistribution_counts = Counter(
        source.redistribution_status.value for source in catalog.sources
    )
    complete = sum(source.licensing_complete for source in catalog.sources)
    return SourceSummary(
        total=len(catalog.sources),
        by_role=dict(sorted(role_counts.items())),
        by_status=dict(sorted(status_counts.items())),
        by_redistribution=dict(sorted(redistribution_counts.items())),
        licensing_complete=complete,
        licensing_incomplete=len(catalog.sources) - complete,
    )


def serialize_source(source: SourceManifest) -> str:
    """Serialize one validated record as stable, normalized YAML."""
    values = source.model_dump(mode="json", exclude_none=False)
    return yaml.safe_dump(values, sort_keys=False, allow_unicode=True)


def serialize_source_catalog(catalog: SourceCatalog) -> str:
    """Serialize a complete validated source catalog as normalized YAML."""
    values = catalog.model_dump(mode="json", exclude_none=False)
    return yaml.safe_dump(values, sort_keys=False, allow_unicode=True)
