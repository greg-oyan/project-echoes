from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echoes.final_discovery import pipeline, projection_cache
from echoes.final_discovery.config import load_final_discovery_config
from echoes.final_discovery.stages import StageStore


@pytest.mark.parametrize("pinned", [False, True])
def test_stage_three_uses_work_level_cache_with_explicit_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pinned: bool
) -> None:
    work = tmp_path / "work"
    receipt = work / "recovery/m7-projection/receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("{}", encoding="utf-8")
    stage_two = tmp_path / "stage-two"
    stage_two.mkdir()
    (stage_two / "semantic-index.json").write_text(
        json.dumps({"candidate_pairs": []}), encoding="utf-8"
    )
    request = SimpleNamespace(
        execution_mode="production",
        stage_store=StageStore(work / "stages"),
        m7_expectation=SimpleNamespace(table_hashes_sha256="b" * 64),
    )

    class CacheReached(Exception):
        pass

    def reuse(receipt_path, source_root, output_path, **kwargs):  # type: ignore[no-untyped-def]
        assert receipt_path == receipt and receipt_path.is_file()
        assert source_root == tmp_path / "stage-one/m7"
        assert output_path == tmp_path / "stage-three/m7-lexical-projection.parquet"
        assert kwargs["expected_receipt_sha256"] == "a" * 64
        assert kwargs["expected_manifest_sha256"] == "b" * 64
        raise CacheReached

    monkeypatch.setattr(projection_cache, "reuse_tested_projection", reuse)
    if pinned:
        monkeypatch.setenv("ECHOES_M7_PROJECTION_RECEIPT_SHA256", "a" * 64)
        expected = pytest.raises(CacheReached)
    else:
        monkeypatch.delenv("ECHOES_M7_PROJECTION_RECEIPT_SHA256", raising=False)
        expected = pytest.raises(pipeline.FinalDiscoveryCampaignError, match="no pinned")
    with expected:
        pipeline._produce_stage_three(
            tmp_path / "stage-three", request, (), {}, {}, tmp_path / "stage-one", stage_two
        )


def test_final_package_preserves_original_checkpoint_reuse_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = pipeline.build_bounded_fixture_campaign_request(
        tmp_path / "work",
        config=load_final_discovery_config(),
        code_sha256="a" * 64,
        code_commit="bounded-recovery-fixture",
    )
    original = pipeline._produce_stage_one
    files = {
        "reuse-provenance.json": b'{"source_commit":"original"}\n',
        "authenticate_materialize_inputs.source-completion.json": b"original stage one\n",
        "semantic_representations_indexes.source-completion.json": b"original stage two\n",
    }

    def produce(root, request, controls):  # type: ignore[no-untyped-def]
        original(root, request, controls)
        provenance = root / "checkpoint-reuse"
        provenance.mkdir()
        for name, content in files.items():
            (provenance / name).write_bytes(content)

    monkeypatch.setattr(pipeline, "_produce_stage_one", produce)
    result = pipeline.run_final_discovery_campaign(request)
    packaged = result.package_path.parent / "package/artifacts/inputs/checkpoint-reuse"
    assert {path.name: path.read_bytes() for path in packaged.iterdir()} == files
