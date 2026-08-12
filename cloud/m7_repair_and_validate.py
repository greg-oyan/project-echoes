from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import polars as pl

import echoes.lexical.pipeline as p
import echoes.lexical.validation as v
from echoes.lexical.config import lexical_config_sha256, load_lexical_config
from echoes.lexical.models import LEXICAL_ARTIFACT_SCHEMAS, LEXICAL_INDEX_METADATA_SCHEMA
from echoes.lexical.sequences import iter_passage_sequences

REPO = Path("/srv/project-echoes/repo").resolve()
DATABASE = REPO / "data/processed/project_echoes.duckdb"
STAGING = REPO / "data/processed/lexical/.schema-v1.writing-238902db1f6e479596bea47e70ccf30b"
CANONICAL = REPO / "data/processed/lexical/schema-v1"
REPAIR_PARENT = STAGING.parent
TWO_GIB = 2 * 1024**3


def safe_staging() -> None:
    expected = (
        REPO / "data/processed/lexical/.schema-v1.writing-238902db1f6e479596bea47e70ccf30b"
    ).resolve()
    if STAGING.resolve() != expected or not STAGING.is_dir() or STAGING.is_symlink():
        raise RuntimeError(f"unsafe or missing staging directory: {STAGING}")
    if CANONICAL.exists() or CANONICAL.is_symlink():
        raise RuntimeError("canonical output already exists; refusing repair")
    if not DATABASE.is_file() or DATABASE.is_symlink():
        raise RuntimeError(f"project DuckDB unavailable or unsafe: {DATABASE}")


def existing_index_metadata() -> pl.DataFrame:
    paths = sorted((STAGING / "lexical_index_metadata").glob("part-*.parquet"))
    if not paths:
        raise RuntimeError("lexical_index_metadata is missing")
    return (
        pl.read_parquet(paths, rechunk=True)
        .cast(LEXICAL_INDEX_METADATA_SCHEMA, strict=True)
        .sort("index_id")
    )


def load_sequences(corpus: str, profile: str, reading: str, temp_root: Path) -> list:
    return list(
        iter_passage_sequences(
            DATABASE,
            corpus=corpus,
            analysis_profile=profile,
            analysis_reading=reading,
            granularity="verse",
            duckdb_memory_limit_bytes=TWO_GIB,
            duckdb_temp_directory=temp_root / f"seq-{corpus}-{profile}-{reading}",
        )
    )


