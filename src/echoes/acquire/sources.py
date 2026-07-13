"""Reproducible, approval-gated acquisition of external source files."""

from __future__ import annotations

import csv
import gc
import hashlib
import io
import json
import re
import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from echoes import __version__
from echoes.manifest import sha256_file
from echoes.manifests.sources import (
    MachineProcessingStatus,
    SourceArchiveSchema,
    SourceManifest,
    SourceStatus,
)

ACQUISITION_RECEIPT_NAME = "acquisition-receipt.json"
SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
ARCHIVE_DIRECTORY_NAME = "_archive"
MAX_ZIP_MEMBERS = 1000
MAX_ZIP_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 1000
ALLOWED_ZIP_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
EXECUTABLE_OR_NESTED_ARCHIVE_SUFFIXES = {
    ".7z",
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".gz",
    ".iso",
    ".jar",
    ".js",
    ".msi",
    ".ps1",
    ".py",
    ".rar",
    ".scr",
    ".sh",
    ".tar",
    ".tgz",
    ".vbs",
    ".whl",
    ".xz",
    ".zip",
}


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


def _atomic_directory_rename(source: Path, target: Path) -> None:
    """Rename a private tree, tolerating short Windows scanner locks."""

    for attempt in range(10):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == 9:
                raise
            gc.collect()
            time.sleep(0.05 * (attempt + 1))


class AcquisitionError(RuntimeError):
    """Raised when a governed acquisition cannot be completed or verified."""


def _validated_relative_path(value: str, *, field_name: str) -> str:
    """Reject paths that could escape or alias a governed acquisition tree."""
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"{field_name} must be a nonempty POSIX relative path")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or value.startswith(("/", "//"))
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ValueError(f"{field_name} must be a safe relative path without traversal")
    return posix.as_posix()


class AcquiredFile(BaseModel):
    """Verified metadata for one locally acquired file."""

    model_config = ConfigDict(extra="forbid")

    relative_path: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_member: str | None = None

    @field_validator("relative_path")
    @classmethod
    def relative_path_is_safe(cls, value: str) -> str:
        return _validated_relative_path(value, field_name="acquired file relative_path")


class HttpResponseMetadata(BaseModel):
    """HTTP provenance captured while downloading one governed archive."""

    model_config = ConfigDict(extra="forbid")

    requested_url: str = Field(min_length=1)
    final_url: str = Field(min_length=1)
    status_code: int | None = Field(default=None, ge=100, le=599)
    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = Field(default=None, ge=0)
    content_type: str | None = None


class AcquiredArchive(BaseModel):
    """Content identity, transport metadata, and inventory totals for one ZIP."""

    model_config = ConfigDict(extra="forbid")

    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_count: int = Field(ge=1)
    compressed_size_bytes: int = Field(ge=0)
    uncompressed_size_bytes: int = Field(ge=0)
    http: HttpResponseMetadata

    @field_validator("relative_path")
    @classmethod
    def relative_path_is_safe(cls, value: str) -> str:
        return _validated_relative_path(value, field_name="archive relative_path")


