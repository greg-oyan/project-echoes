"""Tests for the preregistered corpus-global formulaic-language control."""

from __future__ import annotations

import hashlib
from typing import Literal

import pytest
from pydantic import ValidationError

from echoes.final_discovery.config import FormulaicControlPolicy
from echoes.final_discovery.formulaic import (
    FormulaicControlError,
    apply_formulaic_control,
)
from echoes.final_discovery.models import PassageRecord


def _policy(**updates: object) -> FormulaicControlPolicy:
    values: dict[str, object] = {
        "method": "primary_corpus_high_df_lemma_root_ngrams",
        "ngram_sizes": [2, 3],
        "minimum_document_frequency_fraction": 0.5,
        "minimum_document_count": 2,
        "minimum_distinct_high_df_features": 1,
        "minimum_high_df_feature_fraction": 0.2,
        "sensitivity_uses_primary_vocabulary": True,
    }
    values.update(updates)
    return FormulaicControlPolicy.model_validate(values)


def _passage(
    passage_id: str,
    lemmas: tuple[str, str, str, str],
    *,
    profile: Literal["edition_complete", "critical_core"] = "edition_complete",
) -> PassageRecord:
    return PassageRecord(
        passage_id=passage_id,
        reference=f"Fixture {passage_id}",
        corpus="hebrew",
        book="Fixture",
        genre="narrative",
        analysis_profile=profile,
        analysis_reading="qere" if profile == "edition_complete" else "ketiv",
        granularity="verse",
        token_count=4,
        token_ids=tuple(f"{passage_id}-{index}" for index in range(4)),
        original_text="fixture original text",
        normalized_text="fixture normalized text",
        lemma_sequence=lemmas,
        root_sequence=lemmas,
        pos_sequence=("N", "N", "N", "N"),
        morphology_sequence=("x", "x", "x", "x"),
        semantic_domains=(None, None, None, None),
        entities=(None, None, None, None),
        participants=(None, None, None, None),
        frames=(None, None, None, None),
        source_digest=hashlib.sha256(passage_id.encode()).hexdigest(),
    )


def test_formulaic_vocabulary_is_learned_only_from_primary_passages() -> None:
    passages = (
        _passage("primary-a", ("אמר", "מלך", "הלך", "עיר")),
        _passage("primary-b", ("אמר", "מלך", "נתן", "עם")),
        _passage("primary-c", ("ראה", "איש", "בנה", "בית")),
        _passage(
            "sensitivity-shared",
            ("אמר", "מלך", "שמע", "קול"),
            profile="critical_core",
        ),
        _passage(
            "sensitivity-only-a",
            ("זר", "אות", "אחד", "שנים"),
            profile="critical_core",
        ),
        _passage(
            "sensitivity-only-b",
            ("זר", "אות", "שלש", "ארבע"),
            profile="critical_core",
        ),
    )

    enriched, features, controls, report = apply_formulaic_control(
        passages,
        primary_passage_ids={"primary-a", "primary-b", "primary-c"},
        policy=_policy(),
    )

    flags = {row.passage_id: row.formulaic_language for row in controls}
    assert flags == {
        "primary-a": True,
        "primary-b": True,
        "primary-c": False,
        "sensitivity-shared": True,
        "sensitivity-only-a": False,
        "sensitivity-only-b": False,
    }
    assert {row.passage_id: row.formulaic_language for row in enriched} == flags
    assert report.primary_passage_count == 3
    assert report.evaluated_passage_count == 6
    assert report.document_frequency_threshold == 2
    assert report.sensitivity_uses_primary_vocabulary
    assert report.source_text_persisted_in_receipt is False
    assert report.high_df_feature_count == len(features)
    assert all(row.document_frequency == 2 for row in features)
    assert any("אמר" in row.feature_id for row in features)
    assert not any("זר" in row.feature_id for row in features)


def test_formulaic_control_is_order_invariant_and_hashes_unicode() -> None:
    passages = (
        _passage("a", ("אמר", "מלך", "הלך", "עיר")),
        _passage("b", ("אמר", "מלך", "נתן", "עם")),
    )
    first = apply_formulaic_control(
        passages,
        primary_passage_ids={"a", "b"},
        policy=_policy(),
    )
    second = apply_formulaic_control(
        tuple(reversed(passages)),
        primary_passage_ids={"a", "b"},
        policy=_policy(),
    )

    assert first[1] == second[1]
    assert first[3] == second[3]
    assert {row.passage_id: row.model_dump(mode="json") for row in first[2]} == {
        row.passage_id: row.model_dump(mode="json") for row in second[2]
    }


def test_formulaic_control_fails_closed_on_incomplete_population() -> None:
    passage = _passage("a", ("one", "two", "three", "four"))

    with pytest.raises(FormulaicControlError, match="nonempty primary"):
        apply_formulaic_control((passage,), primary_passage_ids=set(), policy=_policy())
    with pytest.raises(FormulaicControlError, match="duplicate or missing"):
        apply_formulaic_control(
            (passage,),
            primary_passage_ids={"missing"},
            policy=_policy(),
        )
    with pytest.raises(FormulaicControlError, match="duplicate or missing"):
        apply_formulaic_control(
            (passage, passage),
            primary_passage_ids={"a"},
            policy=_policy(),
        )


def test_formulaic_policy_rejects_a_changed_ngram_family() -> None:
    with pytest.raises(ValidationError, match="exact lemma/root bigrams and trigrams"):
        _policy(ngram_sizes=[3, 2])
