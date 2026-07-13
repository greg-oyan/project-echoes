"""Synthetic production passage-generation and continuity tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from echoes.segment.generation import PassageGenerationError, generate_partition
from echoes.segment.streams import STREAM_TOKEN_COLUMNS, STREAM_TOKEN_SCHEMA
from echoes.settings import SegmentationConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_HASH = "a" * 64
RUN_ID = "passages-v1-synthetic"


def _config() -> SegmentationConfig:
    loaded = load_config(PROJECT_ROOT / "config" / "segmentation.yaml")
    assert isinstance(loaded, SegmentationConfig)
    return loaded


def _reference_parts(reference: str) -> tuple[str, int, int]:
    book, location = reference.split(" ", maxsplit=1)
    chapter, verse = location.split(":", maxsplit=1)
    return book, int(chapter), int(verse)


def _greek_row(
    position: int,
    reference: str,
    verse_ordinal: int,
    *,
    profile: str = "edition_complete",
    sentence_id: str | None = None,
    clause_id: str | None = None,
    surface: str | None = None,
    normalized: str | None = None,
    folded: str | None = None,
    leading: str = "",
    trailing: str = "",
) -> dict[str, object]:
    book, chapter, verse = _reference_parts(reference)
    core = normalized or f"λόγος{position}"
    return {
        "token_id": f"GNT_{book}_{chapter:03d}_{verse:03d}_{position:04d}",
        "corpus": "greek",
        "analysis_profile": profile,
        "analysis_reading": "source",
        "language": "greek",
        "source_id": "macula-greek",
        "source_version": "greek-test",
        "source_edition_reference": reference,
        "source_word_id": f"{reference}!{position}",
        "book": book,
        "book_order": 4,
        "chapter": chapter,
        "verse": verse,
        "canonical_reference": reference,
        "source_position_in_corpus": position,
        "stream_position_in_corpus": position,
        "verse_ordinal_in_book": verse_ordinal,
        "position_in_word": 1,
        "surface_form": surface or f"{leading}{core}{trailing}",
        "normalized_form": core,
        "unpointed_form": None,
        "folded_form": folded or core.casefold(),
        "leading_punctuation": leading,
        "trailing_punctuation": trailing,
        "is_zero_width": False,
        "is_punctuation": False,
        "is_elided": False,
        "lemma": f"lemma-{position}",
        "lexical_root": None,
        "part_of_speech": "N",
        "semantic_domain": None,
        "entity_id": None,
        "participant_id": None,
        "source_extras_json": "{}",
        "variant_type": None,
        "variant_group_id": None,
        "analysis_sentence_id": sentence_id or f"sentence-{position}",
        "analysis_clause_id": clause_id or f"clause-{position}",
        "analysis_phrase_id": f"phrase-{position}",
        "structural_resolution_status": "source_native",
        "sentence_resolution_status": "source_native",
        "clause_resolution_status": "source_native",
        "phrase_resolution_status": "source_native",
        "locus_id": None,
        "default_membership_basis": "source_native",
    }


def _hebrew_row(
    position: int,
    reference: str,
    verse_ordinal: int,
    *,
    source_id: str = "macula-hebrew",
    token_id: str | None = None,
    surface: str = "דבר",
    sentence_id: str | None = "sentence-1",
    clause_id: str | None = "clause-1",
    phrase_id: str | None = "phrase-1",
    structural_status: str = "source_native",
    clause_status: str = "resolved",
    phrase_status: str = "resolved",
    locus_id: str | None = None,
    variant_type: str | None = None,
) -> dict[str, object]:
    book, chapter, verse = _reference_parts(reference)
    return {
        "token_id": token_id or f"HB_{book}_{chapter:03d}_{verse:03d}_{position:04d}",
        "corpus": "hebrew",
        "analysis_profile": "edition_complete",
        "analysis_reading": "ketiv",
        "language": "hebrew",
        "source_id": source_id,
        "source_version": "hebrew-test" if source_id == "macula-hebrew" else "oshb-test",
        "source_edition_reference": reference,
        "source_word_id": f"{reference}!{position}",
        "book": book,
        "book_order": 1,
        "chapter": chapter,
        "verse": verse,
        "canonical_reference": reference,
        "source_position_in_corpus": position,
        "stream_position_in_corpus": position,
        "verse_ordinal_in_book": verse_ordinal,
        "position_in_word": 1,
        "surface_form": surface,
        "normalized_form": surface,
        "unpointed_form": surface,
        "folded_form": None,
        "leading_punctuation": "",
        "trailing_punctuation": "",
        "is_zero_width": False,
        "is_punctuation": False,
        "is_elided": False,
        "lemma": f"lemma-{position}",
        "lexical_root": None,
        "part_of_speech": "N",
        "semantic_domain": None,
        "entity_id": None,
        "participant_id": None,
        "source_extras_json": json.dumps({"attributes": {"after": " "}}, separators=(",", ":")),
        "variant_type": variant_type,
        "variant_group_id": locus_id,
        "analysis_sentence_id": sentence_id,
        "analysis_clause_id": clause_id,
        "analysis_phrase_id": phrase_id,
        "structural_resolution_status": structural_status,
        "sentence_resolution_status": "resolved" if sentence_id else "unresolved",
        "clause_resolution_status": clause_status,
        "phrase_resolution_status": phrase_status,
        "locus_id": locus_id,
        "default_membership_basis": (
            "ketiv_verse_stream" if source_id == "oshb-morphhb" else "qere_primary"
        ),
    }


def _stream(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=STREAM_TOKEN_SCHEMA, strict=False).select(STREAM_TOKEN_COLUMNS)


def _generate(rows: list[dict[str, object]]) -> Any:
    return generate_partition(
        _stream(rows),
        config=_config(),
        segmentation_run_id=RUN_ID,
        config_hash=CONFIG_HASH,
    )


def test_all_granularities_preserve_cross_verse_units_membership_and_overlap() -> None:
    references = ["JHN 1:1", "JHN 1:2", "JHN 1:3", "JHN 2:1", "JHN 2:2"]
    rows = [
        _greek_row(
            index,
            reference,
            index,
            sentence_id="sentence-cross" if index <= 2 else f"sentence-{index}",
            clause_id="clause-cross" if index <= 2 else f"clause-{index}",
            surface="(λόγος," if index == 1 else None,
            normalized="λόγος" if index == 1 else None,
            folded="λογοσ" if index == 1 else None,
            leading="(" if index == 1 else "",
            trailing="," if index == 1 else "",
        )
        for index, reference in enumerate(references, start=1)
    ]

    generated = _generate(rows)
    counts = generated.passages.group_by("granularity").len()
    assert dict(zip(counts["granularity"], counts["len"], strict=True)) == {
        "clause": 4,
        "sentence": 4,
        "verse": 5,
        "two_verse": 4,
        "five_verse": 1,
    }
    assert generated.membership.height == 28

    sentence = generated.passages.filter(pl.col("source_unit_id") == "sentence-cross").row(
        0, named=True
    )
    assert sentence["token_count"] == 2
    assert json.loads(sentence["reference_sequence_json"]) == ["JHN 1:1", "JHN 1:2"]
    assert sentence["surface_text"].startswith("(λόγος,")

    chapter_window = generated.passages.filter(
        (pl.col("granularity") == "two_verse") & (pl.col("start_reference") == "JHN 1:3")
    ).row(0, named=True)
    assert chapter_window["end_reference"] == "JHN 2:1"
    assert len(json.loads(chapter_window["constituent_verse_passage_ids_json"])) == 2

    windows = generated.passages.filter(pl.col("granularity") == "two_verse").sort(
        "start_stream_position_in_corpus"
    )
    assert windows["overlap_with_next_token_count"].to_list() == [1, 1, 1, 0]
    assert windows["overlap_with_previous_token_count"].to_list() == [0, 1, 1, 1]
    assert generated.issues.is_empty()


def test_generation_is_deterministic_when_input_rows_are_reordered() -> None:
    rows = [_greek_row(index, f"JHN 3:{index}", index) for index in range(1, 6)]

    first = _generate(rows)
    second = _generate(list(reversed(rows)))

    assert first.passages.equals(second.passages)
    assert first.membership.equals(second.membership)
    assert first.adjacency.equals(second.adjacency)
    assert first.exclusions.equals(second.exclusions)
    assert first.issues.equals(second.issues)


def test_reference_gaps_are_flagged_without_fabricating_verses() -> None:
    references = ["ACT 24:5", "ACT 24:6", "ACT 24:8", "ACT 24:9", "ACT 24:10"]
    rows = [
        _greek_row(
            index,
            reference,
            index,
            sentence_id="sentence-gap" if index <= 3 else f"sentence-{index}",
        )
        for index, reference in enumerate(references, start=1)
    ]

    generated = _generate(rows)
    gap_sentence = generated.passages.filter(pl.col("source_unit_id") == "sentence-gap").row(
        0, named=True
    )
    assert gap_sentence["reference_gap"]
    assert gap_sentence["token_count"] == 3

    gap_windows = generated.passages.filter(
        pl.col("reference_gap") & pl.col("granularity").is_in(["two_verse", "five_verse"])
    )
    assert gap_windows.height == 2
    all_references = "".join(generated.passages["reference_sequence_json"].to_list())
    assert "ACT 24:7" not in all_references
    verse_adjacency = generated.adjacency.filter(
        (pl.col("granularity") == "verse") & pl.col("reference_gap")
    )
    assert verse_adjacency.height == 1
    assert verse_adjacency["analytically_continuous"].item()


def test_mark_alternate_ending_is_a_source_successor_but_never_a_window_neighbor() -> None:
    rows = [
        _greek_row(1, "MRK 16:19", 1),
        _greek_row(2, "MRK 16:20", 2),
        _greek_row(3, "MRK 16:99", 3),
    ]

    generated = _generate(rows)
    windows = generated.passages.filter(pl.col("granularity") == "two_verse")
    assert windows.height == 1
    assert json.loads(windows["reference_sequence_json"].item()) == [
        "MRK 16:19",
        "MRK 16:20",
    ]

    verse_rows = generated.passages.filter(pl.col("granularity") == "verse").sort(
        "start_stream_position_in_corpus"
    )
    mark_20 = verse_rows.filter(pl.col("start_reference") == "MRK 16:20").row(0, named=True)
    mark_99 = verse_rows.filter(pl.col("start_reference") == "MRK 16:99").row(0, named=True)
    assert mark_20["next_passage_id"] is None
    assert mark_99["previous_passage_id"] is None
    assert json.loads(mark_99["disputed_passage_ids_json"]) == ["mark_alternate_ending"]

    boundary = generated.adjacency.filter(
        (pl.col("granularity") == "verse") & (pl.col("relation") == "alternate_ending")
    ).row(0, named=True)
    assert boundary["source_successor"]
    assert not boundary["analytically_continuous"]
    assert boundary["reference_gap"]
    assert boundary["boundary_break"]


def test_critical_core_profile_exclusions_break_continuity_without_truncation() -> None:
    rows = [
        _greek_row(1, "JHN 7:51", 1, profile="critical_core"),
        _greek_row(2, "JHN 7:52", 2, profile="critical_core"),
        _greek_row(3, "JHN 8:12", 15, profile="critical_core"),
        _greek_row(4, "JHN 8:13", 16, profile="critical_core"),
    ]

    generated = _generate(rows)
    windows = generated.passages.filter(pl.col("granularity") == "two_verse").sort(
        "start_stream_position_in_corpus"
    )
    assert windows.height == 2
    assert [json.loads(value) for value in windows["reference_sequence_json"]] == [
        ["JHN 7:51", "JHN 7:52"],
        ["JHN 8:12", "JHN 8:13"],
    ]
    assert windows["next_passage_id"][0] is None
    assert windows["previous_passage_id"][1] is None
    assert not generated.passages["profile_truncated"].any()

    exclusion_edge = generated.adjacency.filter(
        (pl.col("granularity") == "verse") & (pl.col("relation") == "profile_exclusion")
    ).row(0, named=True)
    assert not exclusion_edge["source_successor"]
    assert not exclusion_edge["analytically_continuous"]
    assert exclusion_edge["boundary_break"]


def test_ketiv_uncertainty_and_primary_nulls_are_explicit_without_verse_loss() -> None:
    rows = [
        _hebrew_row(1, "GEN 1:1", 1, surface="אמר"),
        _hebrew_row(
            2,
            "GEN 1:1",
            1,
            source_id="oshb-morphhb",
            token_id="HB_GEN_001_001_0002~aaaaaaaaaaaa",
            surface="כתב",
            clause_id=None,
            phrase_id=None,
            structural_status="partially_resolved",
            clause_status="unresolved",
            phrase_status="unresolved",
            locus_id="KQL_GEN_001_001_0002",
            variant_type="ketiv",
        ),
        _hebrew_row(
            3,
            "GEN 1:1",
            1,
            surface="את",
            clause_id=None,
            phrase_id="phrase-primary",
            clause_status="unresolved",
        ),
        _hebrew_row(4, "GEN 1:1", 1, surface="הדבר"),
        _hebrew_row(
            5,
            "GEN 1:2",
            2,
            source_id="oshb-morphhb",
            token_id="HB_GEN_001_002_0001~bbbbbbbbbbbb",
            surface="קרי",
            sentence_id="sentence-2",
            clause_id="clause-2",
            phrase_id="phrase-2",
            structural_status="resolved",
            locus_id="KQL_GEN_001_002_0001",
            variant_type="ketiv",
        ),
    ]

    generated = _generate(rows)
    assert generated.exclusions.height == 2
    assert set(generated.exclusions["reason_code"]) == {
        "ketiv_clause_mapping_unresolved",
        "primary_clause_annotation_unavailable",
    }

    verse_membership = generated.membership.filter(pl.col("granularity") == "verse")
    assert verse_membership.height == len(rows)
    assert set(verse_membership["token_id"]) == {row["token_id"] for row in rows}
    unresolved_id = "HB_GEN_001_001_0002~aaaaaaaaaaaa"
    assert unresolved_id not in set(
        generated.membership.filter(pl.col("granularity") == "clause")["token_id"]
    )
    assert unresolved_id in set(verse_membership["token_id"])

    clause = generated.passages.filter(pl.col("source_unit_id") == "clause-1").row(0, named=True)
    assert clause["ketiv_structural_uncertainty"]
    assert clause["sensitivity_exclusion_count"] == 2
    assert all(
        clause["passage_id"] in json.loads(value)
        for value in generated.exclusions["related_passage_ids_json"]
    )
    verse = generated.passages.filter(
        (pl.col("granularity") == "verse") & (pl.col("start_reference") == "GEN 1:1")
    ).row(0, named=True)
    assert verse["ketiv_structural_uncertainty"]
    assert "כתב" in verse["surface_text"]

    resolved_membership = generated.membership.filter(
        (pl.col("granularity") == "clause")
        & (pl.col("token_id") == "HB_GEN_001_002_0001~bbbbbbbbbbbb")
    ).row(0, named=True)
    assert resolved_membership["membership_basis"] == "ketiv_clause_alignment"
    assert resolved_membership["structural_resolution_status"] == "resolved"


def test_generation_rejects_multiple_books_and_bad_config_hashes() -> None:
    mixed = _stream(
        [
            _greek_row(1, "JHN 1:1", 1),
            {**_greek_row(2, "ACT 1:1", 1), "book_order": 5},
        ]
    )
    with pytest.raises(PassageGenerationError, match="one non-null book"):
        generate_partition(
            mixed,
            config=_config(),
            segmentation_run_id=RUN_ID,
            config_hash=CONFIG_HASH,
        )
    with pytest.raises(PassageGenerationError, match="must be SHA-256"):
        generate_partition(
            _stream([_greek_row(1, "JHN 1:1", 1)]),
            config=_config(),
            segmentation_run_id=RUN_ID,
            config_hash="short",
        )