class AcquisitionReceipt(BaseModel):
    """Local, machine-readable evidence of one completed acquisition."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    upstream_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    acquired_at: datetime
    files: list[AcquiredFile] = Field(min_length=1)
    archive: AcquiredArchive | None = None
    canonical_record_stream_schema_version: str | None = None
    canonical_record_stream_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    acquisition_command: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def file_paths_are_unique(self) -> Self:
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            msg = "acquisition receipt contains duplicate file paths"
            raise ValueError(msg)
        if len(paths) != len({path.casefold() for path in paths}):
            raise ValueError("acquisition receipt contains case-colliding file paths")
        if self.archive is not None and self.archive.relative_path.casefold() in {
            path.casefold() for path in paths
        }:
            raise ValueError("archive path collides with an extracted file path")
        if self.schema_version == 1:
            if self.upstream_commit is None:
                raise ValueError("schema-1 acquisition receipt requires upstream_commit")
            if self.archive is not None or self.canonical_record_stream_sha256 is not None:
                raise ValueError("schema-1 acquisition receipt may not contain ZIP metadata")
        elif self.schema_version == 2:
            if self.upstream_commit is not None:
                raise ValueError("schema-2 ZIP receipt may not contain upstream_commit")
            if self.archive is None:
                raise ValueError("schema-2 ZIP receipt requires archive metadata")
            if not self.canonical_record_stream_schema_version:
                raise ValueError("schema-2 ZIP receipt requires canonical stream schema version")
            if self.canonical_record_stream_sha256 is None:
                raise ValueError("schema-2 ZIP receipt requires canonical stream SHA-256")
            if any(item.archive_member != item.relative_path for item in self.files):
                raise ValueError(
                    "schema-2 extracted files must preserve their exact archive member paths"
                )
        else:
            raise ValueError(
                f"unsupported acquisition receipt schema_version: {self.schema_version}"
            )
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


def _http_metadata(response: object, *, requested_url: str) -> HttpResponseMetadata:
    headers = getattr(response, "headers", None)

    def header(name: str) -> str | None:
        getter = getattr(headers, "get", None)
        if not callable(getter):
            return None
        value = getter(name)
        return None if value is None else str(value)

    content_length_value = header("Content-Length")
    content_length: int | None = None
    if content_length_value is not None:
        try:
            content_length = int(content_length_value)
        except ValueError as exc:
            raise AcquisitionError("HTTP Content-Length is not an integer") from exc
        if content_length < 0:
            raise AcquisitionError("HTTP Content-Length may not be negative")

    geturl = getattr(response, "geturl", None)
    final_url = str(geturl()) if callable(geturl) else requested_url
    status_value = getattr(response, "status", None)
    status_code = int(status_value) if status_value is not None else None
    return HttpResponseMetadata(
        requested_url=requested_url,
        final_url=final_url,
        status_code=status_code,
        etag=header("ETag"),
        last_modified=header("Last-Modified"),
        content_length=content_length,
        content_type=header("Content-Type"),
    )


def _download_http_archive(
    *,
    url: str,
    destination: Path,
    expected_size: int | None,
    expected_hash: str,
) -> tuple[int, str, HttpResponseMetadata]:
    """Download one ZIP as opaque bytes and capture available HTTP provenance."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"Project-Echoes/{__version__} source-acquisition"},
    )
    digest = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(f"{destination.name}.part")
    metadata: HttpResponseMetadata | None = None
    try:
        with urllib.request.urlopen(request, timeout=120) as response, part_path.open("xb") as out:
            metadata = _http_metadata(response, requested_url=url)
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

    assert metadata is not None
    actual_hash = digest.hexdigest()
    if expected_size is not None and size != expected_size:
        part_path.unlink(missing_ok=True)
        raise AcquisitionError(
            f"size mismatch for {url}: expected {expected_size}, received {size} bytes"
        )
    if metadata.content_length is not None and metadata.content_length != size:
        part_path.unlink(missing_ok=True)
        raise AcquisitionError(
            f"HTTP Content-Length mismatch for {url}: "
            f"header={metadata.content_length}, received={size}"
        )
    if actual_hash != expected_hash:
        part_path.unlink(missing_ok=True)
        raise AcquisitionError(
            f"SHA-256 mismatch for {url}: expected {expected_hash}, calculated {actual_hash}"
        )
    part_path.replace(destination)
    return size, actual_hash, metadata


def _zip_member_path(name: str, *, is_directory: bool) -> str:
    candidate = name[:-1] if is_directory and name.endswith("/") else name
    try:
        return _validated_relative_path(candidate, field_name="ZIP member")
    except ValueError as exc:
        raise AcquisitionError(str(exc)) from exc


def _expected_archive_directories(expected_files: set[str]) -> set[str]:
    directories: set[str] = set()
    for expected in expected_files:
        for parent in PurePosixPath(expected).parents:
            if parent.as_posix() != ".":
                directories.add(parent.as_posix())
    return directories


