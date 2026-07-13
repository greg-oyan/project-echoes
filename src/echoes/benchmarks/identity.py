"""Stable, collision-checked identities for benchmark source and mapping layers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkIdentityError(ValueError):
    """Raised when a benchmark identity cannot be derived safely."""


class BenchmarkIdentityCollisionError(BenchmarkIdentityError):
    """Raised if one identifier is observed with distinct canonical payloads."""


class _IdentityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class SourceRecordIdentityPayload(_IdentityPayload):
    """Identity inputs for one exact occurrence of a raw record."""

    source_id: str = Field(min_length=1)
    source_archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duplicate_occurrence_ordinal: int = Field(ge=1)


class RelationshipIdentityPayload(_IdentityPayload):
    """Source-level relationship identity, deliberately independent of mappings."""

    relationship_id_schema_version: Literal[1] = 1
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_reference_scheme: str = Field(min_length=1)
    normalized_source_endpoint_a: str = Field(min_length=1)
    normalized_source_endpoint_b: str = Field(min_length=1)
    source_direction: str = Field(min_length=1)


class PairIdentityPayload(_IdentityPayload):
    """Cross-source canonical reference-pair identity."""

    relationship_id_schema_version: Literal[1] = 1
    source_reference_scheme: str = Field(min_length=1)
    normalized_endpoint_a: str = Field(min_length=1)
    normalized_endpoint_b: str = Field(min_length=1)
    pair_direction: Literal["directed", "unordered"]


class EndpointIdentityPayload(_IdentityPayload):
    """Identity for one relationship side."""

    relationship_id: str = Field(min_length=1)
    endpoint_side: Literal["a", "b"]
    normalized_source_reference: str = Field(min_length=1)


class MappingIdentityPayload(_IdentityPayload):
    """Mapping identity that may change without rewriting relationship identity."""

    mapping_schema_version: Literal[1] = 1
    endpoint_id: str = Field(min_length=1)
    target_corpus: Literal["hebrew", "greek"]
    target_analysis_profile: Literal["edition_complete", "critical_core"]
    target_analysis_reading: Literal["qere", "source"]
    target_granularity: Literal["verse"]
    mapping_method: str = Field(min_length=1)
    crosswalk_version: str | None
    target_passage_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkIdentity:
    """Rendered identifier and its reproducible payload evidence."""

    identifier: str
    payload_sha256: str
    canonical_payload_json: str


def canonical_payload_json(payload: BaseModel) -> str:
    """Serialize a typed payload with one portable canonical representation."""

    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _identity(prefix: str, payload: BaseModel) -> BenchmarkIdentity:
    canonical = canonical_payload_json(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return BenchmarkIdentity(
        identifier=f"{prefix}_{digest}",
        payload_sha256=digest,
        canonical_payload_json=canonical,
    )


def raw_record_sha256(raw_record_bytes: bytes) -> str:
    """Hash the exact record bytes supplied by the governed parser."""

    return hashlib.sha256(raw_record_bytes).hexdigest()


def build_source_record_identity(
    *,
    source_id: str,
    source_archive_sha256: str,
    raw_record_bytes: bytes,
    duplicate_occurrence_ordinal: int,
) -> BenchmarkIdentity:
    """Build an ID independent of mutable line-number provenance."""

    payload = SourceRecordIdentityPayload(
        source_id=source_id,
        source_archive_sha256=source_archive_sha256,
        raw_record_sha256=raw_record_sha256(raw_record_bytes),
        duplicate_occurrence_ordinal=duplicate_occurrence_ordinal,
    )
    return _identity("BSR", payload)


def build_relationship_identity(payload: RelationshipIdentityPayload) -> BenchmarkIdentity:
    """Build a relationship ID without weights, mappings, paths, or row numbers."""

    return _identity("BR", payload)


def build_pair_identities(
    *,
    source_reference_scheme: str,
    normalized_endpoint_a: str,
    normalized_endpoint_b: str,
) -> tuple[BenchmarkIdentity, BenchmarkIdentity]:
    """Return directed and canonical unordered pair identities."""

    directed = _identity(
        "BDP",
        PairIdentityPayload(
            source_reference_scheme=source_reference_scheme,
            normalized_endpoint_a=normalized_endpoint_a,
            normalized_endpoint_b=normalized_endpoint_b,
            pair_direction="directed",
        ),
    )
    first, second = sorted((normalized_endpoint_a, normalized_endpoint_b))
    unordered = _identity(
        "BUP",
        PairIdentityPayload(
            source_reference_scheme=source_reference_scheme,
            normalized_endpoint_a=first,
            normalized_endpoint_b=second,
            pair_direction="unordered",
        ),
    )
    return directed, unordered


def build_endpoint_identity(payload: EndpointIdentityPayload) -> BenchmarkIdentity:
    """Build one stable relationship-side identity."""

    return _identity("BE", payload)


def build_mapping_identity(payload: MappingIdentityPayload) -> BenchmarkIdentity:
    """Build one mapping identity from ordered target passage membership."""

    return _identity("BM", payload)


class BenchmarkIdentityRegistry:
    """Fail clearly if a rendered ID is paired with distinct payloads."""

    def __init__(self) -> None:
        self._payloads: dict[str, str] = {}

    def add(self, identity: BenchmarkIdentity) -> None:
        previous = self._payloads.get(identity.identifier)
        if previous is not None and previous != identity.canonical_payload_json:
            raise BenchmarkIdentityCollisionError(
                f"distinct benchmark payloads share identifier {identity.identifier}"
            )
        self._payloads[identity.identifier] = identity.canonical_payload_json
