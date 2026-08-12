"""Authenticated M6 OpenBible knownness projection tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from echoes.benchmarks.models import (
    BENCHMARK_ARTIFACT_NAMES,
    BENCHMARK_ENDPOINT_MAPPINGS_POLARS_SCHEMA,
    BENCHMARK_ENDPOINTS_POLARS_SCHEMA,
    BENCHMARK_RELATIONSHIPS_POLARS_SCHEMA,
)
from echoes.final_discovery.knownness_projection import (
    KnownnessProjectionError,
    authenticate_knownness_jsonl,
    iter_authenticated_knownness_jsonl,
    project_openbible_knownness,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_fixture(tmp_path: Path, *, self_pair: bool = False) -> tuple[Path, str, str]:
    root = tmp_path / "schema-v1"
    root.mkdir(parents=True)
    relationship_id = "BR_" + "1" * 64
    endpoint_a = "BE_" + "2" * 64
    endpoint_b = "BE_" + "3" * 64
    relationships = pl.DataFrame(
        [
            {
                "relationship_id": relationship_id,
                "benchmark_schema_version": 1,
                "tier": 3,
                "source_id": "openbible-cross-references",
                "source_version": "2026-07-12",
                "source_reference_scheme": "openbible-english-protestant-v1",
                "source_reference_a": "Gen.1.1",
                "source_reference_b": "Exod.1.1",
                "relationship_direction": "a_to_b",
                "relationship_class": "cross_reference",
                "source_record_count": 1,
                "source_weight_sum": 5,
                "source_weight_max": 5,
                "canonical_directed_pair_id": "BDP_" + "4" * 64,
                "canonical_undirected_pair_id": "BUP_" + "5" * 64,
                "weak_supervision_eligible": True,
                "knownness_filter_eligible": True,
                "primary_evaluation_eligible": False,
                "tier1_eligible": False,
                "data_quality_status": "valid",
                "license_status": "approved",
                "provenance_json": "{}",
                "notes": "",
            }
        ],
        schema=BENCHMARK_RELATIONSHIPS_POLARS_SCHEMA,
    )
    endpoints = pl.DataFrame(
        [
            {
                "endpoint_id": endpoint_a,
                "relationship_id": relationship_id,
                "endpoint_side": "a",
                "source_reference": "Gen.1.1",
                "source_reference_scheme": "openbible-english-protestant-v1",
                "parsed_book": "Genesis",
                "parsed_start_chapter": 1,
                "parsed_start_verse": 1,
                "parsed_end_chapter": 1,
                "parsed_end_verse": 1,
                "is_range": False,
                "parse_status": "parsed",
            },
            {
                "endpoint_id": endpoint_b,
                "relationship_id": relationship_id,
                "endpoint_side": "b",
                "source_reference": "Exod.1.1",
                "source_reference_scheme": "openbible-english-protestant-v1",
                "parsed_book": "Exodus",
                "parsed_start_chapter": 1,
                "parsed_start_verse": 1,
                "parsed_end_chapter": 1,
                "parsed_end_verse": 1,
                "is_range": False,
                "parse_status": "parsed",
            },
        ],
        schema=BENCHMARK_ENDPOINTS_POLARS_SCHEMA,
    )
    target_b = ["passage-b1", "passage-b2"]
    if self_pair:
        target_b[0] = "passage-a1"
    mappings = pl.DataFrame(
        [
            _mapping(
                "BM_" + "6" * 64,
                endpoint_a,
                ["passage-a1", "passage-a2"],
                "mapped_verified",
            ),
            _mapping(
                "BM_" + "7" * 64,
                endpoint_b,
                target_b,
                "mapped_partial",
            ),
            _mapping(
                "BM_" + "8" * 64,
                endpoint_b,
                ["ignored-unresolved"],
                "unresolved_reference",
            ),
        ],
        schema=BENCHMARK_ENDPOINT_MAPPINGS_POLARS_SCHEMA,
    )
    frames = {
        "benchmark_relationships": relationships,
        "benchmark_endpoints": endpoints,
        "benchmark_endpoint_mappings": mappings,
    }
    counts = {name: 0 for name in BENCHMARK_ARTIFACT_NAMES}
    logical = {name: "a" * 64 for name in BENCHMARK_ARTIFACT_NAMES}
    physical = {name: "b" * 64 for name in BENCHMARK_ARTIFACT_NAMES}
    for name, frame in frames.items():
        path = root / name / "part-00000.parquet"
        path.parent.mkdir(parents=True)
        frame.write_parquet(path, compression="zstd")
        counts[name] = frame.height
        physical[name] = _sha256(path)
    manifest_path = root / "table-hashes.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_schema_version": 1,
                "table_counts": counts,
                "table_logical_sha256": logical,
                "table_physical_sha256": physical,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return root, _sha256(manifest_path), relationship_id


def _mapping(
    mapping_id: str,
    endpoint_id: str,
    passage_ids: list[str],
    mapping_status: str,
) -> dict[str, object]:
    return {
        "mapping_id": mapping_id,
        "endpoint_id": endpoint_id,
        "target_corpus": "hebrew",
        "target_analysis_profile": "edition_complete",
        "target_analysis_reading": "qere",
        "target_granularity": "verse",
        "target_passage_ids_json": json.dumps(passage_ids),
        "target_reference_sequence_json": json.dumps(
            [f"Fixture {index}:1" for index in range(len(passage_ids))]
        ),
        "mapping_method": "same_label",
        "mapping_confidence": "provisional",
        "mapping_status": mapping_status,
        "reference_gap": False,
        "disputed_passage_flag": False,
        "disputed_passage_ids_json": "[]",
        "crosswalk_source": None,
        "crosswalk_version": None,
        "ambiguity_reason": None,
        "notes": "",
    }


def test_projection_authenticates_expands_and_is_reproducible(tmp_path: Path) -> None:
    root, manifest_sha256, source_relationship_id = _write_fixture(tmp_path)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = project_openbible_knownness(
        root,
        first_root / "knownness.jsonl",
        first_root / "knownness-receipt.json",
        expected_manifest_sha256=manifest_sha256,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=first_root / "spill",
        batch_size=2,
    )
    second = project_openbible_knownness(
        root,
        second_root / "knownness.jsonl",
        second_root / "knownness-receipt.json",
        expected_manifest_sha256=manifest_sha256,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=second_root / "spill",
        batch_size=3,
    )

    assert first == second
    assert first.row_count == 4
    assert first.source_manifest_sha256 == manifest_sha256
    assert set(first.used_table_physical_sha256) == {
        "benchmark_relationships",
        "benchmark_endpoints",
        "benchmark_endpoint_mappings",
    }
    assert (first_root / "knownness.jsonl").read_bytes() == (
        second_root / "knownness.jsonl"
    ).read_bytes()
    rows = tuple(
        iter_authenticated_knownness_jsonl(
            first_root / "knownness.jsonl",
            first_root / "knownness-receipt.json",
            expected_manifest_sha256=manifest_sha256,
        )
    )
    assert {(row.source_passage_id, row.target_passage_id) for row in rows} == {
        ("passage-a1", "passage-b1"),
        ("passage-a1", "passage-b2"),
        ("passage-a2", "passage-b1"),
        ("passage-a2", "passage-b2"),
    }
    assert len({row.relationship_id for row in rows}) == 4
    assert all(row.source_relationship_id == source_relationship_id for row in rows)
    assert all(row.mapping_quality == "mapped_partial" for row in rows)
    assert all("ignored-unresolved" not in row.source_provenance_json for row in rows)


def test_projection_rejects_used_physical_hash_drift(tmp_path: Path) -> None:
    root, manifest_sha256, _ = _write_fixture(tmp_path)
    path = root / "benchmark_endpoints" / "part-00000.parquet"
    with path.open("ab") as handle:
        handle.write(b"drift")

    with pytest.raises(KnownnessProjectionError, match="physical hash mismatch"):
        project_openbible_knownness(
            root,
            tmp_path / "knownness.jsonl",
            tmp_path / "receipt.json",
            expected_manifest_sha256=manifest_sha256,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=tmp_path / "spill",
        )


def test_projection_excludes_and_counts_expanded_self_pair(tmp_path: Path) -> None:
    root, manifest_sha256, _ = _write_fixture(tmp_path, self_pair=True)

    receipt = project_openbible_knownness(
        root,
        tmp_path / "knownness.jsonl",
        tmp_path / "receipt.json",
        expected_manifest_sha256=manifest_sha256,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "spill",
    )

    assert receipt.excluded_self_edge_count == 1
    assert receipt.expanded_edge_count == receipt.row_count + 1


def test_supplied_jsonl_authentication_detects_exact_byte_drift(tmp_path: Path) -> None:
    root, manifest_sha256, _ = _write_fixture(tmp_path)
    output = tmp_path / "knownness.jsonl"
    receipt = tmp_path / "receipt.json"
    project_openbible_knownness(
        root,
        output,
        receipt,
        expected_manifest_sha256=manifest_sha256,
        memory_limit_bytes=256 * 1024**2,
        temp_directory=tmp_path / "spill",
    )
    output.write_bytes(output.read_bytes().replace(b"mapped_partial", b"mapped_verified", 1))

    with pytest.raises(KnownnessProjectionError):
        authenticate_knownness_jsonl(
            output,
            receipt,
            expected_manifest_sha256=manifest_sha256,
        )
