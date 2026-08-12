"""Authenticated read-only adapter for the sealed Milestone 7 artifact."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from echoes.final_discovery.config import DetectorRegistration
from echoes.final_discovery.features import candidate_pair_id, canonical_json
from echoes.final_discovery.models import EvidenceRow, QualityFlags, RawEvidence
from echoes.lexical.models import LEXICAL_ARTIFACT_COLUMNS, LEXICAL_ARTIFACT_NAMES


class M7AdapterError(ValueError):
    """Raised when the canonical M7 input cannot be authenticated or adapted."""


class M7AuthenticationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    root: str
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    table_counts: dict[str, int]
    table_logical_sha256: dict[str, str]
    file_count: int = Field(ge=1)
    verified_file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)


M7_HYDRATION_SELECTION_BATCH_SIZE: Final = 1_024


class M7HydrationIndexReceipt(BaseModel):
    """Bounded-work receipt for one transient hydrated-evidence lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m7-hydration-index-v1"] = "m7-hydration-index-v1"
    row_count: int = Field(ge=0)
    source_scan_count: int = Field(ge=0, le=1)
    selection_batch_size: int = Field(ge=1)
    maximum_selection_batch_rows_observed: int = Field(ge=0)
    arrow_batch_size: int = Field(ge=1)
    source_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class _HydrationStatistics:
    row_count: int
    maximum_selection_batch_rows_observed: int
    source_manifest_sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_or_registered_sentinel(value: object) -> float | str:
    number = float(cast(float, value))
    if math.isfinite(number):
        return number
    if number > 0.0:
        return "positive_infinity_no_qualified_threshold"
    raise M7AdapterError("M7 projection contains an unregistered non-finite calibration value")


def _string_dict(value: object, *, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise M7AdapterError(f"M7 manifest field {field} must be a string mapping")
    return cast(dict[str, str], value)


def _count_dict(value: object, *, field: str) -> dict[str, int]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, int) and item >= 0 for key, item in value.items()
    ):
        raise M7AdapterError(f"M7 manifest field {field} must be a nonnegative count mapping")
    return cast(dict[str, int], value)


