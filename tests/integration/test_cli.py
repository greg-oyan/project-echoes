"""CLI integration tests."""

import json
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
    assert "--determinism-reference-root" in result.stdout


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
