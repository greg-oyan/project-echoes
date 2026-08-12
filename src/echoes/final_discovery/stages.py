"""Durable, authenticated stage checkpoints for ``final-discovery-v1``.

Each successful attempt owns an immutable artifact directory.  A completion
manifest is published last and without replacement, so a late-stage failure
cannot invalidate authenticated upstream work.  Failed and interrupted
attempt directories are retained with explicit failure records.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, Protocol, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from echoes.final_discovery.inputs import sha256_file

FINAL_DISCOVERY_EXPERIMENT_ID: Literal["final-discovery-v1"] = "final-discovery-v1"
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SAFE_STAGE_ID = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SAFE_ATTEMPT_ID = re.compile(r"^[a-f0-9]{32}$")
_SAFE_HASH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class StageStoreError(RuntimeError):
    """Base class for final-discovery checkpoint errors."""


class StageDependencyError(StageStoreError):
    """Raised when a required upstream completion is absent or invalid."""


class StageAuthenticationError(StageStoreError):
    """Raised when persisted completion bytes no longer authenticate."""


class StageConflictError(StageStoreError):
    """Raised instead of silently replacing an existing completion."""


@dataclass(frozen=True, slots=True)
class StageSpec:
    """One frozen node in the eleven-stage campaign graph."""

    number: int
    stage_id: str
    dependencies: tuple[str, ...]
    expensive: bool
    upload_after_completion: bool

    def __post_init__(self) -> None:
        if not 1 <= self.number <= 11:
            raise ValueError("stage number must be between 1 and 11")
        if not _SAFE_STAGE_ID.fullmatch(self.stage_id):
            raise ValueError("stage ID must be a safe lowercase snake-case identifier")
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("stage dependencies must be unique")
        if any(not _SAFE_STAGE_ID.fullmatch(value) for value in self.dependencies):
            raise ValueError("stage dependency IDs must be safe")

    @property
    def sha256(self) -> str:
        return _sha256_payload(
            {
                "number": self.number,
                "stage_id": self.stage_id,
                "dependencies": list(self.dependencies),
                "expensive": self.expensive,
                "upload_after_completion": self.upload_after_completion,
            }
        )


FINAL_DISCOVERY_STAGE_SPECS: tuple[StageSpec, ...] = (
    StageSpec(1, "authenticate_materialize_inputs", (), False, False),
    StageSpec(
        2,
        "semantic_representations_indexes",
        ("authenticate_materialize_inputs",),
        True,
        True,
    ),
    StageSpec(
        3,
        "semantic_candidate_evidence",
        ("semantic_representations_indexes",),
        True,
        True,
    ),
    StageSpec(
        4,
        "grammatical_syntactic_evidence",
        ("authenticate_materialize_inputs",),
        True,
        True,
    ),
    StageSpec(
        5,
        "structural_narrative_evidence",
        ("authenticate_materialize_inputs",),
        True,
        True,
    ),
    StageSpec(
        6,
        "anomaly_evidence",
        (
            "semantic_candidate_evidence",
            "grammatical_syntactic_evidence",
            "structural_narrative_evidence",
        ),
        True,
        True,
    ),
    StageSpec(
        7,
        "empirical_null_controls",
        (
            "semantic_candidate_evidence",
            "grammatical_syntactic_evidence",
            "structural_narrative_evidence",
            "anomaly_evidence",
        ),
        True,
        True,
    ),
    StageSpec(
        8,
        "transparent_final_ensemble",
        (
            "semantic_candidate_evidence",
            "grammatical_syntactic_evidence",
            "structural_narrative_evidence",
            "anomaly_evidence",
            "empirical_null_controls",
        ),
        False,
        True,
    ),
    StageSpec(
        9,
        "tier_a_tier_b_outputs",
        ("transparent_final_ensemble",),
        False,
        True,
    ),
    StageSpec(10, "strict_validation", ("tier_a_tier_b_outputs",), False, True),
    StageSpec(11, "package_upload_verify", ("strict_validation",), False, True),
)

FINAL_DISCOVERY_STAGE_IDS: tuple[str, ...] = tuple(
    stage.stage_id for stage in FINAL_DISCOVERY_STAGE_SPECS
)
_STAGES_BY_ID = {stage.stage_id: stage for stage in FINAL_DISCOVERY_STAGE_SPECS}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StageArtifact(_FrozenModel):
    """One exact regular output file owned by a successful stage attempt."""

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("path")
    @classmethod
    def path_is_confined(cls, value: str) -> str:
        return _normalized_relative_path(value, label="stage artifact path")


class StageAttemptRecord(_FrozenModel):
    """Durable request identity written before a stage producer starts."""

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = FINAL_DISCOVERY_EXPERIMENT_ID
    attempt_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    stage_number: int = Field(ge=1, le=11)
    stage_id: str
    stage_spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    started_at: datetime
    input_sha256: dict[str, str]
    dependency_completion_sha256: dict[str, str]
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_commit: str = Field(min_length=1, max_length=128)

    @field_validator("stage_id")
    @classmethod
    def stage_id_is_safe(cls, value: str) -> str:
        if not _SAFE_STAGE_ID.fullmatch(value):
            raise ValueError("stage ID must be safe")
        return value

    @field_validator("input_sha256", "dependency_completion_sha256")
    @classmethod
    def hashes_are_named_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        return _validated_hashes(value)

    @field_validator("started_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _aware_datetime(value)


class StageCompletionManifest(_FrozenModel):
    """Atomic checkpoint proving a successful attempt's full identity."""

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = FINAL_DISCOVERY_EXPERIMENT_ID
    status: Literal["complete"] = "complete"
    attempt_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    stage_number: int = Field(ge=1, le=11)
    stage_id: str
    stage_spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    started_at: datetime
    completed_at: datetime
    input_sha256: dict[str, str]
    dependency_completion_sha256: dict[str, str]
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_commit: str = Field(min_length=1, max_length=128)
    artifacts_root: str
    artifacts: tuple[StageArtifact, ...] = Field(min_length=1)
    output_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("stage_id")
    @classmethod
    def stage_id_is_safe(cls, value: str) -> str:
        if not _SAFE_STAGE_ID.fullmatch(value):
            raise ValueError("stage ID must be safe")
        return value

    @field_validator("artifacts_root")
    @classmethod
    def artifacts_root_is_confined(cls, value: str) -> str:
        return _normalized_relative_path(value, label="artifacts root")

    @field_validator("input_sha256", "dependency_completion_sha256")
    @classmethod
    def hashes_are_named_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        return _validated_hashes(value)

    @field_validator("started_at", "completed_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def completion_is_internally_consistent(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("stage completion precedes its start")
        expected_root = f"completed-attempts/{self.attempt_id}/artifacts"
        if self.artifacts_root != expected_root:
            raise ValueError("artifacts root does not match the successful attempt")
        paths = [artifact.path for artifact in self.artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("stage artifacts must be uniquely sorted by path")
        if self.output_inventory_sha256 != _artifact_inventory_sha256(self.artifacts):
            raise ValueError("output inventory SHA-256 disagrees with artifacts")
        if not self.input_sha256 and not self.dependency_completion_sha256:
            raise ValueError("a completion requires at least one authenticated input")
        return self


class StageFailureRecord(_FrozenModel):
    """Preserved evidence for an exception or an interrupted attempt."""

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = FINAL_DISCOVERY_EXPERIMENT_ID
    status: Literal["failed"] = "failed"
    failure_kind: Literal["exception", "interrupted"]
    attempt_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    stage_number: int = Field(ge=1, le=11)
    stage_id: str
    stage_spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    started_at: datetime
    failed_at: datetime
    input_sha256: dict[str, str]
    dependency_completion_sha256: dict[str, str]
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_commit: str = Field(min_length=1, max_length=128)
    preserved_path: str
    error_type: str = Field(min_length=1, max_length=256)
    error_message: str = Field(min_length=1, max_length=4000)

    @field_validator("stage_id")
    @classmethod
    def stage_id_is_safe(cls, value: str) -> str:
        if not _SAFE_STAGE_ID.fullmatch(value):
            raise ValueError("stage ID must be safe")
        return value

    @field_validator("preserved_path")
    @classmethod
    def preserved_path_is_confined(cls, value: str) -> str:
        return _normalized_relative_path(value, label="preserved attempt path")

    @field_validator("input_sha256", "dependency_completion_sha256")
    @classmethod
    def hashes_are_named_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        return _validated_hashes(value)

    @field_validator("started_at", "failed_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware_datetime(value)


@dataclass(frozen=True, slots=True)
class StageRunResult:
    """One authenticated completion, either newly run or safely skipped."""

    manifest: StageCompletionManifest
    completion_manifest_sha256: str
    skipped: bool


StageProducer = Callable[[Path], None]


class StageRegistrationLike(Protocol):
    """Structural view of the preregistration's stage rows."""

    number: int
    stage_id: str
    dependencies: Sequence[int]
    expensive: bool
    upload_after_completion: bool


class StageStore:
    """Filesystem checkpoint store for the frozen final-discovery stage graph."""

    def __init__(self, root: Path) -> None:
        if root.exists() and _is_reparse_point(root):
            raise StageStoreError(f"stage-store root is unsafe: {root}")
        self.root = root.resolve()
        if self.root.exists() and (not self.root.is_dir() or _is_reparse_point(self.root)):
            raise StageStoreError(f"stage-store root is unsafe: {root}")
        self.root.mkdir(parents=True, exist_ok=True)

    def completion_path(self, stage_id: str) -> Path:
        spec = _stage_spec(stage_id)
        return self._stage_root(spec) / "completion.json"

    def failure_paths(self, stage_id: str) -> tuple[Path, ...]:
        spec = _stage_spec(stage_id)
        directory = self._stage_root(spec) / "failures"
        if not directory.is_dir():
            return ()
        return tuple(sorted(directory.glob("*.json")))

    def run_stage(
        self,
        stage_id: str,
        *,
        input_hashes: Mapping[str, str],
        config_sha256: str,
        code_sha256: str,
        code_commit: str,
        producer: StageProducer,
    ) -> StageRunResult:
        """Run once, or skip only after full dependency/output authentication."""

        spec = _stage_spec(stage_id)
        external_inputs = _validated_hashes(input_hashes)
        _require_sha256(config_sha256, label="config_sha256")
        _require_sha256(code_sha256, label="code_sha256")
        if (
            not code_commit
            or len(code_commit) > 128
            or any(character in code_commit for character in "\r\n\x00")
        ):
            raise ValueError("code_commit must be one bounded nonempty value")
        completion_path = self.completion_path(stage_id)
        if completion_path.exists():
            manifest = self.authenticate_completion(
                stage_id,
                expected_input_hashes=external_inputs,
                expected_config_sha256=config_sha256,
                expected_code_sha256=code_sha256,
                expected_code_commit=code_commit,
            )
            return StageRunResult(
                manifest=manifest,
                completion_manifest_sha256=sha256_file(completion_path),
                skipped=True,
            )

        dependency_hashes = self._dependency_hashes(spec)
        if not external_inputs and not dependency_hashes:
            raise ValueError("a stage requires at least one authenticated input hash")
        self.record_interrupted_attempts(stage_id)
        attempt = StageAttemptRecord(
            attempt_id=uuid4().hex,
            stage_number=spec.number,
            stage_id=spec.stage_id,
            stage_spec_sha256=spec.sha256,
            started_at=datetime.now(UTC),
            input_sha256=external_inputs,
            dependency_completion_sha256=dependency_hashes,
            config_sha256=config_sha256,
            code_sha256=code_sha256,
            code_commit=code_commit,
        )
        stage_root = self._stage_root(spec)
        in_progress = stage_root / "in-progress" / attempt.attempt_id
        artifacts_root = in_progress / "artifacts"
        artifacts_root.mkdir(parents=True, exist_ok=False)
        _write_model_new(in_progress / "attempt.json", attempt)
        preserved_path = in_progress
        try:
            producer(artifacts_root)
            artifacts = _inventory_stage_artifacts(artifacts_root)
            if not artifacts:
                raise StageStoreError("stage producer created no regular output files")
            completed_attempt = stage_root / "completed-attempts" / attempt.attempt_id
            completed_attempt.parent.mkdir(parents=True, exist_ok=True)
            if completion_path.exists():
                raise StageConflictError(
                    f"completion appeared while stage was running: {spec.stage_id}"
                )
            in_progress.replace(completed_attempt)
            _sync_directory(completed_attempt.parent)
            preserved_path = completed_attempt
            completion = StageCompletionManifest(
                attempt_id=attempt.attempt_id,
                stage_number=spec.number,
                stage_id=spec.stage_id,
                stage_spec_sha256=spec.sha256,
                started_at=attempt.started_at,
                completed_at=datetime.now(UTC),
                input_sha256=external_inputs,
                dependency_completion_sha256=dependency_hashes,
                config_sha256=config_sha256,
                code_sha256=code_sha256,
                code_commit=code_commit,
                artifacts_root=(f"completed-attempts/{attempt.attempt_id}/artifacts"),
                artifacts=artifacts,
                output_inventory_sha256=_artifact_inventory_sha256(artifacts),
            )
            _write_model_new(completion_path, completion)
        except BaseException as exc:
            self._preserve_failure(
                attempt,
                failure_kind="exception",
                preserved_path=preserved_path,
                error_type=type(exc).__name__,
                error_message=_safe_failure_message(str(exc)),
            )
            raise
        authenticated = self.authenticate_completion(
            stage_id,
            expected_input_hashes=external_inputs,
            expected_config_sha256=config_sha256,
            expected_code_sha256=code_sha256,
            expected_code_commit=code_commit,
        )
        return StageRunResult(
            manifest=authenticated,
            completion_manifest_sha256=sha256_file(completion_path),
            skipped=False,
        )

    def authenticate_completion(
        self,
        stage_id: str,
        *,
        expected_input_hashes: Mapping[str, str] | None = None,
        expected_config_sha256: str | None = None,
        expected_code_sha256: str | None = None,
        expected_code_commit: str | None = None,
        _ancestors: frozenset[str] = frozenset(),
        _cache: dict[str, StageCompletionManifest] | None = None,
    ) -> StageCompletionManifest:
        """Authenticate manifest identity, dependencies, exact files, and hashes."""

        spec = _stage_spec(stage_id)
        if stage_id in _ancestors:
            raise StageDependencyError(f"stage dependency cycle detected: {stage_id}")
        cache = {} if _cache is None else _cache
        cached = cache.get(stage_id)
        if cached is not None:
            self._authenticate_expected_request(
                cached,
                expected_input_hashes=expected_input_hashes,
                expected_config_sha256=expected_config_sha256,
                expected_code_sha256=expected_code_sha256,
                expected_code_commit=expected_code_commit,
            )
            return cached
        path = self.completion_path(stage_id)
        if not path.is_file() or _is_reparse_point(path):
            raise StageDependencyError(f"stage completion is absent: {stage_id}")
        try:
            manifest = StageCompletionManifest.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise StageAuthenticationError(
                f"could not validate stage completion manifest: {stage_id}"
            ) from exc
        if (
            manifest.stage_id != spec.stage_id
            or manifest.stage_number != spec.number
            or manifest.stage_spec_sha256 != spec.sha256
        ):
            raise StageAuthenticationError(f"stage specification identity differs: {stage_id}")
        expected_dependency_hashes = self._dependency_hashes(
            spec,
            ancestors=_ancestors | {stage_id},
            cache=cache,
        )
        if manifest.dependency_completion_sha256 != expected_dependency_hashes:
            raise StageAuthenticationError(f"stage dependency identities differ: {stage_id}")
        self._authenticate_expected_request(
            manifest,
            expected_input_hashes=expected_input_hashes,
            expected_config_sha256=expected_config_sha256,
            expected_code_sha256=expected_code_sha256,
            expected_code_commit=expected_code_commit,
        )
        stage_root = self._stage_root(spec).resolve()
        artifacts_root = stage_root.joinpath(*PurePosixPath(manifest.artifacts_root).parts)
        if _is_reparse_point(artifacts_root):
            raise StageAuthenticationError(f"stage artifacts root is unsafe: {stage_id}")
        try:
            resolved_artifacts = artifacts_root.resolve(strict=True)
            resolved_artifacts.relative_to(stage_root)
        except (OSError, ValueError) as exc:
            raise StageAuthenticationError(
                f"stage artifacts escape their root: {stage_id}"
            ) from exc
        if not resolved_artifacts.is_dir() or _is_reparse_point(resolved_artifacts):
            raise StageAuthenticationError(f"stage artifacts root is unsafe: {stage_id}")
        observed = _inventory_stage_artifacts(resolved_artifacts)
        if observed != manifest.artifacts:
            raise StageAuthenticationError(
                f"stage artifact inventory or SHA-256 differs: {stage_id}"
            )
        if _artifact_inventory_sha256(observed) != manifest.output_inventory_sha256:
            raise StageAuthenticationError(f"stage output inventory hash differs: {stage_id}")
        cache[stage_id] = manifest
        return manifest

    def authenticate_all_completions(self) -> tuple[StageCompletionManifest, ...]:
        """Authenticate the full graph once, caching shared ancestors within this call."""

        cache: dict[str, StageCompletionManifest] = {}
        return tuple(
            self.authenticate_completion(stage_id, _cache=cache)
            for stage_id in FINAL_DISCOVERY_STAGE_IDS
        )

    def record_interrupted_attempts(self, stage_id: str) -> tuple[StageFailureRecord, ...]:
        """Record every unpublished attempt as interrupted without deleting it."""

        spec = _stage_spec(stage_id)
        stage_root = self._stage_root(spec)
        published_attempt_id: str | None = None
        completion_path = stage_root / "completion.json"
        if completion_path.exists():
            if not completion_path.is_file() or _is_reparse_point(completion_path):
                raise StageAuthenticationError(f"stage completion manifest is unsafe: {stage_id}")
            try:
                completion = StageCompletionManifest.model_validate_json(
                    completion_path.read_bytes()
                )
            except (OSError, ValueError) as exc:
                raise StageAuthenticationError(
                    f"could not validate stage completion manifest: {stage_id}"
                ) from exc
            if (
                completion.stage_id != spec.stage_id
                or completion.stage_number != spec.number
                or completion.stage_spec_sha256 != spec.sha256
            ):
                raise StageAuthenticationError(f"stage specification identity differs: {stage_id}")
            published_attempt_id = completion.attempt_id

        records: list[StageFailureRecord] = []
        for attempt_root_name in ("in-progress", "completed-attempts"):
            attempt_root = stage_root / attempt_root_name
            if not attempt_root.is_dir():
                continue
            for attempt_directory in sorted(attempt_root.iterdir()):
                if not attempt_directory.is_dir() or _is_reparse_point(attempt_directory):
                    raise StageAuthenticationError(
                        f"interrupted stage entry is unsafe: {attempt_directory}"
                    )
                if not _SAFE_ATTEMPT_ID.fullmatch(attempt_directory.name):
                    raise StageAuthenticationError(
                        f"interrupted stage attempt ID is invalid: {attempt_directory.name}"
                    )
                if (
                    attempt_root_name == "completed-attempts"
                    and attempt_directory.name == published_attempt_id
                ):
                    continue
                failure_path = self._failure_path(spec, attempt_directory.name)
                if failure_path.exists():
                    records.append(self._load_failure(failure_path))
                    continue
                attempt_path = attempt_directory / "attempt.json"
                try:
                    attempt = StageAttemptRecord.model_validate_json(attempt_path.read_bytes())
                except (OSError, ValueError) as exc:
                    raise StageAuthenticationError(
                        f"interrupted stage attempt record is invalid: {attempt_directory.name}"
                    ) from exc
                if (
                    attempt.attempt_id != attempt_directory.name
                    or attempt.stage_id != spec.stage_id
                    or attempt.stage_number != spec.number
                    or attempt.stage_spec_sha256 != spec.sha256
                ):
                    raise StageAuthenticationError(
                        f"interrupted stage attempt identity differs: {attempt_directory.name}"
                    )
                records.append(
                    self._preserve_failure(
                        attempt,
                        failure_kind="interrupted",
                        preserved_path=attempt_directory,
                        error_type="InterruptedStage",
                        error_message=(
                            "stage did not publish a completion manifest; attempt is preserved"
                        ),
                    )
                )
        return tuple(records)

    def _authenticate_expected_request(
        self,
        manifest: StageCompletionManifest,
        *,
        expected_input_hashes: Mapping[str, str] | None,
        expected_config_sha256: str | None,
        expected_code_sha256: str | None,
        expected_code_commit: str | None,
    ) -> None:
        if expected_input_hashes is not None:
            normalized = _validated_hashes(expected_input_hashes)
            if manifest.input_sha256 != normalized:
                raise StageConflictError(
                    f"completed stage input identity differs: {manifest.stage_id}"
                )
        comparisons = (
            ("config", expected_config_sha256, manifest.config_sha256),
            ("code", expected_code_sha256, manifest.code_sha256),
            ("code commit", expected_code_commit, manifest.code_commit),
        )
        for label, expected, observed in comparisons:
            if expected is not None and expected != observed:
                raise StageConflictError(
                    f"completed stage {label} identity differs: {manifest.stage_id}"
                )

    def _dependency_hashes(
        self,
        spec: StageSpec,
        *,
        ancestors: frozenset[str] = frozenset(),
        cache: dict[str, StageCompletionManifest] | None = None,
    ) -> dict[str, str]:
        authentication_cache = {} if cache is None else cache
        hashes: dict[str, str] = {}
        for dependency in spec.dependencies:
            try:
                self.authenticate_completion(
                    dependency,
                    _ancestors=ancestors,
                    _cache=authentication_cache,
                )
            except StageStoreError as exc:
                raise StageDependencyError(
                    f"dependency {dependency} is not authenticated for {spec.stage_id}: {exc}"
                ) from exc
            hashes[dependency] = sha256_file(self.completion_path(dependency))
        return hashes

    def _stage_root(self, spec: StageSpec) -> Path:
        root = self.root / f"{spec.number:02d}-{spec.stage_id}"
        if root.exists() and (not root.is_dir() or _is_reparse_point(root)):
            raise StageStoreError(f"stage root is unsafe: {root}")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _failure_path(self, spec: StageSpec, attempt_id: str) -> Path:
        return self._stage_root(spec) / "failures" / f"{attempt_id}.json"

    def _preserve_failure(
        self,
        attempt: StageAttemptRecord,
        *,
        failure_kind: Literal["exception", "interrupted"],
        preserved_path: Path,
        error_type: str,
        error_message: str,
    ) -> StageFailureRecord:
        spec = _stage_spec(attempt.stage_id)
        try:
            relative = (
                preserved_path.resolve().relative_to(self._stage_root(spec).resolve()).as_posix()
            )
        except ValueError as exc:
            raise StageStoreError("failed attempt path escapes its stage root") from exc
        record = StageFailureRecord(
            failure_kind=failure_kind,
            attempt_id=attempt.attempt_id,
            stage_number=attempt.stage_number,
            stage_id=attempt.stage_id,
            stage_spec_sha256=attempt.stage_spec_sha256,
            started_at=attempt.started_at,
            failed_at=datetime.now(UTC),
            input_sha256=attempt.input_sha256,
            dependency_completion_sha256=attempt.dependency_completion_sha256,
            config_sha256=attempt.config_sha256,
            code_sha256=attempt.code_sha256,
            code_commit=attempt.code_commit,
            preserved_path=relative,
            error_type=error_type[:256] or "UnknownError",
            error_message=error_message[:4000] or "stage failed without an error message",
        )
        failure_path = self._failure_path(spec, attempt.attempt_id)
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        if failure_path.exists():
            existing = self._load_failure(failure_path)
            if existing != record and failure_kind != "interrupted":
                raise StageConflictError(
                    f"failure record already exists for attempt: {attempt.attempt_id}"
                )
            return existing
        _write_model_new(failure_path, record)
        return record

    @staticmethod
    def _load_failure(path: Path) -> StageFailureRecord:
        try:
            return StageFailureRecord.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise StageAuthenticationError(f"invalid stage failure record: {path}") from exc


def assert_stage_registrations(registrations: Sequence[StageRegistrationLike]) -> None:
    """Ensure a loaded preregistration repeats the frozen code stage graph exactly."""

    observed: list[tuple[int, str, tuple[int, ...], bool, bool]] = []
    number_by_id = {stage.stage_id: stage.number for stage in FINAL_DISCOVERY_STAGE_SPECS}
    for registration in registrations:
        try:
            number = int(registration.number)
            stage_id = str(registration.stage_id)
            dependencies = tuple(int(value) for value in registration.dependencies)
            expensive = bool(registration.expensive)
            upload = bool(registration.upload_after_completion)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("invalid stage registration object") from exc
        observed.append((number, stage_id, dependencies, expensive, upload))
    expected = [
        (
            stage.number,
            stage.stage_id,
            tuple(number_by_id[dependency] for dependency in stage.dependencies),
            stage.expensive,
            stage.upload_after_completion,
        )
        for stage in FINAL_DISCOVERY_STAGE_SPECS
    ]
    if observed != expected:
        raise ValueError("preregistered eleven-stage graph differs from the code contract")


def _stage_spec(stage_id: str) -> StageSpec:
    try:
        return _STAGES_BY_ID[stage_id]
    except KeyError as exc:
        raise ValueError(f"unknown final-discovery stage: {stage_id}") from exc


def _inventory_stage_artifacts(root: Path) -> tuple[StageArtifact, ...]:
    if not root.is_dir() or _is_reparse_point(root):
        raise StageAuthenticationError(f"stage artifact root is unsafe: {root}")
    resolved_root = root.resolve()
    artifacts: list[StageArtifact] = []

    def walk_error(error: OSError) -> None:
        raise StageAuthenticationError(f"could not enumerate stage artifacts: {error}")

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
                raise StageAuthenticationError(
                    "stage artifacts contain a directory link/reparse point: "
                    f"{child.relative_to(resolved_root).as_posix()}"
                )
        for name in file_names:
            path = current / name
            relative = path.relative_to(resolved_root).as_posix()
            if not path.is_file() or _is_reparse_point(path):
                raise StageAuthenticationError(
                    f"stage artifact is not a real regular file: {relative}"
                )
            artifacts.append(
                StageArtifact(
                    path=relative,
                    size=path.stat().st_size,
                    sha256=sha256_file(path),
                )
            )
    return tuple(sorted(artifacts, key=lambda artifact: artifact.path))


def _artifact_inventory_sha256(artifacts: Sequence[StageArtifact]) -> str:
    return _sha256_payload(
        [
            {"path": artifact.path, "size": artifact.size, "sha256": artifact.sha256}
            for artifact in artifacts
        ]
    )


def _validated_hashes(values: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_name, raw_digest in sorted(values.items()):
        name = str(raw_name)
        digest = str(raw_digest)
        if not _SAFE_HASH_NAME.fullmatch(name):
            raise ValueError(f"invalid input hash name: {name}")
        _require_sha256(digest, label=f"input hash {name}")
        normalized[name] = digest
    return normalized


def _require_sha256(value: str, *, label: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("stage timestamps must include a timezone")
    return value


def _normalized_relative_path(value: str, *, label: str) -> str:
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


def _write_model_new(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            model.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        + b"\n"
    )
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise StageConflictError(f"refusing to replace existing manifest: {path}") from exc
    except OSError as exc:
        raise StageStoreError(f"could not atomically publish manifest {path}: {exc}") from exc
    else:
        temporary.unlink()
        _sync_directory(path.parent)


def _sha256_payload(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_failure_message(value: str) -> str:
    safe = value
    for name in (
        "B2_APPLICATION_KEY_ID",
        "B2_APPLICATION_KEY",
        "RCLONE_CONFIG_ECHOES_FINAL_DISCOVERY_B2_ACCOUNT",
        "RCLONE_CONFIG_ECHOES_FINAL_DISCOVERY_B2_KEY",
    ):
        secret = os.environ.get(name)
        if secret:
            safe = safe.replace(secret, "<redacted>")
    return safe.strip() or "stage failed without an error message"


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
