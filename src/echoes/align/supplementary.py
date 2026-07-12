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
from collections import defaultdict
from typing import Literal

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

STRUCTURAL_ALIGNMENT_SCHEMA = pl.Schema(
    {  # type: ignore[arg-type]  # Polars List stub rejects its own nested dtype
        "ketiv_token_id": pl.String,
        "locus_id": pl.String,
        "analysis_clause_id": pl.String,
        "analysis_sentence_id": pl.String,
        "analysis_phrase_id": pl.String,
        "structural_anchor_token_ids": pl.List(pl.String),
        "alignment_method": pl.String,
        "alignment_confidence": pl.Float64,
        "resolution_status": pl.String,
        "notes": pl.String,
    }
)
STRUCTURAL_ALIGNMENT_COLUMNS: tuple[str, ...] = tuple(STRUCTURAL_ALIGNMENT_SCHEMA)

StructuralFieldStatus = Literal[
    "resolved",
    "missing_anchor",
    "missing_primary_structure",
    "boundary_disagreement",
]


class SupplementaryAnnotationError(ValueError):
    """Raised when a supplementary annotation table violates the beside-not-over rule."""


class StructuralAlignmentError(ValueError):
    """Raised when Ketiv analytical structure cannot be mapped deterministically."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_word_slot(source_word_id: object) -> int:
    try:
        return int(str(source_word_id).rsplit("!", maxsplit=1)[-1])
    except ValueError as exc:
        raise StructuralAlignmentError(
            f"source_word_id does not end in an integer word slot: {source_word_id}"
        ) from exc


def _field_consensus(
    anchors: list[dict[str, object]], field_name: str
) -> tuple[str | None, StructuralFieldStatus]:
    if not anchors:
        return None, "missing_anchor"
    values = [anchor[field_name] for anchor in anchors]
    if any(value is None for value in values):
        return None, "missing_primary_structure"
    unique_values = {str(value) for value in values}
    if len(unique_values) != 1:
        return None, "boundary_disagreement"
    return unique_values.pop(), "resolved"


def build_kq_structural_alignments(
    primary_tokens: pl.DataFrame,
    ketiv_tokens: pl.DataFrame,
    locus_registry: pl.DataFrame,
) -> pl.DataFrame:
    """Map MACULA analytical structure onto OSHB Ketiv tokens without fabrication.

    Paired loci use all MACULA Qere tokens replaced by the Ketiv stream.  A
    sentence, clause, or phrase identifier is assigned only when every anchor
    supplies the same non-null value for that field.  Ketiv-only loci use the
    nearest primary token on each side of the complete Ketiv run, within the
    same verse, and apply the same field-level consensus rule.  Source-native
    structural fields on the OSHB token records remain null.
    """
    primary_required = {
        "token_id",
        "book",
        "chapter",
        "verse",
        "source_word_id",
        "position_in_corpus",
        "sentence_id",
        "clause_id",
        "phrase_id",
    }
    ketiv_required = {"token_id"}
    registry_required = {
        "locus_id",
        "kind",
        "book",
        "chapter",
        "verse",
        "ketiv_word_slots_json",
        "ketiv_token_ids_json",
        "macula_qere_token_ids_json",
        "alignment_confidence",
    }
    for label, frame, required in (
        ("primary token", primary_tokens, primary_required),
        ("Ketiv token", ketiv_tokens, ketiv_required),
        ("locus registry", locus_registry, registry_required),
    ):
        missing = sorted(required - set(frame.columns))
        if missing:
            raise StructuralAlignmentError(f"{label} frame lacks required columns: {missing}")

    paired_anchor_ids: set[str] = set()
    ketiv_only_verse_keys: set[tuple[str, int, int]] = set()
    for registry_row in locus_registry.iter_rows(named=True):
        kind = str(registry_row["kind"])
        if kind == "paired":
            paired_anchor_ids.update(
                str(value) for value in json.loads(registry_row["macula_qere_token_ids_json"])
            )
        elif kind == "ketiv_only":
            ketiv_only_verse_keys.add(
                (
                    str(registry_row["book"]),
                    int(registry_row["chapter"]),
                    int(registry_row["verse"]),
                )
            )

    # Only Qere anchors and the six full-corpus Ketiv-only verses can
    # participate. Filtering in Polars avoids materializing every primary row
    # into Python dictionaries twice during build and validation.
    primary_filter = pl.col("token_id").is_in(sorted(paired_anchor_ids))
    for book, chapter, verse in sorted(ketiv_only_verse_keys):
        primary_filter = primary_filter | (
            (pl.col("book") == book) & (pl.col("chapter") == chapter) & (pl.col("verse") == verse)
        )
    primary_rows = (
        primary_tokens.filter(primary_filter)
        .select(sorted(primary_required))
        .sort("position_in_corpus")
    )
    primary_by_id = {str(row["token_id"]): row for row in primary_rows.iter_rows(named=True)}
    primary_by_verse: dict[tuple[str, int, int], list[dict[str, object]]] = defaultdict(list)
    for row in primary_rows.iter_rows(named=True):
        item = dict(row)
        item["_word_slot"] = _source_word_slot(item["source_word_id"])
        key = (str(item["book"]), int(item["chapter"]), int(item["verse"]))
        primary_by_verse[key].append(item)

    expected_ketiv_ids = set(str(value) for value in ketiv_tokens["token_id"].to_list())
    mapped_ketiv_ids: set[str] = set()
    rows: list[dict[str, object]] = []
    for registry_row in locus_registry.sort("book", "chapter", "verse", "locus_id").iter_rows(
        named=True
    ):
        ketiv_ids = [str(value) for value in json.loads(registry_row["ketiv_token_ids_json"])]
        if not ketiv_ids:
            continue
        duplicate_ids = mapped_ketiv_ids.intersection(ketiv_ids)
        if duplicate_ids:
            raise StructuralAlignmentError(
                f"Ketiv tokens occur in more than one locus: {sorted(duplicate_ids)}"
            )
        mapped_ketiv_ids.update(ketiv_ids)

        kind = str(registry_row["kind"])
        anchor_ids: list[str]
        if kind == "paired":
            anchor_ids = [
                str(value) for value in json.loads(registry_row["macula_qere_token_ids_json"])
            ]
            method = "paired_qere_consensus"
        elif kind == "ketiv_only":
            method = "adjacent_primary_consensus"
            slots = [int(value) for value in json.loads(registry_row["ketiv_word_slots_json"])]
            if not slots:
                raise StructuralAlignmentError(
                    f"{registry_row['locus_id']}: ketiv-only locus has no word slots"
                )
            key = (
                str(registry_row["book"]),
                int(registry_row["chapter"]),
                int(registry_row["verse"]),
            )
            verse_rows = primary_by_verse.get(key, [])
            before = [row for row in verse_rows if int(str(row["_word_slot"])) < min(slots)]
            after = [row for row in verse_rows if int(str(row["_word_slot"])) > max(slots)]
            anchor_ids = []
            if before:
                anchor_ids.append(str(before[-1]["token_id"]))
            if after:
                anchor_ids.append(str(after[0]["token_id"]))
            # A one-sided inference is forbidden.  Preserve the available ID
            # for audit, but treat every structural field as unresolved.
            if not before or not after:
                anchor_rows: list[dict[str, object]] = []
            else:
                anchor_rows = [primary_by_id[token_id] for token_id in anchor_ids]
        else:
            raise StructuralAlignmentError(
                f"{registry_row['locus_id']}: Ketiv tokens have unsupported locus kind {kind}"
            )

        unknown_anchor_ids = sorted(set(anchor_ids) - set(primary_by_id))
        if unknown_anchor_ids:
            raise StructuralAlignmentError(
                f"{registry_row['locus_id']}: unknown structural anchors {unknown_anchor_ids}"
            )
        anchor_ids = sorted(
            anchor_ids, key=lambda token_id: int(primary_by_id[token_id]["position_in_corpus"])
        )
        if kind == "paired":
            anchor_rows = [primary_by_id[token_id] for token_id in anchor_ids]

        clause_id, clause_status = _field_consensus(anchor_rows, "clause_id")
        sentence_id, sentence_status = _field_consensus(anchor_rows, "sentence_id")
        phrase_id, phrase_status = _field_consensus(anchor_rows, "phrase_id")
        field_statuses: dict[str, StructuralFieldStatus] = {
            "analysis_clause_id": clause_status,
            "analysis_sentence_id": sentence_status,
            "analysis_phrase_id": phrase_status,
        }
        resolved_count = sum(status == "resolved" for status in field_statuses.values())
        if resolved_count == len(field_statuses):
            status = "resolved"
        elif resolved_count:
            status = "partially_resolved"
        else:
            status = "unresolved"
        confidence = 0.0
        if resolved_count:
            confidence = float(registry_row["alignment_confidence"])
            if kind == "ketiv_only":
                confidence = min(confidence, 0.75)
        notes = _canonical_json(
            {
                "field_status": field_statuses,
                "locus_id": str(registry_row["locus_id"]),
            }
        )
        for ketiv_id in ketiv_ids:
            rows.append(
                {
                    "ketiv_token_id": ketiv_id,
                    "locus_id": str(registry_row["locus_id"]),
                    "analysis_clause_id": clause_id,
                    "analysis_sentence_id": sentence_id,
                    "analysis_phrase_id": phrase_id,
                    "structural_anchor_token_ids": anchor_ids,
                    "alignment_method": method,
                    "alignment_confidence": confidence,
                    "resolution_status": status,
                    "notes": notes,
                }
            )

    if mapped_ketiv_ids != expected_ketiv_ids:
        missing = sorted(expected_ketiv_ids - mapped_ketiv_ids)
        unexpected = sorted(mapped_ketiv_ids - expected_ketiv_ids)
        raise StructuralAlignmentError(
            f"structural map differs from Ketiv token set; missing={missing[:5]}, "
            f"unexpected={unexpected[:5]}"
        )
    return pl.DataFrame(rows, schema=STRUCTURAL_ALIGNMENT_SCHEMA, orient="row").sort(
        "ketiv_token_id"
    )


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
