"""Tier 1 header-only placeholder and synthetic future-row governance."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from echoes.benchmarks.tier1 import (
    TIER1_CANONICAL_BYTES,
    TIER1_COLUMNS,
    Tier1ValidationError,
    validate_synthetic_tier1_rows,
    validate_tier1_quotations,
)

CANONICAL_PATH = Path("data/benchmarks/tier1_quotations.csv")
CANONICAL_SHA = "7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b"


def test_canonical_tier1_file_is_exact_utf8_header_with_zero_rows() -> None:
    result = validate_tier1_quotations(CANONICAL_PATH, expected_sha256=CANONICAL_SHA)

    assert result.row_count == 0
    assert result.header_only is True
    assert result.columns == TIER1_COLUMNS
    assert result.sha256 == CANONICAL_SHA


@pytest.mark.parametrize(
    "invalid_bytes",
    [
        b"quotation_id,nt_reference\n",
        TIER1_CANONICAL_BYTES + b"   \n",
        TIER1_CANONICAL_BYTES + b"# no data yet\n",
        b"\xef\xbb\xbf" + TIER1_CANONICAL_BYTES,
        TIER1_CANONICAL_BYTES.replace(b",notes\n", b",unnamed,notes\n"),
    ],
    ids=["wrong-columns", "whitespace-row", "comment-row", "bom", "unnamed-column"],
)
def test_noncanonical_or_hidden_rows_fail(tmp_path: Path, invalid_bytes: bytes) -> None:
    path = tmp_path / "tier1.csv"
    path.write_bytes(invalid_bytes)
    digest = hashlib.sha256(invalid_bytes).hexdigest()

    with pytest.raises(Tier1ValidationError, match="exact governed UTF-8 header"):
        validate_tier1_quotations(path, expected_sha256=digest)


def test_manifest_hash_mismatch_fails_before_content_acceptance() -> None:
    with pytest.raises(Tier1ValidationError, match="hash does not match"):
        validate_tier1_quotations(CANONICAL_PATH, expected_sha256="0" * 64)


def _synthetic_row(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "quotation_id": "Q_SYNTHETIC_001",
        "nt_reference": "SYNTHETIC NT 1:1",
        "ot_reference": "SYNTHETIC OT 1:1",
        "ot_source_tradition": "both_or_indeterminate",
        "relationship_class": "direct_quotation_formula_marked",
        "quotation_marker": "synthetic marker",
        "curation_source": "synthetic public-domain fixture",
        "source_public_domain_status": "verified_public_domain",
        "curator": "Fixture Curator",
        "review_status": "pending",
        "notes": "Synthetic metadata only; not biblical evidence.",
    }
    values.update(updates)
    return values


def test_synthetic_future_rows_validate_controlled_values_only() -> None:
    rows = validate_synthetic_tier1_rows(
        [
            _synthetic_row(),
            _synthetic_row(
                quotation_id="Q_SYNTHETIC_002",
                ot_source_tradition="septuagint",
                relationship_class="composite_quotation",
                source_public_domain_status="permission_documented",
                review_status="verified",
            ),
        ]
    )

    assert [row.review_status for row in rows] == ["pending", "verified"]
    assert CANONICAL_PATH.read_bytes() == TIER1_CANONICAL_BYTES


def test_invalid_synthetic_controlled_value_and_duplicate_id_fail() -> None:
    with pytest.raises(Tier1ValidationError, match="invalid synthetic"):
        validate_synthetic_tier1_rows([_synthetic_row(review_status="auto_verified")])
    with pytest.raises(Tier1ValidationError, match="duplicate quotation_id"):
        validate_synthetic_tier1_rows([_synthetic_row(), _synthetic_row()])
