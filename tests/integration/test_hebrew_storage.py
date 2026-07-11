"""Parquet, DuckDB, rerun, summary, validation, and determinism integration tests."""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from echoes.corpus.models import CANONICAL_TOKEN_COLUMNS
from echoes.corpus.storage import (
    PARQUET_FILES,
    corpus_summary,
    load_hebrew_duckdb,
    write_processed_corpus,
)
from echoes.corpus.validation import compare_processed_corpora, validate_hebrew_corpus
from echoes.ingest.macula_hebrew import AdapterResult, parse_macula_hebrew_nodes
from echoes.manifest import sha256_file
from echoes.manifests.sources import SourceManifest
from echoes.settings import NormalizationConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "macula_hebrew"


def _raw_hashes() -> dict[str, str]:
    return {
        path.relative_to(FIXTURE_ROOT).as_posix(): sha256_file(path)
        for path in FIXTURE_ROOT.rglob("*.xml")
    }


def test_parquet_schema_and_duckdb_tables_are_complete(stored_fixture_corpus: object) -> None:
    output_dir = stored_fixture_corpus.output_dir  # type: ignore[attr-defined]
    database = stored_fixture_corpus.database  # type: ignore[attr-defined]
    tokens = pl.read_parquet(output_dir / PARQUET_FILES["tokens"])

    assert tuple(tokens.columns) == CANONICAL_TOKEN_COLUMNS
    analysis_tokens = pl.read_parquet(output_dir / PARQUET_FILES["analysis_tokens"])

    assert tokens.height == 9
    assert analysis_tokens.height == 8
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        assert {
            "hebrew_tokens",
            "hebrew_analysis_tokens",
            "hebrew_analysis_stream",
            "hebrew_books",
            "hebrew_source_records",
            "hebrew_ingestion_issues",
            "hebrew_corpus_metadata",
            "corpus_schema_versions",
        } <= tables
        preserved_readings = connection.execute(
            "SELECT variant_type FROM hebrew_tokens "
            "WHERE variant_group_id IS NOT NULL ORDER BY variant_type"
        ).fetchall()
        analysis_readings = connection.execute(
            "SELECT variant_type FROM hebrew_analysis_stream WHERE variant_group_id IS NOT NULL"
        ).fetchall()
        analysis_positions = connection.execute(
            "SELECT min(analysis_position_in_corpus), "
            "max(analysis_position_in_corpus), count(*) "
            "FROM hebrew_analysis_stream"
        ).fetchone()
    assert preserved_readings == [("ketiv",), ("qere",)]
    assert analysis_readings == [("qere",)]
    assert analysis_positions == (1, 8, 8)


def test_fixture_corpus_summary_reports_required_counts(stored_fixture_corpus: object) -> None:
    summary = corpus_summary(stored_fixture_corpus.database)  # type: ignore[attr-defined]

    assert summary.total_tokens == 9
    assert summary.total_books == 2
    assert summary.hebrew_tokens == 7
    assert summary.aramaic_tokens == 2
    assert summary.tokens_by_book == {"GEN": 7, "EZR": 2}
    assert summary.variant_count == 2
    assert summary.ketiv_qere_count == 2
    assert summary.punctuation_count == 1


def test_fixture_validation_passes_and_reports_measured_absence(
    stored_fixture_corpus: object,
    normalization_config: NormalizationConfig,
) -> None:
    report = validate_hebrew_corpus(
        stored_fixture_corpus.output_dir,  # type: ignore[attr-defined]
        database_path=stored_fixture_corpus.database,  # type: ignore[attr-defined]
        normalization=normalization_config.hebrew,
        expected_books=2,
        expected_chapters=2,
        expected_tokens=9,
        require_full_coverage=False,
    )

    assert report.passed
    assert report.error_count == 0
    assert report.completeness["missing_lemma"] == 6
    assert report.completeness["missing_morphology"] == 1
    assert report.coverage["aramaic_tokens"] == 2


def test_validation_severity_fails_only_for_errors(
    stored_fixture_corpus: object,
    normalization_config: NormalizationConfig,
) -> None:
    report = validate_hebrew_corpus(
        stored_fixture_corpus.output_dir,  # type: ignore[attr-defined]
        database_path=stored_fixture_corpus.database,  # type: ignore[attr-defined]
        normalization=normalization_config.hebrew,
        expected_books=2,
        expected_chapters=2,
        expected_tokens=10,
        require_full_coverage=False,
    )

    assert not report.passed
    assert any(issue.code == "token-count" for issue in report.issues)


