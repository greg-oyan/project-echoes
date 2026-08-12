from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from echoes.corpus.storage import logical_frame_hash
from echoes.lexical.detectors import longest_common_subsequence, weighted_sequence_alignment
from echoes.lexical.features import (
    LexicalFeatureError,
    build_feature_vocabulary,
    build_passage_feature_statistics,
    combine_feature_vocabularies,
)
from echoes.lexical.models import ABLATION_RESULTS_SCHEMA, FEATURE_VOCABULARY_SCHEMA
from echoes.lexical.phrases import contiguous_ngrams, skip_grams
from echoes.lexical.retrieval import (
    LexicalRetrievalError,
    _bitset_lcs_length_from_masks,
    _extract_phrase_occurrences,
    _lcs_position_masks,
    _pair_score,
    _weighted_local_alignment_normalized_score,
    build_phrase_association_index,
    iter_retrieval_batches,
)
from echoes.lexical.sequences import FeatureOccurrence, PassageLexicalSequence
from echoes.lexical.sparse import (
    SparseIndexError,
    build_sparse_index,
    load_sparse_index,
    persist_sparse_index,
    prepare_sparse_retrieval,
    retrieve_prepared_bm25,
    retrieve_prepared_overlap,
    retrieve_prepared_rare,
    retrieve_prepared_tfidf,
    retrieve_top_bm25,
    retrieve_top_overlap,
    retrieve_top_rare,
    retrieve_top_tfidf,
)


def _occurrences(
    passage_id: str,
    family: str,
    values: tuple[str, ...],
    token_ids: tuple[str, ...],
) -> tuple[FeatureOccurrence, ...]:
    return tuple(
        FeatureOccurrence(
            value=value,
            position_in_passage=index,
            token_id=token_id,
            source_word_id=f"{passage_id}-word-{index}",
        )
        for index, (value, token_id) in enumerate(zip(values, token_ids, strict=True), start=1)
    )


def _passage(
    passage_id: str,
    lemmas: tuple[str, ...],
    *,
    corpus: str = "hebrew",
    book: str = "GEN",
    reading: str | None = None,
    granularity: str = "verse",
    token_ids: tuple[str, ...] | None = None,
    roots: tuple[str, ...] = (),
    glosses: tuple[str, ...] = (),
) -> PassageLexicalSequence:
    ids = token_ids or tuple(f"{passage_id}-token-{index}" for index in range(len(lemmas)))
    if len(ids) != len(lemmas):
        raise ValueError("test token IDs must match lemma length")
    root_ids = ids[: len(roots)]
    gloss_ids = ids[: len(glosses)]
    lemma_occurrences = _occurrences(passage_id, "lemma", lemmas, ids)
    return PassageLexicalSequence(
        passage_id=passage_id,
        corpus=corpus,
        book=book,
        book_order=1,
        analysis_profile="edition_complete",
        analysis_reading=reading or ("qere" if corpus == "hebrew" else "source"),
        granularity=granularity,
        start_reference=f"{book}.1.1",
        end_reference=f"{book}.1.1",
        source_passage_digest="a" * 64,
        start_stream_position_in_corpus=int(passage_id.removeprefix("p") or "0"),
        token_count=len(ids),
        disputed_passage_flag=False,
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        lemma=lemma_occurrences,
        root=_occurrences(passage_id, "root", roots, root_ids),
        surface=lemma_occurrences,
        folded_surface=lemma_occurrences,
        part_of_speech=_occurrences(
            passage_id,
            "part_of_speech",
            tuple("noun" for _ in ids),
            ids,
        ),
        morphology=_occurrences(
            passage_id,
            "morphology",
            tuple('{"number":"singular"}' for _ in ids),
            ids,
        ),
        english_gloss=_occurrences(passage_id, "english_gloss", glosses, gloss_ids),
        provenance_token_ids=ids,
        zero_width_token_ids=(),
        punctuation_token_ids=(),
        elided_token_ids=(),
    )


def _vocabulary(
    sequences: list[PassageLexicalSequence],
    *,
    family: str = "lemma",
    namespace: str = "hb",
    formulaic_minimum: int = 2,
) -> pl.DataFrame:
    return build_feature_vocabulary(
        sequences,
        family=family,  # type: ignore[arg-type]
        namespace=namespace,  # type: ignore[arg-type]
        rare_maximum_corpus_frequency=3,
        high_frequency_document_ratio=0.8,
        formulaic_document_ratio=0.9,
        formulaic_minimum_corpus_count=formulaic_minimum,
        book_genres={"GEN": "torah", "MAT": "gospel"},
    )


