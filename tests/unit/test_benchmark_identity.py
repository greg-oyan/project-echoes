"""Stable benchmark source, relationship, pair, and mapping identities."""

from __future__ import annotations

import pytest

from echoes.benchmarks.identity import (
    BenchmarkIdentity,
    BenchmarkIdentityCollisionError,
    BenchmarkIdentityRegistry,
    EndpointIdentityPayload,
    MappingIdentityPayload,
    RelationshipIdentityPayload,
    build_endpoint_identity,
    build_mapping_identity,
    build_pair_identities,
    build_relationship_identity,
    build_source_record_identity,
)

ARCHIVE_SHA = "a" * 64


def _relationship(
    endpoint_a: str = "Gen.1.1",
    endpoint_b: str = "John.1.1",
    direction: str = "from_to",
) -> BenchmarkIdentity:
    return build_relationship_identity(
        RelationshipIdentityPayload(
            source_id="openbible-cross-references",
            source_version="snapshot-v1",
            source_reference_scheme="openbible-v1",
            normalized_source_endpoint_a=endpoint_a,
            normalized_source_endpoint_b=endpoint_b,
            source_direction=direction,
        )
    )


def test_input_processing_order_does_not_change_relationship_ids() -> None:
    payloads = [("Gen.1.1", "John.1.1"), ("Isa.1.1", "Rom.1.1")]
    forward = {_relationship(a, b).identifier for a, b in payloads}
    reverse = {_relationship(a, b).identifier for a, b in reversed(payloads)}

    assert forward == reverse


def test_source_line_number_and_votes_are_not_identity_inputs() -> None:
    first_line = build_source_record_identity(
        source_id="openbible-cross-references",
        source_archive_sha256=ARCHIVE_SHA,
        raw_record_bytes=b"Gen.1.1\tJohn.1.1\t2",
        duplicate_occurrence_ordinal=1,
    )
    moved_line = build_source_record_identity(
        source_id="openbible-cross-references",
        source_archive_sha256=ARCHIVE_SHA,
        raw_record_bytes=b"Gen.1.1\tJohn.1.1\t2",
        duplicate_occurrence_ordinal=1,
    )
    before_vote_change = _relationship()
    after_vote_change = _relationship()

    assert first_line.identifier == moved_line.identifier
    assert before_vote_change.identifier == after_vote_change.identifier


def test_mapping_changes_do_not_change_relationship_identity() -> None:
    relationship = _relationship()
    endpoint = build_endpoint_identity(
        EndpointIdentityPayload(
            relationship_id=relationship.identifier,
            endpoint_side="a",
            normalized_source_reference="Gen.1.1",
        )
    )
    first = build_mapping_identity(
        MappingIdentityPayload(
            endpoint_id=endpoint.identifier,
            target_corpus="hebrew",
            target_analysis_profile="edition_complete",
            target_analysis_reading="qere",
            target_granularity="verse",
            mapping_method="same_label_extant_reference",
            crosswalk_version=None,
            target_passage_ids=("P_HB_ONE",),
        )
    )
    changed = build_mapping_identity(
        MappingIdentityPayload(
            endpoint_id=endpoint.identifier,
            target_corpus="hebrew",
            target_analysis_profile="edition_complete",
            target_analysis_reading="qere",
            target_granularity="verse",
            mapping_method="same_label_extant_reference",
            crosswalk_version=None,
            target_passage_ids=("P_HB_CHANGED",),
        )
    )

    assert first.identifier != changed.identifier
    assert relationship.identifier == _relationship().identifier


def test_direction_changes_relationship_and_reverse_shares_unordered_pair() -> None:
    assert (
        _relationship(direction="from_to").identifier
        != _relationship(direction="to_from").identifier
    )
    forward_directed, forward_unordered = build_pair_identities(
        source_reference_scheme="openbible-v1",
        normalized_endpoint_a="Gen.1.1",
        normalized_endpoint_b="John.1.1",
    )
    reverse_directed, reverse_unordered = build_pair_identities(
        source_reference_scheme="openbible-v1",
        normalized_endpoint_a="John.1.1",
        normalized_endpoint_b="Gen.1.1",
    )

    assert forward_directed.identifier != reverse_directed.identifier
    assert forward_unordered.identifier == reverse_unordered.identifier


def test_duplicate_raw_occurrences_remain_distinct_but_share_relationship() -> None:
    values = {
        "source_id": "openbible-cross-references",
        "source_archive_sha256": ARCHIVE_SHA,
        "raw_record_bytes": b"Gen.1.1\tJohn.1.1\t2",
    }
    first = build_source_record_identity(**values, duplicate_occurrence_ordinal=1)
    duplicate = build_source_record_identity(**values, duplicate_occurrence_ordinal=2)

    assert first.identifier != duplicate.identifier
    assert _relationship().identifier == _relationship().identifier


def test_identity_collision_registry_fails_clearly() -> None:
    registry = BenchmarkIdentityRegistry()
    registry.add(BenchmarkIdentity("BR_" + "a" * 64, "a" * 64, '{"value":1}'))

    with pytest.raises(BenchmarkIdentityCollisionError, match="distinct benchmark payloads"):
        registry.add(BenchmarkIdentity("BR_" + "a" * 64, "a" * 64, '{"value":2}'))
