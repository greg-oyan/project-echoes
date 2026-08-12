"""Fail-closed command builders for the final-discovery campaign.

The CLI layer delegates here so production identity construction is testable
without invoking Typer.  This module performs no provisioning and never reads
credentials itself; the B2 adapter consumes them only when an object operation
is attempted.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from echoes.final_discovery.checkpoints import (
    StageCheckpointReceipt,
    reauthenticate_finalization_checkpoint_for_cleanup,
)
from echoes.final_discovery.config import (
    DEFAULT_FINAL_DISCOVERY_CONFIG,
    FinalDiscoveryConfig,
    final_discovery_config_sha256,
    load_final_discovery_config,
)
from echoes.final_discovery.disk_validation import (
    DiskFinalDiscoveryValidationReceipt,
    DiskFinalDiscoveryValidationResult,
    validate_final_discovery_disk_backed,
)
from echoes.final_discovery.inputs import (
    InputExpectation,
    ObjectInventory,
    RcloneB2ObjectStore,
    normalize_relative_object_path,
    sha256_file,
)
from echoes.final_discovery.knownness import KnownnessIndex, KnownRelationship
from echoes.final_discovery.models import EvidenceRow, FinalCandidate, PassageRecord
from echoes.final_discovery.nulls import EnsembleNullCalibrationRow
from echoes.final_discovery.passages import PassageParquetSources, PassageProjectionScope
from echoes.final_discovery.pipeline import (
    CampaignRequest,
    InputFileAnchor,
    assert_production_authorized,
)
from echoes.final_discovery.semantic import load_offline_sentence_encoder
from echoes.final_discovery.stages import StageCompletionManifest, StageStore
from echoes.final_discovery.storage import inspect_jsonl_file, iter_jsonl, read_jsonl
from echoes.final_discovery.validation import (
    FinalDiscoveryValidationReport,
    validate_final_discovery,
)
from echoes.manifest import hash_governed_source_tree

_PRODUCTION_DISK_FLOOR_BYTES = 80 * 1024**3
_PRODUCTION_VALIDATION_MEMORY_LIMIT_BYTES = 4 * 1024**3
_PRODUCTION_VALIDATION_THREADS = 1
_INDEPENDENT_VALIDATION_DIRECTORY_NAME = "independent-validation"
_INDEPENDENT_VALIDATION_WORK_DIRECTORY_NAME = "independent-validation-work"


class FinalDiscoveryCommandError(RuntimeError):
    """Raised when a CLI request cannot be bound to a clean exact source tree."""


def _path_size_inventory(root: Path) -> tuple[tuple[str, int], ...]:
    """List one local transfer tree without hashing its potentially large bytes."""

    if not root.is_dir() or root.is_symlink():
        raise FinalDiscoveryCommandError(f"local restart tree is absent or unsafe: {root}")
    resolved = root.resolve()
    rows: list[tuple[str, int]] = []
    for directory, directory_names, file_names in os.walk(resolved, followlinks=False):
        current = Path(directory)
        for name in directory_names:
            if (current / name).is_symlink():
                raise FinalDiscoveryCommandError("local restart tree contains a directory link")
        for name in file_names:
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise FinalDiscoveryCommandError("local restart tree contains a non-regular file")
            rows.append((path.relative_to(resolved).as_posix(), path.stat().st_size))
    return tuple(sorted(rows))


def _registered_output_prefixes(config: FinalDiscoveryConfig) -> tuple[str, ...]:
    return tuple(
        [
            f"checkpoints/{stage.number:02d}-{stage.stage_id}"
            for stage in config.stages
            if stage.upload_after_completion
        ]
        + ["final"]
    )


def _checkpoint_restart_trees(
    work_directory: Path,
    relative_prefix: str,
) -> tuple[Path, ...]:
    leaf = relative_prefix.split("/", 1)[1]
    parent = work_directory / "checkpoint-packages" / leaf
    if not parent.is_dir() or parent.is_symlink():
        return ()
    return tuple(
        child / "payload"
        for child in sorted(parent.iterdir())
        if child.is_dir() and not child.is_symlink() and (child / "payload").is_dir()
    )


def _final_restart_trees(work_directory: Path) -> tuple[Path, ...]:
    stage_root = work_directory / "stages" / "11-package_upload_verify"
    candidates: list[Path] = []
    completion_path = stage_root / "completion.json"
    if completion_path.is_file() and not completion_path.is_symlink():
        try:
            manifest = StageCompletionManifest.model_validate_json(completion_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise FinalDiscoveryCommandError("Stage 11 completion is invalid") from exc
        candidates.append(
            stage_root.joinpath(*PurePosixPath(manifest.artifacts_root).parts) / "upload"
        )
    in_progress = stage_root / "in-progress"
    if in_progress.is_dir() and not in_progress.is_symlink():
        candidates.extend(
            path / "artifacts" / "upload"
            for path in sorted(in_progress.iterdir())
            if path.is_dir() and not path.is_symlink() and (path / "artifacts" / "upload").is_dir()
        )
    return tuple(path for path in candidates if path.is_dir() and not path.is_symlink())


def inspect_production_output_namespace(
    *,
    work_directory: Path,
    output_bucket: str,
    output_prefix: str,
    config_path: Path = DEFAULT_FINAL_DISCOVERY_CONFIG,
) -> dict[str, Any]:
    """Reject unexpected or locally non-resumable B2 state before launch."""

    config = load_final_discovery_config(config_path)
    normalized_output_prefix = normalize_relative_object_path(
        output_prefix,
        label="final-discovery output prefix",
    )
    base_store = RcloneB2ObjectStore(bucket=output_bucket, prefix=normalized_output_prefix)
    inventory: ObjectInventory = base_store.inventory()
    registered = _registered_output_prefixes(config)
    objects_by_prefix: dict[str, list[tuple[str, int]]] = {prefix: [] for prefix in registered}
    for item in inventory.objects:
        matches = [prefix for prefix in registered if item.path.startswith(f"{prefix}/")]
        if len(matches) != 1:
            raise FinalDiscoveryCommandError(
                f"output namespace contains an unregistered object: {item.path}"
            )
        prefix = matches[0]
        objects_by_prefix[prefix].append((item.path[len(prefix) + 1 :], item.size))

    prefix_state: dict[str, dict[str, object]] = {}
    root = work_directory.resolve()
    for prefix in registered:
        remote_rows = tuple(sorted(objects_by_prefix[prefix]))
        if not remote_rows:
            continue
        local_trees = (
            _final_restart_trees(root)
            if prefix == "final"
            else _checkpoint_restart_trees(root, prefix)
        )
        matched_count: int | None = None
        for local_tree in local_trees:
            local_rows = _path_size_inventory(local_tree)
            local_by_path = dict(local_rows)
            if all(local_by_path.get(path) == size for path, size in remote_rows):
                matched_count = len(local_rows)
                break
        if matched_count is None:
            raise FinalDiscoveryCommandError(
                "output namespace state is not an exact resumable subset of preserved local "
                f"state: {prefix}"
            )
        prefix_state[prefix] = {
            "remote_object_count": len(remote_rows),
            "expected_complete_object_count": matched_count,
            "state": (
                "complete_path_size_inventory_requires_content_recheck"
                if len(remote_rows) == matched_count
                else "resumable_exact_path_size_subset"
            ),
        }
    return {
        "schema_version": 1,
        "experiment_id": config.experiment_id,
        "identity": {
            "provider": inventory.identity.provider,
            "bucket": inventory.identity.bucket,
            "prefix": inventory.identity.prefix,
            "canonical_uri": inventory.identity.canonical_uri,
        },
        "state": "empty_new_campaign" if not inventory.objects else "registered_restart_state",
        "portable_path_size_inventory_sha256": inventory.transfer_sha256,
        "object_count": inventory.object_count,
        "total_size": inventory.total_size,
        "registered_prefixes": list(registered),
        "active_prefix_state": prefix_state,
        "content_rechecked_by_stage_specific_immutable_transfer": True,
    }


def verify_production_finalization_for_cleanup(
    *,
    work_directory: Path,
    output_bucket: str,
    output_prefix: str,
) -> dict[str, Any]:
    """Boundedly reauthenticate the Stage 11 B2 finalization object.

    This is a deletion gate, not a campaign stage and not a monitor. It lists
    the complete remote path/size inventory once and downloads only the small
    self-describing finalization records. The initial receipt remains the
    evidence for Stage 11's full ``rclone check --download`` comparison.
    """

    normalized_output_prefix = normalize_relative_object_path(
        output_prefix,
        label="final-discovery output prefix",
    )
    root = work_directory.resolve()
    stage_store = StageStore(root / "stages")
    manifests = stage_store.authenticate_all_completions()
    if len(manifests) != 11:
        raise FinalDiscoveryCommandError("cleanup verification requires eleven stages")
    stage_eleven = manifests[-1]
    if stage_eleven.stage_number != 11 or stage_eleven.stage_id != "package_upload_verify":
        raise FinalDiscoveryCommandError("the terminal campaign stage identity differs")
    completion_sha256 = sha256_file(stage_store.completion_path(stage_eleven.stage_id))
    checkpoint_parent = root / "checkpoint-packages" / "11-package_upload_verify"
    if not checkpoint_parent.is_dir() or checkpoint_parent.is_symlink():
        raise FinalDiscoveryCommandError("Stage 11 checkpoint workspaces are absent or unsafe")
    checkpoint_roots = tuple(
        path
        for path in sorted(checkpoint_parent.glob(f"{completion_sha256}-*"))
        if path.is_dir()
        and not path.is_symlink()
        and (path / "payload").is_dir()
        and (path / "stage-checkpoint-receipt.json").is_file()
    )
    if not checkpoint_roots:
        raise FinalDiscoveryCommandError("no complete Stage 11 checkpoint receipt is present")

    receipts: list[StageCheckpointReceipt] = []
    for checkpoint_root in checkpoint_roots:
        try:
            receipt = StageCheckpointReceipt.model_validate_json(
                (checkpoint_root / "stage-checkpoint-receipt.json").read_bytes()
            )
        except (OSError, ValueError) as exc:
            raise FinalDiscoveryCommandError(
                f"Stage 11 checkpoint receipt is invalid: {checkpoint_root.name}"
            ) from exc
        if receipt.completion_manifest_sha256 != completion_sha256:
            raise FinalDiscoveryCommandError("Stage 11 checkpoint completion identity differs")
        receipts.append(receipt)
    stable_bindings = {
        json.dumps(
            receipt.model_dump(mode="json", exclude={"transfer_action"}),
            sort_keys=True,
            separators=(",", ":"),
        )
        for receipt in receipts
    }
    if len(stable_bindings) != 1:
        raise FinalDiscoveryCommandError("Stage 11 checkpoint attempts disagree")

    finalization_directory = root / "campaign-seals" / completion_sha256
    finalization_receipt_path = finalization_directory / "finalization-receipt.json"
    campaign_seal_path = finalization_directory / "campaign-seal.json"
    try:
        finalization_receipt = json.loads(finalization_receipt_path.read_text(encoding="ascii"))
        campaign_seal = json.loads(campaign_seal_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalDiscoveryCommandError("local finalization binding is absent or invalid") from exc
    if not isinstance(finalization_receipt, dict) or not isinstance(campaign_seal, dict):
        raise FinalDiscoveryCommandError("local finalization records must be JSON objects")
    stable_checkpoint_binding = receipts[0].model_dump(mode="json", exclude={"transfer_action"})
    if (
        finalization_receipt.get("receipt_kind") != "post_stage_11_finalization_checkpoint_v1"
        or finalization_receipt.get("stage_11_completion_manifest_sha256") != completion_sha256
        or finalization_receipt.get("campaign_seal_sha256") != sha256_file(campaign_seal_path)
        or finalization_receipt.get("stage_11_checkpoint") != stable_checkpoint_binding
    ):
        raise FinalDiscoveryCommandError("local finalization receipt does not bind Stage 11")

    checkpoint_prefix = f"{normalized_output_prefix}/checkpoints/11-package_upload_verify"
    store = RcloneB2ObjectStore(bucket=output_bucket, prefix=checkpoint_prefix)
    expected_destination = store.identity.canonical_uri
    seal_checkpoint = campaign_seal.get("finalization_checkpoint")
    seal_validation = campaign_seal.get("all_stage_validation")
    if (
        not isinstance(seal_checkpoint, dict)
        or seal_checkpoint.get("destination") != expected_destination
        or seal_checkpoint.get("remote_reverification_required_before_server_cleanup") is not True
        or seal_checkpoint.get("required_supplemental_paths")
        != [
            "all-stage-validation-receipt.json",
            "all-stage-validation-report.json",
            "campaign-seal.json",
        ]
        or not isinstance(seal_validation, dict)
        or seal_validation.get("passed") is not True
        or seal_validation.get("authenticated_stage_count") != 11
    ):
        raise FinalDiscoveryCommandError("campaign seal does not authorize cleanup verification")

    selected_index = max(
        range(len(receipts)),
        key=lambda index: (receipts[index].transfer_action != "verified_existing", index),
    )
    cleanup = reauthenticate_finalization_checkpoint_for_cleanup(
        store,
        checkpoint_root=checkpoint_roots[selected_index],
        required_supplemental_paths=(
            "all-stage-validation-receipt.json",
            "all-stage-validation-report.json",
            "campaign-seal.json",
        ),
    )
    return {
        "schema_version": 1,
        "experiment_id": "final-discovery-v1",
        "cleanup_finalization_reauthenticated": True,
        "full_content_check_scope": "initial_stage_11_transfer_receipt",
        "cleanup_recheck_scope": cleanup.verification_scope,
        "completion_manifest_sha256": completion_sha256,
        "campaign_seal_sha256": sha256_file(campaign_seal_path),
        "finalization_receipt_sha256": sha256_file(finalization_receipt_path),
        "successful_checkpoint_attempt_count": len(receipts),
        "per_attempt_receipt_sha256": [
            sha256_file(path / "stage-checkpoint-receipt.json") for path in checkpoint_roots
        ],
        "remote_verification": cleanup.model_dump(mode="json"),
    }


def knownness_receipt_path(knownness_path: Path) -> Path:
    """Return the fixed sidecar name required beside a knownness JSONL."""

    if knownness_path.suffix.casefold() != ".jsonl":
        raise FinalDiscoveryCommandError("knownness path must have a .jsonl suffix")
    return knownness_path.with_suffix(".receipt.json")


def _run_git(project_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise FinalDiscoveryCommandError(f"could not execute Git: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:1000]
        suffix = f": {detail}" if detail else ""
        raise FinalDiscoveryCommandError(f"Git {' '.join(arguments)} failed{suffix}")
    return completed.stdout


def authenticate_clean_git_tree(project_root: Path) -> tuple[str, str]:
    """Require a clean exact commit and return commit plus governed-tree SHA-256."""

    root = project_root.resolve()
    commit = _run_git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    if len(commit) not in {40, 64} or any(value not in "0123456789abcdef" for value in commit):
        raise FinalDiscoveryCommandError("Git HEAD is not one full lowercase object ID")
    status = _run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status:
        raise FinalDiscoveryCommandError(
            "production requires a completely clean Git tree, including no untracked files"
        )
    expected = os.environ.get("ECHOES_EXPECTED_GIT_COMMIT")
    if expected is None or expected != commit:
        raise FinalDiscoveryCommandError("Git HEAD differs from ECHOES_EXPECTED_GIT_COMMIT")
    return commit, hash_governed_source_tree(root)


def current_source_identity(project_root: Path) -> tuple[str, str]:
    """Return the current commit and governed-tree digest for a local fixture."""

    root = project_root.resolve()
    commit = _run_git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    if len(commit) not in {40, 64} or any(value not in "0123456789abcdef" for value in commit):
        raise FinalDiscoveryCommandError("Git HEAD is not one full lowercase object ID")
    return commit, hash_governed_source_tree(root)


def _input_file_anchors(
    project_root: Path,
    config: FinalDiscoveryConfig,
) -> tuple[InputFileAnchor, ...]:
    anchors: list[InputFileAnchor] = []
    for artifact in config.inputs:
        if artifact.role == "canonical_m7":
            continue
        for relative_path, expected_sha256 in sorted(artifact.expected_hashes.items()):
            path = project_root / Path(*relative_path.split("/"))
            if not path.is_file() or path.is_symlink():
                raise FinalDiscoveryCommandError(
                    f"governed local input is missing or unsafe: {relative_path}"
                )
            if sha256_file(path) != expected_sha256:
                raise FinalDiscoveryCommandError(
                    f"governed local input hash differs: {relative_path}"
                )
            anchors.append(
                InputFileAnchor(
                    relative_path=relative_path,
                    path=path,
                    sha256=expected_sha256,
                )
            )
    return tuple(anchors)


def build_production_campaign_request(
    *,
    project_root: Path,
    work_directory: Path,
    prepared_passages_path: Path,
    knownness_path: Path,
    offline_model_root: Path,
    m7_bucket: str,
    m7_prefix: str,
    output_bucket: str,
    output_prefix: str,
    config_path: Path = DEFAULT_FINAL_DISCOVERY_CONFIG,
) -> CampaignRequest:
    """Construct the exact production request without starting the campaign."""

    root = project_root.resolve()
    config_file = config_path if config_path.is_absolute() else root / config_path
    config = load_final_discovery_config(config_file)
    assert_production_authorized(config)
    code_commit, code_sha256 = authenticate_clean_git_tree(root)
    normalized_output_prefix = normalize_relative_object_path(
        output_prefix,
        label="final-discovery output prefix",
    )
    normalized_m7_prefix = normalize_relative_object_path(
        m7_prefix,
        label="M7 input prefix",
    )
    knownness = knownness_path.resolve()
    knownness_receipt = knownness_receipt_path(knownness).resolve()
    prepared = prepared_passages_path.resolve()
    model_root = offline_model_root.resolve()
    for label, path in (
        ("prepared-passage projection", prepared),
        ("knownness projection", knownness),
        ("knownness projection receipt", knownness_receipt),
    ):
        if not path.is_file() or path.is_symlink():
            raise FinalDiscoveryCommandError(f"{label} is missing or unsafe: {path}")
    if not model_root.is_dir() or model_root.is_symlink():
        raise FinalDiscoveryCommandError(f"offline model root is missing or unsafe: {model_root}")

    m7_input = next(item for item in config.inputs if item.role == "canonical_m7")
    if m7_input.expected_manifest_sha256 is None:
        raise FinalDiscoveryCommandError("the canonical M7 manifest is not pinned")
    encoder = load_offline_sentence_encoder(model_root, config.embedding_model)
    m7_store = RcloneB2ObjectStore(bucket=m7_bucket, prefix=normalized_m7_prefix)
    checkpoint_stores = {
        stage.stage_id: RcloneB2ObjectStore(
            bucket=output_bucket,
            prefix=(f"{normalized_output_prefix}/checkpoints/{stage.number:02d}-{stage.stage_id}"),
        )
        for stage in config.stages
        if stage.upload_after_completion
    }
    processed = root / "data" / "processed"
    passage_sources = PassageParquetSources(
        passage_root=processed / "passages" / "schema-v1",
        hebrew_tokens_path=processed / "macula-hebrew" / "25.08.11" / "tokens.parquet",
        greek_tokens_path=processed / "macula-greek" / "24.06.17" / "tokens.parquet",
        hebrew_ketiv_tokens_path=(
            processed / "oshb-morphhb" / "master-3d15126" / "kq_ketiv_tokens.parquet"
        ),
        benchmark_config_path=root / "config" / "benchmark.yaml",
    )
    return CampaignRequest(
        config=config,
        stage_store=StageStore(work_directory.resolve() / "stages"),
        prepared_passages_path=prepared,
        m7_store=m7_store,
        m7_expectation=InputExpectation(
            identity=m7_store.identity,
            table_hashes_sha256=m7_input.expected_manifest_sha256,
        ),
        destination_store=RcloneB2ObjectStore(
            bucket=output_bucket,
            prefix=f"{normalized_output_prefix}/final",
        ),
        code_sha256=code_sha256,
        code_commit=code_commit,
        execution_mode="production",
        offline_model_root=model_root,
        encoder=encoder,
        minimum_free_disk_bytes=_PRODUCTION_DISK_FLOOR_BYTES,
        input_file_anchors=_input_file_anchors(root, config),
        prepared_passages_expected_sha256=sha256_file(prepared),
        knownness_source_path=knownness,
        knownness_source_sha256=sha256_file(knownness),
        knownness_projection_receipt_path=knownness_receipt,
        knownness_benchmark_root=processed / "benchmarks" / "schema-v1",
        positive_control_config_path=root / "data" / "benchmarks" / "positive_controls.yaml",
        positive_control_data_path=root / "data" / "benchmarks" / "positive_controls.csv",
        passage_sources=passage_sources,
        passage_projection_scope=PassageProjectionScope(
            include_greek_critical_core=True,
            include_hebrew_ketiv=True,
        ),
        checkpoint_stores=checkpoint_stores,
    )


def _completed_artifact_root(
    store: StageStore,
    manifest: StageCompletionManifest,
) -> Path:
    return store.completion_path(manifest.stage_id).parent.joinpath(
        *PurePosixPath(manifest.artifacts_root).parts
    )


def _authenticated_stage_json_object(
    root: Path,
    manifest: StageCompletionManifest,
    relative_path: str,
) -> dict[str, Any]:
    """Read one JSON object whose exact bytes belong to an authenticated stage."""

    artifact = next(
        (item for item in manifest.artifacts if item.path == relative_path),
        None,
    )
    if artifact is None:
        raise FinalDiscoveryCommandError(
            f"authenticated stage {manifest.stage_id} lacks {relative_path}"
        )
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    if not path.is_file() or path.is_symlink():
        raise FinalDiscoveryCommandError(f"authenticated stage JSON is missing or unsafe: {path}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise FinalDiscoveryCommandError(
            f"could not read authenticated stage JSON: {path}"
        ) from exc
    if len(payload) != artifact.size or hashlib.sha256(payload).hexdigest() != artifact.sha256:
        raise FinalDiscoveryCommandError(
            f"authenticated stage JSON changed after stage authentication: {relative_path}"
        )
    try:
        parsed = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FinalDiscoveryCommandError(
            f"authenticated stage JSON is malformed: {relative_path}"
        ) from exc
    if not isinstance(parsed, dict):
        raise FinalDiscoveryCommandError(
            f"authenticated stage JSON is not an object: {relative_path}"
        )
    return parsed


def _read_validation_report(path: Path) -> FinalDiscoveryValidationReport:
    try:
        payload = json.loads(path.read_bytes())
        if not isinstance(payload, dict):
            raise ValueError("validation report is not a JSON object")
        serialized_error_count = payload.pop("error_count", None)
        serialized_passed = payload.pop("passed", None)
        report = FinalDiscoveryValidationReport.model_validate(payload)
    except (OSError, UnicodeError, ValueError) as exc:
        raise FinalDiscoveryCommandError(
            f"independent validation report is malformed: {path}"
        ) from exc
    if serialized_error_count != report.error_count or serialized_passed is not report.passed:
        raise FinalDiscoveryCommandError(
            "independent validation report computed fields do not reconcile"
        )
    return report


def _read_validation_receipt(path: Path) -> DiskFinalDiscoveryValidationReceipt:
    try:
        return DiskFinalDiscoveryValidationReceipt.model_validate_json(path.read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        raise FinalDiscoveryCommandError(
            f"independent validation receipt is malformed: {path}"
        ) from exc


def _authenticate_production_validation(
    *,
    output_directory: Path,
    input_paths: tuple[Path, Path, Path, Path],
    config: FinalDiscoveryConfig,
    store: StageStore,
) -> DiskFinalDiscoveryValidationResult:
    if not output_directory.is_dir() or output_directory.is_symlink():
        raise FinalDiscoveryCommandError(
            f"independent validation output is missing or unsafe: {output_directory}"
        )
    report_path = output_directory / "validation-report.json"
    receipt_path = output_directory / "validation-receipt.json"
    report = _read_validation_report(report_path)
    receipt = _read_validation_receipt(receipt_path)
    try:
        report_size = report_path.stat().st_size
        report_sha256 = sha256_file(report_path)
    except OSError as exc:
        raise FinalDiscoveryCommandError(
            "could not authenticate the independent validation report"
        ) from exc
    if (
        report.experiment_id != config.experiment_id
        or receipt.config_sha256 != final_discovery_config_sha256(config)
        or receipt.expected_authenticated_stage_count != 11
        or receipt.authenticated_stage_count != 11
        or not receipt.validation_passed
        or not report.passed
        or report.authenticated_stage_count != 11
        or receipt.evidence_pair_count != report.candidate_count
        or receipt.report_file_name != report_path.name
        or receipt.report_sha256 != report_sha256
        or receipt.report_size_bytes != report_size
        or receipt.retained_finding_count != len(report.findings)
        or receipt.total_finding_count != report.error_count
        or receipt.resource_bounds.duckdb_memory_limit_bytes
        != _PRODUCTION_VALIDATION_MEMORY_LIMIT_BYTES
        or receipt.resource_bounds.duckdb_threads != _PRODUCTION_VALIDATION_THREADS
    ):
        raise FinalDiscoveryCommandError(
            "independent disk-validation report or receipt is not an authenticated pass"
        )
    expected_orderings = (
        "candidate_pair_id,detector_id",
        "ensemble_score_desc,candidate_pair_id",
        "candidate_pair_id",
        "candidate_pair_id",
    )
    for path, input_receipt, expected_ordering in zip(
        input_paths,
        receipt.inputs,
        expected_orderings,
        strict=True,
    ):
        if input_receipt.file_name != path.name or input_receipt.ordering != expected_ordering:
            raise FinalDiscoveryCommandError(
                f"independent validation input identity changed: {input_receipt.role}"
            )
        if not path.is_file() or path.is_symlink():
            raise FinalDiscoveryCommandError(
                f"independent validation input is missing or unsafe: {input_receipt.role}"
            )
        try:
            observed = inspect_jsonl_file(path)
        except (OSError, ValueError) as exc:
            raise FinalDiscoveryCommandError(
                f"could not inspect independent validation input: {input_receipt.role}"
            ) from exc
        if (
            observed.row_count != input_receipt.row_count
            or observed.size_bytes != input_receipt.size_bytes
            or observed.sha256 != input_receipt.sha256
        ):
            raise FinalDiscoveryCommandError(
                f"independent validation input changed: {input_receipt.role}"
            )
    completions = store.authenticate_all_completions()
    if len(completions) != 11:
        raise FinalDiscoveryCommandError(
            "independent validation restart authentication did not find eleven stages"
        )
    return DiskFinalDiscoveryValidationResult(
        output_directory=output_directory,
        report_path=report_path,
        receipt_path=receipt_path,
        report=report,
        receipt=receipt,
    )


def _validate_completed_production_campaign(
    *,
    work_directory: Path,
    config: FinalDiscoveryConfig,
    store: StageStore,
    passages: dict[str, PassageRecord],
    knownness_path: Path,
    evidence_path: Path,
    candidates_path: Path,
    full_null_path: Path,
    ablated_null_path: Path,
) -> FinalDiscoveryValidationReport:
    input_paths = (evidence_path, candidates_path, full_null_path, ablated_null_path)
    output_directory = work_directory / _INDEPENDENT_VALIDATION_DIRECTORY_NAME
    if not output_directory.exists():
        validate_final_discovery_disk_backed(
            evidence_path,
            candidates_path,
            full_null_path,
            ablated_null_path,
            output_directory,
            passages=passages,
            knownness=iter_jsonl(knownness_path, KnownRelationship),
            config=config,
            memory_limit_bytes=_PRODUCTION_VALIDATION_MEMORY_LIMIT_BYTES,
            temp_directory=(work_directory / _INDEPENDENT_VALIDATION_WORK_DIRECTORY_NAME),
            stage_store=store,
            expected_authenticated_stage_count=11,
            threads=_PRODUCTION_VALIDATION_THREADS,
        )
    result = _authenticate_production_validation(
        output_directory=output_directory,
        input_paths=input_paths,
        config=config,
        store=store,
    )
    return result.report


def validate_completed_campaign(
    *,
    work_directory: Path,
    config_path: Path = DEFAULT_FINAL_DISCOVERY_CONFIG,
) -> FinalDiscoveryValidationReport:
    """Independently authenticate and scientifically recompute all eleven stages."""

    config = load_final_discovery_config(config_path)
    resolved_work_directory = work_directory.resolve()
    store = StageStore(resolved_work_directory / "stages")
    completions = store.authenticate_all_completions()
    if len(completions) != 11:
        raise FinalDiscoveryCommandError("completed campaign does not contain eleven stages")
    expected_config_sha256 = final_discovery_config_sha256(config)
    code_sha256 = completions[0].code_sha256
    code_commit = completions[0].code_commit
    for completion in completions:
        store.authenticate_completion(
            completion.stage_id,
            expected_config_sha256=expected_config_sha256,
            expected_code_sha256=code_sha256,
            expected_code_commit=code_commit,
        )
    by_stage = {manifest.stage_id: manifest for manifest in completions}
    stage_one = _completed_artifact_root(store, by_stage["authenticate_materialize_inputs"])
    stage_seven = _completed_artifact_root(store, by_stage["empirical_null_controls"])
    stage_eight = _completed_artifact_root(store, by_stage["transparent_final_ensemble"])
    input_summary = _authenticated_stage_json_object(
        stage_one,
        by_stage["authenticate_materialize_inputs"],
        "input-summary.json",
    )
    execution_mode = input_summary.get("execution_mode")
    if execution_mode not in {"fixture", "production"}:
        raise FinalDiscoveryCommandError(
            "authenticated Stage 1 input summary has an unsupported execution mode"
        )
    passage_rows = read_jsonl(stage_one / "passages.jsonl", PassageRecord)
    passages = {row.passage_id: row for row in passage_rows}
    if len(passages) != len(passage_rows):
        raise FinalDiscoveryCommandError("completed passage projection repeats a passage ID")
    evidence_path = stage_seven / "evidence.jsonl"
    candidates_path = stage_eight / "candidates.jsonl"
    full_null_path = stage_seven / "ensemble-null-full.jsonl"
    ablated_null_path = stage_seven / "ensemble-null-remove-all-english.jsonl"
    knownness_path = stage_one / "known-relationships.jsonl"
    if execution_mode == "production":
        return _validate_completed_production_campaign(
            work_directory=resolved_work_directory,
            config=config,
            store=store,
            passages=passages,
            knownness_path=knownness_path,
            evidence_path=evidence_path,
            candidates_path=candidates_path,
            full_null_path=full_null_path,
            ablated_null_path=ablated_null_path,
        )
    evidence = read_jsonl(evidence_path, EvidenceRow)
    candidates = read_jsonl(candidates_path, FinalCandidate)
    full_null = read_jsonl(full_null_path, EnsembleNullCalibrationRow)
    ablated_null = read_jsonl(ablated_null_path, EnsembleNullCalibrationRow)
    return validate_final_discovery(
        evidence,
        candidates,
        config=config,
        stage_store=store,
        require_all_stages=True,
        passages=passages,
        knownness=KnownnessIndex(iter_jsonl(knownness_path, KnownRelationship)),
        null_calibration_by_pair=full_null,
        english_ablation_null_calibration_by_pair=ablated_null,
    )


__all__ = [
    "FinalDiscoveryCommandError",
    "authenticate_clean_git_tree",
    "build_production_campaign_request",
    "current_source_identity",
    "knownness_receipt_path",
    "validate_completed_campaign",
]