def test_feature_frequency_deduplicates_overlapping_source_tokens() -> None:
    first = _passage("p1", ("a\u0301",), token_ids=("shared-token",))
    second = _passage("p2", ("á",), token_ids=("shared-token",))

    vocabulary = _vocabulary([second, first])

    assert vocabulary.height == 1
    assert vocabulary["feature_value"][0] == "á"
    assert vocabulary["corpus_frequency"][0] == 1
    assert vocabulary["document_frequency"][0] == 2
    assert not vocabulary["is_formulaic"][0]
    assert logical_frame_hash(vocabulary, sort_by=["feature_id"]) == logical_frame_hash(
        _vocabulary([first, second]), sort_by=["feature_id"]
    )


def test_feature_namespaces_and_inconsistent_duplicates_fail_closed() -> None:
    passage = _passage("p1", ("lemma",))
    with pytest.raises(LexicalFeatureError, match="another corpus"):
        _vocabulary([passage], namespace="gk")
    with pytest.raises(LexicalFeatureError, match="English gloss"):
        _vocabulary([passage], family="english_gloss", namespace="hb")

    vocabulary = _vocabulary([passage])
    inconsistent = vocabulary.with_columns(pl.lit(99).alias("corpus_frequency"))
    with pytest.raises(LexicalFeatureError, match="inconsistent duplicate"):
        combine_feature_vocabularies([vocabulary, inconsistent])


def test_passage_statistics_count_all_original_eligibility_and_missing_roots() -> None:
    passage = _passage("p1", ("lemma",), glosses=("word",))
    lemma = _vocabulary([passage])
    gloss = _vocabulary([passage], family="english_gloss", namespace="en")

    statistics = build_passage_feature_statistics(
        [passage], combine_feature_vocabularies([lemma, gloss])
    )

    assert statistics["eligible_token_count"][0] == 1
    assert statistics["distinct_root_count"][0] == 0
    assert statistics["english_gloss_sequence_length"][0] == 1


def test_sparse_index_is_reorder_stable_and_root_unavailability_is_explicit() -> None:
    sequences = [_passage("p2", ("b", "a")), _passage("p1", ("a", "a"))]
    first = build_sparse_index(
        sequences,
        representation_id="lemma-representation",
        family="lemma",
        namespace="hb",
    )
    second = build_sparse_index(
        list(reversed(sequences)),
        representation_id="lemma-representation",
        family="lemma",
        namespace="hb",
    )

    assert first.logical_hash == second.logical_hash
    assert first.passage_ids == ("p1", "p2")
    assert first.vocabulary == ("hb:lemma:a", "hb:lemma:b")
    np.testing.assert_array_equal(first.counts.toarray(), second.counts.toarray())

    roots = build_sparse_index(
        sequences,
        representation_id="root-unavailable",
        family="root",
        namespace="hb",
    )
    assert roots.counts.shape == (2, 0)
    assert (
        retrieve_top_tfidf(
            roots,
            top_k=1,
            block_size=1,
            maximum_proposal_document_frequency=1,
            quantization_decimals=12,
            exclude_self=True,
        )
        == []
    )


def test_sparse_persistence_is_atomic_refusing_overwrite_and_round_trips(
    tmp_path: Path,
) -> None:
    index = build_sparse_index(
        [_passage("p2", ("b",)), _passage("p1", ("a",))],
        representation_id="lemma-representation",
        family="lemma",
        namespace="hb",
    )
    output = tmp_path / "index"
    first_files = persist_sparse_index(index, output).files
    with pytest.raises(SparseIndexError, match="refusing to overwrite"):
        persist_sparse_index(index, output)

    loaded = load_sparse_index(output)
    assert loaded.logical_hash == index.logical_hash
    np.testing.assert_array_equal(loaded.counts.toarray(), index.counts.toarray())
    np.testing.assert_allclose(loaded.tfidf.toarray(), index.tfidf.toarray())
    assert persist_sparse_index(index, output, force=True).files == first_files