def test_independent_runs_have_identical_parquet_and_logical_hashes(
    tmp_path: Path,
    adapter_result: AdapterResult,
    macula_source: SourceManifest,
) -> None:
    config_hash = sha256_file(PROJECT_ROOT / "config" / "normalization.yaml")
    first = write_processed_corpus(
        adapter_result,
        source=macula_source,
        normalization_config_hash=config_hash,
        raw_file_hashes=_raw_hashes(),
        output_dir=tmp_path / "run-one",
    )
    second = write_processed_corpus(
        adapter_result,
        source=macula_source,
        normalization_config_hash=config_hash,
        raw_file_hashes=_raw_hashes(),
        output_dir=tmp_path / "run-two",
    )

    assert compare_processed_corpora(first, second) == []


def test_configuration_hash_changes_run_identity(
    tmp_path: Path,
    adapter_result: AdapterResult,
    macula_source: SourceManifest,
) -> None:
    first = write_processed_corpus(
        adapter_result,
        source=macula_source,
        normalization_config_hash="a" * 64,
        raw_file_hashes=_raw_hashes(),
        output_dir=tmp_path / "first",
    )
    second = write_processed_corpus(
        adapter_result,
        source=macula_source,
        normalization_config_hash="b" * 64,
        raw_file_hashes=_raw_hashes(),
        output_dir=tmp_path / "second",
    )

    assert first.run_id != second.run_id
    assert "ingestion run IDs differ" in compare_processed_corpora(first, second)


def test_analysis_selection_leaves_persisted_base_token_artifact_unchanged(
    tmp_path: Path,
    macula_source: SourceManifest,
    normalization_config: NormalizationConfig,
) -> None:
    qere = parse_macula_hebrew_nodes(
        FIXTURE_ROOT,
        source=macula_source,
        normalization=normalization_config.hebrew,
        analysis_reading="qere",
    )
    ketiv = parse_macula_hebrew_nodes(
        FIXTURE_ROOT,
        source=macula_source,
        normalization=normalization_config.hebrew,
        analysis_reading="ketiv",
    )
    qere_processed = write_processed_corpus(
        qere,
        source=macula_source,
        normalization_config_hash="a" * 64,
        raw_file_hashes=_raw_hashes(),
        output_dir=tmp_path / "qere",
    )
    ketiv_processed = write_processed_corpus(
        ketiv,
        source=macula_source,
        normalization_config_hash="b" * 64,
        raw_file_hashes=_raw_hashes(),
        output_dir=tmp_path / "ketiv",
    )

    token_filename = PARQUET_FILES["tokens"]
    assert qere_processed.file_hashes[token_filename] == ketiv_processed.file_hashes[token_filename]
    assert qere_processed.logical_hashes["tokens"] == ketiv_processed.logical_hashes["tokens"]
    assert (
        qere_processed.logical_hashes["analysis_tokens"]
        != ketiv_processed.logical_hashes["analysis_tokens"]
    )


def test_duckdb_transactional_rerun_prevents_duplicates(stored_fixture_corpus: object) -> None:
    processed = stored_fixture_corpus.processed  # type: ignore[attr-defined]
    database = stored_fixture_corpus.database  # type: ignore[attr-defined]

    load_hebrew_duckdb(processed, database)
    load_hebrew_duckdb(processed, database)

    with duckdb.connect(str(database), read_only=True) as connection:
        token_count = connection.execute("SELECT count(*) FROM hebrew_tokens").fetchone()
        distinct_count = connection.execute(
            "SELECT count(DISTINCT token_id) FROM hebrew_tokens"
        ).fetchone()
    assert token_count == (9,)
    assert distinct_count == (9,)


def test_hash_validation_detects_modified_parquet(
    stored_fixture_corpus: object,
    normalization_config: NormalizationConfig,
) -> None:
    output_dir = stored_fixture_corpus.output_dir  # type: ignore[attr-defined]
    tokens_path = output_dir / PARQUET_FILES["tokens"]
    tokens = pl.read_parquet(tokens_path).with_columns(
        pl.when(pl.col("position_in_corpus") == 1)
        .then(pl.lit("changed"))
        .otherwise(pl.col("normalized_form"))
        .alias("normalized_form")
    )
    tokens.write_parquet(tokens_path)

    report = validate_hebrew_corpus(
        output_dir,
        database_path=stored_fixture_corpus.database,  # type: ignore[attr-defined]
        normalization=normalization_config.hebrew,
        expected_books=2,
        expected_chapters=2,
        expected_tokens=9,
        require_full_coverage=False,
    )

    assert not report.passed
    assert {issue.code for issue in report.issues} >= {
        "parquet-hash-mismatch",
        "logical-hash-mismatch",
        "nondeterministic-normalization",
    }
