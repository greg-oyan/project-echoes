"""Stable lexical feature, representation, candidate, and ranking identities."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from echoes.lexical.config import load_lexical_preregistration
from echoes.lexical.identity import (
    CandidatePairIdentityPayload,
    FeatureIdentityPayload,
    LexicalIdentity,
    LexicalIdentityCollisionError,
    LexicalIdentityRegistry,
    RankingIdentityPayload,
    RepresentationIdentityPayload,
    build_candidate_pair_identity,
    build_feature_identity,
    build_ranking_identity,
    build_representation_identity,
    preregistration_digest,
)

SHA = "a" * 64


def _candidate(
    first: str = "P_HB_ONE",
    second: str = "P_HB_TWO",
    *,
    profile: str = "edition_complete",
    granularity: str = "verse",
) -> LexicalIdentity:
    return build_candidate_pair_identity(
        CandidatePairIdentityPayload.model_validate(
            {
                "analysis_profile": profile,
                "granularity": granularity,
                "passage_id_a": first,
                "passage_id_b": second,
            }
        )
    )


def test_input_and_sparse_column_reordering_do_not_change_feature_ids() -> None:
    payloads = [
        FeatureIdentityPayload(
            feature_family="lemma",
            language_namespace="hb",
            feature_value="אמר",
            feature_order=1,
        ),
        FeatureIdentityPayload(
            feature_family="lemma",
            language_namespace="hb",
            feature_value="דבר",
            feature_order=1,
        ),
    ]

    forward = {build_feature_identity(payload).identifier for payload in payloads}
    reordered_columns = {
        build_feature_identity(payload).identifier for payload in reversed(payloads)
    }

    assert forward == reordered_columns


def test_feature_normalization_and_language_namespace_are_identity_facts() -> None:
    decomposed = FeatureIdentityPayload(
        feature_family="lemma",
        language_namespace="gk",
        feature_value="\u03bb\u03bf\u0301\u03b3\u03bf\u03c2",
        feature_order=1,
    )
    composed = FeatureIdentityPayload(
        feature_family="lemma",
        language_namespace="gk",
        feature_value="\u03bb\u03cc\u03b3\u03bf\u03c2",
        feature_order=1,
    )
    hebrew_namespace = FeatureIdentityPayload(
        feature_family="lemma",
        language_namespace="hb",
        feature_value="\u03bb\u03cc\u03b3\u03bf\u03c2",
        feature_order=1,
    )

    assert build_feature_identity(decomposed) == build_feature_identity(composed)
    assert build_feature_identity(composed) != build_feature_identity(hebrew_namespace)
    with pytest.raises(ValidationError, match="English gloss"):
        FeatureIdentityPayload(
            feature_family="english_gloss",
            language_namespace="gk",
            feature_value="word",
            feature_order=1,
        )


def test_scores_and_pair_direction_do_not_change_candidate_identity() -> None:
    before_score_change = _candidate()
    after_score_change = _candidate()
    reverse_input = _candidate("P_HB_TWO", "P_HB_ONE")

    assert before_score_change.identifier == after_score_change.identifier
    assert before_score_change.identifier == reverse_input.identifier


def test_profile_and_granularity_change_candidate_identity() -> None:
    base = _candidate()
    profile = _candidate(profile="critical_core")
    granularity = _candidate(granularity="sentence")

    assert len({base.identifier, profile.identifier, granularity.identifier}) == 3


def test_direction_changes_ranking_identity_not_unordered_pair_identity() -> None:
    pair = _candidate()
    forward = build_ranking_identity(
        RankingIdentityPayload(
            experiment_run_id="lexical-v1-run",
            query_passage_id="P_HB_ONE",
            target_passage_id="P_HB_TWO",
            detector="bm25",
            representation_id="LR_lemma",
            direction="forward",
        )
    )
    reverse = build_ranking_identity(
        RankingIdentityPayload(
            experiment_run_id="lexical-v1-run",
            query_passage_id="P_HB_TWO",
            target_passage_id="P_HB_ONE",
            detector="bm25",
            representation_id="LR_lemma",
            direction="reverse",
        )
    )

    assert forward.identifier != reverse.identifier
    assert pair.identifier == _candidate("P_HB_TWO", "P_HB_ONE").identifier


def test_english_and_original_language_representations_have_distinct_ids() -> None:
    common = {
        "corpus_scope": ["hebrew"],
        "analysis_profile": "edition_complete",
        "analysis_reading": "qere",
        "granularity": "verse",
        "token_eligibility_policy_sha256": SHA,
        "frequency_scope": "language_and_representation",
        "normalization_config_sha256": SHA,
    }
    original = build_representation_identity(
        RepresentationIdentityPayload(
            **common,
            representation_kind="original_language",
            feature_families=["lemma"],
        )
    )
    english = build_representation_identity(
        RepresentationIdentityPayload(
            **common,
            representation_kind="english_derived",
            feature_families=["english_gloss"],
        )
    )

    assert original.identifier != english.identifier
    with pytest.raises(ValidationError, match="cannot contain English"):
        RepresentationIdentityPayload(
            **common,
            representation_kind="original_language",
            feature_families=["lemma", "english_gloss"],
        )


def test_collision_registry_and_preregistration_digest_fail_closed() -> None:
    registry = LexicalIdentityRegistry()
    registry.add(LexicalIdentity("LF_" + SHA, SHA, '{"value":1}'))

    with pytest.raises(LexicalIdentityCollisionError, match="distinct lexical payloads"):
        registry.add(LexicalIdentity("LF_" + SHA, SHA, '{"value":2}'))

    preregistration = load_lexical_preregistration()
    assert preregistration_digest(preregistration) == preregistration.preregistration_sha256
