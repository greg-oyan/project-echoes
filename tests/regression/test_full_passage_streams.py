"""Opt-in full-corpus regression anchors for Milestone 5 token streams."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest

from echoes.segment.streams import (
    GREEK_ANALYTICAL_DIGEST,
    GREEK_CONTENT_DIGEST,
    GREEK_IDENTITY_DIGEST,
    HEBREW_ANALYTICAL_DIGEST,
    HEBREW_CONTENT_DIGEST,
    HEBREW_IDENTITY_DIGEST,
    OSHB_LOGICAL_DIGESTS,
    InputDigestSet,
    SegmentationInputs,
    build_required_analysis_streams,
    load_segmentation_inputs,
)
from echoes.settings import SegmentationConfig, load_config

pytestmark = [
    pytest.mark.full_corpus,
    pytest.mark.skipif(
        os.environ.get("ECHOES_RUN_FULL_CORPUS") != "1",
        reason="set ECHOES_RUN_FULL_CORPUS=1 after governed local corpus ingestion",
    ),
]

EXPECTED_SOURCE_VERSIONS = {
    "macula-hebrew": "7ab368fcb14e4ad2e0f784138241a098fb516ec4",
    "macula-greek": "b5b7ecec0882a3e9a609ecac99e157391e5d9b46",
    "oshb-morphhb": "3d15126fb1ef74867fc1434be1942e837932691f",
}
EXPECTED_STREAM_COUNTS = {
    ("hebrew", "edition_complete", "qere"): 475_911,
    ("hebrew", "edition_complete", "ketiv"): 474_932,
    ("hebrew", "critical_core", "qere"): 475_911,
    ("hebrew", "critical_core", "ketiv"): 474_932,
    ("greek", "edition_complete", "source"): 137_779,
    ("greek", "critical_core", "source"): 137_389,
}


@dataclass(frozen=True, slots=True)
class FullStreams:
    """Full streams plus immutable source snapshots used to detect mutation."""

    inputs: SegmentationInputs
    streams: dict[tuple[str, str, str], pl.DataFrame]
    hebrew_before: pl.DataFrame
    greek_before: pl.DataFrame
    ketiv_before: pl.DataFrame
    registry_before: pl.DataFrame
    structural_before: pl.DataFrame


@pytest.fixture(scope="module")
def full_streams() -> FullStreams:
    loaded = load_config(Path("config/segmentation.yaml"))
    assert isinstance(loaded, SegmentationConfig)
    inputs = load_segmentation_inputs()
    snapshots = (
        inputs.hebrew_tokens.clone(),
        inputs.greek_tokens.clone(),
        inputs.ketiv_tokens.clone(),
        inputs.locus_registry.clone(),
        inputs.structural_alignments.clone(),
    )
    streams = build_required_analysis_streams(inputs, config=loaded)
    return FullStreams(inputs, streams, *snapshots)


def test_full_stream_inputs_match_every_pinned_anchor(full_streams: FullStreams) -> None:
    assert full_streams.inputs.source_versions == EXPECTED_SOURCE_VERSIONS
    assert full_streams.inputs.digests == InputDigestSet(
        hebrew_identity=HEBREW_IDENTITY_DIGEST,
        hebrew_content=HEBREW_CONTENT_DIGEST,
        hebrew_analytical=HEBREW_ANALYTICAL_DIGEST,
        greek_identity=GREEK_IDENTITY_DIGEST,
        greek_content=GREEK_CONTENT_DIGEST,
        greek_analytical=GREEK_ANALYTICAL_DIGEST,
        oshb_logical=OSHB_LOGICAL_DIGESTS,
    )


def test_all_six_full_stream_counts_and_token_ids_are_exact(full_streams: FullStreams) -> None:
    observed = {key: stream.height for key, stream in full_streams.streams.items()}

    assert observed == EXPECTED_STREAM_COUNTS
    for stream in full_streams.streams.values():
        assert stream["token_id"].n_unique() == stream.height


def test_full_stream_derivation_does_not_mutate_any_source_frame(
    full_streams: FullStreams,
) -> None:
    assert full_streams.inputs.hebrew_tokens.equals(full_streams.hebrew_before)
    assert full_streams.inputs.greek_tokens.equals(full_streams.greek_before)
    assert full_streams.inputs.ketiv_tokens.equals(full_streams.ketiv_before)
    assert full_streams.inputs.locus_registry.equals(full_streams.registry_before)
    assert full_streams.inputs.structural_alignments.equals(full_streams.structural_before)


def test_every_oshb_ketiv_token_is_available_to_future_verse_generation(
    full_streams: FullStreams,
) -> None:
    ketiv = full_streams.streams[("hebrew", "edition_complete", "ketiv")]
    input_ids = set(full_streams.inputs.ketiv_tokens["token_id"].to_list())
    stream_ids = set(ketiv["token_id"].to_list())

    assert input_ids <= stream_ids
    assert ketiv.filter(pl.col("source_id") == "oshb-morphhb").height == 1_268


def test_full_ketiv_field_level_uncertainty_counts_are_pinned(
    full_streams: FullStreams,
) -> None:
    ketiv = full_streams.streams[("hebrew", "edition_complete", "ketiv")].filter(
        pl.col("source_id") == "oshb-morphhb"
    )

    assert ketiv.filter(pl.col("clause_resolution_status") == "unresolved").height == 255
    assert ketiv.filter(pl.col("phrase_resolution_status") == "unresolved").height == 818
    assert ketiv.filter(pl.col("sentence_resolution_status") == "unresolved").height == 0


def test_full_critical_core_keeps_source_gaps_as_no_bridge_markers(
    full_streams: FullStreams,
) -> None:
    edition = full_streams.streams[("greek", "edition_complete", "source")]
    critical = full_streams.streams[("greek", "critical_core", "source")]

    assert (
        edition.filter(pl.col("canonical_reference").is_in(["MRK 16:20", "MRK 16:99"])).height > 0
    )
    assert critical.filter(
        pl.col("canonical_reference").is_in(
            ["MRK 16:9", "MRK 16:20", "MRK 16:99", "JHN 7:53", "JHN 8:11"]
        )
    ).is_empty()

    john_neighbors = (
        critical.filter(pl.col("canonical_reference").is_in(["JHN 7:52", "JHN 8:12"]))
        .group_by("canonical_reference")
        .agg(
            pl.col("stream_position_in_corpus").min().alias("stream_start"),
            pl.col("verse_ordinal_in_book").first().alias("verse_ordinal"),
        )
        .sort("stream_start")
    )
    assert john_neighbors["canonical_reference"].to_list() == ["JHN 7:52", "JHN 8:12"]
    assert john_neighbors["stream_start"][1] - john_neighbors["stream_start"][0] > 1
    assert john_neighbors["verse_ordinal"][1] - john_neighbors["verse_ordinal"][0] > 1
