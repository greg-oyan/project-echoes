"""Strict lexical settings and frozen preregistration governance."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from echoes.lexical.config import (
    LEXICAL_CONFIG_PATH,
    LEXICAL_PREREGISTRATION_PATH,
    LexicalConfig,
    LexicalConfigError,
    LexicalExperimentPreregistration,
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
    preregistration_payload_sha256,
    validate_preregistration_against_config,
)
from echoes.settings import load_config, validate_config_directory


def _mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return copy.deepcopy(loaded)


def test_production_lexical_config_and_preregistration_validate() -> None:
    config = load_lexical_config()
    preregistration = load_lexical_preregistration()

    assert isinstance(load_config(LEXICAL_CONFIG_PATH), LexicalConfig)
    assert isinstance(load_config(LEXICAL_PREREGISTRATION_PATH), LexicalExperimentPreregistration)
    assert config.primary_scope.granularity == "verse"
    assert config.feature_namespaces.hebrew_lemma == "hb:lemma"
    assert config.feature_namespaces.greek_lemma == "gk:lemma"
    assert config.null_models.iterations_per_family == 100
    assert config.null_models.calibration_pair_sample_size == 20_000
    assert config.null_models.global_all_pairs_calibration_claim_allowed is False
    assert config.retrieval.expensive_sequence_rerank_k == 25
    assert config.retrieval.persisted_candidate_pool_k == 25
    assert config.resource_limits.maximum_memory_bytes == 6 * 1024**3
    assert config.sensitivity_scopes.critical_core_greek.corpus_pairs == [
        "gnt_gnt",
        "hb_gnt_english_bridge",
    ]
    assert config.sensitivity_scopes.critical_core_greek.repeated_nulls is False
    assert (
        config.sensitivity_scopes.hebrew_qere_ketiv.query_scope == "oshb_affected_verse_references"
    )
    assert config.benchmark_evaluation.split_strategies[-1] == "held_out_genre"
    assert config.benchmark_evaluation.minimum_eligible_queries_per_primary_stratum == 100
    assert preregistration.preregistration_sha256 == lexical_preregistration_sha256(preregistration)
    assert preregistration.lexical_config_sha256 == lexical_config_sha256(config)
    validate_preregistration_against_config(preregistration, config)
    assert LEXICAL_CONFIG_PATH in validate_config_directory(Path("config"))


def _direct_hebrew_greek(values: dict[str, Any]) -> None:
    values["feature_namespaces"]["direct_hebrew_greek_lemma_matching"] = True


def _missing_namespace(values: dict[str, Any]) -> None:
    del values["feature_namespaces"]["greek_lemma"]


def _english_marked_original(values: dict[str, Any]) -> None:
    values["english_features"]["evidence_class"] = "original_language"


def _english_without_ablation(values: dict[str, Any]) -> None:
    values["english_features"]["require_ablation"] = False


def _missing_rare_threshold(values: dict[str, Any]) -> None:
    del values["rare_evidence"]["maximum_corpus_frequency"]


def _insufficient_null_iterations(values: dict[str, Any]) -> None:
    values["null_models"]["iterations_per_family"] = 0


def _one_null_family(values: dict[str, Any]) -> None:
    del values["null_models"]["frequency_preserving_synthetic"]


def _order_shuffle_null(values: dict[str, Any]) -> None:
    values["null_models"]["within_book_reassignment"]["label_or_order_shuffle"] = True


def _missing_null_seed(values: dict[str, Any]) -> None:
    del values["null_models"]["within_book_reassignment"]["seed"]


def _candidate_union_too_small(values: dict[str, Any]) -> None:
    values["retrieval"]["candidate_union_k"] = 99


def _evaluation_below_twenty(values: dict[str, Any]) -> None:
    values["retrieval"]["evaluation_k"] = 19


def _learned_composite(values: dict[str, Any]) -> None:
    values["composite"]["learned_model_allowed"] = True


def _missing_quantization(values: dict[str, Any]) -> None:
    del values["statistics"]["score_quantization_decimals"]


def _missing_tie_break(values: dict[str, Any]) -> None:
    del values["retrieval"]["tie_break"]


def _openbible_tier_one(values: dict[str, Any]) -> None:
    values["benchmark_evaluation"]["tier"] = 1


def _openbible_high_confidence(values: dict[str, Any]) -> None:
    values["benchmark_evaluation"]["high_confidence_benchmark"] = True


def _missing_leakage_enforcement(values: dict[str, Any]) -> None:
    values["benchmark_evaluation"]["enforce_leakage_groups"] = False


def _allow_test_tuning(values: dict[str, Any]) -> None:
    values["benchmark_evaluation"]["test_set_tuning_allowed"] = True


def _unsupported_primary_granularity(values: dict[str, Any]) -> None:
    values["primary_scope"]["granularity"] = "chapter"


def _negative_resource_limit(values: dict[str, Any]) -> None:
    values["resource_limits"]["maximum_memory_bytes"] = -1


def _threshold_without_null_calibration(values: dict[str, Any]) -> None:
    values["candidate_thresholds"]["require_both_null_families"] = False


def _single_rare_item_qualifies(values: dict[str, Any]) -> None:
    values["rare_evidence"]["single_rare_item_sufficient"] = True


def _global_null_calibration_claim(values: dict[str, Any]) -> None:
    values["null_models"]["global_all_pairs_calibration_claim_allowed"] = True


def _invalid_formulaic_threshold(values: dict[str, Any]) -> None:
    values["feature_frequency_thresholds"]["formulaic_document_frequency_ratio"] = 0.2


def _select_model_from_ablation(values: dict[str, Any]) -> None:
    values["ablations"]["select_new_model_from_ablation_results"] = True


def _candidate_pool_below_sequence_rerank(values: dict[str, Any]) -> None:
    values["retrieval"]["persisted_candidate_pool_k"] = 24


def _sensitivity_repeats_nulls(values: dict[str, Any]) -> None:
    values["sensitivity_scopes"]["critical_core_greek"]["repeated_nulls"] = True


def _ketiv_sensitivity_is_not_locus_bounded(values: dict[str, Any]) -> None:
    values["sensitivity_scopes"]["hebrew_qere_ketiv"]["query_scope"] = "all_verses"


@pytest.mark.parametrize(
    "mutation",
    [
        _direct_hebrew_greek,
        _missing_namespace,
        _english_marked_original,
        _english_without_ablation,
        _missing_rare_threshold,
        _insufficient_null_iterations,
        _one_null_family,
        _order_shuffle_null,
        _missing_null_seed,
        _candidate_union_too_small,
        _evaluation_below_twenty,
        _learned_composite,
        _missing_quantization,
        _missing_tie_break,
        _openbible_tier_one,
        _openbible_high_confidence,
        _missing_leakage_enforcement,
        _allow_test_tuning,
        _unsupported_primary_granularity,
        _negative_resource_limit,
        _threshold_without_null_calibration,
        _single_rare_item_qualifies,
        _global_null_calibration_claim,
        _invalid_formulaic_threshold,
        _select_model_from_ablation,
        _candidate_pool_below_sequence_rerank,
        _sensitivity_repeats_nulls,
        _ketiv_sensitivity_is_not_locus_bounded,
    ],
    ids=lambda mutation: mutation.__name__.removeprefix("_"),
)
def test_unsafe_lexical_configurations_are_rejected(mutation: Any) -> None:
    values = _mapping(LEXICAL_CONFIG_PATH)
    mutation(values)

    with pytest.raises(ValidationError):
        LexicalConfig.model_validate(values)


def test_preregistration_digest_is_order_independent_and_tamper_evident() -> None:
    values = _mapping(LEXICAL_PREREGISTRATION_PATH)
    expected = values["preregistration_sha256"]
    reordered = dict(reversed(list(values.items())))

    assert preregistration_payload_sha256(values) == expected
    assert preregistration_payload_sha256(reordered) == expected

    values["bootstrap_seed"] += 1
    with pytest.raises(ValidationError, match="preregistration_sha256"):
        LexicalExperimentPreregistration.model_validate(values)


def test_preregistration_rejects_active_config_drift() -> None:
    preregistration = load_lexical_preregistration()
    values = _mapping(LEXICAL_CONFIG_PATH)
    values["bm25"]["k1"] = 1.3
    drifted = LexicalConfig.model_validate(values)

    with pytest.raises(LexicalConfigError, match="lexical_config_sha256"):
        validate_preregistration_against_config(preregistration, drifted)
