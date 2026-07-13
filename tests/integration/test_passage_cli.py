"""Focused CLI coverage for Milestone 5 passage operations."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
from typer.testing import CliRunner

import echoes.cli as cli_module
from echoes.cli import app

runner = CliRunner()


class _FakePassage(SimpleNamespace):
    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return dict(vars(self))


class _FakeMember(SimpleNamespace):
    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return dict(vars(self))


def _passage() -> _FakePassage:
    return _FakePassage(
        passage_id="P_TEST~" + "a" * 64,
        corpus="hebrew",
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        start_reference="GEN 1:1",
        end_reference="GEN 1:1",
        token_count=2,
        surface_text="surface",
        normalized_text="normalized",
        unpointed_text="unpointed",
        folded_text=None,
        disputed_passage_flag=False,
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        constituent_verse_passage_ids_json="[]",
    )


def _member(passage_id: str, position: int) -> _FakeMember:
    return _FakeMember(
        passage_id=passage_id,
        position_in_passage=position,
        token_id=f"token-{position}",
        source_reference="GEN 1:1",
        source_position_in_corpus=position,
        stream_position_in_corpus=position,
        membership_basis="qere_primary",
        structural_resolution_status="source_native",
    )


def test_segment_passages_requires_all_or_an_exact_stream() -> None:
    result = runner.invoke(app, ["segment-passages"])

    assert result.exit_code == 1
    assert "select --all or provide --corpus, --profile, and --reading together" in result.output


def test_segment_passages_passes_an_exact_selection(monkeypatch: Any, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    output = tmp_path / "schema-v1"
    database = tmp_path / "echoes.duckdb"

    monkeypatch.setattr(cli_module, "_load_segmentation_config", lambda _: object())

    def fake_segment_passages(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            context=SimpleNamespace(run_id="passages-v1-test"),
            output_dir=output,
            database_path=database,
            table_counts={"passages": 1},
            runtime_seconds=0.25,
            output_size_bytes=42,
        )

    monkeypatch.setattr(cli_module, "segment_passages", fake_segment_passages)
    result = runner.invoke(
        app,
        [
            "segment-passages",
            "--corpus",
            "hebrew",
            "--profile",
            "edition_complete",
            "--reading",
            "qere",
            "--granularity",
            "verse",
            "--book",
            "GEN",
            "--output-dir",
            str(output),
            "--database",
            str(database),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Generated passage run passages-v1-test" in result.output
    selection = captured["selection"]
    assert selection.corpus == "hebrew"
    assert selection.analysis_profile == "edition_complete"
    assert selection.analysis_reading == "qere"
    assert selection.granularity == "verse"
    assert selection.book == "GEN"


def test_validate_passages_requires_all() -> None:
    result = runner.invoke(app, ["validate-passages"])

    assert result.exit_code == 1
    assert "select --all" in result.output


def test_validate_passages_returns_nonzero_for_errors(monkeypatch: Any, tmp_path: Path) -> None:
    finding = SimpleNamespace(
        severity="error",
        code="broken-membership",
        table="passage_membership",
        message="membership is incomplete",
    )
    validation = SimpleNamespace(
        segmentation_run_id="passages-v1-test",
        error_count=1,
        warning_count=0,
        informational_count=0,
        table_counts={"passages": 1},
        issues=[finding],
        passed=False,
        exit_code=1,
    )
    monkeypatch.setattr(cli_module, "_load_segmentation_config", lambda _: object())
    monkeypatch.setattr(cli_module, "load_segmentation_inputs", lambda **_: object())
    monkeypatch.setattr(cli_module, "validate_passage_artifacts", lambda *_, **__: validation)

    result = runner.invoke(
        app,
        [
            "validate-passages",
            "--all",
            "--output-dir",
            str(tmp_path / "schema-v1"),
            "--database",
            str(tmp_path / "echoes.duckdb"),
        ],
    )

    assert result.exit_code == 1
    assert "errors=1" in result.output
    assert "broken-membership" in result.output


def test_passage_summary_reads_generated_database(tmp_path: Path) -> None:
    database = tmp_path / "echoes.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE passages (corpus VARCHAR, analysis_profile VARCHAR, "
            "analysis_reading VARCHAR, granularity VARCHAR, book VARCHAR, "
            "token_count BIGINT, disputed_passage_flag BOOLEAN, reference_gap BOOLEAN, "
            "ketiv_structural_uncertainty BOOLEAN)"
        )
        connection.execute(
            "INSERT INTO passages VALUES "
            "('hebrew', 'edition_complete', 'qere', 'verse', 'GEN', 3, false, false, false)"
        )

    result = runner.invoke(
        app,
        ["passage-summary", "--all", "--database", str(database), "--json"],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary[0]["corpus"] == "hebrew"
    assert summary[0]["passage_count"] == 1
    assert summary[0]["membership_count"] == 3


def test_show_and_reconstruct_passage(monkeypatch: Any) -> None:
    passage = _passage()
    monkeypatch.setattr(cli_module, "read_passage", lambda *_: passage)
    monkeypatch.setattr(
        cli_module,
        "_passage_exclusions",
        lambda *_: [
            {
                "reason_code": "unresolved_clause",
                "source_reference": "GEN 1:1",
                "token_id": "token-2",
                "resolution_status": "unresolved",
            }
        ],
    )

    shown = runner.invoke(app, ["show-passage", passage.passage_id])
    reconstructed = runner.invoke(app, ["reconstruct-passage", passage.passage_id, "--json"])

    assert shown.exit_code == 0, shown.output
    assert "References: GEN 1:1 through GEN 1:1" in shown.output
    assert "Explicit exclusions: 1" in shown.output
    assert "Ketiv structural uncertainty: False" in shown.output
    assert reconstructed.exit_code == 0, reconstructed.output
    assert json.loads(reconstructed.stdout)["surface_text"] == "surface"


def test_passage_membership_displays_exact_order(monkeypatch: Any) -> None:
    passage = _passage()
    monkeypatch.setattr(
        cli_module,
        "read_passage_membership",
        lambda *_: [_member(passage.passage_id, 1), _member(passage.passage_id, 2)],
    )

    result = runner.invoke(app, ["passage-membership", passage.passage_id, "--json"])

    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert [row["position_in_passage"] for row in rows] == [1, 2]
    assert [row["token_id"] for row in rows] == ["token-1", "token-2"]


def test_passage_lookup_reports_missing_ids(monkeypatch: Any) -> None:
    monkeypatch.setattr(cli_module, "read_passage", lambda *_: None)

    result = runner.invoke(app, ["show-passage", "P_MISSING~" + "f" * 64])

    assert result.exit_code == 1
    assert "Passage not found" in result.output
