"""Bounded, disk-backed production detector calibration.

This module is the scale-safe counterpart to the small in-memory reference
implementation in :mod:`echoes.final_discovery.nulls`.  It deliberately keeps
the NumPy null generator call order identical while moving row validation,
joins, midrank normalization, and deterministic output ordering to DuckDB.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self, cast

import duckdb
import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
from duckdb.sqltypes import DOUBLE
from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.final_discovery.anomaly import PairFamilyScores, _disagreement, _stratum
from echoes.final_discovery.config import (
    DetectorRegistration,
    FinalDiscoveryConfig,
    final_discovery_config_sha256,
)
from echoes.final_discovery.features import candidate_pair_id, canonical_json, evidence_id
from echoes.final_discovery.models import (
    EvidenceFamily,
    EvidenceRow,
    PassageRecord,
    RawEvidence,
)
from echoes.final_discovery.nulls import (
    DetectorNullCalibrationRow,
    _vectorized_detector_exceedances,
)
from echoes.final_discovery.storage import (
    FinalDiscoveryStorageError,
    StreamArtifactReceipt,
    inspect_jsonl_file,
    iter_canonical_jsonl,
    merge_sorted_jsonl,
    write_json_atomic_new,
    write_jsonl_stream_atomic,
)

_MINIMUM_MEMORY_BYTES = 256 * 1024**2
_M7_SOURCE_NULL_FAMILIES = (
    "within_book_reassignment",
    "frequency_preserving_synthetic",
)
_MECHANISMS = {
    "within_book_reassignment": "within_stratum_reassignment_without_replacement",
    "stratified_score_bootstrap": "within_stratum_score_resampling_with_replacement",
    "stratified_permutation": "within_stratum_permutation_without_replacement",
}

EVIDENCE_FILE_NAME = "evidence.jsonl"
DETECTOR_NULL_FILE_NAME = "detector-null-calibration.jsonl"
CALIBRATION_STATE_FILE_NAME = "detector-calibration-state.jsonl"
PROVENANCE_FILE_NAME = "detector-calibration-provenance.json"
RECEIPT_FILE_NAME = "detector-calibration-receipt.json"
ANOMALY_INPUT_FILE_NAME: Literal["pair-family-scores.jsonl"] = "pair-family-scores.jsonl"
ANOMALY_INPUT_RECEIPT_FILE_NAME = "pair-family-scores-receipt.json"
ANOMALY_EVIDENCE_FILE_NAME: Literal["anomaly-evidence.jsonl"] = "anomaly-evidence.jsonl"
ANOMALY_EVIDENCE_RECEIPT_FILE_NAME = "anomaly-evidence-receipt.json"


class DiskCalibrationError(ValueError):
    """Raised when disk-backed production calibration cannot be authenticated."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PairStratum(_FrozenModel):
    """One exact candidate-pair to registered-confounder-stratum mapping."""

    candidate_pair_id: str = Field(min_length=1)
    stratum: str = Field(min_length=1)


