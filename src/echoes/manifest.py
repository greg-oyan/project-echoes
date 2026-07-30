"""Reproducible run-manifest generation."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from time import perf_counter
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from echoes.settings import ModelsConfig, load_config, validate_config_directory

HardwareValue = str | int | None
ExecutionStatus = Literal["running", "succeeded", "failed"]

_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPRODUCTION_PREFIX = (
    "uv",
    "run",
    "echoes",
    "run-lexical-pipeline",
    "--primary",
)
_UNRESOLVED_RUN_ID = "unresolved"
_PENDING_CONFIGURATION_WARNING = (
    "validated runtime configuration and anchored inputs have not yet been bound"
)


def _normalized_relative_inventory_path(value: str, *, label: str) -> str:
    """Require one normalized POSIX path that cannot escape an inventory root."""
    if not value or "\\" in value:
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in posix_path.parts
        or value != posix_path.as_posix()
        or value in {".", ".."}
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    return value


def _validated_hash_inventory(values: Mapping[str, str], *, label: str) -> dict[str, str]:
    validated: dict[str, str] = {}
    for raw_path, digest in sorted(values.items()):
        path = _normalized_relative_inventory_path(str(raw_path), label=f"{label} key")
        if not _SHA256_PATTERN.fullmatch(str(digest)):
            raise ValueError(f"{label} contains a non-SHA-256 value: {path}")
        validated[path] = str(digest)
    return validated


class RunManifest(BaseModel):
    """Required provenance fields for every Project Echoes experiment."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    experiment_name: str
    timestamp: datetime
    git_commit: str
    working_tree_status: str
    python_version: str
    dependency_lock_hash: str
    config_hash: str
    dataset_manifest_hash: str | None
    dataset_versions: dict[str, str]
    random_seed: int = Field(ge=0)
    model_names: list[str]
    model_versions: dict[str, str]
    input_table_hashes: dict[str, str]
    output_table_hashes: dict[str, str]
    runtime: float = Field(ge=0)
    hardware_summary: dict[str, HardwareValue]
    warnings: list[str]
    errors: list[str]


