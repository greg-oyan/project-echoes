"""Bounded payload hydration preserves complete rows and legacy canonical order."""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest

from echoes.final_discovery import disk_calibration as calibration


@pytest.fixture
def connection() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect() as database:
        database.execute("SET memory_limit='256MiB'")
        database.execute("SET threads=1")
        database.execute(
            "CREATE TABLE raw_evidence(candidate_pair_id VARCHAR, detector_id VARCHAR, "
            "raw_json VARCHAR)"
        )
        database.execute(
            "CREATE TABLE evidence_calibration_projection(candidate_pair_id VARCHAR, "
            "detector_id VARCHAR, normalized_score DOUBLE, ablated_score DOUBLE, "
            "empirical_p_value DOUBLE, normalization VARCHAR, null_family VARCHAR)"
        )
        identities = [
            (pair, detector) for pair in ("p", "pa", "paa", "pb") for detector in ("a", "ab", "b")
        ]
        for index, (pair, detector) in enumerate(reversed(identities)):
            database.execute(
                "INSERT INTO raw_evidence VALUES (?, ?, ?)",
                [pair, detector, f'{{"pair":"{pair}","detector":"{detector}"}}'],
            )
            database.execute(
                "INSERT INTO evidence_calibration_projection VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    pair,
                    detector,
                    index / 12,
                    None if index % 2 else index / 13,
                    (index + 1) / 13,
                    "empirical_percentile",
                    "stratified_permutation",
                ],
            )
        yield database


@pytest.mark.parametrize("batch_size", [1, 2, 5, 4096])
@pytest.mark.parametrize("calibrated", [False, True])
def test_bounded_ranges_equal_whole_table_oracle_across_prefix_and_pair_boundaries(
    connection: duckdb.DuckDBPyConnection, batch_size: int, calibrated: bool
) -> None:
    if calibrated:
        expected = connection.execute(
            "SELECT r.raw_json, c.normalized_score, c.ablated_score, c.empirical_p_value, "
            "c.normalization, c.null_family FROM raw_evidence r "
            "JOIN evidence_calibration_projection c USING(candidate_pair_id, detector_id) "
            "ORDER BY r.candidate_pair_id, r.detector_id"
        ).fetchall()
    else:
        expected = connection.execute(
            "SELECT detector_id, candidate_pair_id, raw_json FROM raw_evidence "
            "ORDER BY detector_id, candidate_pair_id"
        ).fetchall()
    assert (
        list(
            calibration._iter_bounded_raw_payload_rows(
                connection, batch_size=batch_size, calibrated=calibrated
            )
        )
        == expected
    )


@pytest.mark.parametrize("calibrated", [False, True])
def test_one_oversize_payload_is_preserved_without_losing_neighboring_rows(
    connection: duckdb.DuckDBPyConnection, calibrated: bool
) -> None:
    payload = '"' + "x" * (17 * 1024**2) + '"'
    connection.execute(
        "UPDATE raw_evidence SET raw_json=? WHERE candidate_pair_id='pa' AND detector_id='ab'",
        [payload],
    )
    rows = list(
        calibration._iter_bounded_raw_payload_rows(
            connection, batch_size=4096, calibrated=calibrated
        )
    )
    payload_index = 0 if calibrated else 2
    assert len(rows) == 12
    assert sum(row[payload_index] == payload for row in rows) == 1
    assert sum(len(str(row[payload_index])) < 100 for row in rows) == 11


def test_missing_numeric_projection_cannot_silently_drop_a_source_row(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        "DELETE FROM evidence_calibration_projection "
        "WHERE candidate_pair_id='pa' AND detector_id='ab'"
    )
    with pytest.raises(calibration.DiskCalibrationError, match="lost or repeated rows"):
        list(calibration._iter_bounded_raw_payload_rows(connection, batch_size=2, calibrated=True))


def test_bounded_raw_digest_preserves_legacy_logical_receipt(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    expected = calibration._logical_table_receipt(
        connection,
        query="SELECT detector_id,candidate_pair_id,raw_json FROM raw_evidence "
        "ORDER BY detector_id,candidate_pair_id",
        ordering="detector_id,candidate_pair_id",
        batch_size=5,
    )
    assert calibration._raw_evidence_table_receipt(connection, batch_size=2) == expected