class DetectorStratumCalibrationState(_FrozenModel):
    """Compact replacement for persisted per-stratum reference-score arrays."""

    detector_id: str = Field(min_length=1)
    stratum: str = Field(min_length=1)
    normalization: Literal["empirical_percentile", "zscore_within_stratum", "rank_percentile"]
    null_family: Literal[
        "within_book_reassignment", "stratified_score_bootstrap", "stratified_permutation"
    ]
    seed: int = Field(ge=0)
    iterations: int = Field(ge=1)
    reference_score_count: int = Field(ge=1)
    reference_score_min: float
    reference_score_max: float
    reference_score_mean: float
    reference_score_population_variance: float = Field(ge=0.0)
    reference_scores_ordered_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_ordering: Literal["candidate_pair_id_ascending"] = "candidate_pair_id_ascending"

    @model_validator(mode="after")
    def range_and_moments_are_finite(self) -> Self:
        values = (
            self.reference_score_min,
            self.reference_score_max,
            self.reference_score_mean,
            self.reference_score_population_variance,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("detector calibration state requires finite score statistics")
        if self.reference_score_min > self.reference_score_max:
            raise ValueError("detector calibration state has an inverted score range")
        return self


class CalibrationInputFileReceipt(_FrozenModel):
    source_index: int = Field(ge=0)
    file_name: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CalibrationOutputFileReceipt(_FrozenModel):
    file_name: str = Field(min_length=1)
    row_count: int = Field(ge=1)
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CalibrationTableReceipt(_FrozenModel):
    row_count: int = Field(ge=1)
    logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    ordering: str = Field(min_length=1)


class DiskDetectorCalibrationReceipt(_FrozenModel):
    """Portable authentication receipt for the complete calibration bundle."""

    schema_version: Literal[1] = 1
    algorithm: Literal["disk-backed-detector-calibration-v1"] = (
        "disk-backed-detector-calibration-v1"
    )
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    iterations: int = Field(ge=1)
    duckdb_memory_limit_bytes: int = Field(ge=_MINIMUM_MEMORY_BYTES)
    duckdb_threads: int = Field(ge=1)
    ingestion_batch_size: int = Field(ge=1)
    reference_score_arrays_persisted: Literal[False] = False
    raw_input_files: tuple[CalibrationInputFileReceipt, ...] = Field(min_length=1)
    raw_evidence_row_count: int = Field(ge=1)
    candidate_pair_count: int = Field(ge=1)
    detector_count: int = Field(ge=1)
    detector_stratum_count: int = Field(ge=1)
    table_receipts: dict[str, CalibrationTableReceipt]
    output_files: dict[str, CalibrationOutputFileReceipt]

    @model_validator(mode="after")
    def inventories_are_exact(self) -> Self:
        expected_tables = {
            "raw_evidence",
            "pair_strata",
            "detector_null_calibration",
            "detector_stratum_state",
            "calibrated_evidence",
        }
        expected_outputs = {
            EVIDENCE_FILE_NAME,
            DETECTOR_NULL_FILE_NAME,
            CALIBRATION_STATE_FILE_NAME,
            PROVENANCE_FILE_NAME,
        }
        if set(self.table_receipts) != expected_tables:
            raise ValueError("disk calibration receipt has an unexpected table inventory")
        if set(self.output_files) != expected_outputs:
            raise ValueError("disk calibration receipt has an unexpected output inventory")
        if sum(item.row_count for item in self.raw_input_files) != self.raw_evidence_row_count:
            raise ValueError("raw input file counts do not reconcile with ingested evidence")
        for table in ("raw_evidence", "detector_null_calibration", "calibrated_evidence"):
            if self.table_receipts[table].row_count != self.raw_evidence_row_count:
                raise ValueError(f"{table} count does not reconcile with raw evidence")
        if self.table_receipts["pair_strata"].row_count != self.candidate_pair_count:
            raise ValueError("pair-strata count does not reconcile with the pair population")
        if self.table_receipts["detector_stratum_state"].row_count != (self.detector_stratum_count):
            raise ValueError("detector-stratum state count does not reconcile")
        return self


@dataclass(frozen=True, slots=True)
class DiskDetectorCalibrationResult:
    """Resolved files from one atomically published calibration bundle."""

    output_directory: Path
    evidence_path: Path
    detector_null_path: Path
    calibration_state_path: Path
    provenance_path: Path
    receipt_path: Path
    receipt: DiskDetectorCalibrationReceipt


class AnomalyPairProjectionReceipt(_FrozenModel):
    """Portable receipt for the streamed Stage 6 anomaly input projection."""

    schema_version: Literal[1] = 1
    algorithm: Literal["disk-backed-anomaly-pair-projection-v1"] = (
        "disk-backed-anomaly-pair-projection-v1"
    )
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duckdb_memory_limit_bytes: int = Field(ge=_MINIMUM_MEMORY_BYTES)
    duckdb_threads: int = Field(ge=1)
    ingestion_batch_size: int = Field(ge=1)
    raw_input_files: tuple[CalibrationInputFileReceipt, ...] = Field(min_length=1)
    raw_evidence_row_count: int = Field(ge=1)
    eligible_pair_count: int = Field(ge=1)
    output_file_name: Literal["pair-family-scores.jsonl"] = ANOMALY_INPUT_FILE_NAME
    output_size_bytes: int = Field(ge=1)
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_ordering: Literal["candidate_pair_id"] = "candidate_pair_id"
    detector_normalization: Literal["global_exact_empirical_midrank"] = (
        "global_exact_empirical_midrank"
    )


@dataclass(frozen=True, slots=True)
class AnomalyPairProjectionResult:
    output_directory: Path
    pair_family_scores_path: Path
    receipt_path: Path
    receipt: AnomalyPairProjectionReceipt


class AnomalyEvidenceReceipt(_FrozenModel):
    """Resource and lineage receipt for bounded robust anomaly calibration."""

    schema_version: Literal[1] = 1
    algorithm: Literal["disk-backed-robust-anomaly-v1"] = "disk-backed-robust-anomaly-v1"
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duckdb_memory_limit_bytes: int = Field(ge=_MINIMUM_MEMORY_BYTES)
    duckdb_threads: int = Field(ge=1)
    ingestion_batch_size: int = Field(ge=1)
    input_file: CalibrationInputFileReceipt
    passage_count: int = Field(ge=2)
    passage_projection_logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_pair_count: int = Field(ge=1)
    anomaly_stratum_count: int = Field(ge=1)
    stratum_state_logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_artifact_id: str = Field(min_length=1)
    source_artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_file_name: Literal["anomaly-evidence.jsonl"] = ANOMALY_EVIDENCE_FILE_NAME
    output_size_bytes: int = Field(ge=1)
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_ordering: Literal["candidate_pair_id,detector_id"] = "candidate_pair_id,detector_id"
    robust_scale_constant: float = Field(default=1.4826, ge=1.4826, le=1.4826)
    zero_mad_method: Literal["exact_empirical_midrank"] = "exact_empirical_midrank"

    @model_validator(mode="after")
    def input_and_output_counts_reconcile(self) -> Self:
        if self.input_file.row_count != self.candidate_pair_count:
            raise ValueError("anomaly input and output candidate counts differ")
        return self


@dataclass(frozen=True, slots=True)
class AnomalyEvidenceResult:
    output_directory: Path
    anomaly_evidence_path: Path
    receipt_path: Path
    receipt: AnomalyEvidenceReceipt


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _quoted_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _pair_strata_rows(
    values: Mapping[str, str] | Iterable[PairStratum],
) -> Iterator[PairStratum]:
    if isinstance(values, Mapping):
        for pair_id in sorted(values):
            yield PairStratum(candidate_pair_id=pair_id, stratum=values[pair_id])
        return
    yield from values


def _validate_m7_trace(row: RawEvidence, config: FinalDiscoveryConfig) -> None:
    if row.detector_id != "m7_lexical_rrf" or not config.calibration.require_both_m7_null_families:
        return
    try:
        trace = json.loads(row.trace_json)
    except json.JSONDecodeError as exc:
        raise DiskCalibrationError("M7 evidence has an invalid JSON trace") from exc
    if not isinstance(trace, dict) or trace.get("m7_both_null_families_present") is not True:
        raise DiskCalibrationError(
            "production M7 evidence must authenticate both canonical M7 null families"
        )


def _registration_for_raw(
    row: RawEvidence, registrations: Mapping[str, DetectorRegistration]
) -> DetectorRegistration:
    try:
        registration = registrations[row.detector_id]
    except KeyError as exc:
        raise DiskCalibrationError(
            f"unregistered detector in production calibration: {row.detector_id}"
        ) from exc
    expected_independence = registration.counts_for_independence and (
        not row.contains_english_derived_evidence or row.original_language_evidence_remains
    )
    if (
        row.family != registration.family
        or row.independence_group != registration.independence_group
        or row.counts_for_independence != expected_independence
        or (
            row.contains_english_derived_evidence
            and not registration.contains_english_derived_evidence
        )
        or (row.original_language_evidence_remains and not registration.original_language_capable)
    ):
        raise DiskCalibrationError(
            f"raw evidence lineage disagrees with registration: {row.detector_id}"
        )
    return registration


def _create_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE detector_registry (
            detector_id VARCHAR NOT NULL,
            family VARCHAR NOT NULL,
            independence_group VARCHAR NOT NULL,
            normalization VARCHAR NOT NULL,
            null_family VARCHAR NOT NULL,
            seed BIGINT NOT NULL
        );
        CREATE TABLE raw_evidence (
            candidate_pair_id VARCHAR NOT NULL,
            passage_a_id VARCHAR NOT NULL,
            passage_b_id VARCHAR NOT NULL,
            detector_id VARCHAR NOT NULL,
            family VARCHAR NOT NULL,
            raw_score DOUBLE NOT NULL,
            english_ablation_raw_score DOUBLE,
            formulaic_control BOOLEAN NOT NULL,
            evidence_id VARCHAR NOT NULL,
            raw_json VARCHAR NOT NULL
        );
        CREATE TABLE pair_strata (
            candidate_pair_id VARCHAR NOT NULL,
            stratum VARCHAR NOT NULL
        );
        CREATE TABLE detector_null_calibration (
            candidate_pair_id VARCHAR NOT NULL,
            detector_id VARCHAR NOT NULL,
            stratum VARCHAR NOT NULL,
            observed_score DOUBLE NOT NULL,
            null_exceedance_count BIGINT NOT NULL,
            empirical_p_value DOUBLE NOT NULL,
            iterations BIGINT NOT NULL,
            null_family VARCHAR NOT NULL,
            seed BIGINT NOT NULL,
            mechanism VARCHAR NOT NULL
        );
        CREATE TABLE detector_stratum_state (
            detector_id VARCHAR NOT NULL,
            stratum VARCHAR NOT NULL,
            normalization VARCHAR NOT NULL,
            null_family VARCHAR NOT NULL,
            seed BIGINT NOT NULL,
            iterations BIGINT NOT NULL,
            reference_score_count BIGINT NOT NULL,
            reference_score_min DOUBLE NOT NULL,
            reference_score_max DOUBLE NOT NULL,
            reference_score_mean DOUBLE NOT NULL,
            reference_score_population_variance DOUBLE NOT NULL,
            reference_scores_ordered_sha256 VARCHAR NOT NULL
        );
        """
    )


_ARROW_INSERT_COLUMNS = {
    "detector_registry": (
        "detector_id",
        "family",
        "independence_group",
        "normalization",
        "null_family",
        "seed",
    ),
    "raw_evidence": (
        "candidate_pair_id",
        "passage_a_id",
        "passage_b_id",
        "detector_id",
        "family",
        "raw_score",
        "english_ablation_raw_score",
        "formulaic_control",
        "evidence_id",
        "raw_json",
    ),
    "pair_strata": ("candidate_pair_id", "stratum"),
    "detector_null_calibration": (
        "candidate_pair_id",
        "detector_id",
        "stratum",
        "observed_score",
        "null_exceedance_count",
        "empirical_p_value",
        "iterations",
        "null_family",
        "seed",
        "mechanism",
    ),
    "detector_stratum_state": (
        "detector_id",
        "stratum",
        "normalization",
        "null_family",
        "seed",
        "iterations",
        "reference_score_count",
        "reference_score_min",
        "reference_score_max",
        "reference_score_mean",
        "reference_score_population_variance",
        "reference_scores_ordered_sha256",
    ),
    "anomaly_observations": (
        "candidate_pair_id",
        "passage_a_id",
        "passage_b_id",
        "stratum",
        "disagreement",
        "family_scores_json",
        "formulaic_control",
    ),
}


def _insert_arrow_rows(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    rows: Sequence[tuple[object, ...]],
) -> None:
    """Insert one typed in-process Arrow batch without Python row binding."""

    if not rows:
        return
    try:
        column_names = _ARROW_INSERT_COLUMNS[table_name]
    except KeyError as exc:
        raise DiskCalibrationError(f"unregistered Arrow insert table: {table_name}") from exc
    if any(len(row) != len(column_names) for row in rows):
        raise DiskCalibrationError(f"invalid Arrow row width for table: {table_name}")
    batch_name = f"echoes_{table_name}_arrow_batch"
    batch = pa.table(
        {
            column_name: [row[index] for row in rows]
            for index, column_name in enumerate(column_names)
        }
    )
    columns_sql = ",".join(column_names)
    connection.register(batch_name, batch)
    try:
        connection.execute(
            f"INSERT INTO {table_name} ({columns_sql}) SELECT {columns_sql} FROM {batch_name}"
        )
    finally:
        connection.unregister(batch_name)


def _insert_registry(
    connection: duckdb.DuckDBPyConnection,
    config: FinalDiscoveryConfig,
) -> None:
    rows: list[tuple[object, ...]] = []
    for registration in sorted(config.detectors, key=lambda item: item.detector_id):
        try:
            seed = config.calibration.seeds[registration.null_family]
        except KeyError as exc:
            raise DiskCalibrationError(
                f"registered null family has no registered seed: {registration.null_family}"
            ) from exc
        if registration.null_family not in _MECHANISMS:
            raise DiskCalibrationError(
                f"registered null family has no mechanism: {registration.null_family}"
            )
        rows.append(
            (
                registration.detector_id,
                registration.family,
                registration.independence_group,
                registration.normalization,
                registration.null_family,
                seed,
            )
        )
    _insert_arrow_rows(connection, "detector_registry", rows)


def _ingest_raw_evidence(
    connection: duckdb.DuckDBPyConnection,
    raw_evidence_paths: Sequence[Path],
    *,
    config: FinalDiscoveryConfig,
    batch_size: int,
) -> tuple[tuple[CalibrationInputFileReceipt, ...], int]:
    if not raw_evidence_paths:
        raise DiskCalibrationError("disk calibration requires raw-evidence inputs")
    resolved = [path.resolve() for path in raw_evidence_paths]
    if len(resolved) != len(set(resolved)):
        raise DiskCalibrationError("raw-evidence input paths must be unique")
    input_receipts: list[CalibrationInputFileReceipt] = []
    for index, path in enumerate(raw_evidence_paths):
        if not path.is_file():
            raise DiskCalibrationError(f"raw-evidence input is not a regular file: {path}")
        inspected = inspect_jsonl_file(path)
        input_receipts.append(
            CalibrationInputFileReceipt(
                source_index=index,
                file_name=path.name,
                row_count=inspected.row_count,
                size_bytes=inspected.size_bytes,
                sha256=inspected.sha256,
            )
        )
    registrations = {item.detector_id: item for item in config.detectors}
    insert_rows: list[tuple[object, ...]] = []
    row_count = 0
    for row in merge_sorted_jsonl(
        raw_evidence_paths,
        RawEvidence,
        key=lambda item: (item.candidate_pair_id,),
    ):
        _registration_for_raw(row, registrations)
        _validate_m7_trace(row, config)
        expected_pair_id = candidate_pair_id(row.passage_a_id, row.passage_b_id)
        if row.candidate_pair_id != expected_pair_id:
            raise DiskCalibrationError(
                f"raw evidence candidate-pair identity is invalid: {row.candidate_pair_id}"
            )
        canonical_raw = _canonical_json_bytes(row.model_dump(mode="json")).decode("ascii")
        insert_rows.append(
            (
                row.candidate_pair_id,
                row.passage_a_id,
                row.passage_b_id,
                row.detector_id,
                row.family,
                row.raw_score,
                row.english_ablation_raw_score,
                row.source_quality is not None and row.source_quality.formulaic_language,
                evidence_id(row.candidate_pair_id, row.detector_id, row.source_artifact_sha256),
                canonical_raw,
            )
        )
        row_count += 1
        if len(insert_rows) >= batch_size:
            _insert_arrow_rows(connection, "raw_evidence", insert_rows)
            insert_rows.clear()
    if insert_rows:
        _insert_arrow_rows(connection, "raw_evidence", insert_rows)
    if row_count < 1:
        raise DiskCalibrationError("production detector calibration requires evidence")
    expected_count = sum(item.row_count for item in input_receipts)
    if row_count != expected_count:
        raise DiskCalibrationError("streamed raw-evidence count differs from input file receipts")
    return tuple(input_receipts), row_count


def _ingest_pair_strata(
    connection: duckdb.DuckDBPyConnection,
    values: Mapping[str, str] | Iterable[PairStratum],
    *,
    batch_size: int,
) -> int:
    insert_rows: list[tuple[object, ...]] = []
    row_count = 0
    for raw_row in _pair_strata_rows(values):
        row = PairStratum.model_validate(raw_row)
        insert_rows.append((row.candidate_pair_id, row.stratum))
        row_count += 1
        if len(insert_rows) >= batch_size:
            _insert_arrow_rows(connection, "pair_strata", insert_rows)
            insert_rows.clear()
    if insert_rows:
        _insert_arrow_rows(connection, "pair_strata", insert_rows)
    if row_count < 1:
        raise DiskCalibrationError("production detector calibration requires pair strata")
    return row_count


def _first_row(connection: duckdb.DuckDBPyConnection, query: str) -> tuple[object, ...] | None:
    return cast(tuple[object, ...] | None, connection.execute(query).fetchone())


def _validate_ingested_tables(
    connection: duckdb.DuckDBPyConnection,
    *,
    raw_count: int,
    strata_count: int,
) -> tuple[int, int]:
    duplicate = _first_row(
        connection,
        """
        SELECT detector_id,candidate_pair_id,count(*)
        FROM raw_evidence
        GROUP BY detector_id,candidate_pair_id
        HAVING count(*)<>1
        ORDER BY detector_id,candidate_pair_id
        LIMIT 1
        """,
    )
    if duplicate is not None:
        raise DiskCalibrationError(
            "production detector calibration requires one score per detector/pair: "
            f"{duplicate[0]}/{duplicate[1]}"
        )
    duplicate_stratum = _first_row(
        connection,
        """
        SELECT candidate_pair_id,count(*)
        FROM pair_strata
        GROUP BY candidate_pair_id
        HAVING count(*)<>1
        ORDER BY candidate_pair_id
        LIMIT 1
        """,
    )
    if duplicate_stratum is not None:
        raise DiskCalibrationError(f"pair-stratum mapping is duplicate: {duplicate_stratum[0]}")
    inconsistent_pair = _first_row(
        connection,
        """
        SELECT candidate_pair_id
        FROM raw_evidence
        GROUP BY candidate_pair_id
        HAVING count(DISTINCT passage_a_id)<>1 OR count(DISTINCT passage_b_id)<>1
        ORDER BY candidate_pair_id
        LIMIT 1
        """,
    )
    if inconsistent_pair is not None:
        raise DiskCalibrationError(f"raw evidence pair identity disagrees: {inconsistent_pair[0]}")
    nonfinite = _first_row(
        connection,
        """
        SELECT detector_id,candidate_pair_id
        FROM raw_evidence
        WHERE NOT isfinite(raw_score)
           OR (english_ablation_raw_score IS NOT NULL
               AND NOT isfinite(english_ablation_raw_score))
        ORDER BY detector_id,candidate_pair_id
        LIMIT 1
        """,
    )
    if nonfinite is not None:
        raise DiskCalibrationError(
            f"detector {nonfinite[0]} has a non-finite score: {nonfinite[1]}"
        )
    missing = _first_row(
        connection,
        """
        SELECT DISTINCT r.candidate_pair_id
        FROM raw_evidence r
        LEFT JOIN pair_strata s USING (candidate_pair_id)
        WHERE s.candidate_pair_id IS NULL
        ORDER BY r.candidate_pair_id
        LIMIT 1
        """,
    )
    extra = _first_row(
        connection,
        """
        SELECT s.candidate_pair_id
        FROM pair_strata s
        LEFT JOIN (SELECT DISTINCT candidate_pair_id FROM raw_evidence) r
          USING (candidate_pair_id)
        WHERE r.candidate_pair_id IS NULL
        ORDER BY s.candidate_pair_id
        LIMIT 1
        """,
    )
    if missing is not None or extra is not None:
        raise DiskCalibrationError(
            "production detector strata must cover the exact raw-evidence pair population"
        )
    counts = cast(
        tuple[object, object, object],
        connection.execute(
            """
            SELECT
                (SELECT count(*) FROM raw_evidence),
                (SELECT count(DISTINCT candidate_pair_id) FROM raw_evidence),
                (SELECT count(DISTINCT detector_id) FROM raw_evidence)
            """
        ).fetchone(),
    )
    observed_raw_count = int(cast(int, counts[0]))
    pair_count = int(cast(int, counts[1]))
    detector_count = int(cast(int, counts[2]))
    if observed_raw_count != raw_count or strata_count != pair_count:
        raise DiskCalibrationError("ingested table counts do not reconcile")
    evidence_collision = _first_row(
        connection,
        """
        SELECT evidence_id,count(*)
        FROM raw_evidence
        GROUP BY evidence_id
        HAVING count(*)<>1
        ORDER BY evidence_id
        LIMIT 1
        """,
    )
    if evidence_collision is not None:
        raise DiskCalibrationError(f"detector evidence IDs collide: {evidence_collision[0]}")
    return pair_count, detector_count


def _create_normalization_values(connection: duckdb.DuckDBPyConnection) -> None:
    """Compute exact tie-aware empirical midranks for raw and ablated values."""

    connection.execute(
        """
        CREATE TABLE normalization_values AS
        WITH joined AS (
            SELECT r.detector_id,s.stratum,r.raw_score,r.english_ablation_raw_score
            FROM raw_evidence r JOIN pair_strata s USING (candidate_pair_id)
        ),
        requested_values AS (
            SELECT detector_id,stratum,raw_score AS value FROM joined
            UNION
            SELECT detector_id,stratum,english_ablation_raw_score AS value
            FROM joined WHERE english_ablation_raw_score IS NOT NULL
        ),
        reference_bins AS (
            SELECT detector_id,stratum,raw_score AS value,count(*)::BIGINT AS tied_count
            FROM joined GROUP BY detector_id,stratum,raw_score
        ),
        value_grid AS (
            SELECT
                v.detector_id,
                v.stratum,
                v.value,
                coalesce(b.tied_count,0)::BIGINT AS tied_count
            FROM requested_values v
            LEFT JOIN reference_bins b USING (detector_id,stratum,value)
        ),
        ranked AS (
            SELECT
                *,
                coalesce(
                    sum(tied_count) OVER (
                        PARTITION BY detector_id,stratum ORDER BY value
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ),
                    0
                )::BIGINT AS below_count,
                sum(tied_count) OVER (
                    PARTITION BY detector_id,stratum
                )::BIGINT AS reference_count
            FROM value_grid
        )
        SELECT
            ranked.detector_id,
            ranked.stratum,
            ranked.value,
            CASE
                WHEN registry.normalization IN ('empirical_percentile','rank_percentile')
                THEN (below_count + 0.5 * tied_count) / reference_count
                ELSE NULL
            END::DOUBLE AS normalized_score
        FROM ranked
        JOIN detector_registry registry USING (detector_id)
        """
    )


def _iter_detector_strata(
    connection: duckdb.DuckDBPyConnection,
    *,
    batch_size: int,
) -> Iterator[tuple[str, str, tuple[str, ...], np.ndarray]]:
    """Stream every detector/stratum once in the registered RNG call order."""

    reader = connection.cursor()
    try:
        cursor = reader.execute(
            """
            SELECT r.detector_id,s.stratum,r.candidate_pair_id,r.raw_score
            FROM raw_evidence r JOIN pair_strata s USING (candidate_pair_id)
            ORDER BY r.detector_id,s.stratum,r.candidate_pair_id
            """
        )
        current_key: tuple[str, str] | None = None
        pair_ids: list[str] = []
        scores: list[float] = []
        while rows := cursor.fetchmany(batch_size):
            for raw_detector_id, raw_stratum, raw_pair_id, raw_score in rows:
                key = str(raw_detector_id), str(raw_stratum)
                if current_key is not None and key != current_key:
                    observed = np.asarray(scores, dtype=np.float64)
                    if not np.isfinite(observed).all():
                        raise DiskCalibrationError(
                            f"detector {current_key[0]} has a non-finite score"
                        )
                    yield current_key[0], current_key[1], tuple(pair_ids), observed
                    pair_ids = []
                    scores = []
                current_key = key
                pair_ids.append(str(raw_pair_id))
                scores.append(float(raw_score))
        if current_key is not None:
            observed = np.asarray(scores, dtype=np.float64)
            if not np.isfinite(observed).all():
                raise DiskCalibrationError(f"detector {current_key[0]} has a non-finite score")
            yield current_key[0], current_key[1], tuple(pair_ids), observed
    finally:
        reader.close()


def _score_statistics(observed: np.ndarray) -> tuple[float, float, str]:
    mean = math.fsum(float(value) for value in observed) / len(observed)
    variance = math.fsum((float(value) - mean) ** 2 for value in observed) / len(observed)
    digest = hashlib.sha256()
    for value in observed:
        digest.update(struct.pack(">d", float(value)))
    return mean, variance, digest.hexdigest()


def _populate_zscore_values(connection: duckdb.DuckDBPyConnection) -> None:
    """Set every z-score normalization in one exact Python-UDF table update."""

    function_name = "echoes_normal_score"

    def normal_score(value: float, mean: float, variance: float) -> float:
        if variance == 0.0:
            return 0.5
        z_score = (value - mean) / math.sqrt(variance)
        return 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))

    connection.create_function(function_name, normal_score, [DOUBLE, DOUBLE, DOUBLE], DOUBLE)
    try:
        connection.execute(
            f"""
            UPDATE normalization_values AS normalized
            SET normalized_score={function_name}(
                normalized.value,
                state.reference_score_mean,
                state.reference_score_population_variance
            )
            FROM detector_stratum_state AS state
            WHERE normalized.detector_id=state.detector_id
              AND normalized.stratum=state.stratum
              AND state.normalization='zscore_within_stratum'
            """
        )
    finally:
        connection.remove_function(function_name)


def _append_null_rows(
    connection: duckdb.DuckDBPyConnection,
    pending_rows: list[tuple[object, ...]],
    detector_id: str,
    stratum: str,
    pair_ids: Sequence[str],
    observed: np.ndarray,
    exceedances: np.ndarray,
    *,
    registration: DetectorRegistration,
    seed: int,
    iterations: int,
    batch_size: int,
) -> None:
    if len(pair_ids) != len(observed) or len(observed) != len(exceedances):
        raise DiskCalibrationError(
            f"null exceedance count differs from detector stratum: {detector_id}/{stratum}"
        )
    mechanism = _MECHANISMS[registration.null_family]
    for offset in range(len(observed)):
        count = int(exceedances[offset])
        pending_rows.append(
            (
                pair_ids[offset],
                detector_id,
                stratum,
                float(observed[offset]),
                count,
                (count + 1) / (iterations + 1),
                iterations,
                registration.null_family,
                seed,
                mechanism,
            )
        )
        if len(pending_rows) >= batch_size:
            _insert_arrow_rows(connection, "detector_null_calibration", pending_rows)
            pending_rows.clear()


def _calibrate_detector_strata(
    connection: duckdb.DuckDBPyConnection,
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
    batch_size: int,
) -> dict[str, dict[str, object]]:
    registrations = {item.detector_id: item for item in config.detectors}
    provenance: dict[str, dict[str, object]] = {}
    strata_by_detector: dict[str, int] = {}
    random_source_by_detector: dict[str, np.random.Generator] = {}
    pending_null_rows: list[tuple[object, ...]] = []
    state_rows: list[tuple[object, ...]] = []
    for detector_id, stratum, pair_ids, observed in _iter_detector_strata(
        connection,
        batch_size=batch_size,
    ):
        registration = registrations[detector_id]
        seed = config.calibration.seeds[registration.null_family]
        random_source = random_source_by_detector.get(detector_id)
        if random_source is None:
            random_source = np.random.default_rng(seed)
            random_source_by_detector[detector_id] = random_source
        strata_by_detector[detector_id] = strata_by_detector.get(detector_id, 0) + 1
        mean, variance, reference_sha256 = _score_statistics(observed)
        exceedances = _vectorized_detector_exceedances(
            observed,
            null_family=registration.null_family,
            iterations=iterations,
            random_source=random_source,
        )
        _append_null_rows(
            connection,
            pending_null_rows,
            detector_id,
            stratum,
            pair_ids,
            observed,
            exceedances,
            registration=registration,
            seed=seed,
            iterations=iterations,
            batch_size=batch_size,
        )
        state_rows.append(
            (
                detector_id,
                stratum,
                registration.normalization,
                registration.null_family,
                seed,
                iterations,
                len(observed),
                float(np.min(observed)),
                float(np.max(observed)),
                mean,
                variance,
                reference_sha256,
            )
        )
    _insert_arrow_rows(connection, "detector_null_calibration", pending_null_rows)
    _insert_arrow_rows(connection, "detector_stratum_state", state_rows)
    _populate_zscore_values(connection)
    for detector_id in sorted(strata_by_detector):
        registration = registrations[detector_id]
        seed = config.calibration.seeds[registration.null_family]
        source_null_families: tuple[str, ...] = ()
        source_null_validation = "not_applicable"
        if detector_id == "m7_lexical_rrf":
            source_null_families = _M7_SOURCE_NULL_FAMILIES
            source_null_validation = "authenticated_m7_both_null_families_present_trace"
        provenance[detector_id] = {
            "detector_id": detector_id,
            "registered_null_family": registration.null_family,
            "registered_seed": seed,
            "iterations": iterations,
            "mechanism": _MECHANISMS[registration.null_family],
            "mechanism_scope": "detector_score_marginal_within_registered_pair_strata",
            "synthetic_feature_sequences_generated": False,
            "stratum_count": strata_by_detector[detector_id],
            "source_null_families": source_null_families,
            "source_null_validation": source_null_validation,
        }
    missing_normalization = _first_row(
        connection,
        """
        SELECT detector_id,stratum,value
        FROM normalization_values
        WHERE normalized_score IS NULL OR NOT isfinite(normalized_score)
        ORDER BY detector_id,stratum,value
        LIMIT 1
        """,
    )
    if missing_normalization is not None:
        raise DiskCalibrationError(
            "detector normalization is absent or non-finite: "
            f"{missing_normalization[0]}/{missing_normalization[1]}"
        )
    return provenance


def _iter_evidence(
    connection: duckdb.DuckDBPyConnection, *, batch_size: int
) -> Iterator[EvidenceRow]:
    cursor = connection.execute(
        """
        SELECT
            r.raw_json,
            normalized.normalized_score,
            ablated.normalized_score,
            nulls.empirical_p_value,
            registry.normalization,
            registry.null_family
        FROM raw_evidence r
        JOIN pair_strata strata USING (candidate_pair_id)
        JOIN detector_registry registry USING (detector_id)
        JOIN detector_null_calibration nulls USING (candidate_pair_id,detector_id,stratum)
        JOIN normalization_values normalized
          ON normalized.detector_id=r.detector_id
         AND normalized.stratum=strata.stratum
         AND normalized.value=r.raw_score
        LEFT JOIN normalization_values ablated
          ON ablated.detector_id=r.detector_id
         AND ablated.stratum=strata.stratum
         AND ablated.value=r.english_ablation_raw_score
        ORDER BY r.candidate_pair_id,r.detector_id
        """
    )
    while rows := cursor.fetchmany(batch_size):
        for raw_row in rows:
            raw = RawEvidence.model_validate_json(str(raw_row[0]))
            ablated_score = (
                float(raw_row[2]) if raw.english_ablation_raw_score is not None else None
            )
            yield EvidenceRow(
                evidence_id=evidence_id(
                    raw.candidate_pair_id,
                    raw.detector_id,
                    raw.source_artifact_sha256,
                ),
                candidate_pair_id=raw.candidate_pair_id,
                passage_a_id=raw.passage_a_id,
                passage_b_id=raw.passage_b_id,
                detector_id=raw.detector_id,
                family=raw.family,
                independence_group=raw.independence_group,
                raw_score=raw.raw_score,
                normalized_score=float(raw_row[1]),
                normalization_method=str(raw_row[4]),
                empirical_p_value=float(raw_row[3]),
                null_method=str(raw_row[5]),
                contains_english_derived_evidence=raw.contains_english_derived_evidence,
                english_ablation_normalized_score=ablated_score,
                original_language_evidence_remains=raw.original_language_evidence_remains,
                counts_for_independence=raw.counts_for_independence,
                trace_json=raw.trace_json,
                source_artifact_id=raw.source_artifact_id,
                source_artifact_sha256=raw.source_artifact_sha256,
                source_quality=raw.source_quality,
                source_knownness_status=raw.source_knownness_status,
                source_known_relationship_ids=raw.source_known_relationship_ids,
            )


def _iter_detector_null_rows(
    connection: duckdb.DuckDBPyConnection, *, batch_size: int
) -> Iterator[DetectorNullCalibrationRow]:
    cursor = connection.execute(
        """
        SELECT
            candidate_pair_id,detector_id,stratum,observed_score,
            null_exceedance_count,empirical_p_value,iterations,null_family,seed,mechanism
        FROM detector_null_calibration
        ORDER BY candidate_pair_id,detector_id
        """
    )
    while rows := cursor.fetchmany(batch_size):
        for row in rows:
            yield DetectorNullCalibrationRow(
                candidate_pair_id=str(row[0]),
                detector_id=str(row[1]),
                stratum=str(row[2]),
                observed_score=float(row[3]),
                null_exceedance_count=int(row[4]),
                empirical_p_value=float(row[5]),
                iterations=int(row[6]),
                null_family=str(row[7]),
                seed=int(row[8]),
                mechanism=str(row[9]),
            )


def _iter_calibration_state(
    connection: duckdb.DuckDBPyConnection, *, batch_size: int
) -> Iterator[DetectorStratumCalibrationState]:
    cursor = connection.execute(
        """
        SELECT
            detector_id,stratum,normalization,null_family,seed,iterations,
            reference_score_count,reference_score_min,reference_score_max,
            reference_score_mean,reference_score_population_variance,
            reference_scores_ordered_sha256
        FROM detector_stratum_state
        ORDER BY detector_id,stratum
        """
    )
    while rows := cursor.fetchmany(batch_size):
        for row in rows:
            yield DetectorStratumCalibrationState(
                detector_id=str(row[0]),
                stratum=str(row[1]),
                normalization=cast(
                    Literal["empirical_percentile", "zscore_within_stratum", "rank_percentile"],
                    str(row[2]),
                ),
                null_family=cast(
                    Literal[
                        "within_book_reassignment",
                        "stratified_score_bootstrap",
                        "stratified_permutation",
                    ],
                    str(row[3]),
                ),
                seed=int(row[4]),
                iterations=int(row[5]),
                reference_score_count=int(row[6]),
                reference_score_min=float(row[7]),
                reference_score_max=float(row[8]),
                reference_score_mean=float(row[9]),
                reference_score_population_variance=float(row[10]),
                reference_scores_ordered_sha256=str(row[11]),
            )


def _logical_table_receipt(
    connection: duckdb.DuckDBPyConnection,
    *,
    query: str,
    ordering: str,
    batch_size: int,
) -> CalibrationTableReceipt:
    digest = hashlib.sha256()
    count = 0
    cursor = connection.execute(query)
    while rows := cursor.fetchmany(batch_size):
        for row in rows:
            payload = _canonical_json_bytes(list(row))
            digest.update(struct.pack(">Q", len(payload)))
            digest.update(payload)
            count += 1
    if count < 1:
        raise DiskCalibrationError(f"logical table receipt is empty: {ordering}")
    return CalibrationTableReceipt(
        row_count=count,
        logical_sha256=digest.hexdigest(),
        ordering=ordering,
    )


def _validate_raw_only_population(connection: duckdb.DuckDBPyConnection, *, raw_count: int) -> None:
    duplicate = _first_row(
        connection,
        """
        SELECT detector_id,candidate_pair_id,count(*)
        FROM raw_evidence
        GROUP BY detector_id,candidate_pair_id
        HAVING count(*)<>1
        ORDER BY detector_id,candidate_pair_id
        LIMIT 1
        """,
    )
    if duplicate is not None:
        raise DiskCalibrationError(
            "anomaly input projection requires one score per detector/pair: "
            f"{duplicate[0]}/{duplicate[1]}"
        )
    inconsistent_pair = _first_row(
        connection,
        """
        SELECT candidate_pair_id
        FROM raw_evidence
        GROUP BY candidate_pair_id
        HAVING count(DISTINCT passage_a_id)<>1 OR count(DISTINCT passage_b_id)<>1
        ORDER BY candidate_pair_id
        LIMIT 1
        """,
    )
    if inconsistent_pair is not None:
        raise DiskCalibrationError(f"raw evidence pair identity disagrees: {inconsistent_pair[0]}")
    forbidden_anomaly = _first_row(
        connection,
        """
        SELECT detector_id,candidate_pair_id
        FROM raw_evidence
        WHERE family='anomaly'
        ORDER BY detector_id,candidate_pair_id
        LIMIT 1
        """,
    )
    if forbidden_anomaly is not None:
        raise DiskCalibrationError("Stage 6 anomaly inputs cannot recursively contain anomaly rows")
    count_row = connection.execute("SELECT count(*) FROM raw_evidence").fetchone()
    if count_row is None or int(count_row[0]) != raw_count:
        raise DiskCalibrationError("anomaly input raw-evidence count does not reconcile")


def _create_anomaly_pair_projection(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE anomaly_detector_normalization AS
        WITH reference_bins AS (
            SELECT detector_id,raw_score,count(*)::BIGINT AS tied_count
            FROM raw_evidence
            GROUP BY detector_id,raw_score
        ),
        ranked AS (
            SELECT
                detector_id,
                raw_score,
                tied_count,
                coalesce(
                    sum(tied_count) OVER (
                        PARTITION BY detector_id ORDER BY raw_score
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ),
                    0
                )::BIGINT AS below_count,
                sum(tied_count) OVER (PARTITION BY detector_id)::BIGINT AS reference_count
            FROM reference_bins
        )
        SELECT
            detector_id,
            raw_score,
            (below_count + 0.5 * tied_count) / reference_count AS normalized_score
        FROM ranked;

        CREATE TABLE anomaly_pair_family AS
        SELECT
            raw.candidate_pair_id,
            min(raw.passage_a_id) AS passage_a_id,
            min(raw.passage_b_id) AS passage_b_id,
            raw.family,
            max(normalized.normalized_score) AS family_score,
            bool_or(raw.formulaic_control) AS formulaic_control
        FROM raw_evidence raw
        JOIN anomaly_detector_normalization normalized
          ON normalized.detector_id=raw.detector_id
         AND normalized.raw_score=raw.raw_score
        GROUP BY raw.candidate_pair_id,raw.family;

        CREATE TEMP VIEW eligible_anomaly_pairs AS
        SELECT candidate_pair_id
        FROM anomaly_pair_family
        GROUP BY candidate_pair_id
        HAVING count(*)>=2;
        """
    )


