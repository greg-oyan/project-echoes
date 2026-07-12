"""Canonical Greek New Testament book registry for the 27-book MACULA source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GreekBookSpec:
    """One canonical book identity and its MACULA Nestle1904 source numbering."""

    code: str
    name: str
    order: int
    source_number: int
    source_file_stem: str
    chapter_count: int


_BOOK_DATA: tuple[tuple[str, str, str, int], ...] = (
    ("MAT", "Matthew", "matthew", 28),
    ("MRK", "Mark", "mark", 16),
    ("LUK", "Luke", "luke", 24),
    ("JHN", "John", "john", 21),
    ("ACT", "Acts", "acts", 28),
    ("ROM", "Romans", "romans", 16),
    ("1CO", "1 Corinthians", "1corinthians", 16),
    ("2CO", "2 Corinthians", "2corinthians", 13),
    ("GAL", "Galatians", "galatians", 6),
    ("EPH", "Ephesians", "ephesians", 6),
    ("PHP", "Philippians", "philippians", 4),
    ("COL", "Colossians", "colossians", 4),
    ("1TH", "1 Thessalonians", "1thessalonians", 5),
    ("2TH", "2 Thessalonians", "2thessalonians", 3),
    ("1TI", "1 Timothy", "1timothy", 6),
    ("2TI", "2 Timothy", "2timothy", 4),
    ("TIT", "Titus", "titus", 3),
    ("PHM", "Philemon", "philemon", 1),
    ("HEB", "Hebrews", "hebrews", 13),
    ("JAS", "James", "james", 5),
    ("1PE", "1 Peter", "1peter", 5),
    ("2PE", "2 Peter", "2peter", 3),
    ("1JN", "1 John", "1john", 5),
    ("2JN", "2 John", "2john", 1),
    ("3JN", "3 John", "3john", 1),
    ("JUD", "Jude", "jude", 1),
    ("REV", "Revelation", "revelation", 22),
)

GREEK_BOOKS: tuple[GreekBookSpec, ...] = tuple(
    GreekBookSpec(
        code=code,
        name=name,
        order=index,
        source_number=index,
        source_file_stem=stem,
        chapter_count=chapters,
    )
    for index, (code, name, stem, chapters) in enumerate(_BOOK_DATA, start=1)
)
_BY_CODE = {book.code: book for book in GREEK_BOOKS}
_BY_SOURCE_NUMBER = {book.source_number: book for book in GREEK_BOOKS}


def greek_book_by_code(code: str) -> GreekBookSpec:
    """Resolve a canonical code or raise a clear validation error."""
    try:
        return _BY_CODE[code.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown canonical Greek book code: {code}") from exc


def greek_book_by_source_number(source_number: int) -> GreekBookSpec:
    """Resolve MACULA's two-digit Nestle1904 book number."""
    try:
        return _BY_SOURCE_NUMBER[source_number]
    except KeyError as exc:
        raise ValueError(f"unknown MACULA Greek book number: {source_number:02d}") from exc


def validate_greek_reference(book: GreekBookSpec, chapter: int, verse: int) -> None:
    """Validate the source-edition chapter range and a positive verse number."""
    if chapter < 1 or chapter > book.chapter_count:
        raise ValueError(
            f"invalid chapter for {book.code}: {chapter}; expected 1-{book.chapter_count}"
        )
    if verse < 1:
        raise ValueError(f"invalid verse for {book.code} {chapter}: {verse}")
