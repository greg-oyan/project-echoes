"""Optional regression gate for a locally acquired full MACULA Hebrew corpus."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import polars as pl
import pytest

from echoes.corpus.hebrew import validate_existing_hebrew_corpus
from echoes.corpus.validation import (
    corpus_analytical_digest,
    corpus_content_digest,
    corpus_identity_digest,
)

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
EXPECTED_HEBREW_ANALYTICAL_DIGEST = (
    "9464a106684b63ff57bcd9dd754bcd0c875d7ea8157fc7bfe643d7eb66dab173"
)
EXPECTED_GREEK_ANALYTICAL_DIGEST = (
    "31404eb29a1f71855f3670f6f895e3fadc3ab0b39e2685c3cf672620df08a2a1"
)
EXPECTED_GREEK_TOKEN_COUNT = 137_779
EXPECTED_KQ_LOGICAL_HASHES = {
    "ketiv_tokens": "7bb67cebc45c06943a7f1fc2e241202f100a19cf7ad6dd6b0933d999ac01d238",
    "locus_registry": "ae6e70a8d1dd75cccfef85bb5535051134104f03d57490976d4e30f93c60f022",
    "structural_alignments": "ac0c9ebffe971ef9178ef47edbf868d9f904a189133dccf907f815651b867df9",
}
EXPECTED_KQ_PARQUET_HASHES = {
    "kq_ketiv_tokens.parquet": "c14187ed7cdcfa03367c2fbc1a2630e08f0dc51258626d78d95e96967d9cf7da",
    "kq_locus_registry.parquet": "61d3bb76c218537dfc401864685100285308367aa5f2020a2101a97d3c696304",
    "kq_structural_alignments.parquet": (
        "ce59933c69da553f1b74a26296606fc141bdc46c9b9efc399926be9f2e654b58"
    ),
}
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
def test_full_corpus_analytical_digests_are_stable() -> None:
    hebrew = pl.read_parquet(HEBREW_TOKENS_PARQUET)
    greek = pl.read_parquet(GREEK_TOKENS_PARQUET)

    assert hebrew.height == EXPECTED_TOKEN_COUNT
    assert greek.height == EXPECTED_GREEK_TOKEN_COUNT
    assert corpus_analytical_digest(hebrew) == EXPECTED_HEBREW_ANALYTICAL_DIGEST
    assert corpus_analytical_digest(greek) == EXPECTED_GREEK_ANALYTICAL_DIGEST


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


@pytest.mark.full_corpus
@FULL_CORPUS
def test_full_kq_supplement_passes_milestone_four_part_one_gate() -> None:
    from echoes.corpus.kq_supplement import validate_kq_supplement

    supplement_dir = Path("data/processed/oshb-morphhb/master-3d15126")
    primary = pl.read_parquet(HEBREW_TOKENS_PARQUET)
    greek_ids = set(
        pl.read_parquet(GREEK_TOKENS_PARQUET, columns=["token_id"])["token_id"].to_list()
    )

    report = validate_kq_supplement(
        supplement_dir,
        primary,
        other_corpus_token_ids=greek_ids,
        expected_primary_identity_digest=EXPECTED_IDENTITY_DIGEST,
        expected_primary_content_digest=EXPECTED_HEBREW_CONTENT_DIGEST,
        expected_primary_analytical_digest=EXPECTED_HEBREW_ANALYTICAL_DIGEST,
    )

    assert report.passed
    assert report.error_count == 0
    assert report.total_tokens == 1_268
    assert report.coverage["loci"] == 1_260
    assert report.coverage["paired_loci"] == 1_245
    assert report.coverage["ketiv_only_loci"] == 6
    assert report.coverage["qere_only_loci"] == 9
    assert report.coverage["conflicts"] == 0
    assert report.coverage["structural_resolved_tokens"] == 449
    assert report.coverage["structural_partially_resolved_tokens"] == 819
    assert report.coverage["structural_unresolved_tokens"] == 0

    hashes = json.loads((supplement_dir / "table-hashes.json").read_text(encoding="utf-8"))
    assert hashes["ingestion_run_id"] == "oshb-kq-0fed79a1841208ff4d77"
    assert {
        name: hashes["logical_table_sha256"][name] for name in EXPECTED_KQ_LOGICAL_HASHES
    } == EXPECTED_KQ_LOGICAL_HASHES
    assert {
        name: hashes["parquet_sha256"][name] for name in EXPECTED_KQ_PARQUET_HASHES
    } == EXPECTED_KQ_PARQUET_HASHES

    registry = pl.read_parquet(supplement_dir / "kq_locus_registry.parquet")
    # 2KI 8:10: negative-particle ketiv at vacant slot 6 paired against the
    # prepositional qere reading at slot 7.
    locus = registry.filter(pl.col("locus_id") == "KQL_2KI_008_010_0006").to_dicts()[0]
    assert locus["kind"] == "paired"
    assert locus["source_book_identifier"] == "2Kgs"
    assert locus["canonical_book"] == "2KI"
    assert locus["book"] == "2KI"
    assert json.loads(locus["ketiv_word_slots_json"]) == [6]
    assert json.loads(locus["qere_word_slots_json"]) == [7]
    assert locus["ketiv_surface"] == "לא"  # lamed-alef (the negative particle)
    assert locus["surface_match_tier"] == "exact"
    assert locus["alignment_confidence"] == 1.0
    assert json.loads(locus["macula_qere_token_ids_json"]) == [
        "HB_2KI_008_010_0007.01",
        "HB_2KI_008_010_0007.02",
    ]
    ketiv = pl.read_parquet(supplement_dir / "kq_ketiv_tokens.parquet")
    two_kings = ketiv.filter(
        (pl.col("book") == "2KI") & (pl.col("chapter") == 8) & (pl.col("verse") == 10)
    ).to_dicts()
    assert len(two_kings) == 1
    assert two_kings[0]["token_id"] == "HB_2KGS_008_010_0006~94c99d606560"
    assert two_kings[0]["source_edition_reference"] == "2Kgs 8:10"
    assert two_kings[0]["source_word_id"] == "2Kgs 8:10!6"
    assert two_kings[0]["book"] == "2KI"
    assert json.loads(two_kings[0]["morphology_json"])["oshb_morph"] == "HTn"

    assert ketiv["token_id"].n_unique() == 1_268
    assert not (set(ketiv["token_id"].to_list()) & set(primary["token_id"].to_list()))
    assert not (set(ketiv["token_id"].to_list()) & greek_ids)

    structural = pl.read_parquet(supplement_dir / "kq_structural_alignments.parquet")
    assert structural.height == 1_268
    assert structural["ketiv_token_id"].n_unique() == 1_268
    by_locus = structural.unique("locus_id", keep="first")
    assert by_locus.height == 1_251
    assert by_locus["analysis_sentence_id"].is_not_null().sum() == 1_251
    assert by_locus["analysis_clause_id"].is_not_null().sum() == 998
    assert by_locus["analysis_phrase_id"].is_not_null().sum() == 449
    assert by_locus.filter(pl.col("resolution_status") == "resolved").height == 448
    partial_locus_ids = set(
        by_locus.filter(pl.col("resolution_status") == "partially_resolved")["locus_id"].to_list()
    )
    assert len(partial_locus_ids) == 803
    appendix_path = Path("outputs/reports/m4-part1-structural-unresolved.csv")
    with appendix_path.open(encoding="utf-8", newline="") as appendix:
        appendix_locus_ids = {row["locus_id"] for row in csv.DictReader(appendix)}
    assert appendix_locus_ids == partial_locus_ids

    # Four more paired loci across Torah, Prophets, and Writings.
    for locus_id in (
        "KQL_GEN_008_017_0014",
        "KQL_DEU_005_010_0006",
        "KQL_ISA_003_016_0009",
        "KQL_PSA_005_009_0006",
        "KQL_RUT_002_001_0002",
    ):
        row = registry.filter(pl.col("locus_id") == locus_id).to_dicts()
        assert len(row) == 1, locus_id
        assert row[0]["kind"] == "paired"
        assert row[0]["surface_match_tier"] == "exact"
        assert row[0]["alignment_confidence"] == 1.0

    # No conflict rows exist in the pinned sources; the conflict path is
    # exercised by synthetic fixtures instead.
    conflicts = pl.read_parquet(supplement_dir / "kq_conflicts.parquet")
    assert conflicts.height == 0