def _iter_anomaly_pair_scores(
    connection: duckdb.DuckDBPyConnection, *, batch_size: int
) -> Iterator[PairFamilyScores]:
    cursor = connection.execute(
        """
        SELECT
            family.candidate_pair_id,
            family.passage_a_id,
            family.passage_b_id,
            family.family,
            family.family_score,
            family.formulaic_control
        FROM anomaly_pair_family family
        JOIN eligible_anomaly_pairs eligible USING (candidate_pair_id)
        ORDER BY family.candidate_pair_id,family.family
        """
    )
    pair_id: str | None = None
    passage_a_id = ""
    passage_b_id = ""
    family_scores: dict[str, float] = {}
    formulaic_control = False
    while rows := cursor.fetchmany(batch_size):
        for row in rows:
            current_pair_id = str(row[0])
            if pair_id is not None and current_pair_id != pair_id:
                yield PairFamilyScores(
                    candidate_pair_id=pair_id,
                    passage_a_id=passage_a_id,
                    passage_b_id=passage_b_id,
                    family_scores=cast(dict[EvidenceFamily, float], family_scores),
                    formulaic_control=formulaic_control,
                )
                family_scores = {}
                formulaic_control = False
            pair_id = current_pair_id
            passage_a_id = str(row[1])
            passage_b_id = str(row[2])
            family_scores[str(row[3])] = float(row[4])
            formulaic_control = formulaic_control or bool(row[5])
    if pair_id is not None:
        yield PairFamilyScores(
            candidate_pair_id=pair_id,
            passage_a_id=passage_a_id,
            passage_b_id=passage_b_id,
            family_scores=cast(dict[EvidenceFamily, float], family_scores),
            formulaic_control=formulaic_control,
        )


