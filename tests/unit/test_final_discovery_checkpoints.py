"""Bounded durable-upload tests for authenticated stage checkpoints."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from echoes.final_discovery.checkpoints import (
    StageCheckpointError,
    StageCheckpointMetadata,
    package_and_upload_stage_checkpoint,
    reauthenticate_finalization_checkpoint_for_cleanup,
    validate_checkpoint_store_mapping,
)
from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.inputs import (
    LocalObjectStore,
    ObjectStoreConflictError,
    ObjectStoreIdentity,
)
from echoes.final_discovery.stages import StageAuthenticationError, StageRunResult, StageStore

CONFIG_SHA = "a" * 64
CODE_SHA = "b" * 64
INPUT_SHA = "c" * 64
CODE_COMMIT = "d" * 40


def _write_first_stage(root: Path) -> None:
    (root / "input-receipt.json").write_bytes(b'{"authenticated":true}\n')


def _write_second_stage(root: Path) -> None:
    report = root / "nested" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_bytes(b'{"stage":2}\n')
    binary = root / "vectors" / "part-000.bin"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x00\x01deterministic-stage-artifact\n")


def _write_numbered_stage(root: Path, number: int) -> None:
    (root / "artifact.json").write_bytes(f'{{"stage":{number}}}\n'.encode("ascii"))


def _completed_upload_stage(store: StageStore) -> StageRunResult:
    store.run_stage(
        "authenticate_materialize_inputs",
        input_hashes={"m7/materialization-receipt": INPUT_SHA},
        config_sha256=CONFIG_SHA,
        code_sha256=CODE_SHA,
        code_commit=CODE_COMMIT,
        producer=_write_first_stage,
    )
    return store.run_stage(
        "semantic_representations_indexes",
        input_hashes={},
        config_sha256=CONFIG_SHA,
        code_sha256=CODE_SHA,
        code_commit=CODE_COMMIT,
        producer=_write_second_stage,
    )


def _local_destination(root: Path, *, prefix: str) -> LocalObjectStore:
    return LocalObjectStore(
        root,
        identity=ObjectStoreIdentity(
            provider="b2",
            bucket="project-echoes-archive",
            prefix=prefix,
        ),
    )


def _completed_stage_eleven(store: StageStore) -> StageRunResult:
    result: StageRunResult | None = None
    for registration in load_final_discovery_config().stages:
        result = store.run_stage(
            registration.stage_id,
            input_hashes={"fixture-root": INPUT_SHA} if registration.number == 1 else {},
            config_sha256=CONFIG_SHA,
            code_sha256=CODE_SHA,
            code_commit=CODE_COMMIT,
            producer=lambda root, number=registration.number: _write_numbered_stage(root, number),
        )
    assert result is not None
    return result


def test_stage_checkpoint_tree_contains_exact_completion_and_full_artifact_tree(
    tmp_path: Path,
) -> None:
    stage_store = StageStore(tmp_path / "stages")
    result = _completed_upload_stage(stage_store)
    remote_root = tmp_path / "remote"
    remote = _local_destination(
        remote_root,
        prefix="final-discovery-v1/checkpoints/02-semantic",
    )

    receipt = package_and_upload_stage_checkpoint(
        stage_store,
        result,
        remote,
        checkpoint_root=tmp_path / "checkpoint-build",
        expected_store_identity=remote.identity,
    )

    assert receipt.stage_number == 2
    assert receipt.stage_id == "semantic_representations_indexes"
    assert receipt.completion_manifest_sha256 == result.completion_manifest_sha256
    assert receipt.output_inventory_sha256 == result.manifest.output_inventory_sha256
    assert receipt.artifact_count == len(result.manifest.artifacts) == 2
    assert receipt.supplemental_file_count == 0
    assert receipt.supplemental_inventory_sha256 is None
    assert receipt.package_source_file_count == 4
    assert receipt.transfer_action == "uploaded_new"
    assert receipt.store_identity.canonical_uri == remote.identity.canonical_uri
    assert receipt.transfer_mode == "direct_authenticated_tree"
    assert receipt.local_payload_uses_same_filesystem_hardlinks
    assert sorted(path.relative_to(remote_root).as_posix() for path in remote_root.rglob("*")) == [
        "artifacts",
        "artifacts/nested",
        "artifacts/nested/report.json",
        "artifacts/vectors",
        "artifacts/vectors/part-000.bin",
        "checkpoint.json",
        "completion.json",
    ]
    assert (remote_root / "completion.json").read_bytes() == stage_store.completion_path(
        result.manifest.stage_id
    ).read_bytes()
    metadata = StageCheckpointMetadata.model_validate_json(
        (remote_root / "checkpoint.json").read_bytes()
    )
    assert metadata.completion_manifest_sha256 == result.completion_manifest_sha256
    assert metadata.output_inventory_sha256 == result.manifest.output_inventory_sha256
    assert (remote_root / "artifacts/nested/report.json").read_bytes() == b'{"stage":2}\n'
    assert (
        remote_root / "artifacts/vectors/part-000.bin"
    ).read_bytes() == b"\x00\x01deterministic-stage-artifact\n"

    source_artifacts = (
        stage_store.completion_path(result.manifest.stage_id).parent
        / result.manifest.artifacts_root
    )
    assert (source_artifacts / "nested" / "report.json").is_file()
    assert (source_artifacts / "vectors" / "part-000.bin").is_file()
    assert os.path.samefile(
        source_artifacts / "nested" / "report.json",
        tmp_path / "checkpoint-build/payload/artifacts/nested/report.json",
    )


def test_stage_checkpoint_authenticates_post_completion_campaign_seal(
    tmp_path: Path,
) -> None:
    stage_store = StageStore(tmp_path / "stages")
    result = _completed_upload_stage(stage_store)
    remote_root = tmp_path / "remote"
    remote = _local_destination(
        remote_root,
        prefix="final-discovery-v1/checkpoints/02-semantic",
    )
    seal = tmp_path / "campaign-seal.json"
    seal.write_bytes(b'{"authenticated_stage_count":11,"passed":true}\n')

    receipt = package_and_upload_stage_checkpoint(
        stage_store,
        result,
        remote,
        checkpoint_root=tmp_path / "checkpoint-build",
        supplemental_files={"campaign-seal.json": seal},
    )

    assert receipt.supplemental_file_count == 1
    assert receipt.supplemental_inventory_sha256 is not None
    assert receipt.package_source_file_count == 5
    assert (remote_root / "supplemental/campaign-seal.json").read_bytes() == seal.read_bytes()
    metadata = StageCheckpointMetadata.model_validate_json(
        (remote_root / "checkpoint.json").read_bytes()
    )
    assert metadata.supplemental_artifacts[0].path == "campaign-seal.json"
    assert metadata.supplemental_inventory_sha256 == receipt.supplemental_inventory_sha256


def test_cleanup_reauthenticates_stage_eleven_inventory_and_finalization_bytes(
    tmp_path: Path,
) -> None:
    stage_store = StageStore(tmp_path / "stages")
    result = _completed_stage_eleven(stage_store)
    remote_root = tmp_path / "remote"
    remote = _local_destination(
        remote_root,
        prefix="final-discovery-v1/checkpoints/11-package_upload_verify",
    )
    supplemental = {
        "all-stage-validation-receipt.json": tmp_path / "validation-receipt.json",
        "all-stage-validation-report.json": tmp_path / "validation-report.json",
        "campaign-seal.json": tmp_path / "campaign-seal.json",
    }
    supplemental["all-stage-validation-receipt.json"].write_bytes(b'{"passed":true}\n')
    supplemental["all-stage-validation-report.json"].write_bytes(
        b'{"authenticated_stage_count":11,"passed":true}\n'
    )
    supplemental["campaign-seal.json"].write_bytes(
        b'{"remote_reverification_required_before_server_cleanup":true}\n'
    )
    checkpoint_root = tmp_path / "checkpoint-build"
    receipt = package_and_upload_stage_checkpoint(
        stage_store,
        result,
        remote,
        checkpoint_root=checkpoint_root,
        supplemental_files=supplemental,
    )
    (checkpoint_root / "stage-checkpoint-receipt.json").write_text(
        receipt.model_dump_json(),
        encoding="ascii",
    )

    verification = reauthenticate_finalization_checkpoint_for_cleanup(
        remote,
        checkpoint_root=checkpoint_root,
        required_supplemental_paths=tuple(supplemental),
    )

    assert verification.stage_number == 11
    assert verification.completion_manifest_sha256 == result.completion_manifest_sha256
    assert verification.initial_transfer_action == "uploaded_new"
    assert verification.object_count == receipt.package_source_file_count
    assert verification.reverified_transfer_inventory_sha256 == (
        receipt.transfer_verification.remote_inventory_sha256
    )
    assert set(verification.critical_file_sha256) == {
        "checkpoint.json",
        "completion.json",
        "supplemental/all-stage-validation-receipt.json",
        "supplemental/all-stage-validation-report.json",
        "supplemental/campaign-seal.json",
    }

    (remote_root / "supplemental/campaign-seal.json").write_bytes(
        b'{"remote_reverification_required_before_server_cleanup":null}\n'
    )
    with pytest.raises(StageCheckpointError, match="critical file differs"):
        reauthenticate_finalization_checkpoint_for_cleanup(
            remote,
            checkpoint_root=checkpoint_root,
            required_supplemental_paths=tuple(supplemental),
        )


def test_repeat_build_is_byte_deterministic_and_rechecks_existing_exact_store(
    tmp_path: Path,
) -> None:
    stage_store = StageStore(tmp_path / "stages")
    result = _completed_upload_stage(stage_store)
    remote = _local_destination(
        tmp_path / "remote",
        prefix="final-discovery-v1/checkpoints/02-semantic",
    )
    first = package_and_upload_stage_checkpoint(
        stage_store,
        result,
        remote,
        checkpoint_root=tmp_path / "first-build",
    )
    second = package_and_upload_stage_checkpoint(
        stage_store,
        result,
        remote,
        checkpoint_root=tmp_path / "second-build",
    )

    assert first.package_source_inventory_sha256 == second.package_source_inventory_sha256
    assert first.transfer_verification.local_inventory_sha256 == (
        second.transfer_verification.local_inventory_sha256
    )
    assert first.transfer_action == "uploaded_new"
    assert second.transfer_action == "verified_existing"
    assert second.transfer_verification.object_count == 4


def test_checkpoint_upload_resumes_an_exact_partial_prefix_without_replacement(
    tmp_path: Path,
) -> None:
    stage_store = StageStore(tmp_path / "stages")
    result = _completed_upload_stage(stage_store)
    remote_root = tmp_path / "remote"
    remote = _local_destination(
        remote_root,
        prefix="final-discovery-v1/checkpoints/02-semantic",
    )
    package_and_upload_stage_checkpoint(
        stage_store,
        result,
        _local_destination(
            tmp_path / "complete-remote",
            prefix="final-discovery-v1/checkpoints/02-semantic",
        ),
        checkpoint_root=tmp_path / "reference-build",
    )
    reference_root = tmp_path / "complete-remote"
    remote_root.mkdir()
    existing = remote_root / "completion.json"
    existing.write_bytes((reference_root / "completion.json").read_bytes())
    original_inode = existing.stat().st_ino

    receipt = package_and_upload_stage_checkpoint(
        stage_store,
        result,
        remote,
        checkpoint_root=tmp_path / "resumed-build",
    )

    assert receipt.transfer_action == "resumed_partial"
    assert receipt.transfer_verification.object_count == 4
    assert existing.stat().st_ino == original_inode
    assert remote.check_tree(tmp_path / "resumed-build" / "payload").object_count == 4


def test_nonempty_wrong_store_fails_closed_and_preserves_all_local_state(
    tmp_path: Path,
) -> None:
    stage_store = StageStore(tmp_path / "stages")
    result = _completed_upload_stage(stage_store)
    remote_root = tmp_path / "wrong-remote"
    remote_root.mkdir()
    (remote_root / "unrelated.txt").write_text("wrong prefix contents\n", encoding="utf-8")
    remote = _local_destination(
        remote_root,
        prefix="final-discovery-v1/checkpoints/02-semantic",
    )
    checkpoint_root = tmp_path / "failed-build"

    with pytest.raises(ObjectStoreConflictError, match="unexpected objects"):
        package_and_upload_stage_checkpoint(
            stage_store,
            result,
            remote,
            checkpoint_root=checkpoint_root,
        )

    assert (checkpoint_root / "payload" / "completion.json").is_file()
    assert (checkpoint_root / "payload" / "artifacts/nested/report.json").is_file()
    assert stage_store.authenticate_completion(result.manifest.stage_id) == result.manifest
    assert (remote_root / "unrelated.txt").read_text("utf-8") == "wrong prefix contents\n"


def test_stage_or_target_identity_mismatch_fails_before_upload(
    tmp_path: Path,
) -> None:
    stage_store = StageStore(tmp_path / "stages")
    result = _completed_upload_stage(stage_store)
    remote = _local_destination(
        tmp_path / "remote",
        prefix="final-discovery-v1/checkpoints/02-semantic",
    )
    wrong_identity = ObjectStoreIdentity(
        provider="b2",
        bucket="project-echoes-archive",
        prefix="final-discovery-v1/checkpoints/wrong-stage",
    )
    identity_workspace = tmp_path / "identity-failure"
    with pytest.raises(StageCheckpointError, match="identity differs"):
        package_and_upload_stage_checkpoint(
            stage_store,
            result,
            remote,
            checkpoint_root=identity_workspace,
            expected_store_identity=wrong_identity,
        )
    assert not identity_workspace.exists()
    assert not remote.inventory().objects

    wrong_result = replace(result, completion_manifest_sha256="f" * 64)
    result_workspace = tmp_path / "result-failure"
    with pytest.raises(StageCheckpointError, match="completion hash differs"):
        package_and_upload_stage_checkpoint(
            stage_store,
            wrong_result,
            remote,
            checkpoint_root=result_workspace,
        )
    assert not result_workspace.exists()

    artifact = (
        stage_store.completion_path(result.manifest.stage_id).parent
        / result.manifest.artifacts_root
        / result.manifest.artifacts[0].path
    )
    artifact.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(StageAuthenticationError, match="inventory or SHA-256 differs"):
        package_and_upload_stage_checkpoint(
            stage_store,
            result,
            remote,
            checkpoint_root=tmp_path / "tamper-failure",
        )


def test_store_mapping_exactly_covers_configured_upload_stages(tmp_path: Path) -> None:
    config = load_final_discovery_config()
    required = tuple(stage.stage_id for stage in config.stages if stage.upload_after_completion)
    stores = {
        stage_id: _local_destination(
            tmp_path / stage_id,
            prefix=f"final-discovery-v1/checkpoints/{number:02d}-{stage_id}",
        )
        for number, stage_id in enumerate(required, start=2)
    }

    assert validate_checkpoint_store_mapping(config.stages, stores) == required
    with pytest.raises(StageCheckpointError, match="missing="):
        validate_checkpoint_store_mapping(
            config.stages,
            {key: value for key, value in stores.items() if key != required[-1]},
        )
    with pytest.raises(StageCheckpointError, match="unexpected="):
        validate_checkpoint_store_mapping(
            config.stages,
            {**stores, "authenticate_materialize_inputs": stores[required[0]]},
        )

    duplicate_identity = stores[required[0]].identity
    duplicate_stores = dict(stores)
    duplicate_stores[required[1]] = LocalObjectStore(
        tmp_path / "duplicate-physical-root",
        identity=duplicate_identity,
    )
    with pytest.raises(StageCheckpointError, match="share one immutable store prefix"):
        validate_checkpoint_store_mapping(config.stages, duplicate_stores)


def test_checkpoint_workspace_never_overwrites_or_enters_stage_store(tmp_path: Path) -> None:
    stage_store = StageStore(tmp_path / "stages")
    result = _completed_upload_stage(stage_store)
    remote = _local_destination(
        tmp_path / "remote",
        prefix="final-discovery-v1/checkpoints/02-semantic",
    )
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "preserve.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")

    with pytest.raises(ObjectStoreConflictError, match="not empty"):
        package_and_upload_stage_checkpoint(
            stage_store,
            result,
            remote,
            checkpoint_root=occupied,
        )
    assert sentinel.read_text("utf-8") == "preserve\n"
    with pytest.raises(ObjectStoreConflictError, match="inside the authenticated stage store"):
        package_and_upload_stage_checkpoint(
            stage_store,
            result,
            remote,
            checkpoint_root=stage_store.root / "forbidden-checkpoint",
        )
