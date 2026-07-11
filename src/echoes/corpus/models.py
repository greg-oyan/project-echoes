"""Strongly typed canonical token and issue models."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CANONICAL_TOKEN_SCHEMA_VERSION = 1


class Language(StrEnum):
    """Languages represented in the MACULA Hebrew source."""

    HEBREW = "hebrew"
    ARAMAIC = "aramaic"


class ValidationSeverity(StrEnum):
    """Severity levels emitted by ingestion and corpus validation."""

    ERROR = "error"
    WARNING = "warning"
    INFORMATIONAL = "informational"


class CanonicalToken(BaseModel):
    """Versioned, provenance-preserving canonical Hebrew token record."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    schema_version: Literal[1] = 1
    token_id: str = Field(pattern=r"^HB_[A-Z0-9]{3}_\d{3}_\d{3}_\d{4}(?:\.\d{2})?$")
    corpus: Literal["hebrew"] = "hebrew"
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_word_id: str = Field(min_length=1)
    source_row_reference: str = Field(min_length=1)
    book: str = Field(pattern=r"^[A-Z0-9]{3}$")
    book_order: int = Field(ge=1, le=39)
    chapter: int = Field(ge=1)
    verse: int = Field(ge=1)
    subverse: str | None = None
    sentence_id: str | None = None
    clause_id: str | None = None
    phrase_id: str | None = None
    position_in_verse: int = Field(ge=1)
    position_in_clause: int | None = Field(default=None, ge=1)
    position_in_corpus: int = Field(ge=1)
    position_in_word: int = Field(ge=1)
    surface_form: str
    normalized_form: str
    unpointed_form: str
    is_zero_width: bool = False
    lemma: str | None = None
    lexical_root: str | None = None
    part_of_speech: str | None = None
    morphology_json: str | None = None
    syntactic_function: str | None = None
    syntactic_head_source_id: str | None = None
    semantic_domain: str | None = None
    word_sense: str | None = None
    participant_id: str | None = None
    speaker_id: str | None = None
    entity_id: str | None = None
    english_gloss: str | None = None
    language: Language
    is_punctuation: bool = False
    is_variant: bool = False
    variant_type: str | None = None
    ketiv_form: str | None = None
    qere_form: str | None = None
    source_extras_json: str

    @field_validator("morphology_json", "source_extras_json")
    @classmethod
    def json_fields_are_objects(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("must contain valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("must encode a JSON object")
        return value

    @model_validator(mode="after")
    def variants_are_explicit(self) -> Self:
        forms = (self.surface_form, self.normalized_form, self.unpointed_form)
        if self.is_zero_width and any(forms):
            raise ValueError("zero-width morphemes must preserve empty source and derived forms")
        if not self.is_zero_width and not all(forms):
            raise ValueError("non-zero-width tokens require source and derived forms")
        has_variant_detail = any((self.variant_type, self.ketiv_form, self.qere_form))
        if has_variant_detail and not self.is_variant:
            raise ValueError("variant detail requires is_variant=true")
        return self


class IngestionIssue(BaseModel):
    """One actionable finding emitted while parsing or validating a corpus."""

    model_config = ConfigDict(extra="forbid")

    severity: ValidationSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_record_id: str | None = None
    token_id: str | None = None
    book: str | None = None
    chapter: int | None = None
    verse: int | None = None


CANONICAL_TOKEN_POLARS_SCHEMA = {
    "schema_version": pl.Int16,
    "token_id": pl.String,
    "corpus": pl.String,
    "source_id": pl.String,
    "source_version": pl.String,
    "source_file": pl.String,
    "source_record_id": pl.String,
    "source_word_id": pl.String,
    "source_row_reference": pl.String,
    "book": pl.String,
    "book_order": pl.Int16,
    "chapter": pl.Int16,
    "verse": pl.Int16,
    "subverse": pl.String,
    "sentence_id": pl.String,
    "clause_id": pl.String,
    "phrase_id": pl.String,
    "position_in_verse": pl.Int32,
    "position_in_clause": pl.Int32,
    "position_in_corpus": pl.Int64,
    "position_in_word": pl.Int16,
    "surface_form": pl.String,
    "normalized_form": pl.String,
    "unpointed_form": pl.String,
    "is_zero_width": pl.Boolean,
    "lemma": pl.String,
    "lexical_root": pl.String,
    "part_of_speech": pl.String,
    "morphology_json": pl.String,
    "syntactic_function": pl.String,
    "syntactic_head_source_id": pl.String,
    "semantic_domain": pl.String,
    "word_sense": pl.String,
    "participant_id": pl.String,
    "speaker_id": pl.String,
    "entity_id": pl.String,
    "english_gloss": pl.String,
    "language": pl.String,
    "is_punctuation": pl.Boolean,
    "is_variant": pl.Boolean,
    "variant_type": pl.String,
    "ketiv_form": pl.String,
    "qere_form": pl.String,
    "source_extras_json": pl.String,
}

CANONICAL_TOKEN_COLUMNS: tuple[str, ...] = tuple(CANONICAL_TOKEN_POLARS_SCHEMA)
