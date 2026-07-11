"""Experiment-governance schema tests."""

from pathlib import Path

import pytest

from echoes.manifests.experiments import ExperimentManifest, ExperimentStatus
from echoes.settings import ConfigLoadError, load_config, validate_config_directory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "experiments"


def test_valid_experiment_manifest_loads() -> None:
    manifest = load_config(FIXTURES / "valid.yaml")

    assert isinstance(manifest, ExperimentManifest)
    assert manifest.experiment_name == "fixture_experiment"
    assert manifest.status is ExperimentStatus.PLANNED


def test_invalid_experiment_manifest_has_clear_error() -> None:
    with pytest.raises(ConfigLoadError, match=r"validation failed for .*invalid\.yaml") as exc:
        load_config(FIXTURES / "invalid.yaml")

    assert "research_question" in str(exc.value)


def test_every_project_experiment_uses_governance_schema() -> None:
    validated = validate_config_directory(PROJECT_ROOT / "config")
    experiments = [model for model in validated.values() if isinstance(model, ExperimentManifest)]

    assert len(experiments) == 6
    assert all(experiment.prohibited_claims for experiment in experiments)
