"""Explicit benchmark leakage-view tests."""

from __future__ import annotations

from echoes.benchmarks.leakage import (
    LeakageEndpoint,
    RelationshipLeakageInput,
    build_leakage_groups,
    leakage_members_by_group,
)


def _id(prefix: str, character: str) -> str:
    return f"{prefix}_{character * 64}"


def _relationship(
    character: str,
    *,
    directed: str | None = None,
    unordered: str | None = None,
    endpoint_a: LeakageEndpoint | None = None,
    endpoint_b: LeakageEndpoint | None = None,
    duplicate_key: str | None = None,
    provenance_key: str | None = None,
    family: str | None = None,
) -> RelationshipLeakageInput:
    return RelationshipLeakageInput(
        relationship_id=_id("BR", character),
        canonical_directed_pair_id=directed or _id("BDP", character),
        canonical_undirected_pair_id=unordered or _id("BUP", character),
        endpoints=(
            endpoint_a
            or LeakageEndpoint(
                endpoint_key=f"GEN 1:{ord(character) - 96}",
                source_book="GEN",
                source_start_ordinal=ord(character) - 96,
                source_end_ordinal=ord(character) - 96,
            ),
            endpoint_b
            or LeakageEndpoint(
                endpoint_key=f"ROM 1:{ord(character) - 96}",
                source_book="ROM",
                source_start_ordinal=ord(character) - 96,
                source_end_ordinal=ord(character) - 96,
            ),
        ),
        duplicate_source_record_keys=(duplicate_key,) if duplicate_key else (),
        source_provenance_keys=(provenance_key,) if provenance_key else (),
        relationship_family_key=family,
    )


def test_reverse_duplicates_and_source_provenance_get_separate_views() -> None:
    unordered = _id("BUP", "f")
    relationships = [
        _relationship(
            "a",
            unordered=unordered,
            duplicate_key="raw-record-family",
            provenance_key="openbible-source-file",
        ),
        _relationship(
            "b",
            unordered=unordered,
            duplicate_key="raw-record-family",
            provenance_key="openbible-source-file",
        ),
    ]

    rows = build_leakage_groups(relationships)
    by_type: dict[str, list[set[str]]] = {}
    for group_id, members in leakage_members_by_group(rows).items():
        group_type = next(row.group_type for row in rows if row.leakage_group_id == group_id)
        by_type.setdefault(group_type, []).append(set(members))

    expected = {_id("BR", "a"), _id("BR", "b")}
    assert expected in by_type["exact_unordered_pair"]
    assert expected in by_type["duplicate_source_records"]
    assert expected in by_type["shared_source_provenance"]
    assert all(len(group) == 1 for group in by_type["exact_directed_pair"])


def test_shared_endpoints_targets_and_relationship_family_are_inspectable() -> None:
    shared_endpoint = LeakageEndpoint(
        endpoint_key="ISA 6:1",
        source_book="ISA",
        source_start_ordinal=6001,
        source_end_ordinal=6001,
        target_passage_ids=("P_ISA_6_1",),
        target_book="ISA",
        target_start_ordinal=6001,
        target_end_ordinal=6001,
    )
    rows = build_leakage_groups(
        [
            _relationship("a", endpoint_a=shared_endpoint, family="quotation-family-1"),
            _relationship("b", endpoint_a=shared_endpoint, family="quotation-family-1"),
        ]
    )
    present = {row.group_type for row in rows}

    assert "shared_endpoint" in present
    assert "shared_target_passage" in present
    assert "relationship_family" in present
    book_pair_rows = [row for row in rows if row.group_type == "canonical_book_pair"]
    assert {row.group_key for row in book_pair_rows} == {"ISA|ROM"}
    assert len(book_pair_rows) == 2


def test_duplicate_source_record_group_remains_visible_after_relationship_aggregation() -> None:
    relationship = _relationship("a", duplicate_key="duplicate-raw-record")

    rows = build_leakage_groups([relationship])

    duplicate_rows = [row for row in rows if row.group_type == "duplicate_source_records"]
    assert len(duplicate_rows) == 1
    assert duplicate_rows[0].relationship_id == relationship.relationship_id


def test_interval_overlap_uses_atomic_keys_not_one_unrestricted_component() -> None:
    relationships = [
        _relationship(
            "a",
            endpoint_a=LeakageEndpoint("GEN range a", "GEN", 1, 3),
        ),
        _relationship(
            "b",
            endpoint_a=LeakageEndpoint("GEN range b", "GEN", 3, 5),
        ),
        _relationship(
            "c",
            endpoint_a=LeakageEndpoint("GEN range c", "GEN", 5, 7),
        ),
    ]

    rows = build_leakage_groups(relationships)
    overlap_groups = leakage_members_by_group(
        rows, group_types=frozenset({"overlapping_endpoint_range"})
    )

    assert len(overlap_groups) == 2
    assert all(len(members) == 2 for members in overlap_groups.values())
    assert not any(len(members) == 3 for members in overlap_groups.values())


def test_high_degree_coordinate_emits_linear_membership_not_all_pairs() -> None:
    relationship_count = 300
    relationships = [
        RelationshipLeakageInput(
            relationship_id=f"BR_{index:064x}",
            canonical_directed_pair_id=f"BDP_{index:064x}",
            canonical_undirected_pair_id=f"BUP_{index:064x}",
            endpoints=(
                LeakageEndpoint("ISA 6:1", "ISA", 6001, 6001),
                LeakageEndpoint(f"ROM 1:{index + 1}", "ROM", index + 1, index + 1),
            ),
        )
        for index in range(relationship_count)
    ]

    rows = build_leakage_groups(relationships)
    overlap_rows = [row for row in rows if row.group_type == "overlapping_endpoint_range"]

    assert len({row.leakage_group_id for row in overlap_rows}) == 1
    assert len(overlap_rows) == relationship_count
    assert all(
        row.group_method == "interval_start_sweep_no_global_component" for row in overlap_rows
    )
    assert len(overlap_rows) < relationship_count * 2


def test_group_generation_is_input_order_invariant() -> None:
    relationships = [_relationship("a"), _relationship("b"), _relationship("c")]

    assert build_leakage_groups(relationships) == build_leakage_groups(
        list(reversed(relationships))
    )