def _passage_projection_logical_sha256(
    passages: Mapping[str, PassageRecord],
) -> str:
    if len(passages) < 2:
        raise DiskCalibrationError("robust anomaly calibration requires at least two passages")
    digest = hashlib.sha256()
    for passage_id in sorted(passages):
        passage = passages[passage_id]
        if passage_id != passage.passage_id:
            raise DiskCalibrationError(
                f"passage mapping key disagrees with its record: {passage_id}"
            )
        payload = _canonical_json_bytes(
            {
                "passage_id": passage.passage_id,
                "corpus": passage.corpus,
                "book": passage.book,
                "genre": passage.genre,
                "token_count": passage.token_count,
                "formulaic_language": passage.formulaic_language,
            }
        )
        digest.update(struct.pack(">Q", len(payload)))
        digest.update(payload)
    return digest.hexdigest()


def _create_robust_anomaly_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE anomaly_observations (
            candidate_pair_id VARCHAR NOT NULL,
            passage_a_id VARCHAR NOT NULL,
            passage_b_id VARCHAR NOT NULL,
            stratum VARCHAR NOT NULL,
            disagreement DOUBLE NOT NULL,
            family_scores_json VARCHAR NOT NULL,
            formulaic_control BOOLEAN NOT NULL
        );
        CREATE TABLE anomaly_stratum_state (
            stratum VARCHAR NOT NULL,
            pair_count BIGINT NOT NULL,
            disagreement_median DOUBLE NOT NULL,
            disagreement_mad DOUBLE NOT NULL
        );
        """
    )


def _ingest_anomaly_observations(
    connection: duckdb.DuckDBPyConnection,
    pair_family_scores_path: Path,
    passages: Mapping[str, PassageRecord],
    *,
    batch_size: int,
) -> tuple[CalibrationInputFileReceipt, int]:
    if not pair_family_scores_path.is_file():
        raise DiskCalibrationError(
            f"pair-family score input is not a regular file: {pair_family_scores_path}"
        )
    inspected = inspect_jsonl_file(pair_family_scores_path)
    input_receipt = CalibrationInputFileReceipt(
        source_index=0,
        file_name=pair_family_scores_path.name,
        row_count=inspected.row_count,
        size_bytes=inspected.size_bytes,
        sha256=inspected.sha256,
    )
    insert_rows: list[tuple[object, ...]] = []
    prior_pair_id: str | None = None
    row_count = 0
    for observation in iter_canonical_jsonl(pair_family_scores_path, PairFamilyScores):
        if prior_pair_id is not None and observation.candidate_pair_id <= prior_pair_id:
            raise DiskCalibrationError(
                "pair-family scores are duplicate or not strictly candidate-pair ordered"
            )
        expected_pair_id = candidate_pair_id(observation.passage_a_id, observation.passage_b_id)
        if observation.candidate_pair_id != expected_pair_id:
            raise DiskCalibrationError(
                f"pair-family score has a noncanonical pair ID: {observation.candidate_pair_id}"
            )
        try:
            left = passages[observation.passage_a_id]
            right = passages[observation.passage_b_id]
        except KeyError as exc:
            raise DiskCalibrationError(f"missing passage for anomaly pair: {exc}") from exc
        disagreement = _disagreement(observation.family_scores)
        if not math.isfinite(disagreement):
            raise DiskCalibrationError(
                f"anomaly disagreement is non-finite: {observation.candidate_pair_id}"
            )
        formulaic_control = (
            observation.formulaic_control or left.formulaic_language or right.formulaic_language
        )
        insert_rows.append(
            (
                observation.candidate_pair_id,
                observation.passage_a_id,
                observation.passage_b_id,
                _stratum(left, right),
                disagreement,
                _canonical_json_bytes(observation.family_scores).decode("ascii"),
                formulaic_control,
            )
        )
        row_count += 1
        prior_pair_id = observation.candidate_pair_id
        if len(insert_rows) >= batch_size:
            _insert_arrow_rows(connection, "anomaly_observations", insert_rows)
            insert_rows.clear()
    if insert_rows:
        _insert_arrow_rows(connection, "anomaly_observations", insert_rows)
    if row_count < 1:
        raise DiskCalibrationError("robust anomaly calibration requires pair-family scores")
    if row_count != inspected.row_count:
        raise DiskCalibrationError("pair-family score input count does not reconcile")
    return input_receipt, row_count


def _populate_anomaly_stratum_state(connection: duckdb.DuckDBPyConnection) -> int:
    connection.execute(
        """
        CREATE TEMP TABLE anomaly_stratum_medians AS
        SELECT
            stratum,
            count(*)::BIGINT AS pair_count,
            median(disagreement) AS disagreement_median
        FROM anomaly_observations
        GROUP BY stratum;

        INSERT INTO anomaly_stratum_state
        SELECT
            medians.stratum,
            medians.pair_count,
            medians.disagreement_median,
            median(abs(observations.disagreement-medians.disagreement_median))
                AS disagreement_mad
        FROM anomaly_stratum_medians medians
        JOIN anomaly_observations observations USING (stratum)
        GROUP BY medians.stratum,medians.pair_count,medians.disagreement_median;
        """
    )
    count_row = connection.execute("SELECT count(*) FROM anomaly_stratum_state").fetchone()
    if count_row is None or int(count_row[0]) < 1:
        raise DiskCalibrationError("robust anomaly calibration produced no stratum state")
    return int(count_row[0])


def _calibrate_robust_anomaly_scores(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE zero_mad_midrank AS
        WITH bins AS (
            SELECT
                observations.stratum,
                observations.disagreement,
                count(*)::BIGINT AS tied_count
            FROM anomaly_observations observations
            JOIN anomaly_stratum_state state USING (stratum)
            WHERE state.disagreement_mad=0.0
            GROUP BY observations.stratum,observations.disagreement
        ),
        ranked AS (
            SELECT
                *,
                coalesce(
                    sum(tied_count) OVER (
                        PARTITION BY stratum ORDER BY disagreement
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ),
                    0
                )::BIGINT AS below_count,
                sum(tied_count) OVER (PARTITION BY stratum)::BIGINT AS reference_count
            FROM bins
        )
        SELECT
            stratum,
            disagreement,
            (below_count + 0.5 * tied_count) / reference_count AS calibrated_score
        FROM ranked;

        CREATE TABLE anomaly_calibrated_scores AS
        SELECT
            observations.candidate_pair_id,
            CASE
                WHEN state.disagreement_mad=0.0 THEN midrank.calibrated_score
                ELSE NULL
            END::DOUBLE AS calibrated_score
        FROM anomaly_observations observations
        JOIN anomaly_stratum_state state USING (stratum)
        LEFT JOIN zero_mad_midrank midrank
          ON midrank.stratum=observations.stratum
         AND midrank.disagreement=observations.disagreement;
        """
    )

    def robust_upper_probability(value: float, median: float, mad: float) -> float:
        robust_z = (value - median) / (1.4826 * mad)
        return 0.5 * (1.0 + math.erf(robust_z / math.sqrt(2.0)))

    function_name = "echoes_robust_anomaly_probability"
    connection.create_function(
        function_name,
        robust_upper_probability,
        [DOUBLE, DOUBLE, DOUBLE],
        DOUBLE,
    )
    try:
        connection.execute(
            f"""
            UPDATE anomaly_calibrated_scores calibrated
            SET calibrated_score={function_name}(
                observations.disagreement,
                state.disagreement_median,
                state.disagreement_mad
            )
            FROM anomaly_observations observations
            JOIN anomaly_stratum_state state USING (stratum)
            WHERE calibrated.candidate_pair_id=observations.candidate_pair_id
              AND state.disagreement_mad<>0.0
            """
        )
    finally:
        connection.remove_function(function_name)
    missing = _first_row(
        connection,
        """
        SELECT candidate_pair_id
        FROM anomaly_calibrated_scores
        WHERE calibrated_score IS NULL OR NOT isfinite(calibrated_score)
        ORDER BY candidate_pair_id
        LIMIT 1
        """,
    )
    if missing is not None:
        raise DiskCalibrationError(f"robust anomaly score is absent or invalid: {missing[0]}")


