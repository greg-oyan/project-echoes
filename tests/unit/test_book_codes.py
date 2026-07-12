"""OSHB-to-MACULA book-code mapping tests."""

from __future__ import annotations

import pytest

from echoes.align.book_codes import (
    MACULA_TO_OSHB_BOOK,
    OSHB_TO_MACULA_BOOK,
    macula_book_for_oshb,
)
from echoes.corpus.books import BOOKS


def test_mapping_is_a_bijection_over_all_39_books() -> None:
    assert len(OSHB_TO_MACULA_BOOK) == 39
    assert len(set(OSHB_TO_MACULA_BOOK.values())) == 39
    assert set(OSHB_TO_MACULA_BOOK.values()) == {book.code for book in BOOKS}
    assert {MACULA_TO_OSHB_BOOK[macula] for macula in OSHB_TO_MACULA_BOOK.values()} == set(
        OSHB_TO_MACULA_BOOK
    )


def test_known_divergent_identifiers_resolve() -> None:
    assert macula_book_for_oshb("2Kgs") == "2KI"
    assert macula_book_for_oshb("Ps") == "PSA"
    assert macula_book_for_oshb("Song") == "SNG"
    assert macula_book_for_oshb("Nah") == "NAM"
    assert macula_book_for_oshb("Joel") == "JOL"


def test_unknown_identifier_fails_clearly() -> None:
    with pytest.raises(ValueError, match="unknown OSHB book identifier"):
        macula_book_for_oshb("Atlantis")
