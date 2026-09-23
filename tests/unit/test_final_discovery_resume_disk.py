"""Only exact authenticated successor lineage changes the launch disk gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from echoes.final_discovery.stages import StageStore, StageStoreError

ROOT = Path(__file__).resolve().parents[2]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "resume_disk", ROOT / "cloud/final_discovery_resume_disk.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    *,
    six: bool = False,
    eight: bool = False,
) -> tuple[ModuleType, dict[str, Any]]:
    module = _module()
    root, work = tmp_path / "repo", tmp_path / "successor"
    root.mkdir()
    work.mkdir()
    source_tree, target_tree = {"source.py": b"before"}, {"source.py": b"after"}
    source_code = module.recovery._tree_hash(source_tree)
    target_code = module.recovery._tree_hash(target_tree)
    commit = "d" * 40
    one, two = {"prepared": "a" * 64}, {"model": "b" * 64}
    work_name = "REVIEW_WORK" if eight else "CALIBRATION_WORK" if six else "RECOVERY_WORK"
    code_name = (
        "REVIEW_SOURCE_CODE" if eight else "CALIBRATION_SOURCE_CODE" if six else "SOURCE_CODE"
    )
    monkeypatch.setattr(module, work_name, work)
    monkeypatch.setattr(module, code_name, source_code)
    source_commit = (
        module.REVIEW_SOURCE_COMMIT
        if eight
        else module.CALIBRATION_SOURCE_COMMIT
        if six
        else module.SOURCE_COMMIT
    )
    source_work = (
        module.REVIEW_SOURCE_WORK
        if eight
        else module.CALIBRATION_SOURCE_WORK
        if six
        else module.SOURCE_WORK
    )
    source_completions = module.CALIBRATION_SOURCE_COMPLETIONS if six else module.SOURCE_COMPLETIONS
    if eight:
        source_completions = dict.fromkeys(module.FINAL_DISCOVERY_STAGE_IDS[:8], "0" * 64)
    prefix = module.REVIEW_PREFIX if eight else module.CALIBRATION_PREFIX if six else module.PREFIX
    input_sets = (one, two, *({} for _ in range(len(source_completions) - 2)))
    monkeypatch.setattr(module, "authenticate_clean_git_tree", lambda _: (commit, target_code))
    monkeypatch.setattr(module.recovery, "_current_inputs", lambda *_: (one, two, {}))
    monkeypatch.setattr(module, "load_final_discovery_config", lambda _: None)
    monkeypatch.setattr(module, "final_discovery_config_sha256", lambda _: module.CONFIG_HASH)
    monkeypatch.setattr(
        module.recovery,
        "_git_tree",
        lambda _, rev: source_tree if rev == source_commit else target_tree,
    )
    source_store = StageStore(tmp_path / "source-stages")
    originals = {}
    manifests = {}
    for stage_id, inputs in zip(source_completions, input_sets, strict=True):
        artifact_name = (
            "candidates.jsonl"
            if eight
            and stage_id == "transparent_final_ensemble"
            and corruption != "missing_candidate_ledger"
            else "artifact.json"
        )
        result = source_store.run_stage(
            stage_id,
            input_hashes=inputs,
            config_sha256=module.CONFIG_HASH,
            code_sha256=source_code,
            code_commit=source_commit,
            producer=lambda destination, name=artifact_name: (destination / name).write_text(
                "unchanged"
            ),
        )
        originals[stage_id] = source_store.completion_path(stage_id).read_bytes()
        manifests[stage_id] = result.manifest
    pins = {name: hashlib.sha256(content).hexdigest() for name, content in originals.items()}
    if eight:
        monkeypatch.setattr(
            module,
            "REVIEW_KNOWN_SOURCE_COMPLETIONS",
            {key: value for key, value in pins.items() if key != "empirical_null_controls"},
        )
    else:
        monkeypatch.setattr(
            module, "CALIBRATION_SOURCE_COMPLETIONS" if six else "SOURCE_COMPLETIONS", pins
        )
    compatibility = {
        "schema_version": 1,
        "source_code_commit": source_commit,
        "source_code_sha256": source_code,
        "target_code_commit": commit,
        "target_code_sha256": target_code,
        "changed_files": {
            "source.py": {
                "source_sha256": hashlib.sha256(b"before").hexdigest(),
                "target_sha256": hashlib.sha256(b"after").hexdigest(),
            }
        },
    }
    if corruption == "compatibility":
        compatibility["target_code_commit"] = "e" * 40
    compatibility_bytes = json.dumps(compatibility).encode()
    store = StageStore(work / "stages")
    for number, (stage_id, inputs) in enumerate(zip(pins, input_sets, strict=True), 1):
        if corruption == "missing_final" and number == len(pins):
            continue
        original = manifests[stage_id]
        provenance = {
            "schema_version": 1,
            "operation": (
                "authenticated_unchanged_eight_stage_import"
                if eight
                else "authenticated_unchanged_six_stage_import"
                if six
                else "authenticated_unchanged_five_stage_import"
            ),
            "source_work_directory": source_work,
            "source_code_commit": source_commit,
            "source_code_sha256": source_code,
            "source_stage_id": stage_id,
            "source_completion_sha256": pins,
            "source_output_inventory_sha256": original.output_inventory_sha256,
            "revalidation_code_commit": commit,
            "revalidation_code_sha256": target_code,
            "compatibility_manifest_sha256": hashlib.sha256(compatibility_bytes).hexdigest(),
            "config_sha256": module.CONFIG_HASH,
            "copy_mode": "same_filesystem_hardlink" if six or eight else "independent_file_copy",
            "original_receipts_preserved": True,
        }
        if six or eight:
            provenance.update(
                source_metadata_preserved=[
                    "device",
                    "inode",
                    "size",
                    "mode",
                    "mtime_ns",
                    "uid",
                    "gid",
                ],
                hardlink_metadata_side_effects=["link_count", "ctime"],
            )
        if eight:
            provenance["source_pin_derivation"] = {
                "empirical_null_controls": {
                    "from_stage": "transparent_final_ensemble",
                    "pinned_completion_sha256": pins["transparent_final_ensemble"],
                    "field": "dependency_completion_sha256.empirical_null_controls",
                }
            }
        if corruption in {
            "operation",
            "source_code_commit",
            "copy_mode",
            "source_metadata_preserved",
            "hardlink_metadata_side_effects",
            "source_pin_derivation",
        }:
            provenance[corruption] = "tampered"

        def produce(
            destination: Path,
            provenance: dict[str, Any] = provenance,
            artifact_name: str = original.artifacts[0].path,
        ) -> None:
            (destination / artifact_name).write_text(
                "changed" if corruption == "artifact" else "unchanged"
            )
            proof = destination / prefix
            proof.mkdir(parents=True)
            for name, content in originals.items():
                (proof / f"{name}.source-completion.json").write_bytes(
                    content + b" "
                    if corruption == "source_completion"
                    or (corruption == "derived_stage7" and name == "empirical_null_controls")
                    else content
                )
            (proof / "compatibility-manifest.json").write_bytes(compatibility_bytes)
            (proof / "reuse-provenance.json").write_text(json.dumps(provenance))

        store.run_stage(
            stage_id,
            input_hashes=inputs,
            config_sha256=module.CONFIG_HASH,
            code_sha256=target_code,
            code_commit="e" * 40
            if corruption == "current_code" and number == len(pins)
            else commit,
            producer=produce,
        )
    return module, {
        "project_root": root,
        "work_directory": work,
        "expected_commit": commit,
        "prepared_passages": tmp_path / "prepared",
        "knownness": tmp_path / "knownness",
        "offline_model_root": tmp_path / "model",
    }


def test_successor_retains_full_modeled_additional_allocation_and_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, arguments = _fixture(tmp_path, monkeypatch, "none")
    result = module.launch_capacity(**arguments)
    assert result["required_launch_free_bytes"] == 225_737_600_612
    assert result["modeled_additional_bytes"] == 139_838_254_692
    assert result["checkpoint_disk_floor_bytes"] == 80 * 1024**3
    assert result["completed_artifact_credit_bytes"] == 0
    assert len(result["authenticated_completion_sha256"]) == 5
    assert result["projection_is_not_a_peak_guarantee"] is True


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_final",
        "artifact",
        "source_completion",
        "compatibility",
        "operation",
        "source_code_commit",
        "copy_mode",
        "current_code",
    ],
)
def test_successor_missing_or_altered_proof_fails_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    module, arguments = _fixture(tmp_path, monkeypatch, corruption)
    with pytest.raises((module.recovery.RecoveryError, StageStoreError)):
        module.launch_capacity(**arguments)


def test_other_work_directories_keep_original_280_gib_requirement(tmp_path: Path) -> None:
    module = _module()
    result = module.launch_capacity(
        tmp_path, tmp_path / "arbitrary-resume", "d" * 40, tmp_path, tmp_path, tmp_path
    )
    assert result == {"basis": "fresh_run_280_gib", "required_launch_free_bytes": 280 * 1024**3}


def test_six_stage_successor_credits_only_authenticated_completed_model_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, arguments = _fixture(tmp_path, monkeypatch, "none", six=True)
    result = module.launch_capacity(**arguments)
    benchmark = json.loads(
        (ROOT / "outputs/reports/final-discovery-preproduction-benchmark.json").read_bytes()
    )["production_extrapolation"]
    modeled = benchmark["persistent_disk_bytes"]
    assert modeled["canonical_raw_evidence_bytes"] == module.MODELED_COMPLETED_RAW_BYTES
    assert (
        benchmark["resource_gate"]["disk"]["canonical_m7_bytes_estimate"]
        == module.MODELED_COMPLETED_M7_BYTES
    )
    assert result["modeled_additional_bytes"] == (
        modeled["total_bytes"] - modeled["canonical_raw_evidence_bytes"]
    )
    assert result["required_launch_free_bytes"] == 162_204_221_220
    assert result["checkpoint_disk_floor_bytes"] == 80 * 1024**3
    assert result["completed_artifact_credit_bytes"] == 63_533_379_392
    assert result["import_copy_mode"] == "same_filesystem_hardlink"
    assert len(result["authenticated_completion_sha256"]) == 6
    assert result["projection_is_not_a_peak_guarantee"] is True
    assert result["unmodeled_peak_components"] == [
        "duckdb_database_and_spill",
        "full_review_outputs",
    ]


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_final",
        "artifact",
        "source_completion",
        "compatibility",
        "operation",
        "source_code_commit",
        "copy_mode",
        "source_metadata_preserved",
        "hardlink_metadata_side_effects",
        "current_code",
    ],
)
def test_six_stage_successor_rejects_missing_sixth_stage_and_altered_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    module, arguments = _fixture(tmp_path, monkeypatch, corruption, six=True)
    with pytest.raises((module.recovery.RecoveryError, StageStoreError)):
        module.launch_capacity(**arguments)


def test_eight_stage_successor_binds_exact_candidate_bytes_and_requires_measured_review_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, arguments = _fixture(tmp_path, monkeypatch, "none", eight=True)
    result = module.launch_capacity(**arguments)
    benchmark = json.loads(
        (ROOT / "outputs/reports/final-discovery-preproduction-benchmark.json").read_bytes()
    )["production_extrapolation"]["persistent_disk_bytes"]
    assert result["evidence_index_allowance_bytes"] == benchmark["evidence_offset_index_bytes"]
    assert result["remaining_tier_ledger_upper_bound_bytes"] == len(b"unchanged")
    assert result["required_launch_free_bytes"] == (
        80 * 1024**3 + len(b"unchanged") + 358_384_436 + 1024**3
    )
    assert result["checkpoint_disk_floor_bytes"] == 80 * 1024**3
    assert result["review_materialization_gate_required"] is True
    assert result["projection_is_not_a_peak_guarantee"] is True
    assert result["checkpoint_and_package_payloads_use_hardlinks"] is True
    assert len(result["authenticated_completion_sha256"]) == 8
    assert "empirical_null_controls" not in module.REVIEW_KNOWN_SOURCE_COMPLETIONS


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_final",
        "artifact",
        "source_completion",
        "derived_stage7",
        "compatibility",
        "operation",
        "source_code_commit",
        "copy_mode",
        "source_metadata_preserved",
        "hardlink_metadata_side_effects",
        "source_pin_derivation",
        "current_code",
        "missing_candidate_ledger",
    ],
)
def test_eight_stage_successor_rejects_unbound_or_altered_source_and_target_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    module, arguments = _fixture(tmp_path, monkeypatch, corruption, eight=True)
    with pytest.raises((module.recovery.RecoveryError, StageStoreError)):
        module.launch_capacity(**arguments)


def test_launcher_records_effective_requirement_and_fails_closed() -> None:
    script = (ROOT / "cloud/launch_final_discovery.sh").read_text()
    assert '"fresh_run_initial_free_disk_gib": 280' in script
    assert (
        '"required_launch_free_bytes": '
        'json.loads(launch_capacity_json)["required_launch_free_bytes"]' in script
    )
    assert '"launch_capacity": json.loads(launch_capacity_json)' in script
    assert "recovery launch capacity lacks authenticated imported-stage proof" in script
    assert script.index("repository must be completely clean") < script.index(
        "python cloud/final_discovery_resume_disk.py"
    )
    assert (
        '"$ECHOES_WORK_DIR" == /srv/project-echoes/final-discovery/work-20260922-m7-null-recovery'
        in script
    )
    assert (
        '"$ECHOES_WORK_DIR" == /srv/project-echoes/final-discovery/work-20260923-calibration-memory'
        in script
    )
    assert '[[ "$required_launch_free_bytes" == 162204221220 ]]' in script
    assert '[[ "$required_launch_free_bytes" == 225737600612 ]]' in script
    assert (
        '"$ECHOES_WORK_DIR" == /srv/project-echoes/final-discovery/work-20260923-review-disk'
        in script
    )
    assert "assert proof['review_materialization_gate_required'] is True" in script
    assert "proof['remaining_tier_ledger_upper_bound_bytes'] + 358384436 + 1024**3" in script