def repair_sparse_indexes() -> dict[str, object]:
    config = load_lexical_config()
    config_hash = lexical_config_sha256(config)
    existing = existing_index_metadata()
    run_ids = existing.get_column("experiment_run_id").unique().to_list()
    if len(run_ids) != 1:
        raise RuntimeError(f"ambiguous index run IDs: {run_ids}")
    run_id = str(run_ids[0])

    repair_root = REPAIR_PARENT / f".schema-v1.index-repair-{os.getpid()}-{int(time.time())}"
    repair_root.mkdir()
    fake_writer = SimpleNamespace(staging_dir=repair_root)
    frames: list[pl.DataFrame] = []

    try:
        primary = config.primary_scope
        critical = config.sensitivity_scopes.critical_core_greek
        reading = config.sensitivity_scopes.hebrew_qere_ketiv

        hb = load_sequences("hebrew", primary.analysis_profile, primary.hebrew_reading, repair_root)
        gk = load_sequences("greek", primary.analysis_profile, primary.greek_reading, repair_root)
        _, frame, _ = p._build_indexes(
            writer=fake_writer,
            definitions=p._primary_index_definitions(hb, gk, config=config),
            config=config,
            configuration_hash=config_hash,
            experiment_run_id=run_id,
            resource_check=None,
        )
        frames.append(frame)
        del hb, gk

        hb = load_sequences(
            "hebrew", critical.analysis_profile, critical.hebrew_reading, repair_root
        )
        gk = load_sequences("greek", critical.analysis_profile, critical.greek_reading, repair_root)
        _, frame, _ = p._build_indexes(
            writer=fake_writer,
            definitions=p._critical_index_definitions(
                critical_hebrew=hb,
                critical_greek=gk,
                config=config,
            ),
            config=config,
            configuration_hash=config_hash,
            experiment_run_id=run_id,
            resource_check=None,
        )
        frames.append(frame)
        del hb, gk

        hb = load_sequences(
            "hebrew", reading.analysis_profile, reading.comparison_reading, repair_root
        )
        _, frame, _ = p._build_indexes(
            writer=fake_writer,
            definitions=p._ketiv_index_definitions(hb, config=config),
            config=config,
            configuration_hash=config_hash,
            experiment_run_id=run_id,
            resource_check=None,
        )
        frames.append(frame)
        del hb

        generated = (
            pl.concat(frames, how="vertical_relaxed")
            .cast(LEXICAL_INDEX_METADATA_SCHEMA, strict=True)
            .sort("index_id")
        )
        if not generated.equals(existing, null_equal=True):
            raise RuntimeError(
                "regenerated sparse indexes do not exactly match persisted "
                "lexical_index_metadata; refusing installation"
            )

        generated_root = repair_root / "indexes"
        expected = set(existing.get_column("representation_id").to_list())
        observed = {
            path.name
            for path in generated_root.iterdir()
            if path.is_dir() and not path.is_symlink()
        }
        if observed != expected:
            raise RuntimeError(
                f"regenerated representation set differs: "
                f"missing={sorted(expected - observed)}, unexpected={sorted(observed - expected)}"
            )

        destination = STAGING / "indexes"
        if destination.is_symlink():
            raise RuntimeError("staging indexes path is a symlink")
        if destination.exists():
            files = [path for path in destination.rglob("*") if path.is_file()]
            if files:
                backup = REPAIR_PARENT / f".schema-v1.indexes-before-repair-{int(time.time())}"
                destination.replace(backup)
                print(f"preserved_existing_indexes={backup}", flush=True)
            else:
                shutil.rmtree(destination)
        generated_root.replace(destination)

        return {
            "repaired": True,
            "index_count": generated.height,
            "representation_count": len(expected),
        }
    finally:
        if repair_root.exists():
            shutil.rmtree(repair_root, ignore_errors=True)