def _relationship_ids(value: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise M7AdapterError("M7 OpenBible relationship IDs are not valid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) and item for item in parsed):
        raise M7AdapterError("M7 OpenBible relationship IDs must be a string array")
    result = tuple(sorted(set(parsed)))
    if len(result) != len(parsed):
        raise M7AdapterError("M7 OpenBible relationship IDs contain duplicates")
    return result


def _shared_evidence_ids(value: object, *, expected_count: int) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise M7AdapterError("M7 shared-evidence IDs are not valid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) and item for item in parsed):
        raise M7AdapterError("M7 shared-evidence IDs must be a string array")
    result = tuple(cast(list[str], parsed))
    if len(result) != expected_count or len(result) != len(set(result)):
        raise M7AdapterError("M7 shared-evidence IDs disagree with their registered count")
    return result


def _projection_manifest_contract(
    input_root: Path,
) -> tuple[str, dict[str, int], dict[str, str]]:
    manifest_path = input_root / "table-hashes.json"
    if not manifest_path.is_file():
        raise M7AdapterError(f"M7 projection requires its authenticated manifest: {manifest_path}")
    try:
        parsed: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M7AdapterError(f"could not parse M7 projection manifest: {exc}") from exc
    if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
        raise M7AdapterError("M7 projection manifest requires schema_version 1")
    counts = _count_dict(parsed.get("table_counts"), field="table_counts")
    logical = _string_dict(parsed.get("table_logical_sha256"), field="table_logical_sha256")
    required = {"candidate_pairs", "candidate_evidence", "shared_evidence"}
    if not required <= counts.keys() or not required <= logical.keys():
        raise M7AdapterError("M7 projection manifest omits a required lexical table")
    for name in required:
        if not _is_sha256(logical[name]):
            raise M7AdapterError(f"M7 projection manifest has an invalid logical hash for {name}")
    return _sha256_file(manifest_path), counts, logical


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _shared_evidence_digest(rows: list[dict[str, object]]) -> str:
    columns = LEXICAL_ARTIFACT_COLUMNS["shared_evidence"]
    canonical_rows = [{column: row[column] for column in columns} for row in rows]
    canonical_rows.sort(
        key=lambda row: (
            str(row["evidence_family"]),
            str(row["feature_id"]),
            str(row["evidence_id"]),
        )
    )
    payload = json.dumps(
        canonical_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_shared_evidence(
    value: object,
    *,
    candidate_pair_id_value: str,
    expected_count: int,
) -> tuple[tuple[dict[str, object], ...], str]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise M7AdapterError("M7 shared evidence is not valid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(row, dict) for row in parsed):
        raise M7AdapterError("M7 shared evidence must be a JSON object array")
    rows = cast(list[dict[str, object]], parsed)
    return _validate_shared_evidence_rows(
        rows,
        candidate_pair_id_value=candidate_pair_id_value,
        expected_count=expected_count,
    )


def _validate_shared_evidence_rows(
    rows: list[dict[str, object]],
    *,
    candidate_pair_id_value: str,
    expected_count: int,
) -> tuple[tuple[dict[str, object], ...], str]:
    if len(rows) != expected_count:
        raise M7AdapterError("M7 shared-evidence count disagrees with its projection")
    expected_columns = set(LEXICAL_ARTIFACT_COLUMNS["shared_evidence"])
    evidence_ids: set[str] = set()
    for row in rows:
        if set(row) != expected_columns:
            raise M7AdapterError("M7 shared evidence does not retain the exact canonical schema")
        if row["candidate_pair_id"] != candidate_pair_id_value:
            raise M7AdapterError("M7 shared evidence joined to the wrong candidate")
        evidence_id_value = row["evidence_id"]
        if not isinstance(evidence_id_value, str) or not evidence_id_value:
            raise M7AdapterError("M7 shared evidence has an invalid evidence ID")
        if evidence_id_value in evidence_ids:
            raise M7AdapterError("M7 shared evidence repeats an evidence ID")
        evidence_ids.add(evidence_id_value)
        for field in ("passage_a_positions_json", "passage_b_positions_json"):
            try:
                positions = json.loads(str(row[field]))
            except json.JSONDecodeError as exc:
                raise M7AdapterError(f"M7 shared evidence has invalid {field}") from exc
            if (
                not isinstance(positions, list)
                or not positions
                or not all(isinstance(position, int) and position >= 1 for position in positions)
            ):
                raise M7AdapterError(f"M7 shared evidence has invalid {field}")
    try:
        digest = _shared_evidence_digest(rows)
    except (KeyError, TypeError, ValueError) as exc:
        raise M7AdapterError("M7 shared evidence cannot be canonically hashed") from exc
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row["evidence_family"]),
                str(row["feature_id"]),
                str(row["evidence_id"]),
            ),
        )
    )
    return ordered, digest


_EMPTY_SHARED_EVIDENCE_DIGEST = _shared_evidence_digest([])
_SHARED_EVIDENCE_INDEX_SCHEMA = pa.schema(
    (
        pa.field("candidate_pair_id", pa.string(), nullable=False),
        pa.field("m7_shared_evidence_count", pa.int64(), nullable=False),
        pa.field("m7_shared_evidence_ids_json", pa.string(), nullable=False),
        pa.field("m7_shared_evidence_digest", pa.string(), nullable=False),
    )
)


def _write_shared_evidence_index(
    connection: duckdb.DuckDBPyConnection,
    *,
    escaped_shared_glob: str,
    path: Path,
    expected_row_count: int,
    batch_size: int = 65_536,
) -> int:
    """Stream a compact per-candidate locator/digest index with bounded memory."""

    columns = ", ".join(LEXICAL_ARTIFACT_COLUMNS["shared_evidence"])
    reader = connection.execute(
        f"""
        SELECT {columns}
        FROM read_parquet('{escaped_shared_glob}', union_by_name=true)
        ORDER BY candidate_pair_id, evidence_family, feature_id, evidence_id
        """
    ).to_arrow_reader(batch_size=batch_size)
    summary_buffer: list[dict[str, object]] = []
    current_candidate_id: str | None = None
    current_rows: list[dict[str, object]] = []
    total_rows = 0
    candidate_count = 0

    def flush_candidate(writer: pq.ParquetWriter) -> None:
        nonlocal current_candidate_id, current_rows, candidate_count
        if current_candidate_id is None:
            return
        ordered, digest = _validate_shared_evidence_rows(
            current_rows,
            candidate_pair_id_value=current_candidate_id,
            expected_count=len(current_rows),
        )
        summary_buffer.append(
            {
                "candidate_pair_id": current_candidate_id,
                "m7_shared_evidence_count": len(ordered),
                "m7_shared_evidence_ids_json": canonical_json(
                    tuple(str(row["evidence_id"]) for row in ordered)
                ),
                "m7_shared_evidence_digest": digest,
            }
        )
        candidate_count += 1
        if len(summary_buffer) >= 10_000:
            writer.write_table(pa.Table.from_pylist(summary_buffer, _SHARED_EVIDENCE_INDEX_SCHEMA))
            summary_buffer.clear()
        current_candidate_id = None
        current_rows = []

    with pq.ParquetWriter(
        path,
        _SHARED_EVIDENCE_INDEX_SCHEMA,
        compression="zstd",
    ) as writer:
        for batch in reader:
            for raw_row in batch.to_pylist():
                row = cast(dict[str, object], raw_row)
                candidate_id_value = str(row["candidate_pair_id"])
                if current_candidate_id is not None and candidate_id_value != current_candidate_id:
                    flush_candidate(writer)
                if current_candidate_id is None:
                    current_candidate_id = candidate_id_value
                current_rows.append(row)
                total_rows += 1
        flush_candidate(writer)
        if summary_buffer:
            writer.write_table(pa.Table.from_pylist(summary_buffer, _SHARED_EVIDENCE_INDEX_SCHEMA))
    if total_rows != expected_row_count:
        raise M7AdapterError(
            "M7 shared-evidence sidecar row count disagrees with its authenticated manifest"
        )
    return candidate_count


def authenticate_m7_input(
    root: Path,
    *,
    expected_manifest_sha256: str,
    verify_individual_files: bool,
) -> M7AuthenticationReport:
    """Authenticate inventory, table manifest, and optionally every governed leaf."""

    canonical_root = root.resolve()
    manifest_path = canonical_root / "table-hashes.json"
    if not manifest_path.is_file():
        raise M7AdapterError(f"M7 table-hashes.json is missing from {canonical_root}")
    actual_manifest_hash = _sha256_file(manifest_path)
    if actual_manifest_hash != expected_manifest_sha256:
        raise M7AdapterError(
            f"M7 canonical manifest mismatch: {actual_manifest_hash} != {expected_manifest_sha256}"
        )
    try:
        parsed: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M7AdapterError(f"could not parse M7 manifest: {exc}") from exc
    if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
        raise M7AdapterError("M7 table-hash manifest requires schema_version 1")
    table_counts = _count_dict(parsed.get("table_counts"), field="table_counts")
    logical = _string_dict(parsed.get("table_logical_sha256"), field="table_logical_sha256")
    file_hashes = _string_dict(parsed.get("file_sha256"), field="file_sha256")
    expected_tables = set(LEXICAL_ARTIFACT_NAMES)
    if set(table_counts) != expected_tables or set(logical) != expected_tables:
        raise M7AdapterError("M7 manifest does not contain the exact canonical table inventory")
    total_bytes = manifest_path.stat().st_size
    verified = 0
    observed_files: set[str] = set()
    for relative_name, expected_hash in file_hashes.items():
        relative = Path(relative_name)
        path = (canonical_root / relative).resolve()
        try:
            path.relative_to(canonical_root)
        except ValueError as exc:
            raise M7AdapterError(f"M7 manifest path escapes its root: {relative_name}") from exc
        if not path.is_file():
            raise M7AdapterError(f"M7 governed file is missing: {relative_name}")
        observed_files.add(relative.as_posix())
        total_bytes += path.stat().st_size
        if verify_individual_files:
            actual_hash = _sha256_file(path)
            if actual_hash != expected_hash:
                raise M7AdapterError(
                    f"M7 governed file hash mismatch for {relative_name}: "
                    f"{actual_hash} != {expected_hash}"
                )
            verified += 1
    disk_parquet = {
        path.relative_to(canonical_root).as_posix()
        for path in canonical_root.rglob("part-*.parquet")
        if path.is_file()
    }
    manifested_parquet = {name for name in observed_files if name.endswith(".parquet")}
    if disk_parquet != manifested_parquet:
        raise M7AdapterError(
            "M7 Parquet inventory mismatch; "
            f"missing={sorted(manifested_parquet - disk_parquet)[:20]}, "
            f"unexpected={sorted(disk_parquet - manifested_parquet)[:20]}"
        )
    return M7AuthenticationReport(
        root=str(canonical_root),
        manifest_sha256=actual_manifest_hash,
        table_counts=table_counts,
        table_logical_sha256=logical,
        file_count=len(file_hashes),
        verified_file_count=verified,
        total_bytes=total_bytes,
    )


def build_m7_lexical_projection(
    input_root: Path,
    output_path: Path,
    *,
    memory_limit_bytes: int,
    temp_directory: Path,
) -> Path:
    """Build an audited compact one-row-per-pair ranking projection.

    Detailed shared evidence is intentionally hydrated only after final review
    selection through :func:`build_m7_hydration_index`; the compatibility
    :func:`hydrate_m7_shared_evidence` helper is explicitly batch-capped.
    """

    if memory_limit_bytes < 256 * 1024**2:
        raise M7AdapterError("M7 projection requires at least 256 MiB of DuckDB memory")
    input_root = input_root.resolve()
    manifest_sha256, table_counts, logical_hashes = _projection_manifest_contract(input_root)
    pairs_glob = (input_root / "candidate_pairs" / "part-*.parquet").as_posix()
    evidence_glob = (input_root / "candidate_evidence" / "part-*.parquet").as_posix()
    shared_glob = (input_root / "shared_evidence" / "part-*.parquet").as_posix()
    if not list((input_root / "candidate_pairs").glob("part-*.parquet")):
        raise M7AdapterError("M7 candidate_pairs leaves are missing")
    if not list((input_root / "candidate_evidence").glob("part-*.parquet")):
        raise M7AdapterError("M7 candidate_evidence leaves are missing")
    if table_counts["shared_evidence"] and not list(
        (input_root / "shared_evidence").glob("part-*.parquet")
    ):
        raise M7AdapterError("M7 shared_evidence leaves are missing")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_directory.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    temporary_index = output_path.with_name(
        f".{output_path.name}.{uuid.uuid4().hex}.shared-index.tmp"
    )
    escaped_pairs = pairs_glob.replace("'", "''")
    escaped_evidence = evidence_glob.replace("'", "''")
    escaped_shared = shared_glob.replace("'", "''")
    escaped_output = temporary.as_posix().replace("'", "''")
    escaped_index = temporary_index.as_posix().replace("'", "''")
    escaped_temp = temp_directory.resolve().as_posix().replace("'", "''")
    escaped_manifest_sha256 = manifest_sha256.replace("'", "''")
    escaped_pairs_logical = logical_hashes["candidate_pairs"].replace("'", "''")
    escaped_evidence_logical = logical_hashes["candidate_evidence"].replace("'", "''")
    escaped_shared_logical = logical_hashes["shared_evidence"].replace("'", "''")

    def scalar(connection: duckdb.DuckDBPyConnection, query: str) -> int:
        result = connection.execute(query).fetchone()
        if result is None:
            raise M7AdapterError("M7 projection audit returned no result")
        return int(result[0])

    try:
        with duckdb.connect() as connection:
            connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
            connection.execute("SET threads=1")
            connection.execute(f"SET temp_directory='{escaped_temp}'")
            pair_summary = connection.execute(
                f"""
                SELECT
                    count(*)::BIGINT,
                    count(DISTINCT candidate_pair_id)::BIGINT,
                    count(*) FILTER (
                        WHERE candidate_pair_id IS NULL OR candidate_pair_id = ''
                           OR passage_a_id IS NULL OR passage_b_id IS NULL
                           OR passage_a_id >= passage_b_id
                    )::BIGINT
                FROM read_parquet('{escaped_pairs}', union_by_name=true)
                """
            ).fetchone()
            evidence_summary = connection.execute(
                f"""
                SELECT count(*)::BIGINT, count(DISTINCT candidate_pair_id)::BIGINT
                FROM read_parquet('{escaped_evidence}', union_by_name=true)
                """
            ).fetchone()
            if pair_summary is None or evidence_summary is None:
                raise M7AdapterError("M7 projection source audit returned no result")
            observed_pair_count = int(pair_summary[0])
            observed_evidence_count = int(evidence_summary[0])
            if observed_pair_count != table_counts["candidate_pairs"]:
                raise M7AdapterError(
                    "M7 candidate_pairs count disagrees with its authenticated manifest"
                )
            if observed_evidence_count != table_counts["candidate_evidence"]:
                raise M7AdapterError(
                    "M7 candidate_evidence count disagrees with its authenticated manifest"
                )
            if observed_pair_count < 1:
                raise M7AdapterError("M7 lexical projection cannot be empty")
            if int(pair_summary[1]) != observed_pair_count or int(pair_summary[2]):
                raise M7AdapterError(
                    "M7 candidate_pairs are not unique, nonempty canonical passage pairs"
                )
            if int(evidence_summary[1]) != observed_evidence_count:
                raise M7AdapterError("M7 candidate_evidence is not one row per candidate ID")
            duplicate_passage_pairs = scalar(
                connection,
                f"""
                SELECT count(*) FROM (
                    SELECT passage_a_id, passage_b_id
                    FROM read_parquet('{escaped_pairs}', union_by_name=true)
                    GROUP BY passage_a_id, passage_b_id HAVING count(*) <> 1
                )
                """,
            )
            join_mismatches = scalar(
                connection,
                f"""
                SELECT count(*) FROM (
                    SELECT p.candidate_pair_id
                    FROM read_parquet('{escaped_pairs}', union_by_name=true) p
                    FULL OUTER JOIN read_parquet(
                        '{escaped_evidence}', union_by_name=true
                    ) e USING(candidate_pair_id)
                    WHERE p.candidate_pair_id IS NULL OR e.candidate_pair_id IS NULL
                )
                """,
            )
            shared_summary = connection.execute(
                f"""
                SELECT count(*)::BIGINT, count(DISTINCT evidence_id)::BIGINT
                FROM read_parquet('{escaped_shared}', union_by_name=true)
                """
            ).fetchone()
            if shared_summary is None:
                raise M7AdapterError("M7 shared-evidence audit returned no result")
            observed_shared_count = int(shared_summary[0])
            shared_orphans = scalar(
                connection,
                f"""
                SELECT count(*)
                FROM read_parquet('{escaped_shared}', union_by_name=true) s
                LEFT JOIN read_parquet('{escaped_pairs}', union_by_name=true) p
                USING(candidate_pair_id)
                WHERE p.candidate_pair_id IS NULL
                """,
            )
            if duplicate_passage_pairs or join_mismatches:
                raise M7AdapterError("M7 candidate pair/evidence join is not exact and one-to-one")
            if observed_shared_count != table_counts["shared_evidence"]:
                raise M7AdapterError(
                    "M7 shared_evidence count disagrees with its authenticated manifest"
                )
            if int(shared_summary[1]) != observed_shared_count or shared_orphans:
                raise M7AdapterError("M7 shared evidence is duplicated or orphaned")
            indexed_candidate_count = _write_shared_evidence_index(
                connection,
                escaped_shared_glob=escaped_shared,
                path=temporary_index,
                expected_row_count=observed_shared_count,
            )
            if indexed_candidate_count > observed_pair_count:
                raise M7AdapterError("M7 shared-evidence index exceeds the candidate universe")
            connection.execute(
                f"""
                COPY (
                    SELECT
                        p.candidate_pair_id,
                        p.passage_a_id,
                        p.passage_b_id,
                        p.passage_a_reference,
                        p.passage_b_reference,
                        p.known_link_status,
                        p.openbible_relationship_ids_json,
                        p.disputed_passage_flag,
                        p.reference_gap,
                        p.ketiv_structural_uncertainty,
                        p.direct_adjacency,
                        p.nearby_context,
                        p.exact_duplicate,
                        p.near_exact_duplicate,
                        p.formulaic_evidence_flag,
                        p.contains_english_derived_evidence,
                        p.non_english_evidence_remains,
                        p.score_after_removing_all_english_features,
                        p.english_ablation_survives,
                        e.raw_rrf_score,
                        e.rrf_score,
                        e.estimated_empirical_fdr,
                        e.benjamini_hochberg_q_value,
                        e.both_null_families_present,
                        e.detector_trace_digest,
                        e.ablation_digest,
                        e.evidence_digest,
                        coalesce(i.m7_shared_evidence_count, 0)::BIGINT
                            AS m7_shared_evidence_count,
                        coalesce(i.m7_shared_evidence_ids_json, '[]')
                            AS m7_shared_evidence_ids_json,
                        coalesce(
                            i.m7_shared_evidence_digest,
                            '{_EMPTY_SHARED_EVIDENCE_DIGEST}'
                        ) AS m7_shared_evidence_digest,
                        {observed_pair_count}::BIGINT AS m7_projection_candidate_pair_count,
                        {observed_evidence_count}::BIGINT
                            AS m7_projection_candidate_evidence_count,
                        {observed_shared_count}::BIGINT
                            AS m7_projection_shared_evidence_count,
                        '{escaped_manifest_sha256}' AS m7_source_manifest_sha256,
                        '{escaped_pairs_logical}' AS m7_candidate_pairs_logical_sha256,
                        '{escaped_evidence_logical}' AS m7_candidate_evidence_logical_sha256,
                        '{escaped_shared_logical}' AS m7_shared_evidence_logical_sha256
                    FROM read_parquet('{escaped_pairs}', union_by_name=true) AS p
                    INNER JOIN read_parquet('{escaped_evidence}', union_by_name=true) AS e
                    USING (candidate_pair_id)
                    LEFT JOIN read_parquet('{escaped_index}') AS i
                    USING (candidate_pair_id)
                    ORDER BY p.candidate_pair_id
                ) TO '{escaped_output}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
                """
            )
        projected_rows = pq.ParquetFile(temporary).metadata.num_rows
        if projected_rows != observed_pair_count:
            raise M7AdapterError(
                "M7 projection output count disagrees with its exact one-to-one source join"
            )
        temporary_index.unlink()
        if output_path.exists():
            raise M7AdapterError(f"refusing to replace existing M7 projection: {output_path}")
        temporary.replace(output_path)
    except M7AdapterError:
        if temporary.exists():
            temporary.unlink()
        if temporary_index.exists():
            temporary_index.unlink()
        raise
    except (duckdb.Error, OSError) as exc:
        if temporary.exists():
            temporary.unlink()
        if temporary_index.exists():
            temporary_index.unlink()
        raise M7AdapterError(f"could not build M7 lexical projection: {exc}") from exc
    return output_path


def iter_m7_raw_evidence(
    projection_path: Path,
    *,
    registration: DetectorRegistration,
    source_artifact_sha256: str,
    batch_size: int = 65536,
) -> Iterator[RawEvidence]:
    """Yield canonical lexical-family evidence from the authenticated projection."""

    if registration.detector_id != "m7_lexical_rrf" or registration.family != "lexical":
        raise M7AdapterError("M7 projection requires the registered m7_lexical_rrf detector")
    if batch_size < 1:
        raise M7AdapterError("M7 adapter batch_size must be positive")
    parquet = pq.ParquetFile(projection_path)
    required_columns = {
        "candidate_pair_id",
        "passage_a_id",
        "passage_b_id",
        "passage_a_reference",
        "passage_b_reference",
        "known_link_status",
        "openbible_relationship_ids_json",
        "disputed_passage_flag",
        "reference_gap",
        "ketiv_structural_uncertainty",
        "direct_adjacency",
        "nearby_context",
        "exact_duplicate",
        "near_exact_duplicate",
        "formulaic_evidence_flag",
        "contains_english_derived_evidence",
        "non_english_evidence_remains",
        "score_after_removing_all_english_features",
        "english_ablation_survives",
        "raw_rrf_score",
        "rrf_score",
        "estimated_empirical_fdr",
        "benjamini_hochberg_q_value",
        "both_null_families_present",
        "detector_trace_digest",
        "ablation_digest",
        "evidence_digest",
        "m7_shared_evidence_count",
        "m7_shared_evidence_ids_json",
        "m7_shared_evidence_digest",
        "m7_projection_candidate_pair_count",
        "m7_projection_candidate_evidence_count",
        "m7_projection_shared_evidence_count",
        "m7_source_manifest_sha256",
        "m7_candidate_pairs_logical_sha256",
        "m7_candidate_evidence_logical_sha256",
        "m7_shared_evidence_logical_sha256",
    }
    if set(parquet.schema.names) != required_columns:
        raise M7AdapterError("M7 projection does not have the exact registered column inventory")
    previous_source_candidate_id: str | None = None
    for batch in parquet.iter_batches(batch_size=batch_size):
        for row in batch.to_pylist():
            values = cast(dict[str, object], row)
            source_candidate_id = str(values["candidate_pair_id"])
            if not source_candidate_id or (
                previous_source_candidate_id is not None
                and source_candidate_id <= previous_source_candidate_id
            ):
                raise M7AdapterError("M7 projection candidate IDs are not unique and ordered")
            previous_source_candidate_id = source_candidate_id
            if values["m7_source_manifest_sha256"] != source_artifact_sha256:
                raise M7AdapterError("M7 projection is not bound to the supplied source manifest")
            logical_hashes = {
                "candidate_pairs": str(values["m7_candidate_pairs_logical_sha256"]),
                "candidate_evidence": str(values["m7_candidate_evidence_logical_sha256"]),
                "shared_evidence": str(values["m7_shared_evidence_logical_sha256"]),
            }
            if not all(_is_sha256(value) for value in logical_hashes.values()):
                raise M7AdapterError("M7 projection carries an invalid logical table hash")
            shared_count = int(cast(int, values["m7_shared_evidence_count"]))
            if shared_count < 0:
                raise M7AdapterError("M7 projection carries a negative shared-evidence count")
            shared_ids = _shared_evidence_ids(
                values["m7_shared_evidence_ids_json"],
                expected_count=shared_count,
            )
            shared_digest = str(values["m7_shared_evidence_digest"])
            if not _is_sha256(shared_digest):
                raise M7AdapterError("M7 projection carries an invalid shared-evidence digest")
            projection_counts = {
                "candidate_pairs": int(cast(int, values["m7_projection_candidate_pair_count"])),
                "candidate_evidence": int(
                    cast(int, values["m7_projection_candidate_evidence_count"])
                ),
                "shared_evidence": int(cast(int, values["m7_projection_shared_evidence_count"])),
            }
            if (
                projection_counts["candidate_pairs"] < 1
                or projection_counts["candidate_evidence"] != projection_counts["candidate_pairs"]
                or projection_counts["shared_evidence"] < shared_count
            ):
                raise M7AdapterError("M7 projection carries impossible audited source counts")
            english = bool(values["contains_english_derived_evidence"])
            original_remains = bool(values["non_english_evidence_remains"])
            raw_score = float(cast(float, values["rrf_score"]))
            raw_ablated = values["score_after_removing_all_english_features"]
            ablated_score = (
                float(cast(float, raw_ablated))
                if raw_ablated is not None
                else raw_score
                if not english
                else 0.0
            )
            passage_a_id = str(values["passage_a_id"])
            passage_b_id = str(values["passage_b_id"])
            passage_a_reference = str(values["passage_a_reference"])
            passage_b_reference = str(values["passage_b_reference"])
            if not passage_a_reference or not passage_b_reference:
                raise M7AdapterError("M7 projection carries an empty passage reference")
            known_link_status = str(values["known_link_status"])
            relationship_ids = _relationship_ids(values["openbible_relationship_ids_json"])
            represented = known_link_status == "represented_in_openbible_snapshot"
            unresolved = known_link_status == "mapping_unresolved"
            if known_link_status not in {
                "represented_in_openbible_snapshot",
                "not_represented_in_openbible_snapshot",
                "mapping_unresolved",
            }:
                raise M7AdapterError(f"unrecognized M7 known-link status: {known_link_status}")
            if represented != bool(relationship_ids):
                raise M7AdapterError("M7 known-link status and relationship IDs disagree")
            source_quality = QualityFlags(
                disputed_passage=bool(values["disputed_passage_flag"]),
                reference_gap=bool(values["reference_gap"]),
                ketiv_uncertainty=bool(values["ketiv_structural_uncertainty"]),
                formulaic_language=bool(values["formulaic_evidence_flag"]),
                overlapping_passages=False,
                unresolved_data_error=unresolved,
                invalid_trace=False,
                local_context=bool(values["direct_adjacency"]) or bool(values["nearby_context"]),
                exact_or_near_duplicate=bool(values["exact_duplicate"])
                or bool(values["near_exact_duplicate"]),
            )
            trace = {
                "representation": "canonical_m7_reciprocal_rank_fusion",
                "m7_candidate_pair_id": source_candidate_id,
                "m7_passage_references": {
                    passage_a_id: passage_a_reference,
                    passage_b_id: passage_b_reference,
                },
                "raw_rrf_score": float(cast(float, values["raw_rrf_score"])),
                "rrf_score": float(cast(float, values["rrf_score"])),
                "m7_empirical_fdr": _finite_or_registered_sentinel(
                    values["estimated_empirical_fdr"]
                ),
                "m7_bh_q_value": float(cast(float, values["benjamini_hochberg_q_value"])),
                "m7_both_null_families_present": bool(values["both_null_families_present"]),
                "m7_detector_trace_digest": str(values["detector_trace_digest"]),
                "m7_evidence_digest": str(values["evidence_digest"]),
                "m7_ablation_digest": str(values["ablation_digest"]),
                "m7_shared_evidence_locator": {
                    "artifact": "canonical_m7_shared_evidence",
                    "candidate_pair_id": source_candidate_id,
                    "selection_key": "candidate_pair_id",
                    "source_manifest_sha256": source_artifact_sha256,
                    "source_table_logical_sha256": logical_hashes["shared_evidence"],
                },
                "m7_shared_evidence_count": shared_count,
                "m7_shared_evidence_ids": shared_ids,
                "m7_shared_evidence_digest": shared_digest,
                "m7_shared_evidence_hydrated": False,
                "m7_source_manifest_sha256": source_artifact_sha256,
                "m7_source_table_logical_sha256": logical_hashes,
                "m7_projection_audit_counts": projection_counts,
                "m7_english_ablation_survives": bool(values["english_ablation_survives"]),
                "m7_score_after_removing_all_english_features": ablated_score,
                "m7_known_link_status": known_link_status,
                "m7_openbible_relationship_ids": relationship_ids,
                "m7_quality": source_quality.model_dump(mode="json"),
            }
            yield RawEvidence(
                candidate_pair_id=candidate_pair_id(passage_a_id, passage_b_id),
                passage_a_id=passage_a_id,
                passage_b_id=passage_b_id,
                detector_id=registration.detector_id,
                family="lexical",
                independence_group=registration.independence_group,
                raw_score=raw_score,
                contains_english_derived_evidence=english,
                original_language_evidence_remains=original_remains,
                counts_for_independence=registration.counts_for_independence
                and (not english or original_remains),
                english_ablation_raw_score=ablated_score,
                source_quality=source_quality,
                source_knownness_status="known_m7_snapshot" if represented else None,
                source_known_relationship_ids=relationship_ids,
                trace_json=canonical_json(trace),
                source_artifact_id="m7-canonical-schema-v1",
                source_artifact_sha256=source_artifact_sha256,
            )


def _hydration_selection_values(
    row: RawEvidence | EvidenceRow,
    *,
    selection_ordinal: int,
    manifest_sha256: str,
    table_counts: dict[str, int],
    logical_hashes: dict[str, str],
) -> tuple[object, ...]:
    if row.detector_id != "m7_lexical_rrf" or row.family != "lexical":
        raise M7AdapterError("shared-evidence hydration accepts only canonical M7 rows")
    if row.source_artifact_sha256 != manifest_sha256:
        raise M7AdapterError("M7 hydration row is bound to a different source manifest")
    try:
        raw_trace = json.loads(row.trace_json)
    except json.JSONDecodeError as exc:
        raise M7AdapterError("M7 hydration row has an invalid trace") from exc
    if not isinstance(raw_trace, dict):
        raise M7AdapterError("M7 hydration trace must be an object")
    trace = cast(dict[str, object], raw_trace)
    if trace.get("representation") != "canonical_m7_reciprocal_rank_fusion":
        raise M7AdapterError("M7 hydration row has the wrong representation")
    if trace.get("m7_projection_audit_counts") != {
        "candidate_pairs": table_counts["candidate_pairs"],
        "candidate_evidence": table_counts["candidate_evidence"],
        "shared_evidence": table_counts["shared_evidence"],
    }:
        raise M7AdapterError("M7 hydration trace carries stale source-table counts")
    if trace.get("m7_shared_evidence_hydrated") is not False:
        raise M7AdapterError("M7 shared evidence is already hydrated or ambiguously marked")
    source_candidate_id = trace.get("m7_candidate_pair_id")
    if not isinstance(source_candidate_id, str) or not source_candidate_id:
        raise M7AdapterError("M7 hydration trace has no source candidate ID")
    expected_locator = {
        "artifact": "canonical_m7_shared_evidence",
        "candidate_pair_id": source_candidate_id,
        "selection_key": "candidate_pair_id",
        "source_manifest_sha256": manifest_sha256,
        "source_table_logical_sha256": logical_hashes["shared_evidence"],
    }
    if trace.get("m7_shared_evidence_locator") != expected_locator:
        raise M7AdapterError("M7 shared-evidence locator is stale or unauthenticated")
    count = trace.get("m7_shared_evidence_count")
    ids = trace.get("m7_shared_evidence_ids")
    digest = trace.get("m7_shared_evidence_digest")
    if not isinstance(count, int) or count < 0:
        raise M7AdapterError("M7 hydration trace has an invalid evidence count")
    if not isinstance(ids, list):
        raise M7AdapterError("M7 hydration trace has invalid evidence IDs")
    expected_ids = _shared_evidence_ids(canonical_json(ids), expected_count=count)
    if not isinstance(digest, str) or not _is_sha256(digest):
        raise M7AdapterError("M7 hydration trace has an invalid evidence digest")
    model_kind = "evidence" if isinstance(row, EvidenceRow) else "raw"
    row_identity = row.evidence_id if isinstance(row, EvidenceRow) else f"raw-{selection_ordinal}"
    return (
        selection_ordinal,
        row_identity,
        source_candidate_id,
        row.passage_a_id,
        row.passage_b_id,
        model_kind,
        canonical_json(row.model_dump(mode="json")),
        canonical_json(trace),
        count,
        canonical_json(expected_ids),
        digest,
    )


def _hydrate_joined_group(
    metadata: dict[str, object],
    shared_rows: list[dict[str, object]],
) -> RawEvidence | EvidenceRow:
    source_candidate_id = str(metadata["source_candidate_id"])
    if int(cast(int, metadata["source_pair_match_count"] or 0)) != 1:
        raise M7AdapterError("M7 hydration candidate lookup is not one-to-one")
    if metadata["source_passage_a_id"] is None or metadata["source_passage_b_id"] is None:
        raise M7AdapterError("M7 hydration locator references an absent candidate")
    model_kind = str(metadata["model_kind"])
    row_json = str(metadata["row_json"])
    if model_kind == "evidence":
        row: RawEvidence | EvidenceRow = EvidenceRow.model_validate_json(row_json)
    elif model_kind == "raw":
        row = RawEvidence.model_validate_json(row_json)
    else:  # pragma: no cover - constrained by the private selection table
        raise M7AdapterError("M7 hydration selection has an invalid model kind")
    if (row.passage_a_id, row.passage_b_id) != (
        str(metadata["source_passage_a_id"]),
        str(metadata["source_passage_b_id"]),
    ):
        raise M7AdapterError("M7 hydration candidate passage IDs disagree")
    expected_count = int(cast(int, metadata["expected_shared_count"]))
    expected_ids = _shared_evidence_ids(
        metadata["expected_shared_ids_json"],
        expected_count=expected_count,
    )
    expected_digest = str(metadata["expected_shared_digest"])
    shared_evidence, observed_digest = _validate_shared_evidence_rows(
        shared_rows,
        candidate_pair_id_value=source_candidate_id,
        expected_count=expected_count,
    )
    observed_ids = tuple(str(item["evidence_id"]) for item in shared_evidence)
    if observed_ids != expected_ids or observed_digest != expected_digest:
        raise M7AdapterError("hydrated M7 shared evidence disagrees with its compact index")
    trace_value = json.loads(str(metadata["trace_json"]))
    if not isinstance(trace_value, dict):  # pragma: no cover - validated before insertion
        raise M7AdapterError("M7 hydration trace must be an object")
    trace = cast(dict[str, object], trace_value)
    trace["m7_shared_evidence"] = shared_evidence
    trace["m7_shared_evidence_hydrated"] = True
    trace["m7_shared_evidence_hydration_scope"] = "explicit_bounded_review_subset"
    return row.model_copy(update={"trace_json": canonical_json(trace)})


def _hydrate_m7_shared_evidence_to_consumer[T: (RawEvidence, EvidenceRow)](
    rows: Iterable[T],
    input_root: Path,
    *,
    memory_limit_bytes: int,
    temp_directory: Path,
    selection_batch_size: int,
    arrow_batch_size: int,
    consume: Callable[[T], None],
) -> _HydrationStatistics:
    """Hydrate one source scan while retaining only capped selection/Arrow batches."""

    if memory_limit_bytes < 256 * 1024**2:
        raise M7AdapterError("M7 shared-evidence hydration requires at least 256 MiB")
    if selection_batch_size < 1:
        raise M7AdapterError("M7 hydration selection_batch_size must be positive")
    if arrow_batch_size < 1:
        raise M7AdapterError("M7 shared-evidence hydration batch_size must be positive")
    input_root = input_root.resolve()
    manifest_sha256, table_counts, logical_hashes = _projection_manifest_contract(input_root)
    pair_paths = list((input_root / "candidate_pairs").glob("part-*.parquet"))
    shared_paths = list((input_root / "shared_evidence").glob("part-*.parquet"))
    if table_counts["candidate_pairs"] and not pair_paths:
        raise M7AdapterError("M7 candidate_pairs leaves are missing during hydration")
    if table_counts["shared_evidence"] and not shared_paths:
        raise M7AdapterError("M7 shared_evidence leaves are missing during hydration")

    temp_directory.mkdir(parents=True, exist_ok=True)
    escaped_temp = temp_directory.resolve().as_posix().replace("'", "''")
    escaped_pairs = (
        (input_root / "candidate_pairs" / "part-*.parquet").as_posix().replace("'", "''")
    )
    shared_columns = LEXICAL_ARTIFACT_COLUMNS["shared_evidence"]
    if shared_paths:
        escaped_shared = (
            (input_root / "shared_evidence" / "part-*.parquet").as_posix().replace("'", "''")
        )
        shared_relation = f"read_parquet('{escaped_shared}', union_by_name=true)"
    else:
        empty_columns = ", ".join(
            (
                "NULL::VARCHAR AS candidate_pair_id"
                if column == "candidate_pair_id"
                else f"NULL AS {column}"
            )
            for column in shared_columns
        )
        shared_relation = f"(SELECT {empty_columns} WHERE FALSE)"
    selected_columns = (
        "selection_ordinal,row_identity,source_candidate_id,passage_a_id,passage_b_id,"
        "model_kind,row_json,trace_json,expected_shared_count,expected_shared_ids_json,"
        "expected_shared_digest"
    )
    selected_placeholders = ",".join("?" for _ in range(11))
    selected_count = 0
    maximum_batch_rows = 0
    selection_batch: list[tuple[object, ...]] = []
    try:
        with duckdb.connect() as connection:
            connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
            connection.execute("SET threads=1")
            connection.execute(f"SET temp_directory='{escaped_temp}'")
            connection.execute(
                """
                CREATE TEMP TABLE selected_m7_pairs(
                    selection_ordinal BIGINT NOT NULL,
                    row_identity VARCHAR NOT NULL,
                    source_candidate_id VARCHAR NOT NULL,
                    passage_a_id VARCHAR NOT NULL,
                    passage_b_id VARCHAR NOT NULL,
                    model_kind VARCHAR NOT NULL,
                    row_json VARCHAR NOT NULL,
                    trace_json VARCHAR NOT NULL,
                    expected_shared_count BIGINT NOT NULL,
                    expected_shared_ids_json VARCHAR NOT NULL,
                    expected_shared_digest VARCHAR NOT NULL
                )
                """
            )
            for row in rows:
                selection_batch.append(
                    _hydration_selection_values(
                        row,
                        selection_ordinal=selected_count,
                        manifest_sha256=manifest_sha256,
                        table_counts=table_counts,
                        logical_hashes=logical_hashes,
                    )
                )
                selected_count += 1
                if len(selection_batch) == selection_batch_size:
                    connection.executemany(
                        f"INSERT INTO selected_m7_pairs({selected_columns}) "
                        f"VALUES ({selected_placeholders})",
                        selection_batch,
                    )
                    maximum_batch_rows = max(maximum_batch_rows, len(selection_batch))
                    selection_batch.clear()
            if selection_batch:
                connection.executemany(
                    f"INSERT INTO selected_m7_pairs({selected_columns}) "
                    f"VALUES ({selected_placeholders})",
                    selection_batch,
                )
                maximum_batch_rows = max(maximum_batch_rows, len(selection_batch))
                selection_batch.clear()
            if selected_count == 0:
                return _HydrationStatistics(
                    row_count=0,
                    maximum_selection_batch_rows_observed=0,
                    source_manifest_sha256=manifest_sha256,
                )
            duplicate_source = connection.execute(
                """
                SELECT source_candidate_id
                FROM selected_m7_pairs
                GROUP BY source_candidate_id
                HAVING count(*) != 1
                LIMIT 1
                """
            ).fetchone()
            if duplicate_source is not None:
                raise M7AdapterError("M7 hydration repeats a source candidate ID")
            duplicate_identity = connection.execute(
                """
                SELECT row_identity
                FROM selected_m7_pairs
                WHERE model_kind = 'evidence'
                GROUP BY row_identity
                HAVING count(*) != 1
                LIMIT 1
                """
            ).fetchone()
            if duplicate_identity is not None:
                raise M7AdapterError("M7 hydration repeats an evidence ID")

            projected_shared_columns = ", ".join(
                f"s.{column} AS shared_{column}" for column in shared_columns
            )
            reader = connection.execute(
                f"""
                WITH source_pairs AS (
                    SELECT
                        candidate_pair_id,
                        count(*)::BIGINT AS source_pair_match_count,
                        min(passage_a_id) AS passage_a_id,
                        min(passage_b_id) AS passage_b_id
                    FROM read_parquet('{escaped_pairs}', union_by_name=true)
                    GROUP BY candidate_pair_id
                )
                SELECT
                    x.selection_ordinal,
                    x.source_candidate_id,
                    x.model_kind,
                    x.row_json,
                    x.trace_json,
                    x.expected_shared_count,
                    x.expected_shared_ids_json,
                    x.expected_shared_digest,
                    p.source_pair_match_count,
                    p.passage_a_id AS source_passage_a_id,
                    p.passage_b_id AS source_passage_b_id,
                    {projected_shared_columns}
                FROM selected_m7_pairs x
                LEFT JOIN source_pairs p
                    ON p.candidate_pair_id = x.source_candidate_id
                LEFT JOIN {shared_relation} s
                    ON s.candidate_pair_id = x.source_candidate_id
                ORDER BY
                    x.selection_ordinal,
                    s.evidence_family,
                    s.feature_id,
                    s.evidence_id
                """
            ).to_arrow_reader(batch_size=arrow_batch_size)
            current_ordinal: int | None = None
            current_metadata: dict[str, object] | None = None
            current_shared_rows: list[dict[str, object]] = []
            hydrated_count = 0
            for batch in reader:
                for raw_row in batch.to_pylist():
                    joined = cast(dict[str, object], raw_row)
                    ordinal = int(cast(int, joined["selection_ordinal"]))
                    if current_ordinal is not None and ordinal != current_ordinal:
                        if ordinal != current_ordinal + 1 or current_metadata is None:
                            raise M7AdapterError(
                                "M7 hydration selection ordering is not contiguous"
                            )
                        consume(
                            cast(
                                T,
                                _hydrate_joined_group(current_metadata, current_shared_rows),
                            )
                        )
                        hydrated_count += 1
                        current_shared_rows = []
                    if ordinal != current_ordinal:
                        current_ordinal = ordinal
                        current_metadata = joined
                    if joined["shared_evidence_id"] is not None:
                        current_shared_rows.append(
                            {column: joined[f"shared_{column}"] for column in shared_columns}
                        )
            if current_metadata is not None:
                consume(cast(T, _hydrate_joined_group(current_metadata, current_shared_rows)))
                hydrated_count += 1
            if hydrated_count != selected_count:
                raise M7AdapterError("M7 hydration did not return every selected row exactly once")
    except duckdb.Error as exc:
        raise M7AdapterError(f"could not hydrate M7 shared evidence: {exc}") from exc
    return _HydrationStatistics(
        row_count=selected_count,
        maximum_selection_batch_rows_observed=maximum_batch_rows,
        source_manifest_sha256=manifest_sha256,
    )


def hydrate_m7_shared_evidence[T: (RawEvidence, EvidenceRow)](
    rows: Sequence[T],
    input_root: Path,
    *,
    memory_limit_bytes: int,
    temp_directory: Path,
    batch_size: int = 65_536,
    selection_batch_size: int = M7_HYDRATION_SELECTION_BATCH_SIZE,
) -> tuple[T, ...]:
    """Hydrate one explicitly capped in-memory selection.

    Large Tier A/Tier B populations must use :func:`build_m7_hydration_index`.
    This compatibility helper refuses to create an unbounded result tuple.
    """

    if not rows:
        return ()
    if selection_batch_size < 1:
        raise M7AdapterError("M7 hydration selection_batch_size must be positive")
    if len(rows) > selection_batch_size:
        raise M7AdapterError(
            "M7 in-memory hydration selection exceeds the declared batch cap of "
            f"{selection_batch_size}"
        )
    hydrated: list[T] = []
    _hydrate_m7_shared_evidence_to_consumer(
        rows,
        input_root,
        memory_limit_bytes=memory_limit_bytes,
        temp_directory=temp_directory,
        selection_batch_size=selection_batch_size,
        arrow_batch_size=batch_size,
        consume=hydrated.append,
    )
    return tuple(hydrated)


def _open_hydration_index(path: Path, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-32768")
    return connection


def build_m7_hydration_index(
    rows: Iterable[EvidenceRow],
    input_root: Path,
    output_path: Path,
    *,
    memory_limit_bytes: int,
    temp_directory: Path,
    selection_batch_size: int = M7_HYDRATION_SELECTION_BATCH_SIZE,
    batch_size: int = 65_536,
) -> M7HydrationIndexReceipt:
    """Stream hydrated M7 rows into an exact transient disk-backed lookup."""

    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"M7 hydration index already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.writing-{uuid.uuid4().hex}")
    connection: sqlite3.Connection | None = None
    try:
        connection = _open_hydration_index(temporary, readonly=False)
        connection.execute(
            """
            CREATE TABLE hydrated_evidence(
                evidence_id TEXT PRIMARY KEY,
                candidate_pair_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        active_connection = connection

        def consume(row: EvidenceRow) -> None:
            try:
                active_connection.execute(
                    "INSERT INTO hydrated_evidence VALUES (?,?,?)",
                    (
                        row.evidence_id,
                        row.candidate_pair_id,
                        canonical_json(row.model_dump(mode="json")),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise M7AdapterError("M7 hydration repeats an evidence ID") from exc

        statistics = _hydrate_m7_shared_evidence_to_consumer(
            rows,
            input_root,
            memory_limit_bytes=memory_limit_bytes,
            temp_directory=temp_directory,
            selection_batch_size=selection_batch_size,
            arrow_batch_size=batch_size,
            consume=consume,
        )
        receipt = M7HydrationIndexReceipt(
            row_count=statistics.row_count,
            source_scan_count=1 if statistics.row_count else 0,
            selection_batch_size=selection_batch_size,
            maximum_selection_batch_rows_observed=(
                statistics.maximum_selection_batch_rows_observed
            ),
            arrow_batch_size=batch_size,
            source_manifest_sha256=statistics.source_manifest_sha256,
        )
        connection.execute("CREATE TABLE metadata(receipt_json TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES (?)", (receipt.model_dump_json(),))
        connection.commit()
        connection.close()
        connection = None
        temporary.replace(output_path)
    except Exception:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)
        for suffix in ("-journal", "-shm", "-wal"):
            temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
        raise
    return receipt


class M7HydratedEvidenceLookup:
    """Read exact hydrated rows without retaining the selected population in Python."""

    def __init__(self, path: Path, receipt: M7HydrationIndexReceipt) -> None:
        self.path = path.resolve()
        self.receipt = receipt
        self.lookup_count = 0
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> M7HydratedEvidenceLookup:
        if not self.path.is_file():
            raise M7AdapterError(f"M7 hydration index is missing: {self.path}")
        connection = _open_hydration_index(self.path, readonly=True)
        try:
            metadata = connection.execute("SELECT receipt_json FROM metadata").fetchone()
            if (
                metadata is None
                or M7HydrationIndexReceipt.model_validate_json(str(metadata[0])) != self.receipt
            ):
                raise M7AdapterError("M7 hydration index receipt disagrees with the index")
            count = int(connection.execute("SELECT count(*) FROM hydrated_evidence").fetchone()[0])
            if count != self.receipt.row_count:
                raise M7AdapterError("M7 hydration index row count disagrees with its receipt")
        except Exception:
            connection.close()
            raise
        self._connection = connection
        return self

    def __exit__(self, *_args: object) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __call__(self, row: EvidenceRow) -> EvidenceRow:
        if self._connection is None:
            raise M7AdapterError("M7 hydration lookup is not open")
        result = self._connection.execute(
            "SELECT candidate_pair_id,payload_json FROM hydrated_evidence WHERE evidence_id=?",
            (row.evidence_id,),
        ).fetchone()
        if result is None:
            raise M7AdapterError(
                f"hydrated M7 evidence is absent from the index: {row.evidence_id}"
            )
        hydrated = EvidenceRow.model_validate_json(str(result[1]))
        if (
            str(result[0]) != row.candidate_pair_id
            or hydrated.model_copy(update={"trace_json": row.trace_json}) != row
        ):
            raise M7AdapterError("hydrated M7 evidence disagrees with its compact source row")
        self.lookup_count += 1
        return hydrated
