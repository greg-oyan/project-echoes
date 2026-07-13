"""Governed benchmark configuration and rejection cases."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from echoes.settings import BenchmarkConfig, load_config, validate_config_directory

CONFIG_PATH = Path("config/benchmark.yaml")


def _raw_config() -> dict[str, Any]:
    loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return copy.deepcopy(loaded)


def test_production_benchmark_config_and_directory_validate() -> None:
    config = load_config(CONFIG_PATH)
    assert isinstance(config, BenchmarkConfig)
    assert config.sources.openbible.tier == 3
    assert config.sources.tier1.expected_current_row_count == 0
    assert CONFIG_PATH in validate_config_directory(Path("config"))


def _openbible_tier_one(values: dict[str, Any]) -> None:
    values["sources"]["openbible"]["tier"] = 1


def _openbible_primary(values: dict[str, Any]) -> None:
    values["sources"]["openbible"]["primary_evaluation_eligible"] = True


def _automatic_tier1_population(values: dict[str, Any]) -> None:
    values["sources"]["tier1"]["automated_population_allowed"] = True


def _automated_verified(values: dict[str, Any]) -> None:
    values["sources"]["tier1"]["automated_verification_allowed"] = True


def _unlicensed_activation(values: dict[str, Any]) -> None:
    values["sources"]["openbible"]["license_status"] = "unverified"


def _random_row_split(values: dict[str, Any]) -> None:
    values["splits"][0]["random_row_splitting_allowed"] = True


def _proven_negative(values: dict[str, Any]) -> None:
    values["presumed_negatives"][0]["label"] = "proven_negative"


def _silent_mapping(values: dict[str, Any]) -> None:
    values["mapping"]["silent_reference_mapping_allowed"] = True


def _silent_symmetrization(values: dict[str, Any]) -> None:
    values["relationship_policies"]["silent_symmetrization_allowed"] = True


def _missing_snapshot_hash(values: dict[str, Any]) -> None:
    del values["sources"]["openbible"]["snapshot_sha256"]


def _missing_source_scheme(values: dict[str, Any]) -> None:
    del values["sources"]["openbible"]["source_reference_scheme"]


def _missing_leakage_strategy(values: dict[str, Any]) -> None:
    values["leakage"]["group_types"].remove("shared_endpoint")


def _unsupported_metric(values: dict[str, Any]) -> None:
    values["metrics"]["metrics"][0] = "accuracy"


def _bad_split_proportions(values: dict[str, Any]) -> None:
    values["splits"][0]["proportions"] = {
        "train": 0.7,
        "development": 0.1,
        "test": 0.1,
    }


def _duplicate_split_name(values: dict[str, Any]) -> None:
    values["splits"][1]["name"] = values["splits"][0]["name"]


def _duplicate_split_seed(values: dict[str, Any]) -> None:
    values["splits"][1]["seed"] = values["splits"][0]["seed"]


def _populated_tier1(values: dict[str, Any]) -> None:
    values["sources"]["tier1"]["expected_current_row_count"] = 1


@pytest.mark.parametrize(
    "mutation",
    [
        _openbible_tier_one,
        _openbible_primary,
        _automatic_tier1_population,
        _automated_verified,
        _unlicensed_activation,
        _random_row_split,
        _proven_negative,
        _silent_mapping,
        _silent_symmetrization,
        _missing_snapshot_hash,
        _missing_source_scheme,
        _missing_leakage_strategy,
        _unsupported_metric,
        _bad_split_proportions,
        _duplicate_split_name,
        _duplicate_split_seed,
        _populated_tier1,
    ],
    ids=lambda mutation: mutation.__name__.removeprefix("_"),
)
def test_explicit_unsafe_configurations_fail(
    mutation: Any,
) -> None:
    values = _raw_config()
    mutation(values)

    with pytest.raises(ValidationError):
        BenchmarkConfig.model_validate(values)
