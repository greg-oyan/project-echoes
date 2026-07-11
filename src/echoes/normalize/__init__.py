"""Deterministic language-specific normalization."""

from echoes.normalize.hebrew import (
    NormalizedForms,
    is_punctuation,
    normalize_hebrew_token,
    normalize_lemma,
)

__all__ = ["NormalizedForms", "is_punctuation", "normalize_hebrew_token", "normalize_lemma"]
