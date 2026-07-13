"""Run identity and safe selection tests for passage segmentation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import polars as pl
import pytest

from echoes.segment.pipeline import (
    PassagePipelineError,
    SegmentationSelection,
    _iter_book_streams,
    _stream_groups,
    create_run_context,
    segmentation_config_fingerprint,
)
from echoes.segment.streams import InputDigestSet, SegmentationInputs
from echoes.settings import SegmentationConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _config() -> SegmentationConfig:
    loaded = load_config(PROJECT_ROOT / "config" / "segmentation.yaml")
    assert isinstance(loaded, SegmentationConfig)
    return loaded


def _inputs() -> SegmentationInputs:
    empty = pl.DataFrame()
    return SegmentationInputs(
        hebrew_tokens=empty,
        greek_tokens=empty,
        ketiv_tokens=empty,
        locus_registry=empty,
        structural_alignments=empty,
        source_versions={"macula-hebrew": "h", "macula-greek": "g", "oshb-morphhb": "o"},
        digests=InputDigestSet(
            hebrew_identity="1" * 64,
            hebrew_content="2" * 64,
            hebrew_analytical="3" * 64,
            greek_identity="4" * 64,
            greek_content="5" * 64,
            greek_analytical="6" * 64,
            oshb_logical={"ketiv_tokens": "7" * 64},
        ),
    )


def test_all_selection_expands_to_every_required_stream() -> None:
    streams = SegmentationSelection(all_streams=True).selected_streams()

    assert len(streams) == 6
    assert ("hebrew", "edition_complete", "qere") in streams
    assert ("greek", "critical_core", "source") in streams


def test_stream_groups_reuse_one_base_for_both_profiles() -> None:
    groups = _stream_groups(SegmentationSelection(all_streams=True).selected_streams())

    assert groups == (
        ("hebrew", "qere", ("edition_complete", "critical_core")),
        ("hebrew", "ketiv", ("edition_complete", "critical_core")),
        ("greek", "source", ("edition_complete", "critical_core")),
    )


def test_book_streams_are_complete_contiguous_slices() -> None:
    stream = pl.DataFrame(
        {
            "book": ["GEN", "GEN", "EXO", "EXO", "EXO"],
            "token": [1, 2, 3, 4, 5],
        }
    )

    slices = list(_iter_book_streams(stream))

    assert [frame["book"].unique().to_list() for frame in slices] == [["GEN"], ["EXO"]]
    assert pl.concat(slices).equals(stream)


def test_noncontiguous_book_stream_fails() -> None:
    stream = pl.DataFrame({"book": ["GEN", "EXO", "GEN"], "token": [1, 2, 3]})

    with pytest.raises(PassagePipelineError, match="not contiguous"):
        list(_iter_book_streams(stream))


def test_ambiguous_or_contradictory_selection_fails() -> None:
    with pytest.raises(PassagePipelineError, match="cannot be combined"):
        SegmentationSelection(all_streams=True, corpus="hebrew").selected_streams()
    with pytest.raises(PassagePipelineError, match="provide --corpus"):
        SegmentationSelection(corpus="hebrew").selected_streams()
    with pytest.raises(PassagePipelineError, match="qere or ketiv"):
        SegmentationSelection(
            corpus="hebrew",
            analysis_profile="edition_complete",
            analysis_reading="source",
        ).selected_streams()


def test_run_id_is_stable_and_excludes_output_path() -> None:
    config = _config()
    selection = SegmentationSelection(all_streams=True)
    first = create_run_context(config=config, selection=selection, inputs=_inputs())
    second = create_run_context(config=config, selection=selection, inputs=_inputs())
    payload = deepcopy(config.model_dump(mode="python"))
    payload["output_partitioning"]["schema_directory"] = "elsewhere/generated"
    moved = SegmentationConfig.model_validate(payload)
    moved_context = create_run_context(config=moved, selection=selection, inputs=_inputs())

    assert first.run_id == second.run_id == moved_context.run_id
    assert first.config_hash == moved_context.config_hash


def test_relevant_policy_change_changes_config_fingerprint_and_run_id() -> None:
    config = _config()
    payload = deepcopy(config.model_dump(mode="python"))
    payload["default_analysis_profile"] = "critical_core"
    changed = SegmentationConfig.model_validate(payload)

    assert segmentation_config_fingerprint(config) != segmentation_config_fingerprint(changed)
    assert (
        create_run_context(
            config=config,
            selection=SegmentationSelection(all_streams=True),
            inputs=_inputs(),
        ).run_id
        != create_run_context(
            config=changed,
            selection=SegmentationSelection(all_streams=True),
            inputs=_inputs(),
        ).run_id
    )
