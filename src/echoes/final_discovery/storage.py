"""Atomic text-safe storage primitives for checkpointed final-discovery rows."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError


class FinalDiscoveryStorageError(ValueError):
    """Raised when a typed final-discovery artifact is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class StreamArtifactReceipt:
    """Count and physical identity collected in one streaming pass."""

    row_count: int
    size_bytes: int
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_jsonl_file(path: Path) -> StreamArtifactReceipt:
    """Count LF-terminated rows while hashing one JSONL file without parsing it."""

    digest = hashlib.sha256()
    row_count = 0
    size_bytes = 0
    final_byte = b""
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                row_count += chunk.count(b"\n")
                size_bytes += len(chunk)
                final_byte = chunk[-1:]
    except OSError as exc:
        raise FinalDiscoveryStorageError(f"could not inspect artifact {path}: {exc}") from exc
    if size_bytes and final_byte != b"\n":
        raise FinalDiscoveryStorageError(f"JSONL artifact lacks a final LF: {path}")
    return StreamArtifactReceipt(
        row_count=row_count,
        size_bytes=size_bytes,
        sha256=digest.hexdigest(),
    )


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
        raise FinalDiscoveryStorageError(
            f"could not serialize canonical {type(row).__name__}: {exc}"
        ) from exc


def write_json_atomic_new(path: Path, value: Any) -> StreamArtifactReceipt:
    """Write one canonical JSON value plus LF without replacing an artifact."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    try:
        payload = (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FinalDiscoveryStorageError(f"could not serialize canonical JSON: {exc}") from exc
    if path.exists():
        raise FinalDiscoveryStorageError(f"refusing to replace existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _publish_temporary_new(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return StreamArtifactReceipt(
        row_count=1,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _publish_temporary_new(temporary: Path, path: Path) -> None:
    """Publish a same-directory temporary file without a replacement race."""

    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise FinalDiscoveryStorageError(f"refusing to replace existing artifact: {path}") from exc
    except OSError as exc:
        raise FinalDiscoveryStorageError(f"could not publish artifact {path}: {exc}") from exc
    else:
        temporary.unlink()


def write_jsonl_stream_atomic(
    path: Path,
    rows: Iterable[BaseModel],
    *,
    order_key: Callable[[BaseModel], tuple[str, ...]] | None,
    require_strict_order: bool = True,
) -> StreamArtifactReceipt:
    """Stream canonical rows to a new file and publish it without replacement.

    When an ordering key is supplied, the writer proves that its input is
    deterministic rather than silently sorting and materializing it.  A failed
    iterator or serialization leaves no published target.
    """

    if path.exists():
        raise FinalDiscoveryStorageError(f"refusing to replace existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    digest = hashlib.sha256()
    row_count = 0
    size_bytes = 0
    prior_key: tuple[str, ...] | None = None
    try:
        with temporary.open("xb") as handle:
            for row in rows:
                if order_key is not None:
                    key = order_key(row)
                    if prior_key is not None and (
                        key < prior_key or (require_strict_order and key == prior_key)
                    ):
                        qualifier = "duplicate or " if require_strict_order else ""
                        raise FinalDiscoveryStorageError(
                            f"streamed rows are {qualifier}out of order at {key!r}"
                        )
                    prior_key = key
                payload = _canonical_model_bytes(row) + b"\n"
                handle.write(payload)
                digest.update(payload)
                row_count += 1
                size_bytes += len(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _publish_temporary_new(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return StreamArtifactReceipt(
        row_count=row_count,
        size_bytes=size_bytes,
        sha256=digest.hexdigest(),
    )


def write_jsonl_atomic(
    path: Path,
    rows: Iterable[BaseModel],
    *,
    sort_key: str | None,
) -> tuple[int, str]:
    """Create one canonical JSONL artifact without replacing prior output.

    A named key gives stable lexical ordering. ``None`` preserves an already
    deterministically ordered scientific ledger (for example descending final
    ensemble score with the pair ID as its registered tie break).
    """

    if path.exists():
        raise FinalDiscoveryStorageError(f"refusing to replace existing artifact: {path}")
    materialized = list(rows)
    if sort_key is not None:
        try:
            materialized.sort(key=lambda row: str(getattr(row, sort_key)))
        except AttributeError as exc:
            raise FinalDiscoveryStorageError(f"rows do not expose sort key {sort_key}") from exc
    receipt = write_jsonl_stream_atomic(
        path,
        materialized,
        order_key=None,
        require_strict_order=False,
    )
    return receipt.row_count, receipt.sha256


def iter_jsonl[ModelT: BaseModel](path: Path, model: type[ModelT]) -> Iterator[ModelT]:
    """Stream and validate one canonical JSON object per line."""

    try:
        with path.open(encoding="ascii", newline="") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.endswith("\n"):
                    raise FinalDiscoveryStorageError(
                        f"JSONL line {line_number} lacks a final LF: {path}"
                    )
                try:
                    parsed = json.loads(line)
                    yield model.model_validate(parsed)
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise FinalDiscoveryStorageError(
                        f"invalid {model.__name__} at {path}:{line_number}: {exc}"
                    ) from exc
    except (OSError, UnicodeError) as exc:
        raise FinalDiscoveryStorageError(f"could not read artifact {path}: {exc}") from exc


def iter_canonical_jsonl[ModelT: BaseModel](path: Path, model: type[ModelT]) -> Iterator[ModelT]:
    """Stream typed rows while requiring the repository's exact canonical bytes."""

    try:
        with path.open("rb") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.endswith(b"\n"):
                    raise FinalDiscoveryStorageError(
                        f"JSONL line {line_number} lacks a final LF: {path}"
                    )
                payload = line[:-1]
                try:
                    parsed = json.loads(payload.decode("ascii"))
                    row = model.model_validate(parsed)
                except (UnicodeError, json.JSONDecodeError, ValidationError) as exc:
                    raise FinalDiscoveryStorageError(
                        f"invalid {model.__name__} at {path}:{line_number}: {exc}"
                    ) from exc
                if _canonical_model_bytes(row) != payload:
                    raise FinalDiscoveryStorageError(
                        f"noncanonical {model.__name__} bytes at {path}:{line_number}"
                    )
                yield row
    except OSError as exc:
        raise FinalDiscoveryStorageError(f"could not read artifact {path}: {exc}") from exc


