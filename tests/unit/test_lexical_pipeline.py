"""Scoped pipeline, sensitivity, smoke-interface, and resource-control tests."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from echoes.lexical.candidates import build_review_queue
from echoes.lexical.models import CANDIDATE_REVIEW_QUEUE_SCHEMA, DIRECTIONAL_RANKINGS_SCHEMA
from echoes.lexical.pipeline import (
    _iter_ranked_review_queue_frames,
    _iter_sensitivity_result_frames,
    _load_split_provenance,
    _sha256_json,
)
from echoes.lexical.resources import (
    MEBIBYTE,
    LexicalResourceError,
    ProcessResourceGuard,
    configure_duckdb_connection,
    enforce_thread_controls,
    initialize_thread_controls,
)
from echoes.lexical.retrieval import iter_retrieval_batches
from echoes.lexical.sequences import FeatureOccurrence, PassageLexicalSequence
from echoes.lexical.sparse import build_sparse_index


def _occurrences(passage_id: str, values: tuple[str, ...]) -> tuple[FeatureOccurrence, ...]:
    return tuple(
        FeatureOccurrence(
            value=value,
            position_in_passage=index,
            token_id=f"{passage_id}-token-{index}",
            source_word_id=f"{passage_id}-word-{index}",
        )
        for index, value in enumerate(values, start=1)
    )


def _passage(
    passage_id: str,
    reference: str,
    lemmas: tuple[str, ...],
    *,
    corpus: str = "hebrew",
    profile: str = "edition_complete",
    reading: str | None = None,
    granularity: str = "verse",
) -> PassageLexicalSequence:
    occurrences = _occurrences(passage_id, lemmas)
    token_ids = tuple(item.token_id for item in occurrences)
    return PassageLexicalSequence(
        passage_id=passage_id,
        corpus=corpus,
        book="GEN" if corpus == "hebrew" else "MAT",
        book_order=1,
        analysis_profile=profile,
        analysis_reading=reading or ("qere" if corpus == "hebrew" else "source"),
        granularity=granularity,
        start_reference=reference,
        end_reference=reference,
        source_passage_digest="a" * 64,
        start_stream_position_in_corpus=int(passage_id[-1]),
        token_count=len(lemmas),
        disputed_passage_flag=False,
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        lemma=occurrences,
        root=(),
        surface=occurrences,
        folded_surface=occurrences,
        part_of_speech=_occurrences(passage_id, tuple("noun" for _ in lemmas)),
        morphology=_occurrences(passage_id, tuple("N" for _ in lemmas)),
        english_gloss=_occurrences(passage_id, lemmas),
        provenance_token_ids=token_ids,
        zero_width_token_ids=(),
        punctuation_token_ids=(),
        elided_token_ids=(),
    )


def _queue_row(candidate_id: str, score: float) -> dict[str, object]:
    return {
        "candidate_pair_id": candidate_id,
        "passage_a_reference": "GEN 1:1",
        "passage_b_reference": "GEN 1:2",
        "corpus_pair": "hb_hb",
        "raw_rrf_score": score,
        "rrf_score": score,
        "total_penalty_contribution": 0.0,
        "detector_support_count": 2,
        "rare_rule_passed": True,
        "estimated_empirical_fdr": 0.01,
        "known_link_status": "not_represented_in_openbible_snapshot",
        "contains_english_derived_evidence": False,
        "english_ablation_survives": True,
        "disputed_passage_flag": False,
        "reference_gap": False,
        "ketiv_structural_uncertainty": False,
        "review_eligible": True,
    }


def test_disk_spooled_review_queue_is_globally_ranked_in_bounded_batches(
    tmp_path: Path,
) -> None:
    spool = tmp_path / "queue-spool"
    spool.mkdir()
    build_review_queue((_queue_row("candidate-b", 0.2),)).drop("queue_rank").write_parquet(
        spool / "part-00000.parquet"
    )
    build_review_queue((_queue_row("candidate-c", 0.5), _queue_row("candidate-a", 0.5))).drop(
        "queue_rank"
    ).write_parquet(spool / "part-00001.parquet")
    reservations: list[tuple[str, int]] = []

    def resource_check(stage: str, *, estimated_additional_bytes: int = 0) -> None:
        reservations.append((stage, estimated_additional_bytes))

    frames = list(
        _iter_ranked_review_queue_frames(
            spool,
            expected_count=3,
            duckdb_memory_limit_bytes=128 * MEBIBYTE,
            duckdb_temp_directory=tmp_path / "queue-sort-spill",
            resource_check=resource_check,
        )
    )
    queue = pl.concat(frames)

    assert queue.schema == CANDIDATE_REVIEW_QUEUE_SCHEMA
    assert queue.get_column("queue_rank").to_list() == [1, 2, 3]
    assert queue.get_column("candidate_pair_id").to_list() == [
        "candidate-a",
        "candidate-c",
        "candidate-b",
    ]
    assert reservations[0][0] == "candidate_review_queue:sort:before"
    assert all(estimate > 0 for _, estimate in reservations)


@pytest.mark.parametrize("granularity", ["clause", "sentence", "two_verse", "five_verse"])
def test_nonprimary_granularity_interfaces_run_bounded_sparse_smoke(
    granularity: str,
) -> None:
    sequences = [
        _passage("p1", "GEN 1:1", ("shared", "alpha"), granularity=granularity),
        _passage("p2", "GEN 1:2", ("shared", "beta"), granularity=granularity),
        _passage("p3", "GEN 1:3", ("other", "gamma"), granularity=granularity),
    ]
    index = build_sparse_index(
        sequences,
        representation_id=f"smoke-{granularity}",
        family="lemma",
        namespace="hb",
    )
    reservations: list[tuple[str, int]] = []

    def resource_check(stage: str, *, estimated_additional_bytes: int = 0) -> None:
        reservations.append((stage, estimated_additional_bytes))

    batches = list(
        iter_retrieval_batches(
            index,
            sequences,
            experiment_run_id="smoke-run",
            configuration_hash="a" * 64,
            experiment_scope=f"bounded_{granularity}_smoke",
            corpus_pair="hb_hb",
            query_indices=(0, 1, 2),
            target_indices=(0, 1, 2),
            candidate_union_k=2,
            persisted_top_k=2,
            persisted_candidate_pool_k=1,
            expensive_sequence_rerank_k=1,
            block_size=2,
            maximum_proposal_document_frequency=3,
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
            materialization_target_bytes=1,
            resource_check=resource_check,
        )
    )

    assert len(batches) >= 2
    assert any("materialize" in stage for stage, _ in reservations)
    assert all(estimated > 0 for _, estimated in reservations)
    rankings = pl.concat([batch.rankings for batch in batches])
    assert rankings.height > 0
    assert set(rankings.get_column("granularity")) == {granularity}
    assert set(rankings.get_column("experiment_scope")) == {f"bounded_{granularity}_smoke"}


def _ranking_row(
    *,
    ranking_id: str,
    query_id: str,
    target_id: str,
    scope: str,
    profile: str,
    representation_id: str,
    score: float,
) -> dict[str, object]:
    no_assignment = json.dumps(
        {"status": "no_eligible_benchmark_assignment"},
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "ranking_id": ranking_id,
        "experiment_run_id": "run",
        "query_passage_id": query_id,
        "target_passage_id": target_id,
        "corpus_pair": "gnt_gnt",
        "experiment_scope": scope,
        "analysis_profile": profile,
        "query_reading": "source",
        "target_reading": "source",
        "granularity": "verse",
        "representation_id": representation_id,
        "detector": "jaccard",
        "rank": 1,
        "raw_score": score,
        "quantized_score": score,
        "query_split": no_assignment,
        "target_split": no_assignment,
        "mapping_scope": "tier3_weak_supervision_recovery",
        "is_self": False,
        "passage_overlap": False,
        "nearby_context": False,
        "same_book": True,
        "contains_english_derived_evidence": False,
        "query_gloss_feature_count": 2,
        "target_gloss_feature_count": 2,
        "query_gloss_coverage": 1.0,
        "target_gloss_coverage": 1.0,
        "gloss_overlap_count": 1,
        "score_after_removing_all_english_features": score,
        "rank_after_removing_all_english_features": 1,
        "non_english_evidence_remains": True,
        "english_ablation_survives": True,
        "classification_after_english_ablation": "original_language_ranking_unchanged",
        "tie_break_key": target_id,
    }


def test_sensitivity_results_pair_profile_rankings_by_stable_reference(
    tmp_path: Path,
) -> None:
    ranking_root = tmp_path / "rankings"
    ranking_root.mkdir()
    rankings = pl.DataFrame(
        [
            _ranking_row(
                ranking_id="baseline",
                query_id="b1",
                target_id="b2",
                scope="primary",
                profile="edition_complete",
                representation_id="baseline-representation",
                score=0.8,
            ),
            _ranking_row(
                ranking_id="comparison",
                query_id="c1",
                target_id="c2",
                scope="critical_core_greek_sensitivity",
                profile="critical_core",
                representation_id="comparison-representation",
                score=0.6,
            ),
        ],
        schema=DIRECTIONAL_RANKINGS_SCHEMA,
        orient="row",
    )
    rankings.write_parquet(ranking_root / "part-00000.parquet")
    baseline = [
        _passage("b1", "MAT 1:1", ("shared", "alpha"), corpus="greek"),
        _passage("b2", "MAT 1:2", ("shared", "beta"), corpus="greek"),
    ]
    comparison = [
        _passage(
            "c1",
            "MAT 1:1",
            ("shared", "alpha"),
            corpus="greek",
            profile="critical_core",
        ),
        _passage(
            "c2",
            "MAT 1:2",
            ("shared", "changed"),
            corpus="greek",
            profile="critical_core",
        ),
    ]

    frames = list(
        _iter_sensitivity_result_frames(
            ranking_root=ranking_root,
            baseline_scope="primary",
            comparison_scope="critical_core_greek_sensitivity",
            sensitivity_type="critical_core_profile",
            corpus_pairs=("gnt_gnt",),
            baseline_profile="edition_complete",
            comparison_profile="critical_core",
            baseline_reading="qere+source",
            comparison_reading="qere+source",
            baseline_sequences=baseline,
            comparison_sequences=comparison,
            baseline_representation_ids={"gnt_gnt": "baseline-representation"},
            comparison_representation_ids={"gnt_gnt": "comparison-representation"},
            affected_references={},
            experiment_run_id="run",
            configuration_hash="a" * 64,
            preregistration_hash="b" * 64,
            resource_guard=ProcessResourceGuard(16 * 1024**3),
            spill_directory=tmp_path / "spill",
        )
    )

    result = pl.concat(frames)
    assert result.height == 1
    row = result.row(0, named=True)
    assert row["query_reference"] == "MAT 1:1"
    assert row["target_reference"] == "MAT 1:2"
    assert row["score_delta"] == pytest.approx(-0.2)
    assert row["rank_delta"] == 0
    assert row["top_k_overlap"] == 1.0
    assert row["baseline_reading"] == "source"
    assert row["comparison_reading"] == "source"
    assert row["baseline_sequence_digest"] != row["comparison_sequence_digest"]


def test_split_provenance_uses_real_assignments_and_leakage_status(tmp_path: Path) -> None:
    database = tmp_path / "benchmark.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE benchmark_endpoint_mappings(endpoint_id VARCHAR, "
            "target_granularity VARCHAR, target_passage_ids_json VARCHAR, "
            "mapping_status VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE benchmark_endpoints(endpoint_id VARCHAR, relationship_id VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE benchmark_relationships(relationship_id VARCHAR, tier INTEGER)"
        )
        connection.execute(
            "CREATE TABLE benchmark_split_assignments(relationship_id VARCHAR, "
            "benchmark_version VARCHAR, split_strategy VARCHAR, partition VARCHAR, "
            "eligibility_status VARCHAR, exclusion_reason VARCHAR, leakage_group_id VARCHAR)"
        )
        connection.execute("INSERT INTO benchmark_relationships VALUES ('r1',3)")
        connection.execute("INSERT INTO benchmark_endpoints VALUES ('e1','r1')")
        connection.execute(
            "INSERT INTO benchmark_endpoint_mappings VALUES "
            "('e1','verse','[\"p1\"]','mapped_verified')"
        )
        connection.execute(
            "INSERT INTO benchmark_split_assignments VALUES "
            "('r1','v1','held_out_book','test','eligible',NULL,'group-1')"
        )
    sequence = _passage("p1", "GEN 1:1", ("lemma",))

    loaded = _load_split_provenance(
        database,
        [sequence],
        duckdb_memory_limit_bytes=128 * 1024**2,
        duckdb_temp_directory=tmp_path / "duckdb-spill",
    )

    payload = json.loads(loaded["p1"])
    assert payload["status"] == "eligible_benchmark_assignment_present"
    assert payload["eligible_partitions"] == {"held_out_book": ["test"]}
    assert payload["leakage_membership_complete"] is True
    assert payload["leakage_group_count"] == 1
    assert payload["leakage_group_ids_digest"] == _sha256_json(["group-1"])
    assert "leakage_group_ids" not in payload
    assert len(payload["assignment_digest"]) == 64


def test_split_provenance_digest_is_independent_of_grouped_row_order(tmp_path: Path) -> None:
    def build_database(path: Path, rows: list[tuple[str, str]]) -> None:
        with duckdb.connect(str(path)) as connection:
            connection.execute(
                "CREATE TABLE benchmark_endpoint_mappings(endpoint_id VARCHAR, "
                "target_granularity VARCHAR, target_passage_ids_json VARCHAR, "
                "mapping_status VARCHAR)"
            )
            connection.execute(
                "CREATE TABLE benchmark_endpoints(endpoint_id VARCHAR, relationship_id VARCHAR)"
            )
            connection.execute(
                "CREATE TABLE benchmark_relationships(relationship_id VARCHAR, tier INTEGER)"
            )
            connection.execute(
                "CREATE TABLE benchmark_split_assignments(relationship_id VARCHAR, "
                "benchmark_version VARCHAR, split_strategy VARCHAR, partition VARCHAR, "
                "eligibility_status VARCHAR, exclusion_reason VARCHAR, "
                "leakage_group_id VARCHAR)"
            )
            for relationship_id, benchmark_version in rows:
                endpoint_id = f"endpoint-{relationship_id}"
                connection.execute(
                    "INSERT INTO benchmark_relationships VALUES (?,3)", [relationship_id]
                )
                connection.execute(
                    "INSERT INTO benchmark_endpoints VALUES (?,?)",
                    [endpoint_id, relationship_id],
                )
                connection.execute(
                    "INSERT INTO benchmark_endpoint_mappings VALUES "
                    "(?,'verse','[\"p1\"]','mapped_verified')",
                    [endpoint_id],
                )
                for group_id in (
                    f"group-{relationship_id}-b",
                    f"group-{relationship_id}-a",
                    f"group-{relationship_id}-a",
                ):
                    connection.execute(
                        "INSERT INTO benchmark_split_assignments VALUES "
                        "(?,?,'held_out_book','test','eligible',NULL,?)",
                        [relationship_id, benchmark_version, group_id],
                    )

    forward = tmp_path / "forward.duckdb"
    reverse = tmp_path / "reverse.duckdb"
    build_database(forward, [("r1", "v1"), ("r2", "v2")])
    build_database(reverse, [("r2", "v2"), ("r1", "v1")])
    sequence = _passage("p1", "GEN 1:1", ("lemma",))

    def load(path: Path, spill_name: str) -> str:
        return _load_split_provenance(
            path,
            [sequence],
            duckdb_memory_limit_bytes=128 * 1024**2,
            duckdb_temp_directory=tmp_path / spill_name,
        )["p1"]

    forward_payload = load(forward, "forward-spill")
    assert forward_payload == load(reverse, "reverse-spill")
    parsed = json.loads(forward_payload)
    expected_groups = ["group-r1-a", "group-r1-b", "group-r2-a", "group-r2-b"]
    assert parsed["leakage_group_count"] == len(expected_groups)
    assert parsed["leakage_group_ids_digest"] == _sha256_json(expected_groups)


def test_resource_guard_enforces_current_rss_and_thread_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoes.lexical import resources

    monkeypatch.setattr(resources, "process_rss_bytes", lambda: 101)
    guard = ProcessResourceGuard(100)
    with pytest.raises(LexicalResourceError, match="memory ceiling exceeded"):
        guard.check("fixture")

    for name in resources.THREAD_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    defaults = initialize_thread_controls(2)
    assert set(defaults.values()) == {"2"}
    enforced = enforce_thread_controls(1)
    assert set(enforced.values()) == {"1"}


def test_resource_guard_budgets_and_configures_bounded_duckdb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoes.lexical import resources

    monkeypatch.setattr(resources, "process_rss_bytes", lambda: 128 * MEBIBYTE)
    guard = ProcessResourceGuard(1024 * MEBIBYTE)
    budget = guard.bounded_duckdb_memory_bytes(
        "fixture:duckdb-budget",
        preferred_bytes=512 * MEBIBYTE,
        reserve_for_python_bytes=256 * MEBIBYTE,
    )
    assert budget == 512 * MEBIBYTE

    spill = tmp_path / "duckdb-spill"
    with duckdb.connect() as connection:
        observed = configure_duckdb_connection(
            connection,
            memory_limit_bytes=budget,
            temp_directory=spill,
        )
        assert observed["threads"] == 1
        assert observed["memory_limit"] == "512.0 MiB"
        assert observed["memory_limit_bytes"] == budget
        assert observed["preserve_insertion_order"] is False
        assert Path(str(observed["temp_directory"])) == spill.resolve()
        assert connection.execute("SELECT current_setting('threads')").fetchone() == (1,)
        assert connection.execute("SELECT current_setting('memory_limit')").fetchone() == (
            "512.0 MiB",
        )
        assert connection.execute(
            "SELECT current_setting('preserve_insertion_order')"
        ).fetchone() == (False,)
