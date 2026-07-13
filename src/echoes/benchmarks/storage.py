"""Atomic Parquet persistence and transactional DuckDB loading for benchmarks."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import duckdb
import polars as pl
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from echoes.benchmarks.models import (
    BENCHMARK_ARTIFACT_COLUMNS,
    BENCHMARK_ARTIFACT_NAMES,
    BENCHMARK_ARTIFACT_SCHEMAS,
    BenchmarkArtifactName,
)
from echoes.benchmarks.references import (
    GREEK_BOOKS,
    HEBREW_BOOKS,
    OPENBIBLE_BOOK_ALIASES,
)

BENCHMARK_SCHEMA_DIRECTORY: Final = "schema-v1"
HASH_MANIFEST_NAME: Final = "table-hashes.json"
DUCKDB_LOAD_MEMORY_LIMIT: Final = "2GiB"
DUCKDB_LOAD_THREADS: Final = 2
DUCKDB_LOAD_TEMP_SUFFIX: Final = ".benchmark-load.tmp"
DUCKDB_MERGE_MEMORY_LIMIT: Final = "768MiB"
DUCKDB_MERGE_THREADS: Final = 1
PARQUET_BATCH_SIZE: Final = 65_536
CONTENT_TABLES: Final = tuple(
    name for name in BENCHMARK_ARTIFACT_NAMES if name != "benchmark_metadata"
)
SORT_COLUMNS: Final[dict[BenchmarkArtifactName, tuple[str, ...]]] = {
    "benchmark_source_records": ("source_file", "source_line_number", "source_record_id"),
    "benchmark_relationships": ("relationship_id",),
    "benchmark_relationship_source_records": ("relationship_id", "source_record_id"),
    "benchmark_endpoints": ("relationship_id", "endpoint_side", "endpoint_id"),
    "benchmark_endpoint_mappings": (
        "endpoint_id",
        "target_analysis_profile",
        "mapping_id",
    ),
    "benchmark_leakage_groups": ("group_type", "leakage_group_id", "relationship_id"),
    "benchmark_split_assignments": ("split_strategy", "relationship_id"),
    "benchmark_presumed_negatives": (
        "negative_strategy",
        "partition",
        "passage_a_id",
        "passage_b_id",
    ),
    "benchmark_issues": ("severity", "code", "issue_id"),
    "benchmark_metadata": ("benchmark_run_id",),
}
UNIQUE_SORT_COLUMN: Final[dict[BenchmarkArtifactName, str]] = {
    "benchmark_source_records": "source_record_id",
    "benchmark_relationships": "relationship_id",
    "benchmark_relationship_source_records": "source_record_id",
    "benchmark_endpoints": "endpoint_id",
    "benchmark_endpoint_mappings": "mapping_id",
    "benchmark_leakage_groups": "relationship_id",
    "benchmark_split_assignments": "split_assignment_id",
    "benchmark_presumed_negatives": "contrastive_id",
    "benchmark_issues": "issue_id",
    "benchmark_metadata": "benchmark_run_id",
}


class BenchmarkStorageError(RuntimeError):
    """Raised when benchmark artifacts cannot be safely persisted or loaded."""


@dataclass(frozen=True, slots=True)
class BenchmarkStorageResult:
    """Promoted artifact paths, row counts, and deterministic hashes."""

    schema_root: Path
    table_paths: dict[str, Path]
    table_counts: dict[str, int]
    table_logical_hashes: dict[str, str]
    table_physical_hashes: dict[str, str]
    storage_footprint_bytes: int


class BenchmarkArtifactStager:
    """Incrementally write one benchmark table at a time under one atomic gate.

    The full benchmark contains several multi-million-row artifacts.  Keeping
    all ten Polars frames live until promotion exceeds the supported local
    memory envelope, so production builds write typed, sorted content tables
    into a private staging directory as soon as each table is complete.  The
    target is promoted only after metadata and the hash manifest are complete.
    """

    def __init__(self, output_root: Path, *, force: bool = False) -> None:
        self.target = output_root / BENCHMARK_SCHEMA_DIRECTORY
        self.force = force
        self.staging = self.target.with_name(f".{self.target.name}.staging-{uuid.uuid4().hex}")
        self.table_counts: dict[str, int] = {}
        self.logical_hashes: dict[str, str] = {}
        self.physical_hashes: dict[str, str] = {}
        self._entered = False
        self._finalized = False

    def __enter__(self) -> BenchmarkArtifactStager:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        if self.target.exists() and not self.force:
            raise BenchmarkStorageError(
                f"benchmark artifacts already exist at {self.target}; use --force"
            )
        free = shutil.disk_usage(self.target.parent).free
        if free < 64 * 1024 * 1024:
            raise BenchmarkStorageError(
                "insufficient disk space to start benchmark staging: "
                f"need at least {64 * 1024 * 1024}, have {free}"
            )
        self.staging.mkdir(parents=True, exist_ok=False)
        self._entered = True
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if self.staging.exists():
            shutil.rmtree(self.staging)

    def write_content(self, name: BenchmarkArtifactName, frame: pl.DataFrame) -> Path:
        """Write and hash one content table, returning its staged path."""

        return self.write_content_batches(name, (frame,))

    def write_content_batches(
        self,
        name: BenchmarkArtifactName,
        frames: Iterable[pl.DataFrame],
    ) -> Path:
        """Globally sort and persist bounded batches as one canonical table."""

        if not self._entered or self._finalized:
            raise BenchmarkStorageError("benchmark stager is not active")
        if name not in CONTENT_TABLES:
            raise BenchmarkStorageError(f"{name} is not a benchmark content table")
        if name in self.table_counts:
            raise BenchmarkStorageError(f"benchmark content table already staged: {name}")
        table_directory = self.staging / name
        workspace = self.staging / f".{name}.batches-{uuid.uuid4().hex}"
        workspace.mkdir(parents=False, exist_ok=False)
        batch_paths: list[Path] = []
        expected_rows = 0
        try:
            for batch_number, frame in enumerate(frames):
                _ensure_disk_space(self.target, {name: frame})
                typed = _typed_frame(name, frame)
                batch_path = workspace / f"batch-{batch_number:08d}.parquet"
                typed.write_parquet(
                    batch_path,
                    compression="zstd",
                    statistics=True,
                    row_group_size=PARQUET_BATCH_SIZE,
                )
                batch_paths.append(batch_path)
                expected_rows += typed.height
                del typed, frame

            if not batch_paths:
                empty = pl.DataFrame(schema=BENCHMARK_ARTIFACT_SCHEMAS[name])
                batch_path = workspace / "batch-00000000.parquet"
                empty.write_parquet(
                    batch_path,
                    compression="zstd",
                    statistics=True,
                    row_group_size=PARQUET_BATCH_SIZE,
                )
                batch_paths.append(batch_path)

            _ensure_merge_disk_space(workspace, batch_paths)
            path = table_directory / "part-00000.parquet"
            _merge_sorted_parquet_batches(name, batch_paths, path, workspace)
            observed_rows = _parquet_row_count(path)
            if observed_rows != expected_rows:
                raise BenchmarkStorageError(
                    f"{name} batch merge row count changed: "
                    f"expected={expected_rows}, observed={observed_rows}"
                )
            logical_hash = logical_parquet_hash(path, name)
            physical_hash = _sha256_file(path)
            self.table_counts[name] = observed_rows
            self.logical_hashes[name] = logical_hash
            self.physical_hashes[name] = physical_hash
            return path
        except Exception:
            if table_directory.exists():
                shutil.rmtree(table_directory)
            raise
        finally:
            if workspace.exists():
                shutil.rmtree(workspace)

    def finalize(self, metadata_frame: pl.DataFrame) -> BenchmarkStorageResult:
        """Write metadata and promote only after every content table exists."""

        if not self._entered or self._finalized:
            raise BenchmarkStorageError("benchmark stager is not active")
        missing = sorted(set(CONTENT_TABLES) - set(self.table_counts))
        if missing:
            raise BenchmarkStorageError(
                f"cannot finalize benchmark; content tables are missing: {missing}"
            )
        metadata = _typed_sorted_frame("benchmark_metadata", metadata_frame)
        if metadata.height != 1:
            raise BenchmarkStorageError("benchmark_metadata must contain exactly one row")
        content_bytes = sum(path.stat().st_size for path in self.staging.rglob("*.parquet"))
        metadata = metadata.with_columns(
            pl.lit(_canonical_json(self.logical_hashes)).alias("logical_table_hashes_json"),
            pl.lit(_canonical_json(self.physical_hashes)).alias("physical_table_hashes_json"),
            pl.lit(content_bytes).cast(pl.Int64).alias("storage_footprint_bytes"),
        )
        metadata_path = self.staging / "benchmark_metadata" / "part-00000.parquet"
        metadata_path.parent.mkdir(parents=True)
        metadata.write_parquet(metadata_path, compression="zstd", statistics=True)
        self.table_counts["benchmark_metadata"] = 1
        self.logical_hashes["benchmark_metadata"] = logical_parquet_hash(
            metadata_path,
            "benchmark_metadata",
        )
        self.physical_hashes["benchmark_metadata"] = _sha256_file(metadata_path)

        manifest = {
            "artifact_schema_version": 1,
            "table_counts": dict(sorted(self.table_counts.items())),
            "table_logical_sha256": dict(sorted(self.logical_hashes.items())),
            "table_physical_sha256": dict(sorted(self.physical_hashes.items())),
        }
        (self.staging / HASH_MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _promote(self.staging, self.target, force=self.force)
        self._finalized = True

        promoted_paths: dict[str, Path] = {
            name: self.target / name / "part-00000.parquet" for name in BENCHMARK_ARTIFACT_NAMES
        }
        footprint = sum(path.stat().st_size for path in promoted_paths.values())
        footprint += (self.target / HASH_MANIFEST_NAME).stat().st_size
        return BenchmarkStorageResult(
            schema_root=self.target,
            table_paths=promoted_paths,
            table_counts=dict(self.table_counts),
            table_logical_hashes=dict(self.logical_hashes),
            table_physical_hashes=dict(self.physical_hashes),
            storage_footprint_bytes=footprint,
        )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sort_columns(name: BenchmarkArtifactName) -> tuple[str, ...]:
    columns = SORT_COLUMNS[name]
    unique = UNIQUE_SORT_COLUMN[name]
    return columns if unique in columns else (*columns, unique)


def _typed_frame(name: BenchmarkArtifactName, frame: pl.DataFrame) -> pl.DataFrame:
    expected = BENCHMARK_ARTIFACT_COLUMNS[name]
    missing = sorted(set(expected) - set(frame.columns))
    extra = sorted(set(frame.columns) - set(expected))
    if missing or extra:
        raise BenchmarkStorageError(
            f"{name} columns do not match schema; missing={missing}, extra={extra}"
        )
    try:
        return frame.select(expected).cast(BENCHMARK_ARTIFACT_SCHEMAS[name], strict=True)
    except Exception as exc:  # Polars exposes several schema/compute subclasses
        raise BenchmarkStorageError(f"could not type {name}: {exc}") from exc


def _typed_sorted_frame(name: BenchmarkArtifactName, frame: pl.DataFrame) -> pl.DataFrame:
    try:
        return _typed_frame(name, frame).sort(_canonical_sort_columns(name))
    except BenchmarkStorageError:
        raise
    except Exception as exc:  # Polars exposes several schema/compute subclasses
        raise BenchmarkStorageError(f"could not sort {name}: {exc}") from exc


def _logical_projection(name: BenchmarkArtifactName, frame: pl.DataFrame) -> pl.DataFrame:
    if name != "benchmark_metadata":
        return frame
    excluded = {
        "physical_table_hashes_json",
        "processing_environment_json",
        "runtime_seconds",
        "storage_footprint_bytes",
    }
    return frame.select(column for column in frame.columns if column not in excluded)


def logical_parquet_hash(
    path: Path,
    name: BenchmarkArtifactName,
    *,
    batch_size: int = PARQUET_BATCH_SIZE,
) -> str:
    """Hash canonical Parquet incrementally under the existing Polars contract."""

    if batch_size < 1:
        raise BenchmarkStorageError("logical Parquet hash batch_size must be positive")
    try:
        parquet = pq.ParquetFile(path)
    except Exception as exc:
        raise BenchmarkStorageError(f"could not open benchmark Parquet {path}: {exc}") from exc
    expected = BENCHMARK_ARTIFACT_COLUMNS[name]
    observed = tuple(parquet.schema_arrow.names)
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    if missing or extra:
        raise BenchmarkStorageError(
            f"{name} Parquet columns do not match schema; missing={missing}, extra={extra}"
        )

    empty = pl.DataFrame(schema=BENCHMARK_ARTIFACT_SCHEMAS[name])
    logical_empty = _logical_projection(name, empty)
    digest = hashlib.sha256()
    digest.update("\0".join(logical_empty.columns).encode("utf-8"))
    digest.update(b"\0")
    digest.update("\0".join(str(dtype) for dtype in logical_empty.dtypes).encode("utf-8"))
    digest.update(b"\0")
    try:
        for record_batch in parquet.iter_batches(
            batch_size=batch_size,
            columns=list(expected),
            use_threads=False,
        ):
            converted = pl.from_arrow(record_batch)
            if not isinstance(converted, pl.DataFrame):  # pragma: no cover - record batches are 2D
                raise BenchmarkStorageError(f"could not read {name} as a tabular Parquet batch")
            logical = _logical_projection(name, _typed_frame(name, converted))
            row_hashes = logical.hash_rows(seed=0, seed_1=1, seed_2=2, seed_3=3)
            for value in row_hashes:
                digest.update(int(value).to_bytes(8, byteorder="little", signed=False))
    except BenchmarkStorageError:
        raise
    except Exception as exc:
        raise BenchmarkStorageError(f"could not hash benchmark Parquet {path}: {exc}") from exc
    return digest.hexdigest()


def _ensure_disk_space(
    output_root: Path, frames: dict[BenchmarkArtifactName, pl.DataFrame]
) -> None:
    output_root.parent.mkdir(parents=True, exist_ok=True)
    estimated = max(
        64 * 1024 * 1024,
        sum(max(frame.estimated_size(), 1) for frame in frames.values()) * 2,
    )
    free = shutil.disk_usage(output_root.parent).free
    if free < estimated:
        raise BenchmarkStorageError(
            f"insufficient disk space for benchmark staging: need {estimated}, have {free}"
        )


def _ensure_merge_disk_space(workspace: Path, batch_paths: list[Path]) -> None:
    staged_bytes = sum(path.stat().st_size for path in batch_paths)
    estimated = max(64 * 1024 * 1024, staged_bytes * 2)
    free = shutil.disk_usage(workspace).free
    if free < estimated:
        raise BenchmarkStorageError(
            f"insufficient disk space for benchmark batch merge: need {estimated}, have {free}"
        )


def _parquet_row_count(path: Path) -> int:
    try:
        metadata = pq.ParquetFile(path).metadata
    except Exception as exc:
        raise BenchmarkStorageError(f"could not inspect benchmark Parquet {path}: {exc}") from exc
    return int(metadata.num_rows)


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_string_list(values: Iterable[str]) -> str:
    rendered = ",".join("'" + value.replace("'", "''") + "'" for value in sorted(values))
    return f"({rendered})"


def _endpoint_source_corpus_sql(table_alias: str) -> str:
    """Classify a persisted endpoint from source identity, never mapping defaults."""

    hebrew_aliases = {
        alias for alias, canonical in OPENBIBLE_BOOK_ALIASES.items() if canonical in HEBREW_BOOKS
    }
    greek_aliases = {
        alias for alias, canonical in OPENBIBLE_BOOK_ALIASES.items() if canonical in GREEK_BOOKS
    }
    reference = f"{table_alias}.source_reference"
    start_alias = f"split_part({reference},'.',1)"
    end_alias = f"split_part(split_part({reference},'-',2),'.',1)"
    return (
        "CASE "
        f"WHEN {table_alias}.parsed_book IN {_sql_string_list(HEBREW_BOOKS)} "
        "THEN 'hebrew' "
        f"WHEN {table_alias}.parsed_book IN {_sql_string_list(GREEK_BOOKS)} "
        "THEN 'greek' "
        f"WHEN {table_alias}.parse_status='cross_book_range' "
        f"AND {start_alias} IN {_sql_string_list(hebrew_aliases)} "
        f"AND {end_alias} IN {_sql_string_list(hebrew_aliases)} THEN 'hebrew' "
        f"WHEN {table_alias}.parse_status='cross_book_range' "
        f"AND {start_alias} IN {_sql_string_list(greek_aliases)} "
        f"AND {end_alias} IN {_sql_string_list(greek_aliases)} THEN 'greek' "
        "ELSE NULL END"
    )


def _merge_sorted_parquet_batches(
    name: BenchmarkArtifactName,
    batch_paths: list[Path],
    output_path: Path,
    workspace: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=False)
    sources = ",".join(f"'{_quoted_path(path)}'" for path in batch_paths)
    selected = ",".join(_quoted_identifier(column) for column in BENCHMARK_ARTIFACT_COLUMNS[name])
    ordered = ",".join(
        f"{_quoted_identifier(column)} ASC NULLS FIRST" for column in _canonical_sort_columns(name)
    )
    spill_directory = workspace / "duckdb-spill"
    try:
        with duckdb.connect() as connection:
            connection.execute(f"SET memory_limit = '{DUCKDB_MERGE_MEMORY_LIMIT}'")
            connection.execute(f"SET threads = {DUCKDB_MERGE_THREADS}")
            connection.execute("SET preserve_insertion_order = false")
            connection.execute(f"SET temp_directory = '{_quoted_path(spill_directory)}'")
            connection.execute(
                f"COPY (SELECT {selected} FROM read_parquet([{sources}]) ORDER BY {ordered}) "
                f"TO '{_quoted_path(output_path)}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3, "
                f"ROW_GROUP_SIZE {PARQUET_BATCH_SIZE})"
            )
    except Exception as exc:
        raise BenchmarkStorageError(f"could not merge benchmark batches for {name}: {exc}") from exc


def _promote(staging: Path, target: Path, *, force: bool) -> None:
    if target.exists() and not force:
        raise BenchmarkStorageError(f"benchmark artifacts already exist at {target}; use --force")
    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
    try:
        if target.exists():
            target.rename(backup)
        staging.rename(target)
    except OSError as exc:
        if not target.exists() and backup.exists():
            backup.rename(target)
        raise BenchmarkStorageError(
            f"could not atomically promote benchmark artifacts: {exc}"
        ) from exc
    finally:
        if backup.exists():
            shutil.rmtree(backup)


def write_benchmark_artifacts(
    frames: dict[BenchmarkArtifactName, pl.DataFrame],
    output_root: Path,
    *,
    force: bool = False,
) -> BenchmarkStorageResult:
    """Write all ten artifacts through a fresh staging directory."""

    expected = set(BENCHMARK_ARTIFACT_NAMES)
    if set(frames) != expected:
        raise BenchmarkStorageError(
            "benchmark artifact set mismatch: "
            f"expected={sorted(expected)}, observed={sorted(frames)}"
        )
    with BenchmarkArtifactStager(output_root, force=force) as stager:
        for name in CONTENT_TABLES:
            stager.write_content(name, frames[name])
        return stager.finalize(frames["benchmark_metadata"])


def read_benchmark_artifacts(schema_root: Path) -> dict[BenchmarkArtifactName, pl.DataFrame]:
    """Read every governed artifact through its explicit schema."""

    result: dict[BenchmarkArtifactName, pl.DataFrame] = {}
    for name in BENCHMARK_ARTIFACT_NAMES:
        path = schema_root / name / "part-00000.parquet"
        if not path.is_file():
            raise BenchmarkStorageError(f"missing benchmark artifact {path}")
        result[name] = _typed_sorted_frame(name, pl.read_parquet(path))
    return result


REQUIRED_VIEWS: Final = (
    "tier3_openbible_relationships",
    "mapped_openbible_relationships",
    "unmapped_openbible_relationships",
    "cross_testament_relationships",
    "within_old_testament_relationships",
    "within_new_testament_relationships",
    "openbible_reverse_pairs",
    "openbible_duplicate_pairs",
    "benchmark_weak_supervision_splits",
    "benchmark_presumed_negative_pairs",
    "benchmark_mapping_quality",
    "benchmark_reference_risks",
)


def _quoted_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _benchmark_duckdb_temp_directory(database_path: Path) -> Path:
    """Return an ignored spill directory on the database's filesystem."""

    return database_path.with_name(f".{database_path.name}{DUCKDB_LOAD_TEMP_SUFFIX}")


