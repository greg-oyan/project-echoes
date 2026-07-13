"""Focused Milestone 6 persisted-artifact validation contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from echoes.benchmarks.models import BENCHMARK_ARTIFACT_NAMES, BENCHMARK_ARTIFACT_SCHEMAS
from echoes.benchmarks.validation import (
    _configured_leakage_crossing_count,
    _hash_validation,
    _manifest_governance_validation,
)
from echoes.corpus.storage import logical_frame_hash
from echoes.manifests.sources import load_source_catalog
from echoes.settings import BenchmarkConfig, load_config


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_production_manifest_and_config_pass_benchmark_governance() -> None:
    config = load_config(Path("config/benchmark.yaml"))
    assert isinstance(config, BenchmarkConfig)
    catalog = load_source_catalog(Path("data/manifests/sources.yaml"))
    openbible = catalog.find("openbible-cross-references")
    tier1 = catalog.find("project-echoes-tier1-quotations")
    assert openbible is not None and tier1 is not None
    issues = []

    _manifest_governance_validation(openbible, tier1, config, issues)

    assert issues == []


def test_configured_leakage_cross_partition_is_detected(tmp_path: Path) -> None:
    database = tmp_path / "leakage.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE benchmark_leakage_groups AS SELECT * FROM (VALUES "
            "('R1','exact_unordered_pair','G1'),('R2','exact_unordered_pair','G1')) "
            "t(relationship_id,group_type,leakage_group_id)"
        )
        connection.execute(
            "CREATE TABLE benchmark_split_assignments AS SELECT * FROM (VALUES "
            "('R1','held_out_book','train'),('R2','held_out_book','test')) "
            "t(relationship_id,split_strategy,partition)"
        )
        crossing = _configured_leakage_crossing_count(
            connection,
            split_name="held_out_book",
            group_types=("exact_unordered_pair",),
        )
        connection.execute(
            "UPDATE benchmark_split_assignments SET partition='train' WHERE relationship_id='R2'"
        )
        reconciled = _configured_leakage_crossing_count(
            connection,
            split_name="held_out_book",
            group_types=("exact_unordered_pair",),
        )

    assert crossing == 1
    assert reconciled == 0


def test_hash_validation_streams_without_full_frame_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logical: dict[str, str] = {}
    physical: dict[str, str] = {}
    counts: dict[str, int] = {}
    for name in BENCHMARK_ARTIFACT_NAMES:
        frame = pl.DataFrame(schema=BENCHMARK_ARTIFACT_SCHEMAS[name])
        path = tmp_path / name / "part-00000.parquet"
        path.parent.mkdir(parents=True)
        frame.write_parquet(path)
        logical_frame = frame
        if name == "benchmark_metadata":
            logical_frame = frame.drop(
                "physical_table_hashes_json",
                "processing_environment_json",
                "runtime_seconds",
                "storage_footprint_bytes",
            )
        logical[name] = logical_frame_hash(logical_frame, sort_by=[])
        physical[name] = _sha256(path)
        counts[name] = 0
    (tmp_path / "table-hashes.json").write_text(
        json.dumps(
            {
                "artifact_schema_version": 1,
                "table_counts": counts,
                "table_logical_sha256": logical,
                "table_physical_sha256": physical,
            }
        ),
        encoding="utf-8",
    )
    issues = []

    def reject_full_read(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("validation must not materialize a complete Parquet table")

    monkeypatch.setattr(pl, "read_parquet", reject_full_read)

    observed_logical, observed_physical, observed_counts = _hash_validation(tmp_path, issues)

    assert issues == []
    assert observed_logical == logical
    assert observed_physical == physical
    assert observed_counts == counts
