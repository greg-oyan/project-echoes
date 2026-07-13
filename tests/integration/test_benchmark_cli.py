"""Focused CLI coverage for Milestone 6 benchmark workflows."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
from typer.testing import CliRunner

import echoes.cli as cli_module
from echoes.benchmarks.pipeline import BenchmarkBuildError
from echoes.benchmarks.validation import (
    BenchmarkValidationIssue,
    BenchmarkValidationReport,
)
from echoes.cli import app

runner = CliRunner()


def _validation(*, passed: bool = True, strict: bool = False) -> BenchmarkValidationReport:
    issues = (
        []
        if passed
        else [
            BenchmarkValidationIssue(
                severity="error",
                code="fixture_failure",
                message="fixture benchmark failed",
                artifact="benchmark_relationships",
            )
        ]
    )
    return BenchmarkValidationReport(
        benchmark_run_id="benchmark-v1-fixture",
        strict=strict,
        table_counts={"benchmark_relationships": 2},
        logical_table_hashes={},
        physical_table_hashes={},
        issues=issues,
        error_count=0 if passed else 1,
        warning_count=0,
        informational_count=0,
        passed=passed,
    )


def test_ingest_benchmark_rejects_unapproved_source() -> None:
    result = runner.invoke(app, ["ingest-benchmark", "--source", "copyrighted-appendix"])

    assert result.exit_code == 1
    assert "only openbible-cross-references is enabled" in result.output


def test_ingest_benchmark_forwards_governed_paths_and_force(
    monkeypatch: Any, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_build(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            benchmark_run_id="benchmark-v1-fixture",
            benchmark_version="known-links-v1-fixture",
            storage=SimpleNamespace(table_counts={"benchmark_relationships": 2}),
            mapping_status_counts={"mapped_provisional": 4},
            split_counts={"held_out_book|train": 2},
            negative_counts={"length_matched_random_unlinked": 1},
            database_path=tmp_path / "benchmark.duckdb",
        )

    monkeypatch.setattr(cli_module, "build_benchmark", fake_build)
    result = runner.invoke(
        app,
        [
            "ingest-benchmark",
            "--source",
            "OpenBible",
            "--output-dir",
            str(tmp_path / "benchmark-output"),
            "--database",
            str(tmp_path / "benchmark.duckdb"),
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["force"] is True
    assert captured["output_root"] == tmp_path / "benchmark-output"
    assert "Generated benchmark run benchmark-v1-fixture" in result.output


def test_ingest_benchmark_reports_pipeline_failure(monkeypatch: Any) -> None:
    def fail_build(**_: object) -> None:
        raise BenchmarkBuildError("snapshot hash mismatch")

    monkeypatch.setattr(cli_module, "build_benchmark", fail_build)
    result = runner.invoke(app, ["ingest-benchmark"])

    assert result.exit_code == 1
    assert "snapshot hash mismatch" in result.output


def test_validate_benchmarks_requires_all() -> None:
    result = runner.invoke(app, ["validate-benchmarks"])

    assert result.exit_code == 1
    assert "select --all" in result.output


def test_validate_benchmarks_writes_json_report(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli_module,
        "validate_benchmark_artifacts",
        lambda **kwargs: _validation(strict=bool(kwargs["strict"])),
    )
    report = tmp_path / "reports" / "benchmark.json"
    result = runner.invoke(
        app,
        ["validate-benchmarks", "--all", "--strict", "--json", "--report", str(report)],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["benchmark_run_id"] == "benchmark-v1-fixture"
    assert json.loads(report.read_text(encoding="utf-8"))["strict"] is True


def test_validate_benchmarks_returns_nonzero_for_errors(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        cli_module,
        "validate_benchmark_artifacts",
        lambda **_: _validation(passed=False),
    )
    result = runner.invoke(app, ["validate-benchmarks", "--all"])

    assert result.exit_code == 1
    assert "errors=1" in result.output
    assert "fixture_failure" in result.output


def test_validate_tier1_quotations_uses_governed_header() -> None:
    result = runner.invoke(app, ["validate-tier1-quotations", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["row_count"] == 0
    assert payload["header_only"] is True


def test_stage_verification_requires_all_and_force_does_not_bypass_failure(
    monkeypatch: Any,
) -> None:
    missing_all = runner.invoke(app, ["generate-benchmark-splits"])
    assert missing_all.exit_code == 1
    assert "select --all" in missing_all.output

    monkeypatch.setattr(
        cli_module,
        "validate_benchmark_artifacts",
        lambda **_: _validation(passed=False, strict=True),
    )
    monkeypatch.setattr(
        cli_module,
        "table_row_counts",
        lambda _: {"benchmark_split_assignments": 2},
    )
    forced = runner.invoke(app, ["generate-benchmark-splits", "--all", "--force"])

    assert forced.exit_code == 1
    assert "does not pass strict validation" in forced.output


def test_stage_verification_reports_split_and_negative_counts(monkeypatch: Any) -> None:
    validation = _validation(strict=True)
    counts = {
        "benchmark_split_assignments": 10,
        "benchmark_presumed_negatives": 4,
    }
    monkeypatch.setattr(
        cli_module,
        "_verify_generated_benchmark_stage",
        lambda **_: (validation, counts),
    )

    splits = runner.invoke(app, ["generate-benchmark-splits", "--all", "--force"])
    negatives = runner.invoke(app, ["generate-presumed-negatives", "--all"])

    assert splits.exit_code == 0, splits.output
    assert "rows=10" in splits.output
    assert "--force acknowledged after all gates" in splits.output
    assert negatives.exit_code == 0, negatives.output
    assert "rows=4" in negatives.output


def test_benchmark_summary_requires_all_and_supports_json(monkeypatch: Any) -> None:
    missing_all = runner.invoke(app, ["benchmark-summary"])
    assert missing_all.exit_code == 1

    payload = {
        "metadata": {
            "benchmark_run_id": "benchmark-v1-fixture",
            "benchmark_version": "known-links-v1-fixture",
        },
        "table_counts": {"benchmark_relationships": 2},
        "relationships_by_tier_and_source": [],
        "mappings_by_profile_and_status": [],
        "splits_by_strategy_and_partition": [],
        "presumed_negatives_by_strategy": [],
    }
    monkeypatch.setattr(cli_module, "_benchmark_summary_payload", lambda _: payload)
    result = runner.invoke(app, ["benchmark-summary", "--all", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["metadata"]["benchmark_run_id"] == "benchmark-v1-fixture"


def _relationship_details() -> dict[str, object]:
    return {
        "relationship": {
            "relationship_id": "BR_fixture",
            "source_reference_a": "Gen.1.1",
            "source_reference_b": "John.1.1",
            "relationship_direction": "from_to",
            "tier": 3,
            "relationship_class": "broad_cross_reference",
            "source_weight_sum": 2,
            "source_weight_max": 2,
            "weak_supervision_eligible": True,
            "knownness_filter_eligible": True,
            "primary_evaluation_eligible": False,
            "tier1_eligible": False,
            "provenance_json": "{}",
        },
        "source_records": [
            {
                "source_record_id": "BSR_fixture",
                "source_file": "cross_references.txt",
                "source_line_number": 2,
                "source_weight": 2,
                "parse_status": "parsed",
                "raw_record_sha256": "a" * 64,
            }
        ],
        "endpoints": [{"endpoint_id": "BE_fixture"}],
        "endpoint_mappings": [
            {
                "target_analysis_profile": "edition_complete",
                "target_corpus": "hebrew",
                "mapping_status": "mapped_provisional",
                "mapping_confidence": "provisional_mechanical",
                "mapping_method": "same_label_extant_reference",
                "reference_gap": False,
                "disputed_passage_flag": False,
                "target_passage_ids_json": '["P_fixture"]',
                "ambiguity_reason": "same-label provisional mapping",
            }
        ],
        "leakage_groups": [],
        "split_assignments": [],
        "related_presumed_negatives": [],
    }


def test_show_relationship_and_mapping_success_and_missing(monkeypatch: Any) -> None:
    details = _relationship_details()
    monkeypatch.setattr(cli_module, "_relationship_details", lambda *_: details)
    monkeypatch.setattr(
        cli_module,
        "_mapping_details",
        lambda *_: {
            "relationship_id": "BR_fixture",
            "source_reference_a": "Gen.1.1",
            "source_reference_b": "John.1.1",
            "endpoints": details["endpoints"],
            "endpoint_mappings": details["endpoint_mappings"],
        },
    )

    shown = runner.invoke(app, ["show-relationship", "BR_fixture"])
    mapped = runner.invoke(app, ["show-benchmark-mapping", "BR_fixture"])

    assert shown.exit_code == 0, shown.output
    assert "Tier: 3" in shown.output
    assert "primary_evaluation=False" in shown.output
    assert mapped.exit_code == 0, mapped.output
    assert "status=mapped_provisional" in mapped.output

    monkeypatch.setattr(cli_module, "_relationship_details", lambda *_: None)
    missing = runner.invoke(app, ["show-relationship", "BR_missing"])
    assert missing.exit_code == 1
    assert "not found" in missing.output


def test_relationship_detail_query_joins_all_evidence_tables(tmp_path: Path) -> None:
    database = tmp_path / "benchmark.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE benchmark_relationships AS SELECT 'BR_fixture' AS relationship_id, "
            "'Gen.1.1' AS source_reference_a, 'John.1.1' AS source_reference_b"
        )
        connection.execute(
            "CREATE TABLE benchmark_relationship_source_records AS SELECT "
            "'BR_fixture' AS relationship_id, 'BSR_fixture' AS source_record_id, "
            "'supporting_record' AS link_role"
        )
        connection.execute(
            "CREATE TABLE benchmark_source_records AS SELECT 'BSR_fixture' AS source_record_id, "
            "'cross_references.txt' AS source_file, 2::BIGINT AS source_line_number"
        )
        connection.execute(
            "CREATE TABLE benchmark_endpoints AS SELECT 'BE_fixture' AS endpoint_id, "
            "'BR_fixture' AS relationship_id, 'a' AS endpoint_side"
        )
        connection.execute(
            "CREATE TABLE benchmark_endpoint_mappings AS SELECT 'BM_fixture' AS mapping_id, "
            "'BE_fixture' AS endpoint_id, 'edition_complete' AS target_analysis_profile"
        )
        connection.execute(
            "CREATE TABLE benchmark_leakage_groups AS SELECT 'BLG_fixture' AS "
            "leakage_group_id, 'BR_fixture' AS relationship_id, "
            "'exact_unordered_pair' AS group_type"
        )
        connection.execute(
            "CREATE TABLE benchmark_split_assignments AS SELECT 'BR_fixture' AS "
            "relationship_id, 'held_out_book' AS split_strategy"
        )
        connection.execute(
            "CREATE TABLE benchmark_presumed_negatives AS SELECT 'BC_fixture' AS "
            "contrastive_id, 'length_matched_random_unlinked' AS negative_strategy, "
            "'P_fixture' AS passage_a_id, 'P_other' AS passage_b_id"
        )
        connection.execute(
            "CREATE TABLE benchmark_mapping_target_passages AS SELECT 'BM_fixture' AS "
            "mapping_id, 'BE_fixture' AS endpoint_id, 'P_fixture' AS target_passage_id"
        )

    details = cli_module._relationship_details(database, "BR_fixture")

    assert details is not None
    assert len(details["source_records"]) == 1
    assert len(details["endpoint_mappings"]) == 1
    assert len(details["leakage_groups"]) == 1
    assert len(details["split_assignments"]) == 1
    assert len(details["related_presumed_negatives"]) == 1