def _validated_zip_inventory(
    archive_path: Path,
    *,
    expected_files: set[str],
) -> tuple[list[zipfile.ZipInfo], int, int]:
    """Validate a ZIP completely before returning its exact file inventory."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if not infos:
                raise AcquisitionError("ZIP archive is empty")
            if len(infos) > MAX_ZIP_MEMBERS:
                raise AcquisitionError(
                    f"ZIP archive contains {len(infos)} members; limit is {MAX_ZIP_MEMBERS}"
                )

            expected_directories = _expected_archive_directories(expected_files)
            file_infos: list[zipfile.ZipInfo] = []
            seen_paths: set[str] = set()
            seen_casefolded: set[str] = set()
            compressed_total = 0
            uncompressed_total = 0
            for info in infos:
                is_directory = info.is_dir()
                normalized = _zip_member_path(info.filename, is_directory=is_directory)
                if normalized in seen_paths or normalized.casefold() in seen_casefolded:
                    raise AcquisitionError(
                        f"ZIP archive contains duplicate or case-colliding member: {normalized}"
                    )
                seen_paths.add(normalized)
                seen_casefolded.add(normalized.casefold())

                if info.flag_bits & 0x1:
                    raise AcquisitionError(f"encrypted ZIP member is not permitted: {normalized}")
                if info.compress_type not in ALLOWED_ZIP_COMPRESSION:
                    raise AcquisitionError(f"unsupported ZIP compression for member: {normalized}")

                unix_mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(unix_mode)
                allowed_type = stat.S_IFDIR if is_directory else stat.S_IFREG
                if file_type not in {0, allowed_type}:
                    raise AcquisitionError(
                        f"symlink or special ZIP member is not permitted: {normalized}"
                    )
                if not is_directory and unix_mode & 0o111:
                    raise AcquisitionError(
                        f"executable ZIP member mode is not permitted: {normalized}"
                    )

                if is_directory:
                    if normalized not in expected_directories:
                        raise AcquisitionError(f"unexpected ZIP directory member: {normalized}")
                    continue

                if PurePosixPath(normalized).suffix.casefold() in (
                    EXECUTABLE_OR_NESTED_ARCHIVE_SUFFIXES
                ):
                    raise AcquisitionError(
                        f"executable or nested archive member is not permitted: {normalized}"
                    )
                file_infos.append(info)
                compressed_total += info.compress_size
                uncompressed_total += info.file_size

            actual_files = {
                _zip_member_path(info.filename, is_directory=False) for info in file_infos
            }
            if actual_files != expected_files:
                missing = sorted(expected_files - actual_files)
                unexpected = sorted(actual_files - expected_files)
                raise AcquisitionError(
                    "ZIP inventory does not match the approved manifest; "
                    f"missing={missing}, unexpected={unexpected}"
                )
            if uncompressed_total > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise AcquisitionError(
                    f"ZIP uncompressed size {uncompressed_total} exceeds safety limit"
                )
            if compressed_total == 0 and uncompressed_total:
                raise AcquisitionError("ZIP declares zero compressed bytes for nonempty content")
            if (
                compressed_total
                and uncompressed_total / compressed_total > MAX_ZIP_COMPRESSION_RATIO
            ):
                raise AcquisitionError("ZIP compression ratio exceeds safety limit")

            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise AcquisitionError(f"ZIP integrity check failed for member: {corrupt_member}")
            return file_infos, compressed_total, uncompressed_total
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise AcquisitionError(
            f"invalid or unsupported ZIP archive {archive_path.name}: {exc}"
        ) from exc


def _extract_zip_safely(
    archive_path: Path,
    *,
    staging: Path,
    source_url: str,
    expected_files: set[str],
    expected_hashes: dict[str, str],
) -> tuple[list[AcquiredFile], int, int]:
    file_infos, compressed_total, uncompressed_total = _validated_zip_inventory(
        archive_path,
        expected_files=expected_files,
    )
    acquired: list[AcquiredFile] = []
    staging_root = staging.resolve()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in sorted(file_infos, key=lambda item: item.filename):
                relative = _zip_member_path(info.filename, is_directory=False)
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.resolve().is_relative_to(staging_root):
                    raise AcquisitionError(f"ZIP member escapes acquisition root: {relative}")
                part_path = destination.with_name(f"{destination.name}.part")
                digest = hashlib.sha256()
                size = 0
                with archive.open(info, "r") as source_handle, part_path.open("xb") as out:
                    while block := source_handle.read(DOWNLOAD_CHUNK_SIZE):
                        out.write(block)
                        digest.update(block)
                        size += len(block)
                        if size > info.file_size:
                            raise AcquisitionError(
                                f"ZIP member exceeds declared size during extraction: {relative}"
                            )
                actual_hash = digest.hexdigest()
                if size != info.file_size:
                    raise AcquisitionError(
                        f"ZIP member size mismatch for {relative}: "
                        f"declared={info.file_size}, extracted={size}"
                    )
                expected_hash = expected_hashes.get(relative)
                if expected_hash is None or actual_hash != expected_hash:
                    raise AcquisitionError(
                        f"SHA-256 mismatch for extracted ZIP member {relative}: "
                        f"expected={expected_hash}, calculated={actual_hash}"
                    )
                part_path.replace(destination)
                acquired.append(
                    AcquiredFile(
                        relative_path=relative,
                        source_url=source_url,
                        size_bytes=size,
                        sha256=actual_hash,
                        archive_member=relative,
                    )
                )
    except Exception:
        for part_path in staging.rglob("*.part"):
            part_path.unlink(missing_ok=True)
        raise
    return acquired, compressed_total, uncompressed_total


def _validate_text_envelope(raw: bytes, schema: SourceArchiveSchema) -> str:
    boms = {
        "utf-8": b"\xef\xbb\xbf",
        "utf-16-le": b"\xff\xfe",
        "utf-16-be": b"\xfe\xff",
    }
    present_bom = next((name for name, value in boms.items() if raw.startswith(value)), None)
    expected_bom = None if schema.byte_order_mark == "none" else schema.byte_order_mark
    if present_bom != expected_bom:
        raise AcquisitionError(
            f"archive data-file BOM mismatch: expected={expected_bom}, observed={present_bom}"
        )

    without_crlf = raw.replace(b"\r\n", b"")
    conventions: set[str] = set()
    if b"\r\n" in raw:
        conventions.add("crlf")
    if b"\n" in without_crlf:
        conventions.add("lf")
    if b"\r" in without_crlf:
        conventions.add("cr")
    observed_newline = next(iter(conventions)) if len(conventions) == 1 else "mixed"
    if observed_newline != schema.newline_convention:
        raise AcquisitionError(
            "archive data-file newline mismatch: "
            f"expected={schema.newline_convention}, observed={observed_newline}"
        )

    codec = schema.encoding
    if schema.byte_order_mark == "utf-8" and codec.casefold().replace("_", "-") == "utf-8":
        codec = "utf-8-sig"
    try:
        return raw.decode(codec)
    except (LookupError, UnicodeDecodeError) as exc:
        raise AcquisitionError(
            f"could not decode archive data file as {schema.encoding}: {exc}"
        ) from exc


def canonical_delimited_record_stream_sha256(
    path: Path,
    *,
    schema: SourceArchiveSchema,
) -> str:
    """Hash every parsed post-header record using a versioned canonical encoding."""
    text = _validate_text_envelope(path.read_bytes(), schema)
    try:
        rows = csv.reader(io.StringIO(text, newline=""), delimiter=schema.delimiter, strict=True)
        header = next(rows)
        if header != schema.header:
            raise AcquisitionError(
                f"archive data-file header mismatch: expected={schema.header}, observed={header}"
            )
        digest = hashlib.sha256()
        digest.update(b"echoes:canonical-delimited-source-record-stream\0")
        digest.update(schema.canonical_record_stream_schema_version.encode("utf-8"))
        digest.update(b"\0")
        occurrences: dict[bytes, int] = {}
        for fields in rows:
            base = json.dumps(
                {"fields": fields},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            occurrence = occurrences.get(base, 0)
            occurrences[base] = occurrence + 1
            canonical = json.dumps(
                {"duplicate_occurrence_ordinal": occurrence, "fields": fields},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            digest.update(canonical)
            digest.update(b"\n")
        return digest.hexdigest()
    except csv.Error as exc:
        raise AcquisitionError(f"could not parse canonical delimited record stream: {exc}") from exc


def _canonical_record_stream_sha256(source: SourceManifest, root: Path) -> str:
    schema = source.archive_schema
    if schema is None:
        raise AcquisitionError("content-addressed ZIP source has no archive schema")
    data_path = root / schema.data_file
    if source.ingest_adapter == "echoes.benchmarks.openbible":
        try:
            from echoes.benchmarks.openbible import (
                OpenBibleParseError,
                canonical_source_record_stream_sha256,
            )
        except ImportError as exc:
            raise AcquisitionError("OpenBible canonical stream adapter is unavailable") from exc
        try:
            digest = canonical_source_record_stream_sha256(
                data_path,
                schema_version=schema.canonical_record_stream_schema_version,
            )
        except OpenBibleParseError as exc:
            raise AcquisitionError(f"OpenBible canonical stream validation failed: {exc}") from exc
    else:
        digest = canonical_delimited_record_stream_sha256(data_path, schema=schema)
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise AcquisitionError("canonical record-stream adapter returned an invalid SHA-256")
    return digest


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


def _acquire_http_zip(
    source: SourceManifest,
    staging: Path,
) -> tuple[list[AcquiredFile], AcquiredArchive, str]:
    assert source.acquisition is not None
    assert source.acquisition.archive_sha256 is not None
    assert source.archive_schema is not None
    archive_spec = source.acquisition.files[0]
    archive_relative = f"{ARCHIVE_DIRECTORY_NAME}/{archive_spec.path}"
    try:
        archive_relative = _validated_relative_path(
            archive_relative,
            field_name="local archive relative_path",
        )
    except ValueError as exc:
        raise AcquisitionError(str(exc)) from exc
    archive_path = staging / archive_relative
    size, archive_hash, metadata = _download_http_archive(
        url=archive_spec.url,
        destination=archive_path,
        expected_size=archive_spec.size_bytes,
        expected_hash=source.acquisition.archive_sha256,
    )
    files, compressed_total, uncompressed_total = _extract_zip_safely(
        archive_path,
        staging=staging,
        source_url=archive_spec.url,
        expected_files=set(source.expected_files),
        expected_hashes=source.file_hashes,
    )
    canonical_hash = _canonical_record_stream_sha256(source, staging)
    archive = AcquiredArchive(
        relative_path=archive_relative,
        size_bytes=size,
        sha256=archive_hash,
        member_count=len(files),
        compressed_size_bytes=compressed_total,
        uncompressed_size_bytes=uncompressed_total,
        http=metadata,
    )
    return files, archive, canonical_hash


def _configure_canonical_byte_checkout(checkout: Path) -> None:
    """Force byte-identical checkouts so hashes always cover canonical blob bytes.

    Windows text-mode Git checkouts rewrite LF to CRLF, silently changing the
    bytes that reach the hasher.  Disabling ``core.autocrlf`` and declaring
    ``* -text`` in ``.git/info/attributes`` (the highest-precedence
    gitattributes source, overriding any upstream ``.gitattributes``) disables
    every text conversion, so working-tree files carry the pinned commit's
    exact blob bytes.
    """
    _run_git(["config", "core.autocrlf", "false"], cwd=checkout)
    attributes_path = checkout / ".git" / "info" / "attributes"
    attributes_path.parent.mkdir(parents=True, exist_ok=True)
    attributes_path.write_text("* -text\n", encoding="ascii")


def _acquire_git_sparse(source: SourceManifest, staging: Path) -> list[AcquiredFile]:
    assert source.acquisition is not None
    spec = source.acquisition
    assert spec.repository_url is not None
    assert spec.upstream_commit is not None
    checkout = staging.parent / f".{staging.name}.checkout-{uuid4().hex}"
    try:
        _run_git(["init", "--quiet", str(checkout)])
        _configure_canonical_byte_checkout(checkout)
        _run_git(["remote", "add", "origin", spec.repository_url], cwd=checkout)
        _run_git(["config", "remote.origin.promisor", "true"], cwd=checkout)
        _run_git(["config", "remote.origin.partialclonefilter", "blob:none"], cwd=checkout)
        _run_git(["sparse-checkout", "init", "--cone"], cwd=checkout)
        # Suffix-less include paths are sparse-checkout directories; paths
        # with a file suffix (README.md, LICENSE.md) ride along from the root.
        sparse_directories = [path for path in spec.include_paths if not Path(path).suffix]
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
    if source.acquisition.method == "http_zip" and force:
        raise AcquisitionError(
            "--force may not replace a content-addressed ZIP acquisition; "
            "verify the existing snapshot instead"
        )
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
        archive: AcquiredArchive | None = None
        canonical_stream_hash: str | None = None
        if source.acquisition.method == "http_files":
            acquired_files = _acquire_http_files(source, staging)
        elif source.acquisition.method == "http_zip":
            acquired_files, archive, canonical_stream_hash = _acquire_http_zip(source, staging)
        else:
            acquired_files = _acquire_git_sparse(source, staging)

        receipt = AcquisitionReceipt(
            schema_version=2 if source.acquisition.method == "http_zip" else 1,
            source_id=source.source_id,
            source_version=source.version_or_commit or source.acquisition.version_label,
            version_label=source.acquisition.version_label,
            upstream_commit=(
                None
                if source.acquisition.method == "http_zip"
                else source.acquisition.upstream_commit
            ),
            acquired_at=datetime.now(tz=UTC),
            files=acquired_files,
            archive=archive,
            canonical_record_stream_schema_version=(
                source.archive_schema.canonical_record_stream_schema_version
                if source.acquisition.method == "http_zip" and source.archive_schema is not None
                else None
            ),
            canonical_record_stream_sha256=canonical_stream_hash,
            acquisition_command=command or f"echoes acquire-source {source.source_id}",
            tool_version=__version__,
        )
        _write_receipt(receipt, staging / ACQUISITION_RECEIPT_NAME)

        if target.exists():
            target.replace(backup)
        try:
            # ``Path.replace`` can fail for directories on Windows even when
            # the destination is absent. The same-volume rename remains atomic
            # and matches the artifact writers used elsewhere in the project.
            _atomic_directory_rename(staging, target)
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
    if path.is_symlink():
        raise AcquisitionError(f"acquisition receipt may not be a symlink: {path}")
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
    if receipt.version_label != source.acquisition.version_label:
        raise AcquisitionError("receipt version label does not match the source manifest")
    if source.acquisition.method == "http_zip":
        if receipt.schema_version != 2:
            raise AcquisitionError("content-addressed ZIP acquisition requires a schema-2 receipt")
        if receipt.upstream_commit is not None:
            raise AcquisitionError("content-addressed ZIP receipt unexpectedly contains a commit")
    elif receipt.upstream_commit != source.acquisition.upstream_commit:
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
    if source.acquisition.method in {"http_files", "http_zip"} and (
        receipt_paths != expected_paths
    ):
        unexpected = sorted(receipt_paths - expected_paths)
        missing = sorted(expected_paths - receipt_paths)
        raise AcquisitionError(
            f"receipt HTTP file inventory differs from manifest: "
            f"missing={missing}, unexpected={unexpected}"
        )
    if (
        source.acquisition.expected_file_count is not None
        and len(receipt_paths) != source.acquisition.expected_file_count
    ):
        raise AcquisitionError(
            f"receipt contains {len(receipt_paths)} files; "
            f"expected {source.acquisition.expected_file_count}"
        )

    for local_path in directory.rglob("*"):
        if local_path.is_symlink():
            raise AcquisitionError(
                f"local acquisition contains a symlink: "
                f"{local_path.relative_to(directory).as_posix()}"
            )

    actual_paths = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != ACQUISITION_RECEIPT_NAME
    }
    expected_local_paths = set(receipt_paths)
    if receipt.archive is not None:
        expected_local_paths.add(receipt.archive.relative_path)
    if actual_paths != expected_local_paths:
        missing = sorted(expected_local_paths - actual_paths)
        unexpected = sorted(actual_paths - expected_local_paths)
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

    if source.acquisition.method == "http_zip":
        assert source.acquisition.archive_sha256 is not None
        assert source.archive_schema is not None
        if receipt.archive is None:
            raise AcquisitionError("schema-2 receipt is missing archive metadata")
        archive_spec = source.acquisition.files[0]
        expected_archive_path = f"{ARCHIVE_DIRECTORY_NAME}/{archive_spec.path}"
        if receipt.archive.relative_path != expected_archive_path:
            raise AcquisitionError("receipt archive path does not match the source manifest")
        if receipt.archive.http.requested_url != archive_spec.url:
            raise AcquisitionError("receipt acquisition URL does not match the source manifest")
        if receipt.archive.sha256 != source.acquisition.archive_sha256:
            raise AcquisitionError("receipt archive SHA-256 does not match the source manifest")
        archive_path = directory / receipt.archive.relative_path
        actual_archive_size = archive_path.stat().st_size
        if actual_archive_size != receipt.archive.size_bytes:
            raise AcquisitionError(
                "archive size mismatch: "
                f"receipt={receipt.archive.size_bytes}, actual={actual_archive_size}"
            )
        if (
            receipt.archive.http.content_length is not None
            and receipt.archive.http.content_length != actual_archive_size
        ):
            raise AcquisitionError("receipt HTTP Content-Length does not match archive bytes")
        actual_archive_hash = sha256_file(archive_path)
        if actual_archive_hash != receipt.archive.sha256:
            raise AcquisitionError(
                f"archive SHA-256 mismatch: receipt={receipt.archive.sha256}, "
                f"actual={actual_archive_hash}"
            )
        file_infos, compressed_total, uncompressed_total = _validated_zip_inventory(
            archive_path,
            expected_files=expected_paths,
        )
        if len(file_infos) != receipt.archive.member_count:
            raise AcquisitionError("archive member count does not match receipt")
        if compressed_total != receipt.archive.compressed_size_bytes:
            raise AcquisitionError("archive compressed size does not match receipt")
        if uncompressed_total != receipt.archive.uncompressed_size_bytes:
            raise AcquisitionError("archive uncompressed size does not match receipt")
        if (
            receipt.canonical_record_stream_schema_version
            != source.archive_schema.canonical_record_stream_schema_version
        ):
            raise AcquisitionError(
                "receipt canonical stream schema version does not match source manifest"
            )
        canonical_hash = _canonical_record_stream_sha256(source, directory)
        if canonical_hash != receipt.canonical_record_stream_sha256:
            raise AcquisitionError(
                "canonical record-stream SHA-256 mismatch: "
                f"receipt={receipt.canonical_record_stream_sha256}, actual={canonical_hash}"
            )
    return directory, receipt


def audit_manifest_hashes(
    source: SourceManifest,
    *,
    data_root: Path = Path("data"),
) -> list[str] | None:
    """Recompute canonical SHA-256 values for locally present manifest-hashed files.

    Returns ``None`` when the source declares no acquisition or its raw
    directory is absent locally, otherwise a list of mismatch findings.  All
    recorded hashes are canonical-byte SHA-256 values, so any divergence means
    the local bytes no longer match the pinned upstream bytes (for example,
    after a text-mode line-ending rewrite).
    """
    if source.acquisition is None or not source.file_hashes:
        return None
    directory = data_root / "raw" / source.source_id / source.acquisition.version_label
    if not directory.is_dir():
        return None
    if source.acquisition.method == "http_zip":
        try:
            verify_acquisition(source, data_root=data_root)
        except AcquisitionError as exc:
            return [f"{source.source_id}: {exc}"]
        return []
    findings: list[str] = []
    for relative_path, expected_hash in sorted(source.file_hashes.items()):
        path = directory / relative_path
        if not path.is_file():
            findings.append(f"{source.source_id}: manifest-hashed file is missing: {relative_path}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash.lower():
            findings.append(
                f"{source.source_id}: canonical SHA-256 mismatch for {relative_path}: "
                f"manifest={expected_hash.lower()}, local={actual_hash}"
            )
    return findings