def _iter_robust_anomaly_evidence(
    connection: duckdb.DuckDBPyConnection,
    passages: Mapping[str, PassageRecord],
    registration: DetectorRegistration,
    *,
    source_artifact_id: str,
    source_artifact_sha256: str,
    batch_size: int,
) -> Iterator[RawEvidence]:
    cursor = connection.execute(
        """
        SELECT
            observations.candidate_pair_id,
            observations.passage_a_id,
            observations.passage_b_id,
            observations.stratum,
            observations.disagreement,
            observations.family_scores_json,
            observations.formulaic_control,
            state.pair_count,
            calibrated.calibrated_score
        FROM anomaly_observations observations
        JOIN anomaly_stratum_state state USING (stratum)
        JOIN anomaly_calibrated_scores calibrated USING (candidate_pair_id)
        ORDER BY observations.candidate_pair_id
        """
    )
    while rows := cursor.fetchmany(batch_size):
        for row in rows:
            pair_id = str(row[0])
            passage_a_id = str(row[1])
            passage_b_id = str(row[2])
            left = passages[passage_a_id]
            right = passages[passage_b_id]
            parsed_scores = json.loads(str(row[5]))
            if not isinstance(parsed_scores, dict):
                raise DiskCalibrationError(f"anomaly family scores are invalid: {pair_id}")
            family_scores = {
                cast(EvidenceFamily, str(family)): float(score)
                for family, score in parsed_scores.items()
            }
            lexical = family_scores.get("lexical")
            semantic = family_scores.get("semantic")
            lexical_semantic_gap = (
                abs(lexical - semantic) if lexical is not None and semantic is not None else None
            )
            formulaic_control = bool(row[6])
            calibrated = float(row[8])
            score = calibrated * (0.75 if formulaic_control else 1.0)
            yield RawEvidence(
                candidate_pair_id=pair_id,
                passage_a_id=passage_a_id,
                passage_b_id=passage_b_id,
                detector_id=registration.detector_id,
                family="anomaly",
                independence_group=registration.independence_group,
                raw_score=score,
                contains_english_derived_evidence=False,
                original_language_evidence_remains=True,
                counts_for_independence=False,
                trace_json=canonical_json(
                    {
                        "representation": "stratified_family_score_disagreement",
                        "stratum": str(row[3]),
                        "stratum_pair_count": int(row[7]),
                        "family_scores": family_scores,
                        "score_standard_deviation": float(row[4]),
                        "lexical_semantic_absolute_gap": lexical_semantic_gap,
                        "unexpected_neighbor_context": {
                            "different_book": left.book != right.book,
                            "different_genre": left.genre != right.genre,
                            "cross_corpus": left.corpus != right.corpus,
                        },
                        "formulaic_downweight_applied": formulaic_control,
                        "diagnostic_not_independent_proof": True,
                    }
                ),
                source_artifact_id=source_artifact_id,
                source_artifact_sha256=source_artifact_sha256,
            )


