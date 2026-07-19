from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

import polars as pl
import pytest

from echoes.lexical.candidates import (
    CalibrationSelection,
    CandidateEvidenceContext,
    CandidateMaterializationError,
    KnownPair,
    _governed_score_reconciliation,
    build_feature_evidence_indexes,
    build_review_queue,
    candidate_q_values,
    iter_candidate_artifact_batches,
)
from echoes.lexical.config import load_lexical_config
from echoes.lexical.identity import FeatureIdentityPayload, build_feature_identity
from echoes.lexical.retrieval import (
    DETECTOR_FAMILIES,
    CandidateAggregate,
    CandidateDirection,
)
from echoes.lexical.sequences import FeatureOccurrence, PassageLexicalSequence
from echoes.lexical.statistics import hypergeometric_upper_tail


def _occurrences(values: Sequence[str], token_ids: Sequence[str]) -> tuple[FeatureOccurrence, ...]:
    return tuple(
        FeatureOccurrence(
            value=value,
            position_in_passage=index,
            token_id=token_ids[min(index - 1, len(token_ids) - 1)],
            source_word_id=f"word-{token_ids[min(index - 1, len(token_ids) - 1)]}",
        )
        for index, value in enumerate(values, start=1)
    )


def _passage(
    passage_id: str,
    lemmas: Sequence[str],
    *,
    corpus: Literal["hebrew", "greek"] = "hebrew",
    book: str = "GEN",
    start: int = 1,
    granularity: str = "verse",
    roots: Sequence[str] = (),
    surfaces: Sequence[str] = (),
    pos: Sequence[str] = (),
    morphology: Sequence[str] = (),
    glosses: Sequence[str] = (),
    token_count: int | None = None,
    provenance: Sequence[str] | None = None,
) -> PassageLexicalSequence:
    count = token_count or max(len(lemmas), len(roots), len(surfaces), len(glosses), 1)
    token_ids = tuple(provenance or (f"{passage_id}-token-{i}" for i in range(1, count + 1)))
    if len(token_ids) != count:
        raise ValueError("fixture provenance must equal token_count")
    return PassageLexicalSequence(
        passage_id=passage_id,
        corpus=corpus,
        book=book,
        book_order=1,
        analysis_profile="edition_complete",
        analysis_reading="qere" if corpus == "hebrew" else "source",
        granularity=granularity,
        start_reference=f"{book}.{start}.1",
        end_reference=f"{book}.{start}.1",
        source_passage_digest=passage_id.ljust(64, "0")[:64],
        start_stream_position_in_corpus=start,
        token_count=count,
        disputed_passage_flag=False,
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        lemma=_occurrences(lemmas, token_ids),
        root=_occurrences(roots, token_ids),
        surface=_occurrences(surfaces, token_ids),
        folded_surface=_occurrences(surfaces, token_ids),
        part_of_speech=_occurrences(pos, token_ids),
        morphology=_occurrences(morphology, token_ids),
        english_gloss=_occurrences(glosses, token_ids),
        provenance_token_ids=token_ids,
        zero_width_token_ids=(),
        punctuation_token_ids=(),
        elided_token_ids=(),
    )


def _derived(values: Sequence[str], family: str) -> tuple[str, ...]:
    if family.endswith("ngram"):
        return tuple(
            "\u241f".join(values[start : start + size])
            for size in (2, 3)
            for start in range(len(values) - size + 1)
        )
    return tuple(
        f"{values[first]}\u241f*\u241f{values[second]}"
        for first in range(len(values))
        for second in range(first + 2, min(len(values), first + 4))
    )


