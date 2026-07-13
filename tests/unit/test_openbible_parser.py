from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from echoes.benchmarks.openbible import (
    OPENBIBLE_CANONICAL_STREAM_SCHEMA,
    OpenBibleParseError,
    audit_openbible_source,
    canonical_source_record_stream_sha256,
    parse_openbible_source,
)

HEADER = b"From Verse\tTo Verse\tVotes\t#www.openbible.info CC-BY 2026-07-06\n"


def _write(path: Path, rows: list[bytes], *, newline: bytes = b"\n") -> Path:
    path.write_bytes(HEADER.rstrip(b"\n") + newline + newline.join(rows) + newline)
    return path


def test_parser_preserves_duplicates_reverse_self_negative_and_invalid(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "cross_references.txt",
        [
            b"Gen.1.1\tJohn.1.1\t7",
            b"Gen.1.1\tJohn.1.1\t7",
            b"John.1.1\tGen.1.1\t-2",
            b"Ps.1.1\tPs.1.1\t0",
            b"Gen.1.1\tGen.1.2-Gen.2.1\t3",
            b"Bad",
            b"",
        ],
    )
    parsed = parse_openbible_source(source)
    audit = audit_openbible_source(parsed)

    assert parsed.raw_row_count == 7
    assert parsed.parsed_row_count == 5
    assert parsed.invalid_row_count == 2
    assert audit["exact_duplicate_occurrence_count"] == 1
    assert audit["duplicate_directed_pair_count"] == 1
    assert audit["unique_directed_relationship_count"] == 4
    assert audit["unique_unordered_pair_count"] == 3
    assert audit["reverse_pair_count"] == 1
    assert audit["self_link_count"] == 1
    assert audit["negative_weight_count"] == 1
    assert audit["zero_weight_count"] == 1
    assert audit["reference_kind_counts"] == {"cross_chapter_range": 1, "single": 4}
    assert (
        parsed.records[0].raw_record_sha256 == hashlib.sha256(b"Gen.1.1\tJohn.1.1\t7").hexdigest()
    )
    assert {issue.code for issue in parsed.issues} >= {
        "negative_weight",
        "unexpected_columns",
        "blank_record",
    }


def test_canonical_stream_is_stable_and_schema_versioned(tmp_path: Path) -> None:
    source = _write(tmp_path / "source.tsv", [b"Gen.1.1\tGen.1.2\t1"])
    first = canonical_source_record_stream_sha256(source)
    second = parse_openbible_source(source).canonical_stream_sha256
    assert first == second
    assert len(first) == 64
    with pytest.raises(OpenBibleParseError, match="unsupported"):
        canonical_source_record_stream_sha256(source, schema_version="future-v2")
    assert OPENBIBLE_CANONICAL_STREAM_SCHEMA == "openbible-tsv-v1"


def test_parser_rejects_wrong_header_bom_and_encoding(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.tsv"
    wrong.write_bytes(b"From\tTo\tVotes\nGen.1.1\tGen.1.2\t1\n")
    with pytest.raises(OpenBibleParseError, match="header"):
        parse_openbible_source(wrong)

    bom = tmp_path / "bom.tsv"
    bom.write_bytes(b"\xef\xbb\xbf" + HEADER)
    with pytest.raises(OpenBibleParseError, match="byte-order mark"):
        parse_openbible_source(bom)

    invalid = tmp_path / "invalid.tsv"
    invalid.write_bytes(HEADER + b"Gen.1.1\tGen.1.2\t\xff\n")
    with pytest.raises(OpenBibleParseError, match="valid UTF-8"):
        parse_openbible_source(invalid)


def test_parser_reports_newline_convention_and_final_newline(tmp_path: Path) -> None:
    source = _write(tmp_path / "crlf.tsv", [b"Gen.1.1\tGen.1.2\t1"], newline=b"\r\n")
    parsed = parse_openbible_source(source)
    assert parsed.newline_convention == "crlf"
    assert parsed.final_newline is True


def test_noninteger_weight_is_retained_as_invalid(tmp_path: Path) -> None:
    source = _write(tmp_path / "bad-weight.tsv", [b"Gen.1.1\tGen.1.2\tnope"])
    parsed = parse_openbible_source(source)
    assert parsed.raw_row_count == 1
    assert parsed.invalid_row_count == 1
    assert parsed.records[0].parse_status == "invalid_weight"
    assert any(issue.code == "noninteger_weight" for issue in parsed.issues)
