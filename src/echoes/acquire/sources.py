"""Reproducible, approval-gated acquisition of external source files."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import subprocess
import urllib.error
import urllib.request
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes import __version__
from echoes.manifest import sha256_file
from echoes.manifests.sources import (
    MachineProcessingStatus,
    SourceManifest,
    SourceStatus,
)

ACQUISITION_RECEIPT_NAME = "acquisition-receipt.json"
SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def _remove_tree(path: Path) -> None:
    """Remove a private staging tree, including read-only Git metadata on Windows."""
    if not path.exists():
        return
    for child in path.rglob("*"):
        with suppress(OSError):
            child.chmod(stat.S_IRWXU)
    with suppress(OSError):
        path.chmod(stat.S_IRWXU)
    shutil.rmtree(path)


class AcquisitionError(RuntimeError):
    """Raised when a governed acquisition cannot be completed or verified."""


class AcquiredFile(BaseModel):
    """Verified metadata for one locally acquired file."""

    model_config = ConfigDict(extra="forbid")

    relative_path: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AcquisitionReceipt(BaseModel):
    """Local, machine-readable evidence of one completed acquisition."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    upstream_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    acquired_at: datetime
    files: list[AcquiredFile] = Field(min_length=1)
    acquisition_command: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def file_paths_are_unique(self) -> Self:
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            msg = "acquisition receipt contains duplicate file paths"
            raise ValueError(msg)
        return self


def _approval_gate(source: SourceManifest) -> None:
    allowed = {SourceStatus.APPROVED, SourceStatus.ACQUIRED, SourceStatus.VALIDATED}
    if source.status not in allowed:
        raise AcquisitionError(
            f"source '{source.source_id}' is {source.status}; acquisition requires approved status"
        )
    if not source.licensing_complete:
        raise AcquisitionError(
            f"source '{source.source_id}' does not have a complete licensing review"
        )
    if source.machine_processing_status is not MachineProcessingStatus.PERMITTED:
        raise AcquisitionError(
            f"source '{source.source_id}' is not approved for local machine processing"
        )
    if source.acquisition is None:
        raise AcquisitionError(f"source '{source.source_id}' has no acquisition instructions")
    if not SAFE_VERSION_PATTERN.fullmatch(source.acquisition.version_label):
        raise AcquisitionError("source version label is not safe for a local directory name")


def acquisition_directory(source: SourceManifest, data_root: Path = Path("data")) -> Path:
    """Return the versioned, Git-ignored raw directory for a governed source."""
    _approval_gate(source)
    assert source.acquisition is not None  # narrowed by the approval gate
    return data_root / "raw" / source.source_id / source.acquisition.version_label