def _evidence_indexes(
    passages: Sequence[PassageLexicalSequence],
    *,
    rare: set[tuple[str, str, str]] | None = None,
    formulaic: set[tuple[str, str, str]] | None = None,
) -> tuple[
    dict[tuple[str, str, str], tuple[str, int, int, bool, bool]],
    dict[tuple[str, str, str], tuple[str, ...]],
]:
    corpus_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    document_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for passage in passages:
        namespace = "hb" if passage.corpus == "hebrew" else "gk"
        for family, sequence_family in (
            ("lemma", "lemma"),
            ("root", "root"),
            ("normalized_surface", "surface"),
            ("part_of_speech", "part_of_speech"),
            ("morphology", "morphology"),
        ):
            values = passage.values(sequence_family)
            corpus_counts[(namespace, family)].update(values)
            document_counts[(namespace, family)].update(set(values))
        glosses = passage.values("english_gloss")
        corpus_counts[("en", "english_gloss")].update(glosses)
        document_counts[("en", "english_gloss")].update(set(glosses))
        for source_family in ("lemma", "root"):
            values = passage.values(source_family)
            for derived_family in (
                f"{source_family}_ngram",
                f"{source_family}_skipgram",
            ):
                items = _derived(values, derived_family)
                corpus_counts[(namespace, derived_family)].update(items)
                document_counts[(namespace, derived_family)].update(set(items))
    rows: list[dict[str, object]] = []
    rare = rare or set()
    formulaic = formulaic or set()
    for (namespace, family), counts in sorted(corpus_counts.items()):
        for value, corpus_frequency in sorted(counts.items()):
            order = 1
            if family.endswith("ngram"):
                order = value.count("\u241f") + 1
            elif family.endswith("skipgram"):
                order = 2
            feature_id = build_feature_identity(
                FeatureIdentityPayload(
                    feature_family=family,  # type: ignore[arg-type]
                    language_namespace=namespace,  # type: ignore[arg-type]
                    feature_value=value,
                    feature_order=order,
                )
            ).identifier
            key = (namespace, family, value)
            rows.append(
                {
                    "language_namespace": namespace,
                    "feature_family": family,
                    "feature_value": value,
                    "feature_id": feature_id,
                    "corpus_frequency": corpus_frequency,
                    "document_frequency": document_counts[(namespace, family)][value],
                    "is_rare": key in rare,
                    "is_formulaic": key in formulaic,
                }
            )
    vocabulary = pl.DataFrame(rows)
    return build_feature_evidence_indexes(passages, vocabulary)


def _rrf_score(ranks: Mapping[str, int], *, rrf_k: int = 60) -> float:
    selected: dict[str, tuple[int, str]] = {}
    for detector, rank in ranks.items():
        family = DETECTOR_FAMILIES[detector]
        selected[family] = min(selected.get(family, (rank, detector)), (rank, detector))
    return math.fsum(1.0 / (rrf_k + rank) for rank, _ in selected.values())


def _candidate(
    passage_a: PassageLexicalSequence,
    passage_b: PassageLexicalSequence,
    *,
    corpus_pair: str = "hb_hb",
    rare_score: float = 0.0,
    reverse: bool = False,
) -> CandidateAggregate:
    first, second = sorted((passage_a.passage_id, passage_b.passage_id))
    scores = {
        "jaccard": 0.5,
        "weighted_jaccard": 0.4,
        "tfidf_cosine": 0.3,
        "bm25": 0.2,
        "rare_lemma_root": rare_score,
        "phrase_association": 0.0,
        "longest_common_subsequence": 0.0,
        "weighted_sequence_alignment": 0.0,
        "pos_morphology_support": 0.0,
    }
    ranks = {
        detector: rank
        for rank, detector in enumerate(
            (detector for detector in DETECTOR_FAMILIES if scores[detector] > 0.0),
            start=1,
        )
    }
    candidate = CandidateAggregate(
        candidate_pair_id=f"C_{first}_{second}_{passage_a.granularity}",
        canonical_unordered_pair_id=f"C_{first}_{second}_{passage_a.granularity}",
        passage_a_id=first,
        passage_b_id=second,
        corpus_pair=corpus_pair,
        analysis_profile="edition_complete",
        granularity=passage_a.granularity,
    )
    candidate.add_direction(
        CandidateDirection(
            direction="a_to_b",
            query_passage_id=first,
            target_passage_id=second,
            scores=scores,
            ranks=ranks,
            rrf_score=_rrf_score(ranks),
        )
    )
    if reverse:
        reverse_ranks = {detector: rank + 2 for detector, rank in ranks.items()}
        candidate.add_direction(
            CandidateDirection(
                direction="b_to_a",
                query_passage_id=second,
                target_passage_id=first,
                scores={name: value * 0.9 for name, value in scores.items()},
                ranks=reverse_ranks,
                rrf_score=_rrf_score(reverse_ranks),
            )
        )
    return candidate


