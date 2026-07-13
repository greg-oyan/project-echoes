from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import duckdb
import polars as pl
import pytest

from echoes.benchmarks.models import (
    BENCHMARK_ARTIFACT_NAMES,
    BENCHMARK_ARTIFACT_SCHEMAS,
    BenchmarkArtifactName,
    BenchmarkMetadataRow,
)
from echoes.benchmarks.storage import (
    DUCKDB_LOAD_MEMORY_LIMIT,
    DUCKDB_LOAD_THREADS,
    SORT_COLUMNS,
    BenchmarkArtifactStager,
    BenchmarkStorageError,
    _benchmark_duckdb_temp_directory,
    _configure_benchmark_duckdb_connection,
    load_benchmark_duckdb,
    logical_parquet_hash,
    read_benchmark_artifacts,
    table_row_counts,
    write_benchmark_artifacts,
)
from echoes.corpus.storage import logical_frame_hash

ZERO_HASH = "0" * 64


def _empty_frames() -> dict[BenchmarkArtifactName, pl.DataFrame]:
    frames = {
        name: pl.DataFrame(schema=BENCHMARK_ARTIFACT_SCHEMAS[name])
        for name in BENCHMARK_ARTIFACT_NAMES
    }
    metadata = BenchmarkMetadataRow(
        benchmark_run_id="benchmark-v1-test",
        benchmark_version="test-v1",
        source_versions_json='{"openbible":"test"}',
        source_archive_hashes_json=f'{{"openbible":"{ZERO_HASH}"}}',
        source_file_hashes_json="{}",
        source_audit_json="{}",
        tier1_header_sha256=ZERO_HASH,
        passage_input_run_id="passages-v1-test",
        passage_logical_hashes_json="{}",
        relationship_count=0,
        endpoint_count=0,
        mapping_count=0,
        leakage_group_counts_json="{}",
        split_counts_json="{}",
        negative_counts_json="{}",
        configuration_hash=ZERO_HASH,
        logical_table_hashes_json="{}",
        physical_table_hashes_json="{}",
        processing_environment_json='{"python":"test"}',
        runtime_seconds=1.5,
        storage_footprint_bytes=0,
    )
    frames["benchmark_metadata"] = pl.DataFrame(
        [metadata.model_dump()], schema=BENCHMARK_ARTIFACT_SCHEMAS["benchmark_metadata"]
    )
    return frames


def _source_record_frame(line_numbers: list[int]) -> pl.DataFrame:
    rows = [
        {
            "benchmark_schema_version": 1,
            "source_record_id": f"BSR_{line_number:064x}",
            "source_id": "openbible-cross-references",
            "source_version": "fixture",
            "source_archive_sha256": "a" * 64,
            "source_file": "cross_references.txt",
            "source_line_number": line_number,
            "raw_record_sha256": f"{line_number:064x}",
            "source_reference_a": f"Gen.1.{line_number}",
            "source_reference_b": f"John.1.{line_number}",
            "source_weight": line_number if line_number % 2 else None,
            "source_direction": "directed",
            "parse_status": "parsed",
            "notes": "fixture",
        }
        for line_number in line_numbers
    ]
    return pl.DataFrame(
        rows,
        schema=BENCHMARK_ARTIFACT_SCHEMAS["benchmark_source_records"],
        orient="row",
    )


