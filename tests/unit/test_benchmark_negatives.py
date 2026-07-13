"""Deterministic nonlexical presumed-negative tests."""

from __future__ import annotations

import pytest

from echoes.benchmarks.negatives import (
    KnownPositivePair,
    NegativePassage,
    PresumedNegativeDefinition,
    PresumedNegativeGenerationError,
    canonical_passage_pair,
    generate_presumed_negatives,
    iter_mapped_positive_pairs,
)

CONFIG_HASH = "b" * 64


def _passages() -> list[NegativePassage]:
    return [
        NegativePassage(
            "P_GEN_1", "hebrew", "GEN", "Torah", 10, 1, "train", frozenset({"P_GEN_2"})
        ),
        NegativePassage(
            "P_GEN_2", "hebrew", "GEN", "Torah", 10, 2, "train", frozenset({"P_GEN_1"})
        ),
        NegativePassage("P_GEN_3", "hebrew", "GEN", "Torah", 9, 3, "train"),
        NegativePassage("P_ROM_1", "greek", "ROM", "Pauline Letters", 11, 1, "train"),
        NegativePassage("P_ROM_2", "greek", "ROM", "Pauline Letters", 12, 2, "train"),
        NegativePassage("P_EXO_1", "hebrew", "EXO", "Torah", 10, 1, "train"),
        NegativePassage("P_EXO_2", "hebrew", "EXO", "Torah", 11, 2, "train"),
        NegativePassage("P_MAT_1", "greek", "MAT", "Gospels and Acts", 10, 1, "train"),
        NegativePassage("P_MAT_2", "greek", "MAT", "Gospels and Acts", 11, 2, "train"),
    ]


def _positives() -> list[KnownPositivePair]:
    return [
        KnownPositivePair("R1", "P_GEN_1", "P_ROM_1"),
        KnownPositivePair("R2", "P_EXO_1", "P_MAT_1"),
    ]


@pytest.mark.parametrize(
    "strategy",
    [
        "length_matched_random_unlinked",
        "same_book_unlinked",
        "same_book_pair_unlinked",
        "same_broad_genre_unlinked",
        "nearby_context_unlinked",
    ],
)
def test_all_five_nonlexical_strategies_are_deterministic_and_collision_free(
    strategy: str,
) -> None:
    definition = PresumedNegativeDefinition(
        benchmark_version="benchmark-v1",
        strategy=strategy,  # type: ignore[arg-type]
        split_strategy="held-book",
        generation_config_hash=CONFIG_HASH,
        seed=17,
        ratio=1.0,
        length_tolerance=2,
        nearby_distance=3,
    )
    passages = _passages()
    positives = _positives()
    rows = generate_presumed_negatives(passages, positives, definition)
    reversed_rows = generate_presumed_negatives(
        list(reversed(passages)), list(reversed(positives)), definition
    )
    known_pairs = {
        tuple(sorted((positive.passage_a_id, positive.passage_b_id))) for positive in positives
    }

    assert rows == reversed_rows
    assert len(rows) == len(positives)
    assert all(row.presumed_negative for row in rows)
    assert all(row.positive_graph_checked and row.reverse_pair_checked for row in rows)
    assert all(row.passage_overlap_checked and row.leakage_checked for row in rows)
    assert all(
        tuple(sorted((row.passage_a_id, row.passage_b_id))) not in known_pairs for row in rows
    )
    assert all("not proof of nonrelationship" in row.notes for row in rows)


def test_length_matched_strategy_obeys_tolerance_and_rejects_overlap() -> None:
    definition = PresumedNegativeDefinition(
        benchmark_version="benchmark-v1",
        strategy="length_matched_random_unlinked",
        split_strategy="held-book",
        generation_config_hash=CONFIG_HASH,
        seed=4,
        ratio=1.0,
        length_tolerance=1,
    )

    rows = generate_presumed_negatives(_passages(), _positives(), definition)

    assert all(row.length_difference <= 1 for row in rows)
    assert not any({row.passage_a_id, row.passage_b_id} == {"P_GEN_1", "P_GEN_2"} for row in rows)


def test_impossible_ratio_fails_clearly_instead_of_mislabelling_a_positive() -> None:
    passages = [
        NegativePassage("P_A", "hebrew", "GEN", "Torah", 5, 1, "train"),
        NegativePassage("P_B", "greek", "ROM", "Pauline Letters", 5, 1, "train"),
    ]
    positives = [KnownPositivePair("R1", "P_A", "P_B")]
    definition = PresumedNegativeDefinition(
        benchmark_version="benchmark-v1",
        strategy="length_matched_random_unlinked",
        split_strategy="held-book",
        generation_config_hash=CONFIG_HASH,
        seed=1,
    )

    with pytest.raises(PresumedNegativeGenerationError, match="requested 1"):
        generate_presumed_negatives(passages, positives, definition)


def test_known_positive_cannot_cross_split_partitions() -> None:
    passages = [
        NegativePassage("P_A", "hebrew", "GEN", "Torah", 5, 1, "train"),
        NegativePassage("P_B", "greek", "ROM", "Pauline Letters", 5, 1, "test"),
    ]
    definition = PresumedNegativeDefinition(
        benchmark_version="benchmark-v1",
        strategy="length_matched_random_unlinked",
        split_strategy="held-book",
        generation_config_hash=CONFIG_HASH,
        seed=1,
    )

    with pytest.raises(ValueError, match="crosses split partitions"):
        generate_presumed_negatives(passages, [KnownPositivePair("R1", "P_A", "P_B")], definition)


def test_range_and_excluded_positive_pairs_remain_in_collision_graph() -> None:
    passages = [
        NegativePassage("P_A", "hebrew", "GEN", "Torah", 5, 1, "train"),
        NegativePassage("P_B", "hebrew", "GEN", "Torah", 5, 2, "train"),
        NegativePassage("P_C", "hebrew", "GEN", "Torah", 5, 3, "train"),
    ]
    eligible_templates = [KnownPositivePair("R_ELIGIBLE", "P_A", "P_B")]
    positive_graph = set(iter_mapped_positive_pairs(["P_A"], ["P_B", "P_C"]))
    positive_graph.add(canonical_passage_pair("P_B", "P_C"))
    definition = PresumedNegativeDefinition(
        benchmark_version="benchmark-v1",
        strategy="length_matched_random_unlinked",
        split_strategy="held-book",
        generation_config_hash=CONFIG_HASH,
        seed=1,
    )

    with pytest.raises(PresumedNegativeGenerationError, match="governed constraints"):
        generate_presumed_negatives(
            passages,
            eligible_templates,
            definition,
            positive_graph_pairs=positive_graph,
        )


def test_positive_graph_must_include_eligible_template_pairs() -> None:
    definition = PresumedNegativeDefinition(
        benchmark_version="benchmark-v1",
        strategy="length_matched_random_unlinked",
        split_strategy="held-book",
        generation_config_hash=CONFIG_HASH,
        seed=1,
    )

    with pytest.raises(ValueError, match="include every eligible"):
        generate_presumed_negatives(
            _passages(),
            _positives(),
            definition,
            positive_graph_pairs=set(),
        )
