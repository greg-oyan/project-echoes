from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echoes.final_discovery import recovery
from echoes.final_discovery.config import final_discovery_config_sha256, load_final_discovery_config
from echoes.final_discovery.inputs import sha256_file
from echoes.final_discovery.stages import StageStore, StageStoreError


@pytest.fixture
def import_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    root = tmp_path / "repo"
    source = tmp_path / "source"
    target = tmp_path / "target"
    model = tmp_path / "model"
    for path in (root, source, target, model):
        path.mkdir()
    prepared = tmp_path / "prepared.jsonl"
    knownness = tmp_path / "knownness.jsonl"
    prepared.write_bytes(b"prepared governed input\n")
    knownness.write_bytes(b"known relationships\n")
    (model / "weights").write_bytes(b"fixed offline model")
    config = load_final_discovery_config()
    config_hash = final_discovery_config_sha256(config)
    monkeypatch.setattr(recovery, "load_final_discovery_config", lambda _: config)
    monkeypatch.setattr(recovery, "authenticate_clean_git_tree", lambda _: ("current", "b" * 64))
    monkeypatch.setattr(
        recovery,
        "_scientific_compatibility",
        lambda *_: {
            "source_code_sha256": "a" * 64,
            "reviewed_code_sha256": "c" * 64,
            "current_code_sha256": "b" * 64,
        },
    )

    def current_inputs(*_args: object) -> tuple[dict[str, str], dict[str, str], dict[str, object]]:
        return (
            {
                "prepared-passages.jsonl": sha256_file(prepared),
                "knownness-relationships": sha256_file(knownness),
            },
            {"offline-embedding-model-state": "d" * 64},
            {
                "enabled": True,
                "inventory_sha256": sha256_file(model / "weights"),
                "runtime": {"python_version": "3.12.13"},
            },
        )

    monkeypatch.setattr(recovery, "_current_inputs", current_inputs)
    one, two, report = current_inputs()
    store = StageStore(source / "stages")

    def first(destination: Path) -> None:
        (destination / "passages.jsonl").write_bytes(prepared.read_bytes())
        (destination / "source-receipt.json").write_bytes(b'{"original_code":"06baacb"}\n')

    def second(destination: Path) -> None:
        (destination / "embeddings.bin").write_bytes(b"expensive completed representation")
        (destination / "model-report.json").write_text(json.dumps(report), encoding="utf-8")

    for stage_id, inputs, producer in zip(
        recovery.STAGE_IDS, (one, two), (first, second), strict=True
    ):
        store.run_stage(
            stage_id,
            input_hashes=inputs,
            config_sha256=config_hash,
            code_sha256="a" * 64,
            code_commit=recovery.SOURCE_COMMIT,
            producer=producer,
        )
    original = {
        path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()
    }
    return SimpleNamespace(
        source=source,
        target=target,
        store=store,
        config=config,
        original=original,
        model=model,
        prepared=prepared,
        knownness=knownness,
        arguments={
            "project_root": root,
            "source_work_directory": source,
            "work_directory": target,
            "prepared_passages_path": prepared,
            "knownness_path": knownness,
            "offline_model_root": model,
        },
    )


def test_import_preserves_bytes_provenance_and_new_dependency_chain(
    import_case: SimpleNamespace,
) -> None:
    results = recovery.import_completed_input_stages(**import_case.arguments)
    target = StageStore(import_case.target / "stages")
    for result in results:
        assert result.manifest.code_commit == "current"
        assert result.manifest.code_sha256 == "b" * 64
        assert not result.skipped
        root = recovery._artifact_root(target, result.manifest)
        provenance = json.loads((root / recovery.PROVENANCE_PATH).read_bytes())
        assert provenance["source_code_commit"] == recovery.SOURCE_COMMIT
        for stage_id in recovery.STAGE_IDS:
            assert (
                root / "checkpoint-reuse" / f"{stage_id}.source-completion.json"
            ).read_bytes() == (import_case.store.completion_path(stage_id).read_bytes())
    assert results[1].manifest.dependency_completion_sha256 == {
        recovery.STAGE_IDS[0]: results[0].completion_manifest_sha256
    }
    assert {
        path.relative_to(import_case.source): path.read_bytes()
        for path in import_case.source.rglob("*")
        if path.is_file()
    } == import_case.original
    source_root = recovery._artifact_root(
        import_case.store, import_case.store.authenticate_completion(recovery.STAGE_IDS[0])
    )
    copied_root = recovery._artifact_root(target, results[0].manifest)
    assert (source_root / "passages.jsonl").stat().st_ino != (
        copied_root / "passages.jsonl"
    ).stat().st_ino
    assert all(
        result.skipped for result in recovery.import_completed_input_stages(**import_case.arguments)
    )


