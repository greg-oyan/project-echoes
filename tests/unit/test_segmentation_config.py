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
