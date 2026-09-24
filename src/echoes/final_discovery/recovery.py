"""Import authenticated, scientifically unchanged input stages without recomputation.

This local-only operation publishes new revalidation attempts. Original receipts
and artifact bytes are preserved; neither StageStore's identity checks nor the
production command's validation are relaxed. No object-store client is created.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from echoes.benchmarks.positive_controls import validate_positive_controls
from echoes.final_discovery.command import (
    _input_file_anchors,
    authenticate_clean_git_tree,
    knownness_receipt_path,
)
from echoes.final_discovery.config import (
    FinalDiscoveryConfig,
    final_discovery_config_sha256,
    load_final_discovery_config,
)
from echoes.final_discovery.inputs import sha256_file
from echoes.final_discovery.knownness_projection import authenticate_knownness_jsonl
from echoes.final_discovery.semantic import (
    verify_model_artifacts,
    verify_model_runtime_dependencies,
)
from echoes.final_discovery.stages import StageCompletionManifest, StageRunResult, StageStore

SOURCE_COMMIT = "06baacb0f1c9012a92f00a848bc381e696c9c454"
REVIEWED_COMMIT = "e265b59cc26bf33daf1eec832d54b71f29557c19"
STAGE_IDS = ("authenticate_materialize_inputs", "semantic_representations_indexes")
PROVENANCE_PATH = "checkpoint-reuse/reuse-provenance.json"
_PIPELINE = "src/echoes/final_discovery/pipeline.py"
_ADAPTER = "src/echoes/final_discovery/m7_adapter.py"
_NEW_MODULES = {
    "src/echoes/final_discovery/recovery.py",
    "src/echoes/final_discovery/projection_cache.py",
}


class RecoveryError(RuntimeError):
    """A proposed import is not authenticated or scientifically compatible."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryError(message)


def _safe_path(path: Path, *, directory: bool) -> Path:
    absolute = path.absolute()
    _require(absolute.resolve(strict=True) == absolute, f"redirected recovery path: {path}")
    _require(not absolute.is_symlink(), f"linked recovery path: {path}")
    _require(
        absolute.is_dir() if directory else absolute.is_file(),
        f"recovery path has the wrong type: {path}",
    )
    return absolute


def _git_tree(root: Path, commit: str) -> dict[str, bytes]:
    process = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "archive",
            "--format=tar",
            commit,
            "src",
            "config",
            "pyproject.toml",
            "uv.lock",
        ],
        check=True,
        capture_output=True,
    )
    result: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(process.stdout), mode="r:") as archive:
        for member in archive:
            name = member.name
            governed = (
                (name.startswith("src/") and name.endswith(".py"))
                or (name.startswith("config/") and name.endswith(".yaml"))
                or name in {"pyproject.toml", "uv.lock"}
            )
            if not governed:
                continue
            _require(member.isfile(), f"non-regular governed Git member: {name}")
            stream = archive.extractfile(member)
            _require(stream is not None, f"missing governed Git member: {name}")
            assert stream is not None
            result[name] = stream.read()
    return result


def _tree_hash(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode() + b"\0" + content + b"\0")
    return digest.hexdigest()


def _without_functions(content: bytes, names: set[str]) -> str:
    parsed = ast.parse(content)
    parsed.body = [
        node
        for node in parsed.body
        if not isinstance(node, ast.FunctionDef) or node.name not in names
    ]
    return ast.dump(parsed, include_attributes=False)


def _scientific_compatibility(root: Path, current_commit: str) -> dict[str, str]:
    source = _git_tree(root, SOURCE_COMMIT)
    reviewed = _git_tree(root, REVIEWED_COMMIT)
    current = _git_tree(root, current_commit)
    _require(set(source) == set(reviewed), "reviewed scientific source inventory changed")
    for name, content in source.items():
        if name == _ADAPTER:
            excluded = {"build_m7_lexical_projection", "iter_m7_raw_evidence"}
            same = _without_functions(content, excluded) == _without_functions(
                reviewed[name], excluded
            )
        else:
            same = content == reviewed[name]
        _require(same, f"source-to-reviewed Stage 1/2 science differs: {name}")
    _require(
        set(reviewed) <= set(current) and set(current) - set(reviewed) <= _NEW_MODULES,
        "unreviewed scientific source inventory changed",
    )
    for name, content in reviewed.items():
        if name == _PIPELINE:
            excluded = {"_produce_stage_three", "_produce_stage_eleven"}
            same = _without_functions(content, excluded) == _without_functions(
                current[name], excluded
            )
        else:
            same = content == current[name]
        _require(same, f"current Stage 1/2 scientific closure differs: {name}")
    return {
        "source_code_sha256": _tree_hash(source),
        "reviewed_code_sha256": _tree_hash(reviewed),
        "current_code_sha256": _tree_hash(current),
    }


