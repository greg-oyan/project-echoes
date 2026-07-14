from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import polars as pl
import pytest
from pydantic import ValidationError

from echoes.corpus.storage import logical_frame_hash
from echoes.lexical import storage as lexical_storage
from echoes.lexical.anchors import (
    BENCHMARK_CONTENT_LOGICAL_HASHES,
    BENCHMARK_LOGICAL_HASHES,
    BENCHMARK_RUN_ID,
    BENCHMARK_VERSION,
    CORPUS_ANALYTICAL_DIGESTS,
    CORPUS_CONTENT_DIGESTS,
    CORPUS_IDENTITY_DIGESTS,
    GREEK_TOKEN_COUNT,
    HEBREW_TOKEN_COUNT,
    OPENBIBLE_ARCHIVE_SHA256,
    OPENBIBLE_CANONICAL_STREAM_SHA256,
    OPENBIBLE_SNAPSHOT,
    OSHB_LOGICAL_HASHES,
    PASSAGE_CONTENT_COUNTS,
    PASSAGE_CONTENT_LOGICAL_HASHES,
    PASSAGE_COUNTS,
    PASSAGE_LOGICAL_HASHES,
    PASSAGE_RUN_ID,
    TIER1_HEADER_SHA256,
    LexicalAnchorError,
    verify_upstream_anchors,
)
from echoes.lexical.models import (
    FEATURE_VOCABULARY_SCHEMA,
    LEXICAL_ARTIFACT_NAMES,
    LEXICAL_ARTIFACT_SCHEMAS,
    LEXICAL_METADATA_SCHEMA,
    CandidatePairRow,
    DirectionalRankingRow,
    FeatureVocabularyRow,
)
from echoes.lexical.storage import (
    LEXICAL_CONVENIENCE_VIEWS,
    LexicalArtifactWriter,
    LexicalStorageError,
    load_lexical_duckdb,
    processed_from_directory,
    read_artifact_frame,
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _feature_row(feature_id: str, value: str) -> dict[str, object]:
    return {
        "feature_id": feature_id,
        "lexical_schema_version": 1,
        "feature_family": "lemma",
        "language_namespace": "hb",
        "feature_value": value,
        "feature_order": 1,
        "corpus_frequency": 1,
        "document_frequency": 1,
        "inverse_document_frequency": 1.0,
        "book_frequency": 1,
        "genre_frequency": 1,
        "is_rare": True,
        "is_high_frequency": False,
        "is_formulaic": False,
        "contains_english_derived_content": False,
        "normalization_method": "fixture",
        "notes": "",
    }


def _metadata_frame(
    *,
    logical: dict[str, str],
    physical: dict[str, str],
    runtime_seconds: float,
) -> pl.DataFrame:
    row = {
        "experiment_run_id": "lexical-run",
        "experiment_version": "m7-lexical-baseline-v1",
        "lexical_schema_version": 1,
        "candidate_pair_schema_version": 1,
        "configuration_hash": "a" * 64,
        "preregistration_hash": "b" * 64,
        "input_corpus_hashes_json": _canonical({}),
        "passage_hashes_json": _canonical({}),
        "benchmark_hashes_json": _canonical({}),
        "feature_vocabulary_hashes_json": _canonical({}),
        "sparse_index_hashes_json": _canonical({}),
        "table_logical_hashes_json": _canonical(logical),
        "table_physical_hashes_json": _canonical(physical),
        "ranking_count": 0,
        "candidate_count": 0,
        "null_iteration_count": 0,
        "evaluation_count": 0,
        "runtime_seconds": runtime_seconds,
        "stage_runtime_seconds_json": _canonical({"fixture": runtime_seconds}),
        "peak_memory_bytes": 1,
        "storage_footprint_bytes": 1,
        "numerical_environment_json": _canonical({"float": "float64"}),
        "thread_controls_json": _canonical({"threads": 1}),
        "acceptance_status": "implementation_test",
        "notes": "",
    }
    return pl.DataFrame([row], schema=LEXICAL_METADATA_SCHEMA, orient="row")


def _finalize_empty_run(root: Path, *, runtime_seconds: float = 0.0):
    with LexicalArtifactWriter(root, duckdb_memory_limit_bytes=128 * 1024**2) as writer:
        for name in LEXICAL_ARTIFACT_NAMES:
            if name == "lexical_metadata":
                continue
            writer.write_frame(name, pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]))
        logical, physical = writer.content_hashes()
        return writer.finalize(
            _metadata_frame(
                logical=logical,
                physical=physical,
                runtime_seconds=runtime_seconds,
            )
        )


