"""CLI coverage for the standalone final-discovery positive controls."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from echoes.cli import app

runner = CliRunner()


def test_validate_positive_controls_emits_authenticated_json() -> None:
    result = runner.invoke(app, ["validate-positive-controls", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["benchmark_id"] == "final-discovery-positive-controls-v1"
    assert payload["row_count"] == 24
    assert payload["partition_counts"] == {"development": 3, "test": 6, "train": 15}


def test_validate_positive_controls_fails_for_missing_data(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["validate-positive-controls", "--data", str(tmp_path / "missing.csv")],
    )

    assert result.exit_code == 1
    assert "positive-control CSV does not exist" in result.output
