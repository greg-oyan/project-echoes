"""Segmentation configuration and verse-adjacency declaration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from echoes.settings import NonContiguousVerseAdjacency, SegmentationConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_project_segmentation_declares_the_mark_ending_adjacency() -> None:
    config = load_config(PROJECT_ROOT / "config" / "segmentation.yaml")

    assert isinstance(config, SegmentationConfig)
    adjacencies = config.non_contiguous_verse_adjacencies
    assert len(adjacencies) == 1
    adjacency = adjacencies[0]
    assert adjacency.corpus == "greek"
    assert adjacency.from_reference == "MRK 16:20"
    assert adjacency.to_reference == "MRK 16:99"
    assert "shorter ending" in adjacency.reason


def test_adjacency_must_stay_inside_one_book() -> None:
    with pytest.raises(ValidationError, match="inside one book"):
        NonContiguousVerseAdjacency(
            corpus="greek",
            from_reference="MRK 16:20",
            to_reference="LUK 1:1",
            reason="invalid",
        )


def test_adjacency_requires_two_distinct_references() -> None:
    with pytest.raises(ValidationError, match="distinct references"):
        NonContiguousVerseAdjacency(
            corpus="greek",
            from_reference="MRK 16:20",
            to_reference="MRK 16:20",
            reason="invalid",
        )


def test_malformed_reference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="from_reference"):
        NonContiguousVerseAdjacency(
            corpus="greek",
            from_reference="Mark sixteen twenty",
            to_reference="MRK 16:99",
            reason="invalid",
        )


def test_duplicate_adjacencies_are_rejected() -> None:
    adjacency = {
        "corpus": "greek",
        "from_reference": "MRK 16:20",
        "to_reference": "MRK 16:99",
        "reason": "duplicate",
    }
    with pytest.raises(ValidationError, match="must be unique"):
        SegmentationConfig(
            schema_version=1,
            status="planned",
            granularities=["verse"],
            preserve_token_boundaries=True,
            non_contiguous_verse_adjacencies=[adjacency, adjacency],
        )
