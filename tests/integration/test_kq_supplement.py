"""K/Q supplement storage, derived-stream, and validation integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from echoes.corpus.analysis import derive_analysis_stream
from echoes.corpus.kq_supplement import (
    derive_supplemented_analysis_stream,
    load_kq_duckdb,
    validate_kq_supplement,
    write_kq_supplement,
)
from echoes.corpus.storage import CorpusStorageError, load_hebrew_duckdb, write_processed_corpus
from echoes.corpus.validation import corpus_content_digest, corpus_identity_digest
from echoes.manifest import sha256_file
from echoes.manifests.sources import SourceManifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NORMALIZATION_PATH = PROJECT_ROOT / "config" / "normalization.yaml"


def _write(tmp_path: Path, kq_supplement_result, kq_primary_tokens, oshb_source, **kwargs):
    return write_kq_supplement(
        kq_supplement_result,
        source=oshb_source,
        normalization_config_hash=sha256_file(NORMALIZATION_PATH),
        raw_file_hashes={"wlc/Gen.xml": "0" * 64, "wlc/Dan.xml": "1" * 64},
        primary_identity_digest=corpus_identity_digest(kq_primary_tokens),
        primary_content_digest=corpus_content_digest(kq_primary_tokens),
        output_dir=tmp_path / "kq",
        **kwargs,
    )


def test_supplement_roundtrip_validates(
    tmp_path: Path,
    kq_supplement_result,
    kq_primary_tokens,
    oshb_source: SourceManifest,
) -> None:
    processed = _write(tmp_path, kq_supplement_result, kq_primary_tokens, oshb_source)

    report = validate_kq_supplement(
        processed.output_dir,
        kq_primary_tokens,
        expected_primary_identity_digest=corpus_identity_digest(kq_primary_tokens),
        expected_primary_content_digest=corpus_content_digest(kq_primary_tokens),
    )

    assert report.corpus == "hebrew-kq-supplement"
    assert report.passed
    assert report.total_tokens == 7
    assert report.coverage["loci"] == 7
    assert report.coverage["conflicts"] == 2


def test_rerun_is_deterministic_and_overwrite_is_explicit(
    tmp_path: Path,
    kq_supplement_result,
    kq_primary_tokens,
    oshb_source: SourceManifest,
) -> None:
    first = _write(tmp_path, kq_supplement_result, kq_primary_tokens, oshb_source)

    with pytest.raises(CorpusStorageError, match="refusing to overwrite"):
        _write(tmp_path, kq_supplement_result, kq_primary_tokens, oshb_source)

    second = _write(tmp_path, kq_supplement_result, kq_primary_tokens, oshb_source, force=True)

    assert first.run_id == second.run_id
    assert first.file_hashes == second.file_hashes
    assert first.logical_hashes == second.logical_hashes


def test_duckdb_pairing_view_is_queryable(
    tmp_path: Path,
    adapter_result,
    macula_source: SourceManifest,
    kq_supplement_result,
    kq_primary_tokens,
    oshb_source: SourceManifest,
) -> None:
    database = tmp_path / "kq.duckdb"
    # Load a primary corpus first so the pairing view can reference qere rows.
    primary_processed = write_processed_corpus(
        adapter_result,
        source=macula_source,
        normalization_config_hash=sha256_file(NORMALIZATION_PATH),
        raw_file_hashes={"fixture.xml": "0" * 64},
        output_dir=tmp_path / "hebrew",
    )
    load_hebrew_duckdb(primary_processed, database)
    processed = _write(tmp_path, kq_supplement_result, kq_primary_tokens, oshb_source)
    load_kq_duckdb(processed, database)

    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        assert {
            "hebrew_kq_ketiv_tokens",
            "hebrew_kq_locus_registry",
            "hebrew_kq_conflicts",
            "hebrew_kq_metadata",
        } <= tables
        row = connection.execute(
            "SELECT count(*) FROM hebrew_kq_variant_groups WHERE kind = 'paired'"
        ).fetchone()
        assert row is not None and int(row[0]) >= 5
        conflict_row = connection.execute("SELECT count(*) FROM hebrew_kq_conflicts").fetchone()
        assert conflict_row is not None and int(conflict_row[0]) == 2
        # Primary tables remain untouched by the supplement load.
        count_row = connection.execute("SELECT count(*) FROM hebrew_tokens").fetchone()
        assert count_row is not None and int(count_row[0]) == adapter_result.tokens.height


def test_qere_stream_is_byte_identical_to_pre_supplement_state(
    kq_primary_tokens,
    kq_supplement_result,
) -> None:
    base = derive_analysis_stream(kq_primary_tokens, analysis_reading="qere")
    supplemented = derive_supplemented_analysis_stream(
        kq_primary_tokens,
        kq_supplement_result.ketiv_tokens,
        kq_supplement_result.locus_registry,
        analysis_reading="qere",
    )

    assert supplemented.equals(base)


def test_ketiv_stream_substitutes_paired_loci_deterministically(
    kq_primary_tokens,
    kq_supplement_result,
) -> None:
    first = derive_supplemented_analysis_stream(
        kq_primary_tokens,
        kq_supplement_result.ketiv_tokens,
        kq_supplement_result.locus_registry,
        analysis_reading="ketiv",
    )
    second = derive_supplemented_analysis_stream(
        kq_primary_tokens,
        kq_supplement_result.ketiv_tokens,
        kq_supplement_result.locus_registry,
        analysis_reading="ketiv",
    )

    assert first.equals(second)
    positions = first["analysis_position_in_corpus"].to_list()
    assert positions == list(range(1, len(positions) + 1))

    stream_ids = set(first["token_id"].to_list())
    registry = kq_supplement_result.locus_registry
    for row in registry.filter(pl.col("kind") == "paired").iter_rows(named=True):
        for replaced in json.loads(row["macula_qere_token_ids_json"]):
            assert replaced not in stream_ids
        for ketiv_id in json.loads(row["ketiv_token_ids_json"]):
            assert ketiv_id in stream_ids
    # Lone ketiv readings join the ketiv stream only.
    ketiv_only = registry.filter(pl.col("kind") == "ketiv_only")
    for row in ketiv_only.iter_rows(named=True):
        for ketiv_id in json.loads(row["ketiv_token_ids_json"]):
            assert ketiv_id in stream_ids
    # Verse positions are continuous inside a substituted verse.
    gen11 = first.filter(pl.col("source_edition_reference") == "GEN 1:1").sort(
        "analysis_position_in_corpus"
    )
    assert gen11["analysis_position_in_verse"].to_list() == list(range(1, gen11.height + 1))


def test_validation_detects_primary_mutation(
    tmp_path: Path,
    kq_supplement_result,
    kq_primary_tokens,
    oshb_source: SourceManifest,
) -> None:
    processed = _write(tmp_path, kq_supplement_result, kq_primary_tokens, oshb_source)
    mutated = kq_primary_tokens.with_columns(
        pl.when(pl.col("token_id") == "HB_GEN_001_001_0003")
        .then(pl.lit("altered"))
        .otherwise(pl.col("surface_form"))
        .alias("surface_form")
    )

    report = validate_kq_supplement(
        processed.output_dir,
        mutated,
        expected_primary_content_digest=corpus_content_digest(kq_primary_tokens),
    )

    assert not report.passed
    codes = {issue.code for issue in report.issues}
    assert "primary-content-changed" in codes
