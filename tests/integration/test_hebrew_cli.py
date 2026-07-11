"""Hebrew CLI command success and failure integration tests."""

from pathlib import Path

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from echoes.cli import _echo_json, app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


class UnicodePayload(BaseModel):
    text: str


def test_json_emission_is_safe_for_legacy_windows_console(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _echo_json(UnicodePayload(text="עברית"))

    output = capsys.readouterr().out
    output.encode("ascii")
    assert "\\u05e2" in output


def test_verify_acquisition_reports_missing_local_receipt(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "verify-acquisition",
            "macula-hebrew",
            "--manifest-path",
            str(PROJECT_ROOT / "data" / "manifests" / "sources.yaml"),
            "--data-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "receipt does not exist" in result.output


def test_ingest_hebrew_fails_before_parsing_when_acquisition_is_missing(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "ingest-hebrew",
            "--manifest-path",
            str(PROJECT_ROOT / "data" / "manifests" / "sources.yaml"),
            "--config-dir",
            str(PROJECT_ROOT / "config"),
            "--data-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "Hebrew ingestion failed" in result.output
    assert "receipt does not exist" in result.output


def test_validate_corpus_reports_missing_processed_tables(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "validate-corpus",
            "--corpus",
            "hebrew",
            "--manifest-path",
            str(PROJECT_ROOT / "data" / "manifests" / "sources.yaml"),
            "--config-dir",
            str(PROJECT_ROOT / "config"),
            "--data-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "required processed table does not exist" in result.output


def test_corpus_summary_cli_succeeds_with_fixture_database(
    stored_fixture_corpus: object,
) -> None:
    result = runner.invoke(
        app,
        [
            "corpus-summary",
            "--corpus",
            "hebrew",
            "--database",
            str(stored_fixture_corpus.database),  # type: ignore[attr-defined]
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"total_tokens": 9' in result.stdout
    assert '"aramaic_tokens": 2' in result.stdout


def test_hebrew_commands_reject_unsupported_corpora(tmp_path: Path) -> None:
    validation = runner.invoke(app, ["validate-corpus", "--corpus", "greek"])
    summary = runner.invoke(
        app,
        ["corpus-summary", "--corpus", "greek", "--database", str(tmp_path / "none")],
    )

    assert validation.exit_code == 1
    assert summary.exit_code == 1
    assert "Unsupported corpus: greek" in validation.output
