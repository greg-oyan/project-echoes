"""Run-manifest unit tests."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import echoes.manifest as manifest_module
from echoes.manifest import (
    ExperimentExecutionRecorder,
    ResumeLineage,
    RunManifest,
    build_run_manifest,
    discover_execution_manifests,
    finalize_recovered_execution_success,
    load_execution_manifest,
    reproduction_command_path_mismatches,
    reproduction_environment_mismatches,
    resolve_execution_manifest,
    validate_execution_manifest_outputs,
    write_execution_manifest,
    write_run_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _successful_execution(
    project_root: Path,
    *,
    run_id: str = "lexical-v1-test",
    recovered: bool = False,
) -> tuple[ExperimentExecutionRecorder, Path]:
    (project_root / "src" / "echoes").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "echoes" / "fixture.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (project_root / "config").mkdir(exist_ok=True)
    (project_root / "config" / "lexical.yaml").write_text(
        "schema_version: 1\n",
        encoding="utf-8",
    )
    (project_root / "uv.lock").write_text("fixture-lock\n", encoding="utf-8")
    (project_root / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    (project_root / "data" / "manifests" / "sources.yaml").write_text(
        (
            "schema_version: 1\n"
            "sources:\n"
            "  - source_id: fixture\n"
            "    file_hashes:\n"
            f"      fixture.txt: {'9' * 64}\n"
        ),
        encoding="utf-8",
    )
    output_dir = project_root / "data" / "processed" / "lexical" / "schema-v1"
    output_dir.mkdir(parents=True, exist_ok=True)
    resume_staging_dir = None
    if recovered:
        resume_staging_dir = output_dir.parent / ".schema-v1.writing-fixture"
        resume_staging_dir.mkdir()
    recorder = ExperimentExecutionRecorder.begin(
        experiment_name="m7-lexical-baseline",
        experiment_version="m7-lexical-baseline-v1",
        project_root=project_root,
        output_dir=output_dir,
        configuration_files={"lexical_yaml": Path("config/lexical.yaml")},
        dataset_manifest_path=Path("data/manifests/sources.yaml"),
        runtime_versions={"fixture": "1.0"},
        reproduction_command=[
            "uv",
            "run",
            "echoes",
            "run-lexical-pipeline",
            "--primary",
            "--database",
            "data/processed/project_echoes.duckdb",
            "--output-dir",
            "data/processed/lexical/schema-v1",
        ],
        resume_staging_dir=resume_staging_dir,
    )
    recorder.bind_configuration(
        canonical_hashes={
            "lexical_canonical": "a" * 64,
            "lexical_preregistration_canonical": "b" * 64,
        },
        random_seed=7201,
        random_seeds={
            "bootstrap": 7201,
            "frequency_preserving_synthetic": 7102,
            "within_book_reassignment": 7101,
        },
        dataset_versions={"source:fixture": "fixture-v1"},
    )
    recorder.bind_run(
        run_id=run_id,
        input_table_hashes={"fixture:input": "c" * 64},
        dataset_versions={"passages:run_id": "passages-v1-fixture"},
        evaluation_split_lineage={"benchmark:split": "d" * 64},
    )
    if recovered:
        recorder.bind_resume_lineage(
            artifact_part_hashes={"directional_rankings/part-00000.parquet": "0" * 64},
            checkpoint_manifest_hashes={},
            checkpoint_part_hashes={},
        )
        recorder.bind_resume_lineage(
            artifact_part_hashes={},
            checkpoint_manifest_hashes={".resume-primary-candidates/complete.json": "1" * 64},
            checkpoint_part_hashes={".resume-primary-candidates/part-00000.parquet": "2" * 64},
        )
    artifact = output_dir / "lexical_metadata" / "part-00000.parquet"
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_bytes(b"synthetic fixture artifact")
    hash_payload = {
        "schema_version": 1,
        "table_counts": {"lexical_metadata": 1},
        "table_logical_sha256": {"lexical_metadata": "e" * 64},
        "table_physical_sha256": {"lexical_metadata": "f" * 64},
        "artifacts": {"lexical_metadata": {}},
        "file_sha256": {
            "lexical_metadata/part-00000.parquet": hashlib.sha256(artifact.read_bytes()).hexdigest()
        },
    }
    hash_manifest_path = output_dir / "table-hashes.json"
    hash_manifest_path.write_text(
        json.dumps(hash_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    recorder.bind_outputs(
        output_table_hashes={"lexical_metadata": "e" * 64},
        output_table_physical_hashes={"lexical_metadata": "f" * 64},
        output_hash_manifest_path=hash_manifest_path,
    )
    recorder.finalize_success(stage_runtime_seconds={"total": 1.0})
    return recorder, output_dir


def test_build_run_manifest_has_required_provenance() -> None:
    manifest = build_run_manifest(
        "foundation smoke",
        project_root=PROJECT_ROOT,
        config_dir=PROJECT_ROOT / "config",
    )

    assert manifest.run_id.startswith("foundation-smoke-")
    assert len(manifest.config_hash) == 64
    assert manifest.random_seed == 1729
    assert manifest.dataset_manifest_hash is not None
    assert len(manifest.dataset_manifest_hash) == 64
    assert manifest.model_names == []
    assert RunManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_manifest_writer_refuses_silent_overwrite(tmp_path: Path) -> None:
    manifest = build_run_manifest(
        "foundation smoke",
        project_root=PROJECT_ROOT,
        config_dir=PROJECT_ROOT / "config",
    )
    output = tmp_path / "manifest.json"
    write_run_manifest(manifest, output, overwrite=False)

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_run_manifest(manifest, output, overwrite=False)


def test_failed_execution_is_preserved_before_run_identity_is_known(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "config").mkdir()
    (project_root / "config" / "lexical.yaml").write_text(
        "schema_version: 1\n",
        encoding="utf-8",
    )
    (project_root / "uv.lock").write_text("fixture-lock\n", encoding="utf-8")
    (project_root / "data" / "manifests").mkdir(parents=True)
    (project_root / "data" / "manifests" / "sources.yaml").write_text(
        (
            "schema_version: 1\n"
            "sources:\n"
            "  - source_id: fixture\n"
            "    file_hashes:\n"
            f"      fixture.txt: {'9' * 64}\n"
        ),
        encoding="utf-8",
    )
    output_dir = project_root / "data" / "processed" / "lexical" / "schema-v1"
    recorder = ExperimentExecutionRecorder.begin(
        experiment_name="m7-lexical-baseline",
        experiment_version="m7-lexical-baseline-v1",
        project_root=project_root,
        output_dir=output_dir,
        configuration_files={"lexical_yaml": Path("config/lexical.yaml")},
        dataset_manifest_path=Path("data/manifests/sources.yaml"),
        runtime_versions={"fixture": "1.0"},
        reproduction_command=[
            "uv",
            "run",
            "echoes",
            "run-lexical-pipeline",
            "--primary",
            "--database",
            "data/processed/project_echoes.duckdb",
            "--output-dir",
            "data/processed/lexical/schema-v1",
        ],
    )

    recorder.finalize_failure(RuntimeError("synthetic early failure"))

    preserved = load_execution_manifest(recorder.manifest_path)
    assert preserved.run_id == "unresolved"
    assert preserved.execution_status == "failed"
    assert preserved.errors == ["RuntimeError: synthetic early failure"]


def test_successful_attempts_remain_distinct_and_exactly_selectable(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    first, _ = _successful_execution(project_root)
    second, _ = _successful_execution(project_root)

    discovered = discover_execution_manifests(
        first.manifest_root,
        run_id=first.manifest.run_id,
    )
    assert len(discovered) == 2
    assert first.manifest.execution_id != second.manifest.execution_id
    selected_path, selected = resolve_execution_manifest(
        first.manifest_root,
        run_id=first.manifest.run_id,
    )
    assert selected.execution_id == second.manifest.execution_id
    assert selected_path == second.manifest_path
    exact_path, exact = resolve_execution_manifest(
        first.manifest_root,
        run_id=first.manifest.run_id,
        execution_id=first.manifest.execution_id,
    )
    assert exact.execution_id == first.manifest.execution_id
    assert exact_path == first.manifest_path


def test_successful_execution_manifest_matches_static_environment_and_outputs(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, _ = _successful_execution(project_root)

    assert (
        reproduction_environment_mismatches(
            recorder.manifest,
            project_root=project_root,
        )
        == []
    )
    assert recorder.manifest.source_file_hashes == {"fixture:fixture.txt": "9" * 64}
    assert (
        reproduction_command_path_mismatches(
            recorder.manifest,
            project_root=project_root,
        )
        == []
    )


def test_recovered_success_refuses_failed_or_unsuccessful_service(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, _ = _successful_execution(project_root)
    with pytest.raises(ValueError, match="successful service result"):
        finalize_recovered_execution_success(
            recorder.manifest_path,
            validation_report_sha256="0" * 64,
            service_result="oom-kill",
        )

    failed = recorder.manifest.model_copy(
        update={
            "execution_status": "failed",
            "errors": ["RuntimeError: synthetic post-commit failure"],
        }
    )
    write_execution_manifest(failed, recorder.manifest_path, overwrite=True)

    with pytest.raises(ValueError, match="cannot be reclassified"):
        finalize_recovered_execution_success(
            recorder.manifest_path,
            validation_report_sha256="1" * 64,
            service_result="success",
        )

    running = recorder.manifest.model_copy(
        update={
            "execution_status": "running",
            "completed_at": None,
            "errors": [],
        }
    )
    write_execution_manifest(running, recorder.manifest_path, overwrite=True)
    with pytest.raises(ValueError, match="successful service result"):
        finalize_recovered_execution_success(
            recorder.manifest_path,
            validation_report_sha256="2" * 64,
            service_result="timeout",
        )
    assert load_execution_manifest(recorder.manifest_path).execution_status == "running"


def test_recovered_success_transitions_running_manifest_idempotently(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, _ = _successful_execution(project_root)
    running = recorder.manifest.model_copy(
        update={
            "execution_status": "running",
            "completed_at": None,
            "errors": [],
        }
    )
    write_execution_manifest(running, recorder.manifest_path, overwrite=True)

    recovered = finalize_recovered_execution_success(
        recorder.manifest_path,
        validation_report_sha256="3" * 64,
        service_result="success",
    )
    repeated = finalize_recovered_execution_success(
        recorder.manifest_path,
        validation_report_sha256="3" * 64,
        service_result="success",
    )

    assert recovered.execution_status == "succeeded"
    assert repeated == recovered
    assert any("durable post-COMMIT" in warning for warning in recovered.warnings)


def test_archived_direct_sibling_authenticates_the_exact_first_execution(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, output_dir = _successful_execution(project_root)
    archived_root = output_dir.parent / "m7-first-run-reference"
    shutil.copytree(output_dir, archived_root)
    (output_dir / "table-hashes.json").write_text("{}\n", encoding="utf-8")

    assert (
        validate_execution_manifest_outputs(
            recorder.manifest,
            project_root=project_root,
            artifact_root=archived_root,
        )
        == []
    )
    canonical_failures = validate_execution_manifest_outputs(
        recorder.manifest,
        project_root=project_root,
    )
    assert "differs from output_hash_manifest_sha256" in canonical_failures[0]

    unrelated_root = project_root / "data" / "processed" / "other" / "archive"
    shutil.copytree(archived_root, unrelated_root)
    unrelated_failures = validate_execution_manifest_outputs(
        recorder.manifest,
        project_root=project_root,
        artifact_root=unrelated_root,
    )
    assert any("not a direct sibling" in failure for failure in unrelated_failures)


def test_recovered_execution_merges_lineage_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, _ = _successful_execution(project_root, recovered=True)
    lineage = recorder.manifest.resume_lineage
    assert lineage.status == "validated_and_reused"
    assert lineage.recovered_composite is True
    assert lineage.validated_artifact_part_hashes == {
        "directional_rankings/part-00000.parquet": "0" * 64
    }
    assert lineage.validated_checkpoint_manifest_hashes == {
        ".resume-primary-candidates/complete.json": "1" * 64
    }
    assert lineage.validated_checkpoint_part_hashes == {
        ".resume-primary-candidates/part-00000.parquet": "2" * 64
    }
    recovery_warning = "this execution recovered validated artifacts from interrupted staging"
    assert sum(recovery_warning in warning for warning in recorder.manifest.warnings) == 1

    payload = recorder.manifest.model_dump(mode="python")
    payload["execution_status"] = "running"
    payload["completed_at"] = None
    running = type(recorder.manifest).model_validate(payload)
    recorder.manifest = running
    with pytest.raises(ValueError, match="hash conflict"):
        recorder.bind_resume_lineage(
            artifact_part_hashes={"directional_rankings/part-00000.parquet": "f" * 64},
            checkpoint_manifest_hashes={},
            checkpoint_part_hashes={},
        )


def test_resume_lineage_rejects_ungoverned_or_unvalidated_hashes() -> None:
    with pytest.raises(ValidationError, match="normalized relative POSIX path"):
        ResumeLineage(
            requested_staging_directory="data/processed/lexical/staging",
            status="validated_and_reused",
            recovered_composite=True,
            validated_artifact_part_hashes={"../escaped.parquet": "0" * 64},
            validated_checkpoint_manifest_hashes={},
            validated_checkpoint_part_hashes={},
        )
    with pytest.raises(ValidationError, match="cannot record validated hashes"):
        ResumeLineage(
            requested_staging_directory="data/processed/lexical/staging",
            status="requested",
            recovered_composite=False,
            validated_artifact_part_hashes={"artifact/part-00000.parquet": "0" * 64},
            validated_checkpoint_manifest_hashes={},
            validated_checkpoint_part_hashes={},
        )


def test_successful_manifest_rejects_self_inconsistent_hash_maps(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, _ = _successful_execution(project_root)
    payload = recorder.manifest.model_dump(mode="python")
    payload["config_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="config_hash disagrees"):
        type(recorder.manifest).model_validate(payload)

    payload = recorder.manifest.model_dump(mode="python")
    payload["output_table_physical_hashes"] = {"different_table": "f" * 64}
    with pytest.raises(ValidationError, match="name different tables"):
        type(recorder.manifest).model_validate(payload)


def test_git_drift_is_only_a_notice_while_governed_content_matches(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, _ = _successful_execution(project_root)
    payload = recorder.manifest.model_dump(mode="python")
    payload["git_commit"] = "different-docs-only-head"
    manifest = type(recorder.manifest).model_validate(payload)
    notices: list[str] = []

    assert (
        reproduction_environment_mismatches(
            manifest,
            project_root=project_root,
            notices=notices,
        )
        == []
    )
    assert len(notices) == 1
    assert "governed executable inputs" in notices[0]

    (project_root / "src" / "echoes" / "fixture.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    notices.clear()
    mismatches = reproduction_environment_mismatches(
        manifest,
        project_root=project_root,
        notices=notices,
    )
    assert any("git_commit differs" in mismatch for mismatch in mismatches)
    assert any("source_tree_hash" in mismatch for mismatch in mismatches)
    assert notices == []


def test_reproduction_command_paths_must_remain_in_governed_project_data(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, _ = _successful_execution(project_root)
    payload = recorder.manifest.model_dump(mode="python")
    command = list(payload["reproduction_command"])
    database_index = command.index("--database") + 1
    command[database_index] = "../outside.duckdb"
    payload["reproduction_command"] = command
    manifest = type(recorder.manifest).model_validate(payload)

    failures = reproduction_command_path_mismatches(
        manifest,
        project_root=project_root,
    )
    assert any("--database escapes the project root" in failure for failure in failures)
    assert (
        validate_execution_manifest_outputs(
            recorder.manifest,
            project_root=project_root,
        )
        == []
    )


@pytest.mark.parametrize(
    "mutation, expected",
    [
        ("missing_hash_manifest", "table-hashes.json is missing"),
        ("tampered_hash_manifest", "differs from output_hash_manifest_sha256"),
        ("mismatched_output_map", "disagrees with table_logical_sha256"),
        ("tampered_output_file", "declared lexical output file hash differs"),
        ("unexpected_output_file", "undeclared lexical output file exists"),
    ],
)
def test_execution_output_validation_fails_closed(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, output_dir = _successful_execution(project_root)
    manifest = recorder.manifest
    hash_manifest_path = output_dir / "table-hashes.json"

    if mutation == "missing_hash_manifest":
        hash_manifest_path.unlink()
    elif mutation == "tampered_hash_manifest":
        hash_manifest_path.write_text(
            hash_manifest_path.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )
    elif mutation == "mismatched_output_map":
        payload = manifest.model_dump(mode="python")
        payload["output_table_hashes"] = {"lexical_metadata": "0" * 64}
        manifest = type(manifest).model_validate(payload)
    elif mutation == "unexpected_output_file":
        (output_dir / "unexpected.txt").write_text("not governed\n", encoding="utf-8")
    else:
        (output_dir / "lexical_metadata" / "part-00000.parquet").write_bytes(
            b"tampered synthetic fixture artifact"
        )

    failures = validate_execution_manifest_outputs(
        manifest,
        project_root=project_root,
    )
    assert any(expected in failure for failure in failures)


def test_execution_output_validation_rejects_reparse_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    recorder, _ = _successful_execution(project_root)
    original = manifest_module._is_reparse_point

    def mark_artifact_as_reparse(path: Path) -> bool:
        return path.name == "part-00000.parquet" or original(path)

    monkeypatch.setattr(
        manifest_module,
        "_is_reparse_point",
        mark_artifact_as_reparse,
    )
    failures = validate_execution_manifest_outputs(
        recorder.manifest,
        project_root=project_root,
    )
    assert any("symlink or reparse point" in failure for failure in failures)
