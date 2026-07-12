"""Deterministic, information-preserving Greek normalization.

The MACULA Greek Nestle1904 node representation attaches punctuation to the
word text (for example ``δοῦλος,``) and marks elision with U+2019.
Derived forms separate punctuation and produce an accent-insensitive folded
form; the original surface string is never altered.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from echoes.settings import GreekNormalization

# Punctuation observed in the pinned Nestle1904 node text plus close variants.
LEADING_PUNCTUATION = frozenset(
    {
        "(",
        "[",
        "\u2014",  # em dash
        "\u2013",  # en dash
        "\u00ab",  # left guillemet
        "\u201c",  # left double quotation mark
    }
)
TRAILING_PUNCTUATION = frozenset(
    {
        ",",
        ".",
        ";",  # ASCII semicolon; the Greek question mark U+037E normalizes to it
        "\u037e",  # Greek question mark
        "\u00b7",  # middle dot
        "\u0387",  # Greek ano teleia
        ")",
        "]",
        "\u2014",  # em dash
        "\u2013",  # en dash
        "\u00bb",  # right guillemet
        "\u201d",  # right double quotation mark
        "!",
        "?",
    }
)
# Elision and coronis marks belong to the word form and are never separated.
ELISION_MARKS = frozenset(
    {
        "\u2019",  # right single quotation mark (the observed elision mark)
        "\u02bc",  # modifier letter apostrophe
        "\u1fbd",  # Greek koronis
    }
)
ACCENT_COMBINING = frozenset(
    {
        "\u0300",  # combining grave accent
        "\u0301",  # combining acute accent
        "\u0342",  # combining Greek perispomeni (circumflex)
    }
)
BREATHING_COMBINING = frozenset(
    {
        "\u0313",  # combining comma above (smooth breathing)
        "\u0314",  # combining reversed comma above (rough breathing)
    }
)
DIAERESIS_COMBINING = frozenset({"\u0308"})
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class GreekNormalizedForms:
    """Separate source-preserving analytical forms for one Greek token."""

    surface_form: str
    normalized_form: str
    folded_form: str
    leading_punctuation: str
    trailing_punctuation: str


def separate_greek_punctuation(value: str) -> tuple[str, str, str]:
    """Split attached punctuation from the word core without altering bytes.

    Returns ``(leading, core, trailing)`` with
    ``leading + core + trailing == value``.  Elision marks (U+2019 and
    variants) after a letter are part of the word core, not punctuation.
    """
    start = 0
    end = len(value)
    while start < end and value[start] in LEADING_PUNCTUATION:
        start += 1
    while end > start and value[end - 1] in TRAILING_PUNCTUATION:
        end -= 1
    return value[:start], value[start:end], value[end:]


def _collapse(value: str, config: GreekNormalization) -> str:
    if config.transformations.collapse_whitespace:
        return WHITESPACE.sub(" ", value).strip()
    return value


def fold_greek(value: str, config: GreekNormalization) -> str:
    """Case-fold and strip configured diacritics for an accent-insensitive form.

    ``str.casefold`` also maps final sigma to medial sigma, which is the
    documented, intended behavior for the folded comparison form.
    """
    decomposed = unicodedata.normalize("NFD", value)
    removed: set[str] = set()
    if config.transformations.folded_remove_accents:
        removed |= ACCENT_COMBINING
    if config.transformations.folded_remove_breathings:
        removed |= BREATHING_COMBINING
    if config.transformations.folded_remove_diaeresis:
        removed |= DIAERESIS_COMBINING
    stripped = "".join(character for character in decomposed if character not in removed)
    folded = stripped.casefold() if config.transformations.folded_case_fold else stripped
    return unicodedata.normalize(config.transformations.unicode_normalization, folded)


def normalize_greek_token(value: str, config: GreekNormalization) -> GreekNormalizedForms:
    """Derive punctuation-separated and folded forms without altering the source."""
    if not value:
        raise ValueError("surface form must not be empty")
    collapsed = _collapse(value, config)
    leading, core, trailing = separate_greek_punctuation(collapsed)
    if not core:
        # A purely punctuational token keeps its text as its own core.
        leading, core, trailing = "", collapsed, ""
    normalized = unicodedata.normalize(config.transformations.unicode_normalization, core)
    folded = fold_greek(core, config)
    if not normalized:
        raise ValueError("normalization produced an empty token")
    if not folded:
        raise ValueError("folding produced an empty token")
    return GreekNormalizedForms(
        surface_form=value,
        normalized_form=normalized,
        folded_form=folded,
        leading_punctuation=leading,
        trailing_punctuation=trailing,
    )


def normalize_greek_lemma(value: str | None, config: GreekNormalization) -> str | None:
    """Normalize a MACULA Unicode lemma in its own namespace, retaining nulls.

    Lemma homograph markers such as ``δοῦλος (II)`` are preserved verbatim.
    """
    if value is None or not value.strip():
        return None
    collapsed = _collapse(value.strip(), config)
    return unicodedata.normalize(config.transformations.unicode_normalization, collapsed)


def is_greek_elided(value: str) -> bool:
    """Return true when the word core ends with an elision mark after a letter."""
    _, core, _ = separate_greek_punctuation(value)
    return len(core) >= 2 and core[-1] in ELISION_MARKS and core[-2].isalpha()


def is_greek_punctuation(value: str) -> bool:
    """Return true only when a token contains no letters or numbers."""
    return bool(value) and all(
        unicodedata.category(character).startswith(("P", "Z", "S")) for character in value
    )
