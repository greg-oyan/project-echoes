"""Deterministic passage identity derived from exact ordered membership."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.segment.models import (
    AnalysisProfile,
    AnalysisReading,
    Corpus,
    Granularity,
)

_REFERENCE_PATTERN = r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$"


class PassageIdentityError(ValueError):
    """Base class for invalid or unsafe passage identities."""


class DuplicatePassagePayloadError(PassageIdentityError):
    """Raised when generation attempts to emit one canonical payload twice."""


class PassageIdentityCollisionError(PassageIdentityError):
    """Raised when distinct canonical payloads resolve to the same digest or ID."""


class PassageIdentityPayload(BaseModel):
    """Canonical, run-independent facts that determine one passage identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_id_schema_version: Literal[1] = 1
    corpus: Corpus
    analysis_profile: AnalysisProfile
    analysis_reading: AnalysisReading
    granularity: Granularity
    book: str = Field(pattern=r"^[A-Z0-9]{3}$")
    source_unit_id: str | None = None
    reference_sequence: tuple[str, ...] = Field(min_length=1)
    token_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def identity_facts_are_consistent(self) -> Self:
        if self.corpus == "hebrew" and self.analysis_reading not in {"qere", "ketiv"}:
            raise ValueError("Hebrew identity requires qere or ketiv analysis_reading")
        if self.corpus == "greek" and self.analysis_reading != "source":
            raise ValueError("Greek identity requires source analysis_reading")
        if len(self.token_ids) != len(set(self.token_ids)):
            raise ValueError("passage identity cannot contain duplicate token IDs")
        for reference in self.reference_sequence:
            if not _valid_reference(reference):
                raise ValueError(f"malformed canonical reference: {reference}")
            if reference.split(" ", maxsplit=1)[0] != self.book:
                raise ValueError("every identity reference must use the canonical passage book")
        if self.granularity in {"clause", "sentence"} and not self.source_unit_id:
            raise ValueError("clause and sentence identities require source_unit_id")
        return self


@dataclass(frozen=True, slots=True)
class IdentityMember:
    """Minimal membership facts used to establish canonical order."""

    token_id: str
    position_in_passage: int
    source_reference: str


@dataclass(frozen=True, slots=True)
class PassageIdentity:
    """Readable stable ID plus its full canonical SHA-256 evidence."""

    passage_id: str
    payload_sha256: str
    canonical_payload_json: str


def _valid_reference(reference: str) -> bool:
    parts = reference.split(" ", maxsplit=1)
    if len(parts) != 2 or len(parts[0]) != 3 or not parts[0].isalnum():
        return False
    location = parts[1].split(":", maxsplit=1)
    if len(location) != 2 or not all(value.isdigit() for value in location):
        return False
    return all(int(value) >= 1 and not value.startswith("0") for value in location)


def canonical_payload_json(payload: PassageIdentityPayload) -> str:
    """Serialize identity facts without paths, timestamps, or run metadata."""

    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_sha256(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _reference_slug(reference: str) -> str:
    book, location = reference.split(" ", maxsplit=1)
    chapter, verse = (int(value) for value in location.split(":", maxsplit=1))
    return f"{book}_{chapter:03d}_{verse:03d}"


def _readable_prefix(payload: PassageIdentityPayload) -> str:
    corpus = "HB" if payload.corpus == "hebrew" else "GNT"
    start = _reference_slug(payload.reference_sequence[0])
    end = _reference_slug(payload.reference_sequence[-1])
    extent = start if start == end else f"{start}_{end}"
    return "_".join(
        (
            "P",
            corpus,
            payload.analysis_profile.upper(),
            payload.analysis_reading.upper(),
            payload.granularity.upper(),
            extent,
        )
    )


def build_passage_identity(payload: PassageIdentityPayload) -> PassageIdentity:
    """Build a stable readable ID carrying the full payload SHA-256."""

    canonical_json = canonical_payload_json(payload)
    digest = _payload_sha256(canonical_json)
    return PassageIdentity(
        passage_id=f"{_readable_prefix(payload)}~{digest}",
        payload_sha256=digest,
        canonical_payload_json=canonical_json,
    )


def payload_from_membership(
    *,
    corpus: Corpus,
    analysis_profile: AnalysisProfile,
    analysis_reading: AnalysisReading,
    granularity: Granularity,
    book: str,
    source_unit_id: str | None,
    members: Iterable[IdentityMember],
) -> PassageIdentityPayload:
    """Canonicalize arbitrarily ordered input rows by explicit passage position."""

    ordered = sorted(members, key=lambda member: member.position_in_passage)
    expected_positions = list(range(1, len(ordered) + 1))
    positions = [member.position_in_passage for member in ordered]
    if not ordered:
        raise PassageIdentityError("passage identity requires at least one membership row")
    if positions != expected_positions:
        raise PassageIdentityError("membership positions must start at one and be continuous")
    if any(not member.token_id for member in ordered):
        raise PassageIdentityError("membership token IDs must be nonempty")
    references: list[str] = []
    for member in ordered:
        if not references or references[-1] != member.source_reference:
            references.append(member.source_reference)
    return PassageIdentityPayload(
        corpus=corpus,
        analysis_profile=analysis_profile,
        analysis_reading=analysis_reading,
        granularity=granularity,
        book=book,
        source_unit_id=source_unit_id,
        reference_sequence=tuple(references),
        token_ids=tuple(member.token_id for member in ordered),
    )


class PassageIdRegistry:
    """Fail-closed registry for duplicate payloads and digest collisions."""

    def __init__(self) -> None:
        self._payload_by_digest: dict[str, str] = {}
        self._digest_by_id: dict[str, str] = {}

    def register(self, identity: PassageIdentity) -> None:
        """Register one identity, rejecting both duplicates and collisions."""

        existing_payload = self._payload_by_digest.get(identity.payload_sha256)
        if existing_payload is not None:
            if existing_payload == identity.canonical_payload_json:
                raise DuplicatePassagePayloadError(
                    f"canonical passage payload emitted twice: {identity.passage_id}"
                )
            raise PassageIdentityCollisionError(
                f"distinct passage payloads share SHA-256 {identity.payload_sha256}"
            )
        existing_digest = self._digest_by_id.get(identity.passage_id)
        if existing_digest is not None:
            raise PassageIdentityCollisionError(
                f"distinct passage identities share ID {identity.passage_id}"
            )
        self._payload_by_digest[identity.payload_sha256] = identity.canonical_payload_json
        self._digest_by_id[identity.passage_id] = identity.payload_sha256

    def build_and_register(self, payload: PassageIdentityPayload) -> PassageIdentity:
        """Build and register one payload as the normal generation operation."""

        identity = build_passage_identity(payload)
        self.register(identity)
        return identity

    def __len__(self) -> int:
        return len(self._digest_by_id)
