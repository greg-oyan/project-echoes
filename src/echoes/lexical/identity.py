"""Stable collision-checked lexical feature, representation, pair, and ranking IDs."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from echoes.lexical.config import (
    FeatureFamily,
    Granularity,
    LexicalExperimentPreregistration,
    lexical_preregistration_sha256,
)

LanguageNamespace = Literal["hb", "gk", "en"]


class LexicalIdentityError(ValueError):
    """Raised when a lexical identity cannot be derived safely."""


class LexicalIdentityCollisionError(LexicalIdentityError):
    """Raised when one rendered identifier is observed with distinct payloads."""


class _IdentityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class FeatureIdentityPayload(_IdentityPayload):
    """Canonical identity facts for one language-prefixed lexical feature."""

    feature_schema_version: Literal[1] = 1
    feature_family: FeatureFamily
    language_namespace: LanguageNamespace
    feature_value: str = Field(min_length=1)
    feature_order: int = Field(ge=1, le=3)

    @field_validator("feature_value", mode="before")
    @classmethod
    def normalize_feature_value(cls, value: Any) -> Any:
        if isinstance(value, str):
            return unicodedata.normalize("NFC", value.strip())
        return value

    @model_validator(mode="after")
    def namespace_and_order_match_family(self) -> Self:
        if self.feature_family == "english_gloss" and self.language_namespace != "en":
            raise ValueError("English gloss features require the en namespace")
        if self.language_namespace == "en" and self.feature_family != "english_gloss":
            raise ValueError("the en namespace is reserved for English-derived gloss features")
        if self.feature_family in {"lemma_ngram", "root_ngram"}:
            if self.feature_order not in {2, 3}:
                raise ValueError("n-gram feature order must be two or three")
        elif self.feature_family in {"lemma_skipgram", "root_skipgram"}:
            if self.feature_order != 2:
                raise ValueError("Milestone 7 skip-grams must have feature order two")
        elif self.feature_order != 1:
            raise ValueError("unigram feature families require feature order one")
        return self


class RepresentationIdentityPayload(_IdentityPayload):
    """Canonical configuration-dependent identity for one sparse representation."""

    representation_schema_version: Literal[1] = 1
    representation_kind: Literal["original_language", "english_derived"]
    corpus_scope: tuple[Literal["hebrew", "greek"], ...] = Field(min_length=1)
    analysis_profile: Literal["edition_complete", "critical_core"]
    analysis_reading: str = Field(min_length=1)
    granularity: Granularity
    feature_families: tuple[FeatureFamily, ...] = Field(min_length=1)
    token_eligibility_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    frequency_scope: str = Field(min_length=1)
    normalization_config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("corpus_scope", "feature_families", mode="before")
    @classmethod
    def canonicalize_set_like_values(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            if len(value) != len(set(value)):
                raise ValueError("representation identity collections must be unique")
            return tuple(sorted(value))
        return value

    @model_validator(mode="after")
    def english_and_original_language_features_are_separate(self) -> Self:
        has_english = "english_gloss" in self.feature_families
        if self.representation_kind == "english_derived" and not has_english:
            raise ValueError("English-derived representation requires English gloss features")
        if self.representation_kind == "original_language" and has_english:
            raise ValueError("original-language representation cannot contain English features")
        return self


class CandidatePairIdentityPayload(_IdentityPayload):
    """Unordered pair identity deliberately independent of all scores and labels."""

    candidate_pair_schema_version: Literal[1] = 1
    analysis_profile: Literal["edition_complete", "critical_core"]
    granularity: Granularity
    passage_id_a: str = Field(min_length=1)
    passage_id_b: str = Field(min_length=1)

    @model_validator(mode="after")
    def passages_are_distinct_and_canonical(self) -> Self:
        if self.passage_id_a == self.passage_id_b:
            raise ValueError("candidate pair identity requires two distinct passages")
        first, second = sorted((self.passage_id_a, self.passage_id_b))
        object.__setattr__(self, "passage_id_a", first)
        object.__setattr__(self, "passage_id_b", second)
        return self


class RankingIdentityPayload(_IdentityPayload):
    """Directional detector-ranking identity for one query-target result."""

    ranking_schema_version: Literal[1] = 1
    experiment_run_id: str = Field(min_length=1)
    query_passage_id: str = Field(min_length=1)
    target_passage_id: str = Field(min_length=1)
    detector: str = Field(min_length=1)
    representation_id: str = Field(min_length=1)
    direction: Literal["forward", "reverse"]

    @model_validator(mode="after")
    def ranking_is_not_a_self_result(self) -> Self:
        if self.query_passage_id == self.target_passage_id:
            raise ValueError("ranking identity requires distinct query and target passages")
        return self


@dataclass(frozen=True, slots=True)
class LexicalIdentity:
    """Rendered stable identifier and complete canonical payload evidence."""

    identifier: str
    payload_sha256: str
    canonical_payload_json: str


def canonical_payload_json(payload: BaseModel) -> str:
    """Serialize one typed identity payload with portable canonical JSON."""

    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _identity(prefix: str, payload: BaseModel) -> LexicalIdentity:
    canonical = canonical_payload_json(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return LexicalIdentity(
        identifier=f"{prefix}_{digest}",
        payload_sha256=digest,
        canonical_payload_json=canonical,
    )


def build_feature_identity(payload: FeatureIdentityPayload) -> LexicalIdentity:
    """Build a feature ID independent of sparse matrix column position."""

    return _identity("LF", payload)


def build_representation_identity(payload: RepresentationIdentityPayload) -> LexicalIdentity:
    """Build a representation ID from governed analytical choices only."""

    return _identity("LR", payload)


def build_candidate_pair_identity(payload: CandidatePairIdentityPayload) -> LexicalIdentity:
    """Build an unordered candidate ID without scores, thresholds, or labels."""

    return _identity("LCP", payload)


def build_ranking_identity(payload: RankingIdentityPayload) -> LexicalIdentity:
    """Build a directional detector ranking ID."""

    return _identity("LRK", payload)


def preregistration_digest(
    preregistration: LexicalExperimentPreregistration,
) -> str:
    """Return the authenticated digest required by held-out evaluation."""

    return lexical_preregistration_sha256(preregistration)


class LexicalIdentityRegistry:
    """Fail closed if one lexical ID is ever paired with distinct payloads."""

    def __init__(self) -> None:
        self._payloads: dict[str, str] = {}

    def add(self, identity: LexicalIdentity) -> None:
        """Register an identity or raise on a digest/payload collision."""

        previous = self._payloads.get(identity.identifier)
        if previous is not None and previous != identity.canonical_payload_json:
            raise LexicalIdentityCollisionError(
                f"distinct lexical payloads share identifier {identity.identifier}"
            )
        self._payloads[identity.identifier] = identity.canonical_payload_json

    def __len__(self) -> int:
        return len(self._payloads)
