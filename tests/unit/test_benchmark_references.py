"""OpenBible source-reference parsing and 66-book alias coverage."""

from __future__ import annotations

import pytest

from echoes.benchmarks.references import (
    OPENBIBLE_BOOK_ALIASES,
    OPENBIBLE_REFERENCE_SCHEME,
    ReferenceParseError,
    ReferenceParseStatus,
    SourceVersificationStatus,
    expand_canonical_references,
    openbible_alias_for_canonical_book,
    openbible_reference_corpus,
    parse_openbible_reference,
)


def test_all_66_openbible_aliases_map_bijectively_to_project_codes() -> None:
    assert len(OPENBIBLE_BOOK_ALIASES) == 66
    assert len(set(OPENBIBLE_BOOK_ALIASES.values())) == 66
    assert OPENBIBLE_BOOK_ALIASES["Gen"] == "GEN"
    assert OPENBIBLE_BOOK_ALIASES["Ps"] == "PSA"
    assert OPENBIBLE_BOOK_ALIASES["1Thess"] == "1TH"
    assert OPENBIBLE_BOOK_ALIASES["Rev"] == "REV"
    assert all(
        openbible_alias_for_canonical_book(canonical) == alias
        for alias, canonical in OPENBIBLE_BOOK_ALIASES.items()
    )


def test_single_verse_preserves_source_scheme_and_alias() -> None:
    parsed = parse_openbible_reference("Gen.1.1")

    assert parsed.original_reference == "Gen.1.1"
    assert parsed.source_reference_scheme == OPENBIBLE_REFERENCE_SCHEME
    assert parsed.start.source_book_alias == "Gen"
    assert parsed.start.canonical_reference == "GEN 1:1"
    assert parsed.end == parsed.start
    assert parsed.is_range is False
    assert parsed.normalized_source_reference == "Gen.1.1"
    assert parsed.parse_status is ReferenceParseStatus.PARSED
    assert parsed.source_versification_status is SourceVersificationStatus.UNRESOLVED_VERSIFICATION


@pytest.mark.parametrize(
    ("reference", "normalized", "end"),
    [
        ("Gen.1.1-Gen.1.3", "Gen.1.1-Gen.1.3", (1, 3)),
        ("Gen.1.1-1.3", "Gen.1.1-Gen.1.3", (1, 3)),
        ("Gen.1.1-3", "Gen.1.1-Gen.1.3", (1, 3)),
        ("Gen.1.31-Gen.2.2", "Gen.1.31-Gen.2.2", (2, 2)),
    ],
)
def test_same_and_cross_chapter_ranges_normalize_deterministically(
    reference: str,
    normalized: str,
    end: tuple[int, int],
) -> None:
    parsed = parse_openbible_reference(reference)

    assert parsed.is_range is True
    assert parsed.normalized_source_reference == normalized
    assert (parsed.end.chapter, parsed.end.verse) == end


def test_cross_chapter_range_expands_in_exact_order() -> None:
    bounds = {("GEN", 1): 31, ("GEN", 2): 25}
    parsed = parse_openbible_reference("Gen.1.30-Gen.2.2", verse_bounds=bounds)

    assert expand_canonical_references(parsed, verse_bounds=bounds) == (
        "GEN 1:30",
        "GEN 1:31",
        "GEN 2:1",
        "GEN 2:2",
    )


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("2Chr.36.21-Ezra.1.2", "hebrew"),
        ("Acts.28.17-Rom.1.1", "greek"),
        ("Gen.1.1-John.1.1", None),
        ("Unknown.1.1", None),
    ],
)
def test_cross_book_source_corpus_uses_both_preserved_book_names(
    reference: str,
    expected: str | None,
) -> None:
    assert openbible_reference_corpus(reference) == expected


@pytest.mark.parametrize(
    ("reference", "status", "bounds"),
    [
        ("", ReferenceParseStatus.EMPTY_REFERENCE, None),
        ("Unknown.1.1", ReferenceParseStatus.UNKNOWN_BOOK, None),
        ("Gen.51.1", ReferenceParseStatus.INVALID_CHAPTER, None),
        ("Gen.1.0", ReferenceParseStatus.INVALID_VERSE, None),
        ("Gen.1.32", ReferenceParseStatus.INVALID_VERSE, {("GEN", 1): 31}),
        ("Gen.1.3-Gen.1.2", ReferenceParseStatus.BACKWARD_RANGE, None),
        ("Gen.1.1-Gen.1.1", ReferenceParseStatus.EMPTY_RANGE, None),
        ("Gen.1.1-", ReferenceParseStatus.EMPTY_RANGE, None),
        ("Gen.1.1-Exod.1.1", ReferenceParseStatus.CROSS_BOOK_RANGE, None),
        (" Gen.1.1", ReferenceParseStatus.INVALID_SYNTAX, None),
    ],
)
def test_invalid_or_out_of_scheme_references_are_classified(
    reference: str,
    status: ReferenceParseStatus,
    bounds: dict[tuple[str, int], int] | None,
) -> None:
    with pytest.raises(ReferenceParseError) as raised:
        parse_openbible_reference(reference, verse_bounds=bounds)

    assert raised.value.status is status


def test_missing_source_scheme_verse_bounds_remain_explicitly_unresolved() -> None:
    parsed = parse_openbible_reference("Gen.2.1", verse_bounds={("GEN", 1): 31})

    assert parsed.parse_status is ReferenceParseStatus.PARSED
    assert parsed.source_versification_status is SourceVersificationStatus.UNRESOLVED_VERSIFICATION


def test_complete_source_scheme_bound_validates_verse_coordinate() -> None:
    parsed = parse_openbible_reference("Gen.1.31", verse_bounds={("GEN", 1): 31})

    assert parsed.parse_status is ReferenceParseStatus.PARSED
    assert parsed.source_versification_status is SourceVersificationStatus.VALIDATED_BOUNDS


def test_missing_source_scheme_fails_explicitly() -> None:
    with pytest.raises(ReferenceParseError) as raised:
        parse_openbible_reference("Gen.1.1", source_reference_scheme="")

    assert raised.value.status is ReferenceParseStatus.OUTSIDE_SOURCE_SCHEME


def test_unknown_canonical_book_lookup_fails() -> None:
    with pytest.raises(ValueError, match="unknown canonical"):
        openbible_alias_for_canonical_book("TOB")
