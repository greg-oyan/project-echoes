from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

import pytest

from echoes.lexical import nulls as null_models
from echoes.lexical.nulls import (
    NullReplicate,
    PassageFeatures,
    frequency_preserving_synthetic,
    validate_frequency_preserving_synthetic,
    validate_within_book_reassignment,
    within_book_reassignment,
)
from echoes.lexical.statistics import (
    benjamini_hochberg,
    calibrate_null_thresholds,
    hypergeometric_upper_tail,
    paired_bootstrap_difference,
)


def test_hypergeometric_upper_tail_matches_hand_calculation() -> None:
    result = hypergeometric_upper_tail(5, 2, 2, 1)

    # P(X >= 1) = 1 - C(2, 0) C(3, 2) / C(5, 2) = 7 / 10.
    assert result.expected_overlap == pytest.approx(0.8)
    assert result.upper_tail_p_value == pytest.approx(0.7)
    with pytest.raises(ValueError, match="impossible"):
        hypergeometric_upper_tail(5, 1, 1, 2)


def test_benjamini_hochberg_matches_hand_calculation_and_is_monotone() -> None:
    values = (0.01, 0.04, 0.03, 0.002)
    adjusted = benjamini_hochberg(values)

    assert adjusted == pytest.approx((0.02, 0.04, 0.04, 0.008))
    sorted_pairs = sorted(zip(values, adjusted, strict=True))
    assert [q for _, q in sorted_pairs] == sorted(q for _, q in sorted_pairs)


def test_paired_bootstrap_is_deterministic_and_retains_replicates() -> None:
    first = paired_bootstrap_difference(
        (0.3, 0.5, 0.9),
        (0.1, 0.3, 0.7),
        iterations=100,
        seed=20260713,
    )
    second = paired_bootstrap_difference(
        (0.3, 0.5, 0.9),
        (0.1, 0.3, 0.7),
        iterations=100,
        seed=20260713,
    )

    assert first == second
    assert first.observed_difference == pytest.approx(0.2)
    assert first.interval_low == pytest.approx(0.2)
    assert first.interval_high == pytest.approx(0.2)
    assert len(first.replicate_differences) == 100


def test_null_threshold_summary_uses_finite_simulation_correction() -> None:
    summaries = calibrate_null_thresholds(
        (0.9, 0.8, 0.2),
        ((0.7, 0.1), (0.9, 0.85), ()),
        (0.8, 1.0),
    )

    first = summaries[0]
    assert first.observed_count == 2
    assert first.null_counts == (0, 2, 0)
    assert first.null_mean_count == pytest.approx(2.0 / 3.0)
    assert first.enrichment == pytest.approx(3.0)
    assert first.empirical_upper_tail_probability == 0.5
    assert first.raw_empirical_fdr == pytest.approx(1.0 / 3.0)
    assert first.presentation_empirical_fdr == pytest.approx(1.0 / 3.0)

    empty_observed = summaries[1]
    assert empty_observed.observed_count == 0
    assert empty_observed.empirical_upper_tail_probability == 1.0
    assert empty_observed.enrichment is None
    assert empty_observed.raw_empirical_fdr is None


def _source_passages() -> tuple[PassageFeatures, ...]:
    return (
        PassageFeatures("hb-1", "hebrew", "GEN", "torah", "hb:lemma", ("a", "b", "a")),
        PassageFeatures("hb-2", "hebrew", "GEN", "torah", "hb:lemma", ("b", "c")),
        PassageFeatures("hb-3", "hebrew", "EXO", "torah", "hb:lemma", ("d", "e")),
        PassageFeatures("gk-1", "greek", "MAT", "gospel", "gk:lemma", ("x", "y")),
        PassageFeatures("hb-1", "hebrew", "GEN", "torah", "hb:root", ("r1", "r2")),
        PassageFeatures("hb-1", "hebrew", "GEN", "torah", "en:gloss", ("light", "day")),
        PassageFeatures("gk-1", "greek", "MAT", "gospel", "en:gloss", ("light", "word")),
    )


def test_within_book_reassignment_preserves_exact_conservation_contracts() -> None:
    source = _source_passages()
    replicate = within_book_reassignment(source, seed=17)
    reordered = within_book_reassignment(tuple(reversed(source)), seed=17)
    validation = validate_within_book_reassignment(source, replicate)

    assert replicate == reordered
    assert validation.is_valid
    assert validation.passage_count_preserved
    assert validation.passage_lengths_preserved
    assert validation.conditioning_labels_preserved
    assert validation.source_identities_replaced
    assert validation.representation_isolation_preserved
    assert validation.exact_feature_totals_preserved is True
    assert validation.sequence_digest_changed
    assert validation.frequency_deviations == ()
    assert any(
        simulated.features != original.features
        for simulated in replicate.passages
        for original in source
        if (
            simulated.source_passage_id,
            simulated.corpus,
            simulated.representation,
        )
        == (original.passage_id, original.corpus, original.representation)
    )


def test_within_book_validator_allows_only_mathematically_degenerate_unchanged_pool() -> None:
    source = (
        PassageFeatures("p1", "hebrew", "GEN", "torah", "hb:lemma", ("same", "same")),
        PassageFeatures("p2", "hebrew", "GEN", "torah", "hb:lemma", ("same",)),
    )
    replicate = within_book_reassignment(source, seed=1)
    validation = validate_within_book_reassignment(source, replicate)

    assert validation.is_valid
    assert validation.sequence_digest_changed is False
    assert validation.degenerate_units == ("hebrew|hb:lemma|GEN",)


