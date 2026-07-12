"""Optional regression gate for a locally acquired full MACULA Hebrew corpus."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import pytest

from echoes.corpus.hebrew import validate_existing_hebrew_corpus
from echoes.corpus.validation import corpus_content_digest, corpus_identity_digest

# Recorded in docs/experiment-log.md by the pre-Milestone-3 amendment run and
# reconfirmed by the canonical-byte checksum remediation: token identity must
# not change when only acquisition byte handling changes.
EXPECTED_IDENTITY_DIGEST = "91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6"
EXPECTED_TOKEN_COUNT = 475_911
# Content companions recorded in docs/experiment-log.md before Milestone 4
# Part 1: SHA-256 over corpus-position-ordered
# token_id\0surface_form\0normalized_form\0lemma\n rows (null lemma encoded as
# the empty string). The base MACULA tables must reproduce these values
# byte-for-byte through all supplementary Milestone 4 work.
EXPECTED_HEBREW_CONTENT_DIGEST = "7fb443c3f0c42ada5d89f3abad61dd304145863044107ac86277c9f05f76cc82"
EXPECTED_GREEK_IDENTITY_DIGEST = "9035fea8d73a2b2078ad2adc70f8389040dbe2051ee535b2ce88412f551df6f2"
EXPECTED_GREEK_CONTENT_DIGEST = "a5ede58d287c2d29d5dacc7adeb07ff5c6a10587e2949875928b2dd935c8c683"
EXPECTED_GREEK_TOKEN_COUNT = 137_779
HEBREW_TOKENS_PARQUET = Path("data/processed/macula-hebrew/25.08.11/tokens.parquet")
GREEK_TOKENS_PARQUET = Path("data/processed/macula-greek/24.06.17/tokens.parquet")
IDENTITY_COLUMNS = ["position_in_corpus", "token_id", "source_record_id", "source_word_id"]
CONTENT_COLUMNS = ["position_in_corpus", "token_id", "surface_form", "normalized_form", "lemma"]

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
    tokens = pl.read_parquet(HEBREW_TOKENS_PARQUET, columns=IDENTITY_COLUMNS)

    assert tokens.height == EXPECTED_TOKEN_COUNT
    assert corpus_identity_digest(tokens) == EXPECTED_IDENTITY_DIGEST


@pytest.mark.full_corpus
@FULL_CORPUS
def test_full_corpus_content_digests_are_stable() -> None:
    hebrew = pl.read_parquet(HEBREW_TOKENS_PARQUET, columns=CONTENT_COLUMNS)
    greek = pl.read_parquet(GREEK_TOKENS_PARQUET, columns=CONTENT_COLUMNS)

    assert hebrew.height == EXPECTED_TOKEN_COUNT
    assert greek.height == EXPECTED_GREEK_TOKEN_COUNT
    assert corpus_content_digest(hebrew) == EXPECTED_HEBREW_CONTENT_DIGEST
    assert corpus_content_digest(greek) == EXPECTED_GREEK_CONTENT_DIGEST


@pytest.mark.full_corpus
@FULL_CORPUS
def test_full_greek_corpus_identity_digest_is_stable() -> None:
    tokens = pl.read_parquet(GREEK_TOKENS_PARQUET, columns=IDENTITY_COLUMNS)

    assert tokens.height == EXPECTED_GREEK_TOKEN_COUNT
    assert corpus_identity_digest(tokens) == EXPECTED_GREEK_IDENTITY_DIGEST


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
