"""Versification-crosswalk schema tests over synthetic fixtures (no data rows ship)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
import yaml

import echoes.align.versification as versification
from echoes.align.versification import (
    CrosswalkValidationError,
    VersificationCrosswalk,
    load_versification_crosswalk,
)


def _document(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_scheme": "synthetic-edition-a",
        "target_scheme": "synthetic-edition-b",
        "provenance": "synthetic fixture for schema validation only",
        "rows": rows,
    }


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "crosswalk_id": "vx-syn-0001",
        "source_references": ["PSA 51:1"],
        "target_references": ["PSA 50:3"],
        "mapping_type": "one_to_one",
        "alignment_method": "published_crosswalk_table",
        "alignment_confidence": 0.95,
        "notes": None,
    }
    row.update(overrides)
    return row


def _write(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "crosswalk.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_empty_crosswalk_with_no_data_rows_validates(tmp_path: Path) -> None:
    crosswalk = load_versification_crosswalk(_write(tmp_path, _document([])))

    assert isinstance(crosswalk, VersificationCrosswalk)
    assert crosswalk.rows == []


def test_every_mapping_cardinality_is_representable(tmp_path: Path) -> None:
    rows = [
        _row(crosswalk_id="vx-syn-0001"),
        _row(
            crosswalk_id="vx-syn-0002",
            mapping_type="one_to_many",
            target_references=["PSA 50:1", "PSA 50:2"],
        ),
        _row(
            crosswalk_id="vx-syn-0003",
            mapping_type="many_to_one",
            source_references=["PSA 51:1", "PSA 51:2"],
            target_references=["PSA 50:1"],
        ),
        _row(
            crosswalk_id="vx-syn-0004",
            mapping_type="unmatched_source",
            target_references=[],
        ),
        _row(
            crosswalk_id="vx-syn-0005",
            mapping_type="addition_in_target",
            source_references=[],
            target_references=["PSA 151:1"],
        ),
        _row(
            crosswalk_id="vx-syn-0006",
            mapping_type="alternate_structure",
            source_references=["JOL 3:1"],
            target_references=["JOL 2:28"],
            alignment_method="manual",
            alignment_confidence=0.7,
        ),
    ]
    crosswalk = load_versification_crosswalk(_write(tmp_path, _document(rows)))

    assert len(crosswalk.rows) == 6


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"alignment_confidence": 1.5}, "less than or equal to 1"),
        ({"alignment_confidence": -0.1}, "greater than or equal to 0"),
        ({"alignment_method": "guesswork"}, "alignment_method"),
        ({"mapping_type": "identity"}, "mapping_type"),
        ({"source_references": ["Psalm fifty-one"]}, "malformed edition reference"),
        (
            {"mapping_type": "one_to_many", "target_references": ["PSA 50:3"]},
            "one_to_many requires",
        ),
        (
            {"mapping_type": "unmatched_source"},
            "unmatched_source requires",
        ),
        ({"crosswalk_id": "NOT-VALID"}, "crosswalk_id"),
    ],
)
def test_invalid_rows_fail_validation(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(CrosswalkValidationError, match=message):
        load_versification_crosswalk(_write(tmp_path, _document([_row(**overrides)])))


def test_duplicate_row_ids_fail(tmp_path: Path) -> None:
    with pytest.raises(CrosswalkValidationError, match="duplicate crosswalk_id"):
        load_versification_crosswalk(_write(tmp_path, _document([_row(), _row()])))


def test_identical_schemes_fail(tmp_path: Path) -> None:
    document = _document([])
    document["target_scheme"] = document["source_scheme"]

    with pytest.raises(CrosswalkValidationError, match="must differ"):
        load_versification_crosswalk(_write(tmp_path, document))


def test_missing_alignment_method_fails(tmp_path: Path) -> None:
    row = _row()
    del row["alignment_method"]

    with pytest.raises(CrosswalkValidationError, match="alignment_method"):
        load_versification_crosswalk(_write(tmp_path, _document([row])))


def test_crosswalk_module_never_touches_token_identity() -> None:
    tree = ast.parse(inspect.getsource(versification))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any("token_ids" in module for module in imported_modules)
    assert not any("ingest" in module for module in imported_modules)
