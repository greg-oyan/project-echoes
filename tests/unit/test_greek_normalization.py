"""Greek normalization determinism, punctuation, elision, and folding tests."""

from __future__ import annotations

import pytest

from echoes.normalize.greek import (
    fold_greek,
    is_greek_elided,
    is_greek_punctuation,
    normalize_greek_lemma,
    normalize_greek_token,
    separate_greek_punctuation,
)
from echoes.settings import NormalizationConfig


def test_punctuation_separation_is_lossless(normalization_config: NormalizationConfig) -> None:
    for surface in ("λόγου,", "κλητοῖς.", "(θεοῦ)", "αὐτόν·", "τίς" + "\u037e"):
        leading, core, trailing = separate_greek_punctuation(surface)
        assert leading + core + trailing == surface
        assert core
        forms = normalize_greek_token(surface, normalization_config.greek)
        assert forms.leading_punctuation + forms.normalized_form + forms.trailing_punctuation == (
            surface
        )
        assert forms.surface_form == surface


def test_elision_mark_stays_in_word_core(normalization_config: NormalizationConfig) -> None:
    surface = "δι" + "\u2019"
    forms = normalize_greek_token(surface, normalization_config.greek)

    assert forms.normalized_form == surface
    assert forms.trailing_punctuation == ""
    assert is_greek_elided(surface)
    assert is_greek_elided(surface + ",")
    assert not is_greek_elided("λόγου,")


def test_folded_form_is_case_and_accent_insensitive(
    normalization_config: NormalizationConfig,
) -> None:
    config = normalization_config.greek

    assert fold_greek("Δοῦλος", config) == "δουλοσ"
    # Grave versus acute versions of the same word fold identically.
    assert fold_greek("καὶ", config) == fold_greek("καί", config)
    # Breathing marks are removed.
    assert fold_greek("Ἰούδας", config) == "ιουδασ"


def test_lemma_normalization_preserves_homograph_markers(
    normalization_config: NormalizationConfig,
) -> None:
    config = normalization_config.greek

    assert normalize_greek_lemma("δοῦλος (II)", config) == "δοῦλος (II)"
    assert normalize_greek_lemma(None, config) is None
    assert normalize_greek_lemma("  ", config) is None


def test_empty_surface_form_is_rejected(normalization_config: NormalizationConfig) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_greek_token("", normalization_config.greek)


def test_pure_punctuation_detection() -> None:
    assert is_greek_punctuation("·")
    assert is_greek_punctuation(",")
    assert not is_greek_punctuation("λόγου,")
