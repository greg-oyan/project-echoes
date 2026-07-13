"""Typed benchmark row and Polars schema contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from echoes.benchmarks.models import (
    BENCHMARK_ARTIFACT_NAMES,
    BENCHMARK_ARTIFACT_SCHEMAS,
    BenchmarkEndpointMappingRow,
    BenchmarkEndpointRow,
    BenchmarkIssueRow,
    BenchmarkLeakageGroupRow,
    BenchmarkMetadataRow,
    BenchmarkPresumedNegativeRow,
    BenchmarkRelationshipRow,
    BenchmarkRelationshipSourceRecordRow,
    BenchmarkSourceRecordRow,
    BenchmarkSplitAssignmentRow,
)

SHA = "a" * 64
ID = "BR_" + SHA


def test_exact_ten_artifacts_have_explicit_ordered_schemas() -> None:
    assert BENCHMARK_ARTIFACT_NAMES == (
        "benchmark_source_records",
        "benchmark_relationships",
        "benchmark_relationship_source_records",
        "benchmark_endpoints",
        "benchmark_endpoint_mappings",
        "benchmark_leakage_groups",
        "benchmark_split_assignments",
        "benchmark_presumed_negatives",
        "benchmark_issues",
        "benchmark_metadata",
    )
    assert set(BENCHMARK_ARTIFACT_SCHEMAS) == set(BENCHMARK_ARTIFACT_NAMES)
    assert all(len(tuple(schema)) > 0 for schema in BENCHMARK_ARTIFACT_SCHEMAS.values())


def test_model_fields_match_polars_columns_exactly() -> None:
    models = {
        "benchmark_source_records": BenchmarkSourceRecordRow,
        "benchmark_relationships": BenchmarkRelationshipRow,
        "benchmark_relationship_source_records": BenchmarkRelationshipSourceRecordRow,
        "benchmark_endpoints": BenchmarkEndpointRow,
        "benchmark_endpoint_mappings": BenchmarkEndpointMappingRow,
        "benchmark_leakage_groups": BenchmarkLeakageGroupRow,
        "benchmark_split_assignments": BenchmarkSplitAssignmentRow,
        "benchmark_presumed_negatives": BenchmarkPresumedNegativeRow,
        "benchmark_issues": BenchmarkIssueRow,
        "benchmark_metadata": BenchmarkMetadataRow,
    }
    for artifact, model in models.items():
        assert tuple(model.model_fields) == tuple(BENCHMARK_ARTIFACT_SCHEMAS[artifact])


def _relationship(**updates: object) -> BenchmarkRelationshipRow:
    values: dict[str, object] = {
        "relationship_id": ID,
        "tier": 3,
        "source_id": "openbible-cross-references",
        "source_version": "snapshot-v1",
        "source_reference_scheme": "openbible-v1",
        "source_reference_a": "Gen.1.1",
        "source_reference_b": "John.1.1",
        "relationship_direction": "directed",
        "relationship_class": "broad_cross_reference",
        "source_record_count": 1,
        "source_weight_sum": 2,
        "source_weight_max": 2,
        "canonical_directed_pair_id": "BDP_" + SHA,
        "canonical_undirected_pair_id": "BUP_" + SHA,
        "weak_supervision_eligible": True,
        "knownness_filter_eligible": True,
        "primary_evaluation_eligible": False,
        "tier1_eligible": False,
        "data_quality_status": "valid",
        "license_status": "verified",
        "provenance_json": "{}",
        "notes": "",
    }
    values.update(updates)
    return BenchmarkRelationshipRow.model_validate(values)


def test_tier_three_cannot_be_primary_evaluation_or_tier_one() -> None:
    assert _relationship().tier == 3
    with pytest.raises(ValidationError, match="Tier 3"):
        _relationship(primary_evaluation_eligible=True)
    with pytest.raises(ValidationError, match="Tier 3"):
        _relationship(tier1_eligible=True)


def test_endpoint_requires_all_or_no_parsed_coordinates() -> None:
    with pytest.raises(ValidationError, match="wholly present or absent"):
        BenchmarkEndpointRow(
            endpoint_id="BE_" + SHA,
            relationship_id=ID,
            endpoint_side="a",
            source_reference="Gen.1.1",
            source_reference_scheme="openbible-v1",
            parsed_book="GEN",
            parsed_start_chapter=1,
            parsed_start_verse=None,
            parsed_end_chapter=None,
            parsed_end_verse=None,
            is_range=False,
            parse_status="invalid",
        )


def test_presumed_negative_contract_rejects_self_pair() -> None:
    with pytest.raises(ValidationError, match="must be distinct"):
        BenchmarkPresumedNegativeRow(
            contrastive_id="BN_" + SHA,
            benchmark_version="benchmark-v1",
            passage_a_id="P_A",
            passage_b_id="P_A",
            corpus_pair="hebrew-greek",
            negative_strategy="length_matched_random_unlinked",
            presumed_negative=True,
            positive_graph_checked=True,
            reverse_pair_checked=True,
            passage_overlap_checked=True,
            leakage_checked=True,
            length_difference=0,
            book_pair="GEN-JHN",
            genre_pair="torah-gospels_and_acts",
            split_strategy="held_out_book",
            partition="train",
            seed=1,
            generation_config_hash=SHA,
            notes="Absence is not proof of nonrelationship.",
        )