@pytest.mark.parametrize(
    "changed", ["prepared", "knownness", "model", "source_bytes", "dependency"]
)
def test_import_rejects_changed_source_or_inputs_before_target_attempt(
    import_case: SimpleNamespace, changed: str
) -> None:
    if changed in {"prepared", "knownness"}:
        getattr(import_case, changed).write_bytes(b"different governed input")
    elif changed == "model":
        (import_case.model / "weights").write_bytes(b"different model inventory")
    elif changed == "source_bytes":
        manifest = import_case.store.authenticate_completion(recovery.STAGE_IDS[1])
        root = recovery._artifact_root(import_case.store, manifest)
        (root / "embeddings.bin").write_bytes(b"tampered representation")
    else:
        path = import_case.store.completion_path(recovery.STAGE_IDS[1])
        value = json.loads(path.read_bytes())
        value["dependency_completion_sha256"][recovery.STAGE_IDS[0]] = "f" * 64
        path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises((recovery.RecoveryError, StageStoreError)):
        recovery.import_completed_input_stages(**import_case.arguments)
    assert not (import_case.target / "stages").exists()


def test_import_rejects_changed_configuration(
    import_case: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    altered = import_case.config.model_copy(
        update={"random_seed": import_case.config.random_seed + 1}
    )
    monkeypatch.setattr(recovery, "load_final_discovery_config", lambda _: altered)
    with pytest.raises(StageStoreError, match="config identity differs"):
        recovery.import_completed_input_stages(**import_case.arguments)
    assert not (import_case.target / "stages").exists()


def test_import_preserves_interrupted_target_attempt(import_case: SimpleNamespace) -> None:
    target = StageStore(import_case.target / "stages")
    manifest = import_case.store.authenticate_completion(recovery.STAGE_IDS[0])

    def interrupted(root: Path) -> None:
        (root / "preserved.bin").write_bytes(b"interrupted evidence")
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        target.run_stage(
            recovery.STAGE_IDS[0],
            input_hashes=manifest.input_sha256,
            config_sha256=manifest.config_sha256,
            code_sha256="b" * 64,
            code_commit="current",
            producer=interrupted,
        )
    before = {
        path.relative_to(import_case.target): path.read_bytes()
        for path in import_case.target.rglob("*")
        if path.is_file()
    }
    recovery.import_completed_input_stages(**import_case.arguments)
    for relative, content in before.items():
        assert (import_case.target / relative).read_bytes() == content


def test_scientific_closure_allows_only_reviewed_non_input_stage_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = {
        "src/echoes/final_discovery/m7_adapter.py": b"def authenticate_m7_input(): return 1\n",
        "src/echoes/final_discovery/pipeline.py": (
            b"def _produce_stage_one(): return 1\ndef _produce_stage_three(): return 2\n"
        ),
        "config/frozen.yaml": b"threshold: 5\n",
    }
    current = {**source, "src/echoes/final_discovery/recovery.py": b"# local import\n"}
    current[recovery._PIPELINE] = source[recovery._PIPELINE].replace(b"return 2", b"return 3")
    monkeypatch.setattr(
        recovery, "_git_tree", lambda _root, commit: current if commit == "current" else source
    )
    assert recovery._scientific_compatibility(tmp_path, "current")["source_code_sha256"]
    current[recovery._PIPELINE] = current[recovery._PIPELINE].replace(b"return 1", b"return 9")
    with pytest.raises(recovery.RecoveryError, match="scientific closure differs"):
        recovery._scientific_compatibility(tmp_path, "current")
