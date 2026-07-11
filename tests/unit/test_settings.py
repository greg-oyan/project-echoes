"""Typed configuration loading tests."""

from pathlib import Path

import pytest

from echoes.settings import ConfigLoadError, CorporaConfig, load_config, validate_config_directory

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_project_configuration_files_load() -> None:
    validated = validate_config_directory(PROJECT_ROOT / "config")

    assert len(validated) == 12
    assert isinstance(validated[PROJECT_ROOT / "config" / "corpora.yaml"], CorporaConfig)


def test_invalid_configuration_has_clear_error(tmp_path: Path) -> None:
    invalid = tmp_path / "corpora.yaml"
    invalid.write_text("schema_version: 1\ncorpora: not-a-list\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match=r"validation failed for .*corpora\.yaml"):
        load_config(invalid)
