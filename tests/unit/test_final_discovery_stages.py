"""Durable final-discovery checkpoint tests on bounded local artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import echoes.final_discovery.stages as stage_module
from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.stages import (
    FINAL_DISCOVERY_STAGE_IDS,
    FINAL_DISCOVERY_STAGE_SPECS,
    StageAttemptRecord,
    StageAuthenticationError,
    StageConflictError,
    StageDependencyError,
    StageFailureRecord,
    StageStore,
    assert_stage_registrations,
)

CONFIG_SHA = "a" * 64
CODE_SHA = "b" * 64
INPUT_SHA = "c" * 64
CODE_COMMIT = "d" * 40


def _write_artifact(root: Path, value: str = "complete\n") -> None:
    path = root / "nested" / "artifact.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _run_first_stage(store: StageStore, *, value: str = "complete\n") -> None:
    store.run_stage(
        "authenticate_materialize_inputs",
        input_hashes={"m7/materialization-receipt": INPUT_SHA},
        config_sha256=CONFIG_SHA,
        code_sha256=CODE_SHA,
        code_commit=CODE_COMMIT,
        producer=lambda root: _write_artifact(root, value),
    )


def test_stage_names_and_dependencies_exactly_match_frozen_preregistration() -> None:
    assert FINAL_DISCOVERY_STAGE_IDS == (
        "authenticate_materialize_inputs",
        "semantic_representations_indexes",
        "semantic_candidate_evidence",
        "grammatical_syntactic_evidence",
        "structural_narrative_evidence",
        "anomaly_evidence",
        "empirical_null_controls",
        "transparent_final_ensemble",
        "tier_a_tier_b_outputs",
        "strict_validation",
        "package_upload_verify",
    )
    assert [stage.number for stage in FINAL_DISCOVERY_STAGE_SPECS] == list(range(1, 12))
    config = load_final_discovery_config()
    assert_stage_registrations(config.stages)


def test_stage_completion_is_atomic_hash_complete_and_authenticated_before_skip(
    tmp_path: Path,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    producer_calls = 0

    def producer(root: Path) -> None:
        nonlocal producer_calls
        producer_calls += 1
        _write_artifact(root)

    first = store.run_stage(
        "authenticate_materialize_inputs",
        input_hashes={"m7/materialization-receipt": INPUT_SHA},
        config_sha256=CONFIG_SHA,
        code_sha256=CODE_SHA,
        code_commit=CODE_COMMIT,
        producer=producer,
    )
    second = store.run_stage(
        "authenticate_materialize_inputs",
        input_hashes={"m7/materialization-receipt": INPUT_SHA},
        config_sha256=CONFIG_SHA,
        code_sha256=CODE_SHA,
        code_commit=CODE_COMMIT,
        producer=producer,
    )

    assert producer_calls == 1
    assert first.skipped is False
    assert second.skipped is True
    assert second.manifest == first.manifest
    assert second.completion_manifest_sha256 == first.completion_manifest_sha256
    assert first.manifest.input_sha256 == {"m7/materialization-receipt": INPUT_SHA}
    assert first.manifest.config_sha256 == CONFIG_SHA
    assert first.manifest.code_sha256 == CODE_SHA
    assert first.manifest.code_commit == CODE_COMMIT
    assert first.manifest.artifacts[0].path == "nested/artifact.txt"
    completion = store.completion_path("authenticate_materialize_inputs")
    assert completion.is_file()
    assert not list(completion.parent.glob(".completion.json.*.tmp"))

    artifact = completion.parent / first.manifest.artifacts_root / first.manifest.artifacts[0].path
    artifact.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(StageAuthenticationError, match="inventory or SHA-256 differs"):
        store.run_stage(
            "authenticate_materialize_inputs",
            input_hashes={"m7/materialization-receipt": INPUT_SHA},
            config_sha256=CONFIG_SHA,
            code_sha256=CODE_SHA,
            code_commit=CODE_COMMIT,
            producer=producer,
        )
    assert producer_calls == 1


def test_existing_completion_never_silently_changes_input_config_or_code_identity(
    tmp_path: Path,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    _run_first_stage(store)
    completion_path = store.completion_path("authenticate_materialize_inputs")
    original = completion_path.read_bytes()

    mutations = (
        ({"m7/materialization-receipt": "e" * 64}, CONFIG_SHA, CODE_SHA, CODE_COMMIT),
        ({"m7/materialization-receipt": INPUT_SHA}, "e" * 64, CODE_SHA, CODE_COMMIT),
        ({"m7/materialization-receipt": INPUT_SHA}, CONFIG_SHA, "e" * 64, CODE_COMMIT),
        ({"m7/materialization-receipt": INPUT_SHA}, CONFIG_SHA, CODE_SHA, "other-commit"),
    )
    for input_hashes, config_sha, code_sha, commit in mutations:
        with pytest.raises(StageConflictError, match="identity differs"):
            store.run_stage(
                "authenticate_materialize_inputs",
                input_hashes=input_hashes,
                config_sha256=config_sha,
                code_sha256=code_sha,
                code_commit=commit,
                producer=lambda root: _write_artifact(root, "replacement\n"),
            )
        assert completion_path.read_bytes() == original


def test_dependencies_must_exist_and_are_reauthenticated_before_downstream_run(
    tmp_path: Path,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    with pytest.raises(StageDependencyError, match=r"dependency .* not authenticated"):
        store.run_stage(
            "semantic_representations_indexes",
            input_hashes={},
            config_sha256=CONFIG_SHA,
            code_sha256=CODE_SHA,
            code_commit=CODE_COMMIT,
            producer=_write_artifact,
        )

    _run_first_stage(store)
    semantic = store.run_stage(
        "semantic_representations_indexes",
        input_hashes={},
        config_sha256=CONFIG_SHA,
        code_sha256=CODE_SHA,
        code_commit=CODE_COMMIT,
        producer=_write_artifact,
    )
    assert semantic.manifest.dependency_completion_sha256 == {
        "authenticate_materialize_inputs": store.run_stage(
            "authenticate_materialize_inputs",
            input_hashes={"m7/materialization-receipt": INPUT_SHA},
            config_sha256=CONFIG_SHA,
            code_sha256=CODE_SHA,
            code_commit=CODE_COMMIT,
            producer=_write_artifact,
        ).completion_manifest_sha256
    }

    upstream = store.authenticate_completion("authenticate_materialize_inputs")
    upstream_path = (
        store.completion_path("authenticate_materialize_inputs").parent
        / upstream.artifacts_root
        / upstream.artifacts[0].path
    )
    upstream_path.write_text("drifted dependency\n", encoding="utf-8")
    with pytest.raises(StageDependencyError, match="not authenticated"):
        store.authenticate_completion("semantic_representations_indexes")


def test_failed_stage_preserves_partial_staging_and_failure_record_then_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    secret = "failure-record-secret"
    monkeypatch.setenv("B2_APPLICATION_KEY", secret)

    def fail_after_partial_output(root: Path) -> None:
        _write_artifact(root, "partial\n")
        raise RuntimeError(f"synthetic transport failure exposed {secret}")

    with pytest.raises(RuntimeError, match="synthetic transport failure"):
        store.run_stage(
            "authenticate_materialize_inputs",
            input_hashes={"m7/materialization-receipt": INPUT_SHA},
            config_sha256=CONFIG_SHA,
            code_sha256=CODE_SHA,
            code_commit=CODE_COMMIT,
            producer=fail_after_partial_output,
        )

    failures = store.failure_paths("authenticate_materialize_inputs")
    assert len(failures) == 1
    failure = StageFailureRecord.model_validate_json(failures[0].read_bytes())
    assert failure.failure_kind == "exception"
    assert secret not in failure.error_message
    assert "<redacted>" in failure.error_message
    stage_root = store.completion_path("authenticate_materialize_inputs").parent
    preserved = stage_root / failure.preserved_path
    assert (preserved / "artifacts" / "nested" / "artifact.txt").read_text("utf-8") == ("partial\n")
    assert not store.completion_path("authenticate_materialize_inputs").exists()

    _run_first_stage(store, value="retry complete\n")
    assert store.authenticate_completion("authenticate_materialize_inputs")
    assert preserved.is_dir()
    assert failures[0].is_file()


def test_orphaned_in_progress_attempt_gets_interrupted_record_without_deletion(
    tmp_path: Path,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    stage = FINAL_DISCOVERY_STAGE_SPECS[0]
    attempt_id = "f" * 32
    stage_root = store.completion_path(stage.stage_id).parent
    attempt_root = stage_root / "in-progress" / attempt_id
    artifacts = attempt_root / "artifacts"
    artifacts.mkdir(parents=True)
    _write_artifact(artifacts, "interrupted partial\n")
    attempt = StageAttemptRecord(
        attempt_id=attempt_id,
        stage_number=stage.number,
        stage_id=stage.stage_id,
        stage_spec_sha256=stage.sha256,
        started_at=datetime.now(UTC),
        input_sha256={"m7/materialization-receipt": INPUT_SHA},
        dependency_completion_sha256={},
        config_sha256=CONFIG_SHA,
        code_sha256=CODE_SHA,
        code_commit=CODE_COMMIT,
    )
    (attempt_root / "attempt.json").write_text(
        json.dumps(attempt.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )

    records = store.record_interrupted_attempts(stage.stage_id)
    repeated = store.record_interrupted_attempts(stage.stage_id)

    assert len(records) == 1
    assert records[0].failure_kind == "interrupted"
    assert repeated == records
    assert attempt_root.is_dir()
    assert (artifacts / "nested" / "artifact.txt").is_file()
    assert len(store.failure_paths(stage.stage_id)) == 1


def test_orphaned_completed_attempt_is_recorded_before_retry_without_deletion(
    tmp_path: Path,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    stage = FINAL_DISCOVERY_STAGE_SPECS[0]
    attempt_id = "e" * 32
    stage_root = store.completion_path(stage.stage_id).parent
    in_progress = stage_root / "in-progress" / attempt_id
    artifacts = in_progress / "artifacts"
    artifacts.mkdir(parents=True)
    _write_artifact(artifacts, "completed before publication\n")
    attempt = StageAttemptRecord(
        attempt_id=attempt_id,
        stage_number=stage.number,
        stage_id=stage.stage_id,
        stage_spec_sha256=stage.sha256,
        started_at=datetime.now(UTC),
        input_sha256={"m7/materialization-receipt": INPUT_SHA},
        dependency_completion_sha256={},
        config_sha256=CONFIG_SHA,
        code_sha256=CODE_SHA,
        code_commit=CODE_COMMIT,
    )
    (in_progress / "attempt.json").write_text(
        json.dumps(attempt.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    completed_attempt = stage_root / "completed-attempts" / attempt_id
    completed_attempt.parent.mkdir(parents=True)
    in_progress.replace(completed_attempt)

    _run_first_stage(store, value="retry complete\n")

    failures = store.failure_paths(stage.stage_id)
    assert len(failures) == 1
    failure = StageFailureRecord.model_validate_json(failures[0].read_bytes())
    assert failure.failure_kind == "interrupted"
    assert failure.preserved_path == f"completed-attempts/{attempt_id}"
    assert (completed_attempt / "artifacts" / "nested" / "artifact.txt").read_text(
        encoding="utf-8"
    ) == "completed before publication\n"
    published = store.authenticate_completion(stage.stage_id)
    assert published.attempt_id != attempt_id
    assert store.record_interrupted_attempts(stage.stage_id) == (failure,)


def test_published_completed_attempt_is_not_reclassified_as_interrupted(
    tmp_path: Path,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    _run_first_stage(store)

    assert store.record_interrupted_attempts("authenticate_materialize_inputs") == ()
    assert store.failure_paths("authenticate_materialize_inputs") == ()


def test_completion_authentication_rejects_extra_output_and_corrupt_manifest(
    tmp_path: Path,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    _run_first_stage(store)
    manifest = store.authenticate_completion("authenticate_materialize_inputs")
    completion = store.completion_path("authenticate_materialize_inputs")
    artifact_root = completion.parent / manifest.artifacts_root
    (artifact_root / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(StageAuthenticationError, match="inventory or SHA-256 differs"):
        store.authenticate_completion("authenticate_materialize_inputs")

    (artifact_root / "unexpected.txt").unlink()
    completion.write_text("{}\n", encoding="utf-8")
    with pytest.raises(StageAuthenticationError, match="completion manifest"):
        store.authenticate_completion("authenticate_materialize_inputs")


def test_full_graph_authentication_hashes_each_shared_stage_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StageStore(tmp_path / "checkpoints")
    for stage_id in FINAL_DISCOVERY_STAGE_IDS:
        store.run_stage(
            stage_id,
            input_hashes=(
                {"m7/materialization-receipt": INPUT_SHA}
                if stage_id == "authenticate_materialize_inputs"
                else {}
            ),
            config_sha256=CONFIG_SHA,
            code_sha256=CODE_SHA,
            code_commit=CODE_COMMIT,
            producer=lambda root, value=stage_id: _write_artifact(root, f"{value}\n"),
        )

    inventory_calls = 0
    original = stage_module._inventory_stage_artifacts

    def count_inventory(root: Path) -> tuple[stage_module.StageArtifact, ...]:
        nonlocal inventory_calls
        inventory_calls += 1
        return original(root)

    monkeypatch.setattr(stage_module, "_inventory_stage_artifacts", count_inventory)
    manifests = store.authenticate_all_completions()

    assert tuple(manifest.stage_id for manifest in manifests) == FINAL_DISCOVERY_STAGE_IDS
    assert inventory_calls == 11