class ResumeLineage(BaseModel):
    """Authenticated reuse facts for one interrupted-staging recovery."""

    model_config = ConfigDict(extra="forbid")

    requested_staging_directory: str | None
    status: Literal["not_requested", "requested", "validated_and_reused"]
    recovered_composite: bool
    validated_artifact_part_hashes: dict[str, str]
    validated_checkpoint_manifest_hashes: dict[str, str]
    validated_checkpoint_part_hashes: dict[str, str]

    @field_validator(
        "validated_artifact_part_hashes",
        "validated_checkpoint_manifest_hashes",
        "validated_checkpoint_part_hashes",
    )
    @classmethod
    def validated_hashes_are_confined(cls, value: dict[str, str]) -> dict[str, str]:
        return _validated_hash_inventory(value, label="resume hash inventory")

    @field_validator("requested_staging_directory")
    @classmethod
    def requested_staging_directory_is_confined(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_relative_inventory_path(
            value,
            label="requested staging directory",
        )

    @model_validator(mode="after")
    def resume_state_is_consistent(self) -> Self:
        if self.status == "not_requested":
            if self.requested_staging_directory is not None or self.recovered_composite:
                raise ValueError("fresh execution cannot name or recover resume state")
            if any(
                (
                    self.validated_artifact_part_hashes,
                    self.validated_checkpoint_manifest_hashes,
                    self.validated_checkpoint_part_hashes,
                )
            ):
                raise ValueError("fresh execution cannot record reused parts")
            return self
        if self.requested_staging_directory is None:
            raise ValueError("requested resume state requires the staging directory")
        if self.status == "requested":
            if self.recovered_composite:
                raise ValueError("unvalidated resume state cannot be a recovered composite")
            if any(
                (
                    self.validated_artifact_part_hashes,
                    self.validated_checkpoint_manifest_hashes,
                    self.validated_checkpoint_part_hashes,
                )
            ):
                raise ValueError("unvalidated resume state cannot record validated hashes")
            return self
        if self.status == "validated_and_reused" and (
            not self.recovered_composite or not self.validated_artifact_part_hashes
        ):
            raise ValueError("recovered execution requires validated artifact part hashes")
        return self


class ExperimentExecutionManifest(BaseModel):
    """Execution-attempt provenance kept outside experiment artifact schemas."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    execution_id: str
    execution_status: ExecutionStatus
    run_id: str
    experiment_name: str
    experiment_version: str
    timestamp: datetime
    completed_at: datetime | None
    git_commit: str
    working_tree_status: str
    working_tree_status_sha256: str
    source_tree_hash: str
    python_version: str
    runtime_versions: dict[str, str]
    dependency_lock_hash: str
    config_hash: str
    configuration_files: dict[str, str]
    configuration_hashes: dict[str, str]
    dataset_manifest_path: str | None
    dataset_manifest_hash: str | None
    source_file_hashes: dict[str, str]
    dataset_versions: dict[str, str]
    random_seed: int = Field(ge=0)
    random_seeds: dict[str, int]
    model_names: list[str]
    model_versions: dict[str, str]
    model_status: str
    input_table_hashes: dict[str, str]
    output_table_hashes: dict[str, str]
    output_table_physical_hashes: dict[str, str]
    output_hash_manifest_sha256: str | None
    runtime: float = Field(ge=0)
    stage_runtime_seconds: dict[str, float]
    hardware_summary: dict[str, HardwareValue]
    exact_candidate_generation_method: str
    training_data_lineage: str
    evaluation_split_lineage: dict[str, str]
    human_review_history: str
    artifact_output_directory: str
    resume_lineage: ResumeLineage
    reproduction_command: list[str] = Field(min_length=len(_REPRODUCTION_PREFIX) + 4)
    warnings: list[str]
    errors: list[str]
    limitations: list[str]

    @field_validator("execution_id", "run_id")
    @classmethod
    def identifiers_are_safe_path_segments(cls, value: str) -> str:
        if not _SAFE_IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("identifier must be one safe path segment")
        return value

    @field_validator("source_file_hashes")
    @classmethod
    def source_file_checksums_are_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        invalid = sorted(
            key for key, digest in value.items() if not _SHA256_PATTERN.fullmatch(digest)
        )
        if invalid:
            raise ValueError(f"source_file_hashes contains non-SHA-256 values: {invalid}")
        return dict(sorted(value.items()))

    @field_validator("reproduction_command")
    @classmethod
    def reproduction_command_is_bounded(cls, value: list[str]) -> list[str]:
        if tuple(value[: len(_REPRODUCTION_PREFIX)]) != _REPRODUCTION_PREFIX:
            raise ValueError("reproduction command must invoke the governed lexical pipeline")
        required_options = {"--database", "--output-dir"}
        observed_options: set[str] = set()
        index = len(_REPRODUCTION_PREFIX)
        while index < len(value):
            option = value[index]
            if option == "--force":
                if option in observed_options:
                    raise ValueError("reproduction command repeats --force")
                observed_options.add(option)
                index += 1
                continue
            if option not in required_options:
                raise ValueError(f"unsupported reproduction command option: {option}")
            if option in observed_options or index + 1 >= len(value):
                raise ValueError(f"invalid reproduction command option: {option}")
            observed_options.add(option)
            if not value[index + 1] or value[index + 1].startswith("--"):
                raise ValueError(f"reproduction command has an empty value for {option}")
            index += 2
        missing = required_options - observed_options
        if missing:
            raise ValueError(f"reproduction command is missing options: {sorted(missing)}")
        return value

    @model_validator(mode="after")
    def completion_state_is_truthful(self) -> Self:
        if self.config_hash != _hash_named_values(self.configuration_hashes):
            raise ValueError("config_hash disagrees with configuration_hashes")
        if not set(self.configuration_files).issubset(self.configuration_hashes):
            raise ValueError("configuration_files are missing corresponding hashes")
        if set(self.output_table_hashes) != set(self.output_table_physical_hashes):
            raise ValueError("logical and physical output hash maps name different tables")
        if self.execution_status == "running":
            if self.completed_at is not None or self.errors:
                raise ValueError("a running execution cannot be completed or have errors")
            return self
        if self.completed_at is None:
            raise ValueError("a completed execution requires completed_at")
        if self.execution_status == "failed":
            if not self.errors:
                raise ValueError("a failed execution must preserve at least one error")
            return self
        if self.errors:
            raise ValueError("a successful execution cannot contain errors")
        if self.run_id == _UNRESOLVED_RUN_ID:
            raise ValueError("a successful execution requires a resolved experiment run ID")
        if not self.random_seeds:
            raise ValueError("a successful execution requires the actual random seeds")
        if not self.dataset_versions:
            raise ValueError("a successful execution requires upstream dataset versions")
        if self.dataset_manifest_path is None:
            raise ValueError("a successful execution requires a dataset manifest path")
        if not self.source_file_hashes:
            raise ValueError("a successful execution requires source file checksums")
        if not self.configuration_files or not self.configuration_hashes:
            raise ValueError("a successful execution requires configuration provenance")
        if self.resume_lineage.status == "requested":
            raise ValueError("a successful resumed execution must validate and reuse its state")
        if (
            not self.input_table_hashes
            or not self.output_table_hashes
            or not self.output_table_physical_hashes
        ):
            raise ValueError("a successful execution requires input and output table hashes")
        required_hashes = {
            "dependency_lock_hash": self.dependency_lock_hash,
            "config_hash": self.config_hash,
            "dataset_manifest_hash": self.dataset_manifest_hash or "",
            "output_hash_manifest_sha256": self.output_hash_manifest_sha256 or "",
            "source_tree_hash": self.source_tree_hash,
            "working_tree_status_sha256": self.working_tree_status_sha256,
        }
        for name, digest in required_hashes.items():
            if not _SHA256_PATTERN.fullmatch(digest):
                raise ValueError(f"a successful execution requires a SHA-256 {name}")
        for name, values in (
            ("configuration_hashes", self.configuration_hashes),
            ("source_file_hashes", self.source_file_hashes),
            ("input_table_hashes", self.input_table_hashes),
            ("output_table_hashes", self.output_table_hashes),
            ("output_table_physical_hashes", self.output_table_physical_hashes),
            ("evaluation_split_lineage", self.evaluation_split_lineage),
            (
                "resume_artifact_part_hashes",
                self.resume_lineage.validated_artifact_part_hashes,
            ),
            (
                "resume_checkpoint_manifest_hashes",
                self.resume_lineage.validated_checkpoint_manifest_hashes,
            ),
            (
                "resume_checkpoint_part_hashes",
                self.resume_lineage.validated_checkpoint_part_hashes,
            ),
        ):
            invalid = sorted(
                key for key, digest in values.items() if not _SHA256_PATTERN.fullmatch(digest)
            )
            if invalid:
                raise ValueError(f"{name} contains non-SHA-256 values: {invalid}")
        return self


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_named_values(values: Mapping[str, str]) -> str:
    payload = json.dumps(
        dict(sorted(values.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_file_hashes_from_manifest(path: Path) -> dict[str, str]:
    """Extract the source catalog's named file checksums without reading source data."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read dataset source checksums: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("dataset manifest does not contain a sources list")

    result: dict[str, str] = {}
    for raw_source in payload["sources"]:
        if not isinstance(raw_source, dict):
            raise ValueError("dataset manifest contains a non-object source entry")
        source_id = raw_source.get("source_id")
        raw_hashes = raw_source.get("file_hashes")
        if raw_hashes is None:
            continue
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("dataset source checksum entry has no source_id")
        if not isinstance(raw_hashes, dict):
            raise ValueError(f"dataset source file_hashes is not an object: {source_id}")
        for raw_name, raw_digest in sorted(raw_hashes.items()):
            name = str(raw_name)
            digest = str(raw_digest)
            key = f"{source_id}:{name}"
            if key in result:
                raise ValueError(f"duplicate dataset source checksum: {key}")
            if not _SHA256_PATTERN.fullmatch(digest):
                raise ValueError(f"dataset source checksum is not SHA-256: {key}")
            result[key] = digest
    return result


def _project_relative_path(project_root: Path, path: Path) -> str:
    root = project_root.resolve()
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def hash_governed_source_tree(project_root: Path) -> str:
    """Hash M7 source/configuration bytes without reading generated research data."""
    root = project_root.resolve()
    paths = [
        path
        for source_root, pattern in (
            (root / "src", "*.py"),
            (root / "config", "*.yaml"),
        )
        if source_root.is_dir()
        for path in source_root.rglob(pattern)
        if path.is_file() and not path.is_symlink()
    ]
    paths.extend(
        path
        for path in (root / "pyproject.toml", root / "uv.lock")
        if path.is_file() and not path.is_symlink()
    )
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _git_execution_state(project_root: Path) -> tuple[str, str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
    )
    if commit.returncode != 0:
        unavailable_hash = hashlib.sha256(b"git-status-unavailable").hexdigest()
        return "UNCOMMITTED", "uncommitted", unavailable_hash

    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=project_root,
        check=False,
        capture_output=True,
    )
    status_bytes = status.stdout if status.returncode == 0 else b"git-status-unavailable"
    tree_status = "dirty" if status_bytes or status.returncode != 0 else "clean"
    return (
        commit.stdout.decode("ascii", errors="replace").strip(),
        tree_status,
        hashlib.sha256(status_bytes).hexdigest(),
    )


