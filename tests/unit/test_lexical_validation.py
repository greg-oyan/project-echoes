"""Focused contracts for Milestone 7 lexical validation and read-only queries."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import cast

import duckdb
import numpy as np
import polars as pl
import pytest

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
from echoes.lexical.models import (
    LEXICAL_ARTIFACT_NAMES,
    LEXICAL_ARTIFACT_SCHEMAS,
    LexicalArtifactName,
)
from echoes.lexical.sequences import FeatureOccurrence, PassageLexicalSequence
from echoes.lexical.sparse import build_sparse_index, persist_sparse_index
from echoes.lexical.storage import LexicalArtifactWriter
from echoes.lexical.validation import (
    compare_lexical_runs,
    null_replicate_logical_hash,
    shared_evidence_digest,
    show_lexical_candidate,
    sparse_index_physical_hash,
    sparse_index_portable_hash,
    validate_lexical_artifacts,
)


def _empty_artifact_tree(root: Path) -> None:
    for name in LEXICAL_ARTIFACT_NAMES:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]).write_parquet(
            directory / "part-00000.parquet"
        )


def _register_empty_artifact_tables(connection: duckdb.DuckDBPyConnection) -> None:
    for name in LEXICAL_ARTIFACT_NAMES:
        registered = f"__{name}"
        connection.register(registered, pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]))
        connection.execute(f'CREATE TABLE "{name}" AS SELECT * FROM "{registered}"')
        connection.unregister(registered)


def _replace_artifact_table(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    rows: list[dict[str, object]],
) -> None:
    registered = f"__replacement_{name}"
    frame = pl.DataFrame(
        rows,
        schema=LEXICAL_ARTIFACT_SCHEMAS[cast(LexicalArtifactName, name)],
        orient="row",
    )
    connection.register(registered, frame)
    connection.execute(f'DROP TABLE "{name}"')
    connection.execute(f'CREATE TABLE "{name}" AS SELECT * FROM "{registered}"')
    connection.unregister(registered)


def _sparse_passage(passage_id: str, lemma: str) -> PassageLexicalSequence:
    token_id = f"{passage_id}-token"

    def occurrences(family: str, value: str) -> tuple[FeatureOccurrence, ...]:
        return (
            FeatureOccurrence(
                value=value,
                position_in_passage=1,
                token_id=token_id,
                source_word_id=f"{passage_id}-{family}-word",
            ),
        )

    lemma_occurrences = occurrences("lemma", lemma)
    return PassageLexicalSequence(
        passage_id=passage_id,
        corpus="hebrew",
        book="GEN",
        book_order=1,
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        start_reference="GEN.1.1",
        end_reference="GEN.1.1",
        source_passage_digest="a" * 64,
        start_stream_position_in_corpus=0,
        token_count=1,
        disputed_passage_flag=False,
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        lemma=lemma_occurrences,
        root=(),
        surface=lemma_occurrences,
        folded_surface=lemma_occurrences,
        part_of_speech=occurrences("part_of_speech", "noun"),
        morphology=occurrences("morphology", '{"number":"singular"}'),
        english_gloss=(),
        provenance_token_ids=(token_id,),
        zero_width_token_ids=(),
        punctuation_token_ids=(),
        elided_token_ids=(),
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


def test_generic_validation_accepts_nullable_evidence_and_no_threshold_sentinels(
    tmp_path: Path,
) -> None:
    shared = {
        "evidence_id": "E1",
        "candidate_pair_id": "C1",
        "evidence_family": "lemma",
        "feature_id": "F1",
        "feature_value": "lemma-a",
        "passage_a_positions_json": "[0]",
        "passage_b_positions_json": "[0]",
        "corpus_frequency": 1,
        "document_frequency": 1,
        "passage_a_local_frequency": 1,
        "passage_b_local_frequency": 1,
        "association_score": 1.0,
        "pmi": None,
        "log_likelihood": None,
        "frequency_control": None,
        "score_formula": "fixture",
        "detector_contributions_json": "{}",
        "independence_expected_count": 0.0,
        "contains_primary_rare_item": False,
        "counts_as_independent_co_signal": False,
        "english_derived": False,
        "notes": "",
    }
    candidate_evidence: dict[str, object] = {}
    for column, dtype in LEXICAL_ARTIFACT_SCHEMAS["candidate_evidence"].items():
        if dtype == pl.String:
            candidate_evidence[column] = "fixture"
        elif dtype == pl.Boolean:
            candidate_evidence[column] = False
        elif dtype in {pl.Float32, pl.Float64}:
            candidate_evidence[column] = 0.0
        else:
            candidate_evidence[column] = 0
    candidate_evidence.update(
        {
            "null_model_empirical_rate": math.inf,
            "estimated_empirical_fdr": math.inf,
            "selected_score_threshold": 1.0,
        }
    )
    with duckdb.connect() as connection:
        _register_empty_artifact_tables(connection)
        _replace_artifact_table(connection, "shared_evidence", [shared])
        _replace_artifact_table(connection, "candidate_evidence", [candidate_evidence])
        state = lexical_validation._State(output_dir=tmp_path, strict=True)

        lexical_validation._validate_generic_tables(state, connection)

    assert state.issues == []


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


def test_python_quantization_is_half_even_and_streamed_in_fixed_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_batch_sizes: list[int] = []
    original_fetchmany = lexical_validation._fetchmany

    def recording_fetchmany(
        cursor: duckdb.DuckDBPyConnection,
        batch_size: int = 65_536,
    ) -> object:
        observed_batch_sizes.append(batch_size)
        yield from original_fetchmany(cursor, batch_size)

    monkeypatch.setattr(lexical_validation, "_fetchmany", recording_fetchmany)
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE scores AS SELECT 2.675::DOUBLE AS raw_score,"
            "2.67::DOUBLE AS quantized_score FROM range(50001)"
        )

        valid = lexical_validation._python_quantization_mismatches(
            connection,
            table="scores",
            raw_column="raw_score",
            quantized_column="quantized_score",
            decimals=2,
        )
        connection.execute("UPDATE scores SET quantized_score=2.68 WHERE rowid=0")
        corrupt = lexical_validation._python_quantization_mismatches(
            connection,
            table="scores",
            raw_column="raw_score",
            quantized_column="quantized_score",
            decimals=2,
        )

    assert round(2.675, 2) == 2.67
    assert valid == 0
    assert corrupt == 1
    assert observed_batch_sizes == [25_000, 25_000]


def test_rrf_rank_order_uses_raw_score_before_candidate_id_tie_break() -> None:
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE directional_rankings("
            "experiment_scope VARCHAR,analysis_profile VARCHAR,query_reading VARCHAR,"
            "target_reading VARCHAR,granularity VARCHAR,query_passage_id VARCHAR,"
            "representation_id VARCHAR,detector VARCHAR,rank INTEGER,raw_score DOUBLE,"
            "quantized_score DOUBLE,target_passage_id VARCHAR,tie_break_key VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO directional_rankings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "primary",
                    "edition_complete",
                    "qere",
                    "qere",
                    "verse",
                    "Q",
                    "REP",
                    "rrf_composite",
                    1,
                    0.50000000000004,
                    0.5,
                    "Z",
                    "Z",
                ),
                (
                    "primary",
                    "edition_complete",
                    "qere",
                    "qere",
                    "verse",
                    "Q",
                    "REP",
                    "rrf_composite",
                    2,
                    0.50000000000003,
                    0.5,
                    "A",
                    "A",
                ),
            ],
        )

        assert lexical_validation._ranking_order_mismatches(connection) == 0
        connection.execute(
            "UPDATE directional_rankings SET raw_score=CASE rank WHEN 1 THEN 0.4 ELSE 0.6 END"
        )
        assert lexical_validation._ranking_order_mismatches(connection) == 1


def test_split_provenance_reconciliation_uses_bounded_two_gib_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_assignment = '{"status":"no_eligible_benchmark_assignment"}'
    database = tmp_path / "project.duckdb"
    database.touch()
    observed_budget: list[int] = []

    def fake_load_split(
        _database_path: Path,
        sequences: list[object],
        *,
        duckdb_memory_limit_bytes: int,
        duckdb_temp_directory: Path,
    ) -> dict[str, str]:
        del duckdb_temp_directory
        observed_budget.append(duckdb_memory_limit_bytes)
        return {str(item.passage_id): no_assignment for item in sequences}  # type: ignore[attr-defined]

    monkeypatch.setattr("echoes.lexical.pipeline._load_split_provenance", fake_load_split)
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE directional_rankings AS SELECT "
            "'P_QUERY'::VARCHAR AS query_passage_id,?::VARCHAR AS query_split,"
            "'P_TARGET'::VARCHAR AS target_passage_id,?::VARCHAR AS target_split",
            [no_assignment, no_assignment],
        )
        state = lexical_validation._State(output_dir=tmp_path, strict=True)

        lexical_validation._validate_ranking_split_provenance(state, connection, database)

    assert state.issues == []
    assert observed_budget == [2 * 1024**3]


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


def test_inline_directional_english_ablation_is_complete_and_not_duplicated(
    tmp_path: Path,
) -> None:
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE directional_rankings("
            "corpus_pair VARCHAR, contains_english_derived_evidence BOOLEAN, "
            "raw_score DOUBLE, rank INTEGER, "
            "score_after_removing_all_english_features DOUBLE, "
            "rank_after_removing_all_english_features INTEGER, "
            "non_english_evidence_remains BOOLEAN, english_ablation_survives BOOLEAN, "
            "classification_after_english_ablation VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO directional_rankings VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    "hb_gnt_english_bridge",
                    True,
                    0.75,
                    1,
                    0.0,
                    None,
                    False,
                    False,
                    "english_mediated_lead_without_non_english_score",
                ),
                (
                    "hb_hb",
                    False,
                    0.5,
                    2,
                    0.5,
                    2,
                    True,
                    True,
                    "original_language_ranking_unchanged",
                ),
            ],
        )
        connection.execute("CREATE TABLE ablation_results(subject_type VARCHAR)")

        valid = lexical_validation._State(output_dir=tmp_path, strict=True)
        lexical_validation._validate_directional_english_ablation(valid, connection)
        assert valid.issues == []

        connection.execute(
            "UPDATE directional_rankings SET "
            "classification_after_english_ablation='corrupt', "
            "score_after_removing_all_english_features=NULL "
            "WHERE corpus_pair='hb_gnt_english_bridge'"
        )
        corrupt = lexical_validation._State(output_dir=tmp_path, strict=True)
        lexical_validation._validate_directional_english_ablation(corrupt, connection)
        assert {issue.code for issue in corrupt.issues} == {"ranking_english_ablation"}

        connection.execute("INSERT INTO ablation_results VALUES ('directional_ranking')")
        duplicated = lexical_validation._State(output_dir=tmp_path, strict=True)
        lexical_validation._validate_directional_english_ablation(duplicated, connection)
        assert {issue.code for issue in duplicated.issues} == {
            "directional_ablation_storage_normalization",
            "ranking_english_ablation",
        }


def test_special_derived_and_trace_evidence_identities_reproduce_exactly() -> None:
    positions_a = [0]
    positions_b = [1]
    derived_family = "english_gloss_ngram"
    derived_value = "word\u241fpair"
    derived_feature = lexical_validation._canonical_hash_id(
        "LF",
        {"namespace": "en", "family": derived_family, "value": derived_value},
    )
    derived_payload = {
        "candidate_pair_id": "C1",
        "evidence_family": derived_family,
        "feature_id": derived_feature,
        "positions_a": positions_a,
        "positions_b": positions_b,
    }
    trace_family = "longest_common_subsequence_trace"
    trace_payload = {
        "candidate_pair_id": "C1",
        "evidence_family": trace_family,
        "features": ["alpha", "beta"],
        "positions_a": positions_a,
        "positions_b": positions_b,
    }
    rows = [
        (
            lexical_validation._canonical_hash_id("LE", derived_payload),
            "C1",
            derived_family,
            derived_feature,
            derived_value,
            "[0]",
            "[1]",
        ),
        (
            lexical_validation._canonical_hash_id("LE", trace_payload),
            "C1",
            trace_family,
            lexical_validation._canonical_hash_id("LF", trace_payload),
            "alpha\u241fbeta",
            "[0]",
            "[1]",
        ),
    ]
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE candidate_pairs(candidate_pair_id VARCHAR)")
        connection.execute("INSERT INTO candidate_pairs VALUES ('C1')")
        connection.execute(
            "CREATE TABLE feature_vocabulary(feature_id VARCHAR,feature_value VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE shared_evidence(evidence_id VARCHAR,candidate_pair_id VARCHAR,"
            "evidence_family VARCHAR,feature_id VARCHAR,feature_value VARCHAR,"
            "passage_a_positions_json VARCHAR,passage_b_positions_json VARCHAR)"
        )
        connection.executemany("INSERT INTO shared_evidence VALUES (?,?,?,?,?,?,?)", rows)

        assert lexical_validation._special_evidence_identity_mismatches(connection) == 0
        connection.execute(
            "UPDATE shared_evidence SET feature_id='LF_corrupt' "
            "WHERE evidence_family='english_gloss_ngram'"
        )
        assert lexical_validation._special_evidence_identity_mismatches(connection) == 1


def test_trace_position_bounds_follow_retrieval_direction_and_bridge_axis() -> None:
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE shared_evidence(candidate_pair_id VARCHAR,evidence_family VARCHAR,"
            "passage_a_positions_json VARCHAR,passage_b_positions_json VARCHAR,"
            "passage_a_local_frequency INTEGER,passage_b_local_frequency INTEGER)"
        )
        connection.execute(
            "CREATE TABLE candidate_pairs(candidate_pair_id VARCHAR,passage_a_id VARCHAR,"
            "passage_b_id VARCHAR,corpus_pair VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE candidate_detector_scores(candidate_pair_id VARCHAR,detector VARCHAR,"
            "direction VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE passage_feature_statistics(passage_id VARCHAR,"
            "lemma_sequence_length INTEGER,english_gloss_sequence_length INTEGER)"
        )
        connection.executemany(
            "INSERT INTO candidate_pairs VALUES (?,?,?,?)",
            [
                ("C1", "A", "B", "hb_hb"),
                ("C2", "C", "D", "hb_gnt_english_bridge"),
            ],
        )
        connection.executemany(
            "INSERT INTO candidate_detector_scores VALUES (?,'rrf_composite',?)",
            [("C1", "b_to_a"), ("C2", "a_to_b")],
        )
        connection.executemany(
            "INSERT INTO passage_feature_statistics VALUES (?,?,?)",
            [("A", 2, 0), ("B", 5, 0), ("C", 10, 2), ("D", 10, 3)],
        )
        connection.executemany(
            "INSERT INTO shared_evidence VALUES (?,?,?,?,?,?)",
            [
                ("C1", "longest_common_subsequence_trace", "[4]", "[1]", 1, 1),
                ("C2", "weighted_sequence_alignment_trace", "[1]", "[2]", 1, 1),
            ],
        )

        assert lexical_validation._trace_position_mismatches(connection) == 0
        connection.execute(
            "UPDATE shared_evidence SET passage_a_positions_json='[2]' WHERE candidate_pair_id='C2'"
        )
        assert lexical_validation._trace_position_mismatches(connection) == 1


def test_no_qualified_threshold_uses_exact_noneligible_sentinel() -> None:
    config = load_lexical_config()
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE candidate_evidence(candidate_pair_id VARCHAR,"
            "calibration_selection_scope VARCHAR,both_null_families_present BOOLEAN,"
            "selected_score_threshold DOUBLE,estimated_empirical_fdr DOUBLE,"
            "null_model_empirical_rate DOUBLE)"
        )
        connection.execute(
            "CREATE TABLE candidate_pairs(candidate_pair_id VARCHAR,corpus_pair VARCHAR,"
            "review_eligible BOOLEAN)"
        )
        connection.execute(
            "CREATE TABLE candidate_detector_scores(candidate_pair_id VARCHAR,detector VARCHAR,"
            "representation_id VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE threshold_calibration(threshold_id VARCHAR,detector VARCHAR,"
            "selected BOOLEAN,corpus_pair VARCHAR,representation_id VARCHAR,"
            "score_threshold DOUBLE,estimated_empirical_fdr DOUBLE,"
            "mean_null_candidate_count DOUBLE)"
        )
        connection.execute(
            "INSERT INTO candidate_evidence VALUES "
            "('C1','frozen_corpus_pair_rrf_threshold',false,1.0,?,?)",
            [math.inf, math.inf],
        )
        connection.execute("INSERT INTO candidate_pairs VALUES ('C1','hb_hb',false)")
        connection.execute(
            "INSERT INTO candidate_detector_scores VALUES ('C1','rrf_composite','REP')"
        )

        assert (
            lexical_validation._candidate_calibration_provenance_mismatches(connection, config) == 0
        )
        connection.execute("UPDATE candidate_evidence SET selected_score_threshold=0.9")
        assert (
            lexical_validation._candidate_calibration_provenance_mismatches(connection, config) == 1
        )
        connection.execute(
            "UPDATE candidate_evidence SET selected_score_threshold=1.0; "
            "UPDATE candidate_pairs SET review_eligible=true"
        )
        assert (
            lexical_validation._candidate_calibration_provenance_mismatches(connection, config) == 1
        )


def test_bounded_traceback_json_is_not_misclassified_as_bulk_source_text(
    tmp_path: Path,
) -> None:
    traceback_notes = "traceback=" + json.dumps(list(range(1_500)), separators=(",", ":"))
    assert 4_096 < len(traceback_notes) <= 65_536
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE feature_vocabulary(notes VARCHAR)")
        connection.execute("CREATE TABLE shared_evidence(evidence_family VARCHAR,notes VARCHAR)")
        connection.execute("CREATE TABLE threshold_calibration(notes VARCHAR)")
        connection.execute("CREATE TABLE lexical_metadata(notes VARCHAR)")
        connection.execute("CREATE TABLE lexical_issues(message VARCHAR,details_json VARCHAR)")
        connection.execute(
            "INSERT INTO shared_evidence VALUES ('weighted_sequence_alignment_trace',?)",
            [traceback_notes],
        )
        valid = lexical_validation._State(output_dir=tmp_path, strict=True)

        lexical_validation._validate_no_source_text(valid, connection)
        assert valid.issues == []

        connection.execute(
            "UPDATE shared_evidence SET evidence_family='lemma',notes=?",
            ["x" * 4_097],
        )
        invalid = lexical_validation._State(output_dir=tmp_path, strict=True)
        lexical_validation._validate_no_source_text(invalid, connection)

    assert {issue.code for issue in invalid.issues} == {"bulk_text_payload"}


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


def test_sparse_portable_hash_ignores_npy_header_encoding(tmp_path: Path) -> None:
    index = build_sparse_index(
        [_sparse_passage("P1", "alpha")],
        representation_id="REP",
        family="lemma",
        namespace="hb",
    )
    output = tmp_path / "REP"
    persist_sparse_index(index, output)
    portable_before = sparse_index_portable_hash(output)
    physical_before = sparse_index_physical_hash(output)
    data_path = output / "counts-data.npy"
    decoded = np.load(data_path, allow_pickle=False)
    with data_path.open("wb") as handle:
        np.lib.format.write_array(handle, decoded, version=(2, 0), allow_pickle=False)

    assert sparse_index_physical_hash(output) != physical_before
    assert sparse_index_portable_hash(output) == portable_before


def test_sparse_validation_loads_exact_inventory_and_checks_authoritative_axis(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "lexical"
    index = build_sparse_index(
        [_sparse_passage("P1", "alpha")],
        representation_id="REP",
        family="lemma",
        namespace="hb",
    )
    index_directory = artifact_root / "indexes" / "REP"
    persist_sparse_index(index, index_directory)
    database = tmp_path / "project.duckdb"
    with duckdb.connect(str(database)) as source:
        source.execute(
            "CREATE TABLE passages(passage_id VARCHAR,corpus VARCHAR,"
            "analysis_profile VARCHAR,analysis_reading VARCHAR,granularity VARCHAR)"
        )
        source.execute(
            "INSERT INTO passages VALUES ('P1','hebrew','edition_complete','qere','verse')"
        )
    metadata = {
        "index_id": "IDX",
        "experiment_run_id": "RUN",
        "representation_id": "REP",
        "corpus_scope": "hebrew",
        "profile": "edition_complete",
        "reading": "qere",
        "granularity": "verse",
        "feature_family": "lemma",
        "matrix_shape_json": "[1,1]",
        "nonzero_count": 1,
        "vocabulary_size": 1,
        "document_count": 1,
        "index_config_hash": "a" * 64,
        "logical_matrix_hash": index.logical_hash,
        "physical_file_hash": sparse_index_physical_hash(index_directory),
        "dtype": "float64",
        "storage_format": "canonical-npy-csr-v1",
        "notes": "fixture",
    }
    with duckdb.connect() as connection:
        connection.register(
            "metadata_fixture",
            pl.DataFrame(
                [metadata],
                schema=LEXICAL_ARTIFACT_SCHEMAS["lexical_index_metadata"],
                orient="row",
            ),
        )
        connection.execute("CREATE TABLE lexical_index_metadata AS SELECT * FROM metadata_fixture")
        connection.execute(
            "CREATE TABLE feature_vocabulary(language_namespace VARCHAR,"
            "feature_family VARCHAR,feature_value VARCHAR,feature_id VARCHAR)"
        )
        connection.execute("INSERT INTO feature_vocabulary VALUES ('hb','lemma','alpha','F1')")
        connection.execute("CREATE TABLE passage_feature_statistics(passage_id VARCHAR)")
        connection.execute("INSERT INTO passage_feature_statistics VALUES ('P1')")
        valid = lexical_validation._State(output_dir=artifact_root, strict=True)

        lexical_validation._validate_sparse_indexes(valid, connection, database)
        assert valid.issues == []

        unexpected = artifact_root / "indexes" / "unexpected"
        unexpected.mkdir()
        inventory = lexical_validation._State(output_dir=artifact_root, strict=True)
        lexical_validation._validate_sparse_indexes(inventory, connection, database)
        assert "index_inventory" in {issue.code for issue in inventory.issues}
        unexpected.rmdir()

        with duckdb.connect(str(database)) as source:
            source.execute("UPDATE passages SET analysis_reading='ketiv'")
        axis = lexical_validation._State(output_dir=artifact_root, strict=True)
        lexical_validation._validate_sparse_indexes(axis, connection, database)
        assert "index_passage_axis" in {issue.code for issue in axis.issues}


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
        pl.DataFrame(
            values,
            schema=LEXICAL_ARTIFACT_SCHEMAS[cast(LexicalArtifactName, name)],
            orient="row",
        ).write_parquet(root / name / "part-00000.parquet")

    result = show_lexical_candidate(pair_id, root)

    assert result is not None
    assert result["candidate"]["candidate_pair_id"] == pair_id  # type: ignore[index]
    assert result["shared_evidence"] == [shared]
    serialized = json.dumps(result, sort_keys=True)
    assert "source_text" not in serialized
    assert "reconstructed_text" not in serialized


def test_zero_row_review_queue_is_a_valid_typed_artifact(tmp_path: Path) -> None:
    config = load_lexical_config()
    with duckdb.connect() as connection:
        for name in ("candidate_review_queue", "candidate_pairs", "candidate_evidence"):
            registered = f"__{name}"
            connection.register(
                registered,
                pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]),
            )
            connection.execute(f'CREATE TABLE "{name}" AS SELECT * FROM "{registered}"')
            connection.unregister(registered)
        state = lexical_validation._State(output_dir=tmp_path, strict=True)

        lexical_validation._validate_queue(state, connection, config)

    assert state.issues == []


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