def _output_receipt(file_name: str, receipt: StreamArtifactReceipt) -> CalibrationOutputFileReceipt:
    return CalibrationOutputFileReceipt(
        file_name=file_name,
        row_count=receipt.row_count,
        size_bytes=receipt.size_bytes,
        sha256=receipt.sha256,
    )


def _run_in_staging(
    staging: Path,
    database_path: Path,
    raw_evidence_paths: Sequence[Path],
    strata_by_pair: Mapping[str, str] | Iterable[PairStratum],
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
    memory_limit_bytes: int,
    threads: int,
    batch_size: int,
    spill_directory: Path,
) -> DiskDetectorCalibrationReceipt:
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
        connection.execute(f"SET threads={threads}")
        connection.execute("SET preserve_insertion_order=false")
        connection.execute(f"SET temp_directory='{_quoted_path(spill_directory)}'")
        _create_tables(connection)
        connection.execute("BEGIN TRANSACTION")
        try:
            _insert_registry(connection, config)
            input_receipts, raw_count = _ingest_raw_evidence(
                connection,
                raw_evidence_paths,
                config=config,
                batch_size=batch_size,
            )
            strata_count = _ingest_pair_strata(
                connection,
                strata_by_pair,
                batch_size=batch_size,
            )
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")
        pair_count, detector_count = _validate_ingested_tables(
            connection,
            raw_count=raw_count,
            strata_count=strata_count,
        )
        _create_normalization_values(connection)
        connection.execute("BEGIN TRANSACTION")
        try:
            provenance = _calibrate_detector_strata(
                connection,
                config=config,
                iterations=iterations,
                batch_size=batch_size,
            )
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")
        detector_stratum_row = connection.execute(
            "SELECT count(*) FROM detector_stratum_state"
        ).fetchone()
        if detector_stratum_row is None:
            raise DiskCalibrationError("could not count detector-stratum calibration state")
        detector_stratum_count = int(detector_stratum_row[0])

        evidence_receipt = write_jsonl_stream_atomic(
            staging / EVIDENCE_FILE_NAME,
            _iter_evidence(connection, batch_size=batch_size),
            order_key=lambda row: (
                cast(EvidenceRow, row).candidate_pair_id,
                cast(EvidenceRow, row).detector_id,
            ),
        )
        null_receipt = write_jsonl_stream_atomic(
            staging / DETECTOR_NULL_FILE_NAME,
            _iter_detector_null_rows(connection, batch_size=batch_size),
            order_key=lambda row: (
                cast(DetectorNullCalibrationRow, row).candidate_pair_id,
                cast(DetectorNullCalibrationRow, row).detector_id,
            ),
        )
        state_receipt = write_jsonl_stream_atomic(
            staging / CALIBRATION_STATE_FILE_NAME,
            _iter_calibration_state(connection, batch_size=batch_size),
            order_key=lambda row: (
                cast(DetectorStratumCalibrationState, row).detector_id,
                cast(DetectorStratumCalibrationState, row).stratum,
            ),
        )
        provenance_payload = {
            "schema_version": 1,
            "execution_mode": "production",
            "iterations": iterations,
            "config_sha256": final_discovery_config_sha256(config),
            "reference_score_arrays_persisted": False,
            "calibration_state_file": CALIBRATION_STATE_FILE_NAME,
            "detector_null_file": DETECTOR_NULL_FILE_NAME,
            "provenance_by_detector": provenance,
        }
        provenance_receipt = write_json_atomic_new(
            staging / PROVENANCE_FILE_NAME,
            provenance_payload,
        )

        table_receipts = {
            "raw_evidence": _logical_table_receipt(
                connection,
                query="""
                    SELECT detector_id,candidate_pair_id,raw_json
                    FROM raw_evidence ORDER BY detector_id,candidate_pair_id
                """,
                ordering="detector_id,candidate_pair_id",
                batch_size=batch_size,
            ),
            "pair_strata": _logical_table_receipt(
                connection,
                query="""
                    SELECT candidate_pair_id,stratum
                    FROM pair_strata ORDER BY candidate_pair_id
                """,
                ordering="candidate_pair_id",
                batch_size=batch_size,
            ),
            "detector_null_calibration": CalibrationTableReceipt(
                row_count=null_receipt.row_count,
                logical_sha256=null_receipt.sha256,
                ordering="candidate_pair_id,detector_id",
            ),
            "detector_stratum_state": CalibrationTableReceipt(
                row_count=state_receipt.row_count,
                logical_sha256=state_receipt.sha256,
                ordering="detector_id,stratum",
            ),
            "calibrated_evidence": CalibrationTableReceipt(
                row_count=evidence_receipt.row_count,
                logical_sha256=evidence_receipt.sha256,
                ordering="candidate_pair_id,detector_id",
            ),
        }
        receipt = DiskDetectorCalibrationReceipt(
            config_sha256=final_discovery_config_sha256(config),
            iterations=iterations,
            duckdb_memory_limit_bytes=memory_limit_bytes,
            duckdb_threads=threads,
            ingestion_batch_size=batch_size,
            raw_input_files=input_receipts,
            raw_evidence_row_count=raw_count,
            candidate_pair_count=pair_count,
            detector_count=detector_count,
            detector_stratum_count=detector_stratum_count,
            table_receipts=table_receipts,
            output_files={
                EVIDENCE_FILE_NAME: _output_receipt(EVIDENCE_FILE_NAME, evidence_receipt),
                DETECTOR_NULL_FILE_NAME: _output_receipt(DETECTOR_NULL_FILE_NAME, null_receipt),
                CALIBRATION_STATE_FILE_NAME: _output_receipt(
                    CALIBRATION_STATE_FILE_NAME, state_receipt
                ),
                PROVENANCE_FILE_NAME: _output_receipt(PROVENANCE_FILE_NAME, provenance_receipt),
            },
        )
        write_json_atomic_new(staging / RECEIPT_FILE_NAME, receipt)
        return receipt