def test_row_models_canonicalize_json_and_enforce_language_and_pair_guardrails() -> None:
    feature = FeatureVocabularyRow(**_feature_row("LF_feature", "lemma"))
    assert feature.language_namespace == "hb"
    with pytest.raises(ValidationError, match="English-derived"):
        FeatureVocabularyRow(
            **{
                **_feature_row("LF_bad", "bad"),
                "contains_english_derived_content": True,
            }
        )

    pair = CandidatePairRow(
        candidate_pair_id="LCP_pair",
        canonical_unordered_pair_id="LCP_pair",
        experiment_run_id="run",
        passage_a_id="a",
        passage_b_id="b",
        passage_a_reference="GEN 1:1",
        passage_b_reference="GEN 1:2",
        passage_a_book="GEN",
        passage_b_book="GEN",
        passage_a_reading="qere",
        passage_b_reading="qere",
        passage_a_token_count=1,
        passage_b_token_count=1,
        corpus_pair="hb_hb",
        analysis_profile="edition_complete",
        granularity="verse",
        directional_support_count=1,
        detector_support_count=1,
        known_link_status="not_represented_in_openbible_snapshot",
        openbible_relationship_ids_json='[ "r2", "r1" ]',
        highest_openbible_vote=None,
        benchmark_tier=None,
        mapping_quality="not_applicable",
        disputed_passage_flag=False,
        reference_gap=False,
        ketiv_structural_uncertainty=False,
        direct_adjacency=False,
        nearby_context=False,
        same_book=True,
        exact_duplicate=False,
        near_exact_duplicate=False,
        formulaic_evidence_flag=False,
        genealogical_formula_pattern_flag=False,
        legal_formula_pattern_flag=False,
        formula_pattern_annotation_status="unavailable",
        proper_name_only_flag=False,
        proper_name_annotation_status="unavailable",
        contains_english_derived_evidence=False,
        passage_a_gloss_feature_count=0,
        passage_b_gloss_feature_count=0,
        passage_a_gloss_coverage=0.0,
        passage_b_gloss_coverage=0.0,
        gloss_overlap_count=0,
        score_with_english_features=None,
        score_after_removing_all_english_features=None,
        rank_with_english_features=None,
        rank_after_removing_all_english_features=None,
        non_english_evidence_remains=True,
        english_ablation_survives=True,
        classification_after_english_ablation="original_language_evidence_unchanged",
        review_eligible=True,
        eligibility_reason="fixture",
    )
    assert pair.openbible_relationship_ids_json == '["r2","r1"]'
    with pytest.raises(ValidationError, match="canonically ordered"):
        CandidatePairRow.model_validate(
            {**pair.model_dump(), "passage_a_id": "b", "passage_b_id": "a"}
        )