def test_sparse_retrieval_quantizes_and_breaks_ties_by_passage_id() -> None:
    index = build_sparse_index(
        [_passage("p3", ("same",)), _passage("p1", ("same",)), _passage("p2", ("same",))],
        representation_id="tie-representation",
        family="lemma",
        namespace="hb",
    )

    hits = retrieve_top_tfidf(
        index,
        query_indices=[0],
        target_indices=[1, 2],
        top_k=2,
        block_size=1,
        maximum_proposal_document_frequency=3,
        quantization_decimals=12,
        exclude_self=True,
    )
    assert [index.passage_ids[hit.target_index] for hit in hits] == ["p2", "p3"]
    with pytest.raises(SparseIndexError, match="outside"):
        retrieve_top_tfidf(
            index,
            query_indices=[-1],
            top_k=1,
            block_size=1,
            maximum_proposal_document_frequency=3,
            quantization_decimals=12,
            exclude_self=True,
        )


def test_prepared_sparse_retrieval_is_exactly_equivalent_across_query_blocks() -> None:
    index = build_sparse_index(
        [
            _passage("p1", ("a", "a", "b", "rare-1")),
            _passage("p2", ("a", "b", "c", "rare-1")),
            _passage("p3", ("a", "c", "c", "rare-2")),
            _passage("p4", ("b", "c", "d", "rare-2")),
            _passage("p5", ("a", "d", "d", "rare-3")),
            _passage("p6", ("b", "d", "e", "rare-3")),
        ],
        representation_id="prepared-equivalence",
        family="lemma",
        namespace="hb",
    )
    targets = (5, 2, 4, 1, 3, 0)
    query_blocks = ((0, 1), (2, 3), (4, 5))
    common = {
        "top_k": 4,
        "block_size": 2,
        "quantization_decimals": 12,
        "exclude_self": True,
    }
    prepared = prepare_sparse_retrieval(
        index,
        target_indices=targets,
        maximum_proposal_document_frequency=5,
        maximum_corpus_frequency=3,
        k1=1.2,
        b=0.75,
    )

    for queries in query_blocks:
        assert retrieve_prepared_tfidf(prepared, query_indices=queries, **common) == (
            retrieve_top_tfidf(
                index,
                query_indices=queries,
                target_indices=targets,
                maximum_proposal_document_frequency=5,
                **common,
            )
        )
        assert retrieve_prepared_overlap(prepared, query_indices=queries, **common) == (
            retrieve_top_overlap(
                index,
                query_indices=queries,
                target_indices=targets,
                maximum_proposal_document_frequency=5,
                **common,
            )
        )
        assert retrieve_prepared_bm25(prepared, query_indices=queries, **common) == (
            retrieve_top_bm25(
                index,
                query_indices=queries,
                target_indices=targets,
                maximum_proposal_document_frequency=5,
                k1=1.2,
                b=0.75,
                **common,
            )
        )
        assert retrieve_prepared_rare(prepared, query_indices=queries, **common) == (
            retrieve_top_rare(
                index,
                query_indices=queries,
                target_indices=targets,
                maximum_corpus_frequency=3,
                **common,
            )
        )


def test_sparse_preparation_reserves_memory_before_allocating() -> None:
    index = build_sparse_index(
        [_passage("p1", ("a", "b")), _passage("p2", ("a", "c"))],
        representation_id="prepared-resource-gate",
        family="lemma",
        namespace="hb",
    )
    calls: list[tuple[str, int]] = []

    def reject(stage: str, *, estimated_additional_bytes: int = 0) -> None:
        calls.append((stage, estimated_additional_bytes))
        raise RuntimeError("governed memory rejection")

    with pytest.raises(RuntimeError, match="governed memory rejection"):
        prepare_sparse_retrieval(
            index,
            target_indices=(0, 1),
            maximum_proposal_document_frequency=2,
            maximum_corpus_frequency=2,
            k1=1.2,
            b=0.75,
            resource_check=reject,
            resource_stage="test:sparse-preparation",
        )

    assert calls == [("test:sparse-preparation", calls[0][1])]
    assert calls[0][1] >= 64 * 1024**2


def test_phrase_index_enforces_minimum_count_and_configured_pmi_cap() -> None:
    sequences = [
        _passage("p1", ("a", "b", "one-off")),
        _passage("p2", ("a", "b", "other")),
    ]
    phrases = build_phrase_association_index(
        sequences,
        sequence_family="lemma",
        ngram_sizes=(2, 3),
        minimum_corpus_count=2,
        pmi_cap=0.1,
        skipgram_max_gap=2,
        skipgram_minimum_corpus_count=2,
    )

    assert phrases.pmi[("a", "b")] <= 0.1
    assert ("b", "one-off") not in phrases.weights
    assert phrases.corpus_frequency[("a", "b")] == 2


