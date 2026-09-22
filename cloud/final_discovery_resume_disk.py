"""Read-only launch capacity proof for the single five-stage recovery successor.

The ordinary launch contract remains 280 GiB. This recovery retains the entire
139,838,254,692-byte modeled campaign allocation as ADDITIONAL free capacity,
plus the unchanged 80 GiB floor. It credits no bytes for completed stages and
makes no claim that a benchmark projection guarantees future peak disk use.
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
    if work_directory != RECOVERY_WORK:
        return {"basis": "fresh_run_280_gib", "required_launch_free_bytes": FRESH_FREE_BYTES}
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
    source_tree = recovery._git_tree(root, SOURCE_COMMIT)
    target_tree = recovery._git_tree(root, commit)
    _require(recovery._tree_hash(source_tree) == SOURCE_CODE, "source code tree differs")
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
        "source_code_commit": SOURCE_COMMIT,
        "source_code_sha256": SOURCE_CODE,
        "target_code_commit": commit,
        "target_code_sha256": code_hash,
        "changed_files": changed_files,
    }
    store = StageStore(stages)
    cache: dict[str, StageCompletionManifest] = {}
    completion_hashes: dict[str, str] = {}
    compatibility_hash: str | None = None
    for stage_id, expected_inputs in zip(SOURCE_COMPLETIONS, (one, two, {}, {}, {}), strict=True):
        manifest = store.authenticate_completion(
            stage_id,
            expected_input_hashes=expected_inputs,
            expected_config_sha256=CONFIG_HASH,
            expected_code_sha256=code_hash,
            expected_code_commit=commit,
            _cache=cache,
        )
        artifact_root = recovery._artifact_root(store, manifest)
        proof_root = artifact_root / PREFIX
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
        for source_id, expected_hash in SOURCE_COMPLETIONS.items():
            content = (proof_root / f"{source_id}.source-completion.json").read_bytes()
            _require(
                _digest(content) == expected_hash, f"source completion pin differs: {source_id}"
            )
            originals[source_id] = StageCompletionManifest.model_validate_json(content)
        original = originals[stage_id]
        _require(
            original.stage_id == stage_id
            and original.code_commit == SOURCE_COMMIT
            and original.code_sha256 == SOURCE_CODE
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
            | {f"{PREFIX}/{name}.source-completion.json" for name in SOURCE_COMPLETIONS}
            | {f"{PREFIX}/compatibility-manifest.json", f"{PREFIX}/reuse-provenance.json"},
            "unexpected imported artifact inventory",
        )
        provenance = json.loads((proof_root / "reuse-provenance.json").read_bytes())
        expected = {
            "schema_version": 1,
            "operation": "authenticated_unchanged_five_stage_import",
            "source_work_directory": SOURCE_WORK,
            "source_code_commit": SOURCE_COMMIT,
            "source_code_sha256": SOURCE_CODE,
            "source_stage_id": stage_id,
            "source_completion_sha256": SOURCE_COMPLETIONS,
            "source_output_inventory_sha256": original.output_inventory_sha256,
            "revalidation_code_commit": commit,
            "revalidation_code_sha256": code_hash,
            "compatibility_manifest_sha256": compatibility_hash,
            "config_sha256": CONFIG_HASH,
            "copy_mode": "independent_file_copy",
            "original_receipts_preserved": True,
        }
        _require(
            all(provenance.get(key) == value for key, value in expected.items()),
            "resume import provenance differs",
        )
        completion_hashes[stage_id] = sha256_file(store.completion_path(stage_id))
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
