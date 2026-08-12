"""Authenticated object-storage inputs and final artifact transfer primitives.

The production adapter deliberately delegates transport to ``rclone`` while
keeping Backblaze credentials in the child-process environment.  Canonical
artifact authentication does not trust a backend's native object hash as a
SHA-256 substitute: the manifest and every manifest-listed file are hashed
again after materialization.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, Protocol, runtime_checkable
from uuid import uuid4

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_HASH_LENGTHS = {"md5": 32, "sha1": 40, "sha256": 64}
_RCLONE_REMOTE = "echoes_final_discovery_b2"
_B2_KEY_ID_ENV = "B2_APPLICATION_KEY_ID"
_B2_APPLICATION_KEY_ENV = "B2_APPLICATION_KEY"
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024


class ObjectStoreError(RuntimeError):
    """Base error for bounded object-store operations."""


class InputAuthenticationError(ObjectStoreError):
    """Raised when an input fails its frozen identity or content contract."""


class ObjectStoreConflictError(ObjectStoreError):
    """Raised instead of silently replacing a local or remote artifact."""


@dataclass(frozen=True, slots=True)
class ObjectStoreIdentity:
    """Exact provider, bucket, and recursively inventoried prefix identity."""

    provider: str
    bucket: str
    prefix: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", self.provider):
            raise ValueError("object-store provider must be a safe lowercase identifier")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,127}", self.bucket):
            raise ValueError("object-store bucket must be a safe nonempty name")
        normalized = normalize_relative_object_path(self.prefix, label="object-store prefix")
        object.__setattr__(self, "prefix", normalized)

    @property
    def canonical_uri(self) -> str:
        """Return a secret-free, stable identity string."""

        return f"{self.provider}://{self.bucket}/{self.prefix}"


@dataclass(frozen=True, slots=True)
class ObjectInventoryEntry:
    """One recursively discovered regular object with its backend hash."""

    path: str
    size: int
    hash_algorithm: str
    digest: str

    def __post_init__(self) -> None:
        normalized = normalize_relative_object_path(self.path, label="object path")
        algorithm = _normalize_hash_algorithm(self.hash_algorithm)
        digest = self.digest.lower()
        expected_length = _HASH_LENGTHS.get(algorithm)
        if self.size < 0:
            raise ValueError("object size cannot be negative")
        if expected_length is None or not re.fullmatch(rf"[a-f0-9]{{{expected_length}}}", digest):
            raise ValueError(f"invalid {algorithm} object digest: {normalized}")
        object.__setattr__(self, "path", normalized)
        object.__setattr__(self, "hash_algorithm", algorithm)
        object.__setattr__(self, "digest", digest)


@dataclass(frozen=True, slots=True)
class ObjectInventory:
    """Canonical recursive file inventory for one exact store prefix."""

    identity: ObjectStoreIdentity
    objects: tuple[ObjectInventoryEntry, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.objects, key=lambda item: item.path))
        paths = [item.path for item in ordered]
        if len(paths) != len(set(paths)):
            raise ValueError("object inventory contains duplicate paths")
        object.__setattr__(self, "objects", ordered)

    @property
    def object_count(self) -> int:
        return len(self.objects)

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.objects)

    @property
    def by_path(self) -> dict[str, ObjectInventoryEntry]:
        return {item.path: item for item in self.objects}

    @property
    def sha256(self) -> str:
        payload = {
            "identity": {
                "provider": self.identity.provider,
                "bucket": self.identity.bucket,
                "prefix": self.identity.prefix,
            },
            "objects": [
                {
                    "path": item.path,
                    "size": item.size,
                    "hash_algorithm": item.hash_algorithm,
                    "digest": item.digest,
                }
                for item in self.objects
            ],
        }
        return _sha256_bytes(_canonical_json_bytes(payload))

    @property
    def transfer_sha256(self) -> str:
        """Hash portable identity/path/size state for cross-backend transfer checks.

        Backend-native digest algorithms are deliberately excluded: a local
        inventory has SHA-256 while Backblaze B2 commonly exposes SHA-1.  Exact
        content equivalence is established separately by ``check_tree`` (and
        by rclone ``check --download`` for B2).
        """

        payload = {
            "identity": {
                "provider": self.identity.provider,
                "bucket": self.identity.bucket,
                "prefix": self.identity.prefix,
            },
            "objects": [
                {
                    "path": item.path,
                    "size": item.size,
                }
                for item in self.objects
            ],
        }
        return _sha256_bytes(_canonical_json_bytes(payload))


@dataclass(frozen=True, slots=True)
class InputExpectation:
    """Frozen identity needed to accept one canonical table-hash artifact."""

    identity: ObjectStoreIdentity
    table_hashes_sha256: str
    table_hashes_path: str = "table-hashes.json"
    expected_inventory_sha256: str | None = None
    expected_object_count: int | None = None
    expected_total_size: int | None = None

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.table_hashes_sha256):
            raise ValueError("table-hashes.json requires a lowercase SHA-256")
        normalized = normalize_relative_object_path(
            self.table_hashes_path,
            label="table-hashes path",
        )
        object.__setattr__(self, "table_hashes_path", normalized)
        if self.expected_inventory_sha256 is not None and not _SHA256.fullmatch(
            self.expected_inventory_sha256
        ):
            raise ValueError("expected object inventory requires a lowercase SHA-256")
        if self.expected_object_count is not None and self.expected_object_count < 1:
            raise ValueError("expected object count must be positive")
        if self.expected_total_size is not None and self.expected_total_size < 0:
            raise ValueError("expected total size cannot be negative")


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    """Evidence that an exact remote inventory was materialized and rehashed."""

    identity: ObjectStoreIdentity
    remote_inventory_sha256: str | None
    materialized_inventory_sha256: str
    table_hashes_sha256: str
    object_count: int
    total_size: int
    listed_file_sha256: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for label, digest in (
            ("materialized inventory", self.materialized_inventory_sha256),
            ("table-hashes.json", self.table_hashes_sha256),
        ):
            if not _SHA256.fullmatch(digest):
                raise ValueError(f"{label} receipt value must be SHA-256")
        if self.remote_inventory_sha256 is not None and not _SHA256.fullmatch(
            self.remote_inventory_sha256
        ):
            raise ValueError("remote inventory receipt value must be SHA-256")
        if self.object_count < 1 or self.total_size < 0:
            raise ValueError("materialization receipt counts are invalid")
        normalized: list[tuple[str, str]] = []
        for raw_path, digest in self.listed_file_sha256:
            path = normalize_relative_object_path(raw_path, label="receipt file path")
            if not _SHA256.fullmatch(digest):
                raise ValueError(f"receipt file value must be SHA-256: {path}")
            normalized.append((path, digest))
        ordered = tuple(sorted(normalized))
        if len({path for path, _ in ordered}) != len(ordered):
            raise ValueError("materialization receipt contains duplicate file paths")
        object.__setattr__(self, "listed_file_sha256", ordered)

    @property
    def sha256(self) -> str:
        return _sha256_bytes(
            _canonical_json_bytes(
                {
                    "identity": {
                        "provider": self.identity.provider,
                        "bucket": self.identity.bucket,
                        "prefix": self.identity.prefix,
                    },
                    "remote_inventory_sha256": self.remote_inventory_sha256,
                    "materialized_inventory_sha256": self.materialized_inventory_sha256,
                    "table_hashes_sha256": self.table_hashes_sha256,
                    "object_count": self.object_count,
                    "total_size": self.total_size,
                    "listed_file_sha256": dict(self.listed_file_sha256),
                }
            )
        )


@dataclass(frozen=True, slots=True)
class TransferVerificationReceipt:
    """Exact local-versus-object-store verification result."""

    identity: ObjectStoreIdentity
    local_inventory_sha256: str
    remote_inventory_sha256: str
    object_count: int
    total_size: int

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.local_inventory_sha256) or not _SHA256.fullmatch(
            self.remote_inventory_sha256
        ):
            raise ValueError("transfer inventory receipt values must be SHA-256")
        if self.local_inventory_sha256 != self.remote_inventory_sha256:
            raise ValueError("verified transfer inventories must have one portable identity")
        if self.object_count < 0 or self.total_size < 0:
            raise ValueError("transfer receipt counts cannot be negative")


@dataclass(frozen=True, slots=True)
class PackageReceipt:
    """Deterministic uncompressed tar package identity."""

    archive_path: Path
    archive_size: int
    archive_sha256: str
    source_inventory_sha256: str
    source_file_count: int

    def __post_init__(self) -> None:
        if self.archive_size < 0 or self.source_file_count < 1:
            raise ValueError("package receipt counts are invalid")
        if not _SHA256.fullmatch(self.archive_sha256) or not _SHA256.fullmatch(
            self.source_inventory_sha256
        ):
            raise ValueError("package receipt values must be SHA-256")


@runtime_checkable
class ObjectStore(Protocol):
    """Minimal prefix-bound store used by input and upload orchestration."""

    @property
    def identity(self) -> ObjectStoreIdentity: ...

    def inventory(self) -> ObjectInventory: ...

    def read_bytes(self, relative_path: str, *, maximum_bytes: int) -> bytes: ...

    def download_tree(self, destination: Path) -> ObjectInventory: ...

    def upload_tree(self, source: Path) -> ObjectInventory: ...

    def resume_upload_tree(self, source: Path) -> ObjectInventory: ...

    def check_tree(self, source: Path) -> TransferVerificationReceipt: ...


def normalize_relative_object_path(value: str, *, label: str) -> str:
    """Return one confined normalized POSIX path."""

    if not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or value != posix.as_posix()
        or value in {".", ".."}
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    return value


def sha256_file(path: Path) -> str:
    """Compute one file SHA-256 without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory_directory(root: Path, identity: ObjectStoreIdentity) -> ObjectInventory:
    """Recursively inventory regular files while rejecting links/reparse points."""

    if _is_reparse_point(root):
        raise ObjectStoreError(f"inventory root is a link/reparse point: {root}")
    resolved_root = root.resolve()
    if not resolved_root.is_dir() or _is_reparse_point(resolved_root):
        raise ObjectStoreError(f"inventory root is not a real directory: {root}")
    entries: list[ObjectInventoryEntry] = []

    def walk_error(error: OSError) -> None:
        raise ObjectStoreError(f"could not enumerate object inventory: {error}")

    for directory, directory_names, file_names in os.walk(
        resolved_root,
        topdown=True,
        followlinks=False,
        onerror=walk_error,
    ):
        current = Path(directory)
        for name in list(directory_names):
            child = current / name
            if _is_reparse_point(child):
                raise ObjectStoreError(
                    "object inventory contains a directory link/reparse point: "
                    f"{child.relative_to(resolved_root).as_posix()}"
                )
        for name in file_names:
            child = current / name
            relative = child.relative_to(resolved_root).as_posix()
            if _is_reparse_point(child) or not child.is_file():
                raise ObjectStoreError(
                    f"object inventory entry is not a real regular file: {relative}"
                )
            entries.append(
                ObjectInventoryEntry(
                    path=relative,
                    size=child.stat().st_size,
                    hash_algorithm="sha256",
                    digest=sha256_file(child),
                )
            )
    return ObjectInventory(identity=identity, objects=tuple(entries))


