"""Stable passage identity and fail-closed collision tests."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from pydantic import ValidationError

import echoes.segment.identity as identity_module
from echoes.segment.identity import (
    DuplicatePassagePayloadError,
    IdentityMember,
    PassageIdentityCollisionError,
    PassageIdentityPayload,
    PassageIdRegistry,
    build_passage_identity,
    payload_from_membership,
)


def _members(order: Iterable[int] = (1, 2)) -> list[IdentityMember]:
    values = {
        1: IdentityMember("HB_GEN_001_001_0001", 1, "GEN 1:1"),
        2: IdentityMember("HB_GEN_001_001_0002", 2, "GEN 1:1"),
    }
    return [values[position] for position in order]


def _payload(
    *,
    profile: str = "edition_complete",
    reading: str = "qere",
    members: Iterable[IdentityMember] | None = None,
) -> PassageIdentityPayload:
    return payload_from_membership(
        corpus="hebrew",
        analysis_profile=profile,  # type: ignore[arg-type]
        analysis_reading=reading,  # type: ignore[arg-type]
        granularity="verse",
        book="GEN",
        source_unit_id=None,
        members=_members() if members is None else members,
    )


def test_reordered_input_rows_do_not_change_identity() -> None:
    first = build_passage_identity(_payload(members=_members((1, 2))))
    second = build_passage_identity(_payload(members=_members((2, 1))))

    assert first == second
    assert first.passage_id.startswith("P_HB_EDITION_COMPLETE_QERE_VERSE_GEN_001_001~")
    assert first.passage_id.endswith(first.payload_sha256)
    assert len(first.payload_sha256) == 64


def test_membership_profile_and_reading_change_identity() -> None:
    original = build_passage_identity(_payload())
    changed_membership = build_passage_identity(
        _payload(
            members=[
                IdentityMember("HB_GEN_001_001_0001", 1, "GEN 1:1"),
                IdentityMember("HB_GEN_001_001_0003", 2, "GEN 1:1"),
            ]
        )
    )
    changed_profile = build_passage_identity(_payload(profile="critical_core"))
    changed_reading = build_passage_identity(_payload(reading="ketiv"))

    assert (
        len(
            {
                original.passage_id,
                changed_membership.passage_id,
                changed_profile.passage_id,
                changed_reading.passage_id,
            }
        )
        == 4
    )


def test_run_and_configuration_facts_are_absent_from_identity() -> None:
    payload = _payload()
    document = build_passage_identity(payload).canonical_payload_json

    assert "run_id" not in document
    assert "config" not in document
    assert "path" not in document
    assert "timestamp" not in document


def test_duplicate_payload_is_rejected() -> None:
    registry = PassageIdRegistry()
    registry.build_and_register(_payload())

    with pytest.raises(DuplicatePassagePayloadError, match="emitted twice"):
        registry.build_and_register(_payload())


def test_digest_collision_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = PassageIdRegistry()
    monkeypatch.setattr(identity_module, "_payload_sha256", lambda _: "a" * 64)
    registry.build_and_register(_payload())

    with pytest.raises(PassageIdentityCollisionError, match="distinct passage payloads"):
        registry.build_and_register(_payload(profile="critical_core"))


def test_invalid_membership_positions_and_duplicate_tokens_fail() -> None:
    with pytest.raises(ValueError, match="start at one and be continuous"):
        _payload(members=[IdentityMember("HB_GEN_001_001_0001", 2, "GEN 1:1")])

    with pytest.raises(ValidationError, match="duplicate token IDs"):
        PassageIdentityPayload(
            corpus="hebrew",
            analysis_profile="edition_complete",
            analysis_reading="qere",
            granularity="verse",
            book="GEN",
            reference_sequence=("GEN 1:1",),
            token_ids=("HB_GEN_001_001_0001", "HB_GEN_001_001_0001"),
        )


def test_clause_and_sentence_identity_require_source_unit() -> None:
    with pytest.raises(ValidationError, match="require source_unit_id"):
        PassageIdentityPayload(
            corpus="greek",
            analysis_profile="edition_complete",
            analysis_reading="source",
            granularity="sentence",
            book="JHN",
            reference_sequence=("JHN 1:1",),
            token_ids=("GNT_JHN_001_001_0001",),
        )


def test_source_token_ids_are_not_modified() -> None:
    token_ids = ("HB_GEN_001_001_0001", "HB_GEN_001_001_0002")
    payload = _payload(members=_members())
    build_passage_identity(payload)

    assert payload.token_ids == token_ids