def _current_inputs(
    root: Path,
    config: FinalDiscoveryConfig,
    prepared: Path,
    knownness: Path,
    model_root: Path,
) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    positive_controls = validate_positive_controls(
        root / "data/benchmarks/positive_controls.yaml",
        data_path=root / "data/benchmarks/positive_controls.csv",
    )
    anchors = _input_file_anchors(root, config)
    m7_input = next(item for item in config.inputs if item.role == "canonical_m7")
    _require(m7_input.expected_manifest_sha256 is not None, "M7 manifest is not pinned")
    assert m7_input.expected_manifest_sha256 is not None
    knownness_receipt = _safe_path(knownness_receipt_path(knownness), directory=False)
    hashes = {
        name: digest
        for artifact in config.inputs
        for name, digest in artifact.expected_hashes.items()
    }
    authenticate_knownness_jsonl(
        knownness,
        knownness_receipt,
        expected_manifest_sha256=hashes["data/processed/benchmarks/schema-v1/table-hashes.json"],
    )
    one = {
        "m7-table-hashes.json": m7_input.expected_manifest_sha256,
        "prepared-passages.jsonl": sha256_file(prepared),
        "knownness-relationships": sha256_file(knownness),
        "knownness-projection-receipt": sha256_file(knownness_receipt),
        "positive-control-config": positive_controls.validation.config_sha256,
        "positive-control-data": positive_controls.validation.data_sha256,
        **{f"input-anchor:{anchor.relative_path}": anchor.sha256 for anchor in anchors},
    }
    model = verify_model_artifacts(model_root, config.embedding_model)
    runtime = verify_model_runtime_dependencies(config.embedding_model)
    # Exact serialization used by pipeline._model_state_sha256, without loading an encoder.
    model_identity = json.dumps(
        {
            "model_id": config.embedding_model.model_id,
            "revision": config.embedding_model.revision,
            "allowed_files": config.embedding_model.allowed_files,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    two = {"offline-embedding-model-state": hashlib.sha256(model_identity.encode()).hexdigest()}
    return (
        one,
        two,
        {
            "enabled": True,
            **model.model_dump(mode="json"),
            "runtime": runtime.model_dump(mode="json"),
        },
    )


def _artifact_root(store: StageStore, manifest: StageCompletionManifest) -> Path:
    return store.completion_path(manifest.stage_id).parent.joinpath(
        *PurePosixPath(manifest.artifacts_root).parts
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")


def import_completed_input_stages(
    *,
    project_root: Path,
    source_work_directory: Path,
    work_directory: Path,
    prepared_passages_path: Path,
    knownness_path: Path,
    offline_model_root: Path,
) -> tuple[StageRunResult, StageRunResult]:
    """Revalidate and copy original 06baacb Stage 1/2 into current-code attempts.

    Every source check, including both stages and the actual model/runtime,
    completes before any target attempt is started. Existing target completions
    are accepted only through StageStore's ordinary strict authentication.
    """
    root = _safe_path(project_root, directory=True)
    source_work = _safe_path(source_work_directory, directory=True)
    target_work = _safe_path(work_directory, directory=True)
    _require(
        not source_work.is_relative_to(target_work) and not target_work.is_relative_to(source_work),
        "source and target recovery work directories must be disjoint",
    )
    prepared = _safe_path(prepared_passages_path, directory=False)
    knownness = _safe_path(knownness_path, directory=False)
    model_root = _safe_path(offline_model_root, directory=True)
    commit, code_hash = authenticate_clean_git_tree(root)
    compatibility = _scientific_compatibility(root, commit)
    _require(compatibility["current_code_sha256"] == code_hash, "current Git/source bytes differ")
    config = load_final_discovery_config(root / "config/experiments/final-discovery-v1.yaml")
    config_hash = final_discovery_config_sha256(config)
    one_inputs, two_inputs, model_report = _current_inputs(
        root, config, prepared, knownness, model_root
    )
    source_store = StageStore(_safe_path(source_work / "stages", directory=True))
    cache: dict[str, StageCompletionManifest] = {}
    manifests = tuple(
        source_store.authenticate_completion(
            stage_id,
            expected_input_hashes=inputs,
            expected_config_sha256=config_hash,
            expected_code_sha256=compatibility["source_code_sha256"],
            expected_code_commit=SOURCE_COMMIT,
            _cache=cache,
        )
        for stage_id, inputs in zip(STAGE_IDS, (one_inputs, two_inputs), strict=True)
    )
    original_completions = {
        manifest.stage_id: source_store.completion_path(manifest.stage_id).read_bytes()
        for manifest in manifests
    }
    for manifest in manifests:
        _require(
            StageCompletionManifest.model_validate_json(original_completions[manifest.stage_id])
            == manifest,
            "source completion changed after authentication",
        )
    old_model = json.loads(
        (_artifact_root(source_store, manifests[1]) / "model-report.json").read_bytes()
    )
    _require(old_model == model_report, "source Stage 2 model/runtime inventory differs")
    for manifest in manifests:
        _require(
            not any(item.path.startswith("checkpoint-reuse/") for item in manifest.artifacts),
            "source stage is already an imported recovery",
        )
    target_store = StageStore(target_work / "stages")
    results: list[StageRunResult] = []
    for manifest, inputs in zip(manifests, (one_inputs, two_inputs), strict=True):
        source_root = _artifact_root(source_store, manifest)
        provenance: dict[str, Any] = {
            "schema_version": 1,
            "operation": "authenticated_unchanged_stage_artifact_import",
            "source_work_directory": str(source_work),
            "source_stage_id": manifest.stage_id,
            "source_code_commit": SOURCE_COMMIT,
            "source_output_inventory_sha256": manifest.output_inventory_sha256,
            "source_completion_sha256": {
                stage_id: hashlib.sha256(content).hexdigest()
                for stage_id, content in original_completions.items()
            },
            "reviewed_code_commit": REVIEWED_COMMIT,
            "revalidation_code_commit": commit,
            "scientific_compatibility": compatibility,
            "config_sha256": config_hash,
            "copy_mode": "independent_file_copy",
            "original_receipts_preserved": True,
        }

        def produce(
            destination: Path,
            manifest: StageCompletionManifest = manifest,
            source_root: Path = source_root,
            provenance: dict[str, Any] = provenance,
        ) -> None:
            for artifact in manifest.artifacts:
                source = source_root.joinpath(*PurePosixPath(artifact.path).parts)
                target = destination.joinpath(*PurePosixPath(artifact.path).parts)
                _safe_path(source, directory=False)
                target.parent.mkdir(parents=True, exist_ok=True)
                _require(not target.exists(), "recovery destination already exists")
                shutil.copy2(source, target, follow_symlinks=False)
                _require(
                    target.stat().st_size == artifact.size
                    and sha256_file(target) == artifact.sha256,
                    f"copied recovery artifact differs: {artifact.path}",
                )
            evidence = destination / "checkpoint-reuse"
            evidence.mkdir()
            for stage_id, content in original_completions.items():
                _require(
                    source_store.completion_path(stage_id).read_bytes() == content,
                    "source completion changed during recovery",
                )
                with (evidence / f"{stage_id}.source-completion.json").open("xb") as handle:
                    handle.write(content)
            _write_json(
                evidence / "reuse-provenance.json",
                {
                    **provenance,
                    "revalidated_at": datetime.now(UTC).isoformat(),
                },
            )

        result = target_store.run_stage(
            manifest.stage_id,
            input_hashes=inputs,
            config_sha256=config_hash,
            code_sha256=code_hash,
            code_commit=commit,
            producer=produce,
        )
        imported_root = _artifact_root(target_store, result.manifest)
        imported_artifacts = {artifact.path: artifact for artifact in result.manifest.artifacts}
        _require(
            all(
                imported_artifacts.get(artifact.path) == artifact for artifact in manifest.artifacts
            ),
            "completed target artifacts differ from the authenticated source inventory",
        )
        observed = json.loads((imported_root / PROVENANCE_PATH).read_bytes())
        _require(
            all(observed.get(key) == value for key, value in provenance.items()),
            "completed target reuse provenance differs",
        )
        for stage_id, content in original_completions.items():
            _require(
                (
                    imported_root / "checkpoint-reuse" / f"{stage_id}.source-completion.json"
                ).read_bytes()
                == content,
                "completed target original receipt bytes differ",
            )
        results.append(result)
    return results[0], results[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in (
        "project-root",
        "source-work-directory",
        "work-directory",
        "prepared-passages",
        "knownness",
        "offline-model-root",
    ):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    results = import_completed_input_stages(
        project_root=args.project_root,
        source_work_directory=args.source_work_directory,
        work_directory=args.work_directory,
        prepared_passages_path=args.prepared_passages,
        knownness_path=args.knownness,
        offline_model_root=args.offline_model_root,
    )
    print(
        json.dumps(
            {
                "result": "pass",
                "imported_stages": [
                    {
                        "stage_id": result.manifest.stage_id,
                        "completion_sha256": result.completion_manifest_sha256,
                        "code_commit": result.manifest.code_commit,
                        "skipped": result.skipped,
                    }
                    for result in results
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