def hash_config_directory(config_dir: Path) -> str:
    """Hash configuration paths and bytes in a stable order."""
    digest = hashlib.sha256()
    for path in sorted(config_dir.rglob("*.yaml")):
        relative = path.relative_to(config_dir).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_state(project_root: Path) -> tuple[str, str]:
    commit, tree_status, _ = _git_execution_state(project_root)
    return commit, tree_status


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "experiment"


def _safe_identifier(value: str, *, label: str) -> str:
    if not _SAFE_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be one safe path segment")
    return value


def execution_manifest_root(output_dir: Path) -> Path:
    """Return the ignored sidecar root adjacent to, not inside, schema-v1."""
    return output_dir.resolve().parent / "execution-manifests"


def execution_manifest_path(
    manifest_root: Path,
    *,
    run_id: str,
    execution_id: str,
) -> Path:
    """Resolve one confined execution-manifest path from safe identifiers."""
    safe_run_id = _safe_identifier(run_id, label="run_id")
    safe_execution_id = _safe_identifier(execution_id, label="execution_id")
    unresolved_root = Path(os.path.abspath(manifest_root))
    if _is_reparse_point(unresolved_root):
        raise ValueError(f"execution manifest root cannot be a symlink: {unresolved_root}")
    root = unresolved_root.resolve()
    run_directory = root / safe_run_id
    if _is_reparse_point(run_directory):
        raise ValueError(f"execution manifest run directory cannot be a symlink: {run_directory}")
    return run_directory / f"{safe_execution_id}.json"


