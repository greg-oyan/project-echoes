"""Deterministic, information-preserving Hebrew and Aramaic normalization."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from echoes.settings import HebrewNormalization

COMBINING_GRAPHEME_JOINER = "\u034f"
CANTILLATION = frozenset(chr(codepoint) for codepoint in range(0x0591, 0x05B0)) | {
    "\u05bd",
}
VOWEL_POINTS = frozenset(chr(codepoint) for codepoint in range(0x05B0, 0x05BD)) | {
    "\u05bf",
    "\u05c1",
    "\u05c2",
    "\u05c4",
    "\u05c5",
    "\u05c7",
}
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NormalizedForms:
    """Separate source-preserving analytical forms for one token."""

    surface_form: str
    normalized_form: str
    unpointed_form: str


def _base_transform(value: str, config: HebrewNormalization) -> str:
    transformed = unicodedata.normalize(config.transformations.unicode_normalization, value)
    if config.transformations.remove_combining_grapheme_joiner:
        transformed = transformed.replace(COMBINING_GRAPHEME_JOINER, "")
    if config.transformations.collapse_whitespace:
        transformed = WHITESPACE.sub(" ", transformed).strip()
    return transformed


def _remove_marks(value: str, *, cantillation: bool, vowels: bool) -> str:
    return "".join(
        character
        for character in value
        if not (cantillation and character in CANTILLATION)
        and not (vowels and character in VOWEL_POINTS)
    )


def normalize_hebrew_token(value: str, config: HebrewNormalization) -> NormalizedForms:
    """Derive normalized and unpointed forms without altering the source string."""
    if not value:
        raise ValueError("surface form must not be empty")
    normalized = _base_transform(value, config)
    normalized = _remove_marks(
        normalized,
        cantillation=config.transformations.normalized_remove_cantillation,
        vowels=config.transformations.normalized_remove_vowel_points,
    )
    unpointed = _remove_marks(
        _base_transform(value, config),
        cantillation=config.transformations.unpointed_remove_cantillation,
        vowels=config.transformations.unpointed_remove_vowel_points,
    )
    if not normalized:
        raise ValueError("normalization produced an empty token")
    if not unpointed:
        raise ValueError("unpointed normalization produced an empty token")
    return NormalizedForms(
        surface_form=value,
        normalized_form=normalized,
        unpointed_form=unpointed,
    )


def normalize_lemma(value: str | None, config: HebrewNormalization) -> str | None:
    """Normalize a MACULA lemma in its original namespace, retaining null values."""
    if value is None or not value.strip():
        return None
    return _base_transform(value, config)


def is_punctuation(value: str) -> bool:
    """Return true only when a token contains no letters or numbers."""
    return bool(value) and all(
        unicodedata.category(character).startswith(("P", "Z", "S")) for character in value
    )
