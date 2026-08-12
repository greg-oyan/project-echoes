"""Authenticated, bounded M6 OpenBible-to-passage knownness projection."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, Self, cast

import duckdb
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes.benchmarks.models import BENCHMARK_ARTIFACT_COLUMNS, BENCHMARK_ARTIFACT_NAMES
from echoes.final_discovery.knownness import KnownRelationship

_USED_TABLES = (
    "benchmark_relationships",
    "benchmark_endpoints",
    "benchmark_endpoint_mappings",
)
_EligibleMappingStatus = Literal["mapped_verified", "mapped_provisional", "mapped_partial"]
_ELIGIBLE_MAPPING_STATUSES: tuple[_EligibleMappingStatus, ...] = (
    "mapped_verified",
    "mapped_provisional",
    "mapped_partial",
)
_SOURCE_ID = "openbible-cross-references"
_PROJECTION_SCHEMA: Literal["project-echoes-openbible-knownness-v1"] = (
    "project-echoes-openbible-knownness-v1"
)
_ORDERING = (
    "source_relationship_id",
    "source_passage_id",
    "target_passage_id",
    "relationship_id",
)


class KnownnessProjectionError(ValueError):
    """Raised when governed M6 inputs or a projected knownness file fail closed."""


class _BenchmarkHashManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_schema_version: Literal[1]
    table_counts: dict[str, int]
    table_logical_sha256: dict[str, str]
    table_physical_sha256: dict[str, str]

    @model_validator(mode="after")
    def exact_governed_inventory(self) -> Self:
        expected = set(BENCHMARK_ARTIFACT_NAMES)
        for name, values in (
            ("counts", self.table_counts),
            ("logical hashes", self.table_logical_sha256),
            ("physical hashes", self.table_physical_sha256),
        ):
            if set(values) != expected:
                raise ValueError(f"benchmark manifest {name} do not cover the exact schema")
        if any(value < 0 for value in self.table_counts.values()):
            raise ValueError("benchmark table counts must be nonnegative")
        for values in (self.table_logical_sha256, self.table_physical_sha256):
            if any(
                len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
                for value in values.values()
            ):
                raise ValueError("benchmark table hashes must be lowercase SHA-256 values")
        return self


class KnownnessProjectionReceipt(BaseModel):
    """Deterministic authentication receipt for one projected JSONL artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    projection_schema: Literal["project-echoes-openbible-knownness-v1"]
    source_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    used_table_physical_sha256: dict[str, str]
    eligible_mapping_statuses: tuple[
        Literal["mapped_verified", "mapped_provisional", "mapped_partial"], ...
    ]
    target_analysis_profile: Literal["edition_complete"]
    ordering: tuple[str, ...]
    output_file_name: str = Field(min_length=1)
    projection_query_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    eligible_source_relationship_count: int = Field(ge=1)
    mapped_endpoint_target_count: int = Field(ge=1)
    expanded_edge_count: int = Field(ge=1)
    excluded_self_edge_count: int = Field(ge=0)
    represented_source_relationship_count: int = Field(ge=1)
    unique_unordered_pair_count: int = Field(ge=1)
    multi_pair_relationship_count: int = Field(ge=0)
    maximum_pairs_per_relationship: int = Field(ge=1)
    row_count: int = Field(ge=1)
    logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    jsonl_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def governed_values_are_exact(self) -> Self:
        if set(self.used_table_physical_sha256) != set(_USED_TABLES):
            raise ValueError("receipt must cover the exact used M6 tables")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in self.used_table_physical_sha256.values()
        ):
            raise ValueError("receipt used-table hashes must be lowercase SHA-256 values")
        if self.eligible_mapping_statuses != _ELIGIBLE_MAPPING_STATUSES:
            raise ValueError("receipt mapping statuses differ from the governed projection")
        if self.ordering != _ORDERING:
            raise ValueError("receipt ordering differs from the governed projection")
        return self


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _canonical_relationship_bytes(relationship: KnownRelationship) -> bytes:
    return _canonical_json(relationship.model_dump(mode="json")).encode("ascii")


def _logical_hasher() -> Any:
    digest = hashlib.sha256()
    digest.update(_PROJECTION_SCHEMA.encode("ascii"))
    digest.update(b"\0")
    return digest


def _update_logical_digest(digest: Any, payload: bytes) -> None:
    digest.update(payload)
    digest.update(b"\0")


