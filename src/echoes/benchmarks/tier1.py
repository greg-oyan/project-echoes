"""Strict Tier 1 placeholder validation and future human-row contracts."""

from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

TIER1_COLUMNS: tuple[str, ...] = (
    "quotation_id",
    "nt_reference",
    "ot_reference",
    "ot_source_tradition",
    "relationship_class",
    "quotation_marker",
    "curation_source",
    "source_public_domain_status",
    "curator",
    "review_status",
    "notes",
)
TIER1_HEADER = ",".join(TIER1_COLUMNS)
TIER1_CANONICAL_BYTES = (TIER1_HEADER + "\n").encode("utf-8")
TIER1_SCHEMA_VERSION = 1


class Tier1ValidationError(ValueError):
    """Raised when Tier 1 schema or future row governance is violated."""


class Tier1QuotationRow(BaseModel):
    """Controlled future row contract; scripts may never mark rows verified."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    quotation_id: str = Field(pattern=r"^Q_[A-Z0-9]+(?:_[A-Z0-9]+)*$")
    nt_reference: str = Field(min_length=1)
    ot_reference: str = Field(min_length=1)
    ot_source_tradition: Literal[
        "hebrew",
        "septuagint",
        "both_or_indeterminate",
        "other_named_witness",
        "unresolved",
    ]
    relationship_class: Literal[
        "direct_quotation_formula_marked",
        "direct_quotation_unmarked",
        "composite_quotation",
        "adapted_direct_quotation",
        "ambiguous",
    ]
    quotation_marker: str
    curation_source: str = Field(min_length=1)
    source_public_domain_status: Literal[
        "verified_public_domain",
        "compatible_license_documented",
        "permission_documented",
        "unresolved",
    ]
    curator: str = Field(min_length=1)
    review_status: Literal["pending", "needs_adjudication", "verified", "ambiguous", "rejected"]
    notes: str = Field(min_length=1)


class Tier1ValidationResult(BaseModel):
    """Machine-readable evidence that the tracked placeholder remains empty."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    columns: tuple[str, ...]
    row_count: Literal[0]
    header_only: Literal[True]


def validate_tier1_quotations(
    path: Path,
    *,
    expected_sha256: str,
) -> Tier1ValidationResult:
    """Require the canonical UTF-8, LF-terminated header and exactly zero rows."""

    if not path.is_file():
        raise Tier1ValidationError(f"Tier 1 quotation file does not exist: {path}")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise Tier1ValidationError(f"could not read Tier 1 quotation file {path}: {exc}") from exc

    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256.lower():
        raise Tier1ValidationError(
            "Tier 1 quotation file hash does not match the governed manifest: "
            f"expected={expected_sha256.lower()}, actual={actual_sha256}"
        )
    if raw != TIER1_CANONICAL_BYTES:
        raise Tier1ValidationError(
            "Tier 1 quotation file must contain only the exact governed UTF-8 header"
        )

    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    if not rows or tuple(rows[0]) != TIER1_COLUMNS:
        raise Tier1ValidationError("Tier 1 quotation columns or column order are invalid")
    if len(rows) != 1:
        raise Tier1ValidationError("Tier 1 quotation placeholder must have exactly zero data rows")
    return Tier1ValidationResult(
        path=path.as_posix(),
        sha256=actual_sha256,
        columns=TIER1_COLUMNS,
        row_count=0,
        header_only=True,
    )


def validate_synthetic_tier1_rows(
    rows: list[dict[str, object]],
) -> list[Tier1QuotationRow]:
    """Validate controlled future values in tests without populating the CSV."""

    try:
        validated = [Tier1QuotationRow.model_validate(row) for row in rows]
    except ValidationError as exc:
        raise Tier1ValidationError(f"invalid synthetic Tier 1 row:\n{exc}") from exc
    ids = [row.quotation_id for row in validated]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise Tier1ValidationError(f"duplicate quotation_id values: {duplicates}")
    return validated
