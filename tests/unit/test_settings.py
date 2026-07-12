"""Typed configuration loading tests."""

from pathlib import Path

import pytest

from echoes.settings import (
    ConfigLoadError,
    CorporaConfig,
    NormalizationConfig,
    load_config,
    validate_config_directory,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_project_configuration_files_load() -> None:
    validated = validate_config_directory(PROJECT_ROOT / "config")

    assert len(validated) == 14
    assert isinstance(validated[PROJECT_ROOT / "config" / "corpora.yaml"], CorporaConfig)


def test_invalid_configuration_has_clear_error(tmp_path: Path) -> None:
    invalid = tmp_path / "corpora.yaml"
    invalid.write_text("schema_version: 1\ncorpora: not-a-list\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match=r"validation failed for .*corpora\.yaml"):
        load_config(invalid)


def test_ketiv_qere_analysis_reading_is_strict_and_defaults_to_qere(
    tmp_path: Path,
) -> None:
    project_path = PROJECT_ROOT / "config" / "normalization.yaml"
    project = load_config(project_path)
    assert isinstance(project, NormalizationConfig)
    assert project.ketiv_qere.analysis_reading == "qere"

    ketiv_path = tmp_path / "normalization.yaml"
    ketiv_path.write_text(
        project_path.read_text(encoding="utf-8").replace(
            "analysis_reading: qere", "analysis_reading: ketiv"
        ),
        encoding="utf-8",
    )
    ketiv = load_config(ketiv_path)
    assert isinstance(ketiv, NormalizationConfig)
    assert ketiv.ketiv_qere.analysis_reading == "ketiv"

    ketiv_path.write_text(
        ketiv_path.read_text(encoding="utf-8").replace(
            "analysis_reading: ketiv", "analysis_reading: both"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError, match="analysis_reading"):
        load_config(ketiv_path)
