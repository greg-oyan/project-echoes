"""Strict public-field tests for the Build Week demonstration exporter."""

from __future__ import annotations

from copy import deepcopy

import pytest

from echoes.reports.build_week_demo import (
    BuildWeekDemoError,
    validate_public_demo_payloads,
)


def _payloads() -> dict[str, object]:
    return {
        "overview.json": {
            "export_schema_version": 1,
            "export_name": "echoes-demo-v1",
            "run_identity": {
                "lexical_run_id": "lexical-v1-test",
                "configuration_sha256": "a" * 64,
                "preregistration_sha256": "b" * 64,
            },
            "corpus_counts": {"hebrew_tokens": 1, "greek_tokens": 1},
            "passage_counts": [],
            "benchmark_counts": {"tier3_relationships": 1},
            "detectors": ["tfidf_cosine", "bm25"],
            "feature_coverage": [],
            "null_model_summary": {
                "registered_iterations_per_family": 100,
                "families": [],
            },
            "candidate_counts": [],
            "tier3_global_performance": [],
            "source_attribution": [
                {
                    "source_id": "macula-hebrew",
                    "source_name": "MACULA Hebrew Linguistic Datasets",
                    "version_or_commit": "test-version",
                    "repository_or_location": "https://example.test/source",
                    "license": "Test license metadata",
                    "license_url": "https://example.test/license",
                    "required_attribution": "Test attribution",
                    "public_use": "Aggregate identifiers and statistics only.",
                }
            ],
            "scientific_caveats": ["Tier 3 weak supervision only."],
            "no_candidate_review": True,
        },
        "known-recoveries.json": {
            "export_schema_version": 1,
            "selection_procedure": "Stable registered ordering.",
            "requested_count": 20,
            "actual_count": 0,
            "no_candidate_review": True,
            "scientific_caveat": "No scholarly-ground-truth claim.",
            "pairs": [],
        },
        "unreviewed-candidates.json": {
            "export_schema_version": 1,
            "selection_procedure": "Frozen queue order.",
            "requested_count": 50,
            "actual_count": 0,
            "no_candidate_review": True,
            "scientific_caveat": "No novelty claim.",
            "pairs": [],
        },
        "textual-uncertainty-examples.json": {
            "export_schema_version": 1,
            "selection_procedure": "Stable registered ordering.",
            "actual_count": 1,
            "examples": [
                {
                    "example_kind": "qere_ketiv",
                    "sensitivity_id": "LS_test",
                    "corpus_pair": "hb_hb",
                    "detector": "tfidf_cosine",
                    "direction": "forward",
                    "baseline_profile": "edition_complete",
                    "comparison_profile": "edition_complete",
                    "baseline_reading": "qere",
                    "comparison_reading": "ketiv",
                    "query_reference": "GEN 1:1",
                    "target_reference": "GEN 1:2",
                    "baseline_query_passage_id": "P_HB_TEST_A",
                    "comparison_query_passage_id": "P_HB_TEST_B",
                    "baseline_target_passage_id": "P_HB_TEST_C",
                    "comparison_target_passage_id": "P_HB_TEST_D",
                    "baseline_score": 0.5,
                    "comparison_score": 0.4,
                    "score_delta": -0.1,
                    "baseline_rank": 1,
                    "comparison_rank": 2,
                    "rank_delta": 1,
                    "top_k_overlap": 0.9,
                    "affected_locus_count": 1,
                    "disputed_passage_flag": False,
                    "excluded_reason": None,
                    "baseline_sequence_digest": "c" * 64,
                    "comparison_sequence_digest": "d" * 64,
                    "explanatory_metadata": "Identifiers and score changes only.",
                }
            ],
            "unavailable_categories": [],
            "no_interpretive_decision": True,
        },
    }


def test_minimal_public_demo_payload_is_valid() -> None:
    validate_public_demo_payloads(_payloads())


@pytest.mark.parametrize(
    "field",
    [
        "feature_value",
        "lemma_value",
        "root_value",
        "source_text",
        "reconstructed_text",
        "english_gloss",
        "morphology",
        "source_file",
        "local_path",
        "raw_record",
        "excerpt",
        "notes",
    ],
)
def test_public_demo_rejects_prohibited_or_unresolved_redistribution_fields(
    field: str,
) -> None:
    payloads = deepcopy(_payloads())
    overview = payloads["overview.json"]
    assert isinstance(overview, dict)
    attribution = overview["source_attribution"]
    assert isinstance(attribution, list)
    source = attribution[0]
    assert isinstance(source, dict)
    source[field] = "must not enter the public bundle"

    with pytest.raises(BuildWeekDemoError, match="prohibited"):
        validate_public_demo_payloads(payloads)


def test_public_demo_rejects_source_script_text_even_under_an_allowed_key() -> None:
    payloads = deepcopy(_payloads())
    overview = payloads["overview.json"]
    assert isinstance(overview, dict)
    caveats = overview["scientific_caveats"]
    assert isinstance(caveats, list)
    caveats.append("\u05d0\u05b8\u05d1")

    with pytest.raises(BuildWeekDemoError, match="source-script text"):
        validate_public_demo_payloads(payloads)


def test_public_demo_rejects_private_absolute_paths() -> None:
    payloads = deepcopy(_payloads())
    overview = payloads["overview.json"]
    assert isinstance(overview, dict)
    caveats = overview["scientific_caveats"]
    assert isinstance(caveats, list)
    caveats.append("Generated from C:\\private\\source.xml")

    with pytest.raises(BuildWeekDemoError, match="absolute local path"):
        validate_public_demo_payloads(payloads)


def test_public_demo_requires_a_qere_ketiv_uncertainty_example() -> None:
    payloads = deepcopy(_payloads())
    uncertainty = payloads["textual-uncertainty-examples.json"]
    assert isinstance(uncertainty, dict)
    uncertainty["examples"] = []
    uncertainty["actual_count"] = 0

    with pytest.raises(BuildWeekDemoError, match="Qere/Ketiv"):
        validate_public_demo_payloads(payloads)


def test_public_demo_rejects_unexpected_top_level_fields() -> None:
    payloads = deepcopy(_payloads())
    known = payloads["known-recoveries.json"]
    assert isinstance(known, dict)
    known["review_decision"] = "accepted"

    with pytest.raises(BuildWeekDemoError, match="fields differ"):
        validate_public_demo_payloads(payloads)
