"""Bidirectional known-relationship indexing for final discovery."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.final_discovery.models import KnownnessStatus


class KnownRelationship(BaseModel):
    """One mapped known relationship with retained directional provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relationship_id: str = Field(min_length=1)
    source_passage_id: str = Field(min_length=1)
    target_passage_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    mapping_quality: str = Field(min_length=1)
    source_relationship_id: str | None = None
    source_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_provenance_json: str = "{}"

    @model_validator(mode="after")
    def relationship_is_not_self(self) -> KnownRelationship:
        if self.source_passage_id == self.target_passage_id:
            raise ValueError("known relationships cannot be self-links")
        try:
            provenance = json.loads(self.source_provenance_json)
        except json.JSONDecodeError as exc:
            raise ValueError("known relationship provenance must be valid JSON") from exc
        if not isinstance(provenance, dict) or not all(isinstance(key, str) for key in provenance):
            raise ValueError("known relationship provenance must be a string-keyed object")
        if (self.source_relationship_id is None) != (self.source_manifest_sha256 is None):
            raise ValueError(
                "source relationship identity and source manifest must be supplied together"
            )
        return self


class KnownnessIndex:
    """Immutable-in-use lookup that checks both directions explicitly."""

    def __init__(self, relationships: Iterable[KnownRelationship]) -> None:
        directed: dict[tuple[str, str], set[str]] = defaultdict(set)
        ids: dict[str, tuple[str, str]] = {}
        for relationship in relationships:
            pair = (relationship.source_passage_id, relationship.target_passage_id)
            prior = ids.get(relationship.relationship_id)
            if prior is not None and prior != pair:
                raise ValueError(
                    f"known relationship ID maps to multiple pairs: {relationship.relationship_id}"
                )
            ids[relationship.relationship_id] = pair
            directed[pair].add(relationship.relationship_id)
        self._directed = {pair: tuple(sorted(values)) for pair, values in directed.items()}

    def classify(
        self, passage_a_id: str, passage_b_id: str
    ) -> tuple[KnownnessStatus, tuple[str, ...]]:
        if passage_a_id >= passage_b_id:
            raise ValueError("knownness lookup requires canonical distinct passage ordering")
        forward = self._directed.get((passage_a_id, passage_b_id), ())
        reverse = self._directed.get((passage_b_id, passage_a_id), ())
        relationship_ids = tuple(sorted(set(forward) | set(reverse)))
        if forward and reverse:
            return "known_both", relationship_ids
        if forward:
            return "known_forward", relationship_ids
        if reverse:
            return "known_reverse", relationship_ids
        return "unknown", ()