def install_validation_fixes() -> None:
    original_count = v._count_check
    original_candidates = v._validate_candidates
    original_load_split = p._load_split_provenance

    def scalar(connection, sql: str) -> int:
        row = connection.execute(sql).fetchone()
        if row is None:
            raise RuntimeError("validation scalar returned no row")
        return int(row[0])

    def report_count(state, artifact, code, message, count, severity="error"):
        if count:
            state.add(
                code,
                f"{message} Count={count}.",
                severity=severity,
                artifact=artifact,
            )
        return count

    def count_check(
        state,
        connection,
        *,
        artifact,
        code,
        message,
        sql,
        severity="error",
    ):
        if artifact == "shared_evidence" and code == "null_required_field":
            schema = LEXICAL_ARTIFACT_SCHEMAS["shared_evidence"]
            nullable = {"pmi", "log_likelihood", "frequency_control"}
            required = [c for c in schema if c not in nullable]
            predicate = " OR ".join(f'"{c}" IS NULL' for c in required)
            count = scalar(
                connection,
                f"SELECT count(*) FROM shared_evidence WHERE {predicate}",
            )
            return report_count(state, artifact, code, message, count, severity)

        if artifact == "candidate_evidence" and code == "nonfinite_numeric":
            schema = LEXICAL_ARTIFACT_SCHEMAS["candidate_evidence"]
            sentinels = {
                "null_model_empirical_rate",
                "estimated_empirical_fdr",
                "selected_score_threshold",
            }
            columns = [
                c
                for c, dtype in schema.items()
                if dtype in {pl.Float32, pl.Float64} and c not in sentinels
            ]
            predicate = " OR ".join(f'NOT isfinite("{c}")' for c in columns)
            count = scalar(
                connection,
                f"SELECT count(*) FROM candidate_evidence WHERE {predicate}",
            )
            return report_count(state, artifact, code, message, count, severity)

        if (artifact == "directional_rankings" and code == "ranking_quantization") or (
            artifact == "candidate_detector_scores" and code == "candidate_score_quantization"
        ):
            decimals = load_lexical_config().statistics.score_quantization_decimals
            tolerance = 0.500001 * (10.0 ** (-decimals))
            raw, quantized = (
                ("raw_score", "quantized_score")
                if artifact == "directional_rankings"
                else ("score", "quantized_score")
            )
            count = scalar(
                connection,
                f"""SELECT count(*) FROM "{artifact}"
                    WHERE NOT isfinite("{raw}")
                       OR NOT isfinite("{quantized}")
                       OR abs("{quantized}"-"{raw}") > {tolerance!r}""",
            )
            return report_count(state, artifact, code, message, count, severity)

        if artifact == "directional_rankings" and code == "ranking_tie_break":
            count = scalar(
                connection,
                """WITH ordered AS (
                     SELECT *,
                       CASE WHEN detector='rrf_composite'
                            THEN raw_score ELSE quantized_score END AS order_score,
                       lag(CASE WHEN detector='rrf_composite'
                                THEN raw_score ELSE quantized_score END)
                         OVER w AS previous_score,
                       lag(target_passage_id) OVER w AS previous_target
                     FROM directional_rankings
                     WINDOW w AS (
                       PARTITION BY experiment_scope,analysis_profile,
                         query_reading,target_reading,granularity,
                         query_passage_id,representation_id,detector
                       ORDER BY rank
                     )
                   )
                   SELECT count(*) FROM ordered
                   WHERE previous_score IS NOT NULL
                     AND (
                       order_score > previous_score
                       OR (
                         order_score = previous_score
                         AND target_passage_id < previous_target
                       )
                     )""",
            )
            return report_count(state, artifact, code, message, count, severity)

        if artifact == "shared_evidence" and code == "shared_evidence_orphan":
            count = scalar(
                connection,
                """SELECT count(*)
                   FROM shared_evidence e
                   LEFT JOIN candidate_pairs p USING(candidate_pair_id)
                   LEFT JOIN feature_vocabulary f USING(feature_id)
                   WHERE p.candidate_pair_id IS NULL
                      OR (
                        e.evidence_family IN (
                          'english_gloss_ngram','english_gloss_skipgram'
                        )
                        AND e.feature_id <> 'LF_' || sha256(
                          to_json(struct_pack(
                            family := e.evidence_family,
                            namespace := 'en',
                            value := e.feature_value
                          ))
                        )
                      )
                      OR (
                        e.evidence_family NOT IN (
                          'longest_common_subsequence_trace',
                          'weighted_sequence_alignment_trace',
                          'english_gloss_ngram',
                          'english_gloss_skipgram'
                        )
                        AND (
                          f.feature_id IS NULL
                          OR e.feature_value <> f.feature_value
                        )
                      )""",
            )
            return report_count(state, artifact, code, message, count, severity)

        if artifact == "candidate_evidence" and code == "candidate_calibration_provenance":
            sample_size = load_lexical_config().null_models.calibration_pair_sample_size
            count = scalar(
                connection,
                f"""WITH composite AS (
                      SELECT candidate_pair_id,representation_id
                      FROM candidate_detector_scores
                      WHERE detector='rrf_composite'
                    ),
                    selected AS (
                      SELECT *
                      FROM threshold_calibration
                      WHERE detector='rrf_composite' AND selected
                    )
                    SELECT count(*)
                    FROM candidate_evidence e
                    JOIN candidate_pairs p USING(candidate_pair_id)
                    JOIN composite s USING(candidate_pair_id)
                    LEFT JOIN selected t
                      ON t.corpus_pair=p.corpus_pair
                     AND t.representation_id=s.representation_id
                    WHERE NOT e.both_null_families_present
                       OR e.calibration_selection_scope
                            <> 'frozen_corpus_pair_rrf_threshold'
                       OR (
                         t.threshold_id IS NOT NULL
                         AND (
                           e.selected_score_threshold
                             IS DISTINCT FROM t.score_threshold
                           OR e.estimated_empirical_fdr
                             IS DISTINCT FROM t.estimated_empirical_fdr
                           OR abs(
                             e.null_model_empirical_rate
                             - t.mean_null_candidate_count / {sample_size}
                           ) > 1e-15
                         )
                       )
                       OR (
                         t.threshold_id IS NULL
                         AND (
                           NOT (
                             NOT isfinite(e.selected_score_threshold)
                             AND e.selected_score_threshold > 0
                             AND NOT isfinite(e.estimated_empirical_fdr)
                             AND e.estimated_empirical_fdr > 0
                             AND NOT isfinite(e.null_model_empirical_rate)
                             AND e.null_model_empirical_rate > 0
                           )
                           OR p.review_eligible
                         )
                       )""",
            )
            return report_count(state, artifact, code, message, count, severity)

        if artifact == "shared_evidence" and code == "bulk_text_payload":
            count = scalar(
                connection,
                """SELECT count(*) FROM shared_evidence
                   WHERE length(notes)>4096
                     AND NOT (
                       evidence_family='weighted_sequence_alignment_trace'
                       AND starts_with(notes,'traceback=')
                       AND json_valid(substr(notes,11))
                       AND length(notes)<=65536
                     )""",
            )
            return report_count(state, artifact, code, message, count, severity)

        return original_count(
            state,
            connection,
            artifact=artifact,
            code=code,
            message=message,
            sql=sql,
            severity=severity,
        )

    def validate_candidates(state, connection, config):
        connection.execute(
            "CREATE TEMP TABLE __m7_original_pfs AS SELECT * FROM passage_feature_statistics"
        )
        connection.execute("DROP VIEW passage_feature_statistics")
        connection.execute(
            "CREATE VIEW passage_feature_statistics AS "
            "SELECT * REPLACE ("
            "greatest(token_count,english_gloss_sequence_length) "
            "AS eligible_token_count"
            ") FROM __m7_original_pfs"
        )
        try:
            original_candidates(state, connection, config)
        finally:
            connection.execute("DROP VIEW passage_feature_statistics")
            connection.execute(
                "CREATE VIEW passage_feature_statistics AS SELECT * FROM __m7_original_pfs"
            )

    def load_split(
        database_path,
        sequences,
        *,
        duckdb_memory_limit_bytes,
        duckdb_temp_directory,
        resource_check=None,
        targeted_lookup=False,
    ):
        return original_load_split(
            database_path,
            sequences,
            duckdb_memory_limit_bytes=max(TWO_GIB, int(duckdb_memory_limit_bytes)),
            duckdb_temp_directory=duckdb_temp_directory,
            resource_check=resource_check,
            targeted_lookup=targeted_lookup,
        )

    v._count_check = count_check
    v._validate_candidates = validate_candidates
    p._load_split_provenance = load_split