@pytest.mark.parametrize(
    ("values", "maximum_gap"),
    [
        ((), 0),
        (("a",), 1),
        (("a", "b"), 2),
        (("a", "b", "a", "c"), 0),
        (("a", "b", "a", "c"), 1),
        (("a", "b", "a", "c"), 3),
    ],
)
def test_cached_phrase_extraction_is_exactly_equivalent_to_public_extractors(
    values: tuple[str, ...], maximum_gap: int
) -> None:
    contiguous, skipped, features = _extract_phrase_occurrences(
        values,
        ngram_sizes=(2, 3),
        skipgram_max_gap=maximum_gap,
    )
    expected_contiguous = [
        occurrence.features for size in (2, 3) for occurrence in contiguous_ngrams(values, size)
    ]
    expected_skipped = [
        occurrence.features for occurrence in skip_grams(values, 2, max_gap=maximum_gap)
    ]

    assert contiguous == expected_contiguous
    assert skipped == expected_skipped
    assert features.phrases == frozenset(expected_contiguous)
    assert features.skipgrams == frozenset(expected_skipped)


def test_cached_phrase_extraction_preserves_public_validation() -> None:
    with pytest.raises(ValueError, match="empty values"):
        _extract_phrase_occurrences(
            ("a", ""),
            ngram_sizes=(2,),
            skipgram_max_gap=1,
        )
    with pytest.raises(ValueError, match="n must be positive"):
        _extract_phrase_occurrences(
            ("a", "b"),
            ngram_sizes=(0,),
            skipgram_max_gap=1,
        )
    with pytest.raises(ValueError, match="max_gap cannot be negative"):
        _extract_phrase_occurrences(
            ("a", "b"),
            ngram_sizes=(2,),
            skipgram_max_gap=-1,
        )


@pytest.mark.parametrize(
    ("sequence_a", "sequence_b", "weights", "gap_penalty", "mismatch_score"),
    [
        (("a", "x", "b"), ("a", "b"), {"a": 2.0, "x": 1.0, "b": 3.0}, 0.5, -2.0),
        (("a", "b"), ("b", "a"), {"a": 1.0, "b": 1.0}, 1.0, 0.0),
        (("a", "a", "b"), ("a", "b", "b"), {"a": 1.25, "b": 2.5}, 0.75, -1.0),
        ((), (), {}, 1.0, -1.0),
    ],
)
def test_cached_lcs_and_score_only_alignment_match_traceback_detectors(
    sequence_a: tuple[str, ...],
    sequence_b: tuple[str, ...],
    weights: dict[str, float],
    gap_penalty: float,
    mismatch_score: float,
) -> None:
    expected_lcs = longest_common_subsequence(sequence_a, sequence_b)
    assert (
        _bitset_lcs_length_from_masks(sequence_a, _lcs_position_masks(sequence_b))
        == expected_lcs.length
    )

    expected_alignment = weighted_sequence_alignment(
        sequence_a,
        sequence_b,
        weights,
        gap_penalty=gap_penalty,
        mismatch_score=mismatch_score,
        mode="local",
    )
    assert (
        _weighted_local_alignment_normalized_score(
            sequence_a,
            sequence_b,
            weights,
            gap_penalty=gap_penalty,
            mismatch_score=mismatch_score,
        )
        == expected_alignment.normalized_score
    )


def test_single_rare_item_and_english_only_evidence_fail_rare_rule() -> None:
    query = _passage("p1", ("rare",))
    target = _passage("p2", ("rare",))
    phrases = build_phrase_association_index(
        [query, target],
        sequence_family="lemma",
        ngram_sizes=(2, 3),
        minimum_corpus_count=2,
        pmi_cap=10.0,
        skipgram_max_gap=2,
        skipgram_minimum_corpus_count=2,
    )
    scored = _pair_score(
        query,
        target,
        proposal_scores={},
        idf={"rare": 2.0},
        corpus_frequency={"rare": 2},
        rare_threshold=3,
        sequence_family="lemma",
        english_derived=False,
        phrase_associations=phrases,
        phrase_ngram_sizes=(2, 3),
        skipgram_max_gap=2,
    )
    assert not scored.rare_rule_passed
    assert scored.independent_co_signal_count == 0

    english = _pair_score(
        query,
        target,
        proposal_scores={},
        idf={"rare": 2.0},
        corpus_frequency={"rare": 2},
        rare_threshold=3,
        sequence_family="lemma",
        english_derived=True,
        phrase_associations=phrases,
        phrase_ngram_sizes=(2, 3),
        skipgram_max_gap=2,
    )
    assert not english.rare_rule_passed


