"""Compact byte-offset lookup for production ``EvidenceRow`` ledgers.

The canonical evidence JSONL remains the only payload store.  The SQLite
artifact contains one row per candidate pair plus a typed build receipt; a
temporary uniqueness database used during construction is never published.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import BinaryIO, Literal, Self, overload

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes.final_discovery.features import (
    candidate_pair_id as canonical_candidate_pair_id,
)
from echoes.final_discovery.features import evidence_id as canonical_evidence_id
from echoes.final_discovery.models import EvidenceRow, FinalCandidate

_INDEX_SCHEMA_VERSION = 1
_COMMIT_INTERVAL = 50_000


class EvidenceIndexError(ValueError):
    """Raised when an evidence ledger or its compact offset index is invalid."""


class EvidenceOffsetIndexReceipt(BaseModel):
    """Authenticated source identity and resource contract for one offset index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = "final-discovery-v1"
    resource_method: Literal["single_scan_canonical_jsonl_sqlite_pair_byte_offsets"] = (
        "single_scan_canonical_jsonl_sqlite_pair_byte_offsets"
    )
    lookup_method: Literal["sqlite_pair_seek_without_payload_copy"] = (
        "sqlite_pair_seek_without_payload_copy"
    )
    source_ordering: Literal["candidate_pair_id,detector_id"] = "candidate_pair_id,detector_id"
    source_file_name: str = Field(min_length=1)
    source_size_bytes: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_row_count: int = Field(ge=1)
    candidate_pair_count: int = Field(ge=1)
    maximum_rows_per_pair: int = Field(ge=1)
    expected_maximum_rows_per_pair: int = Field(ge=1)
    payload_bytes_copied_into_index: Literal[0] = 0

    @model_validator(mode="after")
    def population_is_consistent(self) -> Self:
        if self.candidate_pair_count > self.evidence_row_count:
            raise ValueError("candidate-pair count exceeds evidence-row count")
        if self.maximum_rows_per_pair > self.evidence_row_count:
            raise ValueError("maximum pair group exceeds the evidence population")
        if self.maximum_rows_per_pair != self.expected_maximum_rows_per_pair:
            raise ValueError("observed maximum pair group differs from its authenticated value")
        return self


