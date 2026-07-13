"""Approval gate, receipt, hash, overwrite, and incomplete-acquisition tests."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import pytest

from echoes.acquire import (
    AcquisitionError,
    acquire_source,
    audit_manifest_hashes,
    verify_acquisition,
)
from echoes.acquire.sources import _configure_canonical_byte_checkout
from echoes.manifests.sources import SourceManifest, SourceStatus


class _HttpResponse(io.BytesIO):
    def __init__(self, payload: bytes, *, url: str) -> None:
        super().__init__(payload)
        self.headers = {
            "Content-Length": str(len(payload)),
            "Content-Type": "application/zip",
            "ETag": '"fixture-etag"',
            "Last-Modified": "Sun, 12 Jul 2026 00:00:00 GMT",
        }
        self.status = 200
        self._url = url

    def geturl(self) -> str:
        return self._url


def _zip_bytes(
    data: bytes,
    *,
    extra_members: list[tuple[str | zipfile.ZipInfo, bytes]] | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("cross_references.txt", data)
        for name, payload in extra_members or []:
            archive.writestr(name, payload)
    return output.getvalue()


def _http_zip_source(
    source: SourceManifest,
    *,
    archive_payload: bytes,
    extracted_payload: bytes,
) -> SourceManifest:
    archive_hash = hashlib.sha256(archive_payload).hexdigest()
    version = f"snapshot-2026-07-12-sha256-{archive_hash[:12]}"
    values = source.model_dump(mode="json")
    values.update(
        {
            "version_or_commit": version,
            "download_date": None,
            "expected_files": ["cross_references.txt"],
            "file_hashes": {"cross_references.txt": hashlib.sha256(extracted_payload).hexdigest()},
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
    return SourceManifest.model_validate(values)


def _http_source(source: SourceManifest, payload: bytes) -> SourceManifest:
    values = source.model_dump(mode="json")
    values.update(
        {
            "expected_files": ["fixture.bin"],
            "file_hashes": {"fixture.bin": hashlib.sha256(payload).hexdigest()},
            "acquisition": {
                "method": "http_files",
                "version_label": "fixture-v1",
                "upstream_commit": source.version_or_commit,
                "files": [
                    {
                        "path": "fixture.bin",
                        "url": "https://example.invalid/fixture.bin",
                        "size_bytes": len(payload),
                    }
                ],
            },
            "status": "approved",
            "download_date": None,
        }
    )
    return SourceManifest.model_validate(values)


def test_source_approval_gate_runs_before_network(
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("network must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    blocked = macula_source.model_copy(update={"status": SourceStatus.UNDER_REVIEW})

    with pytest.raises(AcquisitionError, match="requires approved status"):
        acquire_source(blocked, data_root=tmp_path)

    assert not called


def test_acquisition_writes_and_verifies_hash_receipt(
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"purpose-built acquisition fixture"
    source = _http_source(macula_source, payload)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(payload),
    )

    directory, receipt = acquire_source(source, data_root=tmp_path)
    verified_directory, verified = verify_acquisition(source, data_root=tmp_path)

    assert verified_directory == directory
    assert verified == receipt
    assert (directory / "fixture.bin").read_bytes() == payload
    assert receipt.files[0].sha256 == hashlib.sha256(payload).hexdigest()
    receipt_text = (directory / "acquisition-receipt.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in receipt_text
    assert json.loads(receipt_text)["upstream_commit"] == source.version_or_commit


def test_acquisition_refuses_silent_overwrite_and_force_is_explicit(
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"first version"
    source = _http_source(macula_source, payload)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(payload),
    )
    directory, _ = acquire_source(source, data_root=tmp_path)

    with pytest.raises(AcquisitionError, match="refusing to overwrite"):
        acquire_source(source, data_root=tmp_path)

    refreshed, _ = acquire_source(source, data_root=tmp_path, force=True)
    assert refreshed == directory
    assert (directory / "fixture.bin").read_bytes() == payload


def test_verification_detects_corruption_and_missing_receipt(
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"verified bytes"
    source = _http_source(macula_source, payload)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(payload),
    )
    directory, _ = acquire_source(source, data_root=tmp_path)
    (directory / "fixture.bin").write_bytes(b"corrupt")

    with pytest.raises(AcquisitionError, match=r"size mismatch|SHA-256 mismatch"):
        verify_acquisition(source, data_root=tmp_path)

    empty_root = tmp_path / "empty"
    with pytest.raises(AcquisitionError, match="receipt does not exist"):
        verify_acquisition(source, data_root=empty_root)


def test_http_zip_acquisition_is_content_addressed_and_verifies_offline(
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = b"From Verse\tTo Verse\tVotes\nGen.1.1\tJohn.1.1\t3\n"
    archive_payload = _zip_bytes(extracted)
    source = _http_zip_source(
        macula_source,
        archive_payload=archive_payload,
        extracted_payload=extracted,
    )
    url = source.acquisition.files[0].url if source.acquisition is not None else ""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: _HttpResponse(archive_payload, url=url),
    )

    directory, receipt = acquire_source(source, data_root=tmp_path)

    assert receipt.schema_version == 2
    assert receipt.upstream_commit is None
    assert receipt.archive is not None
    assert receipt.archive.sha256 == source.acquisition.archive_sha256
    assert receipt.archive.http.etag == '"fixture-etag"'
    assert receipt.archive.http.last_modified == "Sun, 12 Jul 2026 00:00:00 GMT"
    assert receipt.archive.http.content_length == len(archive_payload)
    assert receipt.canonical_record_stream_schema_version == "synthetic-tsv-v1"
    assert receipt.canonical_record_stream_sha256 is not None
    assert (directory / "cross_references.txt").read_bytes() == extracted
    assert (directory / receipt.archive.relative_path).read_bytes() == archive_payload

    def fail_if_networked(*args: object, **kwargs: object) -> object:
        raise AssertionError("offline verification must not contact the network")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_networked)
    verified_directory, verified = verify_acquisition(source, data_root=tmp_path)

    assert verified_directory == directory
    assert verified == receipt


def test_http_zip_force_is_refused_before_network(
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = b"From Verse\tTo Verse\tVotes\nGen.1.1\tJohn.1.1\t3\n"
    archive_payload = _zip_bytes(extracted)
    source = _http_zip_source(
        macula_source,
        archive_payload=archive_payload,
        extracted_payload=extracted,
    )
    called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("network must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)

    with pytest.raises(AcquisitionError, match="--force may not replace"):
        acquire_source(source, data_root=tmp_path, force=True)

    assert not called


@pytest.mark.parametrize(
    "unsafe_name",
    ["../escape.txt", "/absolute.txt", "C:/drive.txt", "nested\\escape.txt", "payload.exe"],
)
def test_http_zip_rejects_unsafe_or_executable_members_before_extraction(
    unsafe_name: str,
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = b"From Verse\tTo Verse\tVotes\nGen.1.1\tJohn.1.1\t3\n"
    archive_payload = _zip_bytes(extracted, extra_members=[(unsafe_name, b"not allowed")])
    source = _http_zip_source(
        macula_source,
        archive_payload=archive_payload,
        extracted_payload=extracted,
    )
    url = source.acquisition.files[0].url if source.acquisition is not None else ""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: _HttpResponse(archive_payload, url=url),
    )

    with pytest.raises(AcquisitionError, match=r"ZIP member|executable|inventory"):
        acquire_source(source, data_root=tmp_path)

    assert source.acquisition is not None
    assert not (tmp_path / "raw" / source.source_id / source.acquisition.version_label).exists()
    assert not (tmp_path / "escape.txt").exists()


def test_http_zip_rejects_symlink_member(
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = b"From Verse\tTo Verse\tVotes\nGen.1.1\tJohn.1.1\t3\n"
    symlink = zipfile.ZipInfo("link.txt")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive_payload = _zip_bytes(extracted, extra_members=[(symlink, b"target")])
    source = _http_zip_source(
        macula_source,
        archive_payload=archive_payload,
        extracted_payload=extracted,
    )
    url = source.acquisition.files[0].url if source.acquisition is not None else ""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: _HttpResponse(archive_payload, url=url),
    )

    with pytest.raises(AcquisitionError, match="symlink or special"):
        acquire_source(source, data_root=tmp_path)


def test_http_zip_verification_detects_archive_and_canonical_stream_corruption(
    macula_source: SourceManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = b"From Verse\tTo Verse\tVotes\nGen.1.1\tJohn.1.1\t3\n"
    archive_payload = _zip_bytes(extracted)
    source = _http_zip_source(
        macula_source,
        archive_payload=archive_payload,
        extracted_payload=extracted,
    )
    url = source.acquisition.files[0].url if source.acquisition is not None else ""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: _HttpResponse(archive_payload, url=url),
    )
    directory, receipt = acquire_source(source, data_root=tmp_path)
    assert receipt.archive is not None
    archive_path = directory / receipt.archive.relative_path
    archive_path.write_bytes(archive_payload + b"corruption")

    with pytest.raises(AcquisitionError, match="archive size mismatch"):
        verify_acquisition(source, data_root=tmp_path)

    archive_path.write_bytes(archive_payload)
    data_path = directory / "cross_references.txt"
    data_path.write_bytes(extracted.replace(b"\t3", b"\t4"))
    with pytest.raises(AcquisitionError, match=r"SHA-256 mismatch|size mismatch"):
        verify_acquisition(source, data_root=tmp_path)


def test_git_checkout_configuration_disables_text_conversion(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)

    _configure_canonical_byte_checkout(checkout)

    autocrlf = subprocess.run(
        ["git", "config", "core.autocrlf"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    )
    assert autocrlf.stdout.strip() == "false"
    attributes = (checkout / ".git" / "info" / "attributes").read_text(encoding="ascii")
    assert "* -text" in attributes


def _audited_source(source: SourceManifest, payload: bytes) -> SourceManifest:
    values = source.model_dump(mode="json")
    values.update(
        {
            "expected_files": ["docs/sample.txt"],
            "file_hashes": {"docs/sample.txt": hashlib.sha256(payload).hexdigest()},
            "acquisition": {
                "method": "git_sparse",
                "version_label": "audit-v1",
                "upstream_commit": source.version_or_commit,
                "repository_url": "https://example.invalid/repo.git",
                "include_paths": ["docs/sample.txt"],
                "expected_file_count": 1,
            },
            "status": "approved",
            "download_date": None,
        }
    )
    return SourceManifest.model_validate(values)


def test_manifest_hash_audit_passes_on_canonical_bytes(
    macula_source: SourceManifest, tmp_path: Path
) -> None:
    payload = b"canonical\nbytes\n"
    source = _audited_source(macula_source, payload)
    target = tmp_path / "raw" / source.source_id / "audit-v1" / "docs" / "sample.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)

    assert audit_manifest_hashes(source, data_root=tmp_path) == []


def test_manifest_hash_audit_detects_line_ending_rewrites(
    macula_source: SourceManifest, tmp_path: Path
) -> None:
    payload = b"canonical\nbytes\n"
    source = _audited_source(macula_source, payload)
    target = tmp_path / "raw" / source.source_id / "audit-v1" / "docs" / "sample.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload.replace(b"\n", b"\r\n"))

    findings = audit_manifest_hashes(source, data_root=tmp_path)

    assert findings is not None
    assert len(findings) == 1
    assert "canonical SHA-256 mismatch" in findings[0]


def test_manifest_hash_audit_skips_absent_local_data(
    macula_source: SourceManifest, tmp_path: Path
) -> None:
    source = _audited_source(macula_source, b"never acquired")

    assert audit_manifest_hashes(source, data_root=tmp_path) is None


def test_manifest_hash_audit_reports_missing_hashed_file(
    macula_source: SourceManifest, tmp_path: Path
) -> None:
    payload = b"canonical\nbytes\n"
    source = _audited_source(macula_source, payload)
    directory = tmp_path / "raw" / source.source_id / "audit-v1"
    directory.mkdir(parents=True)

    findings = audit_manifest_hashes(source, data_root=tmp_path)

    assert findings is not None
    assert len(findings) == 1
    assert "missing" in findings[0]