def _context(
    passages: Sequence[PassageLexicalSequence],
    *,
    corpus_pair: str = "hb_hb",
    rare: set[tuple[str, str, str]] | None = None,
    formulaic: set[tuple[str, str, str]] | None = None,
    score_threshold: float = 0.0,
    known_pairs: Mapping[tuple[str, str], KnownPair] | None = None,
) -> CandidateEvidenceContext:
    statistics, postings = _evidence_indexes(passages, rare=rare, formulaic=formulaic)
    return CandidateEvidenceContext(
        experiment_run_id="lexical-test-run",
        configuration_hash="a" * 64,
        sequences={passage.passage_id: passage for passage in passages},
        feature_statistics=statistics,
        feature_passages=postings,
        representation_ids={corpus_pair: f"representation-{corpus_pair}"},
        known_pairs=known_pairs or {},
        calibration={
            corpus_pair: CalibrationSelection(
                score_threshold=score_threshold,
                estimated_empirical_fdr=0.1,
                empirical_rate=0.01,
                both_null_families_present=True,
            )
        },
        config=load_lexical_config(Path("config/lexical.yaml")),
    )


def _batch(
    candidate: CandidateAggregate, context: CandidateEvidenceContext
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]], pl.DataFrame]:
    batch = next(
        iter_candidate_artifact_batches(
            {candidate.candidate_pair_id: candidate},
            context=context,
            q_values={candidate.candidate_pair_id: 0.25},
        )
    )
    return (
        batch.candidate_pairs.row(0, named=True),
        batch.candidate_evidence.row(0, named=True),
        list(batch.shared_evidence.iter_rows(named=True)),
        batch.detector_scores,
    )


def test_candidate_context_precomputes_global_statistics_once() -> None:
    first = _passage("P_A", ("alpha", "beta"), corpus="hebrew")
    second = _passage("P_B", ("beta",), corpus="hebrew")
    greek = _passage("P_C", ("gamma", "delta", "epsilon"), corpus="greek")
    context = _context([first, second, greek])

    expected_lemma_population = sum(
        1
        for namespace, family, _ in context.feature_statistics
        if namespace == "hb" and family == "lemma"
    )
    assert context.feature_population_counts[("hb", "lemma")] == expected_lemma_population
    assert context.document_counts_by_namespace == {"en": 3, "hb": 2, "gk": 1}
    assert context.representation_statistics["hb_hb"] == (2, 1.5)
    assert context.representation_statistics["gnt_gnt"] == (1, 3.0)
    assert context.representation_statistics["hb_gnt_english_bridge"][0] == 3
    assert context.book_ordinals == {"P_A": 0, "P_B": 1, "P_C": 0}


def test_governed_score_reconciliation_leaves_exact_match_trace_unchanged() -> None:
    assert (
        _governed_score_reconciliation(
            detector="bm25",
            candidate_pair_id="candidate",
            persisted=12.867698770178,
            recomputed=12.867698770178,
            decimals=12,
        )
        is None
    )


def test_governed_score_reconciliation_records_one_decimal_bin() -> None:
    assert _governed_score_reconciliation(
        detector="bm25",
        candidate_pair_id="candidate",
        persisted=12.867698770178,
        recomputed=12.867698770179,
        decimals=12,
    ) == {
        "status": "accepted_adjacent_float64_reduction_bin",
        "score_quantization_decimals": 12,
        "persisted_quantized_decimal": "12.867698770178",
        "recomputed_quantized_decimal": "12.867698770179",
        "persisted_minus_recomputed_bin_delta": -1,
        "maximum_allowed_absolute_bin_delta": 1,
    }


def test_governed_score_reconciliation_rejects_two_decimal_bins() -> None:
    with pytest.raises(
        CandidateMaterializationError,
        match="persisted_minus_recomputed_bin_delta=-2",
    ):
        _governed_score_reconciliation(
            detector="bm25",
            candidate_pair_id="candidate",
            persisted=12.867698770178,
            recomputed=12.867698770180,
            decimals=12,
        )


