from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pytest

from echoes.lexical import experiment as lexical_experiment
from echoes.lexical.config import lexical_config_sha256, load_lexical_config
from echoes.lexical.detectors import bm25_score, tfidf_cosine_similarity
from echoes.lexical.evaluation import GOVERNED_VOTE_STRATA, REQUIRED_STRATUM_DIMENSIONS
from echoes.lexical.experiment import (
    COMPOSITE_DETECTOR,
    PRESUMED_NEGATIVE_BASELINE,
    LexicalExperimentError,
    Tier3EvaluationScope,
    _evaluation_groups,
    _IndexedQueryView,
    _load_presumed_negative_pairs,
    _load_tier3_queries,
    _observed_sample_scores,
    run_null_calibration_experiment,
    run_tier3_evaluation_experiment,
)
from echoes.lexical.models import (
    EVALUATION_RESULTS_SCHEMA,
    NULL_REPLICATE_SUMMARIES_SCHEMA,
    THRESHOLD_CALIBRATION_SCHEMA,
)
from echoes.lexical.retrieval import CandidateAggregate, CandidateDirection
from echoes.lexical.sequences import FeatureOccurrence, PassageLexicalSequence

PREREGISTRATION_HASH = "7195f16bc9a0939a41d9fc4509af5c62c3511179a368a3bbddbb4d40d7e2ee93"


class _ResourceRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def __call__(
        self,
        stage: str,
        *,
        estimated_additional_bytes: int = 0,
    ) -> None:
        self.calls.append((stage, estimated_additional_bytes))


def _occurrences(
    passage_id: str,
    family: str,
    values: tuple[str, ...],
) -> tuple[FeatureOccurrence, ...]:
    return tuple(
        FeatureOccurrence(
            value=value,
            position_in_passage=index,
            token_id=f"{passage_id}-{family}-{index}",
            source_word_id=None,
        )
        for index, value in enumerate(values, start=1)
    )


def _sequence(
    passage_id: str,
    values: tuple[str, ...],
    *,
    book: str = "GEN",
    analysis_profile: str = "edition_complete",
) -> PassageLexicalSequence:
    positions = tuple(range(1, len(values) + 1))
    token_ids = tuple(f"{passage_id}-token-{position}" for position in positions)
    return PassageLexicalSequence(
        passage_id=passage_id,
        corpus="hebrew",
        book=book,
        book_order=1,
        analysis_profile=analysis_profile,
        analysis_reading="qere",
        granularity="verse",
        start_reference=f"{book}.1.{passage_id.removeprefix('p')}",
        end_reference=f"{book}.1.{passage_id.removeprefix('p')}",
        source_passage_digest="a" * 64,
        start_stream_position_in_corpus=int(passage_id.removeprefix("p")),
        token_count=len(values),
        disputed_passage_flag=False,
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        lemma=_occurrences(passage_id, "lemma", values),
        root=(),
        surface=_occurrences(passage_id, "surface", values),
        folded_surface=_occurrences(passage_id, "folded", values),
        part_of_speech=_occurrences(
            passage_id,
            "pos",
            tuple(f"pos-{value}" for value in values),
        ),
        morphology=_occurrences(
            passage_id,
            "morphology",
            tuple(f"morph-{value}" for value in values),
        ),
        english_gloss=_occurrences(
            passage_id,
            "gloss",
            tuple(f"gloss-{value}" for value in values),
        ),
        provenance_token_ids=token_ids,
        zero_width_token_ids=(),
        punctuation_token_ids=(),
        elided_token_ids=(),
    )


def _candidate(
    index: int,
    *,
    query: str = "p1",
    target: str = "p2",
    score: float = 0.0,
) -> CandidateAggregate:
    candidate = CandidateAggregate(
        candidate_pair_id=f"CP_{index:05d}",
        canonical_unordered_pair_id=f"CP_{index:05d}",
        passage_a_id=min(query, target),
        passage_b_id=max(query, target),
        corpus_pair="hb_hb",
        analysis_profile="edition_complete",
        granularity="verse",
    )
    candidate.add_direction(
        CandidateDirection(
            direction="a_to_b" if query < target else "b_to_a",
            query_passage_id=query,
            target_passage_id=target,
            scores={
                detector: score
                for detector in (
                    "jaccard",
                    "weighted_jaccard",
                    "tfidf_cosine",
                    "bm25",
                    "rare_lemma_root",
                    "phrase_association",
                    "longest_common_subsequence",
                    "weighted_sequence_alignment",
                    "pos_morphology_support",
                )
            },
            ranks={},
            rrf_score=99.0,
        )
    )
    return candidate


