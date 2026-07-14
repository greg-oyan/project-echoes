"""Focused contracts for Milestone 7 lexical validation and read-only queries."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

from echoes.lexical import validation as lexical_validation
from echoes.lexical.config import (
    lexical_config_sha256,
    lexical_preregistration_sha256,
    load_lexical_config,
    load_lexical_preregistration,
)
from echoes.lexical.identity import (
    CandidatePairIdentityPayload,
    FeatureIdentityPayload,
    build_candidate_pair_identity,
    build_feature_identity,
)
from echoes.lexical.models import LEXICAL_ARTIFACT_NAMES, LEXICAL_ARTIFACT_SCHEMAS
from echoes.lexical.storage import LexicalArtifactWriter
from echoes.lexical.validation import (
    compare_lexical_runs,
    null_replicate_logical_hash,
    shared_evidence_digest,
    show_lexical_candidate,
    sparse_index_physical_hash,
    validate_lexical_artifacts,
)


def _empty_artifact_tree(root: Path) -> None:
    for name in LEXICAL_ARTIFACT_NAMES:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]).write_parquet(
            directory / "part-00000.parquet"
        )


def test_shared_evidence_digest_is_order_independent_and_caveat_sensitive() -> None:
    feature = build_feature_identity(
        FeatureIdentityPayload(
            feature_family="lemma",
            language_namespace="hb",
            feature_value="lemma-a",
            feature_order=1,
        )
    ).identifier
    first = {
        "evidence_id": "E1",
        "candidate_pair_id": "C1",
        "evidence_family": "lemma",
        "feature_id": feature,
        "feature_value": "lemma-a",
        "passage_a_positions_json": "[0]",
        "passage_b_positions_json": "[1]",
        "corpus_frequency": 2,
        "document_frequency": 2,
        "passage_a_local_frequency": 1,
        "passage_b_local_frequency": 1,
        "association_score": 1.0,
        "pmi": None,
        "log_likelihood": None,
        "frequency_control": None,
        "score_formula": "fixture_association_score",
        "detector_contributions_json": "{}",
        "independence_expected_count": 0.1,
        "contains_primary_rare_item": True,
        "counts_as_independent_co_signal": False,
        "english_derived": False,
        "notes": "primary item",
    }
    second = {**first, "evidence_id": "E2", "notes": "co-signal"}

    digest = shared_evidence_digest([first, second])

    assert digest == shared_evidence_digest([second, first])
    assert digest != shared_evidence_digest([first, {**second, "notes": "changed"}])


def test_ranking_split_provenance_collapses_duplicates_and_detects_mismatch(
    tmp_path: Path,
) -> None:
    no_assignment = '{"status":"no_eligible_benchmark_assignment"}'
    governed_assignment = json.dumps(
        {
            "assignment_digest": "a" * 64,
            "benchmark_versions": ["benchmark-v1"],
            "eligible_partitions": {"held_out_genre": ["test"]},
            "leakage_group_count": 1,
            "leakage_group_ids_digest": "b" * 64,
            "leakage_membership_complete": True,
            "mapping_statuses": ["mapped_provisional"],
            "status": "eligible_benchmark_assignment_present",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE directional_rankings AS SELECT "
            "'P_QUERY'::VARCHAR AS query_passage_id,?::VARCHAR AS query_split,"
            "'P_TARGET'::VARCHAR AS target_passage_id,?::VARCHAR AS target_split "
            "FROM range(10000)",
            [no_assignment, no_assignment],
        )

        collapsed = list(lexical_validation._iter_collapsed_ranking_split_provenance(connection))

        assert collapsed == [
            ("P_QUERY", no_assignment, no_assignment, 10_000, 10_000),
            ("P_TARGET", no_assignment, no_assignment, 10_000, 10_000),
        ]
        consistent_state = lexical_validation._State(output_dir=tmp_path, strict=True)
        lexical_validation._validate_ranking_split_provenance(consistent_state, connection, None)
        assert "ranking_split_provenance" not in {issue.code for issue in consistent_state.issues}

        connection.execute(
            "INSERT INTO directional_rankings VALUES ('P_QUERY',?,'P_TARGET',?)",
            [governed_assignment, no_assignment],
        )
        mismatched_state = lexical_validation._State(output_dir=tmp_path, strict=True)
        lexical_validation._validate_ranking_split_provenance(mismatched_state, connection, None)

    assert "ranking_split_provenance" in {issue.code for issue in mismatched_state.issues}


def test_null_logical_hash_excludes_runtime_and_self_hash() -> None:
    row = {
        "null_run_id": "N1",
        "experiment_run_id": "R1",
        "null_family": "within_book_reassignment",
        "iteration": 0,
        "seed": 7101,
        "corpus_pair": "hb_hb",
        "representation_id": "REP1",
        "detector": "rrf_composite",
        "threshold_id": "T1",
        "candidate_count": 1,
        "mean_score": 0.1,
        "score_quantiles_json": '{"q50":0.1}',
        "conditioning_json": '{"passage_lengths_preserved":true}',
        "passage_count": 2,
        "token_count": 4,
        "length_digest": "a" * 64,
        "frequency_digest": "b" * 64,
        "logical_output_hash": "c" * 64,
        "runtime_seconds": 1.0,
    }

    digest = null_replicate_logical_hash(row)

    assert digest == null_replicate_logical_hash(
        {**row, "logical_output_hash": "d" * 64, "runtime_seconds": 99.0}
    )
    assert digest != null_replicate_logical_hash({**row, "candidate_count": 2})


def test_null_scoring_scope_excludes_registered_sensitivities() -> None:
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE directional_rankings(corpus_pair VARCHAR,representation_id VARCHAR,"
            "detector VARCHAR,experiment_scope VARCHAR,analysis_profile VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO directional_rankings VALUES (?,?,?,?,?)",
            [
                ("hb_hb", "REP_PRIMARY", "rrf_composite", "primary", "edition_complete"),
                ("gnt_gnt", "REP_CRITICAL", "rrf_composite", "critical_core", "critical_core"),
                ("hb_hb", "REP_KETIV", "rrf_composite", "qere_ketiv", "edition_complete"),
            ],
        )

        observed = lexical_validation._governed_null_scoring_strata(connection)

    assert observed == {("hb_hb", "REP_PRIMARY", "rrf_composite")}


def test_sparse_physical_hash_is_order_stable_and_content_sensitive(tmp_path: Path) -> None:
    index = tmp_path / "index"
    index.mkdir()
    (index / "b.bin").write_bytes(b"b")
    (index / "a.bin").write_bytes(b"a")

    first = sparse_index_physical_hash(index)
    second = sparse_index_physical_hash(index)
    (index / "a.bin").write_bytes(b"changed")

    assert first == second
    assert first != sparse_index_physical_hash(index)


def test_determinism_comparison_covers_every_governed_artifact(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    hashes = {name: "a" * 64 for name in LEXICAL_ARTIFACT_NAMES}
    manifest = {
        "table_counts": {name: 1 for name in LEXICAL_ARTIFACT_NAMES},
        "table_logical_sha256": hashes,
    }
    for root in (first, second):
        metadata = root / "lexical_metadata"
        metadata.mkdir(parents=True)
        pl.DataFrame({"experiment_run_id": ["deterministic-run"]}).write_parquet(
            metadata / "part-00000.parquet"
        )
        (root / "table-hashes.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )

    matching = compare_lexical_runs(first, second)

    assert matching.passed is True
    assert matching.differing_tables == []

    changed = json.loads((second / "table-hashes.json").read_text(encoding="utf-8"))
    changed["table_logical_sha256"][LEXICAL_ARTIFACT_NAMES[0]] = "b" * 64
    (second / "table-hashes.json").write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")

    differing = compare_lexical_runs(first, second)
    assert differing.passed is False
    assert differing.differing_tables == [LEXICAL_ARTIFACT_NAMES[0]]


def test_candidate_query_returns_decomposed_evidence_without_source_text(tmp_path: Path) -> None:
    root = tmp_path / "lexical" / "schema-v1"
    _empty_artifact_tree(root)
    feature_id = build_feature_identity(
        FeatureIdentityPayload(
            feature_family="lemma",
            language_namespace="hb",
            feature_value="lemma-a",
            feature_order=1,
        )
    ).identifier
    pair_id = build_candidate_pair_identity(
        CandidatePairIdentityPayload(
            analysis_profile="edition_complete",
            granularity="verse",
            passage_id_a="P_A",
            passage_id_b="P_B",
        )
    ).identifier
    shared = {
        "evidence_id": "E1",
        "candidate_pair_id": pair_id,
        "evidence_family": "lemma",
        "feature_id": feature_id,
        "feature_value": "lemma-a",
        "passage_a_positions_json": "[0]",
        "passage_b_positions_json": "[0]",
        "corpus_frequency": 2,
        "document_frequency": 2,
        "passage_a_local_frequency": 1,
        "passage_b_local_frequency": 1,
        "association_score": 1.0,
        "pmi": None,
        "log_likelihood": None,
        "frequency_control": None,
        "score_formula": "fixture_association_score",
        "detector_contributions_json": "{}",
        "independence_expected_count": 0.1,
        "contains_primary_rare_item": True,
        "counts_as_independent_co_signal": True,
        "english_derived": False,
        "notes": "",
    }
    rows: dict[str, list[dict[str, object]]] = {
        "feature_vocabulary": [
            {
                "feature_id": feature_id,
                "lexical_schema_version": 1,
                "feature_family": "lemma",
                "language_namespace": "hb",
                "feature_value": "lemma-a",
                "feature_order": 1,
                "corpus_frequency": 2,
                "document_frequency": 2,
                "inverse_document_frequency": 1.0,
                "book_frequency": 1,
                "genre_frequency": 1,
                "is_rare": True,
                "is_high_frequency": False,
                "is_formulaic": False,
                "contains_english_derived_content": False,
                "normalization_method": "NFC",
                "notes": "",
            }
        ],
        "candidate_pairs": [
            {
                "candidate_pair_id": pair_id,
                "canonical_unordered_pair_id": pair_id,
                "experiment_run_id": "R1",
                "passage_a_id": "P_A",
                "passage_b_id": "P_B",
                "passage_a_reference": "GEN 1:1",
                "passage_b_reference": "GEN 1:2",
                "passage_a_book": "GEN",
                "passage_b_book": "GEN",
                "passage_a_reading": "qere",
                "passage_b_reading": "qere",
                "passage_a_token_count": 1,
                "passage_b_token_count": 1,
                "corpus_pair": "hb_hb",
                "analysis_profile": "edition_complete",
                "granularity": "verse",
                "directional_support_count": 2,
                "detector_support_count": 1,
                "known_link_status": "not_represented_in_openbible_snapshot",
                "openbible_relationship_ids_json": "[]",
                "highest_openbible_vote": None,
                "benchmark_tier": None,
                "mapping_quality": "not_applicable",
                "disputed_passage_flag": False,
                "reference_gap": False,
                "ketiv_structural_uncertainty": False,
                "direct_adjacency": False,
                "nearby_context": False,
                "same_book": True,
                "exact_duplicate": False,
                "near_exact_duplicate": False,
                "formulaic_evidence_flag": False,
                "genealogical_formula_pattern_flag": False,
                "legal_formula_pattern_flag": False,
                "formula_pattern_annotation_status": "unavailable",
                "proper_name_only_flag": False,
                "proper_name_annotation_status": "unavailable",
                "contains_english_derived_evidence": False,
                "passage_a_gloss_feature_count": 0,
                "passage_b_gloss_feature_count": 0,
                "passage_a_gloss_coverage": 0.0,
                "passage_b_gloss_coverage": 0.0,
                "gloss_overlap_count": 0,
                "score_with_english_features": None,
                "score_after_removing_all_english_features": None,
                "rank_with_english_features": None,
                "rank_after_removing_all_english_features": None,
                "non_english_evidence_remains": True,
                "english_ablation_survives": True,
                "classification_after_english_ablation": ("original_language_evidence_unchanged"),
                "review_eligible": True,
                "eligibility_reason": "frozen threshold and conjunctive evidence passed",
            }
        ],
        "candidate_detector_scores": [
            {
                "candidate_pair_id": pair_id,
                "detector": "rrf_composite",
                "representation_id": "REP1",
                "score": 0.05,
                "quantized_score": 0.05,
                "direction": "a_to_b",
                "query_rank": 1,
                "reverse_rank": 1,
                "normalization_method": "rrf",
                "score_contribution": 0.05,
                "penalty_contribution": 0.0,
                "adjusted_score": 0.05,
                "score_components_json": "{}",
                "score_trace_digest": "a" * 64,
                "config_hash": "a" * 64,
            }
        ],
        "candidate_evidence": [
            {
                "candidate_pair_id": pair_id,
                "shared_lemma_count": 1,
                "shared_root_count": 0,
                "shared_surface_count": 0,
                "shared_rare_lemma_count": 1,
                "shared_rare_root_count": 0,
                "shared_phrase_count": 0,
                "shared_skipgram_count": 0,
                "lcs_length": 1,
                "normalized_lcs": 1.0,
                "weighted_alignment_score": 1.0,
                "weighted_jaccard_score": 1.0,
                "tfidf_score": 1.0,
                "bm25_score": 1.0,
                "rare_overlap_score": 1.0,
                "phrase_score": 0.0,
                "ordered_sequence_score": 1.0,
                "raw_rrf_score": 0.05,
                "rrf_score": 0.05,
                "expected_overlap_independence": 0.1,
                "hypergeometric_p_value": 0.1,
                "benjamini_hochberg_q_value": 0.1,
                "hypergeometric_population_size": 2,
                "hypergeometric_success_states": 1,
                "hypergeometric_draws": 1,
                "hypergeometric_observed_overlap": 1,
                "hypothesis_family_id": "fixture-family",
                "hypothesis_family_size": 1,
                "hypothesis_selection_scope": "fixture",
                "null_model_empirical_rate": 0.01,
                "estimated_empirical_fdr": 0.1,
                "selected_score_threshold": 0.01,
                "both_null_families_present": True,
                "calibration_selection_scope": "fixture",
                "independent_co_signal_count": 1,
                "rare_rule_passed": True,
                "formulaic_penalty": 0.0,
                "local_context_penalty": 0.0,
                "short_passage_penalty": 0.0,
                "total_penalty_contribution": 0.0,
                "overlap_exclusion": False,
                "detector_trace_digest": "a" * 64,
                "ablation_digest": "b" * 64,
                "evidence_digest": shared_evidence_digest([shared]),
            }
        ],
        "shared_evidence": [shared],
    }
    for name, values in rows.items():
        pl.DataFrame(values, schema=LEXICAL_ARTIFACT_SCHEMAS[name], orient="row").write_parquet(
            root / name / "part-00000.parquet"
        )

    result = show_lexical_candidate(pair_id, root)

    assert result is not None
    assert result["candidate"]["candidate_pair_id"] == pair_id  # type: ignore[index]
    assert result["shared_evidence"] == [shared]
    serialized = json.dumps(result, sort_keys=True)
    assert "source_text" not in serialized
    assert "reconstructed_text" not in serialized


def test_incomplete_promoted_set_returns_stable_errors_not_an_exception(tmp_path: Path) -> None:
    root = tmp_path / "lexical" / "schema-v1"
    config = load_lexical_config()
    preregistration = load_lexical_preregistration()
    with LexicalArtifactWriter(root, duckdb_memory_limit_bytes=128 * 1024**2) as writer:
        for name in LEXICAL_ARTIFACT_NAMES:
            if name == "lexical_metadata":
                continue
            writer.write_frame(name, pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]))
        logical, physical = writer.content_hashes()
        metadata = pl.DataFrame(
            [
                {
                    "experiment_run_id": "synthetic-incomplete",
                    "experiment_version": config.experiment_version,
                    "lexical_schema_version": 1,
                    "candidate_pair_schema_version": 1,
                    "configuration_hash": lexical_config_sha256(config),
                    "preregistration_hash": lexical_preregistration_sha256(preregistration),
                    "input_corpus_hashes_json": "{}",
                    "passage_hashes_json": "{}",
                    "benchmark_hashes_json": "{}",
                    "feature_vocabulary_hashes_json": "{}",
                    "sparse_index_hashes_json": "{}",
                    "table_logical_hashes_json": json.dumps(logical, sort_keys=True),
                    "table_physical_hashes_json": json.dumps(physical, sort_keys=True),
                    "ranking_count": 0,
                    "candidate_count": 0,
                    "null_iteration_count": 0,
                    "evaluation_count": 0,
                    "runtime_seconds": 0.0,
                    "stage_runtime_seconds_json": '{"fixture":0.0}',
                    "peak_memory_bytes": 0,
                    "storage_footprint_bytes": 0,
                    "numerical_environment_json": '{"python":"synthetic"}',
                    "thread_controls_json": '{"threads":1}',
                    "acceptance_status": "incomplete",
                    "notes": "synthetic validation fixture",
                }
            ],
            schema=LEXICAL_ARTIFACT_SCHEMAS["lexical_metadata"],
            orient="row",
        )
        writer.finalize(metadata)

    report = validate_lexical_artifacts(
        root,
        database_path=None,
        verify_anchors=False,
        verify_duckdb=False,
        verify_sparse_indexes=False,
        strict=True,
    )

    codes = {issue.code for issue in report.issues}
    assert report.passed is False
    assert report.error_count > 0
    assert "null_family_set" in codes
    assert "evaluation_baselines" in codes
    assert "leaf_hash_mismatch" not in codes
    assert "table_logical_hash_mismatch" not in codes
    assert report.exit_code == 1
