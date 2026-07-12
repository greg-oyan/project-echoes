"""Generalized supplementary annotation-alignment tables (master plan 10.4).

Supplementary values are stored *beside* primary annotations with per-value
source attribution, alignment method, and confidence.  A supplement can only
record what the primary says and what it says itself; it can never rewrite
the primary.  Validation enforces exactly that: every row must reference a
real primary token, must faithfully quote the primary value it sits beside,
and must mark disagreement rather than hide it.  The OSHB Ketiv/Qere layer is
the first tenant.
"""

from __future__ import annotations

import json

import polars as pl

SUPPLEMENTARY_ANNOTATION_SCHEMA = {
    "annotation_id": pl.String,
    "token_id": pl.String,
    "field_name": pl.String,
    "primary_source_id": pl.String,
    "primary_value": pl.String,
    "supplement_source_id": pl.String,
    "supplement_source_version": pl.String,
    "supplement_value": pl.String,
    "agrees": pl.Boolean,
    "alignment_method": pl.String,
    "alignment_confidence": pl.Float64,
    "notes": pl.String,
}
SUPPLEMENTARY_ANNOTATION_COLUMNS: tuple[str, ...] = tuple(SUPPLEMENTARY_ANNOTATION_SCHEMA)


class SupplementaryAnnotationError(ValueError):
    """Raised when a supplementary annotation table violates the beside-not-over rule."""


def build_kq_supplementary_annotations(locus_registry: pl.DataFrame) -> pl.DataFrame:
    """Derive per-value annotation rows from the K/Q locus registry.

    Each qere-bearing locus contributes one ``qere_surface`` row anchored to
    the first referenced MACULA qere token: the primary's own surface beside
    OSHB's reading of the same slot, with agreement, method, and confidence.
    """
    rows: list[dict[str, object]] = []
    for row in locus_registry.iter_rows(named=True):
        qere_token_ids = json.loads(str(row["macula_qere_token_ids_json"]))
        if not qere_token_ids:
            continue
        tier = str(row["surface_match_tier"])
        rows.append(
            {
                "annotation_id": f"{row['locus_id']}:qere_surface",
                "token_id": qere_token_ids[0],
                "field_name": "qere_surface",
                "primary_source_id": "macula-hebrew",
                "primary_value": row["macula_qere_surface"],
                "supplement_source_id": row["source_id"],
                "supplement_source_version": row["source_version"],
                "supplement_value": row["oshb_qere_surface"],
                "agrees": tier == "exact",
                "alignment_method": row["alignment_method"],
                "alignment_confidence": row["alignment_confidence"],
                "notes": f"surface_match_tier={tier}; locus kind={row['kind']}",
            }
        )
    return pl.DataFrame(rows, schema=SUPPLEMENTARY_ANNOTATION_SCHEMA, orient="row")


def validate_supplementary_annotations(
    primary_tokens: pl.DataFrame,
    annotations: pl.DataFrame,
) -> list[str]:
    """Return violations of the beside-not-over contract (empty when clean).

    Checks:

    - every annotation references an existing primary token;
    - the quoted ``primary_value`` matches what the primary table actually
      says where the field is a primary column (an annotation that
      misquotes the primary is an attempted overwrite);
    - ``agrees`` is true exactly when the two values are equal;
    - alignment method is present and confidence lies in [0, 1];
    - annotation IDs are unique.
    """
    findings: list[str] = []
    if annotations.height == 0:
        return findings
    if set(annotations.columns) != set(SUPPLEMENTARY_ANNOTATION_COLUMNS):
        return ["annotation columns differ from the governed schema"]
    if annotations["annotation_id"].n_unique() != annotations.height:
        findings.append("duplicate annotation_id values")

    primary_ids = set(primary_tokens["token_id"].to_list())
    primary_columns = set(primary_tokens.columns)
    primary_by_id: dict[str, dict[str, object]] | None = None

    for row in annotations.iter_rows(named=True):
        annotation_id = row["annotation_id"]
        token_id = str(row["token_id"])
        if token_id not in primary_ids:
            findings.append(f"{annotation_id}: references unknown primary token {token_id}")
            continue
        field_name = str(row["field_name"])
        if field_name in primary_columns:
            if primary_by_id is None:
                primary_by_id = {str(item["token_id"]): item for item in primary_tokens.to_dicts()}
            actual = primary_by_id[token_id].get(field_name)
            if (actual or "") != (row["primary_value"] or ""):
                findings.append(
                    f"{annotation_id}: quoted primary_value misrepresents the primary "
                    f"table (attempted overwrite is rejected)"
                )
        primary_value = row["primary_value"] or ""
        supplement_value = row["supplement_value"] or ""
        if bool(row["agrees"]) != (primary_value == supplement_value):
            findings.append(f"{annotation_id}: agrees flag contradicts the stored values")
        if not str(row["alignment_method"] or "").strip():
            findings.append(f"{annotation_id}: alignment_method is required")
        confidence = float(row["alignment_confidence"])
        if not 0.0 <= confidence <= 1.0:
            findings.append(f"{annotation_id}: alignment_confidence {confidence} out of range")
    return findings