def test_retrieval_preserves_direction_corpus_boundaries_overlap_and_frozen_depths() -> None:
    sequences = [
        _passage(
            "p1",
            ("a", "b"),
            granularity="two_verse",
            token_ids=("t1", "shared"),
        ),
        _passage(
            "p2",
            ("b", "c"),
            granularity="two_verse",
            token_ids=("shared", "t3"),
        ),
    ]
    index = build_sparse_index(
        sequences,
        representation_id="overlap-representation",
        family="lemma",
        namespace="hb",
    )

    batch = next(
        iter_retrieval_batches(
            index,
            sequences,
            experiment_run_id="run",
            configuration_hash="a" * 64,
            experiment_scope="primary",
            corpus_pair="hb_hb",
            query_indices=[0],
            target_indices=[1],
            candidate_union_k=1,
            persisted_top_k=1,
            persisted_candidate_pool_k=1,
            expensive_sequence_rerank_k=1,
            block_size=1,
            maximum_proposal_document_frequency=2,
            score_quantization_decimals=12,
            bm25_k1=1.2,
            bm25_b=0.75,
            rare_threshold=3,
            rrf_k=60,
            gap_penalty=-1.0,
            mismatch_score=-1.0,
            nearby_context_distance=5,
            phrase_ngram_sizes=(2, 3),
            phrase_minimum_corpus_count=2,
            phrase_pmi_cap=10.0,
            skipgram_max_gap=2,
            skipgram_minimum_corpus_count=2,
            split_provenance_by_passage_id={},
        )
    )
    assert batch.rankings.height > 0
    assert batch.rankings["passage_overlap"].all()
    assert batch.rankings["nearby_context"].all()
    assert batch.rankings["target_passage_id"].unique().to_list() == ["p2"]
    assert len(batch.candidates) == 1
    assert set(batch.candidates[0].directions) == {"a_to_b"}

    with pytest.raises(LexicalRetrievalError, match="requires namespace gk"):
        next(
            iter_retrieval_batches(
                index,
                sequences,
                experiment_run_id="run",
                configuration_hash="a" * 64,
                experiment_scope="primary",
                corpus_pair="gnt_gnt",
                query_indices=[0],
                target_indices=[1],
                candidate_union_k=1,
                persisted_top_k=1,
                persisted_candidate_pool_k=1,
                expensive_sequence_rerank_k=1,
                block_size=1,
                maximum_proposal_document_frequency=2,
                score_quantization_decimals=12,
                bm25_k1=1.2,
                bm25_b=0.75,
                rare_threshold=3,
                rrf_k=60,
                gap_penalty=-1.0,
                mismatch_score=-1.0,
                nearby_context_distance=5,
                phrase_ngram_sizes=(2, 3),
                phrase_minimum_corpus_count=2,
                phrase_pmi_cap=10.0,
                skipgram_max_gap=2,
                skipgram_minimum_corpus_count=2,
                split_provenance_by_passage_id={},
            )
        )


