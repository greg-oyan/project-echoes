"""CLI integration tests."""

import json
from pathlib import Path

from typer.testing import CliRunner

from echoes.cli import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


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
    assert "create-run-manifest" in result.stdout


def test_cli_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_cli_validates_project_configuration() -> None:
    result = runner.invoke(
        app,
        ["validate-config", "--config-dir", str(PROJECT_ROOT / "config")],
    )

    assert result.exit_code == 0
    assert "Validated 14 configuration files" in result.stdout


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
