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
from echoes.ingest.macula_hebrew import AdapterResult
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
    assert tokens.height == 8
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        assert {
            "hebrew_tokens",
            "hebrew_books",
            "hebrew_source_records",
            "hebrew_ingestion_issues",
            "hebrew_corpus_metadata",
            "corpus_schema_versions",
        } <= tables


def test_fixture_corpus_summary_reports_required_counts(stored_fixture_corpus: object) -> None:
    summary = corpus_summary(stored_fixture_corpus.database)  # type: ignore[attr-defined]

    assert summary.total_tokens == 8
    assert summary.total_books == 2
    assert summary.hebrew_tokens == 6
    assert summary.aramaic_tokens == 2
    assert summary.tokens_by_book == {"GEN": 6, "EZR": 2}
    assert summary.variant_count == 1
    assert summary.ketiv_qere_count == 1
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
        expected_tokens=8,
        require_full_coverage=False,
    )

    assert report.passed
    assert report.error_count == 0
    assert report.completeness["missing_lemma"] == 5
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
        expected_tokens=9,
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
    assert token_count == (8,)
    assert distinct_count == (8,)


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
        expected_tokens=8,
        require_full_coverage=False,
    )

    assert not report.passed
    assert {issue.code for issue in report.issues} >= {
        "parquet-hash-mismatch",
        "logical-hash-mismatch",
        "nondeterministic-normalization",
    }
