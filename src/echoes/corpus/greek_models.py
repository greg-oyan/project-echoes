"""Strongly typed canonical Greek token model.

The Greek corpus shares canonical-identity, provenance, position, and
annotation semantics with the Hebrew corpus while carrying Greek-specific
derived forms: ``normalized_form`` is the punctuation-separated word core,
``folded_form`` is the case-folded accent-insensitive comparison form, and
the source edition's own accent-regularized ``source_normalized_form`` is
preserved as supplied.
"""

from __future__ import annotations

import json
from typing import Literal, Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GREEK_TOKEN_SCHEMA_VERSION = 1


class CanonicalGreekToken(BaseModel):
    """Versioned, provenance-preserving canonical Greek token record."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    schema_version: Literal[1] = 1
    token_id: str = Field(
        pattern=r"^GNT_[A-Z0-9]{3}_\d{3}_\d{3}_\d{4}(?:\.\d{2})?(?:~[a-f0-9]{12})?$"
    )
    corpus: Literal["greek"] = "greek"
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_word_id: str = Field(min_length=1)
    source_edition_reference: str = Field(pattern=r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$")
    source_row_reference: str = Field(min_length=1)
    book: str = Field(pattern=r"^[A-Z0-9]{3}$")
    book_order: int = Field(ge=1, le=27)
    chapter: int = Field(ge=1)
    verse: int = Field(ge=1)
    subverse: str | None = None
    sentence_id: str | None = None
    clause_id: str | None = None
    phrase_id: str | None = None
    position_in_verse: int = Field(ge=1)
    position_in_clause: int | None = Field(default=None, ge=1)
    position_in_corpus: int = Field(ge=1)
    surface_form: str = Field(min_length=1)
    normalized_form: str = Field(min_length=1)
    folded_form: str = Field(min_length=1)
    source_normalized_form: str | None = None
    leading_punctuation: str
    trailing_punctuation: str
    is_elided: bool = False
    lemma: str | None = None
    strong_number: str | None = None
    part_of_speech: str | None = None
    morphology_json: str | None = None
    syntactic_function: str | None = None
    semantic_domain: str | None = None
    word_sense: str | None = None
    participant_id: str | None = None
    frame_json: str | None = None
    english_gloss: str | None = None
    language: Literal["greek"] = "greek"
    is_punctuation: bool = False
    is_variant: bool = False
    variant_type: str | None = None
    variant_group_id: str | None = None
    is_default_reading: bool = True
    source_extras_json: str

    @field_validator("morphology_json", "source_extras_json", "frame_json")
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
    def punctuation_separation_is_lossless(self) -> Self:
        reconstructed = self.leading_punctuation + self.normalized_form + self.trailing_punctuation
        if not self.is_punctuation and reconstructed != self.surface_form:
            raise ValueError("punctuation separation must reconstruct the surface form")
        if not self.is_variant and any((self.variant_type, self.variant_group_id)):
            raise ValueError("ordinary tokens cannot contain variant detail")
        return self


GREEK_TOKEN_POLARS_SCHEMA = {
    "schema_version": pl.Int16,
    "token_id": pl.String,
    "corpus": pl.String,
    "source_id": pl.String,
    "source_version": pl.String,
    "source_file": pl.String,
    "source_record_id": pl.String,
    "source_word_id": pl.String,
    "source_edition_reference": pl.String,
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
    "surface_form": pl.String,
    "normalized_form": pl.String,
    "folded_form": pl.String,
    "source_normalized_form": pl.String,
    "leading_punctuation": pl.String,
    "trailing_punctuation": pl.String,
    "is_elided": pl.Boolean,
    "lemma": pl.String,
    "strong_number": pl.String,
    "part_of_speech": pl.String,
    "morphology_json": pl.String,
    "syntactic_function": pl.String,
    "semantic_domain": pl.String,
    "word_sense": pl.String,
    "participant_id": pl.String,
    "frame_json": pl.String,
    "english_gloss": pl.String,
    "language": pl.String,
    "is_punctuation": pl.Boolean,
    "is_variant": pl.Boolean,
    "variant_type": pl.String,
    "variant_group_id": pl.String,
    "is_default_reading": pl.Boolean,
    "source_extras_json": pl.String,
}

GREEK_TOKEN_COLUMNS: tuple[str, ...] = tuple(GREEK_TOKEN_POLARS_SCHEMA)
