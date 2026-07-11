"""Canonical Hebrew Bible book registry for the initial 39-book source layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BookSpec:
    """One canonical book identity and its MACULA/WLC source numbering."""

    code: str
    name: str
    order: int
    source_number: int
    chapter_count: int


_BOOK_DATA: tuple[tuple[str, str, int], ...] = (
    ("GEN", "Genesis", 50),
    ("EXO", "Exodus", 40),
    ("LEV", "Leviticus", 27),
    ("NUM", "Numbers", 36),
    ("DEU", "Deuteronomy", 34),
    ("JOS", "Joshua", 24),
    ("JDG", "Judges", 21),
    ("RUT", "Ruth", 4),
    ("1SA", "1 Samuel", 31),
    ("2SA", "2 Samuel", 24),
    ("1KI", "1 Kings", 22),
    ("2KI", "2 Kings", 25),
    ("1CH", "1 Chronicles", 29),
    ("2CH", "2 Chronicles", 36),
    ("EZR", "Ezra", 10),
    ("NEH", "Nehemiah", 13),
    ("EST", "Esther", 10),
    ("JOB", "Job", 42),
    ("PSA", "Psalms", 150),
    ("PRO", "Proverbs", 31),
    ("ECC", "Ecclesiastes", 12),
    ("SNG", "Song of Songs", 8),
    ("ISA", "Isaiah", 66),
    ("JER", "Jeremiah", 52),
    ("LAM", "Lamentations", 5),
    ("EZK", "Ezekiel", 48),
    ("DAN", "Daniel", 12),
    ("HOS", "Hosea", 14),
    ("JOL", "Joel", 4),
    ("AMO", "Amos", 9),
    ("OBA", "Obadiah", 1),
    ("JON", "Jonah", 4),
    ("MIC", "Micah", 7),
    ("NAM", "Nahum", 3),
    ("HAB", "Habakkuk", 3),
    ("ZEP", "Zephaniah", 3),
    ("HAG", "Haggai", 2),
    ("ZEC", "Zechariah", 14),
    ("MAL", "Malachi", 3),
)

BOOKS: tuple[BookSpec, ...] = tuple(
    BookSpec(code=code, name=name, order=index, source_number=index, chapter_count=chapters)
    for index, (code, name, chapters) in enumerate(_BOOK_DATA, start=1)
)
_BY_CODE = {book.code: book for book in BOOKS}
_BY_SOURCE_NUMBER = {book.source_number: book for book in BOOKS}


def book_by_code(code: str) -> BookSpec:
    """Resolve a canonical code or raise a clear validation error."""
    try:
        return _BY_CODE[code.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown canonical Hebrew book code: {code}") from exc


def book_by_source_number(source_number: int) -> BookSpec:
    """Resolve MACULA's two-digit WLC book number."""
    try:
        return _BY_SOURCE_NUMBER[source_number]
    except KeyError as exc:
        raise ValueError(f"unknown MACULA Hebrew book number: {source_number:02d}") from exc


def validate_reference(book: BookSpec, chapter: int, verse: int) -> None:
    """Validate the source-edition chapter range and a positive verse number."""
    if chapter < 1 or chapter > book.chapter_count:
        raise ValueError(
            f"invalid chapter for {book.code}: {chapter}; expected 1-{book.chapter_count}"
        )
    if verse < 1:
        raise ValueError(f"invalid verse for {book.code} {chapter}: {verse}")
