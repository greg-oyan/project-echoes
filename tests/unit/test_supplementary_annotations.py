"""Beside-not-over contract tests for supplementary annotation alignment."""

from __future__ import annotations

import polars as pl

from echoes.align.supplementary import (
    STRUCTURAL_ALIGNMENT_COLUMNS,
    SUPPLEMENTARY_ANNOTATION_SCHEMA,
    build_kq_supplementary_annotations,
    validate_supplementary_annotations,
)


def _annotation(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "annotation_id": "syn-1",
        "token_id": "HB_GEN_001_001_0001",
        "field_name": "qere_surface",
        "primary_source_id": "macula-hebrew",
        "primary_value": "אור",
        "supplement_source_id": "oshb-morphhb",
        "supplement_source_version": "3d15126fb1ef74867fc1434be1942e837932691f",
        "supplement_value": "אור",
        "agrees": True,
        "alignment_method": "vacant_slot_adjacency",
        "alignment_confidence": 1.0,
        "notes": "synthetic",
    }
    row.update(overrides)
    return row


def _primary() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "token_id": ["HB_GEN_001_001_0001"],
            "surface_form": ["אור"],
            "lemma": ["אור"],
        }
    )


def _frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SUPPLEMENTARY_ANNOTATION_SCHEMA, orient="row")


def test_clean_annotations_pass() -> None:
    assert validate_supplementary_annotations(_primary(), _frame([_annotation()])) == []


def test_unknown_primary_token_is_rejected() -> None:
    findings = validate_supplementary_annotations(
        _primary(), _frame([_annotation(token_id="HB_GEN_001_001_0099")])
    )

    assert any("unknown primary token" in finding for finding in findings)


def test_overwrite_attempt_via_misquoted_primary_value_fails() -> None:
    # An annotation targeting a real primary column but misquoting its value
    # is an attempted overwrite and must be rejected.
    findings = validate_supplementary_annotations(
        _primary(),
        _frame(
            [
                _annotation(
                    field_name="surface_form",
                    primary_value="something else entirely",
                    supplement_value="something else entirely",
                )
            ]
        ),
    )

    assert any("attempted overwrite is rejected" in finding for finding in findings)


def test_hidden_disagreement_fails() -> None:
    findings = validate_supplementary_annotations(
        _primary(),
        _frame([_annotation(supplement_value="different", agrees=True)]),
    )

    assert any("agrees flag contradicts" in finding for finding in findings)


def test_missing_method_and_bad_confidence_fail() -> None:
    findings = validate_supplementary_annotations(
        _primary(),
        _frame(
            [
                _annotation(annotation_id="syn-a", alignment_method=" "),
                _annotation(annotation_id="syn-b", alignment_confidence=1.5),
            ]
        ),
    )

    assert any("alignment_method is required" in finding for finding in findings)
    assert any("out of range" in finding for finding in findings)


def test_kq_registry_rows_translate_into_annotations(kq_supplement_result) -> None:
    annotations = build_kq_supplementary_annotations(kq_supplement_result.locus_registry)

    # Every qere-bearing locus contributes exactly one qere_surface row.
    qere_bearing = kq_supplement_result.locus_registry.filter(
        pl.col("macula_qere_token_ids_json") != "[]"
    )
    assert annotations.height == qere_bearing.height
    disagreeing = annotations.filter(~pl.col("agrees"))
    assert disagreeing.height == 2  # the synthetic mismatch and consonantal loci
    assert set(annotations["alignment_method"].to_list()) == {"vacant_slot_adjacency"}


def test_kq_structural_map_has_governed_schema_and_one_row_per_ketiv(
    kq_supplement_result,
) -> None:
    structure = kq_supplement_result.structural_alignments

    assert tuple(structure.columns) == STRUCTURAL_ALIGNMENT_COLUMNS
    assert structure.height == kq_supplement_result.ketiv_tokens.height
    assert structure["ketiv_token_id"].n_unique() == structure.height
    assert structure["structural_anchor_token_ids"].dtype == pl.List(pl.String)