def _canonical_model_bytes(row: BaseModel) -> bytes:
    try:
        return json.dumps(
            row.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise EvidenceIndexError(f"could not serialize canonical evidence: {exc}") from exc


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _parse_canonical_evidence(payload: bytes, *, location: str) -> EvidenceRow:
    try:
        parsed = json.loads(payload.decode("ascii"))
        row = EvidenceRow.model_validate(parsed)
    except (UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise EvidenceIndexError(f"invalid EvidenceRow at {location}: {exc}") from exc
    if _canonical_model_bytes(row) != payload:
        raise EvidenceIndexError(f"noncanonical EvidenceRow bytes at {location}")
    return row


def _validate_pair_identity(row: EvidenceRow, *, location: str) -> None:
    expected_pair_id = canonical_candidate_pair_id(row.passage_a_id, row.passage_b_id)
    if row.candidate_pair_id != expected_pair_id:
        raise EvidenceIndexError(
            f"candidate_pair_id identity mismatch at {location}: {row.candidate_pair_id}"
        )


def _validate_evidence_identity(row: EvidenceRow, *, location: str) -> None:
    expected_evidence_id = canonical_evidence_id(
        row.candidate_pair_id,
        row.detector_id,
        row.source_artifact_sha256,
    )
    if row.evidence_id != expected_evidence_id:
        raise EvidenceIndexError(f"evidence_id identity mismatch at {location}: {row.evidence_id}")


def _validate_row_identity(row: EvidenceRow, *, location: str) -> None:
    _validate_pair_identity(row, location=location)
    _validate_evidence_identity(row, location=location)


def _configure_index(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-32768")
    connection.execute(f"PRAGMA user_version={_INDEX_SCHEMA_VERSION}")
    connection.execute(
        """
        CREATE TABLE pair_offsets (
            candidate_pair_id TEXT PRIMARY KEY,
            start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
            byte_length INTEGER NOT NULL CHECK (byte_length > 0),
            row_count INTEGER NOT NULL CHECK (row_count > 0)
        ) WITHOUT ROWID
        """
    )
    connection.execute(
        """
        CREATE TABLE index_metadata (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            receipt_json TEXT NOT NULL
        )
        """
    )


def _configure_uniqueness_store(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-32768")
    connection.execute("CREATE TABLE evidence_ids (evidence_id TEXT PRIMARY KEY) WITHOUT ROWID")


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    for suffix in ("-journal", "-shm", "-wal"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def _publish_new_file(temporary: Path, target: Path) -> None:
    try:
        os.link(temporary, target)
    except FileExistsError as exc:
        raise EvidenceIndexError(f"refusing to replace existing index: {target}") from exc
    except OSError as exc:
        raise EvidenceIndexError(f"could not atomically publish evidence index: {exc}") from exc
    else:
        temporary.unlink()


def _insert_pair(
    connection: sqlite3.Connection,
    *,
    pair_id: str,
    start_offset: int,
    end_offset: int,
    row_count: int,
) -> None:
    try:
        connection.execute(
            "INSERT INTO pair_offsets VALUES (?,?,?,?)",
            (pair_id, start_offset, end_offset - start_offset, row_count),
        )
    except sqlite3.IntegrityError as exc:
        raise EvidenceIndexError(f"duplicate or noncontiguous candidate pair: {pair_id}") from exc


def build_evidence_offset_index(
    source_path: Path,
    index_path: Path,
    *,
    expected_source_sha256: str,
    expected_evidence_row_count: int,
    expected_maximum_rows_per_pair: int,
) -> EvidenceOffsetIndexReceipt:
    """Validate one canonical evidence ledger and atomically publish pair offsets."""

    if not source_path.is_file():
        raise EvidenceIndexError(f"evidence source is not a file: {source_path}")
    if index_path.exists() or index_path.is_symlink():
        raise EvidenceIndexError(f"refusing to replace existing index: {index_path}")
    if source_path.resolve() == index_path.resolve():
        raise EvidenceIndexError("evidence source and index paths must differ")
    if len(expected_source_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_source_sha256
    ):
        raise ValueError("expected_source_sha256 must be lowercase SHA-256")
    if expected_evidence_row_count < 1:
        raise ValueError("expected_evidence_row_count must be positive")
    if expected_maximum_rows_per_pair < 1:
        raise ValueError("expected_maximum_rows_per_pair must be positive")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    temporary_index = index_path.with_name(f".{index_path.name}.{nonce}.tmp")
    uniqueness_path = index_path.with_name(f".{index_path.name}.{nonce}.identities.tmp")
    index_connection: sqlite3.Connection | None = None
    uniqueness_connection: sqlite3.Connection | None = None
    try:
        index_connection = sqlite3.connect(temporary_index)
        uniqueness_connection = sqlite3.connect(uniqueness_path)
        _configure_index(index_connection)
        _configure_uniqueness_store(uniqueness_connection)

        digest = hashlib.sha256()
        evidence_count = 0
        pair_count = 0
        maximum_rows = 0
        prior_key: tuple[str, str] | None = None
        current_pair: str | None = None
        current_pair_start = 0
        current_pair_rows = 0
        source_size = 0

        with source_path.open("rb") as source:
            initial_stat = os.fstat(source.fileno())
            line_number = 0
            while True:
                line_start = source.tell()
                line = source.readline()
                if not line:
                    break
                line_number += 1
                if not line.endswith(b"\n"):
                    raise EvidenceIndexError(
                        f"EvidenceRow line lacks a final LF at {source_path}:{line_number}"
                    )
                digest.update(line)
                source_size += len(line)
                row = _parse_canonical_evidence(
                    line[:-1],
                    location=f"{source_path}:{line_number}",
                )
                _validate_pair_identity(row, location=f"{source_path}:{line_number}")
                key = (row.candidate_pair_id, row.detector_id)
                if prior_key is not None and key <= prior_key:
                    raise EvidenceIndexError(
                        "evidence ledger must be strictly ordered by candidate_pair_id,detector_id"
                    )
                prior_key = key
                try:
                    uniqueness_connection.execute(
                        "INSERT INTO evidence_ids VALUES (?)",
                        (row.evidence_id,),
                    )
                except sqlite3.IntegrityError as exc:
                    raise EvidenceIndexError(f"duplicate evidence_id: {row.evidence_id}") from exc
                _validate_evidence_identity(row, location=f"{source_path}:{line_number}")

                if current_pair is None:
                    current_pair = row.candidate_pair_id
                    current_pair_start = line_start
                elif row.candidate_pair_id != current_pair:
                    _insert_pair(
                        index_connection,
                        pair_id=current_pair,
                        start_offset=current_pair_start,
                        end_offset=line_start,
                        row_count=current_pair_rows,
                    )
                    pair_count += 1
                    maximum_rows = max(maximum_rows, current_pair_rows)
                    current_pair = row.candidate_pair_id
                    current_pair_start = line_start
                    current_pair_rows = 0
                current_pair_rows += 1
                evidence_count += 1
                if current_pair_rows > expected_maximum_rows_per_pair:
                    raise EvidenceIndexError("evidence pair exceeds expected maximum rows per pair")
                if evidence_count > expected_evidence_row_count:
                    raise EvidenceIndexError("evidence source exceeds expected row count")
                if evidence_count % _COMMIT_INTERVAL == 0:
                    index_connection.commit()
                    uniqueness_connection.commit()

            final_stat = os.fstat(source.fileno())
            if (
                initial_stat.st_size != final_stat.st_size
                or initial_stat.st_mtime_ns != final_stat.st_mtime_ns
                or source_size != final_stat.st_size
            ):
                raise EvidenceIndexError("evidence source changed during index construction")

        if current_pair is not None:
            _insert_pair(
                index_connection,
                pair_id=current_pair,
                start_offset=current_pair_start,
                end_offset=source_size,
                row_count=current_pair_rows,
            )
            pair_count += 1
            maximum_rows = max(maximum_rows, current_pair_rows)
        if evidence_count != expected_evidence_row_count:
            raise EvidenceIndexError(
                f"evidence source has {evidence_count} rows; expected {expected_evidence_row_count}"
            )
        observed_sha256 = digest.hexdigest()
        if observed_sha256 != expected_source_sha256:
            raise EvidenceIndexError("evidence source SHA-256 disagrees with expected identity")
        if maximum_rows != expected_maximum_rows_per_pair:
            raise EvidenceIndexError(
                f"maximum rows per pair is {maximum_rows}; expected "
                f"{expected_maximum_rows_per_pair}"
            )

        receipt = EvidenceOffsetIndexReceipt(
            source_file_name=source_path.name,
            source_size_bytes=source_size,
            source_sha256=observed_sha256,
            evidence_row_count=evidence_count,
            candidate_pair_count=pair_count,
            maximum_rows_per_pair=maximum_rows,
            expected_maximum_rows_per_pair=expected_maximum_rows_per_pair,
        )
        index_connection.execute(
            "INSERT INTO index_metadata VALUES (1,?)",
            (_canonical_json(receipt.model_dump(mode="json")),),
        )
        index_connection.commit()
        uniqueness_connection.commit()
        index_connection.close()
        index_connection = None
        uniqueness_connection.close()
        uniqueness_connection = None
        _remove_sqlite_files(uniqueness_path)
        with temporary_index.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        persisted = read_evidence_offset_index_receipt(temporary_index)
        if persisted != receipt:
            raise EvidenceIndexError("persisted evidence-index receipt changed")
        _publish_new_file(temporary_index, index_path)
        return receipt
    except BaseException:
        if index_connection is not None:
            index_connection.close()
        if uniqueness_connection is not None:
            uniqueness_connection.close()
        _remove_sqlite_files(temporary_index)
        _remove_sqlite_files(uniqueness_path)
        raise


def _open_readonly_index(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise EvidenceIndexError(f"evidence index is not a file: {path}")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != _INDEX_SCHEMA_VERSION:
            raise EvidenceIndexError(f"unsupported evidence-index schema version: {version}")
        return connection
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise EvidenceIndexError(f"could not open evidence index: {exc}") from exc
    except EvidenceIndexError:
        if connection is not None:
            connection.close()
        raise


def _read_receipt(connection: sqlite3.Connection) -> EvidenceOffsetIndexReceipt:
    try:
        rows = connection.execute(
            "SELECT receipt_json FROM index_metadata WHERE singleton=1"
        ).fetchall()
    except sqlite3.Error as exc:
        raise EvidenceIndexError(f"evidence index metadata is invalid: {exc}") from exc
    if len(rows) != 1 or not isinstance(rows[0][0], str):
        raise EvidenceIndexError("evidence index must contain exactly one typed receipt")
    raw_receipt = rows[0][0]
    try:
        receipt = EvidenceOffsetIndexReceipt.model_validate_json(raw_receipt)
    except ValidationError as exc:
        raise EvidenceIndexError(f"evidence index receipt is invalid: {exc}") from exc
    if raw_receipt != _canonical_json(receipt.model_dump(mode="json")):
        raise EvidenceIndexError("evidence index receipt is not canonical JSON")
    return receipt


def read_evidence_offset_index_receipt(index_path: Path) -> EvidenceOffsetIndexReceipt:
    """Read and validate the typed receipt embedded in an offset index."""

    connection = _open_readonly_index(index_path)
    try:
        return _read_receipt(connection)
    finally:
        connection.close()


def _sha256_handle(handle: BinaryIO) -> tuple[int, str]:
    handle.seek(0)
    digest = hashlib.sha256()
    size = 0
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
        size += len(block)
    handle.seek(0)
    return size, digest.hexdigest()


class EvidenceOffsetLookup:
    """Context-managed, one-pair-at-a-time lookup over an authenticated ledger."""

    def __init__(
        self,
        index_path: Path,
        source_path: Path,
        *,
        verify_source_sha256: bool = True,
    ) -> None:
        self._index_path = index_path
        self._source_path = source_path
        self._verify_source_sha256 = verify_source_sha256
        self._connection: sqlite3.Connection | None = None
        self._source: BinaryIO | None = None
        self._receipt: EvidenceOffsetIndexReceipt | None = None

    @property
    def receipt(self) -> EvidenceOffsetIndexReceipt:
        if self._receipt is None:
            raise EvidenceIndexError("evidence lookup is not open")
        return self._receipt

    def __enter__(self) -> Self:
        if self._connection is not None or self._source is not None:
            raise EvidenceIndexError("evidence lookup is already open")
        connection: sqlite3.Connection | None = None
        source: BinaryIO | None = None
        try:
            connection = _open_readonly_index(self._index_path)
            receipt = _read_receipt(connection)
            try:
                pair_count = int(
                    connection.execute("SELECT count(*) FROM pair_offsets").fetchone()[0]
                )
            except sqlite3.Error as exc:
                raise EvidenceIndexError(f"evidence offset table is invalid: {exc}") from exc
            if pair_count != receipt.candidate_pair_count:
                raise EvidenceIndexError("evidence-index pair count disagrees with its receipt")
            try:
                source = self._source_path.open("rb")
            except OSError as exc:
                raise EvidenceIndexError(f"could not open evidence source: {exc}") from exc
            if self._verify_source_sha256:
                source_size, source_sha256 = _sha256_handle(source)
                if (
                    source_size != receipt.source_size_bytes
                    or source_sha256 != receipt.source_sha256
                ):
                    raise EvidenceIndexError(
                        "evidence source identity disagrees with the offset-index receipt"
                    )
            elif os.fstat(source.fileno()).st_size != receipt.source_size_bytes:
                raise EvidenceIndexError(
                    "evidence source size disagrees with the offset-index receipt"
                )
            self._connection = connection
            self._source = source
            self._receipt = receipt
            return self
        except BaseException:
            if source is not None:
                source.close()
            if connection is not None:
                connection.close()
            raise

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        if self._source is not None:
            self._source.close()
        if self._connection is not None:
            self._connection.close()
        self._source = None
        self._connection = None
        self._receipt = None

    @overload
    def __call__(self, candidate: FinalCandidate) -> tuple[EvidenceRow, ...]: ...

    @overload
    def __call__(self, candidate: str) -> tuple[EvidenceRow, ...]: ...

    def __call__(self, candidate: FinalCandidate | str) -> tuple[EvidenceRow, ...]:
        if self._connection is None or self._source is None or self._receipt is None:
            raise EvidenceIndexError("evidence lookup is not open")
        pair_id = (
            candidate.candidate_pair_id if isinstance(candidate, FinalCandidate) else candidate
        )
        try:
            indexed = self._connection.execute(
                """
                SELECT start_offset,byte_length,row_count
                FROM pair_offsets WHERE candidate_pair_id=?
                """,
                (pair_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise EvidenceIndexError(f"could not query evidence index: {exc}") from exc
        if indexed is None:
            raise EvidenceIndexError(f"candidate pair is absent from evidence index: {pair_id}")
        start_offset, byte_length, expected_count = (int(value) for value in indexed)
        if (
            start_offset < 0
            or byte_length < 1
            or expected_count < 1
            or expected_count > self._receipt.maximum_rows_per_pair
            or start_offset + byte_length > self._receipt.source_size_bytes
        ):
            raise EvidenceIndexError(f"invalid byte-offset record for candidate pair: {pair_id}")

        self._source.seek(start_offset)
        end_offset = start_offset + byte_length
        rows: list[EvidenceRow] = []
        prior_detector: str | None = None
        while self._source.tell() < end_offset:
            line_start = self._source.tell()
            line = self._source.readline()
            if not line.endswith(b"\n") or self._source.tell() > end_offset:
                raise EvidenceIndexError(f"indexed byte range is not line-aligned: {pair_id}")
            row = _parse_canonical_evidence(
                line[:-1],
                location=f"{self._source_path}@{line_start}",
            )
            _validate_row_identity(row, location=f"{self._source_path}@{line_start}")
            if row.candidate_pair_id != pair_id:
                raise EvidenceIndexError(f"indexed evidence belongs to another pair: {pair_id}")
            if prior_detector is not None and row.detector_id <= prior_detector:
                raise EvidenceIndexError(f"indexed detector order is invalid: {pair_id}")
            prior_detector = row.detector_id
            rows.append(row)
            if len(rows) > expected_count:
                raise EvidenceIndexError(f"indexed row count is stale: {pair_id}")
        if self._source.tell() != end_offset or len(rows) != expected_count:
            raise EvidenceIndexError(f"indexed row count or byte range is stale: {pair_id}")

        result = tuple(rows)
        if isinstance(candidate, FinalCandidate):
            expected_pair_id = canonical_candidate_pair_id(
                candidate.passage_a_id,
                candidate.passage_b_id,
            )
            if pair_id != expected_pair_id:
                raise EvidenceIndexError(f"FinalCandidate has a stale candidate_pair_id: {pair_id}")
            if any(
                (row.passage_a_id, row.passage_b_id)
                != (candidate.passage_a_id, candidate.passage_b_id)
                for row in result
            ):
                raise EvidenceIndexError(
                    f"evidence passage IDs disagree with FinalCandidate: {pair_id}"
                )
            observed_ids = tuple(sorted(row.evidence_id for row in result))
            if candidate.evidence_ids != observed_ids:
                raise EvidenceIndexError(
                    f"evidence IDs disagree with FinalCandidate exactly: {pair_id}"
                )
        return result


__all__ = [
    "EvidenceIndexError",
    "EvidenceOffsetIndexReceipt",
    "EvidenceOffsetLookup",
    "build_evidence_offset_index",
    "read_evidence_offset_index_receipt",
]
