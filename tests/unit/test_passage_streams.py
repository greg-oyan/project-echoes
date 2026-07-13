"""Synthetic tests for governed passage-analysis streams and profiles."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from echoes.align.supplementary import STRUCTURAL_ALIGNMENT_SCHEMA
from echoes.corpus.greek_models import GREEK_TOKEN_POLARS_SCHEMA, CanonicalGreekToken
from echoes.corpus.models import CANONICAL_TOKEN_POLARS_SCHEMA, CanonicalToken, Language
from echoes.segment.streams import (
    InputDigestSet,
    SegmentationInputError,
    SegmentationInputs,
    apply_analysis_profile,
    build_required_analysis_streams,
)
from echoes.settings import SegmentationConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _hebrew_token(
    token_id: str,
    slot: int,
    surface: str,
    *,
    source_id: str = "macula-hebrew",
    source_position: int | None = None,
    sentence_id: str | None = "S_GEN_1",
    clause_id: str | None = "C_GEN_1",
    phrase_id: str | None = "P_GEN_1",
    ketiv: bool = False,
) -> CanonicalToken:
    version = "oshb-fixture" if ketiv else "macula-fixture"
    source_word_id = f"Gen 1:1!{slot}" if ketiv else f"GEN 1:1!{slot}"
    return CanonicalToken(
        token_id=token_id,
        source_id=source_id,
        source_version=version,
        source_file="synthetic.xml",
        source_record_id=f"record-{token_id}",
        source_word_id=source_word_id,
        source_edition_reference="Gen 1:1" if ketiv else "GEN 1:1",
        source_row_reference=f"synthetic.xml#{token_id}",
        book="GEN",
        book_order=1,
        chapter=1,
        verse=1,
        sentence_id=None if ketiv else sentence_id,
        clause_id=None if ketiv else clause_id,
        phrase_id=None if ketiv else phrase_id,
        position_in_verse=slot,
        position_in_clause=slot if clause_id is not None and not ketiv else None,
        position_in_corpus=source_position or slot,
        position_in_word=1,
        surface_form=surface,
        normalized_form=surface,
        unpointed_form=surface,
        lemma=f"lemma-{slot}",
        part_of_speech="noun",
        language=Language.HEBREW,
        is_variant=ketiv,
        variant_type="ketiv" if ketiv else None,
        variant_group_id=f"KQ_GEN_001_001_{slot:04d}~{'a' * 12}" if ketiv else None,
        is_default_reading=not ketiv,
        ketiv_form=surface if ketiv else None,
        source_extras_json="{}",
    )


def _greek_token(
    token_id: str,
    position: int,
    book: str,
    book_order: int,
    chapter: int,
    verse: int,
    *,
    sentence_id: str,
    clause_id: str,
) -> CanonicalGreekToken:
    surface = f"\u03bb\u03cc\u03b3\u03bf\u03c2{position}"
    return CanonicalGreekToken(
        token_id=token_id,
        source_id="macula-greek",
        source_version="greek-fixture",
        source_file="synthetic.xml",
        source_record_id=f"record-{token_id}",
        source_word_id=f"{book} {chapter}:{verse}!1",
        source_edition_reference=f"{book} {chapter}:{verse}",
        source_row_reference=f"synthetic.xml#{token_id}",
        book=book,
        book_order=book_order,
        chapter=chapter,
        verse=verse,
        sentence_id=sentence_id,
        clause_id=clause_id,
        phrase_id=f"P_{position}",
        position_in_verse=1,
        position_in_clause=1,
        position_in_corpus=position,
        surface_form=surface,
        normalized_form=surface,
        folded_form=surface,
        source_normalized_form=surface,
        leading_punctuation="",
        trailing_punctuation="",
        lemma=f"lemma-{position}",
        part_of_speech="noun",
        language="greek",
        source_extras_json="{}",
    )


def _frame(models: list[CanonicalToken]) -> pl.DataFrame:
    return pl.DataFrame(
        [model.model_dump(mode="json") for model in models],
        schema=CANONICAL_TOKEN_POLARS_SCHEMA,
        orient="row",
    )


def _greek_frame(models: list[CanonicalGreekToken]) -> pl.DataFrame:
    return pl.DataFrame(
        [model.model_dump(mode="json") for model in models],
        schema=GREEK_TOKEN_POLARS_SCHEMA,
        orient="row",
    )


def _synthetic_inputs() -> SegmentationInputs:
    primary = _frame(
        [
            _hebrew_token("HB_GEN_001_001_0001", 1, "\u05d0"),
            _hebrew_token("HB_GEN_001_001_0002", 2, "\u05e7"),
            _hebrew_token("HB_GEN_001_001_0003", 3, "\u05d2"),
        ]
    )
    ketiv = _frame(
        [
            _hebrew_token(
                f"HB_GEN_001_001_0002~{'b' * 12}",
                2,
                "\u05db",
                source_id="oshb-morphhb",
                source_position=1,
                ketiv=True,
            ),
            _hebrew_token(
                f"HB_GEN_001_001_0004~{'c' * 12}",
                4,
                "\u05d3",
                source_id="oshb-morphhb",
                source_position=2,
                ketiv=True,
            ),
        ]
    )
    registry = pl.DataFrame(
        {
            "kind": ["paired", "ketiv_only"],
            "macula_qere_token_ids_json": [
                json.dumps(["HB_GEN_001_001_0002"]),
                "[]",
            ],
        }
    )
    structural = pl.DataFrame(
        [
            {
                "ketiv_token_id": f"HB_GEN_001_001_0002~{'b' * 12}",
                "locus_id": "KQL_GEN_001_001_0002",
                "analysis_clause_id": "C_GEN_1",
                "analysis_sentence_id": "S_GEN_1",
                "analysis_phrase_id": None,
                "structural_anchor_token_ids": ["HB_GEN_001_001_0002"],
                "alignment_method": "synthetic",
                "alignment_confidence": 1.0,
                "resolution_status": "partially_resolved",
                "notes": "{}",
            },
            {
                "ketiv_token_id": f"HB_GEN_001_001_0004~{'c' * 12}",
                "locus_id": "KQL_GEN_001_001_0004",
                "analysis_clause_id": None,
                "analysis_sentence_id": "S_GEN_1",
                "analysis_phrase_id": None,
                "structural_anchor_token_ids": ["HB_GEN_001_001_0003"],
                "alignment_method": "synthetic",
                "alignment_confidence": 0.75,
                "resolution_status": "partially_resolved",
                "notes": "{}",
            },
        ],
        schema=STRUCTURAL_ALIGNMENT_SCHEMA,
        orient="row",
    )
    greek = _greek_frame(
        [
            _greek_token(
                "GNT_MRK_016_008_0001",
                1,
                "MRK",
                2,
                16,
                8,
                sentence_id="S_MRK_8",
                clause_id="C_MRK_8",
            ),
            _greek_token(
                "GNT_MRK_016_009_0001",
                2,
                "MRK",
                2,
                16,
                9,
                sentence_id="S_MRK_9",
                clause_id="C_MRK_9",
            ),
            _greek_token(
                "GNT_MRK_016_020_0001",
                3,
                "MRK",
                2,
                16,
                20,
                sentence_id="S_MRK_20",
                clause_id="C_MRK_20",
            ),
            _greek_token(
                "GNT_MRK_016_099_0001",
                4,
                "MRK",
                2,
                16,
                99,
                sentence_id="S_MRK_99",
                clause_id="C_MRK_99",
            ),
            _greek_token(
                "GNT_JHN_007_052_0001",
                5,
                "JHN",
                4,
                7,
                52,
                sentence_id="S_JHN_52",
                clause_id="C_JHN_52",
            ),
            _greek_token(
                "GNT_JHN_007_053_0001",
                6,
                "JHN",
                4,
                7,
                53,
                sentence_id="S_JHN_53",
                clause_id="C_JHN_53",
            ),
            _greek_token(
                "GNT_JHN_008_011_0001",
                7,
                "JHN",
                4,
                8,
                11,
                sentence_id="S_JHN_11",
                clause_id="C_JHN_11",
            ),
            _greek_token(
                "GNT_JHN_008_012_0001",
                8,
                "JHN",
                4,
                8,
                12,
                sentence_id="S_JHN_12",
                clause_id="C_JHN_12",
            ),
        ]
    )
    return SegmentationInputs(
        hebrew_tokens=primary,
        greek_tokens=greek,
        ketiv_tokens=ketiv,
        locus_registry=registry,
        structural_alignments=structural,
        source_versions={
            "macula-hebrew": "fixture",
            "macula-greek": "fixture",
            "oshb-morphhb": "fixture",
        },
        digests=InputDigestSet("h-i", "h-c", "h-a", "g-i", "g-c", "g-a", {}),
    )


@pytest.fixture(scope="module")
def segmentation_config() -> SegmentationConfig:
    loaded = load_config(PROJECT_ROOT / "config" / "segmentation.yaml")
    assert isinstance(loaded, SegmentationConfig)
    return loaded


@pytest.fixture()
def inputs() -> SegmentationInputs:
    return _synthetic_inputs()


def test_all_six_required_streams_are_built_with_unique_tokens(
    inputs: SegmentationInputs, segmentation_config: SegmentationConfig
) -> None:
    streams = build_required_analysis_streams(inputs, config=segmentation_config)

    assert set(streams) == {
        ("hebrew", "edition_complete", "qere"),
        ("hebrew", "edition_complete", "ketiv"),
        ("hebrew", "critical_core", "qere"),
        ("hebrew", "critical_core", "ketiv"),
        ("greek", "edition_complete", "source"),
        ("greek", "critical_core", "source"),
    }
    for stream in streams.values():
        assert stream["token_id"].n_unique() == stream.height
        assert stream["stream_position_in_corpus"].is_sorted()


def test_qere_and_greek_source_streams_preserve_source_identity_and_enrichment(
    inputs: SegmentationInputs, segmentation_config: SegmentationConfig
) -> None:
    streams = build_required_analysis_streams(inputs, config=segmentation_config)
    qere = streams[("hebrew", "edition_complete", "qere")]
    greek = streams[("greek", "edition_complete", "source")]

    assert qere["token_id"].to_list() == inputs.hebrew_tokens["token_id"].to_list()
    assert qere["source_position_in_corpus"].to_list() == [1, 2, 3]
    assert qere["stream_position_in_corpus"].to_list() == [1, 2, 3]
    assert qere["default_membership_basis"].unique().to_list() == ["qere_primary"]
    assert qere["canonical_reference"].unique().to_list() == ["GEN 1:1"]
    assert greek["source_position_in_corpus"].to_list() == list(range(1, 9))
    assert greek["stream_position_in_corpus"].to_list() == list(range(1, 9))
    assert greek["default_membership_basis"].unique().to_list() == ["source_native"]
    assert greek["folded_form"].null_count() == 0


def test_ketiv_stream_substitutes_exactly_and_keeps_source_positions_in_their_domain(
    inputs: SegmentationInputs, segmentation_config: SegmentationConfig
) -> None:
    before_primary = inputs.hebrew_tokens.clone()
    before_ketiv = inputs.ketiv_tokens.clone()

    streams = build_required_analysis_streams(inputs, config=segmentation_config)
    ketiv = streams[("hebrew", "edition_complete", "ketiv")]

    assert ketiv["token_id"].to_list() == [
        "HB_GEN_001_001_0001",
        f"HB_GEN_001_001_0002~{'b' * 12}",
        "HB_GEN_001_001_0003",
        f"HB_GEN_001_001_0004~{'c' * 12}",
    ]
    assert "HB_GEN_001_001_0002" not in set(ketiv["token_id"])
    assert ketiv["stream_position_in_corpus"].to_list() == [1, 2, 3, 4]
    assert ketiv["source_position_in_corpus"].to_list() == [1, 1, 3, 2]
    assert ketiv.filter(pl.col("source_id") == "oshb-morphhb")[
        "default_membership_basis"
    ].unique().to_list() == ["ketiv_verse_stream"]
    assert inputs.hebrew_tokens.equals(before_primary)
    assert inputs.ketiv_tokens.equals(before_ketiv)


def test_structural_resolution_statuses_are_derived_per_field(
    inputs: SegmentationInputs, segmentation_config: SegmentationConfig
) -> None:
    ketiv = build_required_analysis_streams(inputs, config=segmentation_config)[
        ("hebrew", "edition_complete", "ketiv")
    ]
    paired = ketiv.filter(pl.col("locus_id") == "KQL_GEN_001_001_0002").row(0, named=True)
    ketiv_only = ketiv.filter(pl.col("locus_id") == "KQL_GEN_001_001_0004").row(0, named=True)

    assert paired["structural_resolution_status"] == "partially_resolved"
    assert paired["sentence_resolution_status"] == "resolved"
    assert paired["clause_resolution_status"] == "resolved"
    assert paired["phrase_resolution_status"] == "unresolved"
    assert ketiv_only["sentence_resolution_status"] == "resolved"
    assert ketiv_only["clause_resolution_status"] == "unresolved"
    assert ketiv_only["phrase_resolution_status"] == "unresolved"


def test_critical_core_excludes_exact_ranges_and_preserves_no_bridge_markers(
    inputs: SegmentationInputs, segmentation_config: SegmentationConfig
) -> None:
    streams = build_required_analysis_streams(inputs, config=segmentation_config)
    edition = streams[("greek", "edition_complete", "source")]
    critical = streams[("greek", "critical_core", "source")]

    assert edition["canonical_reference"].to_list() == [
        "MRK 16:8",
        "MRK 16:9",
        "MRK 16:20",
        "MRK 16:99",
        "JHN 7:52",
        "JHN 7:53",
        "JHN 8:11",
        "JHN 8:12",
    ]
    assert critical["canonical_reference"].to_list() == [
        "MRK 16:8",
        "JHN 7:52",
        "JHN 8:12",
    ]
    john = critical.filter(pl.col("book") == "JHN")
    assert john["stream_position_in_corpus"].to_list() == [5, 8]
    assert john["verse_ordinal_in_book"].to_list() == [1, 4]

    qere_edition = streams[("hebrew", "edition_complete", "qere")]
    qere_critical = streams[("hebrew", "critical_core", "qere")]
    assert qere_edition["token_id"].to_list() == qere_critical["token_id"].to_list()
    assert qere_critical["analysis_profile"].unique().to_list() == ["critical_core"]


@pytest.mark.parametrize("structural_field", ["analysis_sentence_id", "analysis_clause_id"])
def test_profile_application_stops_before_truncating_a_source_unit(
    inputs: SegmentationInputs,
    segmentation_config: SegmentationConfig,
    structural_field: str,
) -> None:
    edition = build_required_analysis_streams(inputs, config=segmentation_config)[
        ("greek", "edition_complete", "source")
    ]
    straddling = edition.with_columns(
        pl.when(pl.col("canonical_reference").is_in(["JHN 7:52", "JHN 7:53"]))
        .then(pl.lit("STRADDLE"))
        .otherwise(pl.col(structural_field))
        .alias(structural_field)
    )

    with pytest.raises(SegmentationInputError, match=f"truncate source {structural_field}"):
        apply_analysis_profile(
            straddling,
            config=segmentation_config,
            profile="critical_core",
        )
