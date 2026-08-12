"""Standalone post-M7 positive-control governance and leakage tests."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from echoes.benchmarks.positive_controls import (
    POSITIVE_CONTROL_COLUMNS,
    PositiveControlError,
    PositiveControlSplitConfig,
    build_positive_control_id,
    deterministic_leakage_group_splits,
    validate_positive_controls,
)
from echoes.manifests.sources import SourceStatus, load_source_catalog

CONFIG_PATH = Path("data/benchmarks/positive_controls.yaml")
DATA_PATH = Path("data/benchmarks/positive_controls.csv")


def _raw_rows() -> list[dict[str, str]]:
    with DATA_PATH.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, strict=True))


def _validated_mutation(
    tmp_path: Path,
    mutate: Any,
) -> tuple[Path, Path]:
    rows = _raw_rows()
    mutate(rows)
    data_path = tmp_path / "positive_controls.csv"
    with data_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POSITIVE_CONTROL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    values = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    values["dataset"]["sha256"] = hashlib.sha256(data_path.read_bytes()).hexdigest()
    config_path = tmp_path / "positive_controls.yaml"
    config_path.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    return config_path, data_path


def test_tracked_positive_controls_validate_as_separate_reference_only_data() -> None:
    dataset = validate_positive_controls(CONFIG_PATH)

    assert dataset.validation.row_count == 24
    assert dataset.validation.relationship_family_count == 8
    assert dataset.validation.leakage_group_count == 8
    assert dataset.validation.partition_counts == {
        "train": 15,
        "development": 3,
        "test": 6,
    }
    assert {row.corpus_pair for row in dataset.rows} == {
        "hebrew_hebrew",
        "greek_greek",
        "hebrew_greek",
    }
    assert all(row.quotation_formula_status == "not_assessed" for row in dataset.rows)
    assert not {"surface", "text", "gloss", "alignment"}.intersection(POSITIVE_CONTROL_COLUMNS)


def test_ubs_source_manifest_matches_positive_control_pin() -> None:
    dataset = validate_positive_controls(CONFIG_PATH)
    source = load_source_catalog(Path("data/manifests/sources.yaml")).find(
        dataset.config.source.source_id
    )

    assert source is not None
    assert source.status is SourceStatus.APPROVED
    assert source.version_or_commit == dataset.config.source.source_version
    assert (
        source.file_hashes[dataset.config.source.source_file]
        == dataset.config.source.source_file_sha256
    )
    assert source.machine_processing_status.value == "permitted"
    assert source.redistribution_status.value == "permitted"


def test_pair_ids_and_group_splits_are_input_order_independent() -> None:
    first = build_positive_control_id(
        benchmark_id="final-discovery-positive-controls-v1",
        source_reference_scheme="ubs-paratext-canonical-v1",
        reference_a="GEN 2:24",
        reference_b="MAT 19:5",
    )
    reversed_pair = build_positive_control_id(
        benchmark_id="final-discovery-positive-controls-v1",
        source_reference_scheme="ubs-paratext-canonical-v1",
        reference_a="MAT 19:5",
        reference_b="GEN 2:24",
    )
    split_config = PositiveControlSplitConfig.model_validate(
        {
            "algorithm": "sha256_ordered_weighted_cycle_v1",
            "seed": 8171,
            "partition_unit": "leakage_group",
            "random_row_splitting_allowed": False,
            "weights": {"train": 3, "development": 1, "test": 1},
        }
    )
    groups = {"PCL_A", "PCL_B", "PCL_C", "PCL_D", "PCL_E"}

    assert first == reversed_pair
    assert deterministic_leakage_group_splits(
        groups,
        benchmark_id="final-discovery-positive-controls-v1",
        split_config=split_config,
    ) == deterministic_leakage_group_splits(
        set(reversed(sorted(groups))),
        benchmark_id="final-discovery-positive-controls-v1",
        split_config=split_config,
    )


def test_hash_authentication_rejects_unregistered_csv_bytes(tmp_path: Path) -> None:
    changed = tmp_path / "positive_controls.csv"
    changed.write_bytes(DATA_PATH.read_bytes().replace(b"Pinned XML", b"Changed XML", 1))

    with pytest.raises(PositiveControlError, match="CSV hash differs"):
        validate_positive_controls(CONFIG_PATH, data_path=changed)


def test_content_derived_control_id_is_enforced(tmp_path: Path) -> None:
    def mutate(rows: list[dict[str, str]]) -> None:
        rows[0]["control_id"] = "PC_" + "0" * 64

    config_path, data_path = _validated_mutation(tmp_path, mutate)
    with pytest.raises(PositiveControlError, match="content-derived control_id mismatch"):
        validate_positive_controls(config_path, data_path=data_path)


def test_shared_reference_cannot_cross_leakage_groups(tmp_path: Path) -> None:
    def mutate(rows: list[dict[str, str]]) -> None:
        target = next(row for row in rows if row["relationship_family_id"] == "PCF_LAW_IN_KINGS")
        target["reference_a"] = "GEN 1:27"
        target["control_id"] = build_positive_control_id(
            benchmark_id="final-discovery-positive-controls-v1",
            source_reference_scheme="ubs-paratext-canonical-v1",
            reference_a=target["reference_a"],
            reference_b=target["reference_b"],
        )

    config_path, data_path = _validated_mutation(tmp_path, mutate)
    with pytest.raises(PositiveControlError, match="references cross"):
        validate_positive_controls(config_path, data_path=data_path)


def test_whole_leakage_group_must_keep_its_frozen_split(tmp_path: Path) -> None:
    def mutate(rows: list[dict[str, str]]) -> None:
        rows[0]["split"] = "development"

    config_path, data_path = _validated_mutation(tmp_path, mutate)
    with pytest.raises(PositiveControlError, match="leakage groups cross split"):
        validate_positive_controls(config_path, data_path=data_path)


def test_row_level_source_provenance_cannot_drift(tmp_path: Path) -> None:
    def mutate(rows: list[dict[str, str]]) -> None:
        rows[0]["source_version"] = "0" * 40

    config_path, data_path = _validated_mutation(tmp_path, mutate)
    with pytest.raises(PositiveControlError, match="row-level source provenance"):
        validate_positive_controls(config_path, data_path=data_path)
