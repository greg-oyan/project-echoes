"""Optional regression gate for a locally acquired full MACULA Hebrew corpus."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import pytest

from echoes.corpus.hebrew import validate_existing_hebrew_corpus
from echoes.corpus.validation import corpus_identity_digest

# Recorded in docs/experiment-log.md by the pre-Milestone-3 amendment run and
# reconfirmed by the canonical-byte checksum remediation: token identity must
# not change when only acquisition byte handling changes.
EXPECTED_IDENTITY_DIGEST = "91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6"
EXPECTED_TOKEN_COUNT = 475_911

FULL_CORPUS = pytest.mark.skipif(
    os.environ.get("ECHOES_RUN_FULL_CORPUS") != "1",
    reason="set ECHOES_RUN_FULL_CORPUS=1 after local governed acquisition and ingestion",
)


@pytest.mark.full_corpus
@FULL_CORPUS
def test_full_hebrew_corpus_passes_milestone_two_gate() -> None:
    report = validate_existing_hebrew_corpus()

    assert report.passed
    assert report.error_count == 0
    assert report.total_source_records == EXPECTED_TOKEN_COUNT
    assert report.total_tokens == EXPECTED_TOKEN_COUNT
    assert report.book_count == 39
    assert report.chapter_count == 929


@pytest.mark.full_corpus
@FULL_CORPUS
def test_full_hebrew_corpus_identity_digest_is_stable() -> None:
    tokens = pl.read_parquet(
        Path("data/processed/macula-hebrew/25.08.11/tokens.parquet"),
        columns=["position_in_corpus", "token_id", "source_record_id", "source_word_id"],
    )

    assert tokens.height == EXPECTED_TOKEN_COUNT
    assert corpus_identity_digest(tokens) == EXPECTED_IDENTITY_DIGEST


@pytest.mark.full_corpus
@FULL_CORPUS
def test_full_greek_corpus_passes_milestone_three_gate() -> None:
    from echoes.corpus.greek import validate_existing_greek_corpus

    report = validate_existing_greek_corpus()

    assert report.passed
    assert report.error_count == 0
    assert report.total_source_records == 137_779
    assert report.total_tokens == 137_779
    assert report.book_count == 27
    assert report.chapter_count == 260


@pytest.mark.full_corpus
@FULL_CORPUS
def test_full_unified_tables_query_both_corpora() -> None:
    import duckdb

    with duckdb.connect("data/processed/project_echoes.duckdb", read_only=True) as connection:
        row = connection.execute(
            "SELECT count(*), count(DISTINCT token_id), "
            "count(*) FILTER (WHERE corpus = 'hebrew'), "
            "count(*) FILTER (WHERE corpus = 'greek') "
            "FROM unified_tokens"
        ).fetchone()
        assert row is not None
        total, distinct_ids, hebrew_count, greek_count = (int(value) for value in row)
        assert hebrew_count == EXPECTED_TOKEN_COUNT
        assert greek_count == 137_779
        assert total == hebrew_count + greek_count
        assert distinct_ids == total
