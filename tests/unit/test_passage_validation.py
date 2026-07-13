"""Synthetic persisted-artifact validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

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
    PassageRow,
    SegmentationIssueRow,
    SegmentationMetadataRow,
)
from echoes.segment.storage import (
    ArtifactPartition,
    PassageArtifactWriter,
    load_passage_duckdb,
)
from echoes.segment.validation import (
    _membership_groups,
    _SemanticIndex,
    _State,
    _validate_exclusions,
    validate_passage_artifacts,
)

SHA = "a" * 64
RUN_ID = "passages-v1-synthetic"


def _empty(schema: pl.Schema, columns: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema).select(columns)


def _passage_and_membership() -> tuple[pl.DataFrame, pl.DataFrame]:
    identity = build_passage_identity(
        payload_from_membership(
            corpus="hebrew",
            analysis_profile="edition_complete",
            analysis_reading="qere",
            granularity="verse",
            book="GEN",
            source_unit_id=None,
            members=[IdentityMember("HB_GEN_001_001_0001", 1, "GEN 1:1")],
        )
    )
    passage = PassageRow(
        passage_id=identity.passage_id,
        identity_payload_sha256=identity.payload_sha256,
        segmentation_run_id=RUN_ID,
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        book="GEN",
        book_order=1,
        start_reference="GEN 1:1",
        end_reference="GEN 1:1",
        reference_sequence_json='["GEN 1:1"]',
        token_ids_json='["HB_GEN_001_001_0001"]',
        constituent_verse_passage_ids_json="[]",
        start_token_id="HB_GEN_001_001_0001",
        end_token_id="HB_GEN_001_001_0001",
        start_stream_position_in_corpus=1,
        end_stream_position_in_corpus=1,
        token_count=1,
        visible_token_count=1,
        zero_width_token_count=0,
        punctuation_token_count=0,
        word_count=1,
        sentence_count=1,
        clause_count=1,
        source_ids_json='["macula-hebrew"]',
        source_versions_json='["fixture"]',
        surface_text="\u05d0",
        normalized_text="\u05d0",
        unpointed_text="\u05d0",
        lemma_sequence_json="[null]",
        root_sequence_json="[null]",
        part_of_speech_sequence_json="[null]",
        semantic_domain_sequence_json="[null]",
        entity_ids_json="[null]",
        participant_ids_json="[null]",
        disputed_passage_flag=False,
        disputed_passage_ids_json="[]",
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        profile_truncated=False,
        sensitivity_exclusion_count=0,
        overlap_with_previous_token_count=0,
        overlap_with_next_token_count=0,
        segmentation_config_hash=SHA,
    )
    passages = pl.DataFrame(
        [passage.model_dump(mode="python")], schema=PASSAGE_POLARS_SCHEMA, orient="row"
    ).select(PASSAGE_COLUMNS)
    membership = pl.DataFrame(
        [
            {
                "passage_id": identity.passage_id,
                "token_id": "HB_GEN_001_001_0001",
                "position_in_passage": 1,
                "source_position_in_corpus": 1,
                "source_reference": "GEN 1:1",
                "source_id": "macula-hebrew",
                "variant_type": None,
                "membership_basis": "qere_primary",
                "structural_resolution_status": "source_native",
                "segmentation_run_id": RUN_ID,
                "corpus": "hebrew",
                "analysis_profile": "edition_complete",
                "analysis_reading": "qere",
                "granularity": "verse",
                "stream_position_in_corpus": 1,
                "source_edition_reference": "GEN 1:1",
                "source_version": "fixture",
                "locus_id": None,
            }
        ],
        schema=PASSAGE_MEMBERSHIP_POLARS_SCHEMA,
        orient="row",
    ).select(PASSAGE_MEMBERSHIP_COLUMNS)
    return passages, membership


def _write_fixture(output_dir: Path, *, warning: bool = False):
    passages, membership = _passage_and_membership()
    issue_frame = _empty(SEGMENTATION_ISSUE_POLARS_SCHEMA, SEGMENTATION_ISSUE_COLUMNS)
    if warning:
        issue = SegmentationIssueRow(
            issue_id="I_SYNTHETIC",
            segmentation_run_id=RUN_ID,
            severity="warning",
            code="synthetic-warning",
            message="synthetic warning",
            corpus="hebrew",
            analysis_profile="edition_complete",
            analysis_reading="qere",
            granularity="verse",
            details_json="{}",
        )
        issue_frame = pl.DataFrame(
            [issue.model_dump(mode="python")],
            schema=SEGMENTATION_ISSUE_POLARS_SCHEMA,
            orient="row",
        ).select(SEGMENTATION_ISSUE_COLUMNS)
    context = {
        "corpus": "hebrew",
        "analysis_profile": "edition_complete",
        "analysis_reading": "qere",
        "granularity": "verse",
        "book": "GEN",
    }
    with PassageArtifactWriter(output_dir=output_dir, required_free_bytes=0) as writer:
        writer.write_partition(ArtifactPartition("passages", passages, **context))
        writer.write_partition(ArtifactPartition("passage_membership", membership, **context))
        writer.write_partition(
            ArtifactPartition(
                "passage_adjacency",
                _empty(PASSAGE_ADJACENCY_POLARS_SCHEMA, PASSAGE_ADJACENCY_COLUMNS),
                **context,
            )
        )
        writer.write_partition(
            ArtifactPartition(
                "segmentation_exclusions",
                _empty(SEGMENTATION_EXCLUSION_POLARS_SCHEMA, SEGMENTATION_EXCLUSION_COLUMNS),
                **context,
            )
        )
        writer.write_partition(ArtifactPartition("segmentation_issues", issue_frame, **context))
        summary = writer.content_summary()
        metadata = SegmentationMetadataRow(
            segmentation_run_id=RUN_ID,
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
            table_counts_json=json.dumps(summary.table_counts, sort_keys=True),
            table_logical_hashes_json=json.dumps(summary.table_logical_hashes, sort_keys=True),
            table_physical_hashes_json=json.dumps(summary.table_physical_hashes, sort_keys=True),
            processing_environment_json="{}",
            runtime_seconds=0.0,
            output_size_bytes=summary.output_size_bytes,
        )
        metadata_frame = pl.DataFrame(
            [metadata.model_dump(mode="python")],
            schema=SEGMENTATION_METADATA_POLARS_SCHEMA,
            orient="row",
        ).select(SEGMENTATION_METADATA_COLUMNS)
        return writer.finalize(ArtifactPartition("segmentation_metadata", metadata_frame))


def test_valid_artifacts_and_duckdb_agree(tmp_path: Path) -> None:
    processed = _write_fixture(tmp_path / "schema-v1")
    database = tmp_path / "passages.duckdb"
    load_passage_duckdb(processed, database)

    report = validate_passage_artifacts(processed.output_dir, database_path=database)

    assert report.passed
    assert report.exit_code == 0
    assert report.error_count == 0
    assert report.segmentation_run_id == RUN_ID
    assert report.table_counts["passages"] == 1
    assert report.table_counts["passage_membership"] == 1


def test_membership_tampering_fails_hash_identity_and_sequence_checks(tmp_path: Path) -> None:
    processed = _write_fixture(tmp_path / "schema-v1")
    path = next((processed.output_dir / "passage_membership").rglob("*.parquet"))
    changed = pl.read_parquet(path).with_columns(pl.lit("HB_GEN_001_001_9999").alias("token_id"))
    changed.write_parquet(path)

    report = validate_passage_artifacts(processed.output_dir)
    codes = {issue.code for issue in report.issues}

    assert not report.passed
    assert report.exit_code == 1
    assert "parquet-mismatch" in codes
    assert "membership-token-sequence" in codes
    assert "passage-identity" in codes


def test_schema_drift_returns_a_report_instead_of_crashing(tmp_path: Path) -> None:
    processed = _write_fixture(tmp_path / "schema-v1")
    path = next((processed.output_dir / "passages").rglob("*.parquet"))
    pl.read_parquet(path).drop("surface_text").write_parquet(path)

    report = validate_passage_artifacts(processed.output_dir)

    assert not report.passed
    assert any(issue.code == "schema-columns" for issue in report.issues)


def test_strict_mode_promotes_persisted_warnings_to_failure(tmp_path: Path) -> None:
    processed = _write_fixture(tmp_path / "schema-v1", warning=True)

    normal = validate_passage_artifacts(processed.output_dir)
    strict = validate_passage_artifacts(processed.output_dir, strict=True)

    assert normal.passed
    assert normal.warning_count == 1
    assert not strict.passed
    assert strict.warning_count == 1


def test_membership_leaf_is_indexed_once_by_passage_id() -> None:
    frame = pl.DataFrame(
        {
            "passage_id": ["P2", "P1", "P2"],
            "position_in_passage": [1, 1, 2],
        }
    )

    groups = _membership_groups(frame)

    assert set(groups) == {"P1", "P2"}
    assert groups["P1"]["position_in_passage"].to_list() == [1]
    assert groups["P2"]["position_in_passage"].to_list() == [1, 2]


def test_exclusion_coverage_is_scoped_to_persisted_stream_and_book(tmp_path: Path) -> None:
    processed = _write_fixture(tmp_path / "schema-v1")
    passage_path = next((processed.output_dir / "passages").rglob("*.parquet"))
    passage_id = str(pl.read_parquet(passage_path).item(0, "passage_id"))
    selected_stream = pl.DataFrame(
        {
            "book": ["GEN"],
            "token_id": ["HB_GEN_001_001_0001"],
            "analysis_clause_id": ["C1"],
        }
    )
    absent_stream = pl.DataFrame(
        {
            "book": ["MRK"],
            "token_id": ["G_MRK_001_001_0001"],
            "analysis_clause_id": [None],
        }
    )
    state = _State(processed.output_dir, False, [], {}, {}, {})

    _validate_exclusions(
        state,
        {
            ("hebrew", "edition_complete", "qere"): selected_stream,
            ("greek", "critical_core", "source"): absent_stream,
        },
        _SemanticIndex({passage_id}, {}),
    )

    assert not any(finding.code == "clause-exclusion-coverage" for finding in state.findings)
