"""Scoped pipeline, sensitivity, smoke-interface, and resource-control tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import duckdb
import polars as pl
import pytest

import echoes.lexical.pipeline as lexical_pipeline
from echoes.lexical.candidates import build_review_queue
from echoes.lexical.models import CANDIDATE_REVIEW_QUEUE_SCHEMA, DIRECTIONAL_RANKINGS_SCHEMA
from echoes.lexical.pipeline import (
    LexicalPipelineError,
    _iter_ranked_review_queue_frames,
    _iter_sensitivity_result_frames,
    _load_split_provenance,
    _prepare_candidate_review_queue_spool,
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
from echoes.lexical.retrieval import (
    CandidateAggregate,
    CandidateDirection,
    iter_retrieval_batches,
)
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


def test_pipeline_wrapper_finalizes_execution_manifest_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []
    recorder = SimpleNamespace(
        finalize_success=lambda **kwargs: events.append(("success", kwargs)),
        finalize_failure=lambda error: events.append(("failure", error)),
    )
    monkeypatch.setattr(
        lexical_pipeline,
        "ExperimentExecutionRecorder",
        SimpleNamespace(
            begin=lambda **kwargs: (
                events.append(("begin", kwargs)),
                recorder,
            )[1]
        ),
    )
    expected = SimpleNamespace(
        acceptance_status="scientifically_complete",
        stage_runtime_seconds={"total": 1.25},
    )

    def implementation(**kwargs: object) -> object:
        events.append(("implementation", kwargs))
        return expected

    monkeypatch.setattr(
        lexical_pipeline,
        "_run_lexical_pipeline_impl",
        implementation,
    )

    observed = lexical_pipeline.run_lexical_pipeline()

    assert observed is expected
    assert [name for name, _ in events] == ["begin", "implementation", "success"]
    implementation_kwargs = cast(dict[str, object], events[1][1])
    assert implementation_kwargs["execution_recorder"] is recorder
    assert isinstance(
        implementation_kwargs["checkpoint_quarantine"],
        lexical_pipeline._PrivateCheckpointQuarantine,
    )
    success_kwargs = cast(dict[str, object], events[2][1])
    assert success_kwargs["stage_runtime_seconds"] == {"total": 1.25}
    assert success_kwargs["warnings"] == []


def test_pipeline_wrapper_preserves_failure_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[BaseException] = []
    recorder = SimpleNamespace(
        finalize_success=lambda **kwargs: None,
        finalize_failure=failures.append,
    )
    monkeypatch.setattr(
        lexical_pipeline,
        "ExperimentExecutionRecorder",
        SimpleNamespace(begin=lambda **kwargs: recorder),
    )

    def fail(**kwargs: object) -> object:
        raise RuntimeError("synthetic pipeline failure")

    monkeypatch.setattr(lexical_pipeline, "_run_lexical_pipeline_impl", fail)

    with pytest.raises(RuntimeError, match="synthetic pipeline failure"):
        lexical_pipeline.run_lexical_pipeline()

    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)


def test_pipeline_wrapper_exposes_preserved_fresh_staging_without_masking_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[BaseException] = []
    recorder = SimpleNamespace(
        finalize_success=lambda **kwargs: None,
        finalize_failure=failures.append,
    )
    monkeypatch.setattr(
        lexical_pipeline,
        "ExperimentExecutionRecorder",
        SimpleNamespace(begin=lambda **kwargs: recorder),
    )
    output = tmp_path / "lexical" / "schema-v1"
    staging = output.parent / ".schema-v1.writing-preserved"

    def fail(**kwargs: object) -> object:
        staging.mkdir(parents=True)
        guard = cast(
            lexical_pipeline._PrivateCheckpointQuarantine,
            kwargs["checkpoint_quarantine"],
        )
        guard.register_staging(staging)
        raise RuntimeError("synthetic preserved pipeline failure")

    monkeypatch.setattr(lexical_pipeline, "_run_lexical_pipeline_impl", fail)

    with pytest.raises(RuntimeError, match="synthetic preserved pipeline failure") as caught:
        lexical_pipeline.run_lexical_pipeline(output_dir=output)

    assert failures == [caught.value]
    assert any(str(staging.resolve()) in note for note in getattr(caught.value, "__notes__", ()))
    assert staging.is_dir()


def test_primary_candidate_checkpoint_round_trips_exact_direction_traces(
    tmp_path: Path,
) -> None:
    staging = tmp_path / ".schema-v1.writing-fixture"
    staging.mkdir()
    candidate = CandidateAggregate(
        candidate_pair_id="pair",
        canonical_unordered_pair_id="pair",
        passage_a_id="a",
        passage_b_id="b",
        corpus_pair="hb_hb",
        analysis_profile="edition_complete",
        granularity="verse",
    )
    candidate.add_direction(
        CandidateDirection(
            direction="a_to_b",
            query_passage_id="a",
            target_passage_id="b",
            scores={"jaccard": 0.5, "rrf_composite": 0.25},
            ranks={"jaccard": 1},
            rrf_score=0.25,
            proposal_detectors=("jaccard", "tfidf_cosine"),
            alignment_evaluated=True,
            score_trace_version="governed_v1",
        )
    )
    writer = lexical_pipeline._CandidateCheckpointWriter(
        staging,
        experiment_run_id="run",
        configuration_hash="a" * 64,
    )
    writer.write_updates((candidate,))
    writer.finalize()

    loaded = lexical_pipeline._load_candidate_checkpoint(
        staging,
        experiment_run_id="run",
        configuration_hash="a" * 64,
    )

    assert loaded is not None
    assert set(loaded) == {"pair"}
    direction = loaded["pair"].directions["a_to_b"]
    assert direction.scores == candidate.directions["a_to_b"].scores
    assert direction.ranks == {"jaccard": 1}
    assert direction.proposal_detectors == ("jaccard", "tfidf_cosine")
    assert direction.alignment_evaluated is True
    assert direction.score_trace_version == "governed_v1"


def test_missing_primary_checkpoint_manifest_preserves_nested_tier3_state(
    tmp_path: Path,
) -> None:
    staging = tmp_path / ".schema-v1.writing-fixture"
    checkpoint = staging / ".resume-primary-candidates"
    tier3 = checkpoint / "tier3-evaluation"
    tier3.mkdir(parents=True)
    retained = tier3 / "retained-checkpoint.json"
    retained.write_text('{"retained":true}\n', encoding="utf-8")
    incomplete_primary = checkpoint / "part-00000.parquet"
    incomplete_primary.write_bytes(b"incomplete primary checkpoint")

    loaded = lexical_pipeline._load_candidate_checkpoint(
        staging,
        experiment_run_id="run",
        configuration_hash="a" * 64,
    )

    assert loaded is None
    assert retained.is_file()
    lexical_pipeline._CandidateCheckpointWriter(
        staging,
        experiment_run_id="run",
        configuration_hash="a" * 64,
    )
    assert retained.is_file()
    assert not incomplete_primary.exists()


def test_tier3_checkpoint_lineage_is_bound_only_for_unchanged_reused_files(
    tmp_path: Path,
) -> None:
    staging = tmp_path / ".schema-v1.writing-fixture"
    tier3 = staging / ".resume-primary-candidates" / "tier3-evaluation"
    tier3.mkdir(parents=True)
    part = tier3 / "edition_complete-baseline-random-fixture.parquet"
    part.write_bytes(b"authenticated checkpoint fixture")
    part_hash = hashlib.sha256(part.read_bytes()).hexdigest()
    manifest_name = "edition_complete-baseline-random.json"
    (tier3 / manifest_name).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_run_id": "run",
                "configuration_hash": "a" * 64,
                "preregistration_hash": "b" * 64,
                "analysis_profile": "edition_complete",
                "part_kind": "baseline",
                "detector": "random",
                "path": part.name,
                "row_count": 1,
                "sha256": part_hash,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    before_manifests, before_parts = lexical_pipeline._validated_existing_tier3_checkpoint_hashes(
        staging,
        expected_manifest_names=(manifest_name,),
        experiment_run_id="run",
        configuration_hash="a" * 64,
        preregistration_hash="b" * 64,
    )

    after_manifests, after_parts = lexical_pipeline._validated_existing_tier3_checkpoint_hashes(
        staging,
        expected_manifest_names=(manifest_name,),
        experiment_run_id="run",
        configuration_hash="a" * 64,
        preregistration_hash="b" * 64,
    )
    confirmed_manifests, confirmed_parts = lexical_pipeline._confirmed_tier3_checkpoint_reuse(
        before_manifests=before_manifests,
        before_parts=before_parts,
        after_manifests=after_manifests,
        after_parts=after_parts,
    )

    assert confirmed_manifests == before_manifests
    assert confirmed_parts == before_parts
    assert set(confirmed_manifests) == {
        ".resume-primary-candidates/tier3-evaluation/" + manifest_name
    }
    assert set(confirmed_parts) == {".resume-primary-candidates/tier3-evaluation/" + part.name}
    with pytest.raises(LexicalPipelineError, match="changed while confirming reuse"):
        lexical_pipeline._confirmed_tier3_checkpoint_reuse(
            before_manifests=before_manifests,
            before_parts=before_parts,
            after_manifests={},
            after_parts=after_parts,
        )


def test_private_checkpoint_quarantine_restores_failure_and_cleans_only_after_success(
    tmp_path: Path,
) -> None:
    output = tmp_path / "lexical" / "schema-v1"
    staging = output.parent / ".schema-v1.writing-fixture"
    checkpoint = staging / ".resume-primary-candidates"
    retained = checkpoint / "tier3-evaluation" / "retained.txt"
    retained.parent.mkdir(parents=True)
    retained.write_text("retained\n", encoding="utf-8")
    guard = lexical_pipeline._PrivateCheckpointQuarantine(output_dir=output)
    guard.register_staging(staging)
    guard.quarantine_before_promotion()

    assert not checkpoint.exists()
    assert guard.quarantine_dir is not None
    assert guard.quarantine_dir.is_dir()
    failure = RuntimeError("synthetic late failure")
    guard.preserve_after_failure(failure)
    assert retained.is_file()
    assert guard.quarantine_dir is None
    assert any(
        "preserved lexical staging directory" in note for note in getattr(failure, "__notes__", ())
    )

    successful_guard = lexical_pipeline._PrivateCheckpointQuarantine(output_dir=output)
    successful_guard.register_staging(staging)
    successful_guard.quarantine_before_promotion()
    quarantine = successful_guard.quarantine_dir
    assert quarantine is not None and quarantine.is_dir()
    staging.replace(output)
    assert successful_guard.cleanup_after_success() is None
    assert not quarantine.exists()
    assert output.is_dir()


def test_private_checkpoint_quarantine_survives_post_promotion_failure(
    tmp_path: Path,
) -> None:
    output = tmp_path / "lexical" / "schema-v1"
    staging = output.parent / ".schema-v1.writing-fixture"
    retained = staging / ".resume-primary-candidates" / "tier3-evaluation" / "retained.txt"
    retained.parent.mkdir(parents=True)
    retained.write_text("retained\n", encoding="utf-8")
    guard = lexical_pipeline._PrivateCheckpointQuarantine(output_dir=output)
    guard.register_staging(staging)
    guard.quarantine_before_promotion()
    quarantine = guard.quarantine_dir
    assert quarantine is not None
    staging.replace(output)

    failure = RuntimeError("synthetic post-promotion failure")
    guard.preserve_after_failure(failure)

    assert quarantine.is_dir()
    assert (quarantine / "tier3-evaluation" / "retained.txt").is_file()
    assert any(str(quarantine) in note for note in getattr(failure, "__notes__", ()))


def test_private_checkpoint_quarantine_is_restored_after_process_interruption(
    tmp_path: Path,
) -> None:
    output = tmp_path / "lexical" / "schema-v1"
    staging = output.parent / ".schema-v1.writing-fixture"
    retained = staging / ".resume-primary-candidates" / "tier3-evaluation" / "retained.txt"
    retained.parent.mkdir(parents=True)
    retained.write_text("retained\n", encoding="utf-8")
    interrupted = lexical_pipeline._PrivateCheckpointQuarantine(output_dir=output)
    interrupted.register_staging(staging)
    interrupted.quarantine_before_promotion()
    quarantine = interrupted.quarantine_dir
    assert quarantine is not None and quarantine.is_dir()
    assert not retained.exists()

    resumed = lexical_pipeline._PrivateCheckpointQuarantine(output_dir=output)
    resumed.register_staging(staging)

    assert retained.is_file()
    assert not quarantine.exists()


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


def test_resume_recreates_only_an_empty_candidate_review_queue_spool(
    tmp_path: Path,
) -> None:
    staging = tmp_path / ".schema-v1.writing-fixture"
    staging.mkdir()
    stale = staging / ".candidate-review-queue-spool"
    stale.mkdir()

    prepared = _prepare_candidate_review_queue_spool(staging, resumed=True)

    assert prepared == stale
    assert prepared.is_dir()
    assert list(prepared.iterdir()) == []


def test_resume_refuses_to_discard_candidate_review_queue_spool_residue(
    tmp_path: Path,
) -> None:
    staging = tmp_path / ".schema-v1.writing-fixture"
    staging.mkdir()
    stale = staging / ".candidate-review-queue-spool"
    stale.mkdir()
    residual = stale / "part-00000.parquet"
    residual.write_bytes(b"unvalidated residual")

    with pytest.raises(LexicalPipelineError, match="refusing to discard nonempty"):
        _prepare_candidate_review_queue_spool(staging, resumed=True)

    assert residual.read_bytes() == b"unvalidated residual"


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
    detector: str = "jaccard",
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
        "detector": detector,
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
            _ranking_row(
                ranking_id="baseline-bm25",
                query_id="b1",
                target_id="b2",
                scope="primary",
                profile="edition_complete",
                representation_id="baseline-representation",
                score=0.7,
                detector="bm25",
            ),
            _ranking_row(
                ranking_id="comparison-bm25",
                query_id="c1",
                target_id="c2",
                scope="critical_core_greek_sensitivity",
                profile="critical_core",
                representation_id="comparison-representation",
                score=0.5,
                detector="bm25",
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
            minimum_free_disk_bytes=0,
        )
    )

    result = pl.concat(frames)
    assert result.height == 2
    assert result.get_column("detector").to_list() == ["bm25", "jaccard"]
    row = result.filter(pl.col("detector") == "jaccard").row(0, named=True)
    assert row["query_reference"] == "MAT 1:1"
    assert row["target_reference"] == "MAT 1:2"
    assert row["score_delta"] == pytest.approx(-0.2)
    assert row["rank_delta"] == 0
    assert row["top_k_overlap"] == 1.0
    assert row["baseline_reading"] == "source"
    assert row["comparison_reading"] == "source"
    assert row["baseline_sequence_digest"] != row["comparison_sequence_digest"]
    assert not (tmp_path / "spill").exists()


def test_sensitivity_join_fails_before_crossing_disk_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranking_root = tmp_path / "rankings"
    ranking_root.mkdir()
    baseline = [_passage("b1", "MAT 1:1", ("shared",), corpus="greek")]
    comparison = [
        _passage(
            "c1",
            "MAT 1:1",
            ("shared",),
            corpus="greek",
            profile="critical_core",
        )
    ]
    monkeypatch.setattr(
        lexical_pipeline.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=512 * MEBIBYTE),
    )

    with pytest.raises(LexicalPipelineError, match="insufficient disk headroom"):
        list(
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
                minimum_free_disk_bytes=256 * MEBIBYTE,
            )
        )


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


def test_targeted_split_provenance_matches_full_lookup(tmp_path: Path) -> None:
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
            "('e1','verse','[\"p1\",\"p2\"]','mapped_verified')"
        )
        connection.execute(
            "INSERT INTO benchmark_split_assignments VALUES "
            "('r1','v1','held_out_book','test','eligible',NULL,'group-1')"
        )
    sequences = [
        _passage("p1", "GEN 1:1", ("lemma",)),
        _passage("p2", "GEN 1:2", ("lemma",)),
    ]
    full = _load_split_provenance(
        database,
        sequences,
        duckdb_memory_limit_bytes=128 * 1024**2,
        duckdb_temp_directory=tmp_path / "full-spill",
    )
    targeted = _load_split_provenance(
        database,
        [item.passage_id for item in sequences],
        duckdb_memory_limit_bytes=128 * 1024**2,
        duckdb_temp_directory=tmp_path / "targeted-spill",
        targeted_lookup=True,
    )

    assert targeted == full


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