def test_candidate_materialization_byte_flush_preserves_complete_outputs() -> None:
    first = _passage("P_A", ("shared", "alpha"), start=1)
    second = _passage("P_B", ("shared", "beta"), start=2)
    third = _passage("P_C", ("shared", "gamma"), start=3)
    context = _context((first, second, third))
    candidates = {
        candidate.candidate_pair_id: candidate
        for candidate in (_candidate(first, second), _candidate(first, third))
    }
    q_values = dict.fromkeys(candidates, 0.25)

    combined = list(
        iter_candidate_artifact_batches(
            candidates,
            context=context,
            q_values=q_values,
            materialization_target_bytes=1024**3,
        )
    )
    reservations: list[tuple[str, int]] = []

    def resource_check(stage: str, *, estimated_additional_bytes: int = 0) -> None:
        reservations.append((stage, estimated_additional_bytes))

    split = list(
        iter_candidate_artifact_batches(
            candidates,
            context=context,
            q_values=q_values,
            materialization_target_bytes=1,
            resource_check=resource_check,
        )
    )

    assert len(combined) == 1
    assert len(split) == 2
    for attribute, sort_columns in (
        ("candidate_pairs", ("candidate_pair_id",)),
        ("detector_scores", ("candidate_pair_id", "detector")),
        ("candidate_evidence", ("candidate_pair_id",)),
        ("shared_evidence", ("candidate_pair_id", "evidence_id")),
        ("ablation_results", ("subject_id", "ablation_name")),
    ):
        expected = pl.concat([getattr(batch, attribute) for batch in combined]).sort(*sort_columns)
        observed = pl.concat([getattr(batch, attribute) for batch in split]).sort(*sort_columns)
        assert observed.equals(expected)
    candidate_stages = [stage for stage, _ in reservations if ":candidate:" in stage]
    frame_stages = [stage for stage, _ in reservations if ":frames:" in stage]
    assert len(candidate_stages) == 2
    assert len(frame_stages) == 2
    assert all(estimate > 0 for _, estimate in reservations)


def test_cross_language_bridge_never_conflates_source_surfaces_and_fails_ablation() -> None:
    hebrew = _passage(
        "P_A",
        ("source-a",),
        corpus="hebrew",
        surfaces=("same-ascii",),
        glosses=("shared",),
    )
    greek = _passage(
        "P_B",
        ("source-b",),
        corpus="greek",
        surfaces=("same-ascii",),
        glosses=("shared",),
    )
    candidate = _candidate(hebrew, greek, corpus_pair="hb_gnt_english_bridge")
    pair, evidence, shared, _ = _batch(
        candidate, _context((hebrew, greek), corpus_pair="hb_gnt_english_bridge")
    )

    assert evidence["shared_lemma_count"] == 0
    assert evidence["shared_root_count"] == 0
    assert evidence["shared_surface_count"] == 0
    assert {row["evidence_family"] for row in shared} == {
        "english_gloss",
        "longest_common_subsequence_trace",
    }
    assert all(row["english_derived"] for row in shared)
    assert pair["contains_english_derived_evidence"]
    assert not pair["english_ablation_survives"]
    assert not pair["review_eligible"]
    assert "english_only_ablation_failure" in str(pair["eligibility_reason"])

    batch = next(
        iter_candidate_artifact_batches(
            {candidate.candidate_pair_id: candidate},
            context=_context((hebrew, greek), corpus_pair="hb_gnt_english_bridge"),
            q_values={candidate.candidate_pair_id: 0.25},
        )
    )
    ablations = batch.ablation_results
    assert set(ablations.get_column("ablation_name")) == set(
        load_lexical_config(Path("config/lexical.yaml")).ablations.names
    )
    english = ablations.filter(
        pl.col("ablation_name") == "remove_all_english_derived_features"
    ).row(0, named=True)
    assert english["score_after"] == 0.0
    assert english["rank_after"] is None
    assert english["non_english_evidence_remains"] is False
    assert english["review_eligible_after"] is False
    assert english["downgrade_required"] is True


