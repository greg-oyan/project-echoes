"""Deterministic Hebrew and Aramaic normalization policy tests."""

import unicodedata

import pytest

from echoes.normalize.hebrew import is_punctuation, normalize_hebrew_token, normalize_lemma
from echoes.settings import NormalizationConfig


def test_normalization_preserves_surface_and_separates_analytical_forms(
    normalization_config: NormalizationConfig,
) -> None:
    surface = "מֶ֖לֶךְ"

    forms = normalize_hebrew_token(surface, normalization_config.hebrew)

    assert forms.surface_form == surface
    assert forms.normalized_form == unicodedata.normalize("NFD", surface)
    assert forms.unpointed_form == "מלך"


def test_maqqef_paseq_sof_pasuq_and_final_forms_are_preserved(
    normalization_config: NormalizationConfig,
) -> None:
    surface = "מֶלֶךְ־דָּבָר\u05c0\u05c3"

    forms = normalize_hebrew_token(surface, normalization_config.hebrew)

    assert forms.unpointed_form == "מלך־דבר\u05c0\u05c3"
    assert "ך" in forms.unpointed_form


def test_cgj_is_removed_only_from_derived_forms(
    normalization_config: NormalizationConfig,
) -> None:
    surface = "מ\u034fֶלֶךְ"

    forms = normalize_hebrew_token(surface, normalization_config.hebrew)

    assert "\u034f" in forms.surface_form
    assert "\u034f" not in forms.normalized_form
    assert "\u034f" not in forms.unpointed_form
    assert normalize_lemma(surface, normalization_config.hebrew) == forms.normalized_form


def test_normalization_is_deterministic_and_rejects_empty_tokens(
    normalization_config: NormalizationConfig,
) -> None:
    first = normalize_hebrew_token("מַלְכָּא", normalization_config.hebrew)
    second = normalize_hebrew_token("מַלְכָּא", normalization_config.hebrew)

    assert first == second
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_hebrew_token("", normalization_config.hebrew)


def test_punctuation_detection_does_not_misclassify_pointed_words() -> None:
    assert is_punctuation("\u05c3")
    assert is_punctuation("־")
    assert not is_punctuation("דָּבָר־")
