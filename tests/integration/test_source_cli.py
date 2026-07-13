"""Source-governance CLI integration tests."""

import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from echoes.cli import app
from echoes.manifests.sources import SourceManifest, load_source_catalog

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


def _write_http_zip_cli_fixture(tmp_path: Path) -> tuple[Path, Path, bytes]:
    extracted = b"From Verse\tTo Verse\tVotes\nGen.1.1\tJohn.1.1\t3\n"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("cross_references.txt", extracted)
    archive_payload = output.getvalue()
    archive_hash = hashlib.sha256(archive_payload).hexdigest()
    version = f"snapshot-2026-07-12-sha256-{archive_hash[:12]}"
    base = load_source_catalog(PROJECT_ROOT / "data" / "manifests" / "sources.yaml").find(
        "macula-hebrew"
    )
    assert base is not None
    values = base.model_dump(mode="json")
    values.update(
        {
            "source_id": "fixture-http-zip",
            "version_or_commit": version,
            "download_date": None,
            "expected_files": ["cross_references.txt"],
            "file_hashes": {"cross_references.txt": hashlib.sha256(extracted).hexdigest()},
            "ingest_adapter": "tests.synthetic_delimited",
            "acquisition": {
                "method": "http_zip",
                "version_label": version,
                "archive_sha256": archive_hash,
                "files": [
                    {
                        "path": "cross-references.zip",
                        "url": "https://example.invalid/cross-references.zip",
                        "size_bytes": len(archive_payload),
                    }
                ],
            },
            "archive_schema": {
                "archive_format": "zip",
                "data_file": "cross_references.txt",
                "encoding": "utf-8",
                "byte_order_mark": "none",
                "newline_convention": "lf",
                "delimiter": "\t",
                "header": ["From Verse", "To Verse", "Votes"],
                "column_count": 3,
                "reference_syntax": "Book.Chapter.Verse",
                "range_syntax": "Book.Chapter.Verse-Book.Chapter.Verse",
                "weight_representation": "signed decimal integer vote",
                "directionality": "a_to_b",
                "canonical_record_stream_schema_version": "synthetic-tsv-v1",
            },
            "status": "approved",
        }
    )
    source = SourceManifest.model_validate(values)
    manifest = tmp_path / "sources.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "sources": [source.model_dump(mode="json")]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return manifest, tmp_path / "data", archive_payload


def test_http_zip_acquire_and_offline_verify_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, data_root, archive_payload = _write_http_zip_cli_fixture(tmp_path)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(archive_payload),
    )

    acquired = runner.invoke(
        app,
        [
            "acquire-source",
            "fixture-http-zip",
            "--manifest-path",
            str(manifest),
            "--data-root",
            str(data_root),
        ],
    )

    assert acquired.exit_code == 0, acquired.output
    assert "Acquired fixture-http-zip" in acquired.stdout

    def fail_if_networked(*args: object, **kwargs: object) -> object:
        raise AssertionError("verify-acquisition must remain offline")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_networked)
    verified = runner.invoke(
        app,
        [
            "verify-acquisition",
            "fixture-http-zip",
            "--manifest-path",
            str(manifest),
            "--data-root",
            str(data_root),
        ],
    )

    assert verified.exit_code == 0, verified.output
    assert "Verified fixture-http-zip" in verified.stdout