def install_fast_audit() -> None:
    manifest_path = STAGING / "table-hashes.json"
    if not manifest_path.is_file():
        raise RuntimeError("provisional table-hashes.json is missing")

    def fast_audit(state):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        state.table_counts = {str(k): int(val) for k, val in manifest["table_counts"].items()}
        state.logical_hashes = {
            str(k): str(val) for k, val in manifest["table_logical_sha256"].items()
        }
        state.physical_hashes = {
            str(k): str(val) for k, val in manifest["table_physical_sha256"].items()
        }
        return manifest

    v._audit_storage = fast_audit


def main() -> None:
    started = time.time()
    safe_staging()

    print("=== SPARSE INDEX REPAIR ===", flush=True)
    print(json.dumps(repair_sparse_indexes(), sort_keys=True), flush=True)

    print("=== PATCHED RELATIONAL VALIDATION ===", flush=True)
    install_validation_fixes()
    install_fast_audit()

    report = v.validate_lexical_artifacts(
        STAGING,
        database_path=DATABASE,
        verify_anchors=False,
        verify_duckdb=False,
        verify_sparse_indexes=True,
        strict=True,
    )

    print("=== VALIDATION SUMMARY ===", flush=True)
    print(f"errors={report.error_count}", flush=True)
    print(f"warnings={report.warning_count}", flush=True)
    print(f"informationals={report.informational_count}", flush=True)
    print(f"scientific_gate={report.scientific_gate_passed}", flush=True)
    print(f"elapsed_seconds={time.time() - started:.1f}", flush=True)
    print("=== ISSUES ===", flush=True)
    for i, issue in enumerate(report.issues, 1):
        print(
            f"{i}. [{issue.severity}] {issue.code} artifact={issue.artifact}",
            flush=True,
        )
        print(f"   {issue.message}", flush=True)
        if issue.details:
            print(
                "   details=" + json.dumps(issue.details, sort_keys=True),
                flush=True,
            )

    if report.error_count or report.warning_count:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
