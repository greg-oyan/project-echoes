"""Deterministic, sanitized Milestone 5 reporting tests."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest
from pydantic import ValidationError

from echoes.reports.passage_segmentation import (
    PassageAcceptanceEvidence,
    PassageDeterminismEvidence,
    PassagePartitionRuntime,
    PassageReportContext,
    PassageReportError,
    PassageSpotCheckEvidence,
    PassageValidationEvidence,
    collect_passage_report_data,
    render_passage_segmentation_report,
    write_passage_segmentation_report,
)
from echoes.segment.models import SegmentationMetadataRow

SHA = "a" * 64
RUN_ID = "passages-v1-fixture"


def _external_view(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    name: str,
    frame: pl.DataFrame,
) -> None:
    path = root / f"{name}.parquet"
    frame.write_parquet(path)
    escaped = path.as_posix().replace("'", "''")
    connection.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{escaped}')")


def _passage_database(tmp_path: Path) -> Path:
    database = tmp_path / "passages.duckdb"
    metadata = SegmentationMetadataRow(
        segmentation_run_id=RUN_ID,
        segmentation_config_hash=SHA,
        input_source_versions_json=json.dumps(
            {"macula-greek": "fixture-g", "macula-hebrew": "fixture-h"},
            sort_keys=True,
        ),
        input_primary_identity_digests_json=json.dumps(
            {"greek": "b" * 64, "hebrew": "c" * 64}, sort_keys=True
        ),
        input_surface_lemma_digests_json=json.dumps(
            {"greek": "d" * 64, "hebrew": "e" * 64}, sort_keys=True
        ),
        input_analytical_digests_json=json.dumps(
            {"greek": "f" * 64, "hebrew": "1" * 64}, sort_keys=True
        ),
        input_oshb_supplement_digests_json=json.dumps({"oshb_kq_tokens": "2" * 64}, sort_keys=True),
        enabled_corpora_json='["hebrew","greek"]',
        analysis_profiles_json='["edition_complete"]',
        analysis_readings_json='["qere","ketiv","source"]',
        granularities_json='["clause","verse"]',
        table_counts_json=json.dumps(
            {
                "passage_membership": 5,
                "passages": 4,
                "segmentation_exclusions": 1,
            },
            sort_keys=True,
        ),
        table_logical_hashes_json=json.dumps(
            {"passage_membership": "3" * 64, "passages": "4" * 64},
            sort_keys=True,
        ),
        table_physical_hashes_json=json.dumps(
            {"passage_membership": "5" * 64, "passages": "6" * 64},
            sort_keys=True,
        ),
        processing_environment_json='{"python":"3.12"}',
        runtime_seconds=12.5,
        approximate_peak_memory_bytes=1024,
        output_size_bytes=4096,
    )
    passages = pl.DataFrame(
        [
            {
                "passage_id": "P_HB_QERE_VERSE_GEN~" + "1" * 64,
                "corpus": "hebrew",
                "analysis_profile": "edition_complete",
                "analysis_reading": "qere",
                "granularity": "verse",
                "book": "GEN",
                "book_order": 1,
                "start_reference": "GEN 1:1",
                "end_reference": "GEN 1:1",
                "reference_sequence_json": '["GEN 1:1"]',
                "start_stream_position_in_corpus": 1,
                "token_count": 1,
                "reference_gap": False,
                "disputed_passage_flag": False,
                "disputed_passage_ids_json": "[]",
                "ketiv_structural_uncertainty": False,
                "sensitivity_exclusion_count": 0,
            },
            {
                "passage_id": "P_HB_KETIV_VERSE_GEN~" + "2" * 64,
                "corpus": "hebrew",
                "analysis_profile": "edition_complete",
                "analysis_reading": "ketiv",
                "granularity": "verse",
                "book": "GEN",
                "book_order": 1,
                "start_reference": "GEN 1:2",
                "end_reference": "GEN 1:2",
                "reference_sequence_json": '["GEN 1:2"]',
                "start_stream_position_in_corpus": 2,
                "token_count": 2,
                "reference_gap": False,
                "disputed_passage_flag": False,
                "disputed_passage_ids_json": "[]",
                "ketiv_structural_uncertainty": True,
                "sensitivity_exclusion_count": 0,
            },
            {
                "passage_id": "P_HB_KETIV_CLAUSE_GEN~" + "3" * 64,
                "corpus": "hebrew",
                "analysis_profile": "edition_complete",
                "analysis_reading": "ketiv",
                "granularity": "clause",
                "book": "GEN",
                "book_order": 1,
                "start_reference": "GEN 1:2",
                "end_reference": "GEN 1:2",
                "reference_sequence_json": '["GEN 1:2"]',
                "start_stream_position_in_corpus": 2,
                "token_count": 1,
                "reference_gap": False,
                "disputed_passage_flag": False,
                "disputed_passage_ids_json": "[]",
                "ketiv_structural_uncertainty": True,
                "sensitivity_exclusion_count": 1,
            },
            {
                "passage_id": "P_GNT_SOURCE_VERSE_MRK~" + "4" * 64,
                "corpus": "greek",
                "analysis_profile": "edition_complete",
                "analysis_reading": "source",
                "granularity": "verse",
                "book": "MRK",
                "book_order": 41,
                "start_reference": "MRK 16:9",
                "end_reference": "MRK 16:9",
                "reference_sequence_json": '["MRK 16:9"]',
                "start_stream_position_in_corpus": 100,
                "token_count": 1,
                "reference_gap": True,
                "disputed_passage_flag": True,
                "disputed_passage_ids_json": '["mark_longer_ending"]',
                "ketiv_structural_uncertainty": False,
                "sensitivity_exclusion_count": 0,
            },
        ]
    )
    memberships = pl.DataFrame(
        [
            {
                "token_id": "HB_GEN_1",
                "corpus": "hebrew",
                "analysis_profile": "edition_complete",
                "analysis_reading": "ketiv",
                "granularity": "verse",
                "structural_resolution_status": "resolved",
            },
            {
                "token_id": "HB_GEN_2",
                "corpus": "hebrew",
                "analysis_profile": "edition_complete",
                "analysis_reading": "ketiv",
                "granularity": "verse",
                "structural_resolution_status": "partially_resolved",
            },
        ]
    )
    exclusions = pl.DataFrame(
        [
            {
                "exclusion_id": "EX_1",
                "corpus": "hebrew",
                "analysis_profile": "edition_complete",
                "analysis_reading": "ketiv",
                "granularity": "clause",
                "token_id": "HB_GEN_2",
                "locus_id": "KQ_GEN_1_2",
                "source_reference": "GEN 1:2",
                "reason_code": "ketiv_clause_mapping_unresolved",
                "resolution_status": "partially_resolved",
                "related_passage_ids_json": "[]",
                "source_id": "oshb-kq",
                "source_version": "fixture",
            }
        ]
    )
    issues = pl.DataFrame([{"severity": "informational", "code": "fixture", "message": "safe"}])
    metadata_frame = pl.DataFrame([metadata.model_dump(mode="python")])
    with duckdb.connect(str(database)) as connection:
        _external_view(connection, tmp_path, "passages", passages)
        _external_view(connection, tmp_path, "passage_membership", memberships)
        _external_view(connection, tmp_path, "segmentation_exclusions", exclusions)
        _external_view(connection, tmp_path, "segmentation_issues", issues)
        _external_view(connection, tmp_path, "segmentation_metadata", metadata_frame)
    return database


def _context(*, logical_hashes_match: bool = True) -> PassageReportContext:
    return PassageReportContext(
        validation=PassageValidationEvidence(
            passed=True,
            error_count=0,
            warning_count=0,
            informational_count=2,
        ),
        determinism=PassageDeterminismEvidence(
            first_run_id=RUN_ID,
            second_run_id=RUN_ID,
            first_runtime_seconds=12.5,
            second_runtime_seconds=12.0,
            first_output_size_bytes=4096,
            second_output_size_bytes=4096,
            run_ids_match=True,
            logical_hashes_match=logical_hashes_match,
            physical_hashes_match=True,
            input_digests_match=True,
        ),
        acceptance_checks=(
            PassageAcceptanceEvidence(
                gate="Passage identity",
                passed=True,
                evidence="IDs reproduced from authoritative membership.",
            ),
        ),
        spot_checks=(
            PassageSpotCheckEvidence(
                check_id="hebrew-genesis",
                category="Genesis narrative",
                reference="GEN 1:1",
                passage_id="P_HB_QERE_VERSE_GEN~" + "1" * 64,
                corpus="hebrew",
                analysis_profile="edition_complete",
                analysis_reading="qere",
                granularity="verse",
                token_count=1,
                membership_count=1,
                verification_sha256="7" * 64,
                source_ids="macula-hebrew",
                disputed_passage=False,
                reference_gap=False,
                ketiv_structural_uncertainty=False,
                exclusion_count=0,
                neighbor_check="passed",
                status="passed",
            ),
        ),
        partition_runtimes=(
            PassagePartitionRuntime(
                corpus="hebrew",
                analysis_profile="edition_complete",
                analysis_reading="qere",
                granularity="verse",
                runtime_seconds=1.25,
            ),
        ),
        known_limitations=("Phrase passages are outside the Milestone 5 scope.",),
        next_recommended_task=(
            "Milestone 6 only: implement the governed known-link benchmark schemas, "
            "importers, evaluation splits, presumed negatives, and metrics."
        ),
    )


def test_collects_deterministic_sanitized_aggregates_from_external_views(
    tmp_path: Path,
) -> None:
    data = collect_passage_report_data(_passage_database(tmp_path))

    assert data.metadata.segmentation_run_id == RUN_ID
    assert data.book_counts.select("book").to_series().to_list() == [
        "MRK",
        "GEN",
        "GEN",
        "GEN",
    ]
    assert data.reference_gap_passages.height == 1
    assert data.disputed_passages.height == 1
    assert data.ketiv_exclusions.height == 1
    assert data.ketiv_resolution_summary.to_dicts() == [
        {"structural_resolution_status": "partially_resolved", "token_count": 1},
        {"structural_resolution_status": "resolved", "token_count": 1},
    ]
    all_columns = {
        column
        for frame in (
            data.book_counts,
            data.reference_gap_passages,
            data.disputed_passages,
            data.ketiv_exclusions,
        )
        for column in frame.columns
    }
    assert not all_columns.intersection(
        {"surface_text", "normalized_text", "lemma_sequence_json", "english_gloss"}
    )


def test_report_and_csv_bundle_are_complete_sanitized_and_deterministic(
    tmp_path: Path,
) -> None:
    data = collect_passage_report_data(_passage_database(tmp_path))
    context = _context()

    report = render_passage_segmentation_report(data, context)
    for heading in (
        "## Objective",
        "## Architecture",
        "## Input digest table",
        "## Full passage counts",
        "### Counts by book",
        "## Passage-length distributions",
        "## Reference-gap analysis",
        "## Disputed-passage analysis",
        "## Ketiv structural-resolution analysis",
        "## Determinism results",
        "## Validation results",
        "## Manual and scripted spot checks",
        "## Acceptance gate",
        "## Exact next recommended task",
    ):
        assert heading in report
    assert "Status: **PASSED**" in report
    assert "surface_text" not in report
    assert "normalized_text" not in report

    output = tmp_path / "reports"
    first = write_passage_segmentation_report(data, context, output)
    first_payloads = {
        path.name: path.read_bytes() for path in (first.report_path, *first.csv_paths)
    }
    second = write_passage_segmentation_report(data, context, output)
    second_payloads = {
        path.name: path.read_bytes() for path in (second.report_path, *second.csv_paths)
    }
    assert first.sha256_by_name == second.sha256_by_name
    assert first_payloads == second_payloads
    assert {path.name for path in first.csv_paths} == {
        "m5-passage-counts.csv",
        "m5-reference-gap-passages.csv",
        "m5-disputed-passages.csv",
        "m5-ketiv-structural-exclusions.csv",
    }
    assert first.report_path.read_bytes().endswith(b"\n")
    assert b"surface_text" not in b"".join(first_payloads.values())


def test_report_status_fails_closed_on_determinism_mismatch(tmp_path: Path) -> None:
    data = collect_passage_report_data(_passage_database(tmp_path))
    context = _context(logical_hashes_match=False)

    assert not context.all_acceptance_gates_passed
    report = render_passage_segmentation_report(data, context)
    assert "Status: **FAILED**" in report
    assert "At least one Milestone 5 acceptance gate remains unmet." in report


def test_spot_check_model_rejects_source_text_fields() -> None:
    payload = _context().spot_checks[0].model_dump()
    payload["surface_text"] = "restricted fixture source text"

    with pytest.raises(ValidationError, match="surface_text"):
        PassageSpotCheckEvidence.model_validate(payload)


def test_missing_persisted_relation_fails_clearly(tmp_path: Path) -> None:
    database = tmp_path / "incomplete.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE passages (passage_id VARCHAR)")

    with pytest.raises(PassageReportError, match="missing required relations"):
        collect_passage_report_data(database)
