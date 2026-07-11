"""Approval gate, receipt, hash, overwrite, and incomplete-acquisition tests."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request
from pathlib import Path

import pytest

from echoes.acquire import AcquisitionError, acquire_source, verify_acquisition
from echoes.manifests.sources import SourceManifest, SourceStatus


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