def calibrate_detector_evidence_disk_backed(
    raw_evidence_paths: Sequence[Path],
    strata_by_pair: Mapping[str, str] | Iterable[PairStratum],
    output_directory: Path,
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
    memory_limit_bytes: int,
    temp_directory: Path,
    threads: int = 1,
    batch_size: int = 65_536,
) -> DiskDetectorCalibrationResult:
    """Calibrate canonical raw-evidence streams in one atomic output bundle.

    The final directory must not exist.  Work is performed in a hidden sibling
    and a uniquely named DuckDB workspace; therefore validation failures and
    process interruptions cannot publish a partial bundle or replace a prior
    result.  Failed staging, database, WAL, and spill state is preserved for
    diagnosis.  Transient state is removed only after atomic publication.
    """

    if iterations != config.calibration.production_iterations:
        raise DiskCalibrationError(
            "production detector calibration must use the preregistered production iterations"
        )
    if memory_limit_bytes < _MINIMUM_MEMORY_BYTES:
        raise DiskCalibrationError("disk calibration requires at least 256 MiB")
    if threads < 1 or threads > 64:
        raise DiskCalibrationError("DuckDB thread count must be between 1 and 64")
    if batch_size < 1:
        raise DiskCalibrationError("disk calibration batch_size must be positive")
    if output_directory.exists():
        raise DiskCalibrationError(
            f"disk calibration refuses to replace output directory: {output_directory}"
        )
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temp_directory.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    staging = output_directory.with_name(f".{output_directory.name}.{run_id}.tmp")
    run_workspace = temp_directory / f"disk-calibration-{run_id}.work"
    database_path = run_workspace / "disk-calibration.duckdb"
    spill_directory = run_workspace / "spill"
    try:
        staging.mkdir(exist_ok=False)
        run_workspace.mkdir(exist_ok=False)
        spill_directory.mkdir(exist_ok=False)
        receipt = _run_in_staging(
            staging,
            database_path,
            raw_evidence_paths,
            strata_by_pair,
            config=config,
            iterations=iterations,
            memory_limit_bytes=memory_limit_bytes,
            threads=threads,
            batch_size=batch_size,
            spill_directory=spill_directory,
        )
        if output_directory.exists():
            raise DiskCalibrationError(
                f"disk calibration output appeared during execution: {output_directory}"
            )
        staging.rename(output_directory)
        shutil.rmtree(run_workspace)
    except BaseException as exc:
        if isinstance(exc, (DiskCalibrationError, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, (duckdb.Error, FinalDiscoveryStorageError, OSError, ValueError)):
            raise DiskCalibrationError(f"disk-backed detector calibration failed: {exc}") from exc
        raise
    return DiskDetectorCalibrationResult(
        output_directory=output_directory,
        evidence_path=output_directory / EVIDENCE_FILE_NAME,
        detector_null_path=output_directory / DETECTOR_NULL_FILE_NAME,
        calibration_state_path=output_directory / CALIBRATION_STATE_FILE_NAME,
        provenance_path=output_directory / PROVENANCE_FILE_NAME,
        receipt_path=output_directory / RECEIPT_FILE_NAME,
        receipt=receipt,
    )


def project_anomaly_pair_scores_disk_backed(
    raw_evidence_paths: Sequence[Path],
    output_directory: Path,
    *,
    config: FinalDiscoveryConfig,
    memory_limit_bytes: int,
    temp_directory: Path,
    threads: int = 1,
    batch_size: int = 65_536,
) -> AnomalyPairProjectionResult:
    """Project exact Stage 3--5 detector percentiles and pair-family maxima.

    The output is a candidate-pair ordered ``PairFamilyScores`` ledger.  It is
    the bounded handoff to Stage 6 anomaly calibration and avoids retaining
    either raw evidence or all detector reference distributions in Python.
    Failed staging, database, WAL, and spill state is preserved for diagnosis;
    transient state is removed only after atomic publication.
    """

    if memory_limit_bytes < _MINIMUM_MEMORY_BYTES:
        raise DiskCalibrationError("anomaly pair projection requires at least 256 MiB")
    if threads < 1 or threads > 64:
        raise DiskCalibrationError("DuckDB thread count must be between 1 and 64")
    if batch_size < 1:
        raise DiskCalibrationError("anomaly pair projection batch_size must be positive")
    if output_directory.exists():
        raise DiskCalibrationError(
            f"anomaly pair projection refuses to replace output directory: {output_directory}"
        )
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temp_directory.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    staging = output_directory.with_name(f".{output_directory.name}.{run_id}.tmp")
    run_workspace = temp_directory / f"anomaly-pair-projection-{run_id}.work"
    database_path = run_workspace / "anomaly-pair-projection.duckdb"
    spill_directory = run_workspace / "spill"
    try:
        staging.mkdir(exist_ok=False)
        run_workspace.mkdir(exist_ok=False)
        spill_directory.mkdir(exist_ok=False)
        with duckdb.connect(str(database_path)) as connection:
            connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
            connection.execute(f"SET threads={threads}")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute(f"SET temp_directory='{_quoted_path(spill_directory)}'")
            _create_tables(connection)
            connection.execute("BEGIN TRANSACTION")
            try:
                _insert_registry(connection, config)
                input_receipts, raw_count = _ingest_raw_evidence(
                    connection,
                    raw_evidence_paths,
                    config=config,
                    batch_size=batch_size,
                )
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")
            _validate_raw_only_population(connection, raw_count=raw_count)
            _create_anomaly_pair_projection(connection)
            output_receipt = write_jsonl_stream_atomic(
                staging / ANOMALY_INPUT_FILE_NAME,
                _iter_anomaly_pair_scores(connection, batch_size=batch_size),
                order_key=lambda row: (cast(PairFamilyScores, row).candidate_pair_id,),
            )
            receipt = AnomalyPairProjectionReceipt(
                config_sha256=final_discovery_config_sha256(config),
                duckdb_memory_limit_bytes=memory_limit_bytes,
                duckdb_threads=threads,
                ingestion_batch_size=batch_size,
                raw_input_files=input_receipts,
                raw_evidence_row_count=raw_count,
                eligible_pair_count=output_receipt.row_count,
                output_size_bytes=output_receipt.size_bytes,
                output_sha256=output_receipt.sha256,
            )
            write_json_atomic_new(staging / ANOMALY_INPUT_RECEIPT_FILE_NAME, receipt)
        if output_directory.exists():
            raise DiskCalibrationError(
                f"anomaly pair projection output appeared during execution: {output_directory}"
            )
        staging.rename(output_directory)
        shutil.rmtree(run_workspace)
    except BaseException as exc:
        if isinstance(exc, (DiskCalibrationError, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, (duckdb.Error, FinalDiscoveryStorageError, OSError, ValueError)):
            raise DiskCalibrationError(
                f"disk-backed anomaly pair projection failed: {exc}"
            ) from exc
        raise
    return AnomalyPairProjectionResult(
        output_directory=output_directory,
        pair_family_scores_path=output_directory / ANOMALY_INPUT_FILE_NAME,
        receipt_path=output_directory / ANOMALY_INPUT_RECEIPT_FILE_NAME,
        receipt=receipt,
    )


def calibrate_anomaly_evidence_disk_backed(
    pair_family_scores_path: Path,
    passages: Mapping[str, PassageRecord],
    output_directory: Path,
    *,
    config: FinalDiscoveryConfig,
    source_artifact_id: str,
    source_artifact_sha256: str,
    memory_limit_bytes: int,
    temp_directory: Path,
    threads: int = 1,
    batch_size: int = 65_536,
) -> AnomalyEvidenceResult:
    """Apply exact robust Stage 6 anomaly calibration in bounded storage.

    Failed staging, database, WAL, and spill state is preserved for diagnosis;
    transient state is removed only after atomic publication.
    """

    if memory_limit_bytes < _MINIMUM_MEMORY_BYTES:
        raise DiskCalibrationError("robust anomaly calibration requires at least 256 MiB")
    if threads < 1 or threads > 64:
        raise DiskCalibrationError("DuckDB thread count must be between 1 and 64")
    if batch_size < 1:
        raise DiskCalibrationError("robust anomaly calibration batch_size must be positive")
    if not source_artifact_id:
        raise DiskCalibrationError("robust anomaly calibration requires a source artifact ID")
    if len(source_artifact_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in source_artifact_sha256
    ):
        raise DiskCalibrationError("robust anomaly source artifact requires a lowercase SHA-256")
    registrations = {item.detector_id: item for item in config.detectors}
    try:
        registration = registrations["stratified_representation_anomaly"]
    except KeyError as exc:
        raise DiskCalibrationError("unregistered anomaly detector") from exc
    if registration.family != "anomaly" or registration.counts_for_independence:
        raise DiskCalibrationError(
            "anomaly is a diagnostic family and cannot count as independent proof"
        )
    passage_projection_sha256 = _passage_projection_logical_sha256(passages)
    if output_directory.exists():
        raise DiskCalibrationError(
            f"robust anomaly calibration refuses to replace output directory: {output_directory}"
        )
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temp_directory.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    staging = output_directory.with_name(f".{output_directory.name}.{run_id}.tmp")
    run_workspace = temp_directory / f"robust-anomaly-{run_id}.work"
    database_path = run_workspace / "robust-anomaly.duckdb"
    spill_directory = run_workspace / "spill"
    try:
        staging.mkdir(exist_ok=False)
        run_workspace.mkdir(exist_ok=False)
        spill_directory.mkdir(exist_ok=False)
        with duckdb.connect(str(database_path)) as connection:
            connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
            connection.execute(f"SET threads={threads}")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute(f"SET temp_directory='{_quoted_path(spill_directory)}'")
            _create_robust_anomaly_tables(connection)
            connection.execute("BEGIN TRANSACTION")
            try:
                input_receipt, pair_count = _ingest_anomaly_observations(
                    connection,
                    pair_family_scores_path,
                    passages,
                    batch_size=batch_size,
                )
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")
            stratum_count = _populate_anomaly_stratum_state(connection)
            _calibrate_robust_anomaly_scores(connection)
            state_receipt = _logical_table_receipt(
                connection,
                query="""
                    SELECT
                        stratum,pair_count,disagreement_median,disagreement_mad
                    FROM anomaly_stratum_state ORDER BY stratum
                """,
                ordering="stratum",
                batch_size=batch_size,
            )
            output_receipt = write_jsonl_stream_atomic(
                staging / ANOMALY_EVIDENCE_FILE_NAME,
                _iter_robust_anomaly_evidence(
                    connection,
                    passages,
                    registration,
                    source_artifact_id=source_artifact_id,
                    source_artifact_sha256=source_artifact_sha256,
                    batch_size=batch_size,
                ),
                order_key=lambda row: (
                    cast(RawEvidence, row).candidate_pair_id,
                    cast(RawEvidence, row).detector_id,
                ),
            )
            receipt = AnomalyEvidenceReceipt(
                config_sha256=final_discovery_config_sha256(config),
                duckdb_memory_limit_bytes=memory_limit_bytes,
                duckdb_threads=threads,
                ingestion_batch_size=batch_size,
                input_file=input_receipt,
                passage_count=len(passages),
                passage_projection_logical_sha256=passage_projection_sha256,
                candidate_pair_count=pair_count,
                anomaly_stratum_count=stratum_count,
                stratum_state_logical_sha256=state_receipt.logical_sha256,
                source_artifact_id=source_artifact_id,
                source_artifact_sha256=source_artifact_sha256,
                output_size_bytes=output_receipt.size_bytes,
                output_sha256=output_receipt.sha256,
            )
            write_json_atomic_new(staging / ANOMALY_EVIDENCE_RECEIPT_FILE_NAME, receipt)
        if output_directory.exists():
            raise DiskCalibrationError(
                f"robust anomaly output appeared during execution: {output_directory}"
            )
        staging.rename(output_directory)
        shutil.rmtree(run_workspace)
    except BaseException as exc:
        if isinstance(exc, (DiskCalibrationError, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, (duckdb.Error, FinalDiscoveryStorageError, OSError, ValueError)):
            raise DiskCalibrationError(f"disk-backed robust anomaly failed: {exc}") from exc
        raise
    return AnomalyEvidenceResult(
        output_directory=output_directory,
        anomaly_evidence_path=output_directory / ANOMALY_EVIDENCE_FILE_NAME,
        receipt_path=output_directory / ANOMALY_EVIDENCE_RECEIPT_FILE_NAME,
        receipt=receipt,
    )