class LocalObjectStore:
    """Filesystem-backed object store for bounded tests and offline fixtures."""

    def __init__(
        self,
        root: Path,
        *,
        identity: ObjectStoreIdentity | None = None,
    ) -> None:
        if root.exists() and _is_reparse_point(root):
            raise ObjectStoreError(f"local object-store root is unsafe: {root}")
        self._root = root.resolve()
        self._identity = identity or ObjectStoreIdentity(
            provider="local",
            bucket="fixture",
            prefix="objects",
        )
        if self._root.exists() and (not self._root.is_dir() or _is_reparse_point(self._root)):
            raise ObjectStoreError(f"local object-store root is unsafe: {root}")

    @property
    def identity(self) -> ObjectStoreIdentity:
        return self._identity

    def inventory(self) -> ObjectInventory:
        if not self._root.exists():
            return ObjectInventory(identity=self.identity, objects=())
        return inventory_directory(self._root, self.identity)

    def read_bytes(self, relative_path: str, *, maximum_bytes: int) -> bytes:
        relative = normalize_relative_object_path(relative_path, label="object path")
        source = self._safe_source(relative)
        size = source.stat().st_size
        if maximum_bytes < 0 or size > maximum_bytes:
            raise ObjectStoreError(f"object exceeds bounded read limit: {relative}")
        return source.read_bytes()

    def download_tree(self, destination: Path) -> ObjectInventory:
        source_inventory = self.inventory()
        _require_empty_directory(destination, label="materialization destination")
        destination.mkdir(parents=True, exist_ok=True)
        for entry in source_inventory.objects:
            source = self._safe_source(entry.path)
            target = _new_confined_file(destination, entry.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_file_new(source, target)
        return source_inventory

    def upload_tree(self, source: Path) -> ObjectInventory:
        source_inventory = inventory_directory(source, self.identity)
        if self.inventory().objects:
            raise ObjectStoreConflictError(
                f"refusing to replace nonempty object-store prefix: {self.identity.canonical_uri}"
            )
        self._root.mkdir(parents=True, exist_ok=True)
        for entry in source_inventory.objects:
            source_path = _existing_confined_file(source, entry.path)
            target = _new_confined_file(self._root, entry.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_file_new(source_path, target)
        return self.inventory()

    def resume_upload_tree(self, source: Path) -> ObjectInventory:
        """Add only absent files to an authenticated partial local prefix."""

        source_inventory = inventory_directory(source, self.identity)
        remote_inventory = self.inventory()
        _require_resume_subset(source_inventory, remote_inventory, compare_digest=True)
        self._root.mkdir(parents=True, exist_ok=True)
        remote_paths = set(remote_inventory.by_path)
        for entry in source_inventory.objects:
            if entry.path in remote_paths:
                continue
            source_path = _existing_confined_file(source, entry.path)
            target = _new_confined_file(self._root, entry.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_file_new(source_path, target)
        return self.inventory()

    def check_tree(self, source: Path) -> TransferVerificationReceipt:
        local = inventory_directory(source, self.identity)
        remote = self.inventory()
        _require_equal_inventories(local, remote, compare_digest=True)
        return TransferVerificationReceipt(
            identity=self.identity,
            local_inventory_sha256=local.transfer_sha256,
            remote_inventory_sha256=remote.transfer_sha256,
            object_count=remote.object_count,
            total_size=remote.total_size,
        )

    def _safe_source(self, relative_path: str) -> Path:
        return _existing_confined_file(self._root, relative_path)


RcloneRunner = Callable[
    [Sequence[str], Mapping[str, str]],
    subprocess.CompletedProcess[bytes],
]


class RcloneB2ObjectStore:
    """Prefix-bound Backblaze B2 adapter with environment-only credentials."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str,
        rclone_binary: str = "rclone",
        runner: RcloneRunner | None = None,
    ) -> None:
        self._identity = ObjectStoreIdentity(provider="b2", bucket=bucket, prefix=prefix)
        if not rclone_binary or any(character in rclone_binary for character in "\r\n\x00"):
            raise ValueError("rclone binary must be one nonempty executable path")
        self._rclone_binary = rclone_binary
        self._runner = runner or _run_subprocess

    @property
    def identity(self) -> ObjectStoreIdentity:
        return self._identity

    def inventory(self) -> ObjectInventory:
        completed = self._run(
            "recursive object inventory",
            [
                "lsjson",
                self._remote(),
                "--recursive",
                "--files-only",
                "--hash",
                "--no-mimetype",
                "--no-modtime",
            ],
        )
        try:
            raw = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ObjectStoreError("rclone returned an invalid JSON object inventory") from exc
        if not isinstance(raw, list):
            raise ObjectStoreError("rclone object inventory root is not a list")
        entries: list[ObjectInventoryEntry] = []
        for value in raw:
            if not isinstance(value, dict):
                raise ObjectStoreError("rclone object inventory contains a non-object entry")
            if value.get("IsDir") is True:
                continue
            path = value.get("Path")
            size = value.get("Size")
            hashes = value.get("Hashes")
            if (
                not isinstance(path, str)
                or not isinstance(size, int)
                or not isinstance(hashes, dict)
            ):
                raise ObjectStoreError("rclone object inventory entry lacks path, size, or hashes")
            try:
                algorithm, digest = _preferred_rclone_hash(hashes, path=path)
                entries.append(
                    ObjectInventoryEntry(
                        path=path,
                        size=size,
                        hash_algorithm=algorithm,
                        digest=digest,
                    )
                )
            except ValueError as exc:
                raise ObjectStoreError(f"invalid rclone object inventory entry: {path}") from exc
        try:
            return ObjectInventory(identity=self.identity, objects=tuple(entries))
        except ValueError as exc:
            raise ObjectStoreError(f"invalid rclone object inventory: {exc}") from exc

    def read_bytes(self, relative_path: str, *, maximum_bytes: int) -> bytes:
        relative = normalize_relative_object_path(relative_path, label="object path")
        entry = self.inventory().by_path.get(relative)
        if entry is None:
            raise ObjectStoreError(f"object does not exist: {relative}")
        if maximum_bytes < 0 or entry.size > maximum_bytes:
            raise ObjectStoreError(f"object exceeds bounded read limit: {relative}")
        completed = self._run("bounded object read", ["cat", self._remote(relative)])
        if len(completed.stdout) != entry.size or len(completed.stdout) > maximum_bytes:
            raise ObjectStoreError(f"bounded object read returned an unexpected size: {relative}")
        return completed.stdout

    def download_tree(self, destination: Path) -> ObjectInventory:
        _require_empty_directory(destination, label="materialization destination")
        destination.mkdir(parents=True, exist_ok=True)
        inventory = self.inventory()
        self._run(
            "recursive object materialization",
            ["copy", self._remote(), str(destination), "--immutable"],
        )
        return inventory

    def upload_tree(self, source: Path) -> ObjectInventory:
        inventory_directory(source, self.identity)
        if self.inventory().objects:
            raise ObjectStoreConflictError(
                f"refusing to replace nonempty object-store prefix: {self.identity.canonical_uri}"
            )
        self._run(
            "immutable recursive upload",
            ["copy", str(source), self._remote(), "--immutable"],
        )
        return self.inventory()

    def resume_upload_tree(self, source: Path) -> ObjectInventory:
        """Resume an exact partial B2 upload without replacing any object."""

        local = inventory_directory(source, self.identity)
        remote = self.inventory()
        _require_resume_subset(local, remote, compare_digest=False)
        self._run(
            "immutable recursive upload resume",
            ["copy", str(source), self._remote(), "--immutable", "--checksum"],
        )
        return self.inventory()

    def check_tree(self, source: Path) -> TransferVerificationReceipt:
        local = inventory_directory(source, self.identity)
        remote = self.inventory()
        _require_equal_inventories(local, remote, compare_digest=False)
        # B2 commonly exposes SHA-1. --download makes rclone compare content
        # instead of accepting a missing common hash as verification.
        self._run(
            "download-based upload verification",
            ["check", str(source), self._remote(), "--download", "--combined", "-"],
        )
        return TransferVerificationReceipt(
            identity=self.identity,
            local_inventory_sha256=local.transfer_sha256,
            remote_inventory_sha256=remote.transfer_sha256,
            object_count=remote.object_count,
            total_size=remote.total_size,
        )

    def _remote(self, relative_path: str | None = None) -> str:
        suffix = self.identity.prefix
        if relative_path is not None:
            relative = normalize_relative_object_path(relative_path, label="object path")
            suffix = f"{suffix}/{relative}"
        return f"{_RCLONE_REMOTE}:{self.identity.bucket}/{suffix}"

    def _run(self, operation: str, arguments: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        key_id = os.environ.get(_B2_KEY_ID_ENV)
        application_key = os.environ.get(_B2_APPLICATION_KEY_ENV)
        if not key_id or not application_key:
            raise ObjectStoreError(
                f"{operation} requires {_B2_KEY_ID_ENV} and {_B2_APPLICATION_KEY_ENV}"
            )
        environment = dict(os.environ)
        environment.update(
            {
                f"RCLONE_CONFIG_{_RCLONE_REMOTE.upper()}_TYPE": "b2",
                f"RCLONE_CONFIG_{_RCLONE_REMOTE.upper()}_ACCOUNT": key_id,
                f"RCLONE_CONFIG_{_RCLONE_REMOTE.upper()}_KEY": application_key,
            }
        )
        argv = [
            self._rclone_binary,
            "--config",
            os.devnull,
            "--log-level",
            "ERROR",
            *arguments,
        ]
        try:
            completed = self._runner(argv, environment)
        except OSError as exc:
            raise ObjectStoreError(f"could not start rclone for {operation}: {exc}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")
            safe_stderr = _redact(stderr, (key_id, application_key)).strip()[:2000]
            detail = f": {safe_stderr}" if safe_stderr else ""
            raise ObjectStoreError(
                f"rclone {operation} failed with exit code {completed.returncode}{detail}"
            )
        return completed


def materialize_authenticated_input(
    store: ObjectStore,
    destination: Path,
    expectation: InputExpectation,
) -> MaterializationReceipt:
    """Materialize and SHA-256-authenticate one exact canonical object tree."""

    if store.identity != expectation.identity:
        raise InputAuthenticationError(
            "object-store identity differs from the frozen provider/bucket/prefix"
        )
    remote = store.inventory()
    _authenticate_inventory_expectations(remote, expectation)
    manifest_entry = remote.by_path.get(expectation.table_hashes_path)
    if manifest_entry is None:
        raise InputAuthenticationError(
            f"canonical hash manifest is absent: {expectation.table_hashes_path}"
        )
    if manifest_entry.size > _MAX_MANIFEST_BYTES:
        raise InputAuthenticationError("canonical hash manifest exceeds the bounded read limit")
    raw_manifest = store.read_bytes(
        expectation.table_hashes_path,
        maximum_bytes=_MAX_MANIFEST_BYTES,
    )
    if _sha256_bytes(raw_manifest) != expectation.table_hashes_sha256:
        raise InputAuthenticationError("canonical table-hashes.json SHA-256 differs")
    declared = _parse_table_hash_inventory(raw_manifest, expectation.table_hashes_path)
    expected_paths = set(declared) | {expectation.table_hashes_path}
    observed_paths = set(remote.by_path)
    if observed_paths != expected_paths:
        missing = sorted(expected_paths - observed_paths)
        unexpected = sorted(observed_paths - expected_paths)
        raise InputAuthenticationError(
            f"remote object inventory differs; missing={missing}, unexpected={unexpected}"
        )

    _require_empty_directory(destination, label="materialization destination")
    store.download_tree(destination)
    return verify_materialized_input(
        destination,
        expectation,
        remote_inventory=remote,
    )


def verify_materialized_input(
    materialized_root: Path,
    expectation: InputExpectation,
    *,
    remote_inventory: ObjectInventory | None = None,
) -> MaterializationReceipt:
    """Authenticate an already materialized canonical artifact tree."""

    if remote_inventory is not None:
        if remote_inventory.identity != expectation.identity:
            raise InputAuthenticationError("remote inventory identity differs from expectation")
        _authenticate_inventory_expectations(remote_inventory, expectation)
    local = inventory_directory(materialized_root, expectation.identity)
    _authenticate_inventory_expectations(local, expectation, check_inventory_hash=False)
    table_path = _existing_confined_file(materialized_root, expectation.table_hashes_path)
    raw_manifest = table_path.read_bytes()
    observed_manifest_sha256 = _sha256_bytes(raw_manifest)
    if observed_manifest_sha256 != expectation.table_hashes_sha256:
        raise InputAuthenticationError("materialized table-hashes.json SHA-256 differs")
    declared = _parse_table_hash_inventory(raw_manifest, expectation.table_hashes_path)
    expected_paths = set(declared) | {expectation.table_hashes_path}
    local_by_path = local.by_path
    if set(local_by_path) != expected_paths:
        missing = sorted(expected_paths - set(local_by_path))
        unexpected = sorted(set(local_by_path) - expected_paths)
        raise InputAuthenticationError(
            f"materialized object inventory differs; missing={missing}, unexpected={unexpected}"
        )
    if remote_inventory is not None:
        remote_by_path = remote_inventory.by_path
        for relative in sorted(expected_paths):
            if local_by_path[relative].size != remote_by_path[relative].size:
                raise InputAuthenticationError(
                    f"materialized object size differs from remote inventory: {relative}"
                )
    for relative, expected_sha256 in sorted(declared.items()):
        observed = local_by_path[relative]
        if observed.hash_algorithm != "sha256" or observed.digest != expected_sha256:
            raise InputAuthenticationError(
                f"manifest-listed individual file SHA-256 differs: {relative}"
            )
    return MaterializationReceipt(
        identity=expectation.identity,
        remote_inventory_sha256=remote_inventory.sha256 if remote_inventory else None,
        materialized_inventory_sha256=local.sha256,
        table_hashes_sha256=observed_manifest_sha256,
        object_count=local.object_count,
        total_size=local.total_size,
        listed_file_sha256=tuple(sorted(declared.items())),
    )


def create_deterministic_package(source_root: Path, archive_path: Path) -> PackageReceipt:
    """Create a deterministic, no-overwrite tar package of regular files."""

    if _is_reparse_point(source_root):
        raise ObjectStoreError(f"package source is a link/reparse point: {source_root}")
    source = source_root.resolve()
    archive = archive_path.resolve()
    try:
        archive.relative_to(source)
    except ValueError:
        pass
    else:
        raise ObjectStoreConflictError("package archive cannot be inside its source tree")
    identity = ObjectStoreIdentity(provider="local", bucket="package", prefix="source")
    inventory = inventory_directory(source, identity)
    if not inventory.objects:
        raise ObjectStoreError("cannot package an empty source tree")
    if archive.exists():
        raise ObjectStoreConflictError(f"refusing to replace existing package: {archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(f".{archive.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as raw_archive:
            with tarfile.open(fileobj=raw_archive, mode="w", format=tarfile.PAX_FORMAT) as bundle:
                for entry in inventory.objects:
                    source_path = _existing_confined_file(source, entry.path)
                    info = tarfile.TarInfo(name=entry.path)
                    info.size = entry.size
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with source_path.open("rb") as source_handle:
                        bundle.addfile(info, source_handle)
            raw_archive.flush()
            os.fsync(raw_archive.fileno())
        _publish_file_without_overwrite(temporary, archive)
    except Exception:
        # A failed stage retains this uniquely named temporary file in staging.
        raise
    return PackageReceipt(
        archive_path=archive,
        archive_size=archive.stat().st_size,
        archive_sha256=sha256_file(archive),
        source_inventory_sha256=inventory.sha256,
        source_file_count=inventory.object_count,
    )


def verify_package(receipt: PackageReceipt) -> None:
    """Fail if a package no longer matches its recorded size and SHA-256."""

    if not receipt.archive_path.is_file() or _is_reparse_point(receipt.archive_path):
        raise InputAuthenticationError("recorded package is missing or unsafe")
    if receipt.archive_path.stat().st_size != receipt.archive_size:
        raise InputAuthenticationError("recorded package size differs")
    if sha256_file(receipt.archive_path) != receipt.archive_sha256:
        raise InputAuthenticationError("recorded package SHA-256 differs")


def upload_and_verify_tree(
    store: ObjectStore,
    source_root: Path,
) -> TransferVerificationReceipt:
    """Upload a finalized tree once, then perform an exact content check."""

    store.upload_tree(source_root)
    return store.check_tree(source_root)


def resume_or_upload_and_verify_tree(
    store: ObjectStore,
    source_root: Path,
) -> tuple[
    TransferVerificationReceipt, Literal["uploaded_new", "verified_existing", "resumed_partial"]
]:
    """Publish or resume one immutable tree, then verify every byte.

    A nonempty prefix is never treated as writable general-purpose storage.  A
    complete prefix must already verify exactly.  A smaller prefix may contain
    only same-path, same-size (and, where portable, same-digest) members of the
    finalized source; the adapter then adds absent objects with immutable
    semantics.  Unexpected or conflicting objects remain blocking and are
    never removed or replaced.
    """

    local = inventory_directory(source_root, store.identity)
    remote = store.inventory()
    if not remote.objects:
        transfer = upload_and_verify_tree(store, source_root)
        return transfer, "uploaded_new"
    if remote.object_count == local.object_count:
        return store.check_tree(source_root), "verified_existing"
    store.resume_upload_tree(source_root)
    return store.check_tree(source_root), "resumed_partial"


def _parse_table_hash_inventory(raw: bytes, manifest_path: str) -> dict[str, str]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InputAuthenticationError("canonical table-hashes.json is invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise InputAuthenticationError("canonical table-hashes.json schema_version is not 1")
    raw_hashes = payload.get("file_sha256")
    if not isinstance(raw_hashes, dict) or not raw_hashes:
        raise InputAuthenticationError("canonical table-hashes.json file_sha256 is empty")
    declared: dict[str, str] = {}
    for raw_path, raw_digest in sorted(raw_hashes.items(), key=lambda item: str(item[0])):
        try:
            relative = normalize_relative_object_path(
                str(raw_path),
                label="file_sha256 path",
            )
        except ValueError as exc:
            raise InputAuthenticationError(str(exc)) from exc
        digest = str(raw_digest)
        if not _SHA256.fullmatch(digest):
            raise InputAuthenticationError(f"file_sha256 value is not SHA-256: {relative}")
        if relative == manifest_path:
            raise InputAuthenticationError("table-hashes.json cannot list its own SHA-256")
        if relative in declared:
            raise InputAuthenticationError(f"duplicate file_sha256 path: {relative}")
        declared[relative] = digest
    return declared


def _authenticate_inventory_expectations(
    inventory: ObjectInventory,
    expectation: InputExpectation,
    *,
    check_inventory_hash: bool = True,
) -> None:
    if inventory.identity != expectation.identity:
        raise InputAuthenticationError("object inventory identity differs from expectation")
    if (
        check_inventory_hash
        and expectation.expected_inventory_sha256 is not None
        and inventory.sha256 != expectation.expected_inventory_sha256
    ):
        raise InputAuthenticationError("object inventory SHA-256 differs")
    if (
        expectation.expected_object_count is not None
        and inventory.object_count != expectation.expected_object_count
    ):
        raise InputAuthenticationError("object inventory count differs")
    if (
        expectation.expected_total_size is not None
        and inventory.total_size != expectation.expected_total_size
    ):
        raise InputAuthenticationError("object inventory total size differs")


def _require_equal_inventories(
    local: ObjectInventory,
    remote: ObjectInventory,
    *,
    compare_digest: bool,
) -> None:
    local_by_path = local.by_path
    remote_by_path = remote.by_path
    if set(local_by_path) != set(remote_by_path):
        raise InputAuthenticationError("local and remote object paths differ")
    for relative in sorted(local_by_path):
        local_entry = local_by_path[relative]
        remote_entry = remote_by_path[relative]
        if local_entry.size != remote_entry.size:
            raise InputAuthenticationError(f"local and remote object sizes differ: {relative}")
        if compare_digest and (
            local_entry.hash_algorithm != remote_entry.hash_algorithm
            or local_entry.digest != remote_entry.digest
        ):
            raise InputAuthenticationError(f"local and remote object hashes differ: {relative}")


def _require_resume_subset(
    local: ObjectInventory,
    remote: ObjectInventory,
    *,
    compare_digest: bool,
) -> None:
    """Require remote state to be an exact, strictly partial local-tree subset."""

    local_by_path = local.by_path
    remote_by_path = remote.by_path
    unexpected = sorted(set(remote_by_path) - set(local_by_path))
    if unexpected:
        raise ObjectStoreConflictError(
            f"partial object-store prefix has unexpected objects: {unexpected}"
        )
    if len(remote_by_path) >= len(local_by_path):
        raise ObjectStoreConflictError(
            "object-store upload resume requires a strictly partial prefix"
        )
    for relative in sorted(remote_by_path):
        local_entry = local_by_path[relative]
        remote_entry = remote_by_path[relative]
        if local_entry.size != remote_entry.size:
            raise ObjectStoreConflictError(f"partial object-store object size differs: {relative}")
        if compare_digest and (
            local_entry.hash_algorithm != remote_entry.hash_algorithm
            or local_entry.digest != remote_entry.digest
        ):
            raise ObjectStoreConflictError(f"partial object-store object hash differs: {relative}")


def _preferred_rclone_hash(hashes: Mapping[object, object], *, path: str) -> tuple[str, str]:
    normalized = {
        _normalize_hash_algorithm(str(name)): str(value).lower()
        for name, value in hashes.items()
        if value is not None and str(value)
    }
    for algorithm in ("sha256", "sha1", "md5"):
        digest = normalized.get(algorithm)
        if digest is not None:
            return algorithm, digest
    raise ObjectStoreError(f"rclone object inventory has no supported hash: {path}")


def _normalize_hash_algorithm(value: str) -> str:
    return value.lower().replace("-", "").replace("_", "")


def _require_empty_directory(path: Path, *, label: str) -> None:
    if path.exists():
        if not path.is_dir() or _is_reparse_point(path):
            raise ObjectStoreConflictError(f"{label} is not a real directory: {path}")
        if any(path.iterdir()):
            raise ObjectStoreConflictError(f"{label} is not empty: {path}")


def _existing_confined_file(root: Path, relative_path: str) -> Path:
    relative = normalize_relative_object_path(relative_path, label="object path")
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*PurePosixPath(relative).parts)
    if not candidate.is_file() or _is_reparse_point(candidate):
        raise ObjectStoreError(f"object is missing or unsafe: {relative}")
    try:
        candidate.resolve(strict=True).relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ObjectStoreError(f"object escapes its prefix: {relative}") from exc
    return candidate


def _new_confined_file(root: Path, relative_path: str) -> Path:
    relative = normalize_relative_object_path(relative_path, label="object path")
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*PurePosixPath(relative).parts)
    if candidate.exists() or candidate.is_symlink():
        raise ObjectStoreConflictError(f"refusing to replace object: {relative}")
    try:
        candidate.parent.resolve().relative_to(resolved_root)
    except ValueError as exc:
        raise ObjectStoreError(f"object parent escapes its prefix: {relative}") from exc
    return candidate


def _copy_file_new(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ObjectStoreConflictError(f"refusing to replace file: {destination}")
    with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
        destination_handle.flush()
        os.fsync(destination_handle.fileno())


def _publish_file_without_overwrite(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise ObjectStoreConflictError(f"refusing to replace file: {destination}") from exc
    except OSError as exc:
        raise ObjectStoreError(f"could not atomically publish file {destination}: {exc}") from exc
    else:
        temporary.unlink()
        _sync_directory(destination.parent)


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _redact(value: str, secrets: Sequence[str]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _run_subprocess(
    argv: Sequence[str],
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(argv),
        env=dict(environment),
        check=False,
        capture_output=True,
    )
