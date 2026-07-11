"""Source-governance CLI integration tests."""

from pathlib import Path

from typer.testing import CliRunner

from echoes.cli import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "source_manifests"
runner = CliRunner()


def test_validate_sources_succeeds_for_valid_fixture() -> None:
    result = runner.invoke(
        app,
        ["validate-sources", "--manifest-path", str(FIXTURES / "valid.yaml")],
    )

    assert result.exit_code == 0
    assert "Validated 2 source records" in result.stdout
    assert "Licensing: complete=0, incomplete=2" in result.stdout


def test_validate_sources_fails_for_invalid_fixture() -> None:
    result = runner.invoke(
        app,
        ["validate-sources", "--manifest-path", str(FIXTURES / "duplicate-id.yaml")],
    )

    assert result.exit_code == 1
    assert "Source manifest validation failed" in result.output
    assert "duplicate source_id" in result.output


def test_list_sources_filters_by_role() -> None:
    result = runner.invoke(
        app,
        [
            "list-sources",
            "--manifest-path",
            str(FIXTURES / "valid.yaml"),
            "--role",
            "primary_discovery",
        ],
    )

    assert result.exit_code == 0
    assert "fixture-primary" in result.stdout
    assert "fixture-reference" not in result.stdout
    assert "1 source(s)." in result.stdout


def test_list_sources_filters_by_status() -> None:
    result = runner.invoke(
        app,
        [
            "list-sources",
            "--manifest-path",
            str(FIXTURES / "valid.yaml"),
            "--status",
            "under_review",
        ],
    )

    assert result.exit_code == 0
    assert "fixture-reference" in result.stdout
    assert "fixture-primary" not in result.stdout


def test_show_source_prints_normalized_record() -> None:
    result = runner.invoke(
        app,
        [
            "show-source",
            "fixture-reference",
            "--manifest-path",
            str(FIXTURES / "valid.yaml"),
        ],
    )

    assert result.exit_code == 0
    assert "source_id: fixture-reference" in result.stdout
    assert "license_review_status: in_progress" in result.stdout


def _write_audit_file(data_root: Path, payload: bytes) -> None:
    target = data_root / "raw" / "fixture-hash-audit" / "audit-v1" / "docs" / "sample.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)


def test_validate_sources_recomputes_local_canonical_hashes(tmp_path: Path) -> None:
    _write_audit_file(tmp_path, b"canonical\nbytes\n")

    result = runner.invoke(
        app,
        [
            "validate-sources",
            "--manifest-path",
            str(FIXTURES / "hash-audit.yaml"),
            "--data-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "Canonical-hash audit: 1 locally present source(s) recomputed." in result.stdout


def test_validate_sources_fails_on_text_mode_rewritten_bytes(tmp_path: Path) -> None:
    _write_audit_file(tmp_path, b"canonical\r\nbytes\r\n")

    result = runner.invoke(
        app,
        [
            "validate-sources",
            "--manifest-path",
            str(FIXTURES / "hash-audit.yaml"),
            "--data-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "canonical SHA-256 mismatch" in result.output


def test_show_source_handles_missing_id_cleanly() -> None:
    result = runner.invoke(
        app,
        [
            "show-source",
            "missing-source",
            "--manifest-path",
            str(FIXTURES / "valid.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "Source not found: missing-source" in result.output
