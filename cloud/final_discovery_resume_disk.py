"""Read-only launch capacity proof for exact authenticated recovery successors.

The ordinary launch contract remains 280 GiB. This recovery retains the entire
139,838,254,692-byte modeled campaign allocation as ADDITIONAL free capacity,
plus the unchanged 80 GiB floor. It credits no bytes for completed stages and
makes no claim that a benchmark projection guarantees future peak disk use.
The six-stage successor subtracts only the modeled canonical M7 and raw
evidence already authenticated locally. Its reserve is for remaining persistent
artifacts plus the same floor, not a bound on scratch or full review output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from echoes.final_discovery import recovery
from echoes.final_discovery.command import authenticate_clean_git_tree
from echoes.final_discovery.config import (
    final_discovery_config_sha256,
    load_final_discovery_config,
)
from echoes.final_discovery.stages import StageCompletionManifest, StageStore
from echoes.manifest import sha256_file

RECOVERY_WORK = Path("/srv/project-echoes/final-discovery/work-20260922-m7-null-recovery")
SOURCE_WORK = "/srv/project-echoes/final-discovery/work-20260909T040447Z-e265b59c"
SOURCE_COMMIT = "cc88571db35eb85ea1ea5eb355731ad23c29dfda"
SOURCE_CODE = "e4c5930a85136941b943cd5630a489a7638400354be5e399c42e90312c973f4a"
CONFIG_HASH = "7b5c511fed3be041576f9c2ea784d71e028a0f539d7642d84ddcf61eccd22627"
FRESH_FREE_BYTES = 280 * 1024**3
MODELED_ADDITIONAL_BYTES = 139_838_254_692
FLOOR_BYTES = 80 * 1024**3
REQUIRED_RECOVERY_FREE_BYTES = MODELED_ADDITIONAL_BYTES + FLOOR_BYTES
PREFIX = "checkpoint-reuse/null-provenance-repair-v1"
SOURCE_COMPLETIONS = {
    "authenticate_materialize_inputs": (
        "9fb5be11b6a9af1806af43bbc930e8fad9ec32876d5111f070a25b7935568bb3"
    ),
    "semantic_representations_indexes": (
        "00cdd9ca05b1e91ccaea195694f6520b4f914d74bbe4bc7b4ab7e7c270f777c5"
    ),
    "semantic_candidate_evidence": (
        "086030b2caa5984762bc7a5e870d0bf45b3d24ab4958599ff8ffe06f0b0868d3"
    ),
    "grammatical_syntactic_evidence": (
        "f019c859294a18eedb84469d66df0af3fe9d0edbd315896929d5bbbc02eb7051"
    ),
    "structural_narrative_evidence": (
        "463fc8910237eef9450261f13d1b798785121cef5132a255d1438c81a1213762"
    ),
}
CALIBRATION_WORK = Path("/srv/project-echoes/final-discovery/work-20260923-calibration-memory")
CALIBRATION_SOURCE_WORK = str(RECOVERY_WORK)
CALIBRATION_SOURCE_COMMIT = "c94e41df0b4ddbc7e1dcd83c27b7bb2200582d9b"
CALIBRATION_SOURCE_CODE = "6e5666cbf9aac778ffdb8013bb6db875cd72dc7882a55fe040a56cd842c369ea"
CALIBRATION_PREFIX = "checkpoint-reuse/calibration-memory-repair-v1"
CALIBRATION_SOURCE_COMPLETIONS = {
    "authenticate_materialize_inputs": (
        "f22261617c7a11287a92ec4e3b02eae0f75aae2c5a887bedd369849d9783143c"
    ),
    "semantic_representations_indexes": (
        "f32c51f774ae6d2abc07ffdabeae6d2ba1bbb851e4d89fa4d9c98fbb74ce5c97"
    ),
    "semantic_candidate_evidence": (
        "5983fd0b659495cd61e60e2f9ed60b3c8355194e67ce4197cdfe730fe22694bb"
    ),
    "grammatical_syntactic_evidence": (
        "3355069264724f8f93c5b1cd468031a12e0bad29ebd7750017bf32dc5817910d"
    ),
    "structural_narrative_evidence": (
        "3280b5eb4689a453258cf0978267bb9476af7c77fb7d8e71fb0d4c06f6688c90"
    ),
    "anomaly_evidence": ("bdfbe013a3ba423d9ce872290a2059354758730669897d2ce075275c7304a41b"),
}
MODELED_COMPLETED_M7_BYTES = 18_413_598_540
MODELED_COMPLETED_RAW_BYTES = 45_119_780_852
CALIBRATION_MODELED_ADDITIONAL_BYTES = (
    MODELED_ADDITIONAL_BYTES - MODELED_COMPLETED_M7_BYTES - MODELED_COMPLETED_RAW_BYTES
)
REQUIRED_CALIBRATION_FREE_BYTES = CALIBRATION_MODELED_ADDITIONAL_BYTES + FLOOR_BYTES


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise recovery.RecoveryError(message)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def launch_capacity(
    project_root: Path,
    work_directory: Path,
    expected_commit: str,
    prepared_passages: Path,
    knownness: Path,
    offline_model_root: Path,
) -> dict[str, Any]:
    """Authenticate successor lineage before returning its conservative reserve."""
    calibration_successor = work_directory == CALIBRATION_WORK
    if work_directory not in (RECOVERY_WORK, CALIBRATION_WORK):
        return {"basis": "fresh_run_280_gib", "required_launch_free_bytes": FRESH_FREE_BYTES}
    source_commit = CALIBRATION_SOURCE_COMMIT if calibration_successor else SOURCE_COMMIT
    source_code = CALIBRATION_SOURCE_CODE if calibration_successor else SOURCE_CODE
    source_work = CALIBRATION_SOURCE_WORK if calibration_successor else SOURCE_WORK
    source_completions = (
        CALIBRATION_SOURCE_COMPLETIONS if calibration_successor else SOURCE_COMPLETIONS
    )
    prefix = CALIBRATION_PREFIX if calibration_successor else PREFIX
    stage_count = len(source_completions)
    operation = (
        "authenticated_unchanged_six_stage_import"
        if calibration_successor
        else "authenticated_unchanged_five_stage_import"
    )
    copy_mode = "same_filesystem_hardlink" if calibration_successor else "independent_file_copy"
    root = recovery._safe_path(project_root, directory=True)
    work = recovery._safe_path(work_directory, directory=True)
    stages = recovery._safe_path(work / "stages", directory=True)
    commit, code_hash = authenticate_clean_git_tree(root)
    _require(commit == expected_commit, "resume capacity current commit differs")
    config = load_final_discovery_config(root / "config/experiments/final-discovery-v1.yaml")
    _require(
        final_discovery_config_sha256(config) == CONFIG_HASH,
        "resume configuration differs",
    )
    one, two, _ = recovery._current_inputs(
        root, config, prepared_passages, knownness, offline_model_root
    )
    source_tree = recovery._git_tree(root, source_commit)
    target_tree = recovery._git_tree(root, commit)
    _require(recovery._tree_hash(source_tree) == source_code, "source code tree differs")
    _require(recovery._tree_hash(target_tree) == code_hash, "target code tree differs")
    changed_files = {
        name: {
            "source_sha256": _digest(source_tree[name]) if name in source_tree else None,
            "target_sha256": _digest(target_tree[name]) if name in target_tree else None,
        }
        for name in sorted(source_tree.keys() | target_tree.keys())
        if source_tree.get(name) != target_tree.get(name)
    }
    expected_compatibility = {
        "schema_version": 1,
        "source_code_commit": source_commit,
        "source_code_sha256": source_code,
        "target_code_commit": commit,
        "target_code_sha256": code_hash,
        "changed_files": changed_files,
    }
    store = StageStore(stages)
    cache: dict[str, StageCompletionManifest] = {}
    completion_hashes: dict[str, str] = {}
    compatibility_hash: str | None = None
    expected_stage_inputs = (one, two, *({} for _ in range(stage_count - 2)))
    for stage_id, expected_inputs in zip(source_completions, expected_stage_inputs, strict=True):
        manifest = store.authenticate_completion(
            stage_id,
            expected_input_hashes=expected_inputs,
            expected_config_sha256=CONFIG_HASH,
            expected_code_sha256=code_hash,
            expected_code_commit=commit,
            _cache=cache,
        )
        artifact_root = recovery._artifact_root(store, manifest)
        proof_root = artifact_root / prefix
        compatibility = (proof_root / "compatibility-manifest.json").read_bytes()
        _require(
            json.loads(compatibility) == expected_compatibility, "resume compatibility differs"
        )
        observed_compatibility_hash = _digest(compatibility)
        if compatibility_hash is None:
            compatibility_hash = observed_compatibility_hash
        _require(
            observed_compatibility_hash == compatibility_hash, "stage compatibility bytes differ"
        )
        originals: dict[str, StageCompletionManifest] = {}
        for source_id, expected_hash in source_completions.items():
            content = (proof_root / f"{source_id}.source-completion.json").read_bytes()
            _require(
                _digest(content) == expected_hash, f"source completion pin differs: {source_id}"
            )
            originals[source_id] = StageCompletionManifest.model_validate_json(content)
        original = originals[stage_id]
        _require(
            original.stage_id == stage_id
            and original.code_commit == source_commit
            and original.code_sha256 == source_code
            and original.config_sha256 == CONFIG_HASH
            and original.input_sha256 == expected_inputs,
            "source completion identity differs",
        )
        imported = {artifact.path: artifact for artifact in manifest.artifacts}
        _require(
            all(imported.get(item.path) == item for item in original.artifacts),
            "imported artifact differs",
        )
        _require(
            set(imported)
            == {item.path for item in original.artifacts}
            | {f"{prefix}/{name}.source-completion.json" for name in source_completions}
            | {f"{prefix}/compatibility-manifest.json", f"{prefix}/reuse-provenance.json"},
            "unexpected imported artifact inventory",
        )
        provenance = json.loads((proof_root / "reuse-provenance.json").read_bytes())
        expected = {
            "schema_version": 1,
            "operation": operation,
            "source_work_directory": source_work,
            "source_code_commit": source_commit,
            "source_code_sha256": source_code,
            "source_stage_id": stage_id,
            "source_completion_sha256": source_completions,
            "source_output_inventory_sha256": original.output_inventory_sha256,
            "revalidation_code_commit": commit,
            "revalidation_code_sha256": code_hash,
            "compatibility_manifest_sha256": compatibility_hash,
            "config_sha256": CONFIG_HASH,
            "copy_mode": copy_mode,
            "original_receipts_preserved": True,
        }
        if calibration_successor:
            expected.update(
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
        _require(
            all(provenance.get(key) == value for key, value in expected.items()),
            "resume import provenance differs",
        )
        completion_hashes[stage_id] = sha256_file(store.completion_path(stage_id))
    if calibration_successor:
        return {
            "basis": "authenticated_six_stage_import_remaining_modeled_artifacts_plus_80_gib",
            "required_launch_free_bytes": REQUIRED_CALIBRATION_FREE_BYTES,
            "modeled_additional_bytes": CALIBRATION_MODELED_ADDITIONAL_BYTES,
            "checkpoint_disk_floor_bytes": FLOOR_BYTES,
            "completed_artifact_credit_bytes": (
                MODELED_COMPLETED_M7_BYTES + MODELED_COMPLETED_RAW_BYTES
            ),
            "projection_is_not_a_peak_guarantee": True,
            "unmodeled_peak_components": ["duckdb_database_and_spill", "full_review_outputs"],
            "checkpoint_and_package_payloads_use_hardlinks": True,
            "import_copy_mode": copy_mode,
            "authenticated_completion_sha256": completion_hashes,
            "compatibility_manifest_sha256": compatibility_hash,
            "current_code_commit": commit,
            "current_code_sha256": code_hash,
        }
    return {
        "basis": "authenticated_five_stage_import_full_modeled_additional_reserve_plus_80_gib",
        "required_launch_free_bytes": REQUIRED_RECOVERY_FREE_BYTES,
        "modeled_additional_bytes": MODELED_ADDITIONAL_BYTES,
        "checkpoint_disk_floor_bytes": FLOOR_BYTES,
        "completed_artifact_credit_bytes": 0,
        "projection_is_not_a_peak_guarantee": True,
        "authenticated_completion_sha256": completion_hashes,
        "compatibility_manifest_sha256": compatibility_hash,
        "current_code_commit": commit,
        "current_code_sha256": code_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in (
        "project-root",
        "work-directory",
        "prepared-passages",
        "knownness",
        "offline-model-root",
    ):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    args = vars(parser.parse_args())
    print(json.dumps(launch_capacity(**args), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