def test_cached_retrieval_preserves_frozen_ranking_and_candidate_hashes() -> None:
    vocabulary = (
        "shared",
        "covenant",
        "king",
        "house",
        "land",
        "word",
        "people",
        "day",
        "name",
        "god",
        "give",
        "hear",
        "see",
        "make",
        "go",
        "come",
    )
    sequences: list[PassageLexicalSequence] = []
    for passage_number in range(1, 81):
        lemmas = tuple(
            vocabulary[(passage_number + offset * (1 + passage_number % 3)) % len(vocabulary)]
            for offset in range(12)
        )
        glosses = tuple(
            "gloss-" + vocabulary[(passage_number * 3 + offset) % len(vocabulary)]
            for offset in range(12)
        )
        sequences.append(_passage(f"p{passage_number}", lemmas, glosses=glosses))
    index = build_sparse_index(
        sequences,
        representation_id="cache-regression",
        family="lemma",
        namespace="hb",
    )

    batches = list(
        iter_retrieval_batches(
            index,
            sequences,
            experiment_run_id="cache-run",
            configuration_hash="a" * 64,
            experiment_scope="primary",
            corpus_pair="hb_hb",
            query_indices=tuple(range(24)),
            target_indices=tuple(range(80)),
            candidate_union_k=20,
            persisted_top_k=15,
            persisted_candidate_pool_k=10,
            expensive_sequence_rerank_k=8,
            block_size=8,
            maximum_proposal_document_frequency=80,
            score_quantization_decimals=12,
            bm25_k1=1.2,
            bm25_b=0.75,
            rare_threshold=3,
            rrf_k=60,
            gap_penalty=-1.0,
            mismatch_score=-1.0,
            nearby_context_distance=5,
            phrase_ngram_sizes=(2, 3),
            phrase_minimum_corpus_count=2,
            phrase_pmi_cap=10.0,
            skipgram_max_gap=2,
            skipgram_minimum_corpus_count=2,
            split_provenance_by_passage_id={},
        )
    )
    rankings = pl.concat([batch.rankings for batch in batches])
    candidate_payload = json.dumps(
        [asdict(candidate) for batch in batches for candidate in batch.candidates],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert rankings.height == 2_969
    assert logical_frame_hash(rankings, sort_by=["ranking_id"]) == (
        "f5b5081895bcf7ea0268475dff4b5bd8438703127b13db33511771c2bbf6821b"
    )
    assert hashlib.sha256(candidate_payload).hexdigest() == (
        "3faa5c520f16bedcded1adfbd2f8b365da872ae53cf82c690c36501d82972967"
    )


def test_english_directional_ablation_is_inline_and_typed_empty() -> None:
    sequences = [
        _passage(
            "p1",
            ("hb-a", "hb-b"),
            corpus="hebrew",
            book="GEN",
            glosses=("shared", "covenant"),
        ),
        _passage(
            "p2",
            ("gk-a", "gk-b"),
            corpus="greek",
            book="MAT",
            glosses=("shared", "covenant"),
        ),
    ]
    index = build_sparse_index(
        sequences,
        representation_id="english-bridge-regression",
        family="english_gloss",
        namespace="en",
    )

    batch = next(
        iter_retrieval_batches(
            index,
            sequences,
            experiment_run_id="english-run",
            configuration_hash="a" * 64,
            experiment_scope="primary",
            corpus_pair="hb_gnt_english_bridge",
            query_indices=[0],
            target_indices=[1],
            candidate_union_k=1,
            persisted_top_k=1,
            persisted_candidate_pool_k=1,
            expensive_sequence_rerank_k=1,
            block_size=1,
            maximum_proposal_document_frequency=2,
            score_quantization_decimals=12,
            bm25_k1=1.2,
            bm25_b=0.75,
            rare_threshold=3,
            rrf_k=60,
            gap_penalty=-1.0,
            mismatch_score=-1.0,
            nearby_context_distance=5,
            phrase_ngram_sizes=(2, 3),
            phrase_minimum_corpus_count=2,
            phrase_pmi_cap=10.0,
            skipgram_max_gap=2,
            skipgram_minimum_corpus_count=2,
            split_provenance_by_passage_id={},
        )
    )

    assert batch.ablation_results.is_empty()
    assert batch.ablation_results.schema == ABLATION_RESULTS_SCHEMA
    assert batch.rankings.height == 9
    assert batch.rankings["contains_english_derived_evidence"].all()
    assert not batch.rankings["non_english_evidence_remains"].any()
    assert not batch.rankings["english_ablation_survives"].any()
    assert (batch.rankings["query_gloss_feature_count"] == 2).all()
    assert (batch.rankings["target_gloss_feature_count"] == 2).all()
    assert (batch.rankings["gloss_overlap_count"] == 2).all()
    assert (batch.rankings["score_after_removing_all_english_features"] == 0.0).all()
    assert batch.rankings["rank_after_removing_all_english_features"].is_null().all()
    assert batch.rankings["classification_after_english_ablation"].unique().to_list() == [
        "english_mediated_lead_without_non_english_score"
    ]
    assert logical_frame_hash(batch.rankings, sort_by=["ranking_id"]) == (
        "e1b524de19ef66e02dcd701553b54d24012ce491998820ac2dcb55fdaea7cb55"
    )
    candidate_payload = json.dumps(
        [asdict(candidate) for candidate in batch.candidates],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(candidate_payload).hexdigest() == (
        "a36a789eab0474a5f8755f5c2b40946594ff3c3489f431c6dc758136f37adc95"
    )


def test_schema_remains_typed_when_feature_vocabulary_is_empty() -> None:
    frame = pl.DataFrame(schema=FEATURE_VOCABULARY_SCHEMA)
    assert frame.schema == FEATURE_VOCABULARY_SCHEMA
