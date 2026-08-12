"""Immutable remote packaging for authenticated final-discovery stages.

This module does not decide when a stage runs.  It accepts an already
authenticated :class:`~echoes.final_discovery.stages.StageRunResult`, links
the exact completion bytes and full artifact inventory into a new local
checkpoint area on the same filesystem, then uploads that authenticated tree
directly to an empty prefix or verifies an already identical immutable prefix.

Local stage state and partial checkpoint workspaces are never removed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.final_discovery.config import StageRegistration
from echoes.final_discovery.inputs import (
    ObjectStore,
    ObjectStoreConflictError,
    ObjectStoreIdentity,
    TransferVerificationReceipt,
    inventory_directory,
    normalize_relative_object_path,
    resume_or_upload_and_verify_tree,
    sha256_file,
)
from echoes.final_discovery.stages import (
    FINAL_DISCOVERY_EXPERIMENT_ID,
    StageArtifact,
    StageCompletionManifest,
    StageRegistrationLike,
    StageRunResult,
    StageStore,
    assert_stage_registrations,
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CLEANUP_CRITICAL_FILE_LIMIT_BYTES = 16 * 1024**2


class StageCheckpointError(RuntimeError):
    """Raised when a durable stage checkpoint cannot be authenticated."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StageCheckpointMetadata(_FrozenModel):
    """Small self-describing record included inside every stage archive."""

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = FINAL_DISCOVERY_EXPERIMENT_ID
    stage_number: int = Field(ge=1, le=11)
    stage_id: str = Field(min_length=1)
    completion_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_count: int = Field(ge=1)
    supplemental_artifacts: tuple[StageArtifact, ...] = ()
    supplemental_inventory_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )

    @model_validator(mode="after")
    def supplemental_inventory_is_consistent(self) -> Self:
        paths = [artifact.path for artifact in self.supplemental_artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("checkpoint supplemental artifacts must be uniquely sorted")
        expected = (
            _artifact_inventory_sha256(self.supplemental_artifacts)
            if self.supplemental_artifacts
            else None
        )
        if self.supplemental_inventory_sha256 != expected:
            raise ValueError("checkpoint supplemental inventory SHA-256 disagrees")
        return self


class ObjectStoreIdentityBinding(_FrozenModel):
    """Persistable secret-free object-store prefix identity."""

    provider: str = Field(min_length=1)
    bucket: str = Field(min_length=1)
    prefix: str = Field(min_length=1)
    canonical_uri: str = Field(min_length=1)


class TransferVerificationBinding(_FrozenModel):
    """Persistable projection of exact local-versus-remote verification."""

    identity: ObjectStoreIdentityBinding
    local_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    remote_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    object_count: int = Field(ge=0)
    total_size: int = Field(ge=0)

    @model_validator(mode="after")
    def inventories_are_equal(self) -> Self:
        if self.local_inventory_sha256 != self.remote_inventory_sha256:
            raise ValueError("checkpoint transfer inventories must match exactly")
        return self


class StageCheckpointReceipt(_FrozenModel):
    """Complete binding between one stage, package, and immutable store."""

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = FINAL_DISCOVERY_EXPERIMENT_ID
    stage_number: int = Field(ge=1, le=11)
    stage_id: str = Field(min_length=1)
    completion_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_count: int = Field(ge=1)
    supplemental_file_count: int = Field(ge=0)
    supplemental_inventory_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    package_source_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    package_source_file_count: int = Field(ge=3)
    transfer_mode: Literal["direct_authenticated_tree"] = "direct_authenticated_tree"
    local_payload_uses_same_filesystem_hardlinks: Literal[True] = True
    store_identity: ObjectStoreIdentityBinding
    transfer_verification: TransferVerificationBinding
    transfer_action: Literal["uploaded_new", "verified_existing", "resumed_partial"]

    @model_validator(mode="after")
    def bindings_are_consistent(self) -> Self:
        if self.package_source_file_count != (
            self.artifact_count + self.supplemental_file_count + 2
        ):
            raise ValueError(
                "package source must contain metadata, completion, artifacts, and supplements"
            )
        if (self.supplemental_file_count == 0) != (self.supplemental_inventory_sha256 is None):
            raise ValueError("checkpoint supplemental receipt identity is inconsistent")
        if self.transfer_verification.identity != self.store_identity:
            raise ValueError("transfer store identity differs from checkpoint identity")
        if self.transfer_verification.object_count != self.package_source_file_count:
            raise ValueError("remote checkpoint object count differs from its payload")
        return self


class StageCheckpointCleanupVerification(_FrozenModel):
    """Bounded deletion-gate reauthentication of a durable finalization tree."""

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = FINAL_DISCOVERY_EXPERIMENT_ID
    verification_scope: Literal["complete_path_size_inventory_plus_critical_finalization_bytes"] = (
        "complete_path_size_inventory_plus_critical_finalization_bytes"
    )
    initial_full_content_check_bound_by_checkpoint_receipt: Literal[True] = True
    stage_number: Literal[11] = 11
    stage_id: Literal["package_upload_verify"] = "package_upload_verify"
    completion_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    store_identity: ObjectStoreIdentityBinding
    initial_transfer_action: Literal["uploaded_new", "verified_existing", "resumed_partial"]
    reverified_transfer_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    object_count: int = Field(ge=3)
    total_size: int = Field(ge=1)
    critical_file_sha256: dict[str, str]
    supplemental_paths: tuple[str, ...]

    @model_validator(mode="after")
    def critical_inventory_is_exact(self) -> Self:
        if tuple(sorted(self.supplemental_paths)) != self.supplemental_paths:
            raise ValueError("cleanup supplemental paths must be sorted")
        if len(set(self.supplemental_paths)) != len(self.supplemental_paths):
            raise ValueError("cleanup supplemental paths must be unique")
        expected_paths = {
            "checkpoint.json",
            "completion.json",
            *(f"supplemental/{path}" for path in self.supplemental_paths),
        }
        if set(self.critical_file_sha256) != expected_paths:
            raise ValueError("cleanup critical-file inventory differs")
        if any(not _SHA256.fullmatch(value) for value in self.critical_file_sha256.values()):
            raise ValueError("cleanup critical-file identity is not SHA-256")
        return self


def _identity_binding(identity: ObjectStoreIdentity) -> ObjectStoreIdentityBinding:
    return ObjectStoreIdentityBinding(
        provider=identity.provider,
        bucket=identity.bucket,
        prefix=identity.prefix,
        canonical_uri=identity.canonical_uri,
    )


def _transfer_binding(receipt: TransferVerificationReceipt) -> TransferVerificationBinding:
    return TransferVerificationBinding(
        identity=_identity_binding(receipt.identity),
        local_inventory_sha256=receipt.local_inventory_sha256,
        remote_inventory_sha256=receipt.remote_inventory_sha256,
        object_count=receipt.object_count,
        total_size=receipt.total_size,
    )


def _write_bytes_new(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _artifact_inventory_sha256(artifacts: Sequence[StageArtifact]) -> str:
    payload = [artifact.model_dump(mode="json") for artifact in artifacts]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _link_file_new(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ObjectStoreConflictError(f"refusing to replace checkpoint file: {destination}")
    try:
        os.link(source, destination)
    except OSError as exc:
        raise StageCheckpointError(
            "checkpoint payload requires same-filesystem hardlinks; refusing an "
            f"unbounded physical copy for {destination}"
        ) from exc
    if not os.path.samefile(source, destination):
        raise StageCheckpointError(f"checkpoint hardlink identity differs: {destination}")


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _require_new_checkpoint_root(path: Path, stage_store: StageStore) -> Path:
    if path.exists():
        if not path.is_dir() or _is_reparse_point(path):
            raise ObjectStoreConflictError(
                f"stage checkpoint workspace is not a real directory: {path}"
            )
        if any(path.iterdir()):
            raise ObjectStoreConflictError(f"stage checkpoint workspace is not empty: {path}")
    resolved = path.resolve()
    try:
        resolved.relative_to(stage_store.root)
    except ValueError:
        pass
    else:
        raise ObjectStoreConflictError(
            "stage checkpoint workspace cannot be inside the authenticated stage store"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _authenticate_stage_result(
    stage_store: StageStore,
    result: StageRunResult,
) -> tuple[StageCompletionManifest, Path, Path]:
    if not _SHA256.fullmatch(result.completion_manifest_sha256):
        raise StageCheckpointError("stage result completion hash is not a lowercase SHA-256")
    manifest = stage_store.authenticate_completion(result.manifest.stage_id)
    completion_path = stage_store.completion_path(manifest.stage_id)
    completion_sha256 = sha256_file(completion_path)
    if manifest != result.manifest:
        raise StageCheckpointError("stage result manifest differs from authenticated completion")
    if completion_sha256 != result.completion_manifest_sha256:
        raise StageCheckpointError("stage result completion hash differs from local completion")
    stage_root = completion_path.parent.resolve()
    artifact_root = stage_root.joinpath(*PurePosixPath(manifest.artifacts_root).parts)
    return manifest, completion_path, artifact_root


def _write_payload(
    payload_root: Path,
    manifest: StageCompletionManifest,
    completion_path: Path,
    artifact_root: Path,
    completion_sha256: str,
    supplemental_files: Mapping[str, Path],
) -> StageCheckpointMetadata:
    payload_root.mkdir(parents=True, exist_ok=False)
    supplemental_artifacts: list[StageArtifact] = []
    normalized_supplements: list[tuple[str, Path]] = []
    for raw_path, source in supplemental_files.items():
        try:
            relative = normalize_relative_object_path(
                raw_path,
                label="checkpoint supplemental path",
            )
        except ValueError as exc:
            raise StageCheckpointError(str(exc)) from exc
        if relative in {"checkpoint.json", "completion.json"} or relative.startswith("artifacts/"):
            raise StageCheckpointError("checkpoint supplemental path collides with core payload")
        normalized_supplements.append((relative, source))
    normalized_supplements.sort(key=lambda item: item[0])
    if len({item[0] for item in normalized_supplements}) != len(normalized_supplements):
        raise StageCheckpointError("checkpoint supplemental paths are duplicated")
    for relative, source in normalized_supplements:
        if not source.is_file() or _is_reparse_point(source):
            raise StageCheckpointError(
                f"checkpoint supplemental source is missing or unsafe: {relative}"
            )
        source_size = source.stat().st_size
        source_sha256 = sha256_file(source)
        destination = payload_root / "supplemental" / Path(*PurePosixPath(relative).parts)
        _link_file_new(source, destination)
        if destination.stat().st_size != source_size or sha256_file(destination) != source_sha256:
            raise StageCheckpointError(
                f"checkpoint supplemental bytes differ after copying: {relative}"
            )
        if source.stat().st_size != source_size or sha256_file(source) != source_sha256:
            raise StageCheckpointError(
                f"checkpoint supplemental source changed while copying: {relative}"
            )
        supplemental_artifacts.append(
            StageArtifact(path=relative, size=source_size, sha256=source_sha256)
        )
    metadata = StageCheckpointMetadata(
        stage_number=manifest.stage_number,
        stage_id=manifest.stage_id,
        completion_manifest_sha256=completion_sha256,
        output_inventory_sha256=manifest.output_inventory_sha256,
        artifact_count=len(manifest.artifacts),
        supplemental_artifacts=tuple(supplemental_artifacts),
        supplemental_inventory_sha256=(
            _artifact_inventory_sha256(supplemental_artifacts) if supplemental_artifacts else None
        ),
    )
    metadata_bytes = (
        metadata.model_dump_json(indent=None, by_alias=False, exclude_none=False).encode("utf-8")
        + b"\n"
    )
    _write_bytes_new(payload_root / "checkpoint.json", metadata_bytes)
    _link_file_new(completion_path, payload_root / "completion.json")
    for artifact in manifest.artifacts:
        artifact_relative = PurePosixPath(artifact.path)
        source = artifact_root.joinpath(*artifact_relative.parts)
        destination = payload_root / "artifacts" / Path(*artifact_relative.parts)
        _link_file_new(source, destination)
    return metadata


def _authenticate_payload(
    payload_root: Path,
    manifest: StageCompletionManifest,
    metadata: StageCheckpointMetadata,
) -> None:
    completion_path = payload_root / "completion.json"
    if sha256_file(completion_path) != metadata.completion_manifest_sha256:
        raise StageCheckpointError("checkpoint completion bytes differ after copying")
    try:
        copied_manifest = StageCompletionManifest.model_validate_json(completion_path.read_bytes())
        copied_metadata = StageCheckpointMetadata.model_validate_json(
            (payload_root / "checkpoint.json").read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise StageCheckpointError("checkpoint payload metadata is invalid") from exc
    if copied_manifest != manifest or copied_metadata != metadata:
        raise StageCheckpointError("checkpoint payload identities differ after copying")
    identity = ObjectStoreIdentity(
        provider="local",
        bucket="stage-checkpoint",
        prefix="artifacts",
    )
    inventory = inventory_directory(payload_root / "artifacts", identity)
    observed = tuple((entry.path, entry.size, entry.digest) for entry in inventory.objects)
    expected = tuple(
        (artifact.path, artifact.size, artifact.sha256) for artifact in manifest.artifacts
    )
    if observed != expected:
        raise StageCheckpointError("checkpoint artifact inventory differs after copying")
    supplemental_root = payload_root / "supplemental"
    if metadata.supplemental_artifacts:
        supplemental_inventory = inventory_directory(supplemental_root, identity)
        observed_supplemental = tuple(
            (entry.path, entry.size, entry.digest) for entry in supplemental_inventory.objects
        )
        expected_supplemental = tuple(
            (artifact.path, artifact.size, artifact.sha256)
            for artifact in metadata.supplemental_artifacts
        )
        if observed_supplemental != expected_supplemental:
            raise StageCheckpointError("checkpoint supplemental inventory differs after copying")
    elif supplemental_root.exists():
        raise StageCheckpointError("empty checkpoint unexpectedly contains supplemental files")


def package_and_upload_stage_checkpoint(
    stage_store: StageStore,
    stage_result: StageRunResult,
    store: ObjectStore,
    *,
    checkpoint_root: Path,
    expected_store_identity: ObjectStoreIdentity | None = None,
    supplemental_files: Mapping[str, Path] | None = None,
) -> StageCheckpointReceipt:
    """Package, upload, and verify one authenticated stage without deletion.

    ``checkpoint_root`` must be new or empty and outside ``stage_store``.  A
    failure leaves all local source and checkpoint bytes in place.  A nonempty
    destination is accepted only when ``store.check_tree`` proves it is the
    exact authenticated payload tree.  Same-filesystem hardlinks avoid a
    second physical copy before direct object-store transfer.
    """

    if expected_store_identity is not None and store.identity != expected_store_identity:
        raise StageCheckpointError(
            "checkpoint object-store identity differs from the expected provider/bucket/prefix"
        )
    manifest, completion_path, artifact_root = _authenticate_stage_result(
        stage_store,
        stage_result,
    )
    root = _require_new_checkpoint_root(checkpoint_root, stage_store)
    payload_root = root / "payload"
    metadata = _write_payload(
        payload_root,
        manifest,
        completion_path,
        artifact_root,
        stage_result.completion_manifest_sha256,
        supplemental_files or {},
    )
    # Reauthenticate the source after the copy so concurrent or accidental
    # source mutation cannot be hidden by a previously valid manifest.
    second_manifest, _, _ = _authenticate_stage_result(stage_store, stage_result)
    if second_manifest != manifest:
        raise StageCheckpointError("stage completion changed while checkpointing")
    _authenticate_payload(payload_root, manifest, metadata)

    payload_inventory = inventory_directory(
        payload_root,
        ObjectStoreIdentity(provider="local", bucket="stage-checkpoint", prefix="payload"),
    )
    transfer, action = resume_or_upload_and_verify_tree(store, payload_root)
    if transfer.identity != store.identity:
        raise StageCheckpointError("transfer verification returned a different store identity")
    return StageCheckpointReceipt(
        stage_number=manifest.stage_number,
        stage_id=manifest.stage_id,
        completion_manifest_sha256=stage_result.completion_manifest_sha256,
        output_inventory_sha256=manifest.output_inventory_sha256,
        artifact_count=len(manifest.artifacts),
        supplemental_file_count=len(metadata.supplemental_artifacts),
        supplemental_inventory_sha256=metadata.supplemental_inventory_sha256,
        package_source_inventory_sha256=payload_inventory.sha256,
        package_source_file_count=payload_inventory.object_count,
        store_identity=_identity_binding(store.identity),
        transfer_verification=_transfer_binding(transfer),
        transfer_action=action,
    )


def reauthenticate_finalization_checkpoint_for_cleanup(
    store: ObjectStore,
    *,
    checkpoint_root: Path,
    required_supplemental_paths: Sequence[str],
) -> StageCheckpointCleanupVerification:
    """Reauthenticate the remote Stage 11 finalization object before deletion.

    The initial checkpoint receipt already binds a full downloaded-content
    comparison performed by the B2 adapter.  This cleanup-time operation is
    deliberately bounded: it rechecks the complete remote path/size inventory
    and downloads the self-describing checkpoint, completion, campaign seal,
    and validation supplements.  It never treats this bounded recheck as a new
    full-content verification of the potentially very large package tree.
    """

    root = checkpoint_root.resolve()
    payload_root = root / "payload"
    receipt_path = root / "stage-checkpoint-receipt.json"
    try:
        receipt = StageCheckpointReceipt.model_validate_json(receipt_path.read_bytes())
        metadata = StageCheckpointMetadata.model_validate_json(
            (payload_root / "checkpoint.json").read_bytes()
        )
        manifest = StageCompletionManifest.model_validate_json(
            (payload_root / "completion.json").read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise StageCheckpointError("finalization checkpoint metadata is invalid") from exc
    if receipt.stage_number != 11 or receipt.stage_id != "package_upload_verify":
        raise StageCheckpointError("cleanup verification requires the Stage 11 checkpoint")
    if store.identity != ObjectStoreIdentity(
        provider=receipt.store_identity.provider,
        bucket=receipt.store_identity.bucket,
        prefix=receipt.store_identity.prefix,
    ):
        raise StageCheckpointError("cleanup checkpoint store identity differs from its receipt")
    if receipt.store_identity.canonical_uri != store.identity.canonical_uri:
        raise StageCheckpointError("cleanup checkpoint canonical store URI differs")
    if (
        manifest.stage_number != receipt.stage_number
        or manifest.stage_id != receipt.stage_id
        or metadata.stage_number != receipt.stage_number
        or metadata.stage_id != receipt.stage_id
        or receipt.completion_manifest_sha256 != sha256_file(payload_root / "completion.json")
        or receipt.output_inventory_sha256 != manifest.output_inventory_sha256
    ):
        raise StageCheckpointError("cleanup checkpoint stage identities do not reconcile")
    _authenticate_payload(payload_root, manifest, metadata)

    supplemental_paths = tuple(item.path for item in metadata.supplemental_artifacts)
    expected_supplemental = tuple(
        sorted(
            normalize_relative_object_path(path, label="cleanup supplemental path")
            for path in required_supplemental_paths
        )
    )
    if supplemental_paths != expected_supplemental:
        raise StageCheckpointError(
            "finalization checkpoint supplemental inventory differs from the cleanup contract"
        )

    package_inventory = inventory_directory(
        payload_root,
        ObjectStoreIdentity(provider="local", bucket="stage-checkpoint", prefix="payload"),
    )
    if (
        package_inventory.sha256 != receipt.package_source_inventory_sha256
        or package_inventory.object_count != receipt.package_source_file_count
    ):
        raise StageCheckpointError("local finalization payload differs from its checkpoint receipt")
    local_inventory = inventory_directory(payload_root, store.identity)
    remote_inventory = store.inventory()
    local_paths_and_sizes = tuple((item.path, item.size) for item in local_inventory.objects)
    remote_paths_and_sizes = tuple((item.path, item.size) for item in remote_inventory.objects)
    if local_paths_and_sizes != remote_paths_and_sizes:
        raise StageCheckpointError("remote finalization path/size inventory differs")
    if (
        local_inventory.transfer_sha256 != receipt.transfer_verification.local_inventory_sha256
        or remote_inventory.transfer_sha256 != receipt.transfer_verification.remote_inventory_sha256
        or remote_inventory.object_count != receipt.transfer_verification.object_count
        or remote_inventory.total_size != receipt.transfer_verification.total_size
    ):
        raise StageCheckpointError(
            "remote finalization inventory differs from its transfer receipt"
        )

    critical_paths = (
        "checkpoint.json",
        "completion.json",
        *(f"supplemental/{path}" for path in supplemental_paths),
    )
    critical_file_sha256: dict[str, str] = {}
    for relative in critical_paths:
        local_path = payload_root.joinpath(*PurePosixPath(relative).parts)
        size = local_path.stat().st_size
        if size > _CLEANUP_CRITICAL_FILE_LIMIT_BYTES:
            raise StageCheckpointError(
                f"cleanup critical file exceeds the bounded read limit: {relative}"
            )
        local_bytes = local_path.read_bytes()
        remote_bytes = store.read_bytes(relative, maximum_bytes=size)
        if remote_bytes != local_bytes:
            raise StageCheckpointError(f"remote finalization critical file differs: {relative}")
        critical_file_sha256[relative] = hashlib.sha256(local_bytes).hexdigest()

    return StageCheckpointCleanupVerification(
        completion_manifest_sha256=receipt.completion_manifest_sha256,
        store_identity=receipt.store_identity,
        initial_transfer_action=receipt.transfer_action,
        reverified_transfer_inventory_sha256=remote_inventory.transfer_sha256,
        object_count=remote_inventory.object_count,
        total_size=remote_inventory.total_size,
        critical_file_sha256=critical_file_sha256,
        supplemental_paths=supplemental_paths,
    )


def validate_checkpoint_store_mapping(
    registrations: Sequence[StageRegistration],
    stores: Mapping[str, ObjectStore],
) -> tuple[str, ...]:
    """Require exactly one distinct store prefix for every configured upload stage."""

    typed_registrations = cast(Sequence[StageRegistrationLike], registrations)
    try:
        assert_stage_registrations(typed_registrations)
    except ValueError as exc:
        raise StageCheckpointError(str(exc)) from exc
    required = tuple(
        registration.stage_id
        for registration in typed_registrations
        if registration.upload_after_completion
    )
    required_set = set(required)
    supplied_set = set(stores)
    if supplied_set != required_set:
        missing = sorted(required_set - supplied_set)
        unexpected = sorted(supplied_set - required_set)
        raise StageCheckpointError(
            f"checkpoint store mapping differs; missing={missing}, unexpected={unexpected}"
        )
    identities: dict[str, str] = {}
    for stage_id in required:
        store = stores[stage_id]
        if not isinstance(store, ObjectStore):
            raise StageCheckpointError(
                f"checkpoint store does not implement the object-store contract: {stage_id}"
            )
        uri = store.identity.canonical_uri
        prior = identities.get(uri)
        if prior is not None:
            raise StageCheckpointError(
                f"checkpoint stages share one immutable store prefix: {prior}, {stage_id}"
            )
        identities[uri] = stage_id
    return required