def test_penalties_change_eligibility_and_are_reversible_in_typed_ablation() -> None:
    first = _passage("P_A", ("formula",), book="GEN", surfaces=("first",))
    second = _passage("P_B", ("formula",), book="EXO", surfaces=("second",), start=10)
    candidate = _candidate(first, second)
    context = _context(
        (first, second),
        formulaic={("hb", "lemma", "formula")},
        score_threshold=0.02,
    )
    batch = next(
        iter_candidate_artifact_batches(
            {candidate.candidate_pair_id: candidate},
            context=context,
            q_values={candidate.candidate_pair_id: 0.25},
        )
    )
    pair = batch.candidate_pairs.row(0, named=True)
    evidence = batch.candidate_evidence.row(0, named=True)
    formulaic = batch.ablation_results.filter(
        pl.col("ablation_name") == "remove_formulaic_penalty"
    ).row(0, named=True)

    assert evidence["raw_rrf_score"] > context.calibration["hb_hb"].score_threshold
    assert evidence["rrf_score"] < context.calibration["hb_hb"].score_threshold
    assert pair["review_eligible"] is False
    assert "below_frozen_rrf_threshold" in str(pair["eligibility_reason"])
    assert evidence["raw_rrf_score"] + evidence["total_penalty_contribution"] == pytest.approx(
        evidence["rrf_score"]
    )
    assert formulaic["score_after"] > formulaic["score_before"]
    assert formulaic["penalty_after"] < formulaic["penalty_before"]
    assert pair["proper_name_only_flag"] is False
    assert str(pair["proper_name_annotation_status"]).startswith("unavailable")


def test_complete_evidence_digest_binds_calibration_and_detector_traces() -> None:
    first = _passage("P_A", ("shared",), book="GEN", surfaces=("first",))
    second = _passage("P_B", ("shared",), book="EXO", surfaces=("second",))
    candidate = _candidate(first, second)

    def materialize(threshold: float) -> tuple[dict[str, object], pl.DataFrame]:
        batch = next(
            iter_candidate_artifact_batches(
                {candidate.candidate_pair_id: candidate},
                context=_context((first, second), score_threshold=threshold),
                q_values={candidate.candidate_pair_id: 0.25},
            )
        )
        return batch.candidate_evidence.row(0, named=True), batch.detector_scores

    baseline, detector_scores = materialize(0.0)
    changed, _ = materialize(0.01)

    assert baseline["evidence_digest"] != changed["evidence_digest"]
    assert baseline["selected_score_threshold"] == 0.0
    assert baseline["both_null_families_present"] is True
    for row in detector_scores.iter_rows(named=True):
        components = json.loads(str(row["score_components_json"]))
        assert isinstance(components, dict)
        assert len(str(row["score_trace_digest"])) == 64


def test_within_language_label_rejects_a_cross_namespace_candidate() -> None:
    hebrew = _passage("P_A", ("same",), corpus="hebrew", surfaces=("ha",))
    greek = _passage("P_B", ("same",), corpus="greek", surfaces=("ga",))
    candidate = _candidate(hebrew, greek, corpus_pair="hb_hb")

    with pytest.raises(CandidateMaterializationError, match="crosses source-language namespaces"):
        candidate_q_values(
            {candidate.candidate_pair_id: candidate},
            _context((hebrew, greek), corpus_pair="hb_hb"),
        )


def test_correlated_lemma_root_and_vector_restatements_cannot_bypass_rare_rule() -> None:
    first = _passage(
        "P_A",
        ("rare-lemma",),
        roots=("rare-root",),
        surfaces=("surface-a",),
    )
    second = _passage(
        "P_B",
        ("rare-lemma",),
        roots=("rare-root",),
        surfaces=("surface-b",),
        start=10,
    )
    rare = {
        ("hb", "lemma", "rare-lemma"),
        ("hb", "root", "rare-root"),
    }
    pair, evidence, shared, _ = _batch(
        _candidate(first, second, rare_score=1.0),
        _context((first, second), rare=rare),
    )

    assert evidence["shared_rare_lemma_count"] == 1
    assert evidence["shared_rare_root_count"] == 1
    assert evidence["independent_co_signal_count"] == 0
    assert not evidence["rare_rule_passed"]
    assert not pair["review_eligible"]
    notes = ";".join(str(row["notes"]) for row in shared)
    assert "lemma_root_same_token_positions" in notes
    assert "tfidf_bm25_same_item" in notes


def test_second_rare_item_at_distinct_positions_is_traceable_independent_evidence() -> None:
    first = _passage(
        "P_A",
        ("rare-a", "rare-b"),
        surfaces=("surface-a1", "surface-a2"),
    )
    second = _passage(
        "P_B",
        ("rare-a", "rare-b"),
        surfaces=("surface-b1", "surface-b2"),
        start=10,
    )
    rare = {("hb", "lemma", "rare-a"), ("hb", "lemma", "rare-b")}
    _, evidence, shared, _ = _batch(
        _candidate(first, second, rare_score=1.0),
        _context((first, second), rare=rare),
    )

    assert evidence["rare_rule_passed"]
    assert evidence["independent_co_signal_count"] == 1
    marked = [row for row in shared if row["counts_as_independent_co_signal"]]
    assert len(marked) == 1
    assert "second_distinct_rare_lemma_or_root" in str(marked[0]["notes"])


