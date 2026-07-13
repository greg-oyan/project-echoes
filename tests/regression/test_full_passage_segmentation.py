"""Opt-in regression anchors for the complete Milestone 5 passage artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pytest

EXPECTED_PATH = Path("tests/fixtures/expected/m5-full-corpus-v1.json")
ARTIFACT_DIR = Path("data/processed/passages/schema-v1")
DATABASE_PATH = Path("data/processed/project_echoes.duckdb")

pytestmark = [
    pytest.mark.full_corpus,
    pytest.mark.skipif(
        os.environ.get("ECHOES_RUN_FULL_CORPUS") != "1",
        reason="set ECHOES_RUN_FULL_CORPUS=1 after complete Milestone 5 generation",
    ),
]


@pytest.fixture(scope="module")
def expected() -> dict[str, Any]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def database() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect(str(DATABASE_PATH), read_only=True) as connection:
        yield connection


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    assert isinstance(parsed, dict)
    return parsed


def _key(*values: object) -> str:
    return "|".join(str(value) for value in values)


def test_full_passage_manifest_and_source_anchors_are_pinned(
    database: duckdb.DuckDBPyConnection,
    expected: dict[str, Any],
) -> None:
    manifest = json.loads((ARTIFACT_DIR / "table-hashes.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == expected["passage_schema_version"]
    assert manifest["table_counts"] == expected["table_counts"]
    assert manifest["table_logical_sha256"] == expected["table_logical_sha256"]

    cursor = database.execute("SELECT * FROM segmentation_metadata")
    columns = [str(description[0]) for description in cursor.description]
    rows = cursor.fetchall()
    assert len(rows) == 1
    metadata = dict(zip(columns, rows[0], strict=True))
    anchors = expected["source_anchors"]
    assert metadata["segmentation_run_id"] == expected["segmentation_run_id"]
    assert metadata["passage_schema_version"] == expected["passage_schema_version"]
    assert metadata["passage_id_schema_version"] == expected["passage_id_schema_version"]
    assert metadata["segmentation_config_hash"] == expected["segmentation_config_hash"]
    assert _json_object(metadata["input_source_versions_json"]) == anchors["source_versions"]
    assert (
        _json_object(metadata["input_primary_identity_digests_json"])
        == anchors["primary_identity_digests"]
    )
    assert (
        _json_object(metadata["input_surface_lemma_digests_json"])
        == anchors["surface_lemma_digests"]
    )
    assert _json_object(metadata["input_analytical_digests_json"]) == anchors["analytical_digests"]
    assert (
        _json_object(metadata["input_oshb_supplement_digests_json"])
        == anchors["oshb_supplement_digests"]
    )

    observed_source_counts = {
        table: int(database.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in anchors["source_row_counts"]
    }
    assert observed_source_counts == anchors["source_row_counts"]


def test_all_stream_and_granularity_counts_are_exact(
    database: duckdb.DuckDBPyConnection,
    expected: dict[str, Any],
) -> None:
    rows = database.execute(
        """
        SELECT corpus, analysis_profile, analysis_reading, granularity,
               count(*) AS passage_count,
               sum(token_count) AS membership_rows,
               count(*) FILTER (WHERE reference_gap) AS reference_gap_count,
               count(*) FILTER (WHERE disputed_passage_flag) AS disputed_passage_count,
               count(*) FILTER (WHERE ketiv_structural_uncertainty)
                   AS ketiv_uncertain_count,
               sum(sensitivity_exclusion_count) AS sensitivity_exclusion_count
        FROM passages
        GROUP BY corpus, analysis_profile, analysis_reading, granularity
        """
    ).fetchall()
    observed = {_key(*row[:4]): [int(value) for value in row[4:]] for row in rows}
    assert observed == expected["stream_counts"]


def test_critical_core_excludes_exactly_the_three_governed_regions(
    database: duckdb.DuckDBPyConnection,
    expected: dict[str, Any],
) -> None:
    rows = database.execute(
        """
        WITH edition AS (
          SELECT token_id, source_reference, source_position_in_corpus
          FROM passage_membership
          WHERE corpus = 'greek' AND analysis_profile = 'edition_complete'
            AND analysis_reading = 'source' AND granularity = 'verse'
        ), critical AS (
          SELECT token_id FROM passage_membership
          WHERE corpus = 'greek' AND analysis_profile = 'critical_core'
            AND analysis_reading = 'source' AND granularity = 'verse'
        )
        SELECT edition.token_id, edition.source_reference
        FROM edition ANTI JOIN critical USING (token_id)
        ORDER BY edition.source_position_in_corpus, edition.token_id
        """
    ).fetchall()
    exclusion = expected["critical_core_exclusions"]
    assert len(rows) == exclusion["excluded_token_count"]
    reference_counts = dict(sorted(Counter(str(row[1]) for row in rows).items()))
    assert len(reference_counts) == exclusion["excluded_reference_count"]
    assert reference_counts == exclusion["reference_token_counts"]
    digest = hashlib.sha256("".join(f"{row[0]}\n" for row in rows).encode("utf-8")).hexdigest()
    assert digest == exclusion["ordered_token_ids_sha256_lines"]

    region_counts = {
        "JHN 7:53-8:11": sum(
            count for reference, count in reference_counts.items() if reference.startswith("JHN ")
        ),
        "MRK 16:9-16:20": sum(
            count
            for reference, count in reference_counts.items()
            if reference.startswith("MRK 16:") and 9 <= int(reference.split(":")[1]) <= 20
        ),
        "MRK 16:99": reference_counts.get("MRK 16:99", 0),
    }
    assert region_counts == exclusion["region_token_counts"]


def test_reference_gap_and_disputed_counts_are_exact(
    database: duckdb.DuckDBPyConnection,
    expected: dict[str, Any],
) -> None:
    gap_rows = database.execute(
        """
        SELECT corpus, analysis_profile, analysis_reading, granularity, count(*)
        FROM passages WHERE reference_gap
        GROUP BY corpus, analysis_profile, analysis_reading, granularity
        """
    ).fetchall()
    observed_gaps = {_key(*row[:4]): int(row[4]) for row in gap_rows}
    assert observed_gaps == expected["reference_gap_counts"]

    disputed_rows = database.execute(
        """
        SELECT corpus, analysis_profile, analysis_reading, granularity,
               disputed_passage_ids_json, count(*)
        FROM passages WHERE disputed_passage_flag
        GROUP BY corpus, analysis_profile, analysis_reading, granularity,
                 disputed_passage_ids_json
        """
    ).fetchall()
    observed_disputed = {
        _key(*row[:4], json.loads(row[4])[0]): int(row[5]) for row in disputed_rows
    }
    assert observed_disputed == expected["disputed_passage_counts"]


def test_ketiv_uncertainty_and_all_explicit_exclusions_are_exact(
    database: duckdb.DuckDBPyConnection,
    expected: dict[str, Any],
) -> None:
    uncertainty_rows = database.execute(
        """
        SELECT analysis_profile, granularity, count(*),
               sum(sensitivity_exclusion_count)
        FROM passages
        WHERE corpus = 'hebrew' AND analysis_reading = 'ketiv'
          AND ketiv_structural_uncertainty
        GROUP BY analysis_profile, granularity
        """
    ).fetchall()
    observed_uncertainty = {
        _key(*row[:2]): [int(value) for value in row[2:]] for row in uncertainty_rows
    }
    assert observed_uncertainty == expected["ketiv_uncertainty_counts"]

    exclusion_rows = database.execute(
        """
        SELECT analysis_profile, analysis_reading, granularity, reason_code,
               resolution_status, count(*), count(DISTINCT token_id),
               count(DISTINCT locus_id)
        FROM segmentation_exclusions
        GROUP BY analysis_profile, analysis_reading, granularity, reason_code,
                 resolution_status
        """
    ).fetchall()
    observed_exclusions = {
        _key(*row[:5]): [int(value) for value in row[5:]] for row in exclusion_rows
    }
    assert observed_exclusions == expected["exclusion_counts"]

    missing_from_verse = database.execute(
        """
        SELECT count(*) FROM segmentation_exclusions AS exclusion
        WHERE NOT EXISTS (
          SELECT 1 FROM passage_membership AS membership
          WHERE membership.token_id = exclusion.token_id
            AND membership.corpus = exclusion.corpus
            AND membership.analysis_profile = exclusion.analysis_profile
            AND membership.analysis_reading = exclusion.analysis_reading
            AND membership.granularity = 'verse'
        )
        """
    ).fetchone()
    assert missing_from_verse == (0,)


def test_selected_passage_ids_and_reconstruction_hashes_are_stable(
    database: duckdb.DuckDBPyConnection,
    expected: dict[str, Any],
) -> None:
    selected = expected["selected_passages"]
    passage_ids = [item["passage_id"] for item in selected.values()]
    placeholders = ",".join("?" for _ in passage_ids)
    cursor = database.execute(
        f"""
        SELECT passage_id, start_reference, end_reference, granularity, token_count,
               reference_gap, disputed_passage_flag, ketiv_structural_uncertainty,
               surface_text, normalized_text, unpointed_text, folded_text
        FROM passages WHERE passage_id IN ({placeholders})
        """,
        passage_ids,
    )
    columns = [str(description[0]) for description in cursor.description]
    passage_rows = {row[0]: dict(zip(columns, row, strict=True)) for row in cursor.fetchall()}
    membership_counts = dict(
        database.execute(
            f"""
            SELECT passage_id, count(*) FROM passage_membership
            WHERE passage_id IN ({placeholders}) GROUP BY passage_id
            """,
            passage_ids,
        ).fetchall()
    )
    assert set(passage_rows) == set(passage_ids)

    for item in selected.values():
        row = passage_rows[item["passage_id"]]
        for field in (
            "start_reference",
            "end_reference",
            "granularity",
            "token_count",
            "reference_gap",
            "disputed_passage_flag",
            "ketiv_structural_uncertainty",
        ):
            assert row[field] == item[field]
        assert int(membership_counts[item["passage_id"]]) == item["membership_count"]
        reconstruction = {
            field: row[field]
            for field in (
                "surface_text",
                "normalized_text",
                "unpointed_text",
                "folded_text",
            )
        }
        digest = hashlib.sha256(
            json.dumps(
                reconstruction,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        assert digest == item["reconstruction_sha256"]