def test_directional_ranking_rejects_self_pairs_and_wrong_tie_key() -> None:
    values = {
        "ranking_id": "ranking",
        "experiment_run_id": "run",
        "query_passage_id": "a",
        "target_passage_id": "b",
        "corpus_pair": "hb_hb",
        "experiment_scope": "primary",
        "analysis_profile": "edition_complete",
        "query_reading": "qere",
        "target_reading": "qere",
        "granularity": "verse",
        "representation_id": "representation",
        "detector": "jaccard",
        "rank": 1,
        "raw_score": 1.0,
        "quantized_score": 1.0,
        "query_split": "all",
        "target_split": "all",
        "mapping_scope": "tier3_weak_supervision_recovery",
        "is_self": False,
        "passage_overlap": False,
        "nearby_context": False,
        "same_book": False,
        "contains_english_derived_evidence": False,
        "query_gloss_feature_count": 0,
        "target_gloss_feature_count": 0,
        "query_gloss_coverage": 0.0,
        "target_gloss_coverage": 0.0,
        "gloss_overlap_count": 0,
        "score_after_removing_all_english_features": 1.0,
        "rank_after_removing_all_english_features": 1,
        "non_english_evidence_remains": True,
        "english_ablation_survives": True,
        "classification_after_english_ablation": "original_language_evidence_unchanged",
        "tie_break_key": "b",
    }
    assert DirectionalRankingRow(**values).rank == 1
    with pytest.raises(ValidationError, match="self-pairs"):
        DirectionalRankingRow(
            **{
                **values,
                "target_passage_id": "a",
                "tie_break_key": "a",
                "is_self": True,
            }
        )
    with pytest.raises(ValidationError, match="tie_break_key"):
        DirectionalRankingRow(**{**values, "tie_break_key": "elsewhere"})


def test_streamed_table_hash_is_global_and_independent_of_part_boundaries(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data" / "processed" / "lexical" / "schema-v1"
    full = pl.DataFrame(
        [_feature_row("LF_a", "a"), _feature_row("LF_b", "b")],
        schema=FEATURE_VOCABULARY_SCHEMA,
        orient="row",
    )
    with LexicalArtifactWriter(root, duckdb_memory_limit_bytes=128 * 1024**2) as writer:
        writer.write_frame("feature_vocabulary", full.slice(0, 1), part=0)
        writer.write_frame("feature_vocabulary", full.slice(1, 1), part=1)
        for name in LEXICAL_ARTIFACT_NAMES:
            if name in {"feature_vocabulary", "lexical_metadata"}:
                continue
            writer.write_frame(name, pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]))
        logical, _ = writer.content_hashes()
        assert logical["feature_vocabulary"] == logical_frame_hash(full, sort_by=["feature_id"])


def test_writer_rechecks_the_governed_free_disk_floor_for_each_part(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    free_values = iter((100, 100, 9))
    monkeypatch.setattr(
        lexical_storage.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=next(free_values)),
    )
    root = tmp_path / "lexical" / "schema-v1"

    with (
        pytest.raises(LexicalStorageError, match="free-disk floor"),
        LexicalArtifactWriter(
            root,
            required_free_bytes=10,
            duckdb_memory_limit_bytes=128 * 1024**2,
        ) as writer,
    ):
        writer.write_frame(
            "feature_vocabulary",
            pl.DataFrame(
                [_feature_row("LF_a", "a")],
                schema=FEATURE_VOCABULARY_SCHEMA,
                orient="row",
            ),
        )

    assert not root.exists()
    assert not list(root.parent.glob(".schema-v1.writing-*"))


def test_null_runtime_is_excluded_from_global_logical_hash(tmp_path: Path) -> None:
    def null_run(root: Path, runtime_seconds: float):
        row = {
            "null_run_id": "null_fixture",
            "experiment_run_id": "run",
            "null_family": "within_book_reassignment",
            "iteration": 1,
            "seed": 1,
            "corpus_pair": "hb_hb",
            "representation_id": "representation",
            "detector": "jaccard",
            "threshold_id": "threshold",
            "candidate_count": 1,
            "mean_score": 0.5,
            "score_quantiles_json": '{"q025":0.5,"q50":0.5,"q975":0.5}',
            "conditioning_json": "{}",
            "passage_count": 2,
            "token_count": 4,
            "length_digest": "a" * 64,
            "frequency_digest": "b" * 64,
            "logical_output_hash": "c" * 64,
            "runtime_seconds": runtime_seconds,
        }
        with LexicalArtifactWriter(root, duckdb_memory_limit_bytes=128 * 1024**2) as writer:
            for name in LEXICAL_ARTIFACT_NAMES:
                if name == "lexical_metadata":
                    continue
                frame = (
                    pl.DataFrame(
                        [row],
                        schema=LEXICAL_ARTIFACT_SCHEMAS[name],
                        orient="row",
                    )
                    if name == "null_replicate_summaries"
                    else pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name])
                )
                writer.write_frame(name, frame)
            logical, physical = writer.content_hashes()
            return writer.finalize(
                _metadata_frame(
                    logical=logical,
                    physical=physical,
                    runtime_seconds=runtime_seconds,
                )
            )

    first = null_run(tmp_path / "first" / "lexical" / "schema-v1", 1.0)
    second = null_run(tmp_path / "second" / "lexical" / "schema-v1", 99.0)
    assert (
        first.table_physical_hashes["null_replicate_summaries"]
        != (second.table_physical_hashes["null_replicate_summaries"])
    )
    assert first.table_logical_hashes == second.table_logical_hashes