def test_evidence_positions_frequencies_alternatives_and_rrf_contributions_reconcile() -> None:
    first = _passage("P_A", ("shared",), surfaces=("surface-a",), start=1)
    second = _passage("P_B", ("shared",), surfaces=("surface-b",), start=10)
    alternative = _passage("P_C", ("shared",), surfaces=("surface-c",), start=20)
    candidate = _candidate(first, second, reverse=True)
    _, evidence, shared, detector_scores = _batch(candidate, _context((first, second, alternative)))

    lemma = next(row for row in shared if row["evidence_family"] == "lemma")
    assert json.loads(str(lemma["passage_a_positions_json"])) == [0]
    assert json.loads(str(lemma["passage_b_positions_json"])) == [0]
    assert lemma["corpus_frequency"] == 3
    assert lemma["document_frequency"] == 3
    assert "alternative_passage_ids=P_C" in str(lemma["notes"])
    expected_feature_id = build_feature_identity(
        FeatureIdentityPayload(
            feature_family="lemma",
            language_namespace="hb",
            feature_value="shared",
            feature_order=1,
        )
    ).identifier
    assert lemma["feature_id"] == expected_feature_id
    assert (
        detector_scores.get_column("score_contribution").sum()
        + detector_scores.get_column("penalty_contribution").sum()
    ) == pytest.approx(evidence["rrf_score"], abs=1e-12)
    assert evidence["raw_rrf_score"] >= evidence["rrf_score"]
    assert set(detector_scores.filter(pl.col("score_contribution") > 0)["detector"]) == {
        "jaccard",
        "tfidf_cosine",
    }


def test_overlap_exact_duplicate_and_book_ordinal_proximity_are_explicit() -> None:
    shared_tokens = ("shared-token", "other-token")
    overlapping_a = _passage(
        "P_A",
        ("common",),
        surfaces=("surface-a",),
        token_count=2,
        provenance=shared_tokens,
    )
    overlapping_b = _passage(
        "P_B",
        ("common",),
        surfaces=("surface-b",),
        token_count=2,
        provenance=("shared-token", "different-token"),
        start=10,
    )
    pair, evidence, _, _ = _batch(
        _candidate(overlapping_a, overlapping_b),
        _context((overlapping_a, overlapping_b)),
    )
    assert evidence["overlap_exclusion"]
    assert "passage_or_constituent_overlap" in str(pair["eligibility_reason"])

    duplicate_a = _passage("P_C", ("common",), surfaces=("duplicate",), start=1)
    duplicate_b = _passage("P_D", ("common",), surfaces=("duplicate",), start=10)
    pair, evidence, _, _ = _batch(
        _candidate(duplicate_a, duplicate_b), _context((duplicate_a, duplicate_b))
    )
    assert not evidence["overlap_exclusion"]
    assert "exact_duplicate_positive_control" in str(pair["eligibility_reason"])
    assert not pair["review_eligible"]

    adjacent_a = _passage("P_E", ("common",), surfaces=("ea",), start=1)
    adjacent_b = _passage("P_F", ("common",), surfaces=("fb",), start=10_000)
    pair, evidence, _, _ = _batch(
        _candidate(adjacent_a, adjacent_b), _context((adjacent_a, adjacent_b))
    )
    assert evidence["local_context_penalty"] > 0.0
    assert "nearby_context" in str(pair["eligibility_reason"])


def test_more_than_five_verses_apart_is_not_nearby_even_for_long_passages() -> None:
    passages = tuple(
        _passage(
            f"P_{index}",
            ("common",) if index in {1, 7} else (f"other-{index}",),
            surfaces=(f"surface-{index}",),
            start=index,
            token_count=100,
        )
        for index in range(1, 8)
    )
    first, last = passages[0], passages[-1]
    pair, evidence, _, _ = _batch(_candidate(first, last), _context(passages))

    assert evidence["local_context_penalty"] == 0.0
    assert "nearby_context" not in str(pair["eligibility_reason"])
    assert pair["review_eligible"]


