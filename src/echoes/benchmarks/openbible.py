"""Strict parsing and canonical hashing for the governed OpenBible TSV snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

OPENBIBLE_CANONICAL_STREAM_SCHEMA: Final = "openbible-tsv-v1"
OPENBIBLE_HEADER: Final = (
    "From Verse",
    "To Verse",
    "Votes",
    "#www.openbible.info CC-BY 2026-07-06",
)
REFERENCE_RE: Final = re.compile(
    rb"^[1-3]?[A-Za-z]+\.[1-9][0-9]*\.[1-9][0-9]*"
    rb"(?:-[1-3]?[A-Za-z]+\.[1-9][0-9]*\.[1-9][0-9]*)?$"
)


class OpenBibleParseError(ValueError):
    """Raised when source-level invariants prevent a governed parse."""


@dataclass(frozen=True, slots=True)
class OpenBibleParseIssue:
    """One explicit source parsing or structural finding."""

    severity: Literal["error", "warning", "informational"]
    code: str
    message: str
    source_line_number: int | None = None


@dataclass(frozen=True, slots=True)
class OpenBibleSourceRecord:
    """One physical post-header record, including malformed and blank rows."""

    source_line_number: int
    raw_record_bytes: bytes
    raw_record_sha256: str
    source_reference_a: str
    source_reference_b: str
    source_weight: int | None
    source_direction: str
    parse_status: str
    notes: str


@dataclass(frozen=True, slots=True)
class OpenBibleParseResult:
    """Reconciled source parse plus audit observations."""

    path: Path
    header: tuple[str, ...]
    records: tuple[OpenBibleSourceRecord, ...]
    issues: tuple[OpenBibleParseIssue, ...]
    encoding: str
    byte_order_mark: str
    newline_convention: str
    final_newline: bool
    canonical_stream_sha256: str

    @property
    def raw_row_count(self) -> int:
        return len(self.records)

    @property
    def parsed_row_count(self) -> int:
        return sum(record.parse_status == "parsed" for record in self.records)

    @property
    def invalid_row_count(self) -> int:
        return self.raw_row_count - self.parsed_row_count


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_source_record_bytes(record: OpenBibleSourceRecord) -> bytes:
    """Return the versioned canonical representation of one parsed source row."""

    return _canonical_json(
        {
            "notes": record.notes,
            "parse_status": record.parse_status,
            "raw_record_sha256": record.raw_record_sha256,
            "source_direction": record.source_direction,
            "source_reference_a": record.source_reference_a,
            "source_reference_b": record.source_reference_b,
            "source_weight": record.source_weight,
        }
    )


def _hash_canonical_records(records: Iterable[OpenBibleSourceRecord]) -> str:
    digest = hashlib.sha256()
    digest.update(b"project-echoes:openbible-canonical-stream:openbible-tsv-v1\0")
    for record in records:
        payload = canonical_source_record_bytes(record)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _split_binary_lines(data: bytes) -> tuple[list[bytes], str, bool]:
    crlf = data.count(b"\r\n")
    bare_lf = data.count(b"\n") - crlf
    bare_cr = data.count(b"\r") - crlf
    conventions = sum(value > 0 for value in (crlf, bare_lf, bare_cr))
    if conventions > 1:
        newline = "mixed"
    elif crlf:
        newline = "crlf"
    elif bare_lf:
        newline = "lf"
    elif bare_cr:
        newline = "cr"
    else:
        newline = "none"
    final_newline = data.endswith((b"\n", b"\r"))
    return data.splitlines(), newline, final_newline


def _decode_field(value: bytes) -> str:
    return value.decode("utf-8", errors="strict")


def _parse_record(
    raw: bytes, line_number: int
) -> tuple[OpenBibleSourceRecord, list[OpenBibleParseIssue]]:
    issues: list[OpenBibleParseIssue] = []
    reference_a = ""
    reference_b = ""
    weight: int | None = None
    status = "parsed"
    notes: list[str] = []

    if not raw:
        status = "invalid_blank_record"
        notes.append("blank source record")
        issues.append(
            OpenBibleParseIssue("error", "blank_record", "source record is blank", line_number)
        )
    else:
        fields = raw.split(b"\t")
        if len(fields) != 3:
            status = "invalid_column_count"
            notes.append(f"expected 3 TSV fields; observed {len(fields)}")
            issues.append(
                OpenBibleParseIssue(
                    "error",
                    "unexpected_columns",
                    f"expected 3 TSV fields; observed {len(fields)}",
                    line_number,
                )
            )
        else:
            try:
                reference_a = _decode_field(fields[0])
                reference_b = _decode_field(fields[1])
                weight_text = _decode_field(fields[2])
            except UnicodeDecodeError:
                status = "invalid_encoding"
                notes.append("record is not valid UTF-8")
                issues.append(
                    OpenBibleParseIssue(
                        "error", "invalid_encoding", "record is not valid UTF-8", line_number
                    )
                )
            else:
                if not reference_a or not reference_b:
                    status = "invalid_empty_reference"
                    notes.append("one or more reference fields are empty")
                    issues.append(
                        OpenBibleParseIssue(
                            "error",
                            "empty_reference",
                            "one or more reference fields are empty",
                            line_number,
                        )
                    )
                elif not REFERENCE_RE.fullmatch(fields[0]) or not REFERENCE_RE.fullmatch(fields[1]):
                    status = "invalid_reference_syntax"
                    notes.append("reference does not match Book.Chapter.Verse syntax")
                    issues.append(
                        OpenBibleParseIssue(
                            "error",
                            "invalid_reference_syntax",
                            "reference does not match Book.Chapter.Verse syntax",
                            line_number,
                        )
                    )
                try:
                    weight = int(weight_text)
                except (UnboundLocalError, ValueError):
                    status = "invalid_weight"
                    notes.append("weight is not a signed decimal integer")
                    issues.append(
                        OpenBibleParseIssue(
                            "error",
                            "noninteger_weight",
                            "weight is not a signed decimal integer",
                            line_number,
                        )
                    )
                else:
                    if weight < 0:
                        issues.append(
                            OpenBibleParseIssue(
                                "informational",
                                "negative_weight",
                                "source ranking vote is negative",
                                line_number,
                            )
                        )

    return (
        OpenBibleSourceRecord(
            source_line_number=line_number,
            raw_record_bytes=raw,
            raw_record_sha256=hashlib.sha256(raw).hexdigest(),
            source_reference_a=reference_a,
            source_reference_b=reference_b,
            source_weight=weight,
            source_direction="a_to_b",
            parse_status=status,
            notes="; ".join(notes),
        ),
        issues,
    )


def parse_openbible_source(
    path: Path,
    *,
    schema_version: str = OPENBIBLE_CANONICAL_STREAM_SCHEMA,
) -> OpenBibleParseResult:
    """Parse every physical source row without silent loss."""

    if schema_version != OPENBIBLE_CANONICAL_STREAM_SCHEMA:
        raise OpenBibleParseError(f"unsupported OpenBible canonical schema: {schema_version}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise OpenBibleParseError(f"could not read OpenBible source {path}: {exc}") from exc
    if not data:
        raise OpenBibleParseError("OpenBible source is empty")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        bom = "utf-16"
    elif data.startswith(b"\xef\xbb\xbf"):
        bom = "utf-8"
    else:
        bom = "none"
    if bom != "none":
        raise OpenBibleParseError(f"unexpected OpenBible byte-order mark: {bom}")
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise OpenBibleParseError("OpenBible source is not valid UTF-8") from exc

    lines, newline, final_newline = _split_binary_lines(data)
    if not lines:
        raise OpenBibleParseError("OpenBible source has no header")
    try:
        header = tuple(part.decode("utf-8") for part in lines[0].split(b"\t"))
    except UnicodeDecodeError as exc:  # pragma: no cover - whole-file validation precedes this
        raise OpenBibleParseError("OpenBible header is not valid UTF-8") from exc
    if header != OPENBIBLE_HEADER:
        raise OpenBibleParseError(
            f"unexpected OpenBible header: expected {OPENBIBLE_HEADER!r}, observed {header!r}"
        )

    issues: list[OpenBibleParseIssue] = []
    records: list[OpenBibleSourceRecord] = []
    for line_number, raw in enumerate(lines[1:], start=2):
        record, record_issues = _parse_record(raw, line_number)
        records.append(record)
        issues.extend(record_issues)
    if len(records) != max(0, len(lines) - 1):  # pragma: no cover - defensive reconciliation
        raise OpenBibleParseError("unexplained OpenBible row loss")

    return OpenBibleParseResult(
        path=path,
        header=header,
        records=tuple(records),
        issues=tuple(issues),
        encoding="utf-8",
        byte_order_mark=bom,
        newline_convention=newline,
        final_newline=final_newline,
        canonical_stream_sha256=_hash_canonical_records(records),
    )


def canonical_source_record_stream_sha256(
    path: Path,
    *,
    schema_version: str = OPENBIBLE_CANONICAL_STREAM_SCHEMA,
) -> str:
    """Recompute the exact governed parsed-stream digest for offline verification."""

    return parse_openbible_source(path, schema_version=schema_version).canonical_stream_sha256


def _reference_kind(reference: str) -> str:
    if "-" not in reference:
        return "single"
    first, second = reference.split("-", maxsplit=1)
    first_book, first_chapter, _ = first.split(".")
    second_book, second_chapter, _ = second.split(".")
    if first_book != second_book:
        return "cross_book_range"
    if first_chapter != second_chapter:
        return "cross_chapter_range"
    return "same_chapter_range"


def audit_openbible_source(result: OpenBibleParseResult) -> dict[str, object]:
    """Return sanitized structural statistics without exposing bulk source rows."""

    valid = [record for record in result.records if record.parse_status == "parsed"]
    raw_counts = Counter(record.raw_record_sha256 for record in valid)
    pair_records: dict[tuple[str, str], list[OpenBibleSourceRecord]] = defaultdict(list)
    for record in valid:
        pair_records[(record.source_reference_a, record.source_reference_b)].append(record)
    pairs = set(pair_records)
    unordered = {tuple(sorted(pair)) for pair in pairs}
    reverse_unordered = {
        tuple(sorted(pair)) for pair in pairs if pair[0] != pair[1] and (pair[1], pair[0]) in pairs
    }
    conflicting = sum(
        len({record.source_weight for record in records}) > 1 for records in pair_records.values()
    )
    weights = sorted(record.source_weight for record in valid if record.source_weight is not None)

    def quantile(index: float) -> int | None:
        if not weights:
            return None
        return weights[round((len(weights) - 1) * index)]

    return {
        "canonical_stream_sha256": result.canonical_stream_sha256,
        "raw_row_count": result.raw_row_count,
        "parsed_row_count": result.parsed_row_count,
        "invalid_row_count": result.invalid_row_count,
        "exact_duplicate_occurrence_count": sum(count - 1 for count in raw_counts.values()),
        "duplicate_directed_pair_count": sum(len(records) - 1 for records in pair_records.values()),
        "conflicting_weight_pair_count": conflicting,
        "unique_directed_relationship_count": len(pairs),
        "unique_unordered_pair_count": len(unordered),
        "reverse_pair_count": len(reverse_unordered),
        "self_link_count": sum(a == b for a, b in pairs),
        "negative_weight_count": sum(weight < 0 for weight in weights),
        "zero_weight_count": sum(weight == 0 for weight in weights),
        "positive_weight_count": sum(weight > 0 for weight in weights),
        "weight_min": weights[0] if weights else None,
        "weight_q1": quantile(0.25),
        "weight_median": quantile(0.50),
        "weight_q3": quantile(0.75),
        "weight_max": weights[-1] if weights else None,
        "distinct_weight_count": len(set(weights)),
        "reference_kind_counts": dict(
            sorted(Counter(_reference_kind(record.source_reference_b) for record in valid).items())
        ),
        "newline_convention": result.newline_convention,
        "final_newline": result.final_newline,
        "encoding": result.encoding,
        "byte_order_mark": result.byte_order_mark,
    }