def _download_file(
    *,
    url: str,
    destination: Path,
    relative_path: str,
    expected_size: int | None,
    expected_hash: str | None,
) -> AcquiredFile:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"Project-Echoes/{__version__} source-acquisition"},
    )
    digest = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(f"{destination.name}.part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response, part_path.open("xb") as out:
            while block := response.read(DOWNLOAD_CHUNK_SIZE):
                out.write(block)
                digest.update(block)
                size += len(block)
    except FileExistsError as exc:
        raise AcquisitionError(f"stale partial download exists: {part_path}") from exc
    except urllib.error.HTTPError as exc:
        part_path.unlink(missing_ok=True)
        raise AcquisitionError(f"download failed for {url}: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        part_path.unlink(missing_ok=True)
        raise AcquisitionError(f"network failure while downloading {url}: {exc.reason}") from exc
    except (OSError, TimeoutError) as exc:
        part_path.unlink(missing_ok=True)
        raise AcquisitionError(f"could not download {url}: {exc}") from exc

    actual_hash = digest.hexdigest()
    if expected_size is not None and size != expected_size:
        part_path.unlink(missing_ok=True)
        raise AcquisitionError(
            f"size mismatch for {url}: expected {expected_size}, received {size} bytes"
        )
    if expected_hash is not None and actual_hash != expected_hash:
        part_path.unlink(missing_ok=True)
        raise AcquisitionError(
            f"SHA-256 mismatch for {url}: expected {expected_hash}, calculated {actual_hash}"
        )
    part_path.replace(destination)
    return AcquiredFile(
        relative_path=relative_path,
        source_url=url,
        size_bytes=size,
        sha256=actual_hash,
    )


def _write_receipt(receipt: AcquisitionReceipt, path: Path) -> None:
    path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _run_git(arguments: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise AcquisitionError(f"could not execute Git: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise AcquisitionError(f"Git acquisition failed: {detail}")
    return result.stdout.strip()


def _acquire_http_files(source: SourceManifest, staging: Path) -> list[AcquiredFile]:
    assert source.acquisition is not None
    acquired_files: list[AcquiredFile] = []
    for file_spec in source.acquisition.files:
        destination = staging / Path(file_spec.path)
        acquired = _download_file(
            url=file_spec.url,
            destination=destination,
            relative_path=file_spec.path,
            expected_size=file_spec.size_bytes,
            expected_hash=source.file_hashes.get(file_spec.path),
        )
        acquired_files.append(acquired)
    return acquired_files


def _acquire_git_sparse(source: SourceManifest, staging: Path) -> list[AcquiredFile]:
    assert source.acquisition is not None
    spec = source.acquisition
    assert spec.repository_url is not None
    checkout = staging.parent / f".{staging.name}.checkout-{uuid4().hex}"
    try:
        _run_git(["init", "--quiet", str(checkout)])
        _run_git(["remote", "add", "origin", spec.repository_url], cwd=checkout)
        _run_git(["config", "remote.origin.promisor", "true"], cwd=checkout)
        _run_git(["config", "remote.origin.partialclonefilter", "blob:none"], cwd=checkout)
        _run_git(["sparse-checkout", "init", "--cone"], cwd=checkout)
        sparse_directories = [
            path for path in spec.include_paths if "/" in path and not Path(path).suffix
        ]
        if not sparse_directories:
            raise AcquisitionError("git_sparse acquisition requires at least one directory")
        _run_git(["sparse-checkout", "set", *sparse_directories], cwd=checkout)
        _run_git(
            [
                "fetch",
                "--filter=blob:none",
                "--no-tags",
                "--depth",
                "1",
                "origin",
                spec.upstream_commit,
            ],
            cwd=checkout,
        )
        _run_git(["checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=checkout)
        actual_commit = _run_git(["rev-parse", "HEAD"], cwd=checkout)
        if actual_commit != spec.upstream_commit:
            raise AcquisitionError(
                f"Git checkout resolved to {actual_commit}, expected {spec.upstream_commit}"
            )

        for include_path in spec.include_paths:
            source_path = checkout / include_path
            destination = staging / include_path
            if source_path.is_dir():
                shutil.copytree(source_path, destination)
            elif source_path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
            else:
                raise AcquisitionError(
                    f"pinned Git acquisition is missing include path: {include_path}"
                )

        paths = sorted(path for path in staging.rglob("*") if path.is_file())
        if spec.expected_file_count is not None and len(paths) != spec.expected_file_count:
            raise AcquisitionError(
                f"pinned Git acquisition produced {len(paths)} files; "
                f"expected {spec.expected_file_count}"
            )
        acquired_files = []
        repository_page = spec.repository_url.removesuffix(".git")
        for path in paths:
            relative = path.relative_to(staging).as_posix()
            acquired_files.append(
                AcquiredFile(
                    relative_path=relative,
                    source_url=f"{repository_page}/blob/{spec.upstream_commit}/{relative}",
                    size_bytes=path.stat().st_size,
                    sha256=sha256_file(path),
                )
            )
        return acquired_files
    finally:
        if checkout.exists():
            _remove_tree(checkout)


def acquire_source(
    source: SourceManifest,
    *,
    data_root: Path = Path("data"),
    force: bool = False,
    command: str | None = None,
) -> tuple[Path, AcquisitionReceipt]:
    """Acquire exactly the files declared by an approved source manifest."""
    _approval_gate(source)
    assert source.acquisition is not None
    target = acquisition_directory(source, data_root)
    if target.exists() and not force:
        state = "complete" if (target / ACQUISITION_RECEIPT_NAME).is_file() else "incomplete"
        raise AcquisitionError(
            f"refusing to overwrite {state} acquisition at {target}; "
            "verify it or pass --force explicitly"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.acquiring-{uuid4().hex}"
    backup = target.parent / f".{target.name}.backup-{uuid4().hex}"
    acquired_files: list[AcquiredFile] = []
    try:
        staging.mkdir()
        if source.acquisition.method == "http_files":
            acquired_files = _acquire_http_files(source, staging)
        else:
            acquired_files = _acquire_git_sparse(source, staging)

        receipt = AcquisitionReceipt(
            source_id=source.source_id,
            source_version=source.version_or_commit or source.acquisition.upstream_commit,
            version_label=source.acquisition.version_label,
            upstream_commit=source.acquisition.upstream_commit,
            acquired_at=datetime.now(tz=UTC),
            files=acquired_files,
            acquisition_command=command or f"echoes acquire-source {source.source_id}",
            tool_version=__version__,
        )
        _write_receipt(receipt, staging / ACQUISITION_RECEIPT_NAME)

        if target.exists():
            target.replace(backup)
        try:
            staging.replace(target)
        except OSError:
            if backup.exists() and not target.exists():
                backup.replace(target)
            raise
        if backup.exists():
            _remove_tree(backup)
    except Exception:
        if staging.exists():
            _remove_tree(staging)
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise
    return target, receipt


def load_acquisition_receipt(path: Path) -> AcquisitionReceipt:
    """Load and validate a local acquisition receipt."""
    if not path.is_file():
        raise AcquisitionError(f"acquisition receipt does not exist: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AcquisitionReceipt.model_validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise AcquisitionError(f"invalid acquisition receipt {path}: {exc}") from exc


def verify_acquisition(
    source: SourceManifest,
    *,
    data_root: Path = Path("data"),
) -> tuple[Path, AcquisitionReceipt]:
    """Verify local files against their receipt and current approved manifest."""
    _approval_gate(source)
    assert source.acquisition is not None
    directory = acquisition_directory(source, data_root)
    receipt = load_acquisition_receipt(directory / ACQUISITION_RECEIPT_NAME)
    if receipt.source_id != source.source_id:
        raise AcquisitionError(
            f"receipt source_id is {receipt.source_id}, expected {source.source_id}"
        )
    if receipt.upstream_commit != source.acquisition.upstream_commit:
        raise AcquisitionError(
            "receipt upstream commit does not match the approved source manifest"
        )
    if receipt.source_version != source.version_or_commit:
        raise AcquisitionError("receipt source version does not match the source manifest")

    receipt_paths = {item.relative_path for item in receipt.files}
    expected_paths = set(source.expected_files)
    missing_expected = sorted(expected_paths - receipt_paths)
    if missing_expected:
        raise AcquisitionError(f"receipt is missing manifest-required files: {missing_expected}")
    if source.acquisition.method == "http_files" and receipt_paths != expected_paths:
        unexpected = sorted(receipt_paths - expected_paths)
        raise AcquisitionError(f"receipt contains unexpected HTTP-acquired files: {unexpected}")
    if (
        source.acquisition.expected_file_count is not None
        and len(receipt_paths) != source.acquisition.expected_file_count
    ):
        raise AcquisitionError(
            f"receipt contains {len(receipt_paths)} files; "
            f"expected {source.acquisition.expected_file_count}"
        )

    actual_paths = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != ACQUISITION_RECEIPT_NAME
    }
    if actual_paths != receipt_paths:
        missing = sorted(receipt_paths - actual_paths)
        unexpected = sorted(actual_paths - receipt_paths)
        raise AcquisitionError(
            f"local acquisition is incomplete or contains unexpected files; "
            f"missing={missing}, unexpected={unexpected}"
        )

    for item in receipt.files:
        path = directory / item.relative_path
        actual_size = path.stat().st_size
        if actual_size != item.size_bytes:
            raise AcquisitionError(
                f"size mismatch for {item.relative_path}: "
                f"receipt={item.size_bytes}, actual={actual_size}"
            )
        actual_hash = sha256_file(path)
        if actual_hash != item.sha256:
            raise AcquisitionError(
                f"SHA-256 mismatch for {item.relative_path}: "
                f"receipt={item.sha256}, actual={actual_hash}"
            )
        manifest_hash = source.file_hashes.get(item.relative_path)
        if manifest_hash is not None and actual_hash != manifest_hash:
            raise AcquisitionError(
                f"SHA-256 mismatch against source manifest for {item.relative_path}"
            )
    return directory, receipt
