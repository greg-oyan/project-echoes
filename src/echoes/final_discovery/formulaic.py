"""Preregistered corpus-global formulaic-language control."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.final_discovery.config import FormulaicControlPolicy
from echoes.final_discovery.features import adjacent_ngrams
from echoes.final_discovery.models import PassageRecord


class FormulaicControlError(ValueError):
    """Raised when the global control population is incomplete or ambiguous."""


class FormulaicFeatureRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_id: str = Field(min_length=1)
    document_frequency: int = Field(ge=1)


class PassageFormulaicControlRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_id: str = Field(min_length=1)
    candidate_feature_count: int = Field(ge=0)
    high_df_feature_ids: tuple[str, ...]
    high_df_feature_fraction: float = Field(ge=0.0, le=1.0)
    formulaic_language: bool

    @model_validator(mode="after")
    def features_are_sorted_unique(self) -> Self:
        if self.high_df_feature_ids != tuple(sorted(set(self.high_df_feature_ids))):
            raise ValueError("formulaic feature IDs must be sorted and unique")
        expected = (
            len(self.high_df_feature_ids) / self.candidate_feature_count
            if self.candidate_feature_count
            else 0.0
        )
        if not math.isclose(
            self.high_df_feature_fraction,
            expected,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("formulaic feature fraction disagrees with its counts")
        return self


class FormulaicControlReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    method: Literal["primary_corpus_high_df_lemma_root_ngrams"]
    primary_passage_count: int = Field(ge=1)
    evaluated_passage_count: int = Field(ge=1)
    document_frequency_threshold: int = Field(ge=2)
    high_df_feature_count: int = Field(ge=0)
    formulaic_passage_count: int = Field(ge=0)
    high_df_vocabulary_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy: FormulaicControlPolicy
    sensitivity_uses_primary_vocabulary: Literal[True] = True
    source_text_persisted_in_receipt: Literal[False] = False


def _passage_features(
    passage: PassageRecord,
    ngram_sizes: Sequence[int],
) -> tuple[str, ...]:
    values: set[str] = set()
    for family, sequence in (
        ("lemma", passage.lemma_sequence),
        ("root", passage.root_sequence),
    ):
        cleaned = tuple(value for value in sequence if value)
        for size in ngram_sizes:
            values.update(f"{family}:{size}:{value}" for value in adjacent_ngrams(cleaned, size))
    return tuple(sorted(values))


def _vocabulary_sha256(features: Sequence[FormulaicFeatureRow]) -> str:
    payload = [row.model_dump(mode="json") for row in features]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def apply_formulaic_control(
    passages: Sequence[PassageRecord],
    *,
    primary_passage_ids: set[str],
    policy: FormulaicControlPolicy,
) -> tuple[
    tuple[PassageRecord, ...],
    tuple[FormulaicFeatureRow, ...],
    tuple[PassageFormulaicControlRow, ...],
    FormulaicControlReport,
]:
    """Derive flags from high-DF primary-corpus original-language n-grams."""

    if not passages or not primary_passage_ids:
        raise FormulaicControlError("formulaic control requires a nonempty primary population")
    by_id = {passage.passage_id: passage for passage in passages}
    if len(by_id) != len(passages) or not primary_passage_ids.issubset(by_id):
        raise FormulaicControlError("formulaic passage population has duplicate or missing IDs")
    features_by_passage = {
        passage.passage_id: _passage_features(passage, policy.ngram_sizes) for passage in passages
    }
    frequencies: Counter[str] = Counter()
    for passage_id in sorted(primary_passage_ids):
        frequencies.update(features_by_passage[passage_id])
    threshold = max(
        policy.minimum_document_count,
        math.ceil(len(primary_passage_ids) * policy.minimum_document_frequency_fraction),
    )
    high_df = {feature: count for feature, count in frequencies.items() if count >= threshold}
    feature_rows = tuple(
        FormulaicFeatureRow(feature_id=feature, document_frequency=high_df[feature])
        for feature in sorted(high_df)
    )
    control_rows: list[PassageFormulaicControlRow] = []
    enriched: list[PassageRecord] = []
    for passage in passages:
        candidate_features = features_by_passage[passage.passage_id]
        matched = tuple(feature for feature in candidate_features if feature in high_df)
        fraction = len(matched) / len(candidate_features) if candidate_features else 0.0
        formulaic = (
            len(matched) >= policy.minimum_distinct_high_df_features
            and fraction >= policy.minimum_high_df_feature_fraction
        )
        control_rows.append(
            PassageFormulaicControlRow(
                passage_id=passage.passage_id,
                candidate_feature_count=len(candidate_features),
                high_df_feature_ids=matched,
                high_df_feature_fraction=fraction,
                formulaic_language=formulaic,
            )
        )
        enriched.append(passage.model_copy(update={"formulaic_language": formulaic}))
    rows = tuple(control_rows)
    return (
        tuple(enriched),
        feature_rows,
        rows,
        FormulaicControlReport(
            method=policy.method,
            primary_passage_count=len(primary_passage_ids),
            evaluated_passage_count=len(passages),
            document_frequency_threshold=threshold,
            high_df_feature_count=len(feature_rows),
            formulaic_passage_count=sum(row.formulaic_language for row in rows),
            high_df_vocabulary_sha256=_vocabulary_sha256(feature_rows),
            policy=policy,
        ),
    )


__all__ = [
    "FormulaicControlError",
    "FormulaicControlReport",
    "FormulaicFeatureRow",
    "PassageFormulaicControlRow",
    "apply_formulaic_control",
]
