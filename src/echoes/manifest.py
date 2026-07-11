"""Reproducible run-manifest generation."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from echoes.settings import ModelsConfig, load_config, validate_config_directory

HardwareValue = str | int | None


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


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        return "UNCOMMITTED", "uncommitted"

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    tree_status = "dirty" if status.stdout.strip() or status.returncode != 0 else "clean"
    return commit.stdout.strip(), tree_status


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "experiment"


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
