"""Opt-in regression anchors for the complete Milestone 6 benchmark."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
import pytest

from echoes.benchmarks.models import BENCHMARK_ARTIFACT_NAMES
from echoes.benchmarks.openbible import audit_openbible_source, parse_openbible_source
from echoes.benchmarks.references import openbible_reference_corpus
from echoes.benchmarks.storage import logical_parquet_hash
from echoes.benchmarks.tier1 import validate_tier1_quotations

ARTIFACT_ROOT = Path("data/processed/benchmarks/schema-v1")
DATABASE_PATH = Path("data/processed/project_echoes.duckdb")
PASSAGE_ARTIFACT_ROOT = Path("data/processed/passages/schema-v1")
SOURCE_ROOT = Path("data/raw/openbible-cross-references/snapshot-2026-07-12-sha256-18e63e370308")
SOURCE_ARCHIVE = SOURCE_ROOT / "_archive/cross-references.zip"
SOURCE_FILE = SOURCE_ROOT / "cross_references.txt"
TIER1_PATH = Path("data/benchmarks/tier1_quotations.csv")

EXPECTED_BENCHMARK_RUN_ID = "benchmark-v1-dff1d3ef650c8ccd4930"
EXPECTED_BENCHMARK_VERSION = "known-links-v1-dff1d3ef650c"
EXPECTED_ARCHIVE_SHA256 = "18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492"
EXPECTED_SOURCE_FILE_SHA256 = "eb7a78dbd5a8a88f1a87689de11f6d87806dc9fa20c3e88f7800665deb6b5c37"
EXPECTED_CANONICAL_STREAM_SHA256 = (
    "e3b2b3bb8c0097382ce4385c38342d4d4d07dd3cde05b331c0998a007840482e"
)
EXPECTED_TIER1_HEADER_SHA256 = "7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b"
EXPECTED_SOURCE_AUDIT = {
    "raw_row_count": 344_799,
    "parsed_row_count": 344_799,
    "invalid_row_count": 0,
    "exact_duplicate_occurrence_count": 0,
    "duplicate_directed_pair_count": 0,
    "unique_directed_relationship_count": 344_799,
    "unique_unordered_pair_count": 314_921,
    "reverse_pair_count": 29_878,
    "self_link_count": 0,
    "weight_min": -86,
    "weight_q1": 2,
    "weight_median": 3,
    "weight_q3": 6,
    "weight_max": 1_281,
    "negative_weight_count": 1_239,
    "zero_weight_count": 2_277,
    "positive_weight_count": 341_283,
    "distinct_weight_count": 418,
}
EXPECTED_REFERENCE_KIND_COUNTS = {
    "single": 256_649,
    "same_chapter_range": 87_495,
    "cross_chapter_range": 637,
    "cross_book_range": 18,
}
EXPECTED_TABLE_COUNTS = {
    "benchmark_source_records": 344_799,
    "benchmark_relationships": 344_799,
    "benchmark_relationship_source_records": 344_799,
    "benchmark_endpoints": 689_598,
    "benchmark_endpoint_mappings": 1_379_196,
    "benchmark_leakage_groups": 4_561_525,
    "benchmark_split_assignments": 1_723_995,
    "benchmark_presumed_negatives": 29_275,
    "benchmark_issues": 18,
    "benchmark_metadata": 1,
}
EXPECTED_LOGICAL_HASHES = {
    "benchmark_source_records": "481e53738ae4f4940277d211176194b97e57908eb31ef172359524165409f1f4",
    "benchmark_relationships": "4bd3d602a2604d425c0016eb7d565667a844b353cb16d0d88f3c369c21a13a6f",
    "benchmark_relationship_source_records": (
        "f215928778e16ef496ec309282a327559d242f520d531240059ecdbe21ba64a1"
    ),
    "benchmark_endpoints": "a9560e443ba32b3900f635421f9390f461fdebe0c23f316ec295b7be28ba13c7",
    "benchmark_endpoint_mappings": (
        "d56e5211a415b51abbfa5080add85ade3ad8d4f30b6c95313fef19e5c6e956e3"
    ),
    "benchmark_leakage_groups": (
        "56c356147c61d12074dbdf88e7ea2dd111e8a2d0e34e7caa530d103e6d66f9d7"
    ),
    "benchmark_split_assignments": (
        "bda3c63f2aa15cd60567fd3a8dae3118402df35fc07921910a218a941c9ac5e0"
    ),
    "benchmark_presumed_negatives": (
        "9bf1ed5dd30c6a93b6ef359cd7d5fd39704f3c0cb3719e17cbcaae5bf524d6ff"
    ),
    "benchmark_issues": "f39d5494a1d13e68e9acf77b44e6c1a38dc419ec52abfb879a26f41165a07de0",
    "benchmark_metadata": "b406ab043ed90ba59204b1b6937ea742ea6d2e66a552a8678934d94b290086d8",
}
EXPECTED_ENDPOINT_PARSE_STATUSES = {"cross_book_range": 18, "parsed": 689_580}
EXPECTED_MAPPING_STATUSES = {
    "excluded_by_profile": 639,
    "mapped_partial": 781,
    "mapped_provisional": 1_371_984,
    "unresolved_missing_target": 5_756,
    "unresolved_reference": 36,
}
EXPECTED_MAPPING_FLAGS = {
    "critical_core": [134, 644, 639],
    "edition_complete": [134, 644, 0],
}
EXPECTED_CORPUS_PAIR_COUNTS = {
    "old_testament_to_old_testament": 187_117,
    "new_testament_to_new_testament": 84_369,
    "cross_testament": 73_313,
}
EXPECTED_LEAKAGE_COUNTS = {
    "canonical_book_pair": [2_114, 344_799],
    "exact_directed_pair": [344_799, 344_799],
    "exact_unordered_pair": [314_921, 344_799],
    "overlapping_endpoint_range": [30_266, 953_361],
    "overlapping_target_passage": [30_133, 949_259],
    "shared_endpoint": [44_663, 670_106],
    "shared_target_passage": [30_810, 954_402],
}
EXPECTED_SPLIT_COUNTS = {
    "held_out_book|development": 137,
    "held_out_book|excluded": 306_941,
    "held_out_book|test": 34_859,
    "held_out_book|train": 2_862,
    "held_out_book_pair|excluded": 338_769,
    "held_out_book_pair|train": 6_030,
    "held_out_genre|excluded": 304_087,
    "held_out_genre|test": 32_297,
    "held_out_genre|train": 8_415,
    "held_out_relationship_family|excluded": 344_799,
    "held_out_source_passage|development": 2_375,
    "held_out_source_passage|excluded": 177_222,
    "held_out_source_passage|test": 2_607,
    "held_out_source_passage|train": 162_595,
}
EXPECTED_NEGATIVE_COUNTS = {
    "length_matched_random_unlinked": 5_855,
    "nearby_context_unlinked": 5_855,
    "same_book_pair_unlinked": 5_855,
    "same_book_unlinked": 5_855,
    "same_broad_genre_unlinked": 5_855,
}
EXPECTED_PASSAGE_RUN_ID = "passages-v1-00e261abea9ed44ef087"
EXPECTED_PASSAGE_LOGICAL_HASHES = {
    "passage_adjacency": "1ca8c79f92b2742e12586b6c72eaddbcc834d5bce818b909f33b2c10b9db69bd",
    "passage_membership": "726c6b9339a78e7806bac90f7d91930c7f86bec7c7c0be6a51bdedb7a54d40bd",
    "passages": "00047c9dc16ceaefdc0ff1b18a8fb2b4480a1be0534ed861cf5c11706d2048a0",
    "segmentation_exclusions": ("6a0e475398e76730b5a7a92370ee319b803c0d17ba45e01b7155fa3b28c7e209"),
    "segmentation_issues": "2f3a57eada1dda388ca99bf67cd0b6de70fb31afa1abc1980eafbf605359eac3",
    "segmentation_metadata": ("87b88f0b3d4efa88c9d4668ba1eb0aba5fce244b0350130a033deb1a087578cf"),
}

pytestmark = [
    pytest.mark.full_corpus,
    pytest.mark.skipif(
        os.environ.get("ECHOES_RUN_FULL_CORPUS") != "1",
        reason="set ECHOES_RUN_FULL_CORPUS=1 after complete Milestone 6 generation",
    ),
]


@pytest.fixture(scope="module")
def database() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect(str(DATABASE_PATH), read_only=True) as connection:
        yield connection


@pytest.fixture(scope="module")
def metadata(database: duckdb.DuckDBPyConnection) -> dict[str, object]:
    cursor = database.execute("SELECT * FROM benchmark_metadata")
    rows = cursor.fetchall()
    assert len(rows) == 1
    return dict(zip((str(item[0]) for item in cursor.description), rows[0], strict=True))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(value: object) -> dict[str, Any]:
    parsed = json.loads(str(value))
    assert isinstance(parsed, dict)
    return parsed


def test_full_openbible_source_snapshot_and_audit_are_pinned() -> None:
    assert _sha256_file(SOURCE_ARCHIVE) == EXPECTED_ARCHIVE_SHA256
    assert _sha256_file(SOURCE_FILE) == EXPECTED_SOURCE_FILE_SHA256

    audit = audit_openbible_source(parse_openbible_source(SOURCE_FILE))
    assert audit["canonical_stream_sha256"] == EXPECTED_CANONICAL_STREAM_SHA256
    assert audit["reference_kind_counts"] == EXPECTED_REFERENCE_KIND_COUNTS
    assert {key: audit[key] for key in EXPECTED_SOURCE_AUDIT} == EXPECTED_SOURCE_AUDIT


def test_full_benchmark_parquet_counts_and_logical_hashes_are_pinned() -> None:
    manifest = _json_object((ARTIFACT_ROOT / "table-hashes.json").read_text("utf-8"))
    assert manifest["artifact_schema_version"] == 1
    assert manifest["table_counts"] == EXPECTED_TABLE_COUNTS
    assert manifest["table_logical_sha256"] == EXPECTED_LOGICAL_HASHES

    for name in BENCHMARK_ARTIFACT_NAMES:
        path = ARTIFACT_ROOT / name / "part-00000.parquet"
        parquet_metadata = pq.ParquetFile(path).metadata
        assert parquet_metadata is not None
        assert parquet_metadata.num_rows == EXPECTED_TABLE_COUNTS[name]
        assert logical_parquet_hash(path, name, batch_size=7_919) == EXPECTED_LOGICAL_HASHES[name]


def test_full_benchmark_database_and_metadata_reconcile(
    database: duckdb.DuckDBPyConnection,
    metadata: dict[str, object],
) -> None:
    observed_counts = {
        name: int(database.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
        for name in BENCHMARK_ARTIFACT_NAMES
    }
    assert observed_counts == EXPECTED_TABLE_COUNTS
    assert metadata["benchmark_run_id"] == EXPECTED_BENCHMARK_RUN_ID
    assert metadata["benchmark_version"] == EXPECTED_BENCHMARK_VERSION
    assert metadata["relationship_count"] == EXPECTED_TABLE_COUNTS["benchmark_relationships"]
    assert metadata["endpoint_count"] == EXPECTED_TABLE_COUNTS["benchmark_endpoints"]
    assert metadata["mapping_count"] == EXPECTED_TABLE_COUNTS["benchmark_endpoint_mappings"]
    assert _json_object(metadata["logical_table_hashes_json"]) == {
        name: digest
        for name, digest in EXPECTED_LOGICAL_HASHES.items()
        if name != "benchmark_metadata"
    }


def test_full_relationship_graph_and_weights_are_exact(
    database: duckdb.DuckDBPyConnection,
) -> None:
    source = database.execute(
        "SELECT count(*),count(*) FILTER(WHERE parse_status='parsed'),"
        "count(*) FILTER(WHERE parse_status<>'parsed'),min(source_weight),"
        "quantile_disc(source_weight,0.25),median(source_weight),"
        "quantile_disc(source_weight,0.75),max(source_weight),"
        "count(*) FILTER(WHERE source_weight<0),count(*) FILTER(WHERE source_weight=0),"
        "count(*) FILTER(WHERE source_weight>0),count(DISTINCT source_weight) "
        "FROM benchmark_source_records"
    ).fetchone()
    assert source == (344_799, 344_799, 0, -86, 2, 3.0, 6, 1_281, 1_239, 2_277, 341_283, 418)

    relationships = database.execute(
        "SELECT count(*),count(DISTINCT canonical_directed_pair_id),"
        "count(DISTINCT canonical_undirected_pair_id),"
        "count(*) FILTER(WHERE source_record_count>1),"
        "count(*) FILTER(WHERE source_reference_a=source_reference_b) "
        "FROM benchmark_relationships"
    ).fetchone()
    assert relationships == (344_799, 344_799, 314_921, 0, 0)
    reverse_pairs = database.execute(
        "SELECT count(*) FROM (SELECT canonical_undirected_pair_id "
        "FROM benchmark_relationships GROUP BY 1 HAVING count(*)>1)"
    ).fetchone()
    assert reverse_pairs == (29_878,)


def test_full_endpoint_mapping_and_reference_risk_counts_are_exact(
    database: duckdb.DuckDBPyConnection,
) -> None:
    endpoint_statuses = {
        str(status): int(count)
        for status, count in database.execute(
            "SELECT parse_status,count(*) FROM benchmark_endpoints GROUP BY 1"
        ).fetchall()
    }
    mapping_statuses = {
        str(status): int(count)
        for status, count in database.execute(
            "SELECT mapping_status,count(*) FROM benchmark_endpoint_mappings GROUP BY 1"
        ).fetchall()
    }
    mapping_flags = {
        str(profile): [int(reference_gap), int(disputed), int(excluded)]
        for profile, reference_gap, disputed, excluded in database.execute(
            "SELECT target_analysis_profile,count(*) FILTER(WHERE reference_gap),"
            "count(*) FILTER(WHERE disputed_passage_flag),"
            "count(*) FILTER(WHERE mapping_status='excluded_by_profile') "
            "FROM benchmark_endpoint_mappings GROUP BY 1"
        ).fetchall()
    }

    assert endpoint_statuses == EXPECTED_ENDPOINT_PARSE_STATUSES
    assert mapping_statuses == EXPECTED_MAPPING_STATUSES
    assert "mapped_verified" not in mapping_statuses
    assert mapping_flags == EXPECTED_MAPPING_FLAGS


def test_full_source_reference_corpus_pairs_include_cross_book_ranges(
    database: duckdb.DuckDBPyConnection,
) -> None:
    cross_book_corpora = [
        openbible_reference_corpus(str(reference))
        for (reference,) in database.execute(
            "SELECT source_reference FROM benchmark_endpoints WHERE parse_status='cross_book_range'"
        ).fetchall()
    ]
    assert cross_book_corpora.count("hebrew") == 10
    assert cross_book_corpora.count("greek") == 8
    assert None not in cross_book_corpora

    observed = {
        "old_testament_to_old_testament": int(
            database.execute("SELECT count(*) FROM within_old_testament_relationships").fetchone()[
                0
            ]
        ),
        "new_testament_to_new_testament": int(
            database.execute("SELECT count(*) FROM within_new_testament_relationships").fetchone()[
                0
            ]
        ),
        "cross_testament": int(
            database.execute("SELECT count(*) FROM cross_testament_relationships").fetchone()[0]
        ),
    }
    assert observed == EXPECTED_CORPUS_PAIR_COUNTS
    assert sum(observed.values()) == EXPECTED_TABLE_COUNTS["benchmark_relationships"]


def test_full_leakage_split_and_presumed_negative_counts_are_exact(
    database: duckdb.DuckDBPyConnection,
) -> None:
    leakage = {
        str(group_type): [int(group_count), int(membership_count)]
        for group_type, group_count, membership_count in database.execute(
            "SELECT group_type,count(DISTINCT leakage_group_id),count(*) "
            "FROM benchmark_leakage_groups GROUP BY 1"
        ).fetchall()
    }
    splits = {
        f"{strategy}|{partition}": int(count)
        for strategy, partition, count in database.execute(
            "SELECT split_strategy,partition,count(*) FROM benchmark_split_assignments GROUP BY 1,2"
        ).fetchall()
    }
    negatives = {
        str(strategy): int(count)
        for strategy, count in database.execute(
            "SELECT negative_strategy,count(*) FROM benchmark_presumed_negatives GROUP BY 1"
        ).fetchall()
    }

    assert leakage == EXPECTED_LEAKAGE_COUNTS
    assert splits == EXPECTED_SPLIT_COUNTS
    assert negatives == EXPECTED_NEGATIVE_COUNTS


def test_full_presumed_negatives_have_zero_positive_collisions(
    database: duckdb.DuckDBPyConnection,
) -> None:
    collision = database.execute(
        """
        WITH endpoint_targets AS (
          SELECT e.relationship_id,e.endpoint_side,t.target_passage_id
          FROM benchmark_endpoints e
          JOIN benchmark_endpoint_mappings m USING(endpoint_id)
          JOIN benchmark_mapping_target_passages t USING(mapping_id,endpoint_id)
          WHERE m.target_analysis_profile='edition_complete'
        ), positive_pairs AS (
          SELECT a.target_passage_id AS a,b.target_passage_id AS b
          FROM endpoint_targets a JOIN endpoint_targets b USING(relationship_id)
          WHERE a.endpoint_side='a' AND b.endpoint_side='b'
        )
        SELECT count(DISTINCT n.contrastive_id) FROM benchmark_presumed_negatives n
        JOIN positive_pairs p
          ON least(n.passage_a_id,n.passage_b_id)=least(p.a,p.b)
         AND greatest(n.passage_a_id,n.passage_b_id)=greatest(p.a,p.b)
        """
    ).fetchone()
    control_violations = database.execute(
        "SELECT count(*) FROM benchmark_presumed_negatives "
        "WHERE passage_a_id=passage_b_id OR NOT presumed_negative "
        "OR NOT positive_graph_checked OR NOT reverse_pair_checked "
        "OR NOT passage_overlap_checked OR NOT leakage_checked"
    ).fetchone()
    assert collision == (0,)
    assert control_violations == (0,)


def test_full_tier1_and_passage_inputs_remain_invariant(
    database: duckdb.DuckDBPyConnection,
    metadata: dict[str, object],
) -> None:
    tier1 = validate_tier1_quotations(
        TIER1_PATH,
        expected_sha256=EXPECTED_TIER1_HEADER_SHA256,
    )
    assert tier1.row_count == 0
    assert tier1.sha256 == EXPECTED_TIER1_HEADER_SHA256

    source_audit = _json_object(metadata["source_audit_json"])
    assert source_audit["canonical_stream_sha256"] == EXPECTED_CANONICAL_STREAM_SHA256
    assert _json_object(metadata["source_archive_hashes_json"]) == {
        "openbible-cross-references": EXPECTED_ARCHIVE_SHA256
    }
    assert metadata["tier1_header_sha256"] == EXPECTED_TIER1_HEADER_SHA256
    assert metadata["passage_input_run_id"] == EXPECTED_PASSAGE_RUN_ID
    assert _json_object(metadata["passage_logical_hashes_json"]) == EXPECTED_PASSAGE_LOGICAL_HASHES

    passage_manifest = _json_object(
        (PASSAGE_ARTIFACT_ROOT / "table-hashes.json").read_text("utf-8")
    )
    assert passage_manifest["table_logical_sha256"] == EXPECTED_PASSAGE_LOGICAL_HASHES
    assert database.execute("SELECT segmentation_run_id FROM segmentation_metadata").fetchone() == (
        EXPECTED_PASSAGE_RUN_ID,
    )
