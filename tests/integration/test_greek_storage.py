"""Greek storage, unified cross-corpus, duplicate-prevention, and rerun tests."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from echoes.corpus.greek_storage import (
    CorpusStorageError,
    greek_corpus_summary,
    load_greek_duckdb,
    write_processed_greek_corpus,
)
from echoes.corpus.greek_validation import validate_greek_corpus
from echoes.corpus.storage import load_hebrew_duckdb, write_processed_corpus
from echoes.ingest.macula_greek import GreekAdapterResult
from echoes.ingest.macula_hebrew import AdapterResult
from echoes.manifest import sha256_file
from echoes.manifests.sources import SourceManifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GREEK_FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "macula_greek"
NORMALIZATION_PATH = PROJECT_ROOT / "config" / "normalization.yaml"


def _greek_raw_hashes() -> dict[str, str]:
    return {
        path.relative_to(GREEK_FIXTURE_ROOT).as_posix(): sha256_file(path)
        for path in GREEK_FIXTURE_ROOT.rglob("*.xml")
    }


def test_greek_storage_roundtrip_and_summary(stored_greek_fixture_corpus) -> None:
    summary = greek_corpus_summary(stored_greek_fixture_corpus.database)

    assert summary.total_tokens == 7
    assert summary.total_books == 1
    assert summary.tokens_by_book == {"JUD": 7}
    assert summary.missing_lemma_count == 0
    assert summary.missing_morphology_count == 0
    assert summary.elided_count == 1
    assert summary.punctuation_bearing_count == 2
    assert summary.ingestion_run_id.startswith("greek-")


def test_greek_rerun_is_deterministic_and_transactional(
    tmp_path: Path,
    greek_adapter_result: GreekAdapterResult,
    greek_source: SourceManifest,
) -> None:
    output_dir = tmp_path / "processed" / "greek"
    database = tmp_path / "processed" / "greek.duckdb"
    kwargs = {
        "source": greek_source,
        "normalization_config_hash": sha256_file(NORMALIZATION_PATH),
        "raw_file_hashes": _greek_raw_hashes(),
    }
    first = write_processed_greek_corpus(greek_adapter_result, output_dir=output_dir, **kwargs)
    load_greek_duckdb(first, database)

    with pytest.raises(CorpusStorageError, match="refusing to overwrite"):
        write_processed_greek_corpus(greek_adapter_result, output_dir=output_dir, **kwargs)

    second = write_processed_greek_corpus(
        greek_adapter_result, output_dir=output_dir, force=True, **kwargs
    )
    load_greek_duckdb(second, database)

    assert first.run_id == second.run_id
    assert first.file_hashes == second.file_hashes
    assert first.logical_hashes == second.logical_hashes
    with duckdb.connect(str(database), read_only=True) as connection:
        count_row = connection.execute("SELECT count(*) FROM greek_tokens").fetchone()
        assert count_row is not None and int(count_row[0]) == 7
        distinct_row = connection.execute(
            "SELECT count(DISTINCT token_id) FROM greek_tokens"
        ).fetchone()
        assert distinct_row is not None and int(distinct_row[0]) == 7


def test_greek_validation_passes_on_fixture(
    stored_greek_fixture_corpus,
    normalization_config,
) -> None:
    report = validate_greek_corpus(
        stored_greek_fixture_corpus.output_dir,
        database_path=stored_greek_fixture_corpus.database,
        normalization=normalization_config.greek,
        expected_books=1,
        expected_chapters=1,
        expected_tokens=7,
    )

    assert report.corpus == "greek"
    assert report.passed
    assert report.error_count == 0
    assert report.total_tokens == 7
    assert report.coverage["elided_tokens"] == 1


def test_unified_view_queries_both_corpora(
    tmp_path: Path,
    adapter_result: AdapterResult,
    macula_source: SourceManifest,
    greek_adapter_result: GreekAdapterResult,
    greek_source: SourceManifest,
) -> None:
    database = tmp_path / "unified.duckdb"
    hebrew_processed = write_processed_corpus(
        adapter_result,
        source=macula_source,
        normalization_config_hash=sha256_file(NORMALIZATION_PATH),
        raw_file_hashes={"fixture.xml": "0" * 64},
        output_dir=tmp_path / "hebrew",
    )
    load_hebrew_duckdb(hebrew_processed, database)
    greek_processed = write_processed_greek_corpus(
        greek_adapter_result,
        source=greek_source,
        normalization_config_hash=sha256_file(NORMALIZATION_PATH),
        raw_file_hashes=_greek_raw_hashes(),
        output_dir=tmp_path / "greek",
    )
    load_greek_duckdb(greek_processed, database)

    with duckdb.connect(str(database), read_only=True) as connection:
        corpora = dict(
            connection.execute(
                "SELECT corpus, count(*) FROM unified_tokens GROUP BY corpus ORDER BY corpus"
            ).fetchall()
        )
        assert set(corpora) == {"hebrew", "greek"}
        assert corpora["greek"] == 7
        total_row = connection.execute(
            "SELECT count(*), count(DISTINCT token_id) FROM unified_tokens"
        ).fetchone()
        assert total_row is not None
        assert int(total_row[0]) == int(total_row[1])
        sources = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT source_id FROM unified_tokens"
            ).fetchall()
        }
        assert sources == {"macula-hebrew", "macula-greek"}
        versions = connection.execute(
            "SELECT corpus, count(*) FROM corpus_schema_versions GROUP BY corpus"
        ).fetchall()
        assert dict(versions) == {"hebrew": 1, "greek": 1}
        # A cross-corpus lemma-shaped query runs against the shared columns.
        cross = connection.execute(
            "SELECT corpus, count(DISTINCT lemma) FROM unified_tokens "
            "WHERE lemma IS NOT NULL GROUP BY corpus"
        ).fetchall()
        assert len(cross) == 2


def test_hebrew_reload_after_greek_keeps_cross_corpus_artifacts(
    tmp_path: Path,
    adapter_result: AdapterResult,
    macula_source: SourceManifest,
    greek_adapter_result: GreekAdapterResult,
    greek_source: SourceManifest,
) -> None:
    database = tmp_path / "unified.duckdb"
    greek_processed = write_processed_greek_corpus(
        greek_adapter_result,
        source=greek_source,
        normalization_config_hash=sha256_file(NORMALIZATION_PATH),
        raw_file_hashes=_greek_raw_hashes(),
        output_dir=tmp_path / "greek",
    )
    load_greek_duckdb(greek_processed, database)
    hebrew_processed = write_processed_corpus(
        adapter_result,
        source=macula_source,
        normalization_config_hash=sha256_file(NORMALIZATION_PATH),
        raw_file_hashes={"fixture.xml": "0" * 64},
        output_dir=tmp_path / "hebrew",
    )
    load_hebrew_duckdb(hebrew_processed, database)

    with duckdb.connect(str(database), read_only=True) as connection:
        versions = dict(
            connection.execute(
                "SELECT corpus, count(*) FROM corpus_schema_versions GROUP BY corpus"
            ).fetchall()
        )
        assert versions == {"hebrew": 1, "greek": 1}
        row = connection.execute("SELECT count(*) FROM unified_tokens").fetchone()
        assert row is not None and int(row[0]) > 7