def _projected_relationship_id(
    source_relationship_id: str, source_passage_id: str, target_passage_id: str
) -> str:
    payload = _canonical_json(
        {
            "projection_schema": _PROJECTION_SCHEMA,
            "source_relationship_id": source_relationship_id,
            "source_passage_id": source_passage_id,
            "target_passage_id": target_passage_id,
        }
    )
    return f"FDK_{hashlib.sha256(payload.encode('ascii')).hexdigest()}"


def _mapping_quality(statuses_a: list[str], statuses_b: list[str]) -> str:
    statuses = set((*statuses_a, *statuses_b))
    for status in reversed(_ELIGIBLE_MAPPING_STATUSES):
        if status in statuses:
            return status
    raise KnownnessProjectionError("projected relationship has no eligible mapping status")


def _quoted_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _load_and_authenticate_manifest(
    benchmark_root: Path, expected_manifest_sha256: str
) -> tuple[_BenchmarkHashManifest, dict[str, Path], dict[str, str]]:
    if len(expected_manifest_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in expected_manifest_sha256
    ):
        raise KnownnessProjectionError("expected M6 manifest hash must be lowercase SHA-256")
    root = benchmark_root.resolve()
    manifest_path = root / "table-hashes.json"
    if not manifest_path.is_file():
        raise KnownnessProjectionError(f"M6 table-hashes.json is missing from {root}")
    actual_manifest_sha256 = _sha256_file(manifest_path)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise KnownnessProjectionError(
            "M6 benchmark manifest hash mismatch: "
            f"{actual_manifest_sha256} != {expected_manifest_sha256}"
        )
    try:
        manifest = _BenchmarkHashManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError) as exc:
        raise KnownnessProjectionError(f"invalid M6 benchmark manifest: {exc}") from exc

    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for table in _USED_TABLES:
        table_root = root / table
        observed = sorted(
            path.relative_to(table_root).as_posix()
            for path in table_root.rglob("*.parquet")
            if path.is_file()
        )
        if observed != ["part-00000.parquet"]:
            raise KnownnessProjectionError(
                f"used M6 table {table} requires exact part-00000.parquet inventory"
            )
        path = table_root / "part-00000.parquet"
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise KnownnessProjectionError(
                f"used M6 table path escapes the benchmark root: {table}"
            ) from exc
        actual_hash = _sha256_file(path)
        expected_hash = manifest.table_physical_sha256[table]
        if actual_hash != expected_hash:
            raise KnownnessProjectionError(
                f"used M6 table physical hash mismatch for {table}: "
                f"{actual_hash} != {expected_hash}"
            )
        try:
            parquet = pq.ParquetFile(path)
            columns = tuple(parquet.schema_arrow.names)
            row_count = int(parquet.metadata.num_rows)
        except Exception as exc:
            raise KnownnessProjectionError(
                f"could not inspect used M6 table {table}: {exc}"
            ) from exc
        expected_columns = BENCHMARK_ARTIFACT_COLUMNS[cast(Any, table)]
        if columns != expected_columns:
            raise KnownnessProjectionError(
                f"used M6 table schema mismatch for {table}: {columns} != {expected_columns}"
            )
        if row_count != manifest.table_counts[table]:
            raise KnownnessProjectionError(
                f"used M6 table row count mismatch for {table}: "
                f"{row_count} != {manifest.table_counts[table]}"
            )
        paths[table] = path
        hashes[table] = actual_hash
    return manifest, paths, hashes


def _projection_query() -> str:
    return """
        SELECT
            source_relationship_id,
            source_version,
            source_reference_a,
            source_reference_b,
            relationship_direction,
            relationship_class,
            source_passage_id,
            target_passage_id,
            list_sort(list_distinct(list(mapping_id_a))) AS mapping_ids_a,
            list_sort(list_distinct(list(mapping_id_b))) AS mapping_ids_b,
            list_sort(list_distinct(list(mapping_status_a))) AS mapping_statuses_a,
            list_sort(list_distinct(list(mapping_status_b))) AS mapping_statuses_b
        FROM expanded_openbible_knownness
        WHERE source_passage_id <> target_passage_id
        GROUP BY ALL
        ORDER BY source_relationship_id, source_passage_id, target_passage_id
    """


