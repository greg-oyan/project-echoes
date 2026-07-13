"""Segmentation source-order, disputed-text, and boundary-policy tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from echoes.settings import (
    AnalyticalBoundaryBreak,
    SegmentationConfig,
    SourceVerseSuccessor,
    load_config,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_config() -> SegmentationConfig:
    loaded = load_config(PROJECT_ROOT / "config" / "segmentation.yaml")
    assert isinstance(loaded, SegmentationConfig)
    return loaded


def _project_payload() -> dict[str, Any]:
    return deepcopy(_project_config().model_dump(mode="python"))


def test_active_schema_v3_enables_every_required_stream_and_granularity() -> None:
    config = _project_config()

    assert config.schema_version == 3
    assert config.status == "active"
    assert set(config.enabled_corpora) == {"hebrew", "greek"}
    assert set(config.enabled_analysis_profiles) == {"edition_complete", "critical_core"}
    assert set(config.enabled_analysis_readings.hebrew) == {"qere", "ketiv"}
    assert config.enabled_analysis_readings.greek == ["source"]
    assert set(config.granularities) == {
        "clause",
        "sentence",
        "verse",
        "two_verse",
        "five_verse",
    }


def test_window_policy_prohibits_partial_unsafe_or_bridged_windows() -> None:
    policy = _project_config().window_policy

    assert policy.cross_chapter_boundaries
    assert not policy.cross_book_boundaries
    assert not policy.emit_partial_windows
    assert not policy.bridge_profile_exclusions
    assert not policy.bridge_analytical_boundary_breaks
    assert policy.allow_source_order_reference_gaps
    assert policy.mark_reference_gaps
    assert policy.minimum_verse_count == 2
    assert policy.maximum_verse_count == 5
    assert policy.window_sizes == {"two_verse": 2, "five_verse": 5}


def test_ketiv_reconstruction_identity_and_storage_policies_are_explicit() -> None:
    config = _project_config()

    ketiv = config.ketiv_policy
    assert ketiv.verse_include_every_token
    assert ketiv.sentence_use_resolved_mapping
    assert ketiv.clause_use_resolved_mapping_only
    assert ketiv.unresolved_clause_action == "explicit_exclusion"
    assert ketiv.unresolved_phrase_action == "flag_only"
    assert ketiv.never_fabricate_structure
    assert ketiv.preserve_excluded_tokens_in_verse_analysis
    assert ketiv.record_affected_token_ids

    assert config.reconstruction_policy.language_aware
    assert not config.reconstruction_policy.universal_space_join
    assert config.zero_width_token_policy.include_in_membership
    assert not config.zero_width_token_policy.contributes_visible_text
    assert config.punctuation_reconstruction_policy.use_leading_punctuation
    assert config.punctuation_reconstruction_policy.use_trailing_punctuation

    identity = config.passage_identity
    assert identity.schema_version == 1
    assert identity.digest_algorithm == "sha256"
    assert identity.collision_action == "error"
    assert not identity.include_segmentation_config_hash
    assert identity.digest_hex_length == 64
    assert identity.canonical_payload_fields[-1] == "token_ids"

    output = config.output_partitioning
    assert output.schema_directory == "data/processed/passages/schema-v1"
    assert output.partition_by == [
        "corpus",
        "analysis_profile",
        "analysis_reading",
        "granularity",
    ]
    assert output.atomic_writes
    assert output.overwrite_requires_force


def test_mark_source_successor_is_not_an_analytical_adjacency() -> None:
    config = _project_config()

    assert len(config.source_successors) == 1
    successor = config.source_successors[0]
    assert successor.source_id == "macula-greek"
    assert successor.corpus == "greek"
    assert successor.from_reference == "MRK 16:20"
    assert successor.to_reference == "MRK 16:99"
    assert successor.relation == "alternate_ending"
    assert successor.reference_gap

    matching_breaks = [
        boundary
        for boundary in config.analytical_boundary_breaks
        if (boundary.corpus, boundary.from_reference, boundary.to_reference)
        == (successor.corpus, successor.from_reference, successor.to_reference)
    ]
    assert len(matching_breaks) == 1
    assert set(matching_breaks[0].prohibited_window_granularities) == {
        "two_verse",
        "five_verse",
    }


def test_disputed_passages_and_analysis_profiles_are_explicit() -> None:
    config = _project_config()
    passages = {passage.passage_id: passage for passage in config.disputed_passages}

    assert {
        passage_id: (
            passage.start_reference,
            passage.end_reference,
            passage.classification,
            passage.source_presence,
        )
        for passage_id, passage in passages.items()
    } == {
        "mark_longer_ending": ("MRK 16:9", "MRK 16:20", "longer_ending", "inline"),
        "mark_alternate_ending": (
            "MRK 16:99",
            "MRK 16:99",
            "alternate_ending",
            "inline",
        ),
        "pericope_adulterae": (
            "JHN 7:53",
            "JHN 8:11",
            "pericope_adulterae",
            "inline",
        ),
    }

    profiles = {profile.name: profile for profile in config.analysis_profiles}
    assert config.default_analysis_profile == "edition_complete"
    assert profiles["edition_complete"].base_stream == "source_inline"
    assert profiles["edition_complete"].excluded_disputed_passage_ids == []
    assert set(profiles["critical_core"].excluded_disputed_passage_ids) == set(passages)


def test_reference_gap_and_future_candidate_policies_are_pinned() -> None:
    config = _project_config()
    gap_policy = config.reference_gap_policy

    assert not gap_policy.fabricate_omitted_references
    assert gap_policy.allow_source_order_adjacency_across_numbering_gaps
    assert gap_policy.mark_reference_gap
    assert not gap_policy.concatenate_alternate_readings_from_source_order

    candidate_policy = config.disputed_candidate_policy
    assert candidate_policy.flag_candidates
    assert candidate_policy.candidate_flag_field == "disputed_passage_flag"
    assert candidate_policy.strong_candidate_requires == (
        "survives_disputed_text_exclusion_or_completed_textual_criticism_review"
    )


def test_source_successor_must_stay_inside_one_book() -> None:
    with pytest.raises(ValidationError, match="inside one book"):
        SourceVerseSuccessor(
            source_id="macula-greek",
            corpus="greek",
            from_reference="MRK 16:20",
            to_reference="LUK 1:1",
            relation="alternate_ending",
            reference_gap=True,
            reason="invalid",
        )


def test_source_successor_requires_two_distinct_references() -> None:
    with pytest.raises(ValidationError, match="distinct references"):
        SourceVerseSuccessor(
            source_id="macula-greek",
            corpus="greek",
            from_reference="MRK 16:20",
            to_reference="MRK 16:20",
            relation="alternate_ending",
            reference_gap=False,
            reason="invalid",
        )


def test_malformed_source_successor_reference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="from_reference"):
        SourceVerseSuccessor(
            source_id="macula-greek",
            corpus="greek",
            from_reference="Mark sixteen twenty",
            to_reference="MRK 16:99",
            relation="alternate_ending",
            reference_gap=True,
            reason="invalid",
        )


def test_duplicate_source_successors_are_rejected() -> None:
    payload = _project_payload()
    payload["source_successors"].append(deepcopy(payload["source_successors"][0]))

    with pytest.raises(ValidationError, match="source_successors must be unique"):
        SegmentationConfig.model_validate(payload)


def test_duplicate_analytical_boundaries_are_rejected() -> None:
    payload = _project_payload()
    payload["analytical_boundary_breaks"].append(deepcopy(payload["analytical_boundary_breaks"][0]))

    with pytest.raises(ValidationError, match="analytical_boundary_breaks must be unique"):
        SegmentationConfig.model_validate(payload)


def test_duplicate_disputed_passage_ids_are_rejected() -> None:
    payload = _project_payload()
    payload["disputed_passages"].append(deepcopy(payload["disputed_passages"][0]))

    with pytest.raises(ValidationError, match="disputed passage IDs must be unique"):
        SegmentationConfig.model_validate(payload)


def test_boundary_window_granularities_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="window granularities must be unique"):
        AnalyticalBoundaryBreak(
            corpus="greek",
            from_reference="MRK 16:20",
            to_reference="MRK 16:99",
            prohibited_window_granularities=["two_verse", "two_verse"],
            reason="invalid",
        )


def test_alternate_ending_requires_a_matching_complete_boundary_break() -> None:
    payload = _project_payload()
    payload["analytical_boundary_breaks"] = []

    with pytest.raises(ValidationError, match="alternate-ending source successors"):
        SegmentationConfig.model_validate(payload)


def test_profile_cannot_exclude_an_undeclared_disputed_passage() -> None:
    payload = _project_payload()
    critical_core = next(
        profile for profile in payload["analysis_profiles"] if profile["name"] == "critical_core"
    )
    critical_core["excluded_disputed_passage_ids"].append("unknown_passage")

    with pytest.raises(ValidationError, match="unknown disputed passage IDs"):
        SegmentationConfig.model_validate(payload)


def test_edition_complete_cannot_exclude_inline_text() -> None:
    payload = _project_payload()
    edition_complete = next(
        profile for profile in payload["analysis_profiles"] if profile["name"] == "edition_complete"
    )
    edition_complete["excluded_disputed_passage_ids"] = ["mark_longer_ending"]

    with pytest.raises(ValidationError, match="must include all inline disputed passages"):
        SegmentationConfig.model_validate(payload)


def test_critical_core_must_exclude_every_disputed_passage() -> None:
    payload = _project_payload()
    critical_core = next(
        profile for profile in payload["analysis_profiles"] if profile["name"] == "critical_core"
    )
    critical_core["excluded_disputed_passage_ids"].remove("pericope_adulterae")

    with pytest.raises(ValidationError, match="must exclude every declared disputed passage"):
        SegmentationConfig.model_validate(payload)


def test_book_boundary_windows_are_rejected() -> None:
    payload = _project_payload()
    payload["window_policy"]["cross_book_boundaries"] = True

    with pytest.raises(ValidationError, match="cross_book_boundaries"):
        SegmentationConfig.model_validate(payload)


def test_partial_windows_are_rejected() -> None:
    payload = _project_payload()
    payload["window_policy"]["emit_partial_windows"] = True

    with pytest.raises(ValidationError, match="emit_partial_windows"):
        SegmentationConfig.model_validate(payload)


def test_alternate_endings_cannot_be_concatenated() -> None:
    payload = _project_payload()
    payload["reference_gap_policy"]["concatenate_alternate_readings_from_source_order"] = True

    with pytest.raises(
        ValidationError,
        match="concatenate_alternate_readings_from_source_order",
    ):
        SegmentationConfig.model_validate(payload)


def test_omitted_references_cannot_be_fabricated() -> None:
    payload = _project_payload()
    payload["reference_gap_policy"]["fabricate_omitted_references"] = True

    with pytest.raises(ValidationError, match="fabricate_omitted_references"):
        SegmentationConfig.model_validate(payload)


def test_unresolved_ketiv_structure_cannot_be_fabricated() -> None:
    payload = _project_payload()
    payload["ketiv_policy"]["never_fabricate_structure"] = False

    with pytest.raises(ValidationError, match="never_fabricate_structure"):
        SegmentationConfig.model_validate(payload)


def test_boundary_cannot_be_both_continuous_and_broken() -> None:
    payload = _project_payload()
    boundary = payload["analytical_boundary_breaks"][0]
    payload["analytical_continuities"].append(
        {
            "corpus": boundary["corpus"],
            "from_reference": boundary["from_reference"],
            "to_reference": boundary["to_reference"],
            "reason": "contradictory declaration",
        }
    )

    with pytest.raises(ValidationError, match="both analytically continuous and broken"):
        SegmentationConfig.model_validate(payload)


def test_unknown_enabled_profile_is_rejected() -> None:
    payload = _project_payload()
    payload["enabled_analysis_profiles"].append("unknown_profile")

    with pytest.raises(ValidationError, match="enabled_analysis_profiles"):
        SegmentationConfig.model_validate(payload)


def test_unknown_granularity_is_rejected() -> None:
    payload = _project_payload()
    payload["granularities"].append("paragraph")

    with pytest.raises(ValidationError, match="granularities"):
        SegmentationConfig.model_validate(payload)


def test_critical_core_references_must_resolve_to_declared_ranges() -> None:
    payload = _project_payload()
    payload["critical_core_exclusions"][0]["start_reference"] = "MRK 16:10"

    with pytest.raises(ValidationError, match="references must resolve"):
        SegmentationConfig.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minimum_verse_count", 3),
        ("maximum_verse_count", 4),
    ],
)
def test_invalid_window_size_bounds_are_rejected(field: str, value: int) -> None:
    payload = _project_payload()
    payload["window_policy"][field] = value

    with pytest.raises(ValidationError, match="window size bounds"):
        SegmentationConfig.model_validate(payload)


def test_invalid_named_window_size_is_rejected() -> None:
    payload = _project_payload()
    payload["window_policy"]["window_sizes"]["two_verse"] = 3

    with pytest.raises(ValidationError, match="window sizes must be exactly"):
        SegmentationConfig.model_validate(payload)


def test_default_profile_must_be_declared() -> None:
    payload = _project_payload()
    payload["analysis_profiles"] = [
        profile
        for profile in payload["analysis_profiles"]
        if profile["name"] != payload["default_analysis_profile"]
    ]

    with pytest.raises(ValidationError, match="default analysis profile must be declared"):
        SegmentationConfig.model_validate(payload)
