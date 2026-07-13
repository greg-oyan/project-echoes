"""Conservative benchmark endpoint-to-verse mapping contracts."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from echoes.benchmarks.mapping import (
    BenchmarkMappingError,
    PassageReferenceIndex,
    PassageTarget,
    iter_benchmark_endpoint_mappings,
    map_benchmark_endpoints,
)
from echoes.benchmarks.models import BenchmarkEndpointMappingRow, BenchmarkEndpointRow
from echoes.benchmarks.pipeline import _model_frame, _model_frame_batches


def _identifier(prefix: str, digit: str) -> str:
    return f"{prefix}_{digit * 64}"


def _target(
    passage_id: str,
    *,
    corpus: str,
    profile: str,
    reading: str,
    book: str,
    chapter: int,
    verse: int,
    disputed_ids: tuple[str, ...] = (),
    reference_gap: bool = False,
) -> PassageTarget:
    return PassageTarget(
        passage_id=passage_id,
        corpus=corpus,  # type: ignore[arg-type]
        analysis_profile=profile,  # type: ignore[arg-type]
        analysis_reading=reading,  # type: ignore[arg-type]
        book=book,
        chapter=chapter,
        verse=verse,
        reference=f"{book} {chapter}:{verse}",
        token_count=3,
        disputed_passage_flag=bool(disputed_ids),
        disputed_passage_ids=disputed_ids,
        reference_gap=reference_gap,
    )


def _paired_target(
    passage_stem: str,
    *,
    corpus: str,
    reading: str,
    book: str,
    chapter: int,
    verse: int,
    disputed_ids: tuple[str, ...] = (),
    reference_gap: bool = False,
) -> list[PassageTarget]:
    return [
        _target(
            f"{passage_stem}-{profile}",
            corpus=corpus,
            profile=profile,
            reading=reading,
            book=book,
            chapter=chapter,
            verse=verse,
            disputed_ids=disputed_ids,
            reference_gap=reference_gap,
        )
        for profile in ("edition_complete", "critical_core")
    ]


def _index() -> PassageReferenceIndex:
    targets: list[PassageTarget] = []
    for verse in (1, 2, 4):
        targets.extend(
            _paired_target(
                f"hb-gen-001-{verse:03d}",
                corpus="hebrew",
                reading="qere",
                book="GEN",
                chapter=1,
                verse=verse,
            )
        )
    targets.extend(
        _paired_target(
            "gnt-jhn-001-001",
            corpus="greek",
            reading="source",
            book="JHN",
            chapter=1,
            verse=1,
        )
    )
    # This disputed verse is present in edition_complete and deliberately absent
    # from critical_core, matching the Milestone 5 profile contract.
    targets.append(
        _target(
            "gnt-jhn-007-053-edition-complete",
            corpus="greek",
            profile="edition_complete",
            reading="source",
            book="JHN",
            chapter=7,
            verse=53,
            disputed_ids=("gnt-pericope-adulterae",),
        )
    )
    return PassageReferenceIndex(reversed(targets))


def _endpoint(
    *,
    digit: str,
    side: str,
    source_reference: str,
    book: str,
    start_chapter: int,
    start_verse: int,
    end_chapter: int | None = None,
    end_verse: int | None = None,
) -> BenchmarkEndpointRow:
    return BenchmarkEndpointRow(
        endpoint_id=_identifier("BE", digit),
        relationship_id=_identifier("BR", digit),
        endpoint_side=side,  # type: ignore[arg-type]
        source_reference=source_reference,
        source_reference_scheme="openbible-english-versification",
        parsed_book=book,
        parsed_start_chapter=start_chapter,
        parsed_start_verse=start_verse,
        parsed_end_chapter=end_chapter or start_chapter,
        parsed_end_verse=end_verse or start_verse,
        is_range=(end_chapter, end_verse) != (None, None),
        parse_status="parsed",
    )


def _by_profile(
    mappings: tuple[BenchmarkEndpointMappingRow, ...], endpoint_id: str
) -> dict[str, BenchmarkEndpointMappingRow]:
    return {
        mapping.target_analysis_profile: mapping
        for mapping in mappings
        if mapping.endpoint_id == endpoint_id
    }


def _json_array(value: str) -> list[str]:
    parsed = json.loads(value)
    assert isinstance(parsed, list)
    assert all(isinstance(item, str) for item in parsed)
    return parsed


def test_exact_ot_and_nt_references_map_provisionally_in_both_profiles() -> None:
    ot = _endpoint(
        digit="1",
        side="a",
        source_reference="Gen.1.1",
        book="GEN",
        start_chapter=1,
        start_verse=1,
    )
    nt = _endpoint(
        digit="2",
        side="b",
        source_reference="John.1.1",
        book="JHN",
        start_chapter=1,
        start_verse=1,
    )

    result = map_benchmark_endpoints([nt, ot], _index())
    ot_mappings = _by_profile(result.mappings, ot.endpoint_id)
    nt_mappings = _by_profile(result.mappings, nt.endpoint_id)

    assert set(ot_mappings) == {"edition_complete", "critical_core"}
    assert set(nt_mappings) == {"edition_complete", "critical_core"}
    for mapping in ot_mappings.values():
        assert mapping.mapping_status == "mapped_provisional"
        assert mapping.mapping_method == "same_label_extant_reference"
        assert mapping.mapping_confidence == "provisional_mechanical"
        assert mapping.target_corpus == "hebrew"
        assert mapping.target_analysis_reading == "qere"
        assert _json_array(mapping.target_reference_sequence_json) == ["GEN 1:1"]
    for mapping in nt_mappings.values():
        assert mapping.mapping_status == "mapped_provisional"
        assert mapping.target_corpus == "greek"
        assert mapping.target_analysis_reading == "source"
        assert _json_array(mapping.target_reference_sequence_json) == ["JHN 1:1"]


def test_disputed_edition_target_is_explicitly_excluded_from_critical_core() -> None:
    endpoint = _endpoint(
        digit="3",
        side="a",
        source_reference="John.7.53",
        book="JHN",
        start_chapter=7,
        start_verse=53,
    )

    result = map_benchmark_endpoints([endpoint], _index())
    mappings = _by_profile(result.mappings, endpoint.endpoint_id)
    edition = mappings["edition_complete"]
    critical = mappings["critical_core"]

    assert edition.mapping_status == "mapped_provisional"
    assert edition.disputed_passage_flag
    assert _json_array(edition.disputed_passage_ids_json) == ["gnt-pericope-adulterae"]
    assert critical.mapping_status == "excluded_by_profile"
    assert critical.mapping_method == "critical_core_profile_compatibility"
    assert critical.mapping_confidence == "profile_excluded"
    assert _json_array(critical.target_passage_ids_json) == []
    assert critical.disputed_passage_flag
    assert _json_array(critical.disputed_passage_ids_json) == ["gnt-pericope-adulterae"]
    assert {risk.mapping_status for risk in result.risks} == {
        "mapped_provisional",
        "excluded_by_profile",
    }


def test_omitted_exact_target_remains_unresolved_and_is_never_fabricated() -> None:
    endpoint = _endpoint(
        digit="4",
        side="b",
        source_reference="John.5.4",
        book="JHN",
        start_chapter=5,
        start_verse=4,
    )

    result = map_benchmark_endpoints([endpoint], _index())

    assert len(result.mappings) == 2
    for mapping in result.mappings:
        assert mapping.mapping_status == "unresolved_missing_target"
        assert mapping.mapping_confidence == "unresolved"
        assert _json_array(mapping.target_passage_ids_json) == []
        assert _json_array(mapping.target_reference_sequence_json) == []
        assert "absent from the pinned source edition" in (mapping.ambiguity_reason or "")


def test_unsupported_nt_cross_book_range_preserves_inferred_target_corpus() -> None:
    endpoint = BenchmarkEndpointRow(
        endpoint_id=_identifier("BE", "c"),
        relationship_id=_identifier("BR", "c"),
        endpoint_side="a",
        source_reference="Acts.28.17-Rom.1.1",
        source_reference_scheme="openbible-english-versification",
        parsed_book=None,
        parsed_start_chapter=None,
        parsed_start_verse=None,
        parsed_end_chapter=None,
        parsed_end_verse=None,
        is_range=True,
        parse_status="cross_book_range",
    )

    result = map_benchmark_endpoints([endpoint], PassageReferenceIndex([]))

    assert len(result.mappings) == 2
    for mapping in result.mappings:
        assert mapping.mapping_status == "unresolved_reference"
        assert mapping.target_corpus == "greek"
        assert mapping.target_analysis_reading == "source"
        assert _json_array(mapping.target_passage_ids_json) == []


def test_same_chapter_range_with_missing_verse_maps_only_ordered_extant_targets() -> None:
    endpoint = _endpoint(
        digit="5",
        side="a",
        source_reference="Gen.1.1-Gen.1.4",
        book="GEN",
        start_chapter=1,
        start_verse=1,
        end_chapter=1,
        end_verse=4,
    )

    result = map_benchmark_endpoints([endpoint], _index())

    for mapping in result.mappings:
        assert mapping.mapping_status == "mapped_partial"
        assert mapping.reference_gap
        assert mapping.mapping_confidence == "partial_provisional"
        assert _json_array(mapping.target_reference_sequence_json) == [
            "GEN 1:1",
            "GEN 1:2",
            "GEN 1:4",
        ]
        assert "GEN 1:3" not in mapping.target_reference_sequence_json


def test_complete_cross_chapter_range_is_not_mislabeled_partial() -> None:
    targets: list[PassageTarget] = []
    for chapter, verse in ((1, 4), (2, 1), (2, 2)):
        targets.extend(
            _paired_target(
                f"hb-gen-{chapter:03d}-{verse:03d}",
                corpus="hebrew",
                reading="qere",
                book="GEN",
                chapter=chapter,
                verse=verse,
            )
        )
    endpoint = _endpoint(
        digit="8",
        side="a",
        source_reference="Gen.1.4-Gen.2.2",
        book="GEN",
        start_chapter=1,
        start_verse=4,
        end_chapter=2,
        end_verse=2,
    )

    result = map_benchmark_endpoints([endpoint], PassageReferenceIndex(targets))

    for mapping in result.mappings:
        assert mapping.mapping_status == "mapped_provisional"
        assert mapping.mapping_confidence == "provisional_mechanical"
        assert not mapping.reference_gap
        assert _json_array(mapping.target_reference_sequence_json) == [
            "GEN 1:4",
            "GEN 2:1",
            "GEN 2:2",
        ]


def test_mapping_output_and_ids_are_deterministic_across_input_order() -> None:
    first = _endpoint(
        digit="6",
        side="a",
        source_reference="Gen.1.1-Gen.1.4",
        book="GEN",
        start_chapter=1,
        start_verse=1,
        end_chapter=1,
        end_verse=4,
    )
    second = _endpoint(
        digit="7",
        side="b",
        source_reference="John.1.1",
        book="JHN",
        start_chapter=1,
        start_verse=1,
    )

    forward = map_benchmark_endpoints([first, second], _index())
    reversed_input = map_benchmark_endpoints([second, first], _index())

    assert forward == reversed_input
    assert [mapping.mapping_id for mapping in forward.mappings] == [
        mapping.mapping_id for mapping in reversed_input.mappings
    ]


def test_streaming_mapping_api_matches_fixture_result_without_risks() -> None:
    first = _endpoint(
        digit="9",
        side="a",
        source_reference="Gen.1.1-Gen.1.4",
        book="GEN",
        start_chapter=1,
        start_verse=1,
        end_chapter=1,
        end_verse=4,
    )
    second = _endpoint(
        digit="a",
        side="b",
        source_reference="John.7.53",
        book="JHN",
        start_chapter=7,
        start_verse=53,
    )

    expected = map_benchmark_endpoints([second, first], _index(), collect_risks=False)
    streamed = tuple(iter_benchmark_endpoint_mappings([second, first], _index()))

    assert streamed == expected.mappings
    assert expected.risks == ()


def test_streaming_mapping_rejects_duplicate_endpoint_identity() -> None:
    endpoint = _endpoint(
        digit="b",
        side="a",
        source_reference="Gen.1.1",
        book="GEN",
        start_chapter=1,
        start_verse=1,
    )

    with pytest.raises(BenchmarkMappingError, match="duplicate endpoint identity"):
        tuple(iter_benchmark_endpoint_mappings([endpoint, endpoint], _index()))


def test_mapping_rows_convert_to_reusable_bounded_frame_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _endpoint(
        digit="c",
        side="a",
        source_reference="Gen.1.1",
        book="GEN",
        start_chapter=1,
        start_verse=1,
    )
    second = _endpoint(
        digit="d",
        side="b",
        source_reference="John.1.1",
        book="JHN",
        start_chapter=1,
        start_verse=1,
    )
    rows = tuple(iter_benchmark_endpoint_mappings([first, second], _index()))
    monkeypatch.setattr("echoes.benchmarks.pipeline.MODEL_FRAME_BATCH_SIZE", 3)

    batches = list(_model_frame_batches(rows, "benchmark_endpoint_mappings"))
    expected = _model_frame(rows, "benchmark_endpoint_mappings")

    assert [batch.height for batch in batches] == [3, 1]
    assert [value for batch in batches for value in batch["mapping_id"]] == expected[
        "mapping_id"
    ].to_list()


def test_mapping_membership_changes_do_not_rewrite_relationship_identity() -> None:
    endpoint = _endpoint(
        digit="8",
        side="a",
        source_reference="Gen.1.1",
        book="GEN",
        start_chapter=1,
        start_verse=1,
    )
    original_index = _index()
    remapped_targets = [
        replace(target, passage_id=f"replacement-{target.passage_id}")
        for target in original_index.by_key.values()
    ]

    original = map_benchmark_endpoints([endpoint], original_index)
    remapped = map_benchmark_endpoints([endpoint], PassageReferenceIndex(remapped_targets))

    assert endpoint.relationship_id == _identifier("BR", "8")
    assert {mapping.mapping_id for mapping in original.mappings} != {
        mapping.mapping_id for mapping in remapped.mappings
    }
    assert {mapping.endpoint_id for mapping in original.mappings} == {endpoint.endpoint_id}
    assert {mapping.endpoint_id for mapping in remapped.mappings} == {endpoint.endpoint_id}