def _atomic_write_execution_manifest(
    manifest: ExperimentExecutionManifest,
    output_path: Path,
    *,
    overwrite: bool,
) -> None:
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing manifest: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.writing-{os.getpid()}")
    if temporary_path.exists():
        raise FileExistsError(f"execution manifest temporary path already exists: {temporary_path}")
    try:
        temporary_path.write_text(
            manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_execution_manifest(
    manifest: ExperimentExecutionManifest,
    output_path: Path,
    *,
    overwrite: bool = False,
) -> None:
    """Atomically persist one validated execution-attempt sidecar."""
    expected_name = f"{manifest.execution_id}.json"
    if output_path.name != expected_name or output_path.parent.name != manifest.run_id:
        raise ValueError("execution manifest path does not match its run/execution identity")
    _atomic_write_execution_manifest(manifest, output_path, overwrite=overwrite)


def _updated_execution_manifest(
    manifest: ExperimentExecutionManifest,
    **updates: object,
) -> ExperimentExecutionManifest:
    payload = manifest.model_dump(mode="python")
    payload.update(updates)
    return ExperimentExecutionManifest.model_validate(payload)


def _execution_id(
    *,
    timestamp: datetime,
    started_at_monotonic: float,
    project_root: Path,
    source_tree_hash: str,
    reproduction_command: Sequence[str],
) -> str:
    identity = {
        "timestamp": timestamp.isoformat(),
        "started_at_monotonic": started_at_monotonic,
        "process_id": os.getpid(),
        "project_root": project_root.resolve().as_posix(),
        "source_tree_hash": source_tree_hash,
        "reproduction_command": list(reproduction_command),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"execution-{timestamp:%Y%m%dT%H%M%S%fZ}-{digest[:12]}"


@dataclass(slots=True)
class ExperimentExecutionRecorder:
    """Atomically preserve the lifecycle of one experiment execution attempt."""

    project_root: Path
    manifest_root: Path
    manifest_path: Path
    manifest: ExperimentExecutionManifest
    started_at_monotonic: float

    @classmethod
    def begin(
        cls,
        *,
        experiment_name: str,
        experiment_version: str,
        project_root: Path,
        output_dir: Path,
        configuration_files: Mapping[str, Path],
        dataset_manifest_path: Path,
        runtime_versions: Mapping[str, str],
        reproduction_command: Sequence[str],
        resume_staging_dir: Path | None = None,
    ) -> ExperimentExecutionRecorder:
        """Capture immutable execution context before experiment work begins."""
        started_at_monotonic = perf_counter()
        timestamp = datetime.now(tz=UTC)
        root = project_root.resolve()
        output = output_dir.resolve()
        command = list(reproduction_command)
        source_tree_hash = hash_governed_source_tree(root)
        git_commit, tree_status, tree_status_hash = _git_execution_state(root)
        warnings = [_PENDING_CONFIGURATION_WARNING]
        limitations: list[str] = []

        lock_path = root / "uv.lock"
        dependency_lock_hash = "MISSING"
        if lock_path.is_file():
            dependency_lock_hash = sha256_file(lock_path)
        else:
            warnings.append("uv.lock is missing; dependencies are not reproducibly pinned")

        manifest_dataset_path = (root / dataset_manifest_path).resolve()
        dataset_manifest_hash: str | None = None
        source_file_hashes: dict[str, str] = {}
        if manifest_dataset_path.is_file():
            dataset_manifest_hash = sha256_file(manifest_dataset_path)
            try:
                source_file_hashes = _source_file_hashes_from_manifest(manifest_dataset_path)
            except ValueError as exc:
                warnings.append(str(exc))
        else:
            warnings.append(f"dataset source manifest is missing: {manifest_dataset_path}")

        configuration_paths: dict[str, str] = {}
        configuration_hashes: dict[str, str] = {}
        for name, configured_path in sorted(configuration_files.items()):
            path = (root / configured_path).resolve()
            configuration_paths[name] = _project_relative_path(root, path)
            if path.is_file():
                configuration_hashes[name] = sha256_file(path)
            else:
                configuration_hashes[name] = "MISSING"
                warnings.append(f"configuration file is missing: {path}")

        if git_commit == "UNCOMMITTED":
            warnings.append("repository has no commit; exact source revision is unavailable")
            limitations.append("git cannot reconstruct this execution's source revision")
        elif tree_status == "dirty":
            warnings.append("working tree is dirty; the execution includes uncommitted changes")
            limitations.append(
                "git commit alone cannot reconstruct the dirty tree; source_tree_hash "
                "authenticates the governed code and configuration bytes"
            )

        requested_resume = (
            None if resume_staging_dir is None else _project_relative_path(root, resume_staging_dir)
        )
        resume_lineage = ResumeLineage(
            requested_staging_directory=requested_resume,
            status="not_requested" if requested_resume is None else "requested",
            recovered_composite=False,
            validated_artifact_part_hashes={},
            validated_checkpoint_manifest_hashes={},
            validated_checkpoint_part_hashes={},
        )
        execution_id = _execution_id(
            timestamp=timestamp,
            started_at_monotonic=started_at_monotonic,
            project_root=root,
            source_tree_hash=source_tree_hash,
            reproduction_command=command,
        )
        manifest_root = execution_manifest_root(output)
        manifest_path = execution_manifest_path(
            manifest_root,
            run_id=_UNRESOLVED_RUN_ID,
            execution_id=execution_id,
        )
        manifest = ExperimentExecutionManifest(
            execution_id=execution_id,
            execution_status="running",
            run_id=_UNRESOLVED_RUN_ID,
            experiment_name=experiment_name,
            experiment_version=experiment_version,
            timestamp=timestamp,
            completed_at=None,
            git_commit=git_commit,
            working_tree_status=tree_status,
            working_tree_status_sha256=tree_status_hash,
            source_tree_hash=source_tree_hash,
            python_version=platform.python_version(),
            runtime_versions=dict(sorted(runtime_versions.items())),
            dependency_lock_hash=dependency_lock_hash,
            config_hash=_hash_named_values(configuration_hashes),
            configuration_files=configuration_paths,
            configuration_hashes=configuration_hashes,
            dataset_manifest_path=(
                _project_relative_path(root, manifest_dataset_path)
                if manifest_dataset_path.is_file()
                else None
            ),
            dataset_manifest_hash=dataset_manifest_hash,
            source_file_hashes=source_file_hashes,
            dataset_versions={},
            random_seed=0,
            random_seeds={},
            model_names=[],
            model_versions={},
            model_status="not_applicable_no_learned_models",
            input_table_hashes={},
            output_table_hashes={},
            output_table_physical_hashes={},
            output_hash_manifest_sha256=None,
            runtime=0.0,
            stage_runtime_seconds={},
            hardware_summary={
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "processor": platform.processor() or None,
                "cpu_count": os.cpu_count(),
            },
            exact_candidate_generation_method=(
                "frozen_m7_transparent_lexical_retrieval_calibration_and_candidate_evidence"
            ),
            training_data_lineage="not_applicable_no_model_training",
            evaluation_split_lineage={},
            human_review_history="not_started_milestone_8",
            artifact_output_directory=_project_relative_path(root, output),
            resume_lineage=resume_lineage,
            reproduction_command=command,
            warnings=warnings,
            errors=[],
            limitations=limitations,
        )
        write_execution_manifest(manifest, manifest_path)
        return cls(
            project_root=root,
            manifest_root=manifest_root,
            manifest_path=manifest_path,
            manifest=manifest,
            started_at_monotonic=started_at_monotonic,
        )

    def _ensure_running(self) -> None:
        if self.manifest.execution_status != "running":
            raise RuntimeError("execution manifest is already finalized")

    def _persist(self, manifest: ExperimentExecutionManifest) -> None:
        write_execution_manifest(manifest, self.manifest_path, overwrite=True)
        self.manifest = manifest

    def bind_configuration(
        self,
        *,
        canonical_hashes: Mapping[str, str],
        random_seed: int,
        random_seeds: Mapping[str, int],
        dataset_versions: Mapping[str, str],
    ) -> None:
        """Bind validated runtime configuration, seeds, and pinned source versions."""
        self._ensure_running()
        hashes = {
            **self.manifest.configuration_hashes,
            **dict(sorted(canonical_hashes.items())),
        }
        manifest = _updated_execution_manifest(
            self.manifest,
            config_hash=_hash_named_values(hashes),
            configuration_hashes=hashes,
            random_seed=random_seed,
            random_seeds=dict(sorted(random_seeds.items())),
            dataset_versions=dict(sorted(dataset_versions.items())),
            warnings=[
                warning
                for warning in self.manifest.warnings
                if warning != _PENDING_CONFIGURATION_WARNING
            ],
        )
        self._persist(manifest)

    def bind_run(
        self,
        *,
        run_id: str,
        input_table_hashes: Mapping[str, str],
        dataset_versions: Mapping[str, str],
        evaluation_split_lineage: Mapping[str, str],
    ) -> None:
        """Bind the unchanged scientific run identity and authenticated inputs."""
        self._ensure_running()
        _safe_identifier(run_id, label="run_id")
        versions = {
            **self.manifest.dataset_versions,
            **dict(sorted(dataset_versions.items())),
        }
        manifest = _updated_execution_manifest(
            self.manifest,
            run_id=run_id,
            dataset_versions=dict(sorted(versions.items())),
            input_table_hashes=dict(sorted(input_table_hashes.items())),
            evaluation_split_lineage=dict(sorted(evaluation_split_lineage.items())),
        )
        old_path = self.manifest_path
        new_path = execution_manifest_path(
            self.manifest_root,
            run_id=run_id,
            execution_id=manifest.execution_id,
        )
        if new_path.exists():
            raise FileExistsError(f"execution ID collision: {new_path}")
        write_execution_manifest(manifest, new_path)
        if old_path.exists():
            old_path.unlink()
        self.manifest_path = new_path
        self.manifest = manifest

    def bind_resume_lineage(
        self,
        *,
        artifact_part_hashes: Mapping[str, str],
        checkpoint_manifest_hashes: Mapping[str, str],
        checkpoint_part_hashes: Mapping[str, str],
    ) -> None:
        """Add authenticated resume files without weakening earlier lineage."""
        self._ensure_running()
        current = self.manifest.resume_lineage
        if current.status not in {"requested", "validated_and_reused"}:
            raise ValueError("resume lineage was not requested for this execution")

        incoming_artifacts = _validated_hash_inventory(
            artifact_part_hashes,
            label="resume artifact hash inventory",
        )
        incoming_manifests = _validated_hash_inventory(
            checkpoint_manifest_hashes,
            label="resume checkpoint-manifest hash inventory",
        )
        incoming_parts = _validated_hash_inventory(
            checkpoint_part_hashes,
            label="resume checkpoint-part hash inventory",
        )
        if not any((incoming_artifacts, incoming_manifests, incoming_parts)):
            raise ValueError("resume lineage update contains no validated files")

        def merge(
            existing: Mapping[str, str],
            incoming: Mapping[str, str],
            *,
            label: str,
        ) -> tuple[dict[str, str], bool]:
            merged = dict(existing)
            added = False
            for path, digest in incoming.items():
                prior = merged.get(path)
                if prior is not None and prior != digest:
                    raise ValueError(f"{label} hash conflict for {path}")
                if prior is None:
                    merged[path] = digest
                    added = True
            return dict(sorted(merged.items())), added

        artifacts, artifacts_added = merge(
            current.validated_artifact_part_hashes,
            incoming_artifacts,
            label="resume artifact",
        )
        checkpoint_manifests, manifests_added = merge(
            current.validated_checkpoint_manifest_hashes,
            incoming_manifests,
            label="resume checkpoint manifest",
        )
        checkpoint_parts, parts_added = merge(
            current.validated_checkpoint_part_hashes,
            incoming_parts,
            label="resume checkpoint part",
        )
        if not any((artifacts_added, manifests_added, parts_added)):
            raise ValueError("resume lineage update adds no new validated files")

        lineage = ResumeLineage(
            requested_staging_directory=current.requested_staging_directory,
            status="validated_and_reused",
            recovered_composite=True,
            validated_artifact_part_hashes=artifacts,
            validated_checkpoint_manifest_hashes=checkpoint_manifests,
            validated_checkpoint_part_hashes=checkpoint_parts,
        )
        warning = (
            "this execution recovered validated artifacts from interrupted staging; "
            "it is a composite completion, not an independent fresh run"
        )
        warnings = self.manifest.warnings
        limitations = self.manifest.limitations
        if current.status == "requested":
            warnings = [*warnings, warning]
            limitations = [*limitations, warning]
        manifest = _updated_execution_manifest(
            self.manifest,
            resume_lineage=lineage,
            warnings=warnings,
            limitations=limitations,
        )
        self._persist(manifest)

    def bind_outputs(
        self,
        *,
        output_table_hashes: Mapping[str, str],
        output_table_physical_hashes: Mapping[str, str],
        output_hash_manifest_path: Path,
    ) -> None:
        """Capture promoted output identities before any post-promotion load can fail."""
        self._ensure_running()
        manifest = _updated_execution_manifest(
            self.manifest,
            output_table_hashes=dict(sorted(output_table_hashes.items())),
            output_table_physical_hashes=dict(sorted(output_table_physical_hashes.items())),
            output_hash_manifest_sha256=sha256_file(output_hash_manifest_path),
        )
        self._persist(manifest)

    def finalize_success(
        self,
        *,
        stage_runtime_seconds: Mapping[str, float],
        warnings: Sequence[str] = (),
    ) -> None:
        """Finalize a successful attempt only after every pipeline stage returns."""
        self._ensure_running()
        manifest = _updated_execution_manifest(
            self.manifest,
            execution_status="succeeded",
            completed_at=datetime.now(tz=UTC),
            runtime=max(0.0, perf_counter() - self.started_at_monotonic),
            stage_runtime_seconds=dict(sorted(stage_runtime_seconds.items())),
            warnings=[*self.manifest.warnings, *warnings],
            errors=[],
        )
        self._persist(manifest)

    def finalize_failure(self, error: BaseException) -> None:
        """Preserve a failed attempt and rethrow responsibility to the caller."""
        self._ensure_running()
        message = f"{type(error).__name__}: {error}".strip()
        manifest = _updated_execution_manifest(
            self.manifest,
            execution_status="failed",
            completed_at=datetime.now(tz=UTC),
            runtime=max(0.0, perf_counter() - self.started_at_monotonic),
            errors=[*self.manifest.errors, message[:4000]],
        )
        self._persist(manifest)


def build_run_manifest(
    experiment_name: str,
    *,
    project_root: Path,
    config_dir: Path,
    random_seed: int = 1729,
) -> RunManifest:
    """Build an empty experiment manifest from validated repository state."""
    started = perf_counter()
    validate_config_directory(config_dir)
    config_hash = hash_config_directory(config_dir)
    timestamp = datetime.now(tz=UTC)
    git_commit, tree_status = _git_state(project_root)
    warnings: list[str] = []

    lock_path = project_root / "uv.lock"
    if lock_path.is_file():
        lock_hash = sha256_file(lock_path)
    else:
        lock_hash = "MISSING"
        warnings.append("uv.lock is missing; dependencies are not reproducibly pinned")

    dataset_manifest_path = project_root / "data" / "manifests" / "sources.yaml"
    dataset_manifest_hash = None
    if dataset_manifest_path.is_file():
        dataset_manifest_hash = sha256_file(dataset_manifest_path)
    else:
        warnings.append("no dataset manifest exists; Milestone 0 has no acquired corpus")

    if git_commit == "UNCOMMITTED":
        warnings.append("repository has no commit; exact source revision is unavailable")
    elif tree_status == "dirty":
        warnings.append("working tree is dirty; the run includes uncommitted changes")

    models_path = config_dir / "models.yaml"
    models = load_config(models_path)
    if not isinstance(models, ModelsConfig):
        msg = f"unexpected schema loaded for {models_path}"
        raise TypeError(msg)
    model_names = [model.name for model in models.models]
    model_versions = {model.name: model.version for model in models.models}

    run_id = f"{_slug(experiment_name)}-{timestamp:%Y%m%dT%H%M%S%fZ}-{config_hash[:8]}"
    runtime = round(perf_counter() - started, 6)
    return RunManifest(
        run_id=run_id,
        experiment_name=experiment_name,
        timestamp=timestamp,
        git_commit=git_commit,
        working_tree_status=tree_status,
        python_version=platform.python_version(),
        dependency_lock_hash=lock_hash,
        config_hash=config_hash,
        dataset_manifest_hash=dataset_manifest_hash,
        dataset_versions={},
        random_seed=random_seed,
        model_names=model_names,
        model_versions=model_versions,
        input_table_hashes={},
        output_table_hashes={},
        runtime=runtime,
        hardware_summary={
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "cpu_count": os.cpu_count(),
        },
        warnings=warnings,
        errors=[],
    )


def write_run_manifest(manifest: RunManifest, output_path: Path, *, overwrite: bool) -> None:
    """Write a run manifest without silently replacing an existing artifact."""
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing manifest: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_execution_manifest(path: Path) -> ExperimentExecutionManifest:
    """Load and authenticate one execution sidecar and its path identity."""
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"execution manifest does not exist as a regular file: {path}")
    manifest = ExperimentExecutionManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if path.name != f"{manifest.execution_id}.json" or path.parent.name != manifest.run_id:
        raise ValueError("execution manifest path identity differs from its payload")
    return manifest


def finalize_recovered_execution_success(
    path: Path,
    *,
    validation_report_sha256: str,
    service_result: str,
) -> ExperimentExecutionManifest:
    """Finalize post-COMMIT provenance only after an external strict validation.

    The caller authenticates the durable promotion journal, DuckDB commit
    marker, and strict validation report before invoking this idempotent
    transition. Any pre-recovery error text is retained as a warning and
    limitation rather than silently discarded.
    """

    if not _SHA256_PATTERN.fullmatch(validation_report_sha256):
        raise ValueError("recovery validation report identity must be SHA-256")
    if service_result != "success":
        raise ValueError(
            "recovery finalization requires an authenticated successful service result"
        )
    manifest = load_execution_manifest(path)
    if manifest.execution_status == "succeeded":
        return manifest
    if manifest.execution_status == "failed":
        raise ValueError("a recorded failed execution cannot be reclassified as succeeded")
    completed_at = datetime.now(tz=UTC)
    prior_errors = "; ".join(manifest.errors)
    warning = (
        "execution success provenance was finalized from a durable post-COMMIT "
        "promotion journal after strict validation and a successful service result "
        f"{validation_report_sha256}"
    )
    if prior_errors:
        warning += f"; preserved pre-recovery errors: {prior_errors[:3000]}"
    limitation = (
        "the worker was interrupted or failed after its atomic DuckDB exposure; "
        "success was recovered from the transaction marker and strict validation"
    )
    recovered = _updated_execution_manifest(
        manifest,
        execution_status="succeeded",
        completed_at=completed_at,
        runtime=max(
            manifest.runtime,
            max(0.0, (completed_at - manifest.timestamp).total_seconds()),
        ),
        warnings=[*manifest.warnings, warning],
        errors=[],
        limitations=[*manifest.limitations, limitation],
    )
    write_execution_manifest(recovered, path, overwrite=True)
    return recovered


def discover_execution_manifests(
    manifest_root: Path,
    *,
    run_id: str,
) -> list[tuple[Path, ExperimentExecutionManifest]]:
    """Return every separately preserved execution attempt for one scientific run."""
    safe_run_id = _safe_identifier(run_id, label="run_id")
    unresolved_root = Path(os.path.abspath(manifest_root))
    if _is_reparse_point(unresolved_root):
        raise ValueError(f"execution manifest root cannot be a symlink: {unresolved_root}")
    root = unresolved_root.resolve()
    run_directory = root / safe_run_id
    if not run_directory.is_dir():
        return []
    if _is_reparse_point(run_directory):
        raise ValueError(f"execution manifest run directory cannot be a symlink: {run_directory}")
    discovered: list[tuple[Path, ExperimentExecutionManifest]] = []
    for path in sorted(run_directory.glob("*.json")):
        if path.is_symlink():
            raise ValueError(f"execution manifest cannot be a symlink: {path}")
        manifest = load_execution_manifest(path)
        if manifest.run_id != safe_run_id:
            raise ValueError(f"execution manifest belongs to another run: {path}")
        discovered.append((path, manifest))
    return discovered


def resolve_execution_manifest(
    manifest_root: Path,
    *,
    run_id: str,
    execution_id: str | None = None,
    require_success: bool = True,
) -> tuple[Path, ExperimentExecutionManifest]:
    """Resolve an exact attempt or the newest successful attempt deterministically."""
    discovered = discover_execution_manifests(manifest_root, run_id=run_id)
    if execution_id is not None:
        safe_execution_id = _safe_identifier(execution_id, label="execution_id")
        matches = [item for item in discovered if item[1].execution_id == safe_execution_id]
        if not matches:
            raise FileNotFoundError(
                f"no execution manifest for run={run_id}, execution={safe_execution_id}"
            )
        selected = matches[0]
        if require_success and selected[1].execution_status != "succeeded":
            raise ValueError(
                f"execution {safe_execution_id} is {selected[1].execution_status}, not succeeded"
            )
        return selected

    candidates = (
        [item for item in discovered if item[1].execution_status == "succeeded"]
        if require_success
        else discovered
    )
    if not candidates:
        qualifier = "successful " if require_success else ""
        raise FileNotFoundError(f"no {qualifier}execution manifest exists for run={run_id}")
    return max(candidates, key=lambda item: (item[1].timestamp, item[1].execution_id))


def _is_reparse_point(path: Path) -> bool:
    """Identify symlinks and Windows junction/reparse entries before resolving them."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and bool(is_junction()):
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(attributes & reparse_flag)
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _resolve_confined_project_path(
    project_root: Path,
    value: str | Path,
    *,
    label: str = "manifest path",
) -> Path:
    """Resolve one project-local path after rejecting reparse-point traversal."""
    root = project_root.resolve()
    candidate = Path(value)
    unresolved = candidate if candidate.is_absolute() else root / candidate
    lexical = Path(os.path.abspath(unresolved))
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the project root: {value}") from exc

    current = root
    for part in relative.parts:
        current /= part
        if _is_reparse_point(current):
            raise ValueError(f"{label} traverses a symlink or reparse point: {value}")

    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the project root: {value}") from exc
    return resolved


def reproduction_command_path_mismatches(
    manifest: ExperimentExecutionManifest,
    *,
    project_root: Path,
) -> list[str]:
    """Reject reproduction argv that can write outside governed project data paths."""
    root = project_root.resolve()
    try:
        recorded_output = _resolve_confined_project_path(
            root,
            manifest.artifact_output_directory,
            label="artifact_output_directory",
        )
        command_output = _resolve_confined_project_path(
            root,
            _reproduction_option(manifest.reproduction_command, "--output-dir"),
            label="reproduction command --output-dir",
        )
        command_database = _resolve_confined_project_path(
            root,
            _reproduction_option(manifest.reproduction_command, "--database"),
            label="reproduction command --database",
        )
    except ValueError as exc:
        return [str(exc)]

    failures: list[str] = []
    if command_output != recorded_output:
        failures.append("artifact_output_directory differs from reproduction command --output-dir")
    expected_output = (root / "data" / "processed" / "lexical" / "schema-v1").resolve(strict=False)
    if recorded_output != expected_output:
        failures.append(
            "artifact output is not the governed data/processed/lexical/schema-v1 directory"
        )
    governed_data_root = (root / "data" / "processed").resolve(strict=False)
    try:
        command_database.relative_to(governed_data_root)
    except ValueError:
        failures.append("reproduction command --database is outside governed data/processed")
    return failures


def reproduction_environment_mismatches(
    manifest: ExperimentExecutionManifest,
    *,
    project_root: Path,
    notices: list[str] | None = None,
) -> list[str]:
    """Report static provenance drift before an exact reproduction is executed."""
    root = project_root.resolve()
    content_mismatches: list[str] = []
    other_mismatches: list[str] = []
    git_commit, _, _ = _git_execution_state(root)
    current_source_hash = hash_governed_source_tree(root)
    if current_source_hash != manifest.source_tree_hash:
        content_mismatches.append(
            "governed source/configuration tree differs from source_tree_hash"
        )
    if platform.python_version() != manifest.python_version:
        other_mismatches.append(
            "python_version differs: "
            f"expected={manifest.python_version}, actual={platform.python_version()}"
        )

    lock_path = root / "uv.lock"
    current_lock_hash = sha256_file(lock_path) if lock_path.is_file() else "MISSING"
    if current_lock_hash != manifest.dependency_lock_hash:
        content_mismatches.append("uv.lock differs from dependency_lock_hash")

    if manifest.dataset_manifest_path is None:
        content_mismatches.append("execution manifest has no dataset manifest path")
    else:
        dataset_path = _resolve_confined_project_path(
            root,
            manifest.dataset_manifest_path,
            label="dataset manifest path",
        )
        current_dataset_hash = sha256_file(dataset_path) if dataset_path.is_file() else "MISSING"
        if current_dataset_hash != manifest.dataset_manifest_hash:
            content_mismatches.append("dataset source manifest differs from dataset_manifest_hash")
        if dataset_path.is_file():
            try:
                current_source_file_hashes = _source_file_hashes_from_manifest(dataset_path)
            except ValueError as exc:
                content_mismatches.append(str(exc))
            else:
                if current_source_file_hashes != manifest.source_file_hashes:
                    content_mismatches.append(
                        "dataset source file checksums differ from source_file_hashes"
                    )

    for name, path_value in sorted(manifest.configuration_files.items()):
        path = _resolve_confined_project_path(
            root,
            path_value,
            label=f"configuration file {name}",
        )
        current_hash = sha256_file(path) if path.is_file() else "MISSING"
        if current_hash != manifest.configuration_hashes.get(name):
            content_mismatches.append(f"configuration file differs: {name} ({path_value})")

    if git_commit != manifest.git_commit:
        git_message = f"git_commit differs: expected={manifest.git_commit}, actual={git_commit}"
        if content_mismatches:
            content_mismatches.insert(0, git_message)
        elif notices is not None:
            notices.append(
                f"{git_message}; governed executable inputs and dataset manifest still match"
            )
    return [*content_mismatches, *other_mismatches]


def _reproduction_option(command: Sequence[str], option: str) -> str:
    try:
        index = command.index(option)
    except ValueError as exc:  # guarded by model validation
        raise ValueError(f"reproduction command is missing {option}") from exc
    if index + 1 >= len(command):  # guarded by model validation
        raise ValueError(f"reproduction command has no value for {option}")
    return command[index + 1]


def _artifact_file_inventory(artifact_root: Path) -> tuple[set[str], list[str]]:
    """Return the exact regular-file inventory without traversing reparse points."""
    observed: set[str] = set()
    failures: list[str] = []

    def record_walk_error(error: OSError) -> None:
        failures.append(f"could not enumerate lexical output files: {error}")

    for directory, directory_names, file_names in os.walk(
        artifact_root,
        topdown=True,
        onerror=record_walk_error,
        followlinks=False,
    ):
        current = Path(directory)
        safe_directories: list[str] = []
        for name in directory_names:
            path = current / name
            relative = path.relative_to(artifact_root).as_posix()
            if _is_reparse_point(path):
                failures.append(
                    f"lexical output directory is a symlink or reparse point: {relative}"
                )
            else:
                safe_directories.append(name)
        directory_names[:] = safe_directories

        for name in file_names:
            path = current / name
            relative = path.relative_to(artifact_root).as_posix()
            if _is_reparse_point(path):
                failures.append(f"lexical output file is a symlink or reparse point: {relative}")
                continue
            if not path.is_file():
                failures.append(f"lexical output entry is not a regular file: {relative}")
                continue
            if relative != "table-hashes.json":
                observed.add(relative)
    return observed, failures


def validate_execution_manifest_outputs(
    manifest: ExperimentExecutionManifest,
    *,
    project_root: Path,
    artifact_root: Path | None = None,
) -> list[str]:
    """Authenticate a canonical or archived artifact root against one sidecar."""
    failures: list[str] = []
    if manifest.execution_status != "succeeded":
        return [f"execution status is {manifest.execution_status}, not succeeded"]
    failures.extend(
        reproduction_command_path_mismatches(
            manifest,
            project_root=project_root,
        )
    )
    if failures:
        return failures
    try:
        output_dir = _resolve_confined_project_path(
            project_root,
            manifest.artifact_output_directory,
            label="artifact_output_directory",
        )
        command_output = _resolve_confined_project_path(
            project_root,
            _reproduction_option(manifest.reproduction_command, "--output-dir"),
            label="reproduction command --output-dir",
        )
        inspection_root = (
            output_dir
            if artifact_root is None
            else _resolve_confined_project_path(
                project_root,
                artifact_root,
                label="artifact-root override",
            )
        )
    except ValueError as exc:
        return [str(exc)]
    if command_output != output_dir:
        failures.append("artifact_output_directory differs from reproduction command --output-dir")
    if inspection_root.parent != output_dir.parent:
        failures.append("artifact-root override is not a direct sibling of recorded schema-v1")
        return failures
    if not inspection_root.is_dir() or _is_reparse_point(inspection_root):
        failures.append(f"lexical artifact root is not a real directory: {inspection_root}")
        return failures

    hash_manifest_path = inspection_root / "table-hashes.json"
    if not hash_manifest_path.is_file() or _is_reparse_point(hash_manifest_path):
        failures.append(f"lexical table-hashes.json is missing: {hash_manifest_path}")
        return failures
    observed_manifest_hash = sha256_file(hash_manifest_path)
    if observed_manifest_hash != manifest.output_hash_manifest_sha256:
        failures.append("table-hashes.json differs from output_hash_manifest_sha256")
        return failures
    try:
        payload = json.loads(hash_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        failures.append(f"could not parse lexical table-hashes.json: {exc}")
        return failures
    if not isinstance(payload, dict):
        failures.append("lexical table-hashes.json root is not an object")
        return failures
    if payload.get("schema_version") != 1:
        failures.append("lexical table-hashes.json schema_version is not 1")

    for field_name, expected in (
        ("table_logical_sha256", manifest.output_table_hashes),
        ("table_physical_sha256", manifest.output_table_physical_hashes),
    ):
        observed = payload.get(field_name)
        if not isinstance(observed, dict):
            failures.append(f"table-hashes.json field is not an object: {field_name}")
            continue
        normalized = {str(key): str(value) for key, value in observed.items()}
        if normalized != expected:
            failures.append(f"execution manifest disagrees with {field_name}")
    expected_tables = set(manifest.output_table_hashes)
    for field_name in ("table_counts", "artifacts"):
        observed = payload.get(field_name)
        if not isinstance(observed, dict):
            failures.append(f"table-hashes.json field is not an object: {field_name}")
        elif set(str(key) for key in observed) != expected_tables:
            failures.append(f"table-hashes.json field names unexpected tables: {field_name}")

    file_hashes = payload.get("file_sha256")
    if not isinstance(file_hashes, dict):
        failures.append("table-hashes.json field is not an object: file_sha256")
        return failures
    if not file_hashes:
        failures.append("table-hashes.json file_sha256 inventory is empty")

    declared_files: dict[str, str] = {}
    for relative_value, expected_value in sorted(file_hashes.items()):
        try:
            relative = _normalized_relative_inventory_path(
                str(relative_value),
                label="file_sha256 path",
            )
        except ValueError as exc:
            failures.append(str(exc))
            continue
        digest = str(expected_value)
        if not _SHA256_PATTERN.fullmatch(digest):
            failures.append(f"file_sha256 value is not SHA-256: {relative}")
            continue
        declared_files[relative] = digest

    actual_files, inventory_failures = _artifact_file_inventory(inspection_root)
    failures.extend(inventory_failures)
    declared_names = set(declared_files)
    for relative in sorted(declared_names - actual_files):
        failures.append(f"declared lexical output file is missing: {relative}")
    for relative in sorted(actual_files - declared_names):
        failures.append(f"undeclared lexical output file exists: {relative}")
    for relative in sorted(declared_names & actual_files):
        path = inspection_root / Path(relative)
        if sha256_file(path) != declared_files[relative]:
            failures.append(f"declared lexical output file hash differs: {relative}")
    return failures


def format_reproduction_command(command: Sequence[str]) -> str:
    """Render the validated argv for human inspection without executing a shell."""
    return shlex.join(command)
