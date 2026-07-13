"""OpenBible source-scheme reference parsing without implicit crosswalk claims."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

OPENBIBLE_REFERENCE_SCHEME = "openbible-english-protestant-v1"

# Exact OSIS-style identifiers observed in the OpenBible graph.  Canonical
# Project Echoes codes remain a separate target namespace.
_OPENBIBLE_ALIAS_ITEMS: tuple[tuple[str, str], ...] = (
    ("Gen", "GEN"),
    ("Exod", "EXO"),
    ("Lev", "LEV"),
    ("Num", "NUM"),
    ("Deut", "DEU"),
    ("Josh", "JOS"),
    ("Judg", "JDG"),
    ("Ruth", "RUT"),
    ("1Sam", "1SA"),
    ("2Sam", "2SA"),
    ("1Kgs", "1KI"),
    ("2Kgs", "2KI"),
    ("1Chr", "1CH"),
    ("2Chr", "2CH"),
    ("Ezra", "EZR"),
    ("Neh", "NEH"),
    ("Esth", "EST"),
    ("Job", "JOB"),
    ("Ps", "PSA"),
    ("Prov", "PRO"),
    ("Eccl", "ECC"),
    ("Song", "SNG"),
    ("Isa", "ISA"),
    ("Jer", "JER"),
    ("Lam", "LAM"),
    ("Ezek", "EZK"),
    ("Dan", "DAN"),
    ("Hos", "HOS"),
    ("Joel", "JOL"),
    ("Amos", "AMO"),
    ("Obad", "OBA"),
    ("Jonah", "JON"),
    ("Mic", "MIC"),
    ("Nah", "NAM"),
    ("Hab", "HAB"),
    ("Zeph", "ZEP"),
    ("Hag", "HAG"),
    ("Zech", "ZEC"),
    ("Mal", "MAL"),
    ("Matt", "MAT"),
    ("Mark", "MRK"),
    ("Luke", "LUK"),
    ("John", "JHN"),
    ("Acts", "ACT"),
    ("Rom", "ROM"),
    ("1Cor", "1CO"),
    ("2Cor", "2CO"),
    ("Gal", "GAL"),
    ("Eph", "EPH"),
    ("Phil", "PHP"),
    ("Col", "COL"),
    ("1Thess", "1TH"),
    ("2Thess", "2TH"),
    ("1Tim", "1TI"),
    ("2Tim", "2TI"),
    ("Titus", "TIT"),
    ("Phlm", "PHM"),
    ("Heb", "HEB"),
    ("Jas", "JAS"),
    ("1Pet", "1PE"),
    ("2Pet", "2PE"),
    ("1John", "1JN"),
    ("2John", "2JN"),
    ("3John", "3JN"),
    ("Jude", "JUD"),
    ("Rev", "REV"),
)
OPENBIBLE_BOOK_ALIASES: Mapping[str, str] = MappingProxyType(dict(_OPENBIBLE_ALIAS_ITEMS))
_CANONICAL_TO_ALIAS: Mapping[str, str] = MappingProxyType(
    {canonical: alias for alias, canonical in _OPENBIBLE_ALIAS_ITEMS}
)
HEBREW_BOOKS = frozenset(canonical for _, canonical in _OPENBIBLE_ALIAS_ITEMS[:39])
GREEK_BOOKS = frozenset(canonical for _, canonical in _OPENBIBLE_ALIAS_ITEMS[39:])
# OpenBible uses an English Protestant reference scheme, not the primary
# Hebrew edition's chapter divisions (notably Joel and Malachi).  Keep this
# structural source-scheme registry separate from target passage metadata.
_CHAPTER_COUNT_VALUES = (
    50,
    40,
    27,
    36,
    34,
    24,
    21,
    4,
    31,
    24,
    22,
    25,
    29,
    36,
    10,
    13,
    10,
    42,
    150,
    31,
    12,
    8,
    66,
    52,
    5,
    48,
    12,
    14,
    3,
    9,
    1,
    4,
    7,
    3,
    3,
    3,
    2,
    14,
    4,
    28,
    16,
    24,
    21,
    28,
    16,
    16,
    13,
    6,
    6,
    4,
    4,
    5,
    3,
    6,
    4,
    3,
    1,
    13,
    5,
    5,
    3,
    5,
    1,
    1,
    1,
    22,
)
_CHAPTER_COUNTS = dict(
    zip((canonical for _, canonical in _OPENBIBLE_ALIAS_ITEMS), _CHAPTER_COUNT_VALUES, strict=True)
)
_POINT_RE = re.compile(r"^(?P<book>[1-3]?[A-Za-z]+)\.(?P<chapter>[0-9]+)\.(?P<verse>[0-9]+)$")
_SHORT_CHAPTER_VERSE_RE = re.compile(r"^(?P<chapter>[0-9]+)\.(?P<verse>[0-9]+)$")
_SHORT_VERSE_RE = re.compile(r"^(?P<verse>[0-9]+)$")


class ReferenceParseStatus(StrEnum):
    """Explicit parser outcomes retained by benchmark endpoint rows."""

    PARSED = "parsed"
    EMPTY_REFERENCE = "empty_reference"
    INVALID_SYNTAX = "invalid_syntax"
    UNKNOWN_BOOK = "unknown_book"
    INVALID_CHAPTER = "invalid_chapter"
    INVALID_VERSE = "invalid_verse"
    EMPTY_RANGE = "empty_range"
    BACKWARD_RANGE = "backward_range"
    CROSS_BOOK_RANGE = "cross_book_range"
    OUTSIDE_SOURCE_SCHEME = "outside_source_scheme"
    UNRESOLVED_VERSIFICATION = "unresolved_versification"


class SourceVersificationStatus(StrEnum):
    """Whether source-scheme verse bounds were independently available."""

    VALIDATED_BOUNDS = "validated_bounds"
    UNRESOLVED_VERSIFICATION = "unresolved_versification"


class ReferenceParseError(ValueError):
    """A classified failure that callers can persist without dropping a row."""

    def __init__(self, status: ReferenceParseStatus, reference: str, detail: str) -> None:
        super().__init__(f"{status.value}: {detail}: {reference!r}")
        self.status = status
        self.reference = reference
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ReferencePoint:
    """One parsed source point plus its separate canonical project book code."""

    source_book_alias: str
    canonical_book: str
    chapter: int
    verse: int

    @property
    def source_reference(self) -> str:
        return f"{self.source_book_alias}.{self.chapter}.{self.verse}"

    @property
    def canonical_reference(self) -> str:
        return f"{self.canonical_book} {self.chapter}:{self.verse}"


@dataclass(frozen=True, slots=True)
class ReferenceSpan:
    """One source-scheme reference with preserved original and normalized forms."""

    original_reference: str
    source_reference_scheme: str
    start: ReferencePoint
    end: ReferencePoint
    is_range: bool
    source_versification_status: SourceVersificationStatus

    @property
    def normalized_source_reference(self) -> str:
        if not self.is_range:
            return self.start.source_reference
        return f"{self.start.source_reference}-{self.end.source_reference}"

    @property
    def parse_status(self) -> ReferenceParseStatus:
        """Confirm syntax parsing independently of source-versification confidence."""

        return ReferenceParseStatus.PARSED


def _point(alias: str, chapter: int, verse: int, reference: str) -> ReferencePoint:
    canonical_book = OPENBIBLE_BOOK_ALIASES.get(alias)
    if canonical_book is None:
        raise ReferenceParseError(
            ReferenceParseStatus.UNKNOWN_BOOK,
            reference,
            f"unknown OpenBible book alias {alias}",
        )
    if chapter < 1:
        raise ReferenceParseError(
            ReferenceParseStatus.INVALID_CHAPTER,
            reference,
            "chapter must be positive",
        )
    if verse < 1:
        raise ReferenceParseError(
            ReferenceParseStatus.INVALID_VERSE,
            reference,
            "verse must be positive",
        )
    maximum_chapter = _CHAPTER_COUNTS[canonical_book]
    if chapter > maximum_chapter:
        raise ReferenceParseError(
            ReferenceParseStatus.INVALID_CHAPTER,
            reference,
            f"chapter {chapter} exceeds {alias} chapter count {maximum_chapter}",
        )
    return ReferencePoint(alias, canonical_book, chapter, verse)


def _full_point(value: str, reference: str) -> ReferencePoint:
    match = _POINT_RE.fullmatch(value)
    if match is None:
        book_like = value.split(".", maxsplit=1)[0]
        if (
            book_like
            and re.fullmatch(r"[1-3]?[A-Za-z]+", book_like)
            and book_like not in OPENBIBLE_BOOK_ALIASES
        ):
            raise ReferenceParseError(
                ReferenceParseStatus.UNKNOWN_BOOK,
                reference,
                f"unknown OpenBible book alias {book_like}",
            )
        raise ReferenceParseError(
            ReferenceParseStatus.INVALID_SYNTAX,
            reference,
            "expected Book.chapter.verse",
        )
    return _point(
        match.group("book"),
        int(match.group("chapter")),
        int(match.group("verse")),
        reference,
    )


def _validate_verse_bound(
    point: ReferencePoint,
    reference: str,
    verse_bounds: Mapping[tuple[str, int], int] | None,
) -> bool:
    if verse_bounds is None:
        return False
    maximum = verse_bounds.get((point.canonical_book, point.chapter))
    if maximum is None:
        return False
    if point.verse > maximum:
        raise ReferenceParseError(
            ReferenceParseStatus.INVALID_VERSE,
            reference,
            f"verse {point.verse} exceeds chapter maximum {maximum}",
        )
    return True


def parse_openbible_reference(
    reference: str,
    *,
    source_reference_scheme: str = OPENBIBLE_REFERENCE_SCHEME,
    verse_bounds: Mapping[tuple[str, int], int] | None = None,
) -> ReferenceSpan:
    """Parse one reference while preserving its source scheme and exact spelling."""

    if not source_reference_scheme:
        raise ReferenceParseError(
            ReferenceParseStatus.OUTSIDE_SOURCE_SCHEME,
            reference,
            "source reference scheme is missing",
        )
    if reference == "":
        raise ReferenceParseError(
            ReferenceParseStatus.EMPTY_REFERENCE, reference, "reference is empty"
        )
    if reference.strip() != reference:
        raise ReferenceParseError(
            ReferenceParseStatus.INVALID_SYNTAX,
            reference,
            "leading or trailing whitespace is not permitted",
        )
    parts = reference.split("-")
    if len(parts) > 2:
        raise ReferenceParseError(
            ReferenceParseStatus.INVALID_SYNTAX, reference, "too many range separators"
        )
    start = _full_point(parts[0], reference)
    if len(parts) == 1:
        bound_validated = _validate_verse_bound(start, reference, verse_bounds)
        status = (
            SourceVersificationStatus.VALIDATED_BOUNDS
            if bound_validated
            else SourceVersificationStatus.UNRESOLVED_VERSIFICATION
        )
        return ReferenceSpan(reference, source_reference_scheme, start, start, False, status)
    if not parts[1]:
        raise ReferenceParseError(
            ReferenceParseStatus.EMPTY_RANGE, reference, "range endpoint is empty"
        )

    end_match = _POINT_RE.fullmatch(parts[1])
    if end_match is not None:
        end = _full_point(parts[1], reference)
    elif (short_match := _SHORT_CHAPTER_VERSE_RE.fullmatch(parts[1])) is not None:
        end = _point(
            start.source_book_alias,
            int(short_match.group("chapter")),
            int(short_match.group("verse")),
            reference,
        )
    elif (short_match := _SHORT_VERSE_RE.fullmatch(parts[1])) is not None:
        end = _point(
            start.source_book_alias,
            start.chapter,
            int(short_match.group("verse")),
            reference,
        )
    else:
        raise ReferenceParseError(
            ReferenceParseStatus.INVALID_SYNTAX,
            reference,
            "invalid range endpoint",
        )

    if end.canonical_book != start.canonical_book:
        raise ReferenceParseError(
            ReferenceParseStatus.CROSS_BOOK_RANGE,
            reference,
            "cross-book ranges are not supported",
        )
    start_bound_validated = _validate_verse_bound(start, reference, verse_bounds)
    end_bound_validated = _validate_verse_bound(end, reference, verse_bounds)
    if (end.chapter, end.verse) == (start.chapter, start.verse):
        raise ReferenceParseError(
            ReferenceParseStatus.EMPTY_RANGE, reference, "range has no extent"
        )
    if (end.chapter, end.verse) < (start.chapter, start.verse):
        raise ReferenceParseError(
            ReferenceParseStatus.BACKWARD_RANGE,
            reference,
            "range endpoint precedes its start",
        )
    status = (
        SourceVersificationStatus.VALIDATED_BOUNDS
        if start_bound_validated and end_bound_validated
        else SourceVersificationStatus.UNRESOLVED_VERSIFICATION
    )
    return ReferenceSpan(reference, source_reference_scheme, start, end, True, status)


def openbible_reference_corpus(reference: str) -> Literal["hebrew", "greek"] | None:
    """Classify both preserved book names without claiming a passage mapping.

    Cross-book ranges remain unsupported for passage mapping, but their exact
    source aliases are sufficient to classify an OT-only or NT-only endpoint.
    A malformed reference or a range spanning the two testaments remains
    explicitly unclassified.
    """

    try:
        span = parse_openbible_reference(reference)
        books = (span.start.canonical_book, span.end.canonical_book)
    except ReferenceParseError as exc:
        if exc.status is not ReferenceParseStatus.CROSS_BOOK_RANGE:
            return None
        parts = reference.split("-")
        if len(parts) != 2:
            return None
        try:
            books = (
                _full_point(parts[0], reference).canonical_book,
                _full_point(parts[1], reference).canonical_book,
            )
        except ReferenceParseError:
            return None

    if all(book in HEBREW_BOOKS for book in books):
        return "hebrew"
    if all(book in GREEK_BOOKS for book in books):
        return "greek"
    return None


def expand_canonical_references(
    span: ReferenceSpan,
    *,
    verse_bounds: Mapping[tuple[str, int], int],
) -> tuple[str, ...]:
    """Expand a valid span into exact ordered canonical reference labels."""

    references: list[str] = []
    for chapter in range(span.start.chapter, span.end.chapter + 1):
        maximum = verse_bounds.get((span.start.canonical_book, chapter))
        if maximum is None:
            raise ReferenceParseError(
                ReferenceParseStatus.OUTSIDE_SOURCE_SCHEME,
                span.original_reference,
                f"no source-scheme verse bound for {span.start.canonical_book} {chapter}",
            )
        first_verse = span.start.verse if chapter == span.start.chapter else 1
        last_verse = span.end.verse if chapter == span.end.chapter else maximum
        if first_verse > maximum or last_verse > maximum:
            raise ReferenceParseError(
                ReferenceParseStatus.INVALID_VERSE,
                span.original_reference,
                f"range exceeds chapter {chapter} maximum {maximum}",
            )
        references.extend(
            f"{span.start.canonical_book} {chapter}:{verse}"
            for verse in range(first_verse, last_verse + 1)
        )
    return tuple(references)


def openbible_alias_for_canonical_book(canonical_book: str) -> str:
    """Resolve a canonical project code without treating either namespace as identity."""

    try:
        return _CANONICAL_TO_ALIAS[canonical_book]
    except KeyError as exc:
        raise ValueError(f"unknown canonical Protestant-canon book: {canonical_book}") from exc
