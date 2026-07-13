"""Deterministic leakage-safe split tests."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from echoes.benchmarks.leakage import (
    LeakageEndpoint,
    RelationshipLeakageInput,
    build_leakage_groups,
)
from echoes.benchmarks.models import BENCHMARK_ARTIFACT_SCHEMAS
from echoes.benchmarks.negatives import Partition
from echoes.benchmarks.pipeline import (
    _exclude_split_leakage_conflicts,
    _generate_splits,
    _iter_split_frames,
)
from echoes.benchmarks.splits import (
    SplitDefinition,
    SplitRelationship,
    generate_split_assignments,
    split_leakage_violations,
)
from echoes.settings import BenchmarkConfig, load_config

CONFIG_HASH = "a" * 64


def _id(prefix: str, character: str) -> str:
    return f"{prefix}_{character * 64}"


def _inputs() -> tuple[list[SplitRelationship], tuple[object, ...]]:
    unordered_reverse_pair = _id("BUP", "f")
    leakage_inputs = [
        RelationshipLeakageInput(
            relationship_id=_id("BR", "a"),
            canonical_directed_pair_id=_id("BDP", "a"),
            canonical_undirected_pair_id=unordered_reverse_pair,
            endpoints=(
                LeakageEndpoint("ISA 6:1", "ISA", 6001, 6001),
                LeakageEndpoint("ROM 9:1", "ROM", 9001, 9001),
            ),
            relationship_family_key="family-1",
        ),
        RelationshipLeakageInput(
            relationship_id=_id("BR", "b"),
            canonical_directed_pair_id=_id("BDP", "b"),
            canonical_undirected_pair_id=unordered_reverse_pair,
            endpoints=(
                LeakageEndpoint("ROM 9:1", "ROM", 9001, 9001),
                LeakageEndpoint("ISA 6:1", "ISA", 6001, 6001),
            ),
            relationship_family_key="family-1",
        ),
        RelationshipLeakageInput(
            relationship_id=_id("BR", "c"),
            canonical_directed_pair_id=_id("BDP", "c"),
            canonical_undirected_pair_id=_id("BUP", "c"),
            endpoints=(
                LeakageEndpoint("GEN 1:1", "GEN", 1001, 1001),
                LeakageEndpoint("EXO 1:1", "EXO", 1001, 1001),
            ),
        ),
        RelationshipLeakageInput(
            relationship_id=_id("BR", "d"),
            canonical_directed_pair_id=_id("BDP", "d"),
            canonical_undirected_pair_id=_id("BUP", "d"),
            endpoints=(
                LeakageEndpoint("JHN 7:53", "JHN", 7053, 7053),
                LeakageEndpoint("JHN 8:1", "JHN", 8001, 8001),
            ),
        ),
    ]
    relationships = [
        SplitRelationship(
            _id("BR", "a"),
            3,
            True,
            ("ISA", "ROM"),
            ("ISA 6:1", "ROM 9:1"),
            ("Major Prophets", "Pauline Letters"),
            "family-1",
        ),
        SplitRelationship(
            _id("BR", "b"),
            3,
            True,
            ("ROM", "ISA"),
            ("ROM 9:1", "ISA 6:1"),
            ("Pauline Letters", "Major Prophets"),
            "family-1",
        ),
        SplitRelationship(
            _id("BR", "c"), 3, True, ("GEN", "EXO"), ("GEN 1:1", "EXO 1:1"), ("Torah", "Torah")
        ),
        SplitRelationship(
            _id("BR", "d"),
            3,
            False,
            ("JHN", "JHN"),
            ("JHN 7:53", "JHN 8:1"),
            ("Gospels and Acts", "Gospels and Acts"),
        ),
    ]
    return relationships, build_leakage_groups(leakage_inputs)


@pytest.mark.parametrize(
    ("strategy", "held_value"),
    [
        ("held_out_book", "ISA"),
        ("held_out_book_pair", "ISA|ROM"),
        ("held_out_source_passage", "ISA 6:1"),
        ("held_out_genre", "Major Prophets"),
    ],
)
def test_nonrandom_heldouts_keep_reverse_pairs_together(strategy: str, held_value: str) -> None:
    relationships, groups = _inputs()
    definition = SplitDefinition(
        name=f"test-{strategy}",
        strategy=strategy,  # type: ignore[arg-type]
        benchmark_version="benchmark-v1",
        config_hash=CONFIG_HASH,
        held_out_values=(held_value,),
    )

    assignments = generate_split_assignments(relationships, groups, definition)
    partitions = {row.relationship_id: row.partition for row in assignments}

    assert partitions[_id("BR", "a")] == "test"
    assert partitions[_id("BR", "b")] == "test"
    assert partitions[_id("BR", "c")] == "train"
    assert (
        split_leakage_violations(
            assignments, groups, enforced_group_types=definition.effective_group_types
        )
        == ()
    )


def test_mapping_dependent_split_excludes_unmapped_relationships() -> None:
    relationships, groups = _inputs()
    definition = SplitDefinition(
        name="held-source",
        strategy="held_out_source_passage",
        benchmark_version="benchmark-v1",
        config_hash=CONFIG_HASH,
        held_out_values=("JHN 7:53",),
    )

    assignments = generate_split_assignments(relationships, groups, definition)
    assignment = next(row for row in assignments if row.relationship_id == _id("BR", "d"))

    assert assignment.partition == "excluded"
    assert assignment.exclusion_reason == "mapping_ineligible"


def test_unavailable_relationship_families_are_excluded_not_invented() -> None:
    relationships, groups = _inputs()
    definition = SplitDefinition(
        name="held-family",
        strategy="held_out_relationship_family",
        benchmark_version="benchmark-v1",
        config_hash=CONFIG_HASH,
        held_out_values=("family-1",),
    )

    assignments = generate_split_assignments(relationships, groups, definition)
    partitions = {row.relationship_id: row for row in assignments}

    assert partitions[_id("BR", "a")].partition == "test"
    assert partitions[_id("BR", "c")].partition == "excluded"
    assert partitions[_id("BR", "c")].exclusion_reason == "relationship_family_unavailable"


def test_split_assignment_is_input_order_invariant() -> None:
    relationships, groups = _inputs()
    definition = SplitDefinition(
        name="held-book",
        strategy="held_out_book",
        benchmark_version="benchmark-v1",
        config_hash=CONFIG_HASH,
        held_out_values=("ISA",),
    )

    assert generate_split_assignments(relationships, groups, definition) == (
        generate_split_assignments(
            list(reversed(relationships)), list(reversed(groups)), definition
        )
    )


def test_columnar_split_enforcement_excludes_cross_partition_group(
    tmp_path: Path,
) -> None:
    relationships, groups = _inputs()
    leakage_path = tmp_path / "leakage.parquet"
    pl.DataFrame(
        {
            name: [getattr(row, name) for row in groups]
            for name in BENCHMARK_ARTIFACT_SCHEMAS["benchmark_leakage_groups"].names()
        },
        schema=BENCHMARK_ARTIFACT_SCHEMAS["benchmark_leakage_groups"],
    ).write_parquet(leakage_path)
    shared_group = next(
        row.leakage_group_id
        for row in groups
        if row.group_type == "shared_endpoint" and row.group_key == "ISA 6:1"
    )
    assignments = pl.DataFrame(
        {
            "split_assignment_id": [_id("BSA", "a"), _id("BSA", "b")],
            "benchmark_version": ["benchmark-v1", "benchmark-v1"],
            "relationship_id": [relationships[0].relationship_id, relationships[1].relationship_id],
            "split_strategy": ["held_out_source_passage", "held_out_source_passage"],
            "partition": ["train", "test"],
            "leakage_group_id": [_id("BLG", "a"), _id("BLG", "b")],
            "seed": [6103, 6103],
            "eligibility_status": ["eligible", "eligible"],
            "exclusion_reason": [None, None],
            "config_hash": [CONFIG_HASH, CONFIG_HASH],
        },
        schema=BENCHMARK_ARTIFACT_SCHEMAS["benchmark_split_assignments"],
    )

    enforced = _exclude_split_leakage_conflicts(
        assignments,
        leakage_path=leakage_path,
        enforced_group_types=frozenset({"shared_endpoint"}),
    )

    assert enforced["partition"].to_list() == ["excluded", "excluded"]
    assert enforced["leakage_group_id"].to_list() == [shared_group, shared_group]
    assert enforced["exclusion_reason"].to_list() == [
        "leakage_group_partition_conflict:shared_endpoint",
        "leakage_group_partition_conflict:shared_endpoint",
    ]


def test_per_strategy_split_frames_match_fixture_materialization(tmp_path: Path) -> None:
    relationships, groups = _inputs()
    leakage_path = tmp_path / "leakage.parquet"
    pl.DataFrame(
        {
            name: [getattr(row, name) for row in groups]
            for name in BENCHMARK_ARTIFACT_SCHEMAS["benchmark_leakage_groups"].names()
        },
        schema=BENCHMARK_ARTIFACT_SCHEMAS["benchmark_leakage_groups"],
    ).write_parquet(leakage_path)
    loaded = load_config(Path("config/benchmark.yaml"))
    assert isinstance(loaded, BenchmarkConfig)
    unordered_pairs = {
        _id("BR", "a"): _id("BUP", "f"),
        _id("BR", "b"): _id("BUP", "f"),
        _id("BR", "c"): _id("BUP", "c"),
        _id("BR", "d"): _id("BUP", "d"),
    }
    materialized, expected_heldout = _generate_splits(
        relationships,
        unordered_pairs,
        loaded,
        "benchmark-v1",
        CONFIG_HASH,
        leakage_path,
    )
    counts: Counter[str] = Counter()
    streamed_heldout: dict[str, Partition] = {}
    frames = list(
        _iter_split_frames(
            relationships,
            unordered_pairs,
            loaded,
            "benchmark-v1",
            CONFIG_HASH,
            leakage_path,
            counts,
            streamed_heldout,
        )
    )

    assert [frame.height for frame in frames] == [len(relationships)] * 5
    assert_frame_equal(pl.concat(frames), materialized)
    assert streamed_heldout == expected_heldout
    assert sum(counts.values()) == materialized.height
