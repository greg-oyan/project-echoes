"""Run-manifest unit tests."""

from pathlib import Path

import pytest

from echoes.manifest import RunManifest, build_run_manifest, write_run_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_build_run_manifest_has_required_provenance() -> None:
    manifest = build_run_manifest(
        "foundation smoke",
        project_root=PROJECT_ROOT,
        config_dir=PROJECT_ROOT / "config",
    )

    assert manifest.run_id.startswith("foundation-smoke-")
    assert len(manifest.config_hash) == 64
    assert manifest.random_seed == 1729
    assert manifest.dataset_manifest_hash is None
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
