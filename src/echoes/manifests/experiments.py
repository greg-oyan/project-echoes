"""Governance schema for planned and executed experiments."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ExperimentStatus(StrEnum):
    """Lifecycle state for an experiment configuration."""

    PLANNED = "planned"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    DEPRECATED = "deprecated"


class ExperimentManifest(BaseModel):
    """Research-governance declaration for one reproducible experiment."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1]
    experiment_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    research_question: str = Field(min_length=1)
    input_sources: list[str] = Field(min_length=1)
    input_tables: list[str]
    methods: list[str] = Field(min_length=1)
    parameters: dict[str, JsonValue]
    evaluation_dataset: str | None
    random_seed: int = Field(ge=0)
    expected_outputs: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    prohibited_claims: list[str] = Field(min_length=1)
    status: ExperimentStatus

    @model_validator(mode="after")
    def list_members_are_unique(self) -> Self:
        """Reject duplicate identifiers that would obscure experiment lineage."""
        for field_name in ("input_sources", "input_tables", "methods", "expected_outputs"):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                msg = f"{field_name} values must be unique"
                raise ValueError(msg)
        return self