def test_frequency_preserving_synthetic_is_deterministic_isolated_and_validated() -> None:
    source = _source_passages()
    replicate = frequency_preserving_synthetic(
        source,
        seed=23,
        minimum_book_token_count=5,
    )
    reordered = frequency_preserving_synthetic(
        tuple(reversed(source)),
        seed=23,
        minimum_book_token_count=5,
    )
    validation = validate_frequency_preserving_synthetic(source, replicate)

    assert replicate == reordered
    assert validation.is_valid
    assert validation.passage_count_preserved
    assert validation.passage_lengths_preserved
    assert validation.conditioning_labels_preserved
    assert validation.source_identities_replaced
    assert validation.representation_isolation_preserved
    assert validation.exact_feature_totals_preserved is None
    assert validation.no_original_sequences_copied is True
    assert validation.frequency_deviations

    scopes = {
        (passage.corpus, passage.representation, passage.book): passage.conditioning_scope
        for passage in replicate.passages
    }
    assert scopes[("hebrew", "hb:lemma", "GEN")] == "book"
    assert scopes[("hebrew", "hb:lemma", "EXO")] == "broad_genre"
    hebrew_glosses = {
        feature
        for passage in replicate.passages
        if passage.corpus == "hebrew" and passage.representation == "en:gloss"
        for feature in passage.features
    }
    greek_glosses = {
        feature
        for passage in replicate.passages
        if passage.corpus == "greek" and passage.representation == "en:gloss"
        for feature in passage.features
    }
    assert "word" not in hebrew_glosses
    assert "day" not in greek_glosses

    deviation_sums: defaultdict[tuple[str, str, str, str], float] = defaultdict(float)
    for item in validation.frequency_deviations:
        deviation_sums[
            (
                item.corpus,
                item.representation,
                item.conditioning_scope,
                item.conditioning_value,
            )
        ] += item.deviation
    assert all(value == pytest.approx(0.0) for value in deviation_sums.values())


def test_synthetic_validator_rejects_length_tampering() -> None:
    source = _source_passages()
    replicate = frequency_preserving_synthetic(
        source,
        seed=29,
        minimum_book_token_count=5,
    )
    first = replace(replicate.passages[0], features=(*replicate.passages[0].features, "extra"))
    tampered = NullReplicate(
        family=replicate.family,
        seed=replicate.seed,
        passages=(first, *replicate.passages[1:]),
        minimum_book_token_count=replicate.minimum_book_token_count,
    )

    validation = validate_frequency_preserving_synthetic(source, tampered)
    assert validation.is_valid is False
    assert "passage_lengths_changed" in validation.errors


def test_synthetic_validator_rejects_copy_of_any_conditioned_source_sequence() -> None:
    source = _source_passages()
    replicate = frequency_preserving_synthetic(
        source,
        seed=31,
        minimum_book_token_count=5,
    )
    passages = list(replicate.passages)
    target_index = next(
        index
        for index, passage in enumerate(passages)
        if passage.source_passage_id == "hb-3" and passage.representation == "hb:lemma"
    )
    # hb-3 falls back to the Torah distribution; ("b", "c") is hb-2's source sequence.
    passages[target_index] = replace(passages[target_index], features=("b", "c"))
    tampered = NullReplicate(
        family=replicate.family,
        seed=replicate.seed,
        passages=tuple(passages),
        minimum_book_token_count=replicate.minimum_book_token_count,
    )

    validation = validate_frequency_preserving_synthetic(source, tampered)
    assert validation.is_valid is False
    assert "synthetic_original_sequence_copied" in validation.errors


def test_synthetic_conditioning_indexes_are_built_once_per_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tuple(
        PassageFeatures(
            f"hb-{index:04d}",
            "hebrew",
            f"BOOK-{index % 5}",
            f"genre-{index % 2}",
            "hb:lemma",
            tuple(f"lemma-{(index + offset) % 17}" for offset in range(12)),
        )
        for index in range(500)
    )
    original = null_models._build_conditioning_indexes
    calls = 0

    def counted(
        passages: tuple[PassageFeatures, ...],
    ) -> null_models._ConditioningIndexes:
        nonlocal calls
        calls += 1
        return original(passages)

    monkeypatch.setattr(null_models, "_build_conditioning_indexes", counted)
    replicate = frequency_preserving_synthetic(
        source,
        seed=37,
        minimum_book_token_count=20,
    )
    assert calls == 1

    validation = validate_frequency_preserving_synthetic(source, replicate)
    assert validation.is_valid
    assert calls == 2


def test_prepared_null_source_reuses_indexes_and_compacts_deviation_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tuple(
        PassageFeatures(
            f"hb-{index:04d}",
            "hebrew",
            f"BOOK-{index % 3}",
            "genre",
            "hb:lemma",
            tuple(f"lemma-{(index + offset) % 11}" for offset in range(8)),
        )
        for index in range(100)
    )
    original = null_models._build_conditioning_indexes
    calls = 0

    def counted(passages: tuple[PassageFeatures, ...]) -> null_models._ConditioningIndexes:
        nonlocal calls
        calls += 1
        return original(passages)

    monkeypatch.setattr(null_models, "_build_conditioning_indexes", counted)
    prepared = null_models.prepare_null_source(source)
    for seed in (41, 43):
        replicate = frequency_preserving_synthetic(
            prepared,
            seed=seed,
            minimum_book_token_count=20,
        )
        validation = validate_frequency_preserving_synthetic(
            prepared,
            replicate,
            retain_frequency_deviation_details=False,
        )
        assert validation.is_valid
        assert validation.frequency_deviations == ()
        assert validation.frequency_deviation_count > 0
        assert validation.maximum_absolute_frequency_deviation is not None
        assert validation.mean_absolute_frequency_deviation is not None
    assert calls == 1