def _projection_query_sha256() -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "projection_schema": _PROJECTION_SCHEMA,
                "source_id": _SOURCE_ID,
                "eligible_mapping_statuses": _ELIGIBLE_MAPPING_STATUSES,
                "target_analysis_profile": "edition_complete",
                "target_analysis_readings": ("qere", "source"),
                "target_granularity": "verse",
                "knownness_filter_eligible": True,
                "self_edge_policy": "exclude_and_count",
                "projection_query": _projection_query(),
            }
        ).encode("ascii")
    ).hexdigest()


def _relationship_from_query_row(
    row: tuple[object, ...], *, source_manifest_sha256: str
) -> KnownRelationship:
    (
        source_relationship_id,
        source_version,
        source_reference_a,
        source_reference_b,
        relationship_direction,
        relationship_class,
        source_passage_id,
        target_passage_id,
        raw_mapping_ids_a,
        raw_mapping_ids_b,
        raw_mapping_statuses_a,
        raw_mapping_statuses_b,
    ) = row
    mapping_ids_a = [str(value) for value in cast(list[object], raw_mapping_ids_a)]
    mapping_ids_b = [str(value) for value in cast(list[object], raw_mapping_ids_b)]
    statuses_a = [str(value) for value in cast(list[object], raw_mapping_statuses_a)]
    statuses_b = [str(value) for value in cast(list[object], raw_mapping_statuses_b)]
    source_id = str(source_relationship_id)
    passage_a = str(source_passage_id)
    passage_b = str(target_passage_id)
    provenance = {
        "projection_schema": _PROJECTION_SCHEMA,
        "source_id": _SOURCE_ID,
        "source_relationship_id": source_id,
        "source_version": str(source_version),
        "source_reference_a": str(source_reference_a),
        "source_reference_b": str(source_reference_b),
        "relationship_direction": str(relationship_direction),
        "relationship_class": str(relationship_class),
        "mapping_ids_a": mapping_ids_a,
        "mapping_ids_b": mapping_ids_b,
        "mapping_statuses_a": statuses_a,
        "mapping_statuses_b": statuses_b,
        "source_manifest_sha256": source_manifest_sha256,
    }
    return KnownRelationship(
        relationship_id=_projected_relationship_id(source_id, passage_a, passage_b),
        source_passage_id=passage_a,
        target_passage_id=passage_b,
        source_name=_SOURCE_ID,
        mapping_quality=_mapping_quality(statuses_a, statuses_b),
        source_relationship_id=source_id,
        source_manifest_sha256=source_manifest_sha256,
        source_provenance_json=_canonical_json(provenance),
    )


