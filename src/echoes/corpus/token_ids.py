"""Pure source-edition token identity generation.

This module deliberately depends only on Python's standard library.  In
particular, token identity is defined before and independently of any later
versification crosswalk or alignment layer.
"""

from __future__ import annotations

import hashlib
import re

BOOK_IDENTIFIER_PATTERN = re.compile(r"^[A-Z0-9]{3}$")
CORPUS_PREFIX_PATTERN = re.compile(r"^[A-Z]{2,4}$")
SOURCE_RECORD_SUFFIX_LENGTH = 12


class TokenIdentityError(ValueError):
    """Raised when a source-edition identity cannot produce a safe token ID."""


def generate_source_edition_token_id(
    *,
    book_identifier: str,
    chapter: int,
    verse: int,
    source_token_position: int,
    source_subtoken_position: int | None = None,
    source_record_id: str | None = None,
    disambiguate_with_source_record: bool = False,
    corpus_prefix: str = "HB",
) -> str:
    """Return an ID derived exclusively from identity inside one source edition.

    ``source_record_id`` contributes only a stable digest and only when the
    caller explicitly requests disambiguation (for example, for two variant
    records occupying the same source word).  ``corpus_prefix`` selects the
    corpus namespace (``HB`` for Hebrew, ``GNT`` for Greek) and changes no
    Hebrew identity semantics.  No external mapping is accepted by this API.
    """
    if CORPUS_PREFIX_PATTERN.fullmatch(corpus_prefix) is None:
        raise TokenIdentityError("corpus_prefix must contain two to four ASCII capital letters")
    normalized_book = book_identifier.upper()
    if BOOK_IDENTIFIER_PATTERN.fullmatch(normalized_book) is None:
        raise TokenIdentityError(
            "book_identifier must contain exactly three ASCII letters or digits"
        )
    coordinates = {
        "chapter": chapter,
        "verse": verse,
        "source_token_position": source_token_position,
    }
    for name, value in coordinates.items():
        if value < 1:
            raise TokenIdentityError(f"{name} must be at least 1")
    if source_subtoken_position is not None and source_subtoken_position < 1:
        raise TokenIdentityError("source_subtoken_position must be at least 1")

    token_id = (
        f"{corpus_prefix}_{normalized_book}_{chapter:03d}_{verse:03d}_{source_token_position:04d}"
    )
    if source_subtoken_position is not None:
        token_id = f"{token_id}.{source_subtoken_position:02d}"
    if disambiguate_with_source_record:
        if source_record_id is None or not source_record_id:
            raise TokenIdentityError(
                "source_record_id is required when source-record disambiguation is enabled"
            )
        digest = hashlib.sha256(source_record_id.encode("utf-8")).hexdigest()
        token_id = f"{token_id}~{digest[:SOURCE_RECORD_SUFFIX_LENGTH]}"
    return token_id
