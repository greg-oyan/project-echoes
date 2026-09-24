"""Reuse an explicitly pinned, successfully tested canonical M7 projection."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from echoes.final_discovery.config import DetectorRegistration
from echoes.final_discovery.features import candidate_pair_id
from echoes.final_discovery.inputs import ObjectStoreError, ObjectStoreIdentity, inventory_directory
from echoes.final_discovery.m7_adapter import (
    M7AdapterError,
    M7AuthenticationReport,
    authenticate_m7_input,
    iter_m7_raw_evidence,
)
from echoes.final_discovery.stages import StageCompletionManifest
from echoes.final_discovery.storage import sha256_file, write_json_atomic_new

_CANONICAL_PAIR_COUNT = 1_248_779
_PROJECTION_NAME = "m7-lexical-projection.parquet"
_REVIEWED_COMMIT = "e265b59cc26bf33daf1eec832d54b71f29557c19"
# Git blob identities read from the reviewed commit. Pinning the relevant source
# files also works in shallow checkouts; unrelated recovery/launcher edits do not
# invalidate the demonstrated adapter result.
_REVIEWED_SOURCE_BLOBS = {
    "src/echoes/final_discovery/m7_adapter.py": "4fcbadc9a841ec49cf472f8b4e11e476ab8cd752",
    "src/echoes/final_discovery/features.py": "ec46e8ae5a44cd0b471110ca1ae618513c91655b",
    "src/echoes/final_discovery/models.py": "e0f3fc1be9cfde87a78d8af9fae68ffe3b73ff98",
    "src/echoes/lexical/models.py": "a48488deb9ff703cac407d30931df2b3e800f094",
}


class ProjectionCacheError(M7AdapterError):
    """A requested cache cannot prove the exact previously tested projection."""


class _OrderingReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    complete_source_inventory_authenticated: Literal[True]
    completed_at: datetime
    completion_path: str
    completion_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    downstream_order_condition_passed: Literal[True]
    duckdb_memory_limit_bytes: Literal[1073741824]
    duckdb_threads: Literal[1]
    first_final_id: str = Field(pattern=r"^FDPAIR~[a-f0-9]{64}$")
    full_stream_reached_eof: Literal[True]
    globally_unique_final_ids: Literal[True]
    last_final_id: str = Field(pattern=r"^FDPAIR~[a-f0-9]{64}$")
    output_path: str
    output_row_count: int = Field(ge=1)
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result: Literal["pass"]
    source_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_object_count: int = Field(ge=1)
    source_root: str
    started_at: datetime
    stream_row_count: int = Field(ge=1)
    strict_final_identity_order: Literal[True]
    table_counts: dict[str, int]
    test_directory: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectionCacheError(message)


def _safe_path(path: Path, *, directory: bool) -> Path:
    """Reject symlinks/junctions in every component, including parent paths."""

    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        _require(
            not component.is_symlink() and not component.is_junction(),
            f"projection cache path contains a link: {component}",
        )
    _require(absolute.resolve(strict=True) == absolute, f"noncanonical cache path: {path}")
    _require(
        absolute.is_dir() if directory else absolute.is_file(),
        f"projection cache path has the wrong type: {path}",
    )
    return absolute


def _new_output(path: Path) -> Path:
    parent = _safe_path(path.parent, directory=True)
    output = parent / path.name
    _require(not os.path.lexists(output), f"refusing to replace cache output: {output}")
    return output


def _authenticate_adapter(expected_code_commit: str) -> dict[str, str]:
    _require(expected_code_commit == _REVIEWED_COMMIT, "unreviewed projection adapter code pin")
    repository = Path(__file__).resolve().parents[3]
    for relative, expected in _REVIEWED_SOURCE_BLOBS.items():
        path = _safe_path(repository / relative, directory=False)
        # These Python source files use Git's text normalization. CRLF and LF
        # worktrees execute identical Python and identify the same committed blob.
        payload = path.read_bytes().replace(b"\r\n", b"\n")
        observed = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        _require(
            observed == expected,
            f"projection adapter source changed since reviewed test: {relative}",
        )
    return dict(_REVIEWED_SOURCE_BLOBS)


def _authenticate_source(
    receipt: _OrderingReceipt, source_root: Path, expected_manifest_sha256: str
) -> tuple[M7AuthenticationReport, str]:
    completion_path = _safe_path(Path(receipt.completion_path), directory=False)
    completion_bytes = completion_path.read_bytes()
    _require(
        hashlib.sha256(completion_bytes).hexdigest() == receipt.completion_sha256,
        "tested projection source completion SHA-256 differs",
    )
    completion = StageCompletionManifest.model_validate_json(completion_bytes)
    _require(
        completion.stage_number == 1
        and completion.stage_id == "authenticate_materialize_inputs"
        and completion_path.name == "completion.json"
        and completion_path.parent.name == "01-authenticate_materialize_inputs"
        and completion_path.parent.parent.name == "stages",
        "tested projection receipt does not bind Stage 1",
    )
    recorded_root = _safe_path(Path(receipt.source_root), directory=True)
    _require(
        recorded_root
        == completion_path.parent.joinpath(*PurePosixPath(completion.artifacts_root).parts, "m7"),
        "tested projection source root differs from its completed Stage 1",
    )
    recorded_manifest = _safe_path(recorded_root / "table-hashes.json", directory=False)
    current_root = _safe_path(source_root, directory=True)
    _require(
        receipt.source_manifest_sha256 == expected_manifest_sha256
        and sha256_file(recorded_manifest) == expected_manifest_sha256,
        "tested projection source manifest binding differs",
    )
    report = authenticate_m7_input(
        current_root,
        expected_manifest_sha256=expected_manifest_sha256,
        verify_individual_files=False,
    )
    _require(report.table_counts == receipt.table_counts, "tested source table counts differ")
    _require(
        report.table_counts["candidate_pairs"] == _CANONICAL_PAIR_COUNT
        and report.table_counts["candidate_evidence"] == _CANONICAL_PAIR_COUNT,
        "tested source is not the complete canonical M7 candidate population",
    )
    # Authenticate every current source byte against the original successful Stage 1.
    # This allows an identical copy in a new stage without rebuilding lexical evidence.
    inventory = inventory_directory(
        current_root,
        ObjectStoreIdentity(provider="local", bucket="m7-projection-reuse", prefix="source"),
    )
    expected = {
        item.path.removeprefix("m7/"): (item.size, item.sha256)
        for item in completion.artifacts
        if item.path.startswith("m7/")
    }
    observed = {item.path: (item.size, item.digest) for item in inventory.objects}
    _require(
        observed == expected and inventory.object_count == receipt.source_object_count,
        "current M7 source inventory differs from the tested source completion",
    )
    _require(
        sha256_file(completion_path) == receipt.completion_sha256
        and sha256_file(recorded_manifest) == expected_manifest_sha256,
        "tested source control files changed during authentication",
    )
    return report, inventory.sha256


def _authenticate_projection(
    projection: Path, receipt: _OrderingReceipt, report: M7AuthenticationReport
) -> None:
    _require(sha256_file(projection) == receipt.output_sha256, "tested projection SHA-256 differs")
    parquet = pq.ParquetFile(projection)
    _require(
        parquet.metadata.num_rows == receipt.output_row_count == _CANONICAL_PAIR_COUNT,
        "tested projection actual Parquet row count differs",
    )
    registration = DetectorRegistration(
        detector_id="m7_lexical_rrf",
        family="lexical",
        independence_group="lexical_m7",
        original_language_capable=True,
        contains_english_derived_evidence=True,
        counts_for_independence=True,
        normalization="empirical_percentile",
        null_family="within_book_reassignment",
    )
    # The existing adapter authenticates the exact schema and first evidence row.
    # Production still consumes the entire strict, uniquely ordered evidence iterator.
    evidence = iter_m7_raw_evidence(
        projection,
        registration=registration,
        source_artifact_sha256=report.manifest_sha256,
        batch_size=1,
    )
    try:
        first = next(evidence)
        _require(first.candidate_pair_id == receipt.first_final_id, "tested first final ID differs")
    finally:
        close = getattr(evidence, "close", None)
        if close is not None:
            close()
    constants: dict[str, str | int] = {"m7_source_manifest_sha256": report.manifest_sha256}
    for table in ("candidate_pairs", "candidate_evidence", "shared_evidence"):
        constants[f"m7_{table}_logical_sha256"] = report.table_logical_sha256[table]
    constants.update(
        {
            "m7_projection_candidate_pair_count": report.table_counts["candidate_pairs"],
            "m7_projection_candidate_evidence_count": report.table_counts["candidate_evidence"],
            "m7_projection_shared_evidence_count": report.table_counts["shared_evidence"],
        }
    )
    for batch in parquet.iter_batches(
        batch_size=65_536, columns=list(constants), use_threads=False
    ):
        for name, expected in constants.items():
            values = batch.column(name)
            _require(
                values.null_count == 0 and pc.all(pc.equal(values, expected)).as_py() is True,
                f"tested projection embedded binding differs: {name}",
            )
    last_group = parquet.read_row_group(
        parquet.num_row_groups - 1, columns=["passage_a_id", "passage_b_id"], use_threads=False
    )
    last = last_group.slice(last_group.num_rows - 1, 1).to_pylist()[0]
    _require(
        candidate_pair_id(last["passage_a_id"], last["passage_b_id"]) == receipt.last_final_id,
        "tested last final ID differs",
    )


def reuse_tested_projection(
    receipt_path: Path,
    source_root: Path,
    output_path: Path,
    expected_manifest_sha256: str,
    *,
    expected_receipt_sha256: str,
    expected_code_commit: str = _REVIEWED_COMMIT,
) -> Path:
    """Copy an exactly pinned tested projection; retain its receipt and reuse binding.

    The caller supplies the trusted receipt hash independently of the cache bundle.
    Cache misses and inconsistencies are fatal, never a silent rebuild fallback.
    Only the new projection and its ``.reuse.json`` provenance are written.
    """

    try:
        receipt_file = _safe_path(receipt_path, directory=False)
        raw_receipt = receipt_file.read_bytes()
        _require(
            hashlib.sha256(raw_receipt).hexdigest() == expected_receipt_sha256,
            "tested projection receipt SHA-256 differs from the trusted pin",
        )
        flags = (
            "complete_source_inventory_authenticated",
            "downstream_order_condition_passed",
            "full_stream_reached_eof",
            "globally_unique_final_ids",
            "strict_final_identity_order",
        )
        payload = json.loads(raw_receipt)
        _require(
            isinstance(payload, dict) and all(payload.get(name) is True for name in flags),
            "tested projection receipt lacks complete successful ordering checks",
        )
        receipt = _OrderingReceipt.model_validate_json(raw_receipt)
        _require(
            receipt.code_commit == expected_code_commit, "tested projection code commit differs"
        )
        adapter_blobs = _authenticate_adapter(expected_code_commit)
        _require(
            receipt.started_at.tzinfo is not None
            and receipt.completed_at.tzinfo is not None
            and receipt.completed_at >= receipt.started_at,
            "tested projection receipt timestamps are invalid",
        )
        _require(
            receipt.stream_row_count == receipt.output_row_count == _CANONICAL_PAIR_COUNT,
            "tested projection receipt does not cover the complete canonical population",
        )
        recorded_output = Path(receipt.output_path)
        _require(
            recorded_output.is_absolute()
            and recorded_output.name == _PROJECTION_NAME
            and recorded_output.parent == Path(receipt.test_directory),
            "tested projection original output path is inconsistent",
        )
        projection = _safe_path(receipt_file.parent / _PROJECTION_NAME, directory=False)
        output = _new_output(output_path)
        provenance = _new_output(output.with_name(output.name + ".reuse.json"))
        for input_root in (
            receipt_file.parent,
            source_root.absolute(),
            Path(receipt.source_root),
            Path(receipt.completion_path).parent.parent.parent,
        ):
            _require(
                not output.is_relative_to(input_root),
                "projection reuse output must be outside preserved inputs",
            )
        report, inventory_sha256 = _authenticate_source(
            receipt, source_root, expected_manifest_sha256
        )
        _authenticate_projection(projection, receipt, report)
        with projection.open("rb") as source, output.open("xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        _require(
            sha256_file(output) == sha256_file(projection) == receipt.output_sha256
            and pq.ParquetFile(output).metadata.num_rows == receipt.output_row_count,
            "projection copy changed content or row count",
        )
        _require(not output.samefile(projection), "projection reuse must not hardlink the cache")
        _require(
            receipt_file.read_bytes() == raw_receipt
            and sha256_file(source_root / "table-hashes.json") == expected_manifest_sha256,
            "projection reuse inputs changed during copying",
        )
        write_json_atomic_new(
            provenance,
            {
                "schema_version": 1,
                "reuse_kind": "pinned_full_ordering_test_projection_copy_v1",
                "reused_at": datetime.now(UTC).isoformat(),
                "source_receipt_path": str(receipt_file),
                "source_receipt_sha256": expected_receipt_sha256,
                "source_receipt_bytes_base64": base64.b64encode(raw_receipt).decode("ascii"),
                "tested_code_commit": receipt.code_commit,
                "reviewed_adapter_source_blobs": adapter_blobs,
                "recorded_source_root": receipt.source_root,
                "recorded_projection_path": receipt.output_path,
                "cache_projection_path": str(projection),
                "projection_sha256": receipt.output_sha256,
                "output_path": str(output),
                "output_row_count": receipt.output_row_count,
                "current_source_root": report.root,
                "source_manifest_sha256": report.manifest_sha256,
                "current_source_inventory_sha256": inventory_sha256,
                "source_completion_sha256": receipt.completion_sha256,
                "table_counts": report.table_counts,
                "complete_current_source_inventory_authenticated": True,
                "copy_mode": "exclusive_regular_file_copy",
                "downstream_full_strict_iterator_still_required": True,
            },
        )
        return output
    except ProjectionCacheError:
        raise
    except (OSError, ValueError, StopIteration, ObjectStoreError) as exc:
        raise ProjectionCacheError(
            f"could not authenticate tested M7 projection cache: {exc}"
        ) from exc
