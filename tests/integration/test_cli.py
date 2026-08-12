"""CLI integration tests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import polars as pl
from rich.text import Text
from typer.testing import CliRunner

import echoes.cli as cli_module
from echoes.cli import app
from echoes.lexical.config import (
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
)
from echoes.lexical.models import (
    LEXICAL_ARTIFACT_NAMES,
    LEXICAL_ARTIFACT_SCHEMAS,
    LEXICAL_METADATA_SCHEMA,
)
from echoes.lexical.storage import LexicalArtifactWriter
from echoes.lexical.validation import LexicalValidationReport
from echoes.manifest import (
    ExperimentExecutionManifest,
    ResumeLineage,
    write_execution_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _named_hash(values: dict[str, str]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_lexical_run(tmp_path: Path) -> Path:
    root = tmp_path / "lexical" / "schema-v1"
    config = load_lexical_config()
    preregistration = load_lexical_preregistration()
    with LexicalArtifactWriter(root, duckdb_memory_limit_bytes=128 * 1024**2) as writer:
        for name in LEXICAL_ARTIFACT_NAMES:
            if name != "lexical_metadata":
                writer.write_frame(name, pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]))
        logical, physical = writer.content_hashes()
        metadata = pl.DataFrame(
            [
                {
                    "experiment_run_id": "cli-fixture",
                    "experiment_version": config.experiment_version,
                    "lexical_schema_version": 1,
                    "candidate_pair_schema_version": 1,
                    "configuration_hash": lexical_config_sha256(config),
                    "preregistration_hash": lexical_preregistration_sha256(preregistration),
                    "input_corpus_hashes_json": _canonical({}),
                    "passage_hashes_json": _canonical({}),
                    "benchmark_hashes_json": _canonical({}),
                    "feature_vocabulary_hashes_json": _canonical({}),
                    "sparse_index_hashes_json": _canonical({}),
                    "table_logical_hashes_json": _canonical(logical),
                    "table_physical_hashes_json": _canonical(physical),
                    "ranking_count": 0,
                    "candidate_count": 0,
                    "null_iteration_count": 0,
                    "evaluation_count": 0,
                    "runtime_seconds": 0.0,
                    "stage_runtime_seconds_json": _canonical({"fixture": 0.0}),
                    "peak_memory_bytes": 1,
                    "storage_footprint_bytes": 1,
                    "numerical_environment_json": _canonical({"fixture": True}),
                    "thread_controls_json": _canonical({"threads": 1}),
                    "acceptance_status": "implementation_test",
                    "notes": "legally safe empty CLI fixture",
                }
            ],
            schema=LEXICAL_METADATA_SCHEMA,
            orient="row",
        )
        writer.finalize(metadata)
    return root


def _write_cli_execution_manifest(
    manifest_root: Path,
    *,
    execution_id: str,
    timestamp: datetime,
    database: str,
) -> ExperimentExecutionManifest:
    run_id = "lexical-v1-cli-fixture"
    configuration_hashes = {"lexical_yaml": "4" * 64}
    manifest = ExperimentExecutionManifest(
        execution_id=execution_id,
        execution_status="succeeded",
        run_id=run_id,
        experiment_name="m7-lexical-baseline",
        experiment_version="m7-lexical-baseline-v1",
        timestamp=timestamp,
        completed_at=timestamp,
        git_commit="fixture-commit",
        working_tree_status="clean",
        working_tree_status_sha256="0" * 64,
        source_tree_hash="1" * 64,
        python_version="3.12.0",
        runtime_versions={"fixture": "1.0"},
        dependency_lock_hash="2" * 64,
        config_hash=_named_hash(configuration_hashes),
        configuration_files={"lexical_yaml": "config/lexical.yaml"},
        configuration_hashes=configuration_hashes,
        dataset_manifest_path="data/manifests/sources.yaml",
        dataset_manifest_hash="5" * 64,
        source_file_hashes={"fixture:source.txt": "b" * 64},
        dataset_versions={"source:fixture": "fixture-v1"},
        random_seed=7201,
        random_seeds={
            "bootstrap": 7201,
            "frequency_preserving_synthetic": 7102,
            "within_book_reassignment": 7101,
        },
        model_names=[],
        model_versions={},
        model_status="not_applicable_no_learned_models",
        input_table_hashes={"fixture:input": "6" * 64},
        output_table_hashes={"fixture:output": "7" * 64},
        output_table_physical_hashes={"fixture:output": "8" * 64},
        output_hash_manifest_sha256="9" * 64,
        runtime=1.0,
        stage_runtime_seconds={"total": 1.0},
        hardware_summary={"system": "fixture"},
        exact_candidate_generation_method="frozen_m7_fixture",
        training_data_lineage="not_applicable_no_model_training",
        evaluation_split_lineage={"fixture:split": "a" * 64},
        human_review_history="not_started_milestone_8",
        artifact_output_directory="data/processed/lexical/schema-v1",
        resume_lineage=ResumeLineage(
            requested_staging_directory=None,
            status="not_requested",
            recovered_composite=False,
            validated_artifact_part_hashes={},
            validated_checkpoint_manifest_hashes={},
            validated_checkpoint_part_hashes={},
        ),
        reproduction_command=[
            "uv",
            "run",
            "echoes",
            "run-lexical-pipeline",
            "--primary",
            "--database",
            database,
            "--output-dir",
            "data/processed/lexical/schema-v1",
        ],
        warnings=[],
        errors=[],
        limitations=[],
    )
    path = manifest_root / run_id / f"{execution_id}.json"
    write_execution_manifest(manifest, path)
    return manifest


def test_cli_help_runs() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "validate-config" in result.stdout
    assert "validate-sources" in result.stdout
    assert "list-sources" in result.stdout
    assert "show-source" in result.stdout
    assert "acquire-source" in result.stdout
    assert "verify-acquisition" in result.stdout
    assert "ingest-hebrew" in result.stdout
    assert "validate-corpus" in result.stdout
    assert "corpus-summary" in result.stdout
    assert "audit-lexical-features" in result.stdout
    assert "recover-lexical-promotion" in result.stdout
    assert "build-lexical-index" in result.stdout
    assert "run-lexical-baseline" in result.stdout
    assert "run-lexical-null-models" in result.stdout
    assert "evaluate-lexical-baseline" in result.stdout
    assert "build-lexical-review-queue" in result.stdout
    assert "validate-lexical" in result.stdout
    assert "lexical-summary" in result.stdout
    assert "show-lexical-candidate" in result.stdout
    assert "show-lexical-evidence" in result.stdout
    assert "compare-lexical-ablation" in result.stdout
    assert "create-run-manifest" in result.stdout


def test_cli_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_lexical_validation_exposes_determinism_reference() -> None:
    result = runner.invoke(app, ["validate-lexical", "--help"])

    assert result.exit_code == 0
    assert "--determinism-reference-root" in Text.from_ansi(result.stdout).plain


def test_lexical_promotion_recovery_cli_reports_machine_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "recover_interrupted_lexical_promotion",
        lambda output_dir, database: "staging_restored",
    )
    result = runner.invoke(
        app,
        [
            "recover-lexical-promotion",
            "--database",
            str(tmp_path / "project_echoes.duckdb"),
            "--output-dir",
            str(tmp_path / "lexical" / "schema-v1"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "state": "staging_restored",
        "canonical_output_present": False,
    }


def test_recovery_finalizer_retry_uses_the_archived_commit_witness(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "lexical" / "schema-v1"
    output.mkdir(parents=True)
    database = tmp_path / "project_echoes.duckdb"
    manifest_root = tmp_path / "execution-manifests"
    manifest = _write_cli_execution_manifest(
        manifest_root,
        execution_id="execution-archived",
        timestamp=datetime.now(tz=UTC),
        database=str(database),
    )
    manifest_path = manifest_root / manifest.run_id / f"{manifest.execution_id}.json"
    validation = LexicalValidationReport(
        output_dir=str(output.resolve()),
        experiment_run_id=manifest.run_id,
        experiment_version=manifest.experiment_version,
        configuration_hash=None,
        preregistration_hash=None,
        strict=True,
        table_counts={"fixture:output": 1},
        table_logical_hashes=manifest.output_table_hashes,
        table_physical_hashes=manifest.output_table_physical_hashes,
        scientific_gate_passed=True,
        insufficient_primary_strata=[],
        issues=[],
        error_count=0,
        warning_count=0,
        informational_count=0,
        passed=True,
    )
    validation_path = tmp_path / "strict-validation.json"
    validation_path.write_text(validation.model_dump_json(indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        cli_module,
        "recover_interrupted_lexical_promotion",
        lambda output_dir, database_path, *, archive_committed=False: "canonical_committed",
    )
    monkeypatch.setattr(
        cli_module,
        "read_current_lexical_promotion_witness",
        lambda output_dir, database_path: SimpleNamespace(
            execution_manifest_path=manifest_path,
            execution_id=manifest.execution_id,
        ),
    )

    result = runner.invoke(
        app,
        [
            "finalize-lexical-promotion-recovery",
            "--validation-report",
            str(validation_path),
            "--service-result",
            "success",
            "--database",
            str(database),
            "--output-dir",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["state"] == "canonical_committed"
    assert payload["prior_execution_status"] == "succeeded"
    assert payload["execution_status"] == "succeeded"
    assert payload["active_journal_present"] is False


def test_cli_validates_project_configuration() -> None:
    result = runner.invoke(
        app,
        ["validate-config", "--config-dir", str(PROJECT_ROOT / "config")],
    )

    assert result.exit_code == 0
    assert "Validated 17 configuration files" in result.stdout


def test_cli_reports_invalid_configuration(tmp_path: Path) -> None:
    (tmp_path / "corpora.yaml").write_text(
        "schema_version: 1\ncorpora: invalid\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate-config", "--config-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "Configuration validation failed" in result.output
    assert "corpora.yaml" in result.output


def test_cli_creates_run_manifest(tmp_path: Path) -> None:
    output = tmp_path / "run-manifest.json"
    result = runner.invoke(
        app,
        [
            "create-run-manifest",
            "--experiment-name",
            "integration smoke",
            "--config-dir",
            str(PROJECT_ROOT / "config"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["experiment_name"] == "integration smoke"
    assert payload["errors"] == []
    assert set(payload) == {
        "run_id",
        "experiment_name",
        "timestamp",
        "git_commit",
        "working_tree_status",
        "python_version",
        "dependency_lock_hash",
        "config_hash",
        "dataset_manifest_hash",
        "dataset_versions",
        "random_seed",
        "model_names",
        "model_versions",
        "input_table_hashes",
        "output_table_hashes",
        "runtime",
        "hardware_summary",
        "warnings",
        "errors",
    }


def test_reproduce_is_dry_run_by_default_and_selects_exact_execution(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    manifest_root = tmp_path / "execution-manifests"
    timestamp = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    first = _write_cli_execution_manifest(
        manifest_root,
        execution_id="execution-first",
        timestamp=timestamp,
        database="data/processed/first.duckdb",
    )
    second = _write_cli_execution_manifest(
        manifest_root,
        execution_id="execution-second",
        timestamp=timestamp + timedelta(seconds=1),
        database="data/processed/second.duckdb",
    )

    def forbid_execution(*args: object, **kwargs: object) -> object:
        raise AssertionError("dry-run reproduce must not spawn a process")

    monkeypatch.setattr(cli_module.subprocess, "run", forbid_execution)
    latest = runner.invoke(
        app,
        [
            "reproduce",
            first.run_id,
            "--manifest-root",
            str(manifest_root),
        ],
    )
    exact = runner.invoke(
        app,
        [
            "reproduce",
            first.run_id,
            "--execution-id",
            first.execution_id,
            "--manifest-root",
            str(manifest_root),
        ],
    )

    assert latest.exit_code == 0
    assert second.execution_id in latest.output
    assert "data/processed/second.duckdb" in latest.output
    assert "Dry run only" in latest.output
    assert exact.exit_code == 0
    assert first.execution_id in exact.output
    assert "data/processed/first.duckdb" in exact.output


def test_validate_run_manifest_surfaces_output_hash_disagreement(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    manifest_root = tmp_path / "execution-manifests"
    manifest = _write_cli_execution_manifest(
        manifest_root,
        execution_id="execution-validation",
        timestamp=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        database="data/processed/project_echoes.duckdb",
    )
    monkeypatch.setattr(
        cli_module,
        "reproduction_environment_mismatches",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        cli_module,
        "validate_execution_manifest_outputs",
        lambda *args, **kwargs: ["execution manifest disagrees with table_logical_sha256"],
    )

    result = runner.invoke(
        app,
        [
            "validate-run-manifest",
            manifest.run_id,
            "--execution-id",
            manifest.execution_id,
            "--manifest-root",
            str(manifest_root),
        ],
    )

    assert result.exit_code == 1
    assert "Run-manifest validation failed" in result.output
    assert "disagrees with table_logical_sha256" in result.output


def test_validate_run_manifest_forwards_archived_artifact_root(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    manifest_root = tmp_path / "execution-manifests"
    archived_root = tmp_path / "m7-first-run-reference"
    manifest = _write_cli_execution_manifest(
        manifest_root,
        execution_id="execution-archived-validation",
        timestamp=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        database="data/processed/project_echoes.duckdb",
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        cli_module,
        "reproduction_environment_mismatches",
        lambda *args, **kwargs: [],
    )

    def validate_outputs(*args: object, **kwargs: object) -> list[str]:
        observed["artifact_root"] = kwargs.get("artifact_root")
        return []

    monkeypatch.setattr(
        cli_module,
        "validate_execution_manifest_outputs",
        validate_outputs,
    )
    result = runner.invoke(
        app,
        [
            "validate-run-manifest",
            manifest.run_id,
            "--execution-id",
            manifest.execution_id,
            "--manifest-root",
            str(manifest_root),
            "--artifact-root",
            str(archived_root),
        ],
    )

    assert result.exit_code == 0
    assert observed["artifact_root"] == archived_root


def test_validate_run_manifest_surfaces_nonfatal_git_provenance_notice(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    manifest_root = tmp_path / "execution-manifests"
    manifest = _write_cli_execution_manifest(
        manifest_root,
        execution_id="execution-git-notice",
        timestamp=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        database="data/processed/project_echoes.duckdb",
    )

    def environment_check(
        *args: object,
        notices: list[str] | None = None,
        **kwargs: object,
    ) -> list[str]:
        if notices is not None:
            notices.append("git_commit differs; governed executable inputs still match")
        return []

    monkeypatch.setattr(
        cli_module,
        "reproduction_environment_mismatches",
        environment_check,
    )
    monkeypatch.setattr(
        cli_module,
        "validate_execution_manifest_outputs",
        lambda *args, **kwargs: [],
    )
    result = runner.invoke(
        app,
        [
            "validate-run-manifest",
            manifest.run_id,
            "--manifest-root",
            str(manifest_root),
        ],
    )

    assert result.exit_code == 0
    assert "Provenance notice: git_commit differs" in result.output


def test_reproduce_execute_rejects_database_outside_governed_project_data(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    manifest_root = tmp_path / "execution-manifests"
    manifest = _write_cli_execution_manifest(
        manifest_root,
        execution_id="execution-unsafe-database",
        timestamp=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        database="../outside.duckdb",
    )
    monkeypatch.setattr(
        cli_module,
        "reproduction_environment_mismatches",
        lambda *args, **kwargs: [],
    )

    def forbid_execution(*args: object, **kwargs: object) -> object:
        raise AssertionError("unsafe reproduction path must not spawn a process")

    monkeypatch.setattr(cli_module.subprocess, "run", forbid_execution)
    result = runner.invoke(
        app,
        [
            "reproduce",
            manifest.run_id,
            "--execution-id",
            manifest.execution_id,
            "--manifest-root",
            str(manifest_root),
            "--execute",
        ],
    )

    assert result.exit_code == 1
    assert "--database escapes the project root" in result.output


def test_cli_accepts_a_hash_validated_zero_row_review_queue(tmp_path: Path) -> None:
    output_dir = _empty_lexical_run(tmp_path)

    result = runner.invoke(
        app,
        ["build-lexical-review-queue", "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert "candidate_review_queue rows=0" in result.stdout


def test_cli_stage_verification_rejects_empty_baseline_and_physical_tampering(
    tmp_path: Path,
) -> None:
    output_dir = _empty_lexical_run(tmp_path)
    empty = runner.invoke(
        app,
        ["run-lexical-baseline", "--primary", "--output-dir", str(output_dir)],
    )
    assert empty.exit_code == 1
    assert "omit governed cells" in empty.output

    queue_path = output_dir / "candidate_review_queue" / "part-00000.parquet"
    queue_path.write_bytes(queue_path.read_bytes() + b"tamper")
    tampered = runner.invoke(
        app,
        ["build-lexical-review-queue", "--output-dir", str(output_dir)],
    )
    assert tampered.exit_code == 1
    assert "physical hash mismatch" in tampered.output