def _corpus_view_frames() -> dict[BenchmarkArtifactName, pl.DataFrame]:
    frames = _empty_frames()
    relationships = []
    endpoints = []
    definitions = (
        (
            "ot",
            ("Dan.6.28", "DAN", 6, 28, "parsed"),
            ("2Chr.36.21-Ezra.1.2", None, None, None, "cross_book_range"),
        ),
        (
            "nt",
            ("Acts.9.15", "ACT", 9, 15, "parsed"),
            ("Acts.28.17-Rom.1.1", None, None, None, "cross_book_range"),
        ),
        (
            "cross",
            ("Gen.1.1", "GEN", 1, 1, "parsed"),
            ("John.1.1", "JHN", 1, 1, "parsed"),
        ),
    )
    for name, endpoint_a, endpoint_b in definitions:
        relationship_id = f"BR_{name}"
        relationships.append(
            {
                "relationship_id": relationship_id,
                "benchmark_schema_version": 1,
                "tier": 3,
                "source_id": "openbible-cross-references",
                "source_version": "fixture",
                "source_reference_scheme": "openbible-english-protestant-v1",
                "source_reference_a": endpoint_a[0],
                "source_reference_b": endpoint_b[0],
                "relationship_direction": "directed",
                "relationship_class": "cross_reference",
                "source_record_count": 1,
                "source_weight_sum": 1,
                "source_weight_max": 1,
                "canonical_directed_pair_id": f"BDP_{name}",
                "canonical_undirected_pair_id": f"BUP_{name}",
                "weak_supervision_eligible": True,
                "knownness_filter_eligible": True,
                "primary_evaluation_eligible": False,
                "tier1_eligible": False,
                "data_quality_status": "fixture",
                "license_status": "fixture",
                "provenance_json": "{}",
                "notes": "fixture",
            }
        )
        for side, endpoint in zip(("a", "b"), (endpoint_a, endpoint_b), strict=True):
            reference, book, chapter, verse, status = endpoint
            endpoints.append(
                {
                    "endpoint_id": f"BE_{name}_{side}",
                    "relationship_id": relationship_id,
                    "endpoint_side": side,
                    "source_reference": reference,
                    "source_reference_scheme": "openbible-english-protestant-v1",
                    "parsed_book": book,
                    "parsed_start_chapter": chapter,
                    "parsed_start_verse": verse,
                    "parsed_end_chapter": chapter,
                    "parsed_end_verse": verse,
                    "is_range": "-" in reference,
                    "parse_status": status,
                }
            )
    frames["benchmark_relationships"] = pl.DataFrame(
        relationships,
        schema=BENCHMARK_ARTIFACT_SCHEMAS["benchmark_relationships"],
        orient="row",
    )
    frames["benchmark_endpoints"] = pl.DataFrame(
        endpoints,
        schema=BENCHMARK_ARTIFACT_SCHEMAS["benchmark_endpoints"],
        orient="row",
    )
    return frames


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_atomic_parquet_round_trip_and_no_silent_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "benchmarks"
    first = write_benchmark_artifacts(_empty_frames(), output)
    loaded = read_benchmark_artifacts(first.schema_root)
    assert set(loaded) == set(BENCHMARK_ARTIFACT_NAMES)
    assert loaded["benchmark_metadata"].height == 1
    assert set(first.table_logical_hashes) == set(BENCHMARK_ARTIFACT_NAMES)
    assert all(len(value) == 64 for value in first.table_physical_hashes.values())
    manifest = json.loads((first.schema_root / "table-hashes.json").read_text("utf-8"))
    assert manifest["table_counts"]["benchmark_metadata"] == 1
    for name, path in first.table_paths.items():
        assert logical_parquet_hash(path, name, batch_size=1) == first.table_logical_hashes[name]

    with pytest.raises(BenchmarkStorageError, match="already exist"):
        write_benchmark_artifacts(_empty_frames(), output)
    second = write_benchmark_artifacts(_empty_frames(), output, force=True)
    assert second.table_logical_hashes == first.table_logical_hashes
    assert second.table_physical_hashes == first.table_physical_hashes


def test_duckdb_rerun_preserves_nonbenchmark_tables(tmp_path: Path) -> None:
    stored = write_benchmark_artifacts(_empty_frames(), tmp_path / "benchmarks")
    database = tmp_path / "echoes.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE passage_sentinel(value INTEGER)")
        connection.execute("INSERT INTO passage_sentinel VALUES (7)")

    load_benchmark_duckdb(stored, database)
    load_benchmark_duckdb(stored, database)
    counts = table_row_counts(database)
    assert counts["benchmark_metadata"] == 1
    assert sum(counts.values()) == 1
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT value FROM passage_sentinel").fetchone() == (7,)
        views = {
            row[0]
            for row in connection.execute(
                "SELECT view_name FROM duckdb_views() WHERE database_name=current_database()"
            ).fetchall()
        }
    assert "tier3_openbible_relationships" in views
    assert "benchmark_reference_risks" in views