def _configure_benchmark_duckdb_connection(
    connection: duckdb.DuckDBPyConnection, database_path: Path
) -> Path:
    """Bound loader resources before any benchmark table or index is built."""

    temp_directory = _benchmark_duckdb_temp_directory(database_path)
    connection.execute(f"SET memory_limit = '{DUCKDB_LOAD_MEMORY_LIMIT}'")
    connection.execute(f"SET threads = {DUCKDB_LOAD_THREADS}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(f"SET temp_directory = '{_quoted_path(temp_directory)}'")
    return temp_directory


def load_benchmark_duckdb(storage: BenchmarkStorageResult, database_path: Path) -> None:
    """Transactionally replace benchmark-only tables/views without touching passage data."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with duckdb.connect(str(database_path)) as connection:
            _configure_benchmark_duckdb_connection(connection, database_path)
            connection.execute("BEGIN TRANSACTION")
            try:
                for view in REQUIRED_VIEWS:
                    connection.execute(f'DROP VIEW IF EXISTS "{view}"')
                connection.execute("DROP TABLE IF EXISTS benchmark_mapping_target_passages")
                for name in BENCHMARK_ARTIFACT_NAMES:
                    path = _quoted_path(storage.table_paths[name])
                    connection.execute(
                        f'CREATE OR REPLACE TABLE "{name}" AS '
                        f"SELECT * FROM read_parquet('{path}')"
                    )
                connection.execute(
                    """
                    CREATE TABLE benchmark_mapping_target_passages AS
                    SELECT m.mapping_id, m.endpoint_id,
                           CAST(j.key AS BIGINT) + 1 AS position,
                           trim(CAST(j.value AS VARCHAR), '"') AS target_passage_id
                    FROM benchmark_endpoint_mappings m,
                         json_each(m.target_passage_ids_json) j
                    """
                )
                index_specs = {
                    "idx_benchmark_relationship": (
                        "benchmark_relationships",
                        "relationship_id",
                    ),
                    "idx_benchmark_source_record": (
                        "benchmark_source_records",
                        "source_record_id",
                    ),
                    "idx_benchmark_directed_pair": (
                        "benchmark_relationships",
                        "canonical_directed_pair_id",
                    ),
                    "idx_benchmark_unordered_pair": (
                        "benchmark_relationships",
                        "canonical_undirected_pair_id",
                    ),
                    "idx_benchmark_tier": ("benchmark_relationships", "tier"),
                    "idx_benchmark_endpoint_reference": (
                        "benchmark_endpoints",
                        "source_reference",
                    ),
                    "idx_benchmark_mapping_status": (
                        "benchmark_endpoint_mappings",
                        "mapping_status",
                    ),
                    "idx_benchmark_mapping_target": (
                        "benchmark_mapping_target_passages",
                        "target_passage_id",
                    ),
                    "idx_benchmark_leakage": (
                        "benchmark_leakage_groups",
                        "leakage_group_id",
                    ),
                    "idx_benchmark_split": (
                        "benchmark_split_assignments",
                        "split_strategy, partition",
                    ),
                }
                for index, (table, columns) in index_specs.items():
                    connection.execute(f'CREATE INDEX "{index}" ON "{table}" ({columns})')

                connection.execute(
                    "CREATE VIEW tier3_openbible_relationships AS "
                    "SELECT * FROM benchmark_relationships WHERE tier=3 "
                    "AND source_id='openbible-cross-references'"
                )
                connection.execute(
                    "CREATE VIEW benchmark_mapping_quality AS "
                    "SELECT mapping_status, mapping_confidence, target_corpus, "
                    "count(*) AS mapping_count FROM benchmark_endpoint_mappings "
                    "GROUP BY ALL"
                )
                connection.execute(
                    "CREATE VIEW mapped_openbible_relationships AS "
                    "SELECT DISTINCT r.* FROM tier3_openbible_relationships r "
                    "JOIN benchmark_endpoints e USING (relationship_id) "
                    "JOIN benchmark_endpoint_mappings m USING (endpoint_id) "
                    "WHERE m.target_analysis_profile='edition_complete' AND "
                    "m.mapping_status IN ('mapped_verified','mapped_provisional','mapped_partial')"
                )
                connection.execute(
                    "CREATE VIEW unmapped_openbible_relationships AS "
                    "SELECT r.* FROM tier3_openbible_relationships r WHERE NOT EXISTS "
                    "(SELECT 1 FROM benchmark_endpoints e JOIN benchmark_endpoint_mappings m "
                    "USING (endpoint_id) WHERE e.relationship_id=r.relationship_id "
                    "AND m.target_analysis_profile='edition_complete' AND "
                    "m.mapping_status IN ('mapped_verified','mapped_provisional','mapped_partial'))"
                )
                endpoint_corpora = (
                    "WITH c AS (SELECT e.relationship_id,e.endpoint_side,"
                    f"{_endpoint_source_corpus_sql('e')} AS source_corpus "
                    "FROM benchmark_endpoints e) "
                )
                connection.execute(
                    "CREATE VIEW cross_testament_relationships AS "
                    + endpoint_corpora
                    + "SELECT DISTINCT r.* FROM benchmark_relationships r "
                    "JOIN c a ON r.relationship_id=a.relationship_id AND a.endpoint_side='a' "
                    "JOIN c b ON r.relationship_id=b.relationship_id AND b.endpoint_side='b' "
                    "WHERE a.source_corpus<>b.source_corpus"
                )
                connection.execute(
                    "CREATE VIEW within_old_testament_relationships AS "
                    + endpoint_corpora
                    + "SELECT DISTINCT r.* FROM benchmark_relationships r "
                    "JOIN c a ON r.relationship_id=a.relationship_id AND a.endpoint_side='a' "
                    "JOIN c b ON r.relationship_id=b.relationship_id AND b.endpoint_side='b' "
                    "WHERE a.source_corpus='hebrew' AND b.source_corpus='hebrew'"
                )
                connection.execute(
                    "CREATE VIEW within_new_testament_relationships AS "
                    + endpoint_corpora
                    + "SELECT DISTINCT r.* FROM benchmark_relationships r "
                    "JOIN c a ON r.relationship_id=a.relationship_id AND a.endpoint_side='a' "
                    "JOIN c b ON r.relationship_id=b.relationship_id AND b.endpoint_side='b' "
                    "WHERE a.source_corpus='greek' AND b.source_corpus='greek'"
                )
                connection.execute(
                    "CREATE VIEW openbible_reverse_pairs AS SELECT * FROM "
                    "tier3_openbible_relationships WHERE canonical_undirected_pair_id IN "
                    "(SELECT canonical_undirected_pair_id FROM tier3_openbible_relationships "
                    "GROUP BY 1 HAVING count(*)>1)"
                )
                connection.execute(
                    "CREATE VIEW openbible_duplicate_pairs AS SELECT * FROM "
                    "tier3_openbible_relationships WHERE source_record_count>1"
                )
                connection.execute(
                    "CREATE VIEW benchmark_weak_supervision_splits AS "
                    "SELECT s.*,r.tier,r.source_id FROM benchmark_split_assignments s "
                    "JOIN benchmark_relationships r USING(relationship_id) WHERE r.tier=3"
                )
                connection.execute(
                    "CREATE VIEW benchmark_presumed_negative_pairs AS "
                    "SELECT * FROM benchmark_presumed_negatives WHERE presumed_negative"
                )
                connection.execute(
                    "CREATE VIEW benchmark_reference_risks AS "
                    "SELECT e.relationship_id,e.source_reference,m.* FROM benchmark_endpoints e "
                    "JOIN benchmark_endpoint_mappings m USING(endpoint_id) WHERE "
                    "m.mapping_status NOT IN ('mapped_verified','mapped_provisional') "
                    "OR m.reference_gap OR m.disputed_passage_flag"
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
    except Exception as exc:
        raise BenchmarkStorageError(
            f"could not load benchmark DuckDB {database_path}: {exc}"
        ) from exc


def table_row_counts(database_path: Path) -> dict[str, int]:
    """Return the ten benchmark table counts for CLI summaries and validation."""

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            counts: dict[str, int] = {}
            for name in BENCHMARK_ARTIFACT_NAMES:
                row = connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()
                if row is None:  # pragma: no cover - aggregate always returns one row
                    raise BenchmarkStorageError(f"could not count benchmark table {name}")
                counts[name] = int(row[0])
            return counts
    except Exception as exc:
        raise BenchmarkStorageError(f"could not inspect benchmark DuckDB: {exc}") from exc
