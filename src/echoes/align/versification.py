"""Versification-crosswalk schema and validation (Milestone 4 mapping layer).

The crosswalk is a separate mapping layer per master plan section 10.5.  It
maps edition-specific references for comparison and must never participate in
source-edition token-ID generation or rewrite a source edition's own verse
identifiers.  This module therefore deliberately imports nothing from
``echoes.corpus.token_ids`` and exposes only schema validation; no crosswalk
data rows ship with Milestone 4 preparation.
"""

from __future__ import annotations

import re
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REFERENCE_PATTERN = re.compile(r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*(?:[a-z])?$")
CROSSWALK_ID_PATTERN = r"^vx-[a-z0-9]+(?:-[a-z0-9]+)*$"


class CrosswalkValidationError(ValueError):
    """Raised when a versification crosswalk document cannot be validated."""


class MappingType(StrEnum):
    """Supported reference-mapping relationships between two editions."""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    UNMATCHED_SOURCE = "unmatched_source"
    ADDITION_IN_TARGET = "addition_in_target"
    ALTERNATE_STRUCTURE = "alternate_structure"


class AlignmentMethod(StrEnum):
    """How a mapping row was produced; every row must declare one."""

    PUBLISHED_CROSSWALK_TABLE = "published_crosswalk_table"
    RULE_BASED = "rule_based"
    STATISTICAL = "statistical"
    MANUAL = "manual"


class CrosswalkRow(BaseModel):
    """One edition-to-edition reference mapping with method and confidence."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    crosswalk_id: str = Field(pattern=CROSSWALK_ID_PATTERN)
    source_references: list[str] = Field(default_factory=list)
    target_references: list[str] = Field(default_factory=list)
    mapping_type: MappingType
    alignment_method: AlignmentMethod
    alignment_confidence: float = Field(ge=0.0, le=1.0)
    notes: str | None = None

    @model_validator(mode="after")
    def references_match_mapping_type(self) -> Self:
        for reference in (*self.source_references, *self.target_references):
            if REFERENCE_PATTERN.fullmatch(reference) is None:
                raise ValueError(f"malformed edition reference: {reference!r}")
        source_count = len(self.source_references)
        target_count = len(self.target_references)
        constraints: dict[MappingType, tuple[bool, str]] = {
            MappingType.ONE_TO_ONE: (
                source_count == 1 and target_count == 1,
                "one_to_one requires exactly one source and one target reference",
            ),
            MappingType.ONE_TO_MANY: (
                source_count == 1 and target_count > 1,
                "one_to_many requires one source and multiple target references",
            ),
            MappingType.MANY_TO_ONE: (
                source_count > 1 and target_count == 1,
                "many_to_one requires multiple source and one target reference",
            ),
            MappingType.UNMATCHED_SOURCE: (
                source_count >= 1 and target_count == 0,
                "unmatched_source requires source references and no target references",
            ),
            MappingType.ADDITION_IN_TARGET: (
                source_count == 0 and target_count >= 1,
                "addition_in_target requires target references and no source references",
            ),
            MappingType.ALTERNATE_STRUCTURE: (
                source_count >= 1 and target_count >= 1,
                "alternate_structure requires references on both sides",
            ),
        }
        valid, message = constraints[self.mapping_type]
        if not valid:
            raise ValueError(message)
        return self


class VersificationCrosswalk(BaseModel):
    """A validated crosswalk document between two named reference schemes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1]
    source_scheme: str = Field(min_length=1)
    target_scheme: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    rows: list[CrosswalkRow] = Field(default_factory=list)

    @model_validator(mode="after")
    def document_is_consistent(self) -> Self:
        if self.source_scheme == self.target_scheme:
            raise ValueError("source_scheme and target_scheme must differ")
        row_ids = [row.crosswalk_id for row in self.rows]
        duplicates = sorted(row_id for row_id, count in Counter(row_ids).items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate crosswalk_id values: {duplicates[:5]}")
        return self


def load_versification_crosswalk(path: Path) -> VersificationCrosswalk:
    """Load and validate one crosswalk YAML document."""
    if not path.is_file():
        raise CrosswalkValidationError(f"crosswalk document does not exist: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise CrosswalkValidationError(f"could not parse crosswalk {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CrosswalkValidationError(f"crosswalk root must be a mapping: {path}")
    try:
        return VersificationCrosswalk.model_validate(cast(dict[str, object], raw))
    except ValidationError as exc:
        raise CrosswalkValidationError(f"validation failed for crosswalk {path}:\n{exc}") from exc