def test_duckdb_loader_uses_bounded_resources_and_same_volume_spill(
    tmp_path: Path,
) -> None:
    database = tmp_path / "echoes.duckdb"
    temp_directory = _benchmark_duckdb_temp_directory(database)
    temp_directory.mkdir()
    marker = temp_directory / "preexisting-marker.txt"
    marker.write_text("preserve\n", encoding="utf-8")

    with duckdb.connect(str(database)) as connection:
        observed_temp = _configure_benchmark_duckdb_connection(connection, database)
        settings = connection.execute(
            "SELECT current_setting('memory_limit'), current_setting('threads'), "
            "current_setting('preserve_insertion_order'), current_setting('temp_directory')"
        ).fetchone()

    assert observed_temp.parent == database.parent
    assert settings is not None
    assert settings[0] == "2.0 GiB"
    assert settings[1] == DUCKDB_LOAD_THREADS == 2
    assert settings[2] is False
    assert Path(settings[3]).resolve() == temp_directory.resolve()
    assert DUCKDB_LOAD_MEMORY_LIMIT == "2GiB"
    assert marker.read_text(encoding="utf-8") == "preserve\n"


def test_corpus_pair_views_use_preserved_source_books_without_mapping_defaults(
    tmp_path: Path,
) -> None:
    stored = write_benchmark_artifacts(_corpus_view_frames(), tmp_path / "benchmarks")
    database = tmp_path / "echoes.duckdb"
    load_benchmark_duckdb(stored, database)

    with duckdb.connect(str(database), read_only=True) as connection:
        counts = tuple(
            int(connection.execute(f"SELECT count(*) FROM {view}").fetchone()[0])
            for view in (
                "within_old_testament_relationships",
                "within_new_testament_relationships",
                "cross_testament_relationships",
            )
        )

    assert counts == (1, 1, 1)


def test_batched_staging_matches_single_frame_and_is_physically_deterministic(
    tmp_path: Path,
) -> None:
    name: BenchmarkArtifactName = "benchmark_source_records"
    unsorted = _source_record_frame([3, 1, 4, 2])
    expected_logical = logical_frame_hash(
        unsorted,
        sort_by=list(SORT_COLUMNS[name]),
    )

    with BenchmarkArtifactStager(tmp_path / "single") as single:
        single_staging = single.staging
        single_path = single.write_content(name, unsorted)
        single_physical = _sha256(single_path)
        single_logical = logical_parquet_hash(single_path, name, batch_size=2)
        assert single.table_counts[name] == 4
    assert not single_staging.exists()

    with BenchmarkArtifactStager(tmp_path / "batched") as batched:
        batched_staging = batched.staging
        batched_path = batched.write_content_batches(
            name,
            (_source_record_frame([4, 2]), _source_record_frame([3, 1])),
        )
        observed = pl.read_parquet(batched_path)
        batched_physical = _sha256(batched_path)
        batched_logical = logical_parquet_hash(batched_path, name, batch_size=1)
        assert observed.schema == BENCHMARK_ARTIFACT_SCHEMAS[name]
        assert observed["source_line_number"].to_list() == [1, 2, 3, 4]
        assert batched.table_counts[name] == 4
    assert not batched_staging.exists()

    assert single_logical == batched_logical == expected_logical
    assert single_physical == batched_physical


def test_batched_staging_cleans_private_parts_after_failure(tmp_path: Path) -> None:
    name: BenchmarkArtifactName = "benchmark_source_records"

    def failing_batches() -> Iterator[pl.DataFrame]:
        yield _source_record_frame([1])
        raise RuntimeError("synthetic batch failure")

    with BenchmarkArtifactStager(tmp_path / "failed") as stager:
        with pytest.raises(RuntimeError, match="synthetic batch failure"):
            stager.write_content_batches(name, failing_batches())
        assert list(stager.staging.iterdir()) == []
        recovered = stager.write_content_batches(name, (_source_record_frame([2]),))
        assert recovered.is_file()