def project_openbible_knownness(
    benchmark_root: Path,
    output_jsonl: Path,
    receipt_path: Path,
    *,
    expected_manifest_sha256: str,
    memory_limit_bytes: int,
    temp_directory: Path,
    batch_size: int = 65_536,
) -> KnownnessProjectionReceipt:
    """Authenticate M6 and stream its eligible mapped OpenBible links to JSONL."""

    if memory_limit_bytes < 256 * 1024**2:
        raise KnownnessProjectionError("knownness projection requires at least 256 MiB")
    if batch_size < 1:
        raise KnownnessProjectionError("knownness projection batch_size must be positive")
    if output_jsonl.resolve() == receipt_path.resolve():
        raise KnownnessProjectionError("knownness JSONL and receipt paths must be distinct")
    if output_jsonl.exists() or receipt_path.exists():
        raise KnownnessProjectionError("knownness projection refuses to replace output artifacts")
    _, table_paths, used_hashes = _load_and_authenticate_manifest(
        benchmark_root, expected_manifest_sha256
    )
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temp_directory.mkdir(parents=True, exist_ok=True)
    temporary_output = output_jsonl.with_name(f".{output_jsonl.name}.{uuid.uuid4().hex}.tmp")
    temporary_receipt = receipt_path.with_name(f".{receipt_path.name}.{uuid.uuid4().hex}.tmp")
    physical_digest = hashlib.sha256()
    logical_digest = _logical_hasher()
    row_count = 0
    prior_order: tuple[str, str, str, str] | None = None
    relationships_path = _quoted_path(table_paths["benchmark_relationships"])
    endpoints_path = _quoted_path(table_paths["benchmark_endpoints"])
    mappings_path = _quoted_path(table_paths["benchmark_endpoint_mappings"])
    spill_path = _quoted_path(temp_directory)
    try:
        with duckdb.connect() as connection:
            connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
            connection.execute("SET threads=1")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute(f"SET temp_directory='{spill_path}'")
            connection.execute(
                f"""
                CREATE TEMP VIEW eligible_openbible_mappings AS
                SELECT
                    e.relationship_id,
                    e.endpoint_side,
                    m.mapping_id,
                    m.mapping_status,
                    trim(CAST(j.value AS VARCHAR), '"') AS target_passage_id
                FROM read_parquet('{endpoints_path}') e
                JOIN read_parquet('{mappings_path}') m USING (endpoint_id),
                     json_each(m.target_passage_ids_json) j
                WHERE m.target_analysis_profile='edition_complete'
                  AND m.target_analysis_reading IN ('qere','source')
                  AND m.target_granularity='verse'
                  AND m.mapping_status IN (
                      'mapped_verified','mapped_provisional','mapped_partial'
                  )
                  AND trim(CAST(j.value AS VARCHAR), '"') <> ''
                """
            )
            connection.execute(
                f"""
                CREATE TEMP VIEW expanded_openbible_knownness AS
                SELECT
                    r.relationship_id AS source_relationship_id,
                    r.source_version,
                    r.source_reference_a,
                    r.source_reference_b,
                    r.relationship_direction,
                    r.relationship_class,
                    a.target_passage_id AS source_passage_id,
                    b.target_passage_id AS target_passage_id,
                    a.mapping_id AS mapping_id_a,
                    b.mapping_id AS mapping_id_b,
                    a.mapping_status AS mapping_status_a,
                    b.mapping_status AS mapping_status_b
                FROM read_parquet('{relationships_path}') r
                JOIN eligible_openbible_mappings a
                  ON r.relationship_id=a.relationship_id AND a.endpoint_side='a'
                JOIN eligible_openbible_mappings b
                  ON r.relationship_id=b.relationship_id AND b.endpoint_side='b'
                WHERE r.benchmark_schema_version=1
                  AND r.tier=3
                  AND r.source_id='{_SOURCE_ID}'
                  AND r.knownness_filter_eligible=true
                """
            )
            statistics_row = connection.execute(
                f"""
                WITH retained AS ({_projection_query()}),
                per_relationship AS (
                    SELECT source_relationship_id,count(*) AS pair_count
                    FROM retained GROUP BY source_relationship_id
                )
                SELECT
                    (SELECT count(*) FROM read_parquet('{relationships_path}')
                     WHERE benchmark_schema_version=1 AND tier=3
                       AND source_id='{_SOURCE_ID}' AND knownness_filter_eligible=true),
                    (SELECT count(*) FROM eligible_openbible_mappings),
                    (SELECT count(*) FROM expanded_openbible_knownness),
                    (SELECT count(*) FROM expanded_openbible_knownness
                     WHERE source_passage_id=target_passage_id),
                    (SELECT count(*) FROM retained),
                    (SELECT count(DISTINCT source_relationship_id) FROM retained),
                    (SELECT count(DISTINCT (
                        least(source_passage_id,target_passage_id),
                        greatest(source_passage_id,target_passage_id)
                     )) FROM retained),
                    (SELECT count(*) FROM per_relationship WHERE pair_count>1),
                    (SELECT max(pair_count) FROM per_relationship)
                """
            ).fetchone()
            if statistics_row is None:
                raise KnownnessProjectionError("could not compute M6 knownness statistics")
            (
                eligible_source_count,
                mapped_endpoint_count,
                expanded_edge_count,
                self_count,
                retained_edge_count,
                represented_source_count,
                unique_unordered_count,
                multi_pair_count,
                maximum_pair_count,
            ) = (int(value) for value in statistics_row)
            cursor = connection.execute(_projection_query())
            with temporary_output.open("xb") as output_handle:
                while rows := cursor.fetchmany(batch_size):
                    for raw_row in rows:
                        relationship = _relationship_from_query_row(
                            cast(tuple[object, ...], raw_row),
                            source_manifest_sha256=expected_manifest_sha256,
                        )
                        order = (
                            relationship.source_relationship_id or "",
                            relationship.source_passage_id,
                            relationship.target_passage_id,
                            relationship.relationship_id,
                        )
                        if prior_order is not None and order <= prior_order:
                            raise KnownnessProjectionError(
                                "projected knownness rows are duplicate or out of order"
                            )
                        prior_order = order
                        payload = _canonical_relationship_bytes(relationship)
                        output_handle.write(payload)
                        output_handle.write(b"\n")
                        physical_digest.update(payload)
                        physical_digest.update(b"\n")
                        _update_logical_digest(logical_digest, payload)
                        row_count += 1
                output_handle.flush()
                os.fsync(output_handle.fileno())
        if row_count < 1:
            raise KnownnessProjectionError("M6 OpenBible knownness projection produced zero rows")
        if row_count != retained_edge_count:
            raise KnownnessProjectionError(
                "streamed knownness row count differs from the authenticated SQL count"
            )
        receipt = KnownnessProjectionReceipt(
            projection_schema=_PROJECTION_SCHEMA,
            source_manifest_sha256=expected_manifest_sha256,
            used_table_physical_sha256=used_hashes,
            eligible_mapping_statuses=_ELIGIBLE_MAPPING_STATUSES,
            target_analysis_profile="edition_complete",
            ordering=_ORDERING,
            output_file_name=output_jsonl.name,
            projection_query_sha256=_projection_query_sha256(),
            eligible_source_relationship_count=eligible_source_count,
            mapped_endpoint_target_count=mapped_endpoint_count,
            expanded_edge_count=expanded_edge_count,
            excluded_self_edge_count=self_count,
            represented_source_relationship_count=represented_source_count,
            unique_unordered_pair_count=unique_unordered_count,
            multi_pair_relationship_count=multi_pair_count,
            maximum_pairs_per_relationship=maximum_pair_count,
            row_count=row_count,
            logical_sha256=logical_digest.hexdigest(),
            jsonl_sha256=physical_digest.hexdigest(),
        )
        receipt_bytes = _canonical_json(receipt.model_dump(mode="json")).encode("ascii") + b"\n"
        with temporary_receipt.open("xb") as receipt_handle:
            receipt_handle.write(receipt_bytes)
            receipt_handle.flush()
            os.fsync(receipt_handle.fileno())
        temporary_output.replace(output_jsonl)
        try:
            temporary_receipt.replace(receipt_path)
        except OSError:
            output_jsonl.unlink(missing_ok=True)
            raise
    except KnownnessProjectionError:
        temporary_output.unlink(missing_ok=True)
        temporary_receipt.unlink(missing_ok=True)
        raise
    except (duckdb.Error, OSError, ValueError, TypeError) as exc:
        temporary_output.unlink(missing_ok=True)
        temporary_receipt.unlink(missing_ok=True)
        raise KnownnessProjectionError(f"could not project M6 OpenBible knownness: {exc}") from exc
    return authenticate_knownness_jsonl(
        output_jsonl,
        receipt_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def _load_receipt(receipt_path: Path) -> KnownnessProjectionReceipt:
    try:
        raw = receipt_path.read_bytes()
        receipt = KnownnessProjectionReceipt.model_validate_json(raw)
    except (OSError, ValidationError) as exc:
        raise KnownnessProjectionError(f"invalid knownness projection receipt: {exc}") from exc
    canonical = _canonical_json(receipt.model_dump(mode="json")).encode("ascii") + b"\n"
    if raw != canonical:
        raise KnownnessProjectionError("knownness projection receipt is not canonical")
    return receipt


def _validate_projected_lineage(
    relationship: KnownRelationship,
    *,
    source_manifest_sha256: str,
    line_number: int,
) -> None:
    if (
        relationship.source_name != _SOURCE_ID
        or relationship.source_relationship_id is None
        or relationship.source_manifest_sha256 != source_manifest_sha256
    ):
        raise KnownnessProjectionError(f"knownness source lineage mismatch at line {line_number}")
    try:
        provenance = cast(dict[str, object], json.loads(relationship.source_provenance_json))
    except json.JSONDecodeError as exc:  # model validation normally catches this first
        raise KnownnessProjectionError(
            f"knownness provenance is invalid at line {line_number}"
        ) from exc
    expected_keys = {
        "projection_schema",
        "source_id",
        "source_relationship_id",
        "source_version",
        "source_reference_a",
        "source_reference_b",
        "relationship_direction",
        "relationship_class",
        "mapping_ids_a",
        "mapping_ids_b",
        "mapping_statuses_a",
        "mapping_statuses_b",
        "source_manifest_sha256",
    }
    if set(provenance) != expected_keys:
        raise KnownnessProjectionError(
            f"knownness provenance inventory mismatch at line {line_number}"
        )
    if (
        provenance["projection_schema"] != _PROJECTION_SCHEMA
        or provenance["source_id"] != _SOURCE_ID
        or provenance["source_relationship_id"] != relationship.source_relationship_id
        or provenance["source_manifest_sha256"] != source_manifest_sha256
    ):
        raise KnownnessProjectionError(
            f"knownness provenance identity mismatch at line {line_number}"
        )

    def string_list(field: str) -> list[str]:
        value = provenance[field]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise KnownnessProjectionError(
                f"knownness provenance {field} is invalid at line {line_number}"
            )
        if value != sorted(set(value)):
            raise KnownnessProjectionError(
                f"knownness provenance {field} is not sorted/unique at line {line_number}"
            )
        return value

    mapping_ids_a = string_list("mapping_ids_a")
    mapping_ids_b = string_list("mapping_ids_b")
    statuses_a = string_list("mapping_statuses_a")
    statuses_b = string_list("mapping_statuses_b")
    if (
        not mapping_ids_a
        or not mapping_ids_b
        or not set((*statuses_a, *statuses_b)).issubset(_ELIGIBLE_MAPPING_STATUSES)
    ):
        raise KnownnessProjectionError(
            f"knownness mapping provenance is ineligible at line {line_number}"
        )
    if relationship.mapping_quality != _mapping_quality(statuses_a, statuses_b):
        raise KnownnessProjectionError(f"knownness mapping quality mismatch at line {line_number}")


def authenticate_knownness_jsonl(
    jsonl_path: Path,
    receipt_path: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> KnownnessProjectionReceipt:
    """Authenticate every canonical JSONL byte, row identity, order, and digest."""

    receipt = _load_receipt(receipt_path)
    if expected_manifest_sha256 is not None and (
        receipt.source_manifest_sha256 != expected_manifest_sha256
    ):
        raise KnownnessProjectionError("knownness receipt source manifest hash mismatch")
    if receipt.output_file_name != jsonl_path.name:
        raise KnownnessProjectionError("knownness receipt output filename mismatch")
    physical_digest = hashlib.sha256()
    logical_digest = _logical_hasher()
    count = 0
    prior_order: tuple[str, str, str, str] | None = None
    try:
        with jsonl_path.open("rb") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.endswith(b"\n"):
                    raise KnownnessProjectionError(
                        f"knownness JSONL line {line_number} lacks a final LF"
                    )
                try:
                    relationship = KnownRelationship.model_validate_json(line)
                except ValidationError as exc:
                    raise KnownnessProjectionError(
                        f"invalid knownness relationship at line {line_number}: {exc}"
                    ) from exc
                canonical = _canonical_relationship_bytes(relationship) + b"\n"
                if line != canonical:
                    raise KnownnessProjectionError(
                        f"knownness JSONL line {line_number} is not canonical"
                    )
                _validate_projected_lineage(
                    relationship,
                    source_manifest_sha256=receipt.source_manifest_sha256,
                    line_number=line_number,
                )
                source_relationship_id = cast(str, relationship.source_relationship_id)
                expected_id = _projected_relationship_id(
                    source_relationship_id,
                    relationship.source_passage_id,
                    relationship.target_passage_id,
                )
                if relationship.relationship_id != expected_id:
                    raise KnownnessProjectionError(
                        f"knownness projected identity mismatch at line {line_number}"
                    )
                order = (
                    source_relationship_id,
                    relationship.source_passage_id,
                    relationship.target_passage_id,
                    relationship.relationship_id,
                )
                if prior_order is not None and order <= prior_order:
                    raise KnownnessProjectionError(
                        f"knownness order/uniqueness violation at line {line_number}"
                    )
                prior_order = order
                physical_digest.update(line)
                _update_logical_digest(logical_digest, line[:-1])
                count += 1
    except OSError as exc:
        raise KnownnessProjectionError(f"could not read knownness JSONL: {exc}") from exc
    if count != receipt.row_count:
        raise KnownnessProjectionError(
            f"knownness row count mismatch: {count} != {receipt.row_count}"
        )
    if physical_digest.hexdigest() != receipt.jsonl_sha256:
        raise KnownnessProjectionError("knownness JSONL physical SHA-256 mismatch")
    if logical_digest.hexdigest() != receipt.logical_sha256:
        raise KnownnessProjectionError("knownness JSONL logical SHA-256 mismatch")
    return receipt


def iter_authenticated_knownness_jsonl(
    jsonl_path: Path,
    receipt_path: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> Iterator[KnownRelationship]:
    """Authenticate a complete artifact, then stream its typed relationships."""

    authenticate_knownness_jsonl(
        jsonl_path,
        receipt_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    with jsonl_path.open("rb") as handle:
        for line in handle:
            yield KnownRelationship.model_validate_json(line)
