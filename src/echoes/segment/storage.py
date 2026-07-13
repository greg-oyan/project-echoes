"""Atomic partitioned Parquet storage and transactional DuckDB exposure.

Segmentation artifacts are generated data and remain outside Git.  This module
stores one book-sized frame per Hive-style leaf while retaining the explicit
dimension columns in every Parquet file.  Source corpus tables are never copied,
replaced, or dropped by the passage loader.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import duckdb
import polars as pl

from echoes.corpus.storage import logical_frame_hash
from echoes.manifest import sha256_file
from echoes.segment.models import (
    PASSAGE_ADJACENCY_COLUMNS,
    PASSAGE_ADJACENCY_POLARS_SCHEMA,
    PASSAGE_COLUMNS,
    PASSAGE_MEMBERSHIP_COLUMNS,
    PASSAGE_MEMBERSHIP_POLARS_SCHEMA,
    PASSAGE_POLARS_SCHEMA,
    PASSAGE_SCHEMA_VERSION,
    SEGMENTATION_EXCLUSION_COLUMNS,
    SEGMENTATION_EXCLUSION_POLARS_SCHEMA,
    SEGMENTATION_ISSUE_COLUMNS,
    SEGMENTATION_ISSUE_POLARS_SCHEMA,
    SEGMENTATION_METADATA_COLUMNS,
    SEGMENTATION_METADATA_POLARS_SCHEMA,
    PassageMembershipRow,
    PassageRow,
)

ArtifactName = Literal[
    "passages",
    "passage_membership",
    "passage_adjacency",
    "segmentation_exclusions",
    "segmentation_issues",
    "segmentation_metadata",
]

ARTIFACT_NAMES: tuple[ArtifactName, ...] = (
    "passages",
    "passage_membership",
    "passage_adjacency",
    "segmentation_exclusions",
    "segmentation_issues",
    "segmentation_metadata",
)
TABLE_HASH_FILE = "table-hashes.json"
MINIMUM_DISK_PREFLIGHT_BYTES = 64 * 1024 * 1024

ARTIFACT_SCHEMAS: Mapping[ArtifactName, pl.Schema] = {
    "passages": PASSAGE_POLARS_SCHEMA,
    "passage_membership": PASSAGE_MEMBERSHIP_POLARS_SCHEMA,
    "passage_adjacency": PASSAGE_ADJACENCY_POLARS_SCHEMA,
    "segmentation_exclusions": SEGMENTATION_EXCLUSION_POLARS_SCHEMA,
    "segmentation_issues": SEGMENTATION_ISSUE_POLARS_SCHEMA,
    "segmentation_metadata": SEGMENTATION_METADATA_POLARS_SCHEMA,
}
ARTIFACT_COLUMNS: Mapping[ArtifactName, tuple[str, ...]] = {
    "passages": PASSAGE_COLUMNS,
    "passage_membership": PASSAGE_MEMBERSHIP_COLUMNS,
    "passage_adjacency": PASSAGE_ADJACENCY_COLUMNS,
    "segmentation_exclusions": SEGMENTATION_EXCLUSION_COLUMNS,
    "segmentation_issues": SEGMENTATION_ISSUE_COLUMNS,
    "segmentation_metadata": SEGMENTATION_METADATA_COLUMNS,
}
ARTIFACT_SORT_COLUMNS: Mapping[ArtifactName, tuple[str, ...]] = {
    "passages": ("book_order", "start_stream_position_in_corpus", "passage_id"),
    "passage_membership": ("passage_id", "position_in_passage"),
    "passage_adjacency": ("from_passage_id", "to_passage_id"),
    "segmentation_exclusions": (
        "stream_position_in_corpus",
        "reason_code",
        "exclusion_id",
    ),
    "segmentation_issues": ("severity", "code", "issue_id"),
    "segmentation_metadata": ("segmentation_run_id",),
}

# Execution telemetry is recorded but cannot participate in reproducibility
# hashes because it legitimately varies between identical analytical runs.
METADATA_NONDETERMINISTIC_COLUMNS: frozenset[str] = frozenset(
    {"runtime_seconds", "approximate_peak_memory_bytes", "output_size_bytes"}
)

_SAFE_PARTITION_VALUE = re.compile(r"^[A-Za-z0-9_-]+$")


class PassageStorageError(RuntimeError):
    """Raised when passage artifacts cannot be stored or exposed safely."""


@dataclass(frozen=True, slots=True)
class ArtifactPartition:
    """One schema-correct book-sized artifact leaf."""

    table: ArtifactName
    frame: pl.DataFrame
    corpus: str | None = None
    analysis_profile: str | None = None
    analysis_reading: str | None = None
    granularity: str | None = None
    book: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessedPassages:
    """Stable references and hashes for one promoted schema-v1 output."""

    output_dir: Path
    schema_version: int
    file_hashes: dict[str, str]
    leaf_logical_hashes: dict[str, str]
    table_physical_hashes: dict[str, str]
    table_logical_hashes: dict[str, str]
    table_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class ArtifactContentSummary:
    """Deterministic non-metadata results available before finalization."""

    table_physical_hashes: dict[str, str]
    table_logical_hashes: dict[str, str]
    table_counts: dict[str, int]
    output_size_bytes: int


def _safe_output_path(output_dir: Path) -> Path:
    resolved = output_dir.resolve(strict=False)
    expected_name = f"schema-v{PASSAGE_SCHEMA_VERSION}"
    if resolved.name != expected_name:
        raise PassageStorageError(f"passage output directory must end in {expected_name}")
    if output_dir.is_symlink():
        raise PassageStorageError("passage output directory may not be a symbolic link")
    if resolved == resolved.parent:
        raise PassageStorageError("passage output directory may not be a filesystem root")
    return resolved


def _assert_confined_sibling(path: Path, output_dir: Path) -> None:
    parent = output_dir.parent.resolve(strict=False)
    candidate = path.resolve(strict=False)
    if candidate.parent != parent:
        raise PassageStorageError(f"temporary path escapes output parent: {candidate}")
    allowed_prefixes = (f".{output_dir.name}.writing-", f".{output_dir.name}.backup-")
    if not candidate.name.startswith(allowed_prefixes):
        raise PassageStorageError(f"unexpected temporary passage path: {candidate}")


def _safe_rmtree(path: Path, output_dir: Path) -> None:
    if not path.exists():
        return
    _assert_confined_sibling(path, output_dir)
    shutil.rmtree(path)


def _rename_path(source: Path, target: Path) -> None:
    """Indirection retained for deterministic failure-recovery tests."""

    source.replace(target)


def _promote_staging(staging: Path, output_dir: Path, backup: Path) -> None:
    """Promote a complete staging tree and restore the prior tree on failure."""

    had_output = output_dir.exists()
    if had_output:
        _rename_path(output_dir, backup)
    try:
        _rename_path(staging, output_dir)
    except Exception:
        if had_output and backup.exists() and not output_dir.exists():
            _rename_path(backup, output_dir)
        raise
    if backup.exists():
        _safe_rmtree(backup, output_dir)


def _safe_partition_value(label: str, value: str | None) -> str:
    if value is None:
        return "_all"
    if not _SAFE_PARTITION_VALUE.fullmatch(value):
        raise PassageStorageError(f"unsafe {label} partition value: {value!r}")
    return value


def _leaf_relative_path(partition: ArtifactPartition) -> Path:
    if partition.table == "segmentation_metadata":
        if any(
            value is not None
            for value in (
                partition.corpus,
                partition.analysis_profile,
                partition.analysis_reading,
                partition.granularity,
                partition.book,
            )
        ):
            raise PassageStorageError("segmentation metadata must use the global partition")
        return Path(partition.table) / "_global" / "part-00000.parquet"
    dimensions = (
        ("corpus", partition.corpus),
        ("analysis_profile", partition.analysis_profile),
        ("analysis_reading", partition.analysis_reading),
        ("granularity", partition.granularity),
        ("book", partition.book),
    )
    path = Path(partition.table)
    for label, value in dimensions:
        path /= f"{label}={_safe_partition_value(label, value)}"
    return path / "part-00000.parquet"


def _validate_partition_dimensions(partition: ArtifactPartition, frame: pl.DataFrame) -> None:
    dimensions = {
        "corpus": partition.corpus,
        "analysis_profile": partition.analysis_profile,
        "analysis_reading": partition.analysis_reading,
        "granularity": partition.granularity,
        "book": partition.book,
    }
    if frame.is_empty():
        return
    for column, expected in dimensions.items():
        if expected is None or column not in frame.columns:
            continue
        actual = frame.get_column(column).drop_nulls().unique().to_list()
        if actual != [expected]:
            raise PassageStorageError(
                f"{partition.table} partition {column}={expected!r} contains {actual!r}"
            )


def _prepare_frame(partition: ArtifactPartition) -> pl.DataFrame:
    expected_columns = ARTIFACT_COLUMNS[partition.table]
    if tuple(partition.frame.columns) != expected_columns:
        raise PassageStorageError(
            f"{partition.table} columns differ from the governed schema; "
            f"expected={expected_columns}, actual={tuple(partition.frame.columns)}"
        )
    try:
        frame = partition.frame.cast(ARTIFACT_SCHEMAS[partition.table], strict=True)
    except (pl.exceptions.PolarsError, TypeError) as exc:
        raise PassageStorageError(
            f"{partition.table} does not match its storage schema: {exc}"
        ) from exc
    _validate_partition_dimensions(partition, frame)
    sort_columns = list(ARTIFACT_SORT_COLUMNS[partition.table])
    return frame.sort(sort_columns) if frame.height else frame


def _logical_projection(table: ArtifactName, frame: pl.DataFrame) -> pl.DataFrame:
    if table != "segmentation_metadata":
        return frame
    columns = [
        column for column in frame.columns if column not in METADATA_NONDETERMINISTIC_COLUMNS
    ]
    return frame.select(columns)


def _aggregate_leaf_hashes(leaves: Mapping[str, Mapping[str, object]], hash_key: str) -> str:
    canonical = [
        {
            "path": path,
            "row_count": cast(int, values["row_count"]),
            hash_key: str(values[hash_key]),
        }
        for path, values in sorted(leaves.items())
    ]
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _disk_preflight(parent: Path, required_free_bytes: int) -> None:
    if required_free_bytes < 0:
        raise PassageStorageError("required_free_bytes cannot be negative")
    parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(parent).free
    if free < required_free_bytes:
        raise PassageStorageError(
            f"insufficient disk space for segmentation output: "
            f"required={required_free_bytes}, available={free}"
        )


class PassageArtifactWriter:
    """Incremental atomic writer that never retains completed partition frames."""

    def __init__(
        self,
        *,
        output_dir: Path,
        force: bool = False,
        estimated_output_bytes: int | None = None,
        required_free_bytes: int | None = None,
    ) -> None:
        self.output_dir = _safe_output_path(output_dir)
        if self.output_dir.exists() and not force:
            raise PassageStorageError(
                f"refusing to overwrite passage artifacts at {self.output_dir}; pass --force"
            )
        if estimated_output_bytes is not None and estimated_output_bytes < 0:
            raise PassageStorageError("estimated_output_bytes cannot be negative")
        required = (
            max(MINIMUM_DISK_PREFLIGHT_BYTES, (estimated_output_bytes or 0) * 2)
            if required_free_bytes is None
            else required_free_bytes
        )
        _disk_preflight(self.output_dir.parent, required)
        self._staging = self.output_dir.parent / f".{self.output_dir.name}.writing-{uuid4().hex}"
        self._backup = self.output_dir.parent / f".{self.output_dir.name}.backup-{uuid4().hex}"
        _assert_confined_sibling(self._staging, self.output_dir)
        _assert_confined_sibling(self._backup, self.output_dir)
        self._staging.mkdir()
        self._leaves_by_table: dict[ArtifactName, dict[str, dict[str, object]]] = {
            table: {} for table in ARTIFACT_NAMES
        }
        self._table_counts: dict[str, int] = {table: 0 for table in ARTIFACT_NAMES}
        self._finalized = False

    def __enter__(self) -> PassageArtifactWriter:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._finalized:
            self.abort()

    def _ensure_open(self) -> None:
        if self._finalized or not self._staging.exists():
            raise PassageStorageError("passage artifact writer is already closed")

    def _write_leaf(self, partition: ArtifactPartition) -> None:
        self._ensure_open()
        relative_path = _leaf_relative_path(partition)
        relative_key = relative_path.as_posix()
        table_leaves = self._leaves_by_table[partition.table]
        if relative_key in table_leaves:
            raise PassageStorageError(f"duplicate artifact partition: {relative_key}")
        frame = _prepare_frame(partition)
        target = self._staging / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(
            target,
            compression="zstd",
            compression_level=6,
            statistics=True,
        )
        logical_frame = _logical_projection(partition.table, frame)
        logical_sort = [
            column
            for column in ARTIFACT_SORT_COLUMNS[partition.table]
            if column in logical_frame.columns
        ]
        table_leaves[relative_key] = {
            "row_count": frame.height,
            "parquet_sha256": sha256_file(target),
            "logical_sha256": logical_frame_hash(logical_frame, sort_by=logical_sort),
        }
        self._table_counts[partition.table] += frame.height

    def write_partition(self, partition: ArtifactPartition) -> None:
        """Persist and reduce one non-metadata leaf before requesting another."""

        if partition.table == "segmentation_metadata":
            raise PassageStorageError("segmentation metadata must be supplied to finalize")
        self._write_leaf(partition)

    def _table_hashes(self, tables: Iterable[ArtifactName], hash_key: str) -> dict[str, str]:
        return {
            str(table): _aggregate_leaf_hashes(self._leaves_by_table[table], hash_key)
            for table in tables
        }

    def content_summary(self) -> ArtifactContentSummary:
        """Return deterministic results used to construct the final metadata row."""

        self._ensure_open()
        content_tables = tuple(
            table for table in ARTIFACT_NAMES if table != "segmentation_metadata"
        )
        missing = [table for table in content_tables if not self._leaves_by_table[table]]
        if missing:
            raise PassageStorageError(f"missing required passage artifacts: {missing}")
        return ArtifactContentSummary(
            table_physical_hashes=self._table_hashes(content_tables, "parquet_sha256"),
            table_logical_hashes=self._table_hashes(content_tables, "logical_sha256"),
            table_counts={table: self._table_counts[table] for table in content_tables},
            output_size_bytes=sum(
                (self._staging / path).stat().st_size
                for table in content_tables
                for path in self._leaves_by_table[table]
            ),
        )

    def finalize(self, metadata: ArtifactPartition) -> ProcessedPassages:
        """Write the one-row metadata leaf, manifest, and atomically promote output."""

        self._ensure_open()
        if metadata.table != "segmentation_metadata" or metadata.frame.height != 1:
            raise PassageStorageError("finalize requires one one-row segmentation_metadata leaf")
        self.content_summary()
        try:
            self._write_leaf(metadata)
            table_logical_hashes = self._table_hashes(ARTIFACT_NAMES, "logical_sha256")
            table_physical_hashes = self._table_hashes(ARTIFACT_NAMES, "parquet_sha256")
            file_hashes = {
                path: str(values["parquet_sha256"])
                for table in ARTIFACT_NAMES
                for path, values in sorted(self._leaves_by_table[table].items())
            }
            leaf_logical_hashes = {
                path: str(values["logical_sha256"])
                for table in ARTIFACT_NAMES
                for path, values in sorted(self._leaves_by_table[table].items())
            }
            hash_document = {
                "schema_version": PASSAGE_SCHEMA_VERSION,
                "metadata_nondeterministic_columns": sorted(METADATA_NONDETERMINISTIC_COLUMNS),
                "table_counts": self._table_counts,
                "table_logical_sha256": table_logical_hashes,
                "table_physical_sha256": table_physical_hashes,
                "parquet_sha256": file_hashes,
                "leaf_logical_sha256": leaf_logical_hashes,
                "artifacts": self._leaves_by_table,
            }
            (self._staging / TABLE_HASH_FILE).write_text(
                json.dumps(hash_document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _promote_staging(self._staging, self.output_dir, self._backup)
        except Exception:
            self.abort()
            raise
        self._finalized = True
        return ProcessedPassages(
            output_dir=self.output_dir,
            schema_version=PASSAGE_SCHEMA_VERSION,
            file_hashes=file_hashes,
            leaf_logical_hashes=leaf_logical_hashes,
            table_physical_hashes=table_physical_hashes,
            table_logical_hashes=table_logical_hashes,
            table_counts=dict(self._table_counts),
        )

    def abort(self) -> None:
        """Remove confined staging state and restore any displaced prior output."""

        if self._staging.exists():
            _safe_rmtree(self._staging, self.output_dir)
        if self._backup.exists() and not self.output_dir.exists():
            _rename_path(self._backup, self.output_dir)


def write_passage_artifacts(
    partitions: Iterable[ArtifactPartition],
    *,
    output_dir: Path,
    force: bool = False,
    estimated_output_bytes: int | None = None,
    required_free_bytes: int | None = None,
) -> ProcessedPassages:
    """Consume partitions incrementally; retain only the one-row metadata leaf."""

    metadata: ArtifactPartition | None = None
    with PassageArtifactWriter(
        output_dir=output_dir,
        force=force,
        estimated_output_bytes=estimated_output_bytes,
        required_free_bytes=required_free_bytes,
    ) as writer:
        for partition in partitions:
            if partition.table == "segmentation_metadata":
                if metadata is not None:
                    raise PassageStorageError("segmentation_metadata may occur only once")
                metadata = partition
            else:
                writer.write_partition(partition)
        if metadata is None:
            raise PassageStorageError("missing required segmentation_metadata artifact")
        return writer.finalize(metadata)


def read_hash_manifest(output_dir: Path) -> dict[str, object]:
    """Read and minimally validate the storage hash document."""

    path = _safe_output_path(output_dir) / TABLE_HASH_FILE
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PassageStorageError(f"could not read passage hash manifest {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != PASSAGE_SCHEMA_VERSION:
        raise PassageStorageError(f"invalid passage hash manifest: {path}")
    return cast(dict[str, object], document)


def read_artifact_frame(output_dir: Path, table: ArtifactName) -> pl.DataFrame:
    """Read one complete logical artifact in its governed stable order."""

    root = _safe_output_path(output_dir) / table
    paths = sorted(root.rglob("*.parquet"))
    if not paths:
        raise PassageStorageError(f"no Parquet leaves exist for {table} in {root}")
    try:
        frame = pl.read_parquet(paths, rechunk=True).select(ARTIFACT_COLUMNS[table])
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise PassageStorageError(f"could not read {table}: {exc}") from exc
    sort_columns = list(ARTIFACT_SORT_COLUMNS[table])
    return frame.sort(sort_columns) if frame.height else frame.cast(ARTIFACT_SCHEMAS[table])


def load_passage_duckdb(processed: ProcessedPassages, database_path: Path) -> None:
    """Transactionally expose segmentation Parquet as external DuckDB views.

    The membership artifact is expected to contain tens of millions of rows.
    Materializing it again inside DuckDB, especially with secondary indexes,
    would duplicate several gigabytes of generated data. External views keep
    Parquet statistics and predicate pushdown available. DuckDB cannot index
    views, so indexes are intentionally omitted; a future materialized cache
    must be defined as a separate derived artifact.
    """

    database_path.parent.mkdir(parents=True, exist_ok=True)
    convenience_views = (
        "hebrew_qere_passages",
        "hebrew_ketiv_passages",
        "greek_edition_complete_passages",
        "greek_critical_core_passages",
        "verse_passages",
        "window_passages",
        "passage_token_sequences",
        "passage_uncertainty_summary",
    )
    try:
        with duckdb.connect(str(database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                existing_tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT table_name FROM duckdb_tables() "
                        "WHERE database_name = current_database() AND schema_name = 'main'"
                    ).fetchall()
                }
                existing_views = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT view_name FROM duckdb_views() "
                        "WHERE database_name = current_database() AND schema_name = 'main'"
                    ).fetchall()
                }
                # Drop only known dependent and artifact relations. Source
                # corpus tables and unrelated user objects are never touched.
                for view in convenience_views:
                    if view in existing_views:
                        connection.execute(f"DROP VIEW {view}")
                for table in ARTIFACT_NAMES:
                    if table in existing_views:
                        connection.execute(f"DROP VIEW {table}")
                    elif table in existing_tables:
                        # Migration path from the initial materializing loader.
                        connection.execute(f"DROP TABLE {table}")
                    glob = (processed.output_dir / table / "**" / "*.parquet").as_posix()
                    escaped = glob.replace("'", "''")
                    connection.execute(
                        f"CREATE VIEW {table} AS "
                        f"SELECT * FROM read_parquet('{escaped}', "
                        "union_by_name=true, hive_partitioning=false)"
                    )
                connection.execute(
                    "CREATE OR REPLACE VIEW hebrew_qere_passages AS "
                    "SELECT * FROM passages WHERE corpus = 'hebrew' "
                    "AND analysis_reading = 'qere'"
                )
                connection.execute(
                    "CREATE OR REPLACE VIEW hebrew_ketiv_passages AS "
                    "SELECT * FROM passages WHERE corpus = 'hebrew' "
                    "AND analysis_reading = 'ketiv'"
                )
                connection.execute(
                    "CREATE OR REPLACE VIEW greek_edition_complete_passages AS "
                    "SELECT * FROM passages WHERE corpus = 'greek' "
                    "AND analysis_profile = 'edition_complete'"
                )
                connection.execute(
                    "CREATE OR REPLACE VIEW greek_critical_core_passages AS "
                    "SELECT * FROM passages WHERE corpus = 'greek' "
                    "AND analysis_profile = 'critical_core'"
                )
                connection.execute(
                    "CREATE OR REPLACE VIEW verse_passages AS "
                    "SELECT * FROM passages WHERE granularity = 'verse'"
                )
                connection.execute(
                    "CREATE OR REPLACE VIEW window_passages AS "
                    "SELECT * FROM passages WHERE granularity IN ('two_verse', 'five_verse')"
                )
                connection.execute(
                    "CREATE OR REPLACE VIEW passage_token_sequences AS "
                    "SELECT passage_id, list(token_id ORDER BY position_in_passage) AS token_ids "
                    "FROM passage_membership GROUP BY passage_id"
                )
                connection.execute(
                    "CREATE OR REPLACE VIEW passage_uncertainty_summary AS "
                    "SELECT corpus, analysis_profile, analysis_reading, granularity, "
                    "count(*) AS passage_count, "
                    "count(*) FILTER (WHERE ketiv_structural_uncertainty) "
                    "AS ketiv_uncertain_count, "
                    "sum(sensitivity_exclusion_count) AS sensitivity_exclusion_count "
                    "FROM passages GROUP BY corpus, analysis_profile, "
                    "analysis_reading, granularity"
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
    except (duckdb.Error, OSError) as exc:
        raise PassageStorageError(f"could not load passage DuckDB {database_path}: {exc}") from exc


def read_passage(database_path: Path, passage_id: str) -> PassageRow | None:
    """Read one typed passage row from an exposed DuckDB database."""

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            cursor = connection.execute("SELECT * FROM passages WHERE passage_id = ?", [passage_id])
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [str(description[0]) for description in cursor.description]
    except (duckdb.Error, OSError) as exc:
        raise PassageStorageError(f"could not read passage {passage_id}: {exc}") from exc
    return PassageRow.model_validate(dict(zip(columns, row, strict=True)))


def read_passage_membership(database_path: Path, passage_id: str) -> list[PassageMembershipRow]:
    """Read authoritative membership in exact passage order."""

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            cursor = connection.execute(
                "SELECT * FROM passage_membership WHERE passage_id = ? "
                "ORDER BY position_in_passage",
                [passage_id],
            )
            rows = cursor.fetchall()
            columns = [str(description[0]) for description in cursor.description]
    except (duckdb.Error, OSError) as exc:
        raise PassageStorageError(
            f"could not read membership for passage {passage_id}: {exc}"
        ) from exc
    return [
        PassageMembershipRow.model_validate(dict(zip(columns, row, strict=True))) for row in rows
    ]