def merge_sorted_jsonl[ModelT: BaseModel](
    paths: Sequence[Path],
    model: type[ModelT],
    *,
    key: Callable[[ModelT], tuple[str, ...]],
) -> Iterator[ModelT]:
    """K-way merge canonical nondecreasing JSONL streams in bounded memory."""

    iterators = [iter(iter_canonical_jsonl(path, model)) for path in paths]
    prior_by_source: list[tuple[str, ...] | None] = [None] * len(iterators)
    heap: list[tuple[tuple[str, ...], int, int, ModelT]] = []
    sequence_by_source = [0] * len(iterators)

    def push(source_index: int) -> None:
        try:
            row = next(iterators[source_index])
        except StopIteration:
            return
        row_key = key(row)
        prior = prior_by_source[source_index]
        if prior is not None and row_key < prior:
            raise FinalDiscoveryStorageError(
                f"canonical stream is out of order at {paths[source_index]}: {row_key!r}"
            )
        prior_by_source[source_index] = row_key
        sequence = sequence_by_source[source_index]
        sequence_by_source[source_index] += 1
        heapq.heappush(heap, (row_key, source_index, sequence, row))

    for source_index in range(len(iterators)):
        push(source_index)
    while heap:
        _, source_index, _, row = heapq.heappop(heap)
        yield row
        push(source_index)


def read_jsonl[ModelT: BaseModel](path: Path, model: type[ModelT]) -> tuple[ModelT, ...]:
    return tuple(iter_jsonl(path, model))
