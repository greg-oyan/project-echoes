"""Only authenticated five-stage successor lineage changes the launch disk gate."""

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
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
    monkeypatch.setattr(module, "RECOVERY_WORK", work)
    monkeypatch.setattr(module, "SOURCE_CODE", source_code)
    monkeypatch.setattr(module, "authenticate_clean_git_tree", lambda _: (commit, target_code))
    monkeypatch.setattr(module.recovery, "_current_inputs", lambda *_: (one, two, {}))
    monkeypatch.setattr(module, "load_final_discovery_config", lambda _: None)
    monkeypatch.setattr(module, "final_discovery_config_sha256", lambda _: module.CONFIG_HASH)
    monkeypatch.setattr(
        module.recovery,
        "_git_tree",
        lambda _, rev: source_tree if rev == module.SOURCE_COMMIT else target_tree,
    )
    source_store = StageStore(tmp_path / "source-stages")
    originals = {}
    manifests = {}
    for stage_id, inputs in zip(module.SOURCE_COMPLETIONS, (one, two, {}, {}, {}), strict=True):
        result = source_store.run_stage(
            stage_id,
            input_hashes=inputs,
            config_sha256=module.CONFIG_HASH,
            code_sha256=source_code,
            code_commit=module.SOURCE_COMMIT,
            producer=lambda destination: (destination / "artifact.json").write_text("unchanged"),
        )
        originals[stage_id] = source_store.completion_path(stage_id).read_bytes()
        manifests[stage_id] = result.manifest
    pins = {name: hashlib.sha256(content).hexdigest() for name, content in originals.items()}
    monkeypatch.setattr(module, "SOURCE_COMPLETIONS", pins)
    compatibility = {
        "schema_version": 1,
        "source_code_commit": module.SOURCE_COMMIT,
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
    for number, (stage_id, inputs) in enumerate(zip(pins, (one, two, {}, {}, {}), strict=True), 1):
        if corruption == "missing_fifth" and number == 5:
            continue
        original = manifests[stage_id]
        provenance = {
            "schema_version": 1,
            "operation": "authenticated_unchanged_five_stage_import",
            "source_work_directory": module.SOURCE_WORK,
            "source_code_commit": module.SOURCE_COMMIT,
            "source_code_sha256": source_code,
            "source_stage_id": stage_id,
            "source_completion_sha256": pins,
            "source_output_inventory_sha256": original.output_inventory_sha256,
            "revalidation_code_commit": commit,
            "revalidation_code_sha256": target_code,
            "compatibility_manifest_sha256": hashlib.sha256(compatibility_bytes).hexdigest(),
            "config_sha256": module.CONFIG_HASH,
            "copy_mode": "independent_file_copy",
            "original_receipts_preserved": True,
        }
        if corruption in {"operation", "source_code_commit", "copy_mode"}:
            provenance[corruption] = "tampered"

        def produce(destination: Path, provenance: dict[str, Any] = provenance) -> None:
            (destination / "artifact.json").write_text(
                "changed" if corruption == "artifact" else "unchanged"
            )
            proof = destination / module.PREFIX
            proof.mkdir(parents=True)
            for name, content in originals.items():
                (proof / f"{name}.source-completion.json").write_bytes(
                    content + b" " if corruption == "source_completion" else content
                )
            (proof / "compatibility-manifest.json").write_bytes(compatibility_bytes)
            (proof / "reuse-provenance.json").write_text(json.dumps(provenance))

        store.run_stage(
            stage_id,
            input_hashes=inputs,
            config_sha256=module.CONFIG_HASH,
            code_sha256=target_code,
            code_commit="e" * 40 if corruption == "current_code" and number == 5 else commit,
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
        "missing_fifth",
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


def test_launcher_records_effective_requirement_and_fails_closed() -> None:
    script = (ROOT / "cloud/launch_final_discovery.sh").read_text()
    assert '"fresh_run_initial_free_disk_gib": 280' in script
    assert (
        '"required_launch_free_bytes": '
        'json.loads(launch_capacity_json)["required_launch_free_bytes"]' in script
    )
    assert '"launch_capacity": json.loads(launch_capacity_json)' in script
    assert "recovery launch capacity lacks authenticated five-stage import proof" in script
    assert script.index("repository must be completely clean") < script.index(
        "python cloud/final_discovery_resume_disk.py"
    )
    assert (
        '"$ECHOES_WORK_DIR" == /srv/project-echoes/final-discovery/work-20260922-m7-null-recovery'
        in script
    )