def test_reverse_openbible_facts_reconcile_without_directional_leakage() -> None:
    first = _passage("P_A", ("common",), surfaces=("surface-a",), start=1)
    second = _passage("P_B", ("common",), surfaces=("surface-b",), start=10)
    candidate = _candidate(first, second)
    known = {
        ("P_B", "P_A"): KnownPair(("R2",), 4, "mapped_provisional"),
        ("P_A", "P_B"): KnownPair(("R1",), 7, "mapped_verified"),
    }
    pair, _, _, _ = _batch(candidate, _context((first, second), known_pairs=known))

    assert pair["known_link_status"] == "represented_in_openbible_snapshot"
    assert json.loads(str(pair["openbible_relationship_ids_json"])) == ["R1", "R2"]
    assert pair["highest_openbible_vote"] == 7
    assert pair["mapping_quality"] == "mapped_provisional"
    assert not pair["review_eligible"]


def test_bh_correction_uses_the_registered_corpus_pair_representation_family() -> None:
    verse_a = _passage("P_A", ("x",), surfaces=("va",))
    verse_b = _passage("P_B", ("x",), surfaces=("vb",), start=10)
    window_a = _passage("P_C", ("y",), surfaces=("wa",), granularity="two_verse", start=20)
    window_b = _passage("P_D", ("z",), surfaces=("wb",), granularity="two_verse", start=30)
    passages = (verse_a, verse_b, window_a, window_b)
    candidates = {
        candidate.candidate_pair_id: candidate
        for candidate in (
            _candidate(verse_a, verse_b),
            _candidate(window_a, window_b),
        )
    }
    context = _context(passages)
    adjusted = candidate_q_values(candidates, context)
    raw_verse = hypergeometric_upper_tail(3, 1, 1, 1).upper_tail_p_value

    assert adjusted[_candidate(verse_a, verse_b).candidate_pair_id] == pytest.approx(
        2.0 * raw_verse
    )
    assert adjusted[_candidate(window_a, window_b).candidate_pair_id] == pytest.approx(1.0)


def test_review_queue_is_order_invariant_and_rejects_duplicates() -> None:
    base = {
        "passage_a_reference": "GEN.1.1",
        "passage_b_reference": "GEN.1.2",
        "corpus_pair": "hb_hb",
        "detector_support_count": 2,
        "rare_rule_passed": True,
        "estimated_empirical_fdr": 0.1,
        "known_link_status": "not_represented_in_openbible_snapshot",
        "contains_english_derived_evidence": False,
        "english_ablation_survives": True,
        "disputed_passage_flag": False,
        "reference_gap": False,
        "ketiv_structural_uncertainty": False,
        "review_eligible": True,
    }
    rows = [
        {**base, "candidate_pair_id": "C_B", "rrf_score": 0.5},
        {**base, "candidate_pair_id": "C_A", "rrf_score": 0.5},
        {**base, "candidate_pair_id": "C_C", "rrf_score": 0.4},
    ]

    forward = build_review_queue(rows)
    reverse = build_review_queue(reversed(rows))
    assert forward.equals(reverse)
    assert forward.get_column("candidate_pair_id").to_list() == ["C_A", "C_B", "C_C"]
    assert forward.get_column("queue_rank").to_list() == [1, 2, 3]
    with pytest.raises(CandidateMaterializationError, match="duplicate"):
        build_review_queue((rows[0], rows[0]))


def test_direction_metadata_must_reconcile_to_canonical_pair() -> None:
    first = _passage("P_A", ("common",), surfaces=("surface-a",))
    second = _passage("P_B", ("common",), surfaces=("surface-b",), start=10)
    candidate = _candidate(first, second)
    original = candidate.directions["a_to_b"]
    candidate.directions["a_to_b"] = CandidateDirection(
        direction=cast(Literal["a_to_b", "b_to_a"], "a_to_b"),
        query_passage_id="P_B",
        target_passage_id="P_A",
        scores=original.scores,
        ranks=original.ranks,
        rrf_score=original.rrf_score,
    )

    with pytest.raises(CandidateMaterializationError, match="does not reconcile"):
        candidate_q_values({candidate.candidate_pair_id: candidate}, _context((first, second)))