def test_observed_composite_is_recomputed_inside_the_fixed_sample() -> None:
    config = load_lexical_config()
    candidates = (_candidate(1, score=0.9), _candidate(2, target="p3", score=0.8))

    scores = _observed_sample_scores(candidates, config)

    assert np.all(scores[COMPOSITE_DETECTOR] < 1.0)
    assert not np.any(scores[COMPOSITE_DETECTOR] == 99.0)
    assert scores[COMPOSITE_DETECTOR][0] > scores[COMPOSITE_DETECTOR][1]


def test_compact_null_scorer_matches_explicit_tfidf_and_bm25(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_lexical_config()
    active = {
        "p1": ("a", "a", "b"),
        "p2": ("a", "c"),
        "p3": ("b", "c", "c"),
    }
    candidates = (_candidate(1), _candidate(2, target="p3"))
    monkeypatch.setattr(lexical_experiment, "CALIBRATION_PAIR_SAMPLE_SIZE", 2)

    scores = lexical_experiment._score_shared_null_replicate(
        candidates,
        active_features=active,
        pos_features={key: () for key in active},
        morphology_features={key: () for key in active},
        corpus_pair="hb_hb",
        config=config,
    )

    document_frequencies = Counter(feature for values in active.values() for feature in set(values))
    average_length = sum(map(len, active.values())) / len(active)
    expected_tfidf = tfidf_cosine_similarity(
        Counter(active["p1"]),
        Counter(active["p2"]),
        document_frequencies,
        len(active),
        sublinear_tf=True,
        smooth_idf=True,
    ).score
    expected_bm25 = max(
        bm25_score(
            Counter(active[query]),
            Counter(active[target]),
            document_frequencies,
            len(active),
            document_length=len(active[target]),
            average_document_length=average_length,
            k1=config.bm25.k1,
            b=config.bm25.b,
        ).score
        for query, target in (("p1", "p2"), ("p2", "p1"))
    )

    assert scores["tfidf_cosine"][0] == pytest.approx(expected_tfidf)
    assert scores["bm25"][0] == pytest.approx(expected_bm25)


def test_null_adapter_retains_shared_replicates_and_nullable_undefined_rates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_lexical_config()
    sequences = (
        _sequence("p1", ("a", "b", "c")),
        _sequence("p2", ("b", "c", "d")),
        _sequence("p3", ("c", "d", "a")),
        _sequence("p4", ("d", "a", "b")),
    )
    candidates = {
        candidate.candidate_pair_id: candidate
        for candidate in (_candidate(index) for index in range(20_000))
    }

    score_call_count = 0

    def score_stub(*args: object, **kwargs: object) -> dict[str, np.ndarray]:
        nonlocal score_call_count
        del args, kwargs
        score_call_count += 1
        scores = {
            detector: np.zeros(20_000, dtype=np.float64)
            for detector in (*config.enabled_detectors, COMPOSITE_DETECTOR)
        }
        if score_call_count == 1:
            scores[COMPOSITE_DETECTOR].fill(0.1)
        return scores

    monkeypatch.setattr(
        "echoes.lexical.experiment._score_shared_null_replicate",
        score_stub,
    )
    artifacts = run_null_calibration_experiment(
        candidates,
        sequences_by_corpus_pair={"hb_hb": sequences},
        representation_ids={"hb_hb": "hb-lemma-v1"},
        config=config,
        experiment_run_id="lexical-test-run",
        configuration_hash=lexical_config_sha256(config),
        preregistration_hash=PREREGISTRATION_HASH,
        book_genres={"GEN": "torah"},
        corpus_pairs=("hb_hb",),
    )

    nulls = artifacts.null_replicate_summaries
    calibration = artifacts.threshold_calibration
    assert nulls.schema == NULL_REPLICATE_SUMMARIES_SCHEMA
    assert calibration.schema == THRESHOLD_CALIBRATION_SCHEMA
    assert nulls.height == 2 * 100 * 10 * 5
    assert nulls["null_run_id"].n_unique() == 200
    assert nulls.group_by("null_run_id").len()["len"].unique().to_list() == [50]
    assert calibration.height == 10 * 5
    assert calibration["observed_to_null_enrichment"].null_count() == 50
    assert calibration["estimated_empirical_fdr"].null_count() == 45
    assert artifacts.selected_calibration[0][1].score_threshold == 0.02
    assert calibration["qualifies_empirical_fdr"].sum() == 5
    assert calibration["selected"].sum() == 1
    assert set(calibration["selection_reason"]) == {
        "detector_threshold_reported_not_review_selection",
        "lowest_registered_threshold_qualifying_both_null_families",
        "qualifies_but_not_lowest_selected_threshold",
    }
    assert artifacts.candidate_samples[0][1].pair_ids == tuple(
        sorted(artifacts.candidate_samples[0][1].pair_ids)
    )


def _write_benchmark_database(path: Path) -> None:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE benchmark_relationships AS
            SELECT 'BR_1'::VARCHAR relationship_id, 3::TINYINT tier,
                   'openbible-cross-references'::VARCHAR source_id,
                   4::BIGINT source_weight_sum, 4::BIGINT source_weight_max,
                   true::BOOLEAN weak_supervision_eligible
            """
        )
        connection.execute(
            """
            CREATE TABLE benchmark_endpoints AS
            SELECT * FROM (VALUES
              ('BE_a','BR_1','a','GEN'),
              ('BE_b','BR_1','b','GEN')
            ) t(endpoint_id,relationship_id,endpoint_side,parsed_book)
            """
        )
        connection.execute(
            """
            CREATE TABLE benchmark_endpoint_mappings AS
            SELECT * FROM (VALUES
              ('BE_a','hebrew','edition_complete','verse','["p1"]',
               'mapped_verified',false,false),
              ('BE_b','hebrew','edition_complete','verse','["p2"]',
               'mapped_verified',false,false),
              ('BE_a','hebrew','critical_core','verse','["p1"]',
               'mapped_verified',false,false),
              ('BE_b','hebrew','critical_core','verse','["p2"]',
               'mapped_verified',false,false)
            ) t(endpoint_id,target_corpus,target_analysis_profile,target_granularity,
                target_passage_ids_json,mapping_status,reference_gap,
                disputed_passage_flag)
            """
        )
        connection.execute(
            """
            CREATE TABLE benchmark_leakage_groups AS
            SELECT 'BLG_1'::VARCHAR leakage_group_id, 'BR_1'::VARCHAR relationship_id
            """
        )
        connection.execute(
            """
            CREATE TABLE benchmark_split_assignments AS
            SELECT row_number() OVER ()::VARCHAR split_assignment_id,
                   'benchmark-test-v1'::VARCHAR benchmark_version,
                   'BR_1'::VARCHAR relationship_id,
                   strategy::VARCHAR split_strategy,
                   partition_name::VARCHAR AS "partition",
                   'BLG_1'::VARCHAR leakage_group_id,
                   'eligible'::VARCHAR eligibility_status,
                   NULL::VARCHAR exclusion_reason
            FROM (VALUES
              ('held_out_book','test'),
              ('held_out_book_pair','train'),
              ('held_out_source_passage','test'),
              ('held_out_genre','test')
            ) t(strategy,partition_name)
            """
        )
        connection.execute(
            """
            CREATE TABLE benchmark_presumed_negative_pairs AS
            SELECT 'BC_1'::VARCHAR contrastive_id,
                   'benchmark-test-v1'::VARCHAR benchmark_version,
                   'p3'::VARCHAR passage_a_id, 'p4'::VARCHAR passage_b_id,
                   'hebrew|hebrew'::VARCHAR corpus_pair,
                   'length_matched_random_unlinked'::VARCHAR negative_strategy,
                   true::BOOLEAN presumed_negative,
                   true::BOOLEAN positive_graph_checked,
                   true::BOOLEAN reverse_pair_checked,
                   true::BOOLEAN passage_overlap_checked,
                   true::BOOLEAN leakage_checked,
                   0::BIGINT length_difference,
                   'GEN|GEN'::VARCHAR book_pair,
                   'torah|torah'::VARCHAR genre_pair,
                   'held_out_book'::VARCHAR split_strategy,
                   'test'::VARCHAR AS "partition",
                   6201::BIGINT seed,
                   repeat('a',64)::VARCHAR generation_config_hash,
                   'Presumed negative only; not a proven nonrelationship.'::VARCHAR notes
            """
        )
    finally:
        connection.close()


def _ranking_frame(
    config_detectors: tuple[str, ...],
    *,
    representation_id: str = "hb-lemma-v1",
    analysis_profile: str = "edition_complete",
    experiment_scope: str = "primary",
) -> pl.DataFrame:
    rows = []
    for query, target in (("p1", "p2"), ("p2", "p1")):
        for detector in (*config_detectors, COMPOSITE_DETECTOR):
            rows.append(
                {
                    "experiment_run_id": "lexical-test-run",
                    "query_passage_id": query,
                    "target_passage_id": target,
                    "corpus_pair": "hb_hb",
                    "representation_id": representation_id,
                    "analysis_profile": analysis_profile,
                    "experiment_scope": experiment_scope,
                    "detector": detector,
                    "rank": 1,
                    "quantized_score": 1.0,
                }
            )
    return pl.DataFrame(rows)


def test_benchmark_child_connections_apply_actual_governed_duckdb_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_lexical_config()
    database_path = tmp_path / "benchmark.duckdb"
    _write_benchmark_database(database_path)
    memory_limit = 128 * 1024**2
    temp_directory = tmp_path / "experiment-spill"
    observed: list[tuple[int, int, Path]] = []
    original = lexical_experiment.configure_duckdb_connection

    def recorded(
        connection: duckdb.DuckDBPyConnection,
        *,
        memory_limit_bytes: int,
        temp_directory: Path,
        thread_count: int = 1,
    ) -> dict[str, object]:
        result = original(
            connection,
            memory_limit_bytes=memory_limit_bytes,
            temp_directory=temp_directory,
            thread_count=thread_count,
        )
        observed.append(
            (memory_limit_bytes, int(result["threads"]), Path(result["temp_directory"]))
        )
        return result

    monkeypatch.setattr(lexical_experiment, "configure_duckdb_connection", recorded)
    _load_tier3_queries(
        database_path,
        analysis_profile="edition_complete",
        corpus_pairs=("hb_hb",),
        sequences_by_corpus_pair={"hb_hb": (_sequence("p1", ("a",)), _sequence("p2", ("a",)))},
        book_genres={"GEN": "torah"},
        config=config,
        duckdb_memory_limit_bytes=memory_limit,
        duckdb_temp_directory=temp_directory,
    )
    _load_presumed_negative_pairs(
        database_path,
        benchmark_version="benchmark-test-v1",
        analysis_profile="edition_complete",
        corpus_pairs=("hb_hb",),
        split_strategies=config.benchmark_evaluation.split_strategies,
        duckdb_memory_limit_bytes=memory_limit,
        duckdb_temp_directory=temp_directory,
    )

    assert len(observed) == 2
    assert all(item[0] == memory_limit and item[1] == 1 for item in observed)
    assert all(item[2] == temp_directory.resolve() for item in observed)


def test_streamed_high_duplication_queries_are_batch_invariant_and_groups_are_compact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_lexical_config()
    database_path = tmp_path / "benchmark.duckdb"
    _write_benchmark_database(database_path)
    source_ids = tuple(f"p{100 + index}" for index in range(64))
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            "UPDATE benchmark_endpoint_mappings SET target_passage_ids_json=? "
            "WHERE endpoint_id='BE_a' AND target_analysis_profile='edition_complete'",
            [json.dumps(source_ids, separators=(",", ":"))],
        )
    sequences = (
        *(_sequence(passage_id, ("shared",)) for passage_id in source_ids),
        _sequence("p2", ("shared",)),
    )
    common = {
        "analysis_profile": "edition_complete",
        "corpus_pairs": ("hb_hb",),
        "sequences_by_corpus_pair": {"hb_hb": sequences},
        "book_genres": {"GEN": "torah"},
        "config": config,
    }

    first_resources = _ResourceRecorder()
    monkeypatch.setattr("echoes.lexical.experiment.BENCHMARK_FETCH_BATCH_SIZE", 1)
    first = _load_tier3_queries(
        database_path,
        resource_check=first_resources,
        **common,  # type: ignore[arg-type]
    )
    second_resources = _ResourceRecorder()
    monkeypatch.setattr("echoes.lexical.experiment.BENCHMARK_FETCH_BATCH_SIZE", 128)
    second = _load_tier3_queries(
        database_path,
        resource_check=second_resources,
        **common,  # type: ignore[arg-type]
    )

    assert first == second
    benchmark_version, queries, source_passage_ids, excluded = first
    assert benchmark_version == "benchmark-test-v1"
    assert len(queries) == 4 * (len(source_ids) + 1)
    assert len(source_passage_ids) == len(queries)
    assert excluded == ()
    assert len({id(query.relationship_ids) for query in queries}) == 1
    forward_relevance = [
        query.relevant_passage_ids
        for query in queries
        if query.relevant_passage_ids == frozenset({"p2"})
    ]
    assert len(forward_relevance) == 4 * len(source_ids)
    assert len({id(values) for values in forward_relevance}) == 1

    for recorder in (first_resources, second_resources):
        stages = [stage for stage, _ in recorder.calls]
        assert any(":benchmark:reserve-batch-" in stage for stage in stages)
        assert any(":queries:reserve:" in stage for stage in stages)
        assert any(estimate > 0 for _, estimate in recorder.calls)
        first_reserve = next(
            index for index, stage in enumerate(stages) if ":benchmark:reserve-batch-" in stage
        )
        first_materialized = next(
            index for index, stage in enumerate(stages) if ":benchmark:batch-" in stage
        )
        assert first_reserve < first_materialized

    group_resources = _ResourceRecorder()
    groups = _evaluation_groups(
        queries,
        analysis_profile="edition_complete",
        corpus_pairs=("hb_hb",),
        split_strategies=config.benchmark_evaluation.split_strategies,
        mapping_statuses=config.benchmark_evaluation.eligible_mapping_statuses,
        excluded_facts=excluded,
        resource_check=group_resources,
    )
    indexed = [group for group in groups if group.queries]
    assert indexed
    assert all(isinstance(group.queries, _IndexedQueryView) for group in indexed)
    assert sum(len(group.queries) for group in indexed) == len(queries) * (
        1 + len(REQUIRED_STRATUM_DIMENSIONS)
    )
    assert all(
        group.queries.position_storage_bytes == len(group.queries) * 4
        for group in indexed
        if isinstance(group.queries, _IndexedQueryView)
    )
    assert any(
        ":groups:reserve:" in stage and estimate > 0 for stage, estimate in group_resources.calls
    )


def test_evaluation_adapter_uses_anchored_splits_same_universe_and_strict_gate(
    tmp_path: Path,
) -> None:
    config = load_lexical_config()
    sequences = (
        _sequence("p1", ("a", "b")),
        _sequence("p2", ("a", "c")),
    )
    database_path = tmp_path / "benchmark.duckdb"
    _write_benchmark_database(database_path)
    ranking_path = tmp_path / "directional-rankings.parquet"
    _ranking_frame(tuple(config.enabled_detectors)).write_parquet(ranking_path)

    artifacts = run_tier3_evaluation_experiment(
        ranking_path,
        sequences_by_corpus_pair={"hb_hb": sequences},
        representation_ids={"hb_hb": "hb-lemma-v1"},
        config=config,
        experiment_run_id="lexical-test-run",
        configuration_hash=lexical_config_sha256(config),
        preregistration_hash=PREREGISTRATION_HASH,
        benchmark_database_path=database_path,
        book_genres={"GEN": "torah"},
    )

    frame = artifacts.evaluation_results
    assert frame.schema == EVALUATION_RESULTS_SCHEMA
    assert artifacts.benchmark_version == "benchmark-test-v1"
    assert artifacts.scientific_gate_status == "insufficient_data"
    assert {detail.status for detail in artifacts.scientific_gate_details} == {
        "insufficient_data_no_claim",
        "missing",
    }
    assert set(config.benchmark_evaluation.split_strategies).issubset(set(frame["split_strategy"]))
    assert set(config.benchmark_evaluation.eligible_mapping_statuses).issubset(
        set(frame["mapping_status"])
    )
    assert set(GOVERNED_VOTE_STRATA).issubset(set(frame["vote_stratum"]))
    assert set(frame["detector"]) == {
        *config.enabled_detectors,
        COMPOSITE_DETECTOR,
        "random",
        "length_matched",
        "unweighted_overlap",
    }
    assert set(REQUIRED_STRATUM_DIMENSIONS).issubset(set(frame["stratum_dimension"]))
    assert set(frame["analysis_profile"]) == {"edition_complete"}
    assert set(frame["ranking_role"]) == {"system", "baseline"}
    assert set(frame["preregistration_hash"]) == {PREREGISTRATION_HASH}
    assert frame["frozen_before_test"].all()
    presumed_negative = frame.filter(
        (pl.col("comparison_baseline") == PRESUMED_NEGATIVE_BASELINE)
        & (pl.col("metric") == "presumed_negative_auroc")
    )
    assert presumed_negative.height == len(config.enabled_detectors) + 1
    assert presumed_negative["comparison_count"].unique().to_list() == [1]
    assert presumed_negative["value"].unique().to_list() == [1.0]
    assert presumed_negative["notes"].str.contains("not proven").all()
    assert {
        "recall_at_20_difference_vs_random",
        "recall_at_20_difference_vs_unweighted_overlap",
    }.issubset(set(frame["metric"]))
    gate_rows = frame.filter(
        (pl.col("split_strategy") == "held_out_genre")
        & (pl.col("partition") == "test")
        & (pl.col("mapping_status") == "all_eligible")
        & (pl.col("vote_stratum") == "all_votes")
        & (pl.col("metric") == "recall_at_20")
    )
    assert gate_rows.filter(pl.col("detector") == COMPOSITE_DETECTOR)["value"][0] == 1.0
    assert gate_rows.filter(pl.col("detector") == "random")["value"][0] == 1.0
    missing_test = frame.filter(
        (pl.col("split_strategy") == "held_out_book_pair")
        & (pl.col("partition") == "test")
        & (pl.col("mapping_status") == "all_eligible")
        & (pl.col("vote_stratum") == "all_votes")
        & (pl.col("detector") == COMPOSITE_DETECTOR)
        & (pl.col("metric") == "recall_at_20")
    )
    assert missing_test["eligible_query_count"].to_list() == [0]


def test_evaluation_adapter_persists_profile_keyed_sensitivity_scope(tmp_path: Path) -> None:
    config = load_lexical_config()
    database_path = tmp_path / "benchmark.duckdb"
    _write_benchmark_database(database_path)
    edition_sequences = (_sequence("p1", ("a", "b")), _sequence("p2", ("a", "c")))
    critical_sequences = (
        _sequence("p1", ("a", "b"), analysis_profile="critical_core"),
        _sequence("p2", ("a", "c"), analysis_profile="critical_core"),
    )
    edition_rankings = _ranking_frame(tuple(config.enabled_detectors))
    critical_rankings = _ranking_frame(
        tuple(config.enabled_detectors),
        representation_id="hb-critical-v1",
        analysis_profile="critical_core",
        experiment_scope="critical_core_greek_sensitivity",
    )

    artifacts = run_tier3_evaluation_experiment(
        edition_rankings,
        sequences_by_corpus_pair={"hb_hb": edition_sequences},
        representation_ids={"hb_hb": "hb-lemma-v1"},
        config=config,
        experiment_run_id="lexical-test-run",
        configuration_hash=lexical_config_sha256(config),
        preregistration_hash=PREREGISTRATION_HASH,
        benchmark_database_path=database_path,
        book_genres={"GEN": "torah"},
        additional_evaluation_scopes=(
            Tier3EvaluationScope(
                analysis_profile="critical_core",
                experiment_scope="critical_core_greek_sensitivity",
                directional_rankings=critical_rankings,
                sequences_by_corpus_pair={"hb_hb": critical_sequences},
                representation_ids={"hb_hb": "hb-critical-v1"},
            ),
        ),
    )

    frame = artifacts.evaluation_results
    assert set(frame["analysis_profile"]) == {"edition_complete", "critical_core"}
    assert set(
        frame.filter(pl.col("analysis_profile") == "critical_core")["representation_id"]
    ) == {"hb-critical-v1"}
    assert set(REQUIRED_STRATUM_DIMENSIONS).issubset(
        set(frame.filter(pl.col("analysis_profile") == "critical_core")["stratum_dimension"])
    )
    assert artifacts.scientific_gate_status == "insufficient_data"


def test_evaluation_rejects_nonempty_tier1(tmp_path: Path) -> None:
    config = load_lexical_config()
    database_path = tmp_path / "benchmark.duckdb"
    _write_benchmark_database(database_path)
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("UPDATE benchmark_relationships SET tier=1")
    finally:
        connection.close()

    with pytest.raises(LexicalExperimentError, match="Tier 1 must remain empty"):
        run_tier3_evaluation_experiment(
            _ranking_frame(tuple(config.enabled_detectors)),
            sequences_by_corpus_pair={"hb_hb": (_sequence("p1", ("a",)), _sequence("p2", ("b",)))},
            representation_ids={"hb_hb": "hb-lemma-v1"},
            config=config,
            experiment_run_id="lexical-test-run",
            configuration_hash=lexical_config_sha256(config),
            preregistration_hash=PREREGISTRATION_HASH,
            benchmark_database_path=database_path,
            book_genres={"GEN": "torah"},
        )