def test_storage_external_sorts_out_of_order_parts_and_rejects_duplicate_sparse_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lexical" / "schema-v1"
    with LexicalArtifactWriter(root, duckdb_memory_limit_bytes=128 * 1024**2) as writer:
        later = pl.DataFrame(
            [_feature_row("LF_b", "b")], schema=FEATURE_VOCABULARY_SCHEMA, orient="row"
        )
        earlier = pl.DataFrame(
            [_feature_row("LF_a", "a")], schema=FEATURE_VOCABULARY_SCHEMA, orient="row"
        )
        writer.write_frame("feature_vocabulary", later, part=0)
        writer.write_frame("feature_vocabulary", earlier, part=1)
        for name in LEXICAL_ARTIFACT_NAMES:
            if name in {"feature_vocabulary", "lexical_metadata"}:
                continue
            writer.write_frame(name, pl.DataFrame(schema=LEXICAL_ARTIFACT_SCHEMAS[name]))
        logical, _ = writer.content_hashes()
        expected = pl.concat([earlier, later])
        assert logical["feature_vocabulary"] == logical_frame_hash(expected, sort_by=["feature_id"])
        writer.write_sparse_bytes(Path("index") / "data.npy", b"one")
        with pytest.raises(LexicalStorageError, match="duplicate sparse index path"):
            writer.write_sparse_bytes(Path("index") / "data.npy", b"two")


