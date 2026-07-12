"""Partitioned passage storage, recovery, and DuckDB exposure tests."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

import echoes.segment.storage as storage_module
from echoes.segment.identity import IdentityMember, build_passage_identity, payload_from_membership
from echoes.segment.models import (
    PASSAGE_ADJACENCY_POLARS_SCHEMA,
    PASSAGE_MEMBERSHIP_POLARS_SCHEMA,
    PASSAGE_POLARS_SCHEMA,
    SEGMENTATION_EXCLUSION_POLARS_SCHEMA,
    SEGMENTATION_ISSUE_POLARS_SCHEMA,
    SEGMENTATION_METADATA_POLARS_SCHEMA,
    PassageAdjacencyRow,
    PassageMembershipRow,
    PassageRow,
    SegmentationIssueRow,
    SegmentationMetadataRow,
)
from echoes.segment.storage import (
    ArtifactPartition,
    PassageArtifactWriter,
    PassageStorageError,
    load_passage_duckdb,
    read_artifact_frame,
    read_hash_manifest,
    read_passage,
    read_passage_membership,
    write_passage_artifacts,
)

SHA = "a" * 64


def _identity(verse: int, token_id: str):
    reference = f"GEN 1:{verse}"
    payload = payload_from_membership(
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        book="GEN",
        source_unit_id=None,
        members=[IdentityMember(token_id, 1, reference)],
    )
    return build_passage_identity(payload)


def _passage(verse: int, token_id: str, position: int) -> PassageRow:
    identity = _identity(verse, token_id)
    reference = f"GEN 1:{verse}"
    singleton_null = "[null]"
    return PassageRow(
        passage_id=identity.passage_id,
        identity_payload_sha256=identity.payload_sha256,
        segmentation_run_id="segmentation-fixture",
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        book="GEN",
        book_order=1,
        start_reference=reference,
        end_reference=reference,
        reference_sequence_json=json.dumps([reference]),
        token_ids_json=json.dumps([token_id]),
        source_unit_id=None,
        constituent_verse_passage_ids_json="[]",
        start_token_id=token_id,
        end_token_id=token_id,
        start_stream_position_in_corpus=position,
        end_stream_position_in_corpus=position,
        token_count=1,
        visible_token_count=1,
        zero_width_token_count=0,
        punctuation_token_count=0,
        word_count=1,
        sentence_count=1,
        clause_count=1,
        source_ids_json='["macula-hebrew"]',
        source_versions_json='["fixture"]',
        surface_text=f"fixture-{verse}",
        normalized_text=f"fixture-{verse}",
        unpointed_text=f"fixture-{verse}",
        folded_text=None,
        lemma_sequence_json=singleton_null,
        root_sequence_json=singleton_null,
        part_of_speech_sequence_json=singleton_null,
        semantic_domain_sequence_json=singleton_null,
        entity_ids_json=singleton_null,
        participant_ids_json=singleton_null,
        disputed_passage_flag=False,
        disputed_passage_ids_json="[]",
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        profile_truncated=False,
        sensitivity_exclusion_count=0,
        previous_passage_id=None,
        next_passage_id=None,
        overlap_with_previous_token_count=0,
        overlap_with_next_token_count=0,
        segmentation_config_hash=SHA,
    )


def _frame(rows: list[object], schema: pl.Schema) -> pl.DataFrame:
    dumped = [row.model_dump(mode="json") for row in rows]  # type: ignore[attr-defined]
    return pl.DataFrame(dumped, schema=schema, orient="row")


def _partitions(*, runtime_seconds: float = 1.0, reverse: bool = False):
    first = _passage(1, "HB_GEN_001_001_0001", 1)
    second = _passage(2, "HB_GEN_001_002_0001", 2)
    passages = [first, second]
    memberships = [
        PassageMembershipRow(
            passage_id=first.passage_id,
            token_id=first.start_token_id,
            position_in_passage=1,
            source_position_in_corpus=1,
            source_reference="GEN 1:1",
            source_id="macula-hebrew",
            variant_type=None,
            membership_basis="qere_primary",
            structural_resolution_status="source_native",
            segmentation_run_id="segmentation-fixture",
            corpus="hebrew",
            analysis_profile="edition_complete",
            analysis_reading="qere",
            granularity="verse",
            stream_position_in_corpus=1,
            source_edition_reference="GEN 1:1",
            source_version="fixture",
            locus_id=None,
        ),
        PassageMembershipRow(
            passage_id=second.passage_id,
            token_id=second.start_token_id,
            position_in_passage=1,
            source_position_in_corpus=2,
            source_reference="GEN 1:2",
            source_id="macula-hebrew",
            variant_type=None,
            membership_basis="qere_primary",
            structural_resolution_status="source_native",
            segmentation_run_id="segmentation-fixture",
            corpus="hebrew",
            analysis_profile="edition_complete",
            analysis_reading="qere",
            granularity="verse",
            stream_position_in_corpus=2,
            source_edition_reference="GEN 1:2",
            source_version="fixture",
            locus_id=None,
        ),
    ]
    adjacency = PassageAdjacencyRow(
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        from_passage_id=first.passage_id,
        to_passage_id=second.passage_id,
        source_successor=True,
        analytically_continuous=True,
        reference_gap=False,
        boundary_break=False,
        relation="source_successor",
        reason="fixture",
        segmentation_run_id="segmentation-fixture",
    )
    issue = SegmentationIssueRow(
        issue_id="I_FIXTURE",
        segmentation_run_id="segmentation-fixture",
        severity="informational",
        code="fixture",
        message="fixture",
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        details_json="{}",
    )
    metadata = SegmentationMetadataRow(
        segmentation_run_id="segmentation-fixture",
        segmentation_config_hash=SHA,
        input_source_versions_json="{}",
        input_primary_identity_digests_json="{}",
        input_surface_lemma_digests_json="{}",
        input_analytical_digests_json="{}",
        input_oshb_supplement_digests_json="{}",
        enabled_corpora_json='["hebrew"]',
        analysis_profiles_json='["edition_complete"]',
        analysis_readings_json='["qere"]',
        granularities_json='["verse"]',
        table_counts_json="{}",
        table_logical_hashes_json="{}",
        table_physical_hashes_json="{}",
        processing_environment_json="{}",
        runtime_seconds=runtime_seconds,
        approximate_peak_memory_bytes=1024,
        output_size_bytes=2048,
    )
    if reverse:
        passages.reverse()
        memberships.reverse()
    dimensions = {
        "corpus": "hebrew",
        "analysis_profile": "edition_complete",
        "analysis_reading": "qere",
        "granularity": "verse",
        "book": "GEN",
    }
    return [
        ArtifactPartition("passages", _frame(passages, PASSAGE_POLARS_SCHEMA), **dimensions),
        ArtifactPartition(
            "passage_membership",
            _frame(memberships, PASSAGE_MEMBERSHIP_POLARS_SCHEMA),
            **dimensions,
        ),
        ArtifactPartition(
            "passage_adjacency",
            _frame([adjacency], PASSAGE_ADJACENCY_POLARS_SCHEMA),
            **dimensions,
        ),
        ArtifactPartition(
            "segmentation_exclusions",
            pl.DataFrame(schema=SEGMENTATION_EXCLUSION_POLARS_SCHEMA),
            **dimensions,
        ),
        ArtifactPartition(
            "segmentation_issues",
            _frame([issue], SEGMENTATION_ISSUE_POLARS_SCHEMA),
            **dimensions,
        ),
        ArtifactPartition(
            "segmentation_metadata",
            _frame([metadata], SEGMENTATION_METADATA_POLARS_SCHEMA),
        ),
    ]


def _output(tmp_path: Path) -> Path:
    return tmp_path / "passages" / "schema-v1"


def test_partitioned_round_trip_and_hash_manifest(tmp_path: Path) -> None:
    output = _output(tmp_path)
    processed = write_passage_artifacts(_partitions(), output_dir=output, required_free_bytes=0)

    assert processed.table_counts == {
        "passages": 2,
        "passage_membership": 2,
        "passage_adjacency": 1,
        "segmentation_exclusions": 0,
        "segmentation_issues": 1,
        "segmentation_metadata": 1,
    }
    expected_leaf = (
        output
        / "passages"
        / "corpus=hebrew"
        / "analysis_profile=edition_complete"
        / "analysis_reading=qere"
        / "granularity=verse"
        / "book=GEN"
        / "part-00000.parquet"
    )
    assert expected_leaf.is_file()
    passages = read_artifact_frame(output, "passages")
    assert passages["start_reference"].to_list() == ["GEN 1:1", "GEN 1:2"]
    manifest = read_hash_manifest(output)
    assert manifest["metadata_nondeterministic_columns"] == [
        "approximate_peak_memory_bytes",
        "output_size_bytes",
        "runtime_seconds",
    ]
    assert len(processed.table_logical_hashes["passages"]) == 64
    assert len(processed.file_hashes) == 6


def test_incremental_writer_exposes_content_summary_before_metadata(tmp_path: Path) -> None:
    output = _output(tmp_path)
    partitions = _partitions()
    metadata = partitions.pop()
    with PassageArtifactWriter(output_dir=output, required_free_bytes=0) as writer:
        for partition in partitions:
            writer.write_partition(partition)
        summary = writer.content_summary()
        assert summary.table_counts == {
            "passages": 2,
            "passage_membership": 2,
            "passage_adjacency": 1,
            "segmentation_exclusions": 0,
            "segmentation_issues": 1,
        }
        assert summary.output_size_bytes > 0
        assert len(summary.table_logical_hashes["passage_membership"]) == 64
        processed = writer.finalize(metadata)

    assert processed.table_counts["segmentation_metadata"] == 1


def test_convenience_wrapper_consumes_generator_incrementally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _output(tmp_path)
    partitions = _partitions()
    metadata = partitions.pop()
    original_write = PassageArtifactWriter.write_partition
    writes = 0

    def tracked_write(writer: PassageArtifactWriter, partition: ArtifactPartition) -> None:
        nonlocal writes
        original_write(writer, partition)
        writes += 1

    monkeypatch.setattr(PassageArtifactWriter, "write_partition", tracked_write)

    def generated_partitions():
        for expected_writes, partition in enumerate(partitions):
            assert writes == expected_writes
            yield partition
        assert writes == len(partitions)
        yield metadata

    write_passage_artifacts(generated_partitions(), output_dir=output, required_free_bytes=0)
    assert writes == len(partitions)


def test_refuse_force_and_reordered_input_determinism(tmp_path: Path) -> None:
    output = _output(tmp_path)
    first = write_passage_artifacts(_partitions(), output_dir=output, required_free_bytes=0)
    with pytest.raises(PassageStorageError, match="refusing to overwrite"):
        write_passage_artifacts(_partitions(), output_dir=output, required_free_bytes=0)

    second = write_passage_artifacts(
        _partitions(reverse=True), output_dir=output, force=True, required_free_bytes=0
    )
    assert second.table_logical_hashes == first.table_logical_hashes
    assert second.table_physical_hashes == first.table_physical_hashes
    assert second.file_hashes == first.file_hashes


def test_metadata_telemetry_is_excluded_from_logical_hash(tmp_path: Path) -> None:
    output = _output(tmp_path)
    first = write_passage_artifacts(
        _partitions(runtime_seconds=1.0), output_dir=output, required_free_bytes=0
    )
    second = write_passage_artifacts(
        _partitions(runtime_seconds=9.0),
        output_dir=output,
        force=True,
        required_free_bytes=0,
    )

    assert (
        second.table_logical_hashes["segmentation_metadata"]
        == first.table_logical_hashes["segmentation_metadata"]
    )
    assert (
        second.table_physical_hashes["segmentation_metadata"]
        != first.table_physical_hashes["segmentation_metadata"]
    )


def test_failed_force_promotion_restores_previous_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _output(tmp_path)
    original = write_passage_artifacts(_partitions(), output_dir=output, required_free_bytes=0)
    original_rename = storage_module._rename_path

    def fail_staging_promotion(source: Path, target: Path) -> None:
        if ".writing-" in source.name and target == output.resolve():
            raise OSError("simulated promotion failure")
        original_rename(source, target)

    monkeypatch.setattr(storage_module, "_rename_path", fail_staging_promotion)
    with pytest.raises(OSError, match="simulated promotion failure"):
        write_passage_artifacts(
            _partitions(reverse=True),
            output_dir=output,
            force=True,
            required_free_bytes=0,
        )

    assert read_hash_manifest(output)["table_logical_sha256"] == original.table_logical_hashes
    assert not list(output.parent.glob(".schema-v1.writing-*"))
    assert not list(output.parent.glob(".schema-v1.backup-*"))


def test_path_confinement_and_disk_preflight(tmp_path: Path) -> None:
    with pytest.raises(PassageStorageError, match="must end in schema-v1"):
        write_passage_artifacts(_partitions(), output_dir=tmp_path / "wrong", required_free_bytes=0)
    with pytest.raises(PassageStorageError, match="insufficient disk space"):
        write_passage_artifacts(
            _partitions(),
            output_dir=_output(tmp_path),
            required_free_bytes=10**30,
        )


def test_duckdb_loader_views_helpers_and_transactional_rerun(tmp_path: Path) -> None:
    output = _output(tmp_path)
    processed = write_passage_artifacts(_partitions(), output_dir=output, required_free_bytes=0)
    database = tmp_path / "project_echoes.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE hebrew_tokens AS SELECT 'source-token' AS token_id")
        connection.execute("CREATE TABLE research_notes AS SELECT 'preserve-me' AS note")
        connection.execute("CREATE TABLE passages AS SELECT 'legacy-materialized' AS passage_id")

    load_passage_duckdb(processed, database)
    load_passage_duckdb(processed, database)

    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM passages").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM passage_membership").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM hebrew_tokens").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM research_notes").fetchone() == (1,)
        views = {
            row[0]
            for row in connection.execute(
                "SELECT view_name FROM duckdb_views() WHERE database_name = current_database()"
            ).fetchall()
        }
        assert {
            "passages",
            "passage_membership",
            "passage_adjacency",
            "segmentation_exclusions",
            "segmentation_issues",
            "segmentation_metadata",
            "hebrew_qere_passages",
            "hebrew_ketiv_passages",
            "greek_edition_complete_passages",
            "greek_critical_core_passages",
            "verse_passages",
            "window_passages",
            "passage_token_sequences",
            "passage_uncertainty_summary",
        } <= views
        materialized = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM duckdb_tables() "
                "WHERE database_name = current_database() AND schema_name = 'main'"
            ).fetchall()
        }
        assert materialized == {"hebrew_tokens", "research_notes"}
        assert connection.execute(
            "SELECT count(*) FROM duckdb_indexes() "
            "WHERE table_name IN ('passages', 'passage_membership')"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT len(token_ids) FROM passage_token_sequences ORDER BY passage_id LIMIT 1"
        ).fetchone() == (1,)

    passage_id = _passage(1, "HB_GEN_001_001_0001", 1).passage_id
    passage = read_passage(database, passage_id)
    membership = read_passage_membership(database, passage_id)
    assert passage is not None and passage.start_reference == "GEN 1:1"
    assert [row.token_id for row in membership] == ["HB_GEN_001_001_0001"]
    assert read_passage(database, "P_HB_MISSING~" + "0" * 64) is None
