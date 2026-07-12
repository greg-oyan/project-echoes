"""Typed passage row and ordered storage-schema tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from echoes.segment.identity import IdentityMember, build_passage_identity, payload_from_membership
from echoes.segment.models import (
    PASSAGE_ADJACENCY_COLUMNS,
    PASSAGE_ADJACENCY_POLARS_SCHEMA,
    PASSAGE_COLUMNS,
    PASSAGE_MEMBERSHIP_COLUMNS,
    PASSAGE_MEMBERSHIP_POLARS_SCHEMA,
    PASSAGE_POLARS_SCHEMA,
    SEGMENTATION_EXCLUSION_COLUMNS,
    SEGMENTATION_EXCLUSION_POLARS_SCHEMA,
    SEGMENTATION_ISSUE_COLUMNS,
    SEGMENTATION_ISSUE_POLARS_SCHEMA,
    SEGMENTATION_METADATA_COLUMNS,
    SEGMENTATION_METADATA_POLARS_SCHEMA,
    PassageAdjacencyRow,
    PassageMembershipRow,
    PassageRow,
    SegmentationExclusionRow,
    SegmentationIssueRow,
    SegmentationMetadataRow,
)

SHA = "a" * 64


def _passage_id() -> tuple[str, str]:
    payload = payload_from_membership(
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        book="GEN",
        source_unit_id=None,
        members=[IdentityMember("HB_GEN_001_001_0001", 1, "GEN 1:1")],
    )
    identity = build_passage_identity(payload)
    return identity.passage_id, identity.payload_sha256


def _passage_values() -> dict[str, object]:
    passage_id, digest = _passage_id()
    singleton = json.dumps([None], separators=(",", ":"))
    return {
        "schema_version": 1,
        "passage_id": passage_id,
        "identity_payload_sha256": digest,
        "segmentation_run_id": "segmentation-test",
        "corpus": "hebrew",
        "analysis_profile": "edition_complete",
        "analysis_reading": "qere",
        "granularity": "verse",
        "book": "GEN",
        "book_order": 1,
        "start_reference": "GEN 1:1",
        "end_reference": "GEN 1:1",
        "reference_sequence_json": '["GEN 1:1"]',
        "token_ids_json": '["HB_GEN_001_001_0001"]',
        "source_unit_id": None,
        "constituent_verse_passage_ids_json": "[]",
        "start_token_id": "HB_GEN_001_001_0001",
        "end_token_id": "HB_GEN_001_001_0001",
        "start_stream_position_in_corpus": 1,
        "end_stream_position_in_corpus": 1,
        "token_count": 1,
        "visible_token_count": 1,
        "zero_width_token_count": 0,
        "punctuation_token_count": 0,
        "word_count": 1,
        "sentence_count": 1,
        "clause_count": 1,
        "source_ids_json": '["macula-hebrew"]',
        "source_versions_json": '["fixture"]',
        "surface_text": "fixture",
        "normalized_text": "fixture",
        "unpointed_text": "fixture",
        "folded_text": None,
        "lemma_sequence_json": singleton,
        "root_sequence_json": singleton,
        "part_of_speech_sequence_json": singleton,
        "semantic_domain_sequence_json": singleton,
        "entity_ids_json": singleton,
        "participant_ids_json": singleton,
        "disputed_passage_flag": False,
        "disputed_passage_ids_json": "[]",
        "reference_gap": False,
        "ketiv_structural_uncertainty": False,
        "profile_truncated": False,
        "sensitivity_exclusion_count": 0,
        "previous_passage_id": None,
        "next_passage_id": None,
        "overlap_with_previous_token_count": 0,
        "overlap_with_next_token_count": 0,
        "segmentation_config_hash": SHA,
        "created_by_schema_version": 1,
    }


def test_passage_schema_and_model_have_identical_ordered_fields() -> None:
    assert tuple(PASSAGE_POLARS_SCHEMA) == PASSAGE_COLUMNS
    assert tuple(PassageRow.model_fields) == PASSAGE_COLUMNS
    assert PassageRow.model_validate(_passage_values()).token_count == 1


def test_every_other_table_schema_matches_its_row_model_order() -> None:
    contracts = (
        (PASSAGE_MEMBERSHIP_COLUMNS, PASSAGE_MEMBERSHIP_POLARS_SCHEMA, PassageMembershipRow),
        (PASSAGE_ADJACENCY_COLUMNS, PASSAGE_ADJACENCY_POLARS_SCHEMA, PassageAdjacencyRow),
        (
            SEGMENTATION_EXCLUSION_COLUMNS,
            SEGMENTATION_EXCLUSION_POLARS_SCHEMA,
            SegmentationExclusionRow,
        ),
        (SEGMENTATION_ISSUE_COLUMNS, SEGMENTATION_ISSUE_POLARS_SCHEMA, SegmentationIssueRow),
        (
            SEGMENTATION_METADATA_COLUMNS,
            SEGMENTATION_METADATA_POLARS_SCHEMA,
            SegmentationMetadataRow,
        ),
    )
    for columns, schema, model in contracts:
        assert columns == tuple(schema)
        assert columns == tuple(model.model_fields)


def test_passage_count_and_language_contracts_are_enforced() -> None:
    invalid_counts = _passage_values()
    invalid_counts["zero_width_token_count"] = 1
    with pytest.raises(ValidationError, match="must sum to token_count"):
        PassageRow.model_validate(invalid_counts)

    invalid_language = _passage_values()
    invalid_language["analysis_reading"] = "source"
    with pytest.raises(ValidationError, match="qere or ketiv"):
        PassageRow.model_validate(invalid_language)


def test_nullable_sequence_values_remain_distinct_from_empty_strings() -> None:
    values = _passage_values()
    values["lemma_sequence_json"] = "[null]"
    null_model = PassageRow.model_validate(values)
    values["lemma_sequence_json"] = '[""]'
    empty_model = PassageRow.model_validate(values)

    assert null_model.lemma_sequence_json != empty_model.lemma_sequence_json


def test_sequence_length_must_match_authoritative_membership_count() -> None:
    values = _passage_values()
    values["lemma_sequence_json"] = "[]"

    with pytest.raises(ValidationError, match="length must equal token_count"):
        PassageRow.model_validate(values)


def test_membership_retains_stream_and_source_order_provenance() -> None:
    passage_id, _ = _passage_id()
    row = PassageMembershipRow(
        passage_id=passage_id,
        token_id="HB_GEN_001_001_0001",
        position_in_passage=1,
        source_position_in_corpus=42,
        source_reference="GEN 1:1",
        source_id="oshb-morphhb",
        variant_type="ketiv",
        membership_basis="ketiv_verse_stream",
        structural_resolution_status="partially_resolved",
        segmentation_run_id="segmentation-test",
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="ketiv",
        granularity="verse",
        stream_position_in_corpus=99,
        source_edition_reference="Gen 1:1",
        source_version="fixture",
        locus_id="KQ_GEN_001_001_0001",
    )

    assert row.source_position_in_corpus == 42
    assert row.stream_position_in_corpus == 99
    assert row.source_reference == "GEN 1:1"
    assert row.source_edition_reference == "Gen 1:1"


def test_continuous_adjacency_cannot_also_be_a_boundary_break() -> None:
    passage_id, _ = _passage_id()
    other_id = passage_id.replace("a", "b", 1)
    with pytest.raises(ValidationError, match="cannot be analytically continuous"):
        PassageAdjacencyRow(
            corpus="hebrew",
            analysis_profile="edition_complete",
            analysis_reading="qere",
            granularity="verse",
            from_passage_id=passage_id,
            to_passage_id=other_id,
            source_successor=True,
            analytically_continuous=True,
            reference_gap=False,
            boundary_break=True,
            relation="source_successor",
            reason="invalid fixture",
            segmentation_run_id="segmentation-test",
        )


def test_exclusion_issue_and_metadata_json_contracts() -> None:
    passage_id, _ = _passage_id()
    exclusion = SegmentationExclusionRow(
        exclusion_id="X_TEST",
        segmentation_run_id="segmentation-test",
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="ketiv",
        granularity="clause",
        token_id="HB_GEN_001_001_0001",
        locus_id="KQ_TEST",
        source_reference="GEN 1:1",
        reason_code="ketiv_unresolved_clause_mapping",
        resolution_status="explicit_exclusion",
        related_passage_ids_json=json.dumps([passage_id]),
        notes="fixture",
        source_id="oshb-morphhb",
        source_version="fixture",
        source_edition_reference="Gen 1:1",
        stream_position_in_corpus=1,
    )
    issue = SegmentationIssueRow(
        issue_id="I_TEST",
        segmentation_run_id="segmentation-test",
        severity="warning",
        code="fixture",
        message="fixture",
        details_json="{}",
    )
    metadata = SegmentationMetadataRow(
        segmentation_run_id="segmentation-test",
        segmentation_config_hash=SHA,
        input_source_versions_json="{}",
        input_primary_identity_digests_json="{}",
        input_surface_lemma_digests_json="{}",
        input_analytical_digests_json="{}",
        input_oshb_supplement_digests_json="{}",
        enabled_corpora_json='["hebrew","greek"]',
        analysis_profiles_json='["edition_complete","critical_core"]',
        analysis_readings_json='["qere","ketiv","source"]',
        granularities_json='["clause","sentence","verse","two_verse","five_verse"]',
        table_counts_json="{}",
        table_logical_hashes_json="{}",
        table_physical_hashes_json="{}",
        processing_environment_json="{}",
        runtime_seconds=0.1,
        output_size_bytes=0,
    )

    assert exclusion.related_passage_ids_json == json.dumps([passage_id])
    assert issue.severity.value == "warning"
    assert metadata.passage_schema_version == 1

    with pytest.raises(ValidationError, match="JSON object"):
        SegmentationIssueRow(
            issue_id="I_BAD",
            segmentation_run_id="segmentation-test",
            severity="error",
            code="fixture",
            message="fixture",
            details_json="[]",
        )