def test_finalize_read_and_duckdb_load_are_transactional_and_runtime_hash_neutral(
    tmp_path: Path,
) -> None:
    first = _finalize_empty_run(tmp_path / "first" / "lexical" / "schema-v1", runtime_seconds=1.0)
    second = _finalize_empty_run(
        tmp_path / "second" / "lexical" / "schema-v1", runtime_seconds=99.0
    )
    assert first.table_logical_hashes == second.table_logical_hashes
    reconstructed = processed_from_directory(first.output_dir)
    assert reconstructed.table_counts == first.table_counts
    assert read_artifact_frame(first.output_dir, "candidate_pairs").is_empty()

    database = tmp_path / "lexical.duckdb"
    load_lexical_duckdb(
        first,
        database,
        duckdb_memory_limit_bytes=128 * 1024**2,
        duckdb_temp_directory=tmp_path / "duckdb-load-spill-1",
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        names = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        assert set(LEXICAL_CONVENIENCE_VIEWS).issubset(names)
        assert connection.execute("SELECT count(*) FROM lexical_metadata").fetchone() == (1,)
    load_lexical_duckdb(
        first,
        database,
        duckdb_memory_limit_bytes=128 * 1024**2,
        duckdb_temp_directory=tmp_path / "duckdb-load-spill-2",
    )


def _write_anchor_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    passage_root = tmp_path / "passages"
    benchmark_root = tmp_path / "benchmarks"
    oshb_root = tmp_path / "oshb"
    for root in (passage_root, benchmark_root, oshb_root):
        root.mkdir()
    (passage_root / "table-hashes.json").write_text(
        _canonical(
            {
                "table_counts": PASSAGE_COUNTS,
                "table_logical_sha256": PASSAGE_LOGICAL_HASHES,
            }
        ),
        encoding="utf-8",
    )
    (benchmark_root / "table-hashes.json").write_text(
        _canonical({"table_logical_sha256": BENCHMARK_LOGICAL_HASHES}), encoding="utf-8"
    )
    (oshb_root / "table-hashes.json").write_text(
        _canonical({"logical_table_sha256": OSHB_LOGICAL_HASHES}), encoding="utf-8"
    )
    tier1_path = tmp_path / "tier1.csv"
    tier1_path.write_bytes(Path("data/benchmarks/tier1_quotations.csv").read_bytes())
    database = tmp_path / "anchors.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            f"CREATE VIEW hebrew_tokens AS SELECT range token_id FROM range({HEBREW_TOKEN_COUNT})"
        )
        connection.execute(
            f"CREATE VIEW greek_tokens AS SELECT range token_id FROM range({GREEK_TOKEN_COUNT})"
        )
        connection.execute(
            """
            CREATE TABLE segmentation_metadata(
              segmentation_run_id VARCHAR, input_primary_identity_digests_json VARCHAR,
              input_surface_lemma_digests_json VARCHAR, input_analytical_digests_json VARCHAR,
              input_oshb_supplement_digests_json VARCHAR, table_counts_json VARCHAR,
              table_logical_hashes_json VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO segmentation_metadata VALUES (?,?,?,?,?,?,?)",
            [
                PASSAGE_RUN_ID,
                _canonical(CORPUS_IDENTITY_DIGESTS),
                _canonical(CORPUS_CONTENT_DIGESTS),
                _canonical(CORPUS_ANALYTICAL_DIGESTS),
                _canonical(OSHB_LOGICAL_HASHES),
                _canonical(PASSAGE_CONTENT_COUNTS),
                _canonical(PASSAGE_CONTENT_LOGICAL_HASHES),
            ],
        )
        connection.execute(
            """
            CREATE TABLE benchmark_metadata(
              benchmark_run_id VARCHAR, benchmark_version VARCHAR,
              source_archive_hashes_json VARCHAR, source_audit_json VARCHAR,
              tier1_header_sha256 VARCHAR, source_versions_json VARCHAR,
              passage_input_run_id VARCHAR, passage_logical_hashes_json VARCHAR,
              logical_table_hashes_json VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO benchmark_metadata VALUES (?,?,?,?,?,?,?,?,?)",
            [
                BENCHMARK_RUN_ID,
                BENCHMARK_VERSION,
                _canonical({"openbible-cross-references": OPENBIBLE_ARCHIVE_SHA256}),
                _canonical({"canonical_stream_sha256": OPENBIBLE_CANONICAL_STREAM_SHA256}),
                TIER1_HEADER_SHA256,
                _canonical({"openbible-cross-references": OPENBIBLE_SNAPSHOT}),
                PASSAGE_RUN_ID,
                _canonical(PASSAGE_LOGICAL_HASHES),
                _canonical(BENCHMARK_CONTENT_LOGICAL_HASHES),
            ],
        )
    return database, passage_root, benchmark_root, tier1_path, oshb_root


def test_anchor_verification_checks_snapshot_and_every_fixed_digest(tmp_path: Path) -> None:
    database, passage_root, benchmark_root, tier1_path, oshb_root = _write_anchor_fixture(tmp_path)
    result = verify_upstream_anchors(
        database_path=database,
        passage_root=passage_root,
        benchmark_root=benchmark_root,
        tier1_path=tier1_path,
        oshb_root=oshb_root,
        duckdb_memory_limit_bytes=128 * 1024**2,
        duckdb_temp_directory=tmp_path / "anchor-spill",
    )
    assert result.openbible_snapshot == OPENBIBLE_SNAPSHOT
    assert result.tier1_row_count == 0

    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE benchmark_metadata SET source_versions_json=?",
            [_canonical({"openbible-cross-references": "changed"})],
        )
    with pytest.raises(LexicalAnchorError, match="OpenBible snapshot"):
        verify_upstream_anchors(
            database_path=database,
            passage_root=passage_root,
            benchmark_root=benchmark_root,
            tier1_path=tier1_path,
            oshb_root=oshb_root,
            duckdb_memory_limit_bytes=128 * 1024**2,
            duckdb_temp_directory=tmp_path / "anchor-spill-second",
        )
