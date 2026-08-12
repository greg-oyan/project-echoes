"""Disk-backed exact production calibration for final ensemble nulls.

The in-memory reference implementation is intentionally simple, but its
``pair -> group -> score`` dictionaries become expensive for a whole-canon
candidate population.  This module preserves that implementation's production
semantics while replacing the nested mappings and retained Pydantic rows with
fixed-width, authenticated NumPy files.

Input rows must already be sorted by candidate-pair ID.  Each row carries one
fixed score vector per registered scope, in the exact configured independence-
group order.  Calibration writes only aggregate per-pair statistics; a
pair-by-iteration matrix is never written or retained.  Typed calibration rows
are constructed one at a time by :meth:`CompactNullCalibrationResult.iter_rows`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal, Self, cast

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes.final_discovery.config import (
    FinalDiscoveryConfig,
    final_discovery_config_sha256,
)
from echoes.final_discovery.nulls import (
    EnsembleNullCalibrationRow,
    EnsembleNullThresholdReport,
    EnsembleNullThresholdSummary,
    build_ensemble_null_threshold_summary,
    ensemble_reporting_thresholds,
)

CalibrationScope = Literal["full", "remove_all_english"]

_SCOPES: tuple[CalibrationScope, ...] = ("full", "remove_all_english")
_FLOAT_DTYPE = np.dtype("<f8")
_COUNT_DTYPE = np.dtype("<i8")
_CODE_DTYPE = np.dtype("<i4")
_PERMUTATION_MEMORY_TARGET = 96 * 1024**2
_OBSERVED_CHUNK_ROWS = 131_072
_INPUT_RECEIPT_NAME = "compact-group-scores.json"
_CALIBRATION_RECEIPT_NAME = "compact-null-calibration.json"


class CompactNullCalibrationError(ValueError):
    """Raised when compact calibration input or output fails closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompactArtifactReceipt(_FrozenModel):
    """Identity and physical layout for one compact artifact."""

    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    dtype: Literal["<f8", "<i8", "<i4", "ascii-jsonl"]
    shape: tuple[int, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def fixed_width_size_matches_shape(self) -> Self:
        if any(dimension < 1 for dimension in self.shape):
            raise ValueError("compact artifact dimensions must be positive")
        item_sizes = {"<f8": 8, "<i8": 8, "<i4": 4}
        if self.dtype in item_sizes:
            expected = math.prod(self.shape) * item_sizes[self.dtype]
            if self.size_bytes != expected:
                raise ValueError("compact fixed-width artifact size disagrees with its shape")
        return self


class CompactGroupScoreReceipt(_FrozenModel):
    """Authenticated, portable identity of a compact group-score dataset."""

    schema_version: Literal[1] = 1
    format_id: Literal["echoes-compact-group-scores-v1"] = "echoes-compact-group-scores-v1"
    pair_count: int = Field(ge=1)
    group_ids: tuple[str, ...] = Field(min_length=1)
    missing_group_score: float = Field(ge=0.0, le=1.0)
    calibration_scopes: tuple[CalibrationScope, ...]
    stratum_labels_by_code: tuple[str, ...] = Field(min_length=1)
    stratum_counts_by_code: tuple[int, ...] = Field(min_length=1)
    pair_ids_strictly_sorted: Literal[True]
    artifacts: tuple[CompactArtifactReceipt, ...] = Field(min_length=4, max_length=4)
    logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    persistent_bytes: int = Field(ge=1)
    maximum_builder_row_buffer_bytes: int = Field(ge=1)
    nested_pair_group_mappings_persisted: Literal[False]

    @model_validator(mode="after")
    def registry_and_counts_are_consistent(self) -> Self:
        if self.calibration_scopes != _SCOPES:
            raise ValueError("compact input must contain the exact two registered scopes")
        if len(self.group_ids) != len(set(self.group_ids)) or any(
            not group_id for group_id in self.group_ids
        ):
            raise ValueError("compact input group IDs must be nonempty and unique")
        if len(self.stratum_labels_by_code) != len(set(self.stratum_labels_by_code)):
            raise ValueError("compact input stratum labels must be unique")
        if any(not label for label in self.stratum_labels_by_code):
            raise ValueError("compact input stratum labels must be nonempty")
        if len(self.stratum_labels_by_code) != len(self.stratum_counts_by_code):
            raise ValueError("compact input stratum labels and counts must align")
        if any(count < 1 for count in self.stratum_counts_by_code):
            raise ValueError("compact input strata must be nonempty")
        if sum(self.stratum_counts_by_code) != self.pair_count:
            raise ValueError("compact input stratum counts must cover every pair")
        paths = [artifact.relative_path for artifact in self.artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("compact input artifacts must be uniquely path-sorted")
        if sum(artifact.size_bytes for artifact in self.artifacts) != self.persistent_bytes:
            raise ValueError("compact input persistent-byte total is inconsistent")
        return self


class CompactScopeCalibrationReceipt(_FrozenModel):
    """Persisted aggregate arrays for one final-null calibration scope."""

    calibration_scope: CalibrationScope
    unique_observed_threshold_count: int = Field(ge=1)
    artifacts: tuple[CompactArtifactReceipt, ...] = Field(min_length=5, max_length=5)
    reporting_threshold_summaries: tuple[EnsembleNullThresholdSummary, ...] = Field(min_length=1)
    persistent_bytes: int = Field(ge=1)

    @model_validator(mode="after")
    def artifacts_are_canonical(self) -> Self:
        paths = [artifact.relative_path for artifact in self.artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("compact calibration artifacts must be uniquely path-sorted")
        if sum(artifact.size_bytes for artifact in self.artifacts) != self.persistent_bytes:
            raise ValueError("compact calibration persistent-byte total is inconsistent")
        if any(
            summary.calibration_scope != self.calibration_scope
            for summary in self.reporting_threshold_summaries
        ):
            raise ValueError("compact reporting summary has the wrong calibration scope")
        return self


class CompactCalibrationResourceReceipt(_FrozenModel):
    """Auditable explicit bounds for the compact production computation."""

    pair_count: int = Field(ge=1)
    group_count: int = Field(ge=1)
    stratum_count: int = Field(ge=1)
    maximum_stratum_size: int = Field(ge=1)
    permutation_batch_size: int = Field(ge=1, le=32)
    permutation_memory_target_bytes: Literal[100663296] = 100663296
    maximum_explicit_numpy_working_bytes_upper_bound: int = Field(ge=1)
    pair_iteration_matrix_bytes_if_materialized: int = Field(ge=1)
    pair_iteration_matrix_persisted: Literal[False]
    reporting_threshold_count: int = Field(ge=1)
    reporting_count_vector_cells_per_scope: int = Field(ge=1)
    reporting_count_vectors_persisted_in_authenticated_receipt: Literal[True]
    output_rows_retained_in_memory: Literal[False]
    row_emission: Literal["one_pydantic_row_at_a_time"]


class CompactNullCalibrationReceipt(_FrozenModel):
    """Complete scientific and resource identity for compact calibration."""

    schema_version: Literal[1] = 1
    algorithm_id: Literal["echoes-compact-stratified-ensemble-null-v1"] = (
        "echoes-compact-stratified-ensemble-null-v1"
    )
    input_logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pair_count: int = Field(ge=1)
    group_ids: tuple[str, ...] = Field(min_length=1)
    stratum_labels_by_code: tuple[str, ...] = Field(min_length=1)
    stratum_counts_by_code: tuple[int, ...] = Field(min_length=1)
    calibration_scopes: tuple[CalibrationScope, ...]
    iterations: int = Field(ge=1)
    seed: int = Field(ge=0)
    minimum_effective_null_draws: int = Field(ge=1)
    null_method: Literal["stratified_candidate_pair_permutation"]
    numpy_version: str = Field(min_length=1)
    random_bit_generator: Literal["PCG64"]
    permutation_key_dtype: Literal["float32"]
    permutation_order: Literal["lexical_stratum_then_lexical_pair_numpy_argsort_axis_2"]
    scope_receipts: tuple[CompactScopeCalibrationReceipt, ...] = Field(min_length=2, max_length=2)
    resource_bounds: CompactCalibrationResourceReceipt
    persistent_bytes: int = Field(ge=1)
    logical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def scopes_and_resources_reconcile(self) -> Self:
        if self.calibration_scopes != _SCOPES:
            raise ValueError("compact calibration must contain both registered scopes")
        if tuple(receipt.calibration_scope for receipt in self.scope_receipts) != _SCOPES:
            raise ValueError("compact scope receipts are not in canonical scope order")
        if sum(receipt.persistent_bytes for receipt in self.scope_receipts) != (
            self.persistent_bytes
        ):
            raise ValueError("compact calibration persistent-byte total is inconsistent")
        if self.resource_bounds.pair_count != self.pair_count:
            raise ValueError("compact calibration resource pair count is inconsistent")
        if self.resource_bounds.group_count != len(self.group_ids):
            raise ValueError("compact calibration resource group count is inconsistent")
        if self.resource_bounds.stratum_count != len(self.stratum_labels_by_code):
            raise ValueError("compact calibration resource stratum count is inconsistent")
        reporting_thresholds = tuple(
            summary.score_threshold
            for summary in self.scope_receipts[0].reporting_threshold_summaries
        )
        if any(
            tuple(
                summary.score_threshold for summary in scope_receipt.reporting_threshold_summaries
            )
            != reporting_thresholds
            for scope_receipt in self.scope_receipts
        ):
            raise ValueError("compact calibration scopes use different reporting thresholds")
        if self.resource_bounds.reporting_threshold_count != len(reporting_thresholds):
            raise ValueError("compact calibration reporting-threshold bound is inconsistent")
        if self.resource_bounds.reporting_count_vector_cells_per_scope != (
            len(reporting_thresholds) * self.iterations
        ):
            raise ValueError("compact calibration reporting-vector bound is inconsistent")
        if any(
            summary.hypothesis_count != self.pair_count or summary.iterations != self.iterations
            for scope_receipt in self.scope_receipts
            for summary in scope_receipt.reporting_threshold_summaries
        ):
            raise ValueError("compact calibration reporting population is inconsistent")
        return self


@dataclass(frozen=True, slots=True)
class CompactGroupScoreRow:
    """One fixed-width pair row in configured group order.

    This deliberately is not a Pydantic model.  A producer can aggregate and
    yield one pair at a time without retaining detector evidence or nested
    group dictionaries.
    """

    candidate_pair_id: str
    stratum: str
    full_scores: tuple[float, ...]
    remove_all_english_scores: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class CompactGroupScoreDataset:
    """Authenticated disk-backed group scores."""

    root: Path
    receipt: CompactGroupScoreReceipt

    def score_matrix(self, scope: CalibrationScope) -> np.memmap:
        """Open one read-only ``pair_count x group_count`` score memmap."""

        relative = _input_score_path(scope)
        return np.memmap(
            self.root / relative,
            mode="r",
            dtype=_FLOAT_DTYPE,
            shape=(self.receipt.pair_count, len(self.receipt.group_ids)),
        )

    def stratum_codes(self) -> np.memmap:
        """Open read-only integer stratum codes aligned to pair order."""

        return np.memmap(
            self.root / "stratum-codes.i32",
            mode="r",
            dtype=_CODE_DTYPE,
            shape=(self.receipt.pair_count,),
        )

    def iter_metadata(self) -> Iterator[tuple[str, str]]:
        """Stream pair identity and stratum in lexical pair order."""

        yield from _iter_metadata(self.root / "pair-metadata.jsonl")


@dataclass(frozen=True, slots=True)
class CompactNullCalibrationResult:
    """Authenticated disk-backed aggregate calibration result."""

    root: Path
    input_dataset: CompactGroupScoreDataset
    receipt: CompactNullCalibrationReceipt

    def threshold_report(self) -> EnsembleNullThresholdReport:
        """Return the authenticated bounded reporting artifact without rerunning nulls."""

        first_scope = self.receipt.scope_receipts[0]
        reporting_thresholds = tuple(
            summary.score_threshold for summary in first_scope.reporting_threshold_summaries
        )
        return EnsembleNullThresholdReport(
            config_sha256=self.receipt.config_sha256,
            threshold_source="ensemble.minimum_tier_a_ensemble_score",
            reporting_thresholds=reporting_thresholds,
            hypothesis_count=self.receipt.pair_count,
            iterations=self.receipt.iterations,
            seed=self.receipt.seed,
            null_method=self.receipt.null_method,
            summaries=tuple(
                summary
                for scope_receipt in self.receipt.scope_receipts
                for summary in scope_receipt.reporting_threshold_summaries
            ),
            pair_by_iteration_matrices_persisted=False,
            threshold_count_vectors_persisted=True,
        )

    def iter_rows(self, scope: CalibrationScope) -> Iterator[EnsembleNullCalibrationRow]:
        """Construct and yield typed rows one at a time in lexical pair order."""

        scope_receipt = _scope_receipt(self.receipt, scope)
        arrays = {
            name: np.memmap(
                self.root / _scope_output_path(scope, name),
                mode="r",
                dtype=dtype,
                shape=(self.receipt.pair_count,),
            )
            for name, dtype in _OUTPUT_ARRAY_DTYPES.items()
        }
        codes = self.input_dataset.stratum_codes()
        labels = self.receipt.stratum_labels_by_code
        sizes = self.receipt.stratum_counts_by_code
        emitted = 0
        try:
            for index, (pair_id, stratum) in enumerate(self.input_dataset.iter_metadata()):
                code = int(codes[index])
                if stratum != labels[code]:
                    raise CompactNullCalibrationError(
                        "compact metadata stratum differs from its authenticated code"
                    )
                stratum_size = sizes[code]
                effective_cells = stratum_size * self.receipt.iterations
                exceedance_count = int(arrays["null-exceedance-counts"][index])
                null_discovery_sum = int(arrays["null-discovery-count-sums"][index])
                observed_discovery_count = int(arrays["observed-discovery-counts"][index])
                mean_null = (null_discovery_sum + 1) / (self.receipt.iterations + 1)
                raw_fdr = min(mean_null / observed_discovery_count, 1.0)
                yield EnsembleNullCalibrationRow(
                    candidate_pair_id=pair_id,
                    calibration_scope=scope,
                    stratum=stratum,
                    stratum_size=stratum_size,
                    observed_score=float(arrays["observed-scores"][index]),
                    null_exceedance_count=exceedance_count,
                    effective_null_cell_count=effective_cells,
                    empirical_p_value=(exceedance_count + 1) / (effective_cells + 1),
                    null_discovery_count_sum=null_discovery_sum,
                    mean_null_discovery_count=mean_null,
                    observed_discovery_count=observed_discovery_count,
                    raw_empirical_fdr=raw_fdr,
                    empirical_fdr=float(arrays["monotone-empirical-fdr"][index]),
                    minimum_attainable_p_value=1 / (effective_cells + 1),
                    minimum_effective_null_draws=(self.receipt.minimum_effective_null_draws),
                    stratum_sufficient_for_bh=(
                        effective_cells >= self.receipt.minimum_effective_null_draws
                    ),
                    hypothesis_count=self.receipt.pair_count,
                    iterations=self.receipt.iterations,
                    seed=self.receipt.seed,
                    null_method=self.receipt.null_method,
                )
                emitted += 1
        finally:
            del arrays
            del codes
        if emitted != self.receipt.pair_count:
            raise CompactNullCalibrationError(
                f"compact metadata emitted {emitted} rows; expected {self.receipt.pair_count}"
            )
        if scope_receipt.unique_observed_threshold_count < 1:
            raise CompactNullCalibrationError("compact calibration scope has no thresholds")


_OUTPUT_ARRAY_DTYPES: dict[str, np.dtype[np.generic]] = {
    "monotone-empirical-fdr": _FLOAT_DTYPE,
    "null-discovery-count-sums": _COUNT_DTYPE,
    "null-exceedance-counts": _COUNT_DTYPE,
    "observed-discovery-counts": _COUNT_DTYPE,
    "observed-scores": _FLOAT_DTYPE,
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _write_model_new(path: Path, model: BaseModel) -> None:
    payload = _canonical_json_bytes(model.model_dump(mode="json", exclude_none=False)) + b"\n"
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_existing(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _require_new_directory(path: Path, *, label: str) -> Path:
    if path.exists():
        raise CompactNullCalibrationError(f"refusing to replace existing {label}: {path}")
    try:
        path.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise CompactNullCalibrationError(f"could not create {label} {path}: {exc}") from exc
    return path.resolve()


def _input_score_path(scope: CalibrationScope) -> str:
    if scope == "full":
        return "full-scores.f64"
    return "remove-all-english-scores.f64"


def _scope_directory(scope: CalibrationScope) -> str:
    return scope.replace("_", "-")


def _scope_output_path(scope: CalibrationScope, name: str) -> str:
    suffix = "f64" if _OUTPUT_ARRAY_DTYPES[name] == _FLOAT_DTYPE else "i64"
    return f"{_scope_directory(scope)}/{name}.{suffix}"


def _artifact(
    path: Path,
    root: Path,
    *,
    dtype: str,
    shape: tuple[int, ...],
) -> CompactArtifactReceipt:
    return CompactArtifactReceipt(
        relative_path=path.relative_to(root).as_posix(),
        sha256=_sha256_file(path),
        size_bytes=path.stat().st_size,
        dtype=cast(Literal["<f8", "<i8", "<i4", "ascii-jsonl"], dtype),
        shape=shape,
    )


def _input_logical_sha256(
    *,
    pair_count: int,
    group_ids: Sequence[str],
    missing_group_score: float,
    stratum_labels: Sequence[str],
    stratum_counts: Sequence[int],
    artifacts: Sequence[CompactArtifactReceipt],
) -> str:
    payload = {
        "format_id": "echoes-compact-group-scores-v1",
        "pair_count": pair_count,
        "group_ids": list(group_ids),
        "missing_group_score": missing_group_score,
        "calibration_scopes": list(_SCOPES),
        "stratum_labels_by_code": list(stratum_labels),
        "stratum_counts_by_code": list(stratum_counts),
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _calibration_logical_sha256(
    *,
    input_sha256: str,
    config_sha256: str,
    iterations: int,
    seed: int,
    scope_receipts: Sequence[CompactScopeCalibrationReceipt],
) -> str:
    payload = {
        "algorithm_id": "echoes-compact-stratified-ensemble-null-v1",
        "input_logical_sha256": input_sha256,
        "config_sha256": config_sha256,
        "iterations": iterations,
        "seed": seed,
        "scope_receipts": [receipt.model_dump(mode="json") for receipt in scope_receipts],
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def write_compact_group_scores(
    rows: Iterable[CompactGroupScoreRow],
    destination: Path,
    *,
    group_ids: Sequence[str],
    missing_group_score: float,
) -> CompactGroupScoreDataset:
    """Stream sorted fixed-width group-score rows to a new authenticated dataset.

    ``full_scores`` and ``remove_all_english_scores`` are positional: their
    order must be the supplied ``group_ids`` order.  Missing groups must be
    represented explicitly by ``missing_group_score`` before this boundary.
    """

    groups = tuple(group_ids)
    if not groups or len(groups) != len(set(groups)) or any(not group for group in groups):
        raise CompactNullCalibrationError("compact group IDs must be nonempty and unique")
    if not math.isfinite(missing_group_score) or not 0.0 <= missing_group_score <= 1.0:
        raise CompactNullCalibrationError("compact missing-group score must be within [0, 1]")
    root = _require_new_directory(destination, label="compact group-score dataset")
    metadata_path = root / "pair-metadata.jsonl"
    code_path = root / "stratum-codes.i32"
    full_path = root / _input_score_path("full")
    ablated_path = root / _input_score_path("remove_all_english")
    stratum_code_by_label: dict[str, int] = {}
    stratum_labels: list[str] = []
    stratum_counts: list[int] = []
    previous_pair_id: str | None = None
    pair_count = 0
    try:
        with (
            metadata_path.open("xb") as metadata_handle,
            code_path.open("xb") as code_handle,
            full_path.open("xb") as full_handle,
            ablated_path.open("xb") as ablated_handle,
        ):
            for row in rows:
                pair_id = row.candidate_pair_id
                if not pair_id:
                    raise CompactNullCalibrationError("compact candidate-pair IDs cannot be empty")
                if previous_pair_id is not None and pair_id <= previous_pair_id:
                    raise CompactNullCalibrationError(
                        "compact candidate-pair IDs must be strictly lexically sorted"
                    )
                if not row.stratum:
                    raise CompactNullCalibrationError("compact null strata cannot be empty")
                if len(row.full_scores) != len(groups) or len(row.remove_all_english_scores) != len(
                    groups
                ):
                    raise CompactNullCalibrationError(
                        f"compact score vector width differs for {pair_id}"
                    )
                full = np.asarray(row.full_scores, dtype=_FLOAT_DTYPE)
                ablated = np.asarray(row.remove_all_english_scores, dtype=_FLOAT_DTYPE)
                if (
                    not bool(np.all(np.isfinite(full)))
                    or not bool(np.all(np.isfinite(ablated)))
                    or bool(np.any(full < 0.0))
                    or bool(np.any(full > 1.0))
                    or bool(np.any(ablated < 0.0))
                    or bool(np.any(ablated > 1.0))
                ):
                    raise CompactNullCalibrationError(
                        f"compact group scores must be finite and within [0, 1]: {pair_id}"
                    )
                if bool(np.any(ablated > full)):
                    raise CompactNullCalibrationError(
                        f"remove-all-English group score exceeds full score: {pair_id}"
                    )
                code = stratum_code_by_label.get(row.stratum)
                if code is None:
                    code = len(stratum_labels)
                    if code > np.iinfo(_CODE_DTYPE).max:
                        raise CompactNullCalibrationError("too many compact null strata")
                    stratum_code_by_label[row.stratum] = code
                    stratum_labels.append(row.stratum)
                    stratum_counts.append(0)
                stratum_counts[code] += 1
                metadata = _canonical_json_bytes(
                    {"candidate_pair_id": pair_id, "stratum": row.stratum}
                )
                metadata_handle.write(metadata + b"\n")
                code_handle.write(np.asarray((code,), dtype=_CODE_DTYPE).tobytes())
                full_handle.write(full.tobytes(order="C"))
                ablated_handle.write(ablated.tobytes(order="C"))
                previous_pair_id = pair_id
                pair_count += 1
            if pair_count == 0:
                raise CompactNullCalibrationError(
                    "compact ensemble null requires at least one candidate pair"
                )
            for handle in (metadata_handle, code_handle, full_handle, ablated_handle):
                handle.flush()
                os.fsync(handle.fileno())
    except OSError as exc:
        raise CompactNullCalibrationError(f"could not write compact group scores: {exc}") from exc

    artifacts = tuple(
        sorted(
            (
                _artifact(
                    full_path,
                    root,
                    dtype="<f8",
                    shape=(pair_count, len(groups)),
                ),
                _artifact(
                    metadata_path,
                    root,
                    dtype="ascii-jsonl",
                    shape=(pair_count,),
                ),
                _artifact(
                    ablated_path,
                    root,
                    dtype="<f8",
                    shape=(pair_count, len(groups)),
                ),
                _artifact(code_path, root, dtype="<i4", shape=(pair_count,)),
            ),
            key=lambda item: item.relative_path,
        )
    )
    logical_sha256 = _input_logical_sha256(
        pair_count=pair_count,
        group_ids=groups,
        missing_group_score=missing_group_score,
        stratum_labels=stratum_labels,
        stratum_counts=stratum_counts,
        artifacts=artifacts,
    )
    receipt = CompactGroupScoreReceipt(
        pair_count=pair_count,
        group_ids=groups,
        missing_group_score=missing_group_score,
        calibration_scopes=_SCOPES,
        stratum_labels_by_code=tuple(stratum_labels),
        stratum_counts_by_code=tuple(stratum_counts),
        pair_ids_strictly_sorted=True,
        artifacts=artifacts,
        logical_sha256=logical_sha256,
        persistent_bytes=sum(artifact.size_bytes for artifact in artifacts),
        maximum_builder_row_buffer_bytes=(len(groups) * 2 * _FLOAT_DTYPE.itemsize),
        nested_pair_group_mappings_persisted=False,
    )
    _write_model_new(root / _INPUT_RECEIPT_NAME, receipt)
    return open_compact_group_scores(root)


def _iter_metadata(path: Path) -> Iterator[tuple[str, str]]:
    try:
        with path.open("rb") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.endswith(b"\n"):
                    raise CompactNullCalibrationError(
                        f"compact metadata line {line_number} lacks a final LF"
                    )
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CompactNullCalibrationError(
                        f"invalid compact metadata JSON at line {line_number}"
                    ) from exc
                if not isinstance(parsed, dict) or set(parsed) != {
                    "candidate_pair_id",
                    "stratum",
                }:
                    raise CompactNullCalibrationError(
                        f"invalid compact metadata object at line {line_number}"
                    )
                pair_id = parsed["candidate_pair_id"]
                stratum = parsed["stratum"]
                if not isinstance(pair_id, str) or not pair_id:
                    raise CompactNullCalibrationError(
                        f"invalid compact candidate-pair ID at line {line_number}"
                    )
                if not isinstance(stratum, str) or not stratum:
                    raise CompactNullCalibrationError(
                        f"invalid compact stratum at line {line_number}"
                    )
                yield pair_id, stratum
    except OSError as exc:
        raise CompactNullCalibrationError(f"could not read compact metadata: {exc}") from exc


def _authenticate_artifacts(
    root: Path,
    artifacts: Sequence[CompactArtifactReceipt],
    *,
    receipt_name: str,
) -> None:
    expected_paths = {artifact.relative_path for artifact in artifacts} | {receipt_name}
    try:
        observed_paths = {
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        }
    except OSError as exc:
        raise CompactNullCalibrationError(f"could not inventory compact artifacts: {exc}") from exc
    if observed_paths != expected_paths:
        raise CompactNullCalibrationError(
            "compact artifact paths differ from the authenticated receipt"
        )
    for artifact in artifacts:
        path = root / artifact.relative_path
        if path.is_symlink() or not path.is_file():
            raise CompactNullCalibrationError(
                f"compact artifact is missing or unsafe: {artifact.relative_path}"
            )
        if path.stat().st_size != artifact.size_bytes or _sha256_file(path) != artifact.sha256:
            raise CompactNullCalibrationError(
                f"compact artifact size or SHA-256 differs: {artifact.relative_path}"
            )


def open_compact_group_scores(root: Path) -> CompactGroupScoreDataset:
    """Authenticate and open an existing compact group-score dataset."""

    resolved = root.resolve()
    receipt_path = resolved / _INPUT_RECEIPT_NAME
    try:
        receipt = CompactGroupScoreReceipt.model_validate_json(receipt_path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise CompactNullCalibrationError(
            f"invalid compact group-score receipt {receipt_path}: {exc}"
        ) from exc
    _authenticate_artifacts(resolved, receipt.artifacts, receipt_name=_INPUT_RECEIPT_NAME)
    expected_logical = _input_logical_sha256(
        pair_count=receipt.pair_count,
        group_ids=receipt.group_ids,
        missing_group_score=receipt.missing_group_score,
        stratum_labels=receipt.stratum_labels_by_code,
        stratum_counts=receipt.stratum_counts_by_code,
        artifacts=receipt.artifacts,
    )
    if expected_logical != receipt.logical_sha256:
        raise CompactNullCalibrationError("compact input logical SHA-256 differs")
    dataset = CompactGroupScoreDataset(root=resolved, receipt=receipt)
    codes = dataset.stratum_codes()
    previous_pair: str | None = None
    observed_counts = [0] * len(receipt.stratum_labels_by_code)
    metadata_count = 0
    for index, (pair_id, stratum) in enumerate(dataset.iter_metadata()):
        if index >= receipt.pair_count:
            raise CompactNullCalibrationError("compact metadata contains too many rows")
        if previous_pair is not None and pair_id <= previous_pair:
            raise CompactNullCalibrationError("compact metadata pair IDs are not strictly sorted")
        code = int(codes[index])
        if code < 0 or code >= len(receipt.stratum_labels_by_code):
            raise CompactNullCalibrationError("compact metadata carries an invalid stratum code")
        if stratum != receipt.stratum_labels_by_code[code]:
            raise CompactNullCalibrationError("compact stratum code and metadata disagree")
        observed_counts[code] += 1
        previous_pair = pair_id
        metadata_count += 1
    del codes
    if metadata_count != receipt.pair_count:
        raise CompactNullCalibrationError(
            f"compact metadata contains {metadata_count} rows; expected {receipt.pair_count}"
        )
    if tuple(observed_counts) != receipt.stratum_counts_by_code:
        raise CompactNullCalibrationError("compact metadata stratum counts differ")
    full = dataset.score_matrix("full")
    ablated = dataset.score_matrix("remove_all_english")
    for start in range(0, receipt.pair_count, _OBSERVED_CHUNK_ROWS):
        stop = min(start + _OBSERVED_CHUNK_ROWS, receipt.pair_count)
        full_chunk = full[start:stop]
        ablated_chunk = ablated[start:stop]
        if (
            not bool(np.all(np.isfinite(full_chunk)))
            or not bool(np.all(np.isfinite(ablated_chunk)))
            or bool(np.any(full_chunk < 0.0))
            or bool(np.any(full_chunk > 1.0))
            or bool(np.any(ablated_chunk < 0.0))
            or bool(np.any(ablated_chunk > 1.0))
            or bool(np.any(ablated_chunk > full_chunk))
        ):
            raise CompactNullCalibrationError("compact score matrix is invalid")
    del full
    del ablated
    return dataset


def _batch_size(pair_count: int, group_count: int, iterations: int) -> int:
    bytes_per_iteration = max(pair_count * max(group_count, 1) * 16, 1)
    return max(
        1,
        min(iterations, 32, _PERMUTATION_MEMORY_TARGET // bytes_per_iteration),
    )


def _member_order_and_offsets(
    dataset: CompactGroupScoreDataset,
) -> tuple[np.ndarray, tuple[int, ...], tuple[int, ...]]:
    labels = dataset.receipt.stratum_labels_by_code
    codes = dataset.stratum_codes()
    lexical_codes = tuple(sorted(range(len(labels)), key=lambda code: labels[code]))
    lexical_rank_by_code = np.empty(len(labels), dtype=np.int32)
    for rank, code in enumerate(lexical_codes):
        lexical_rank_by_code[code] = rank
    row_ranks = lexical_rank_by_code[codes]
    member_order = np.argsort(row_ranks, kind="stable")
    lexical_counts = tuple(dataset.receipt.stratum_counts_by_code[code] for code in lexical_codes)
    offsets = [0]
    for count in lexical_counts:
        offsets.append(offsets[-1] + count)
    del row_ranks
    del lexical_rank_by_code
    del codes
    return member_order, lexical_codes, tuple(offsets)


def _compute_observed_scores(
    score_matrix: np.memmap,
    output_path: Path,
    weights: Sequence[float],
) -> np.memmap:
    pair_count = score_matrix.shape[0]
    observed = np.memmap(
        output_path,
        mode="w+",
        dtype=_FLOAT_DTYPE,
        shape=(pair_count,),
    )
    for start in range(0, pair_count, _OBSERVED_CHUNK_ROWS):
        stop = min(start + _OBSERVED_CHUNK_ROWS, pair_count)
        for index in range(start, stop):
            observed[index] = math.fsum(
                weight * float(score_matrix[index, group_index])
                for group_index, weight in enumerate(weights)
            )
    observed.flush()
    _fsync_existing(output_path)
    return observed


def _permutation_counts(
    score_matrix: np.memmap,
    observed: np.memmap,
    member_order: np.ndarray,
    offsets: Sequence[int],
    weights: np.ndarray,
    *,
    pair_count: int,
    iterations: int,
    seed: int,
    batch_size: int,
    reporting_thresholds: Sequence[float],
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    list[np.ndarray],
    list[np.ndarray],
    tuple[tuple[int, ...], ...],
]:
    unique_thresholds, threshold_counts = np.unique(observed, return_counts=True)
    observed_discoveries = np.cumsum(threshold_counts[::-1], dtype=np.int64)[::-1]
    del threshold_counts
    local_thresholds: list[np.ndarray] = []
    pooled_exceedances: list[np.ndarray] = []
    for start, stop in pairwise(offsets):
        members = member_order[start:stop]
        thresholds = np.unique(observed[members])
        local_thresholds.append(thresholds)
        pooled_exceedances.append(np.zeros(len(thresholds), dtype=np.int64))
    global_counts = np.zeros(len(unique_thresholds), dtype=np.int64)
    reporting_threshold_array = np.asarray(reporting_thresholds, dtype=np.float64)
    reporting_counts = np.empty(
        (len(reporting_threshold_array), iterations),
        dtype=np.int64,
    )
    random_source = np.random.default_rng(seed)
    completed = 0
    while completed < iterations:
        current_batch = min(batch_size, iterations - completed)
        batch_scores = np.empty((current_batch, pair_count), dtype=np.float64)
        for stratum_index, (start, stop) in enumerate(pairwise(offsets)):
            members = member_order[start:stop]
            values = np.ascontiguousarray(score_matrix[members, :].T, dtype=np.float64)
            random_keys = random_source.random(
                (current_batch, len(weights), len(members)), dtype=np.float32
            )
            order = np.argsort(random_keys, axis=2)
            permuted = np.take_along_axis(values[None, :, :], order, axis=2)
            reassigned_scores = np.einsum("bgs,g->bs", permuted, weights, optimize=True)
            batch_scores[:, members] = reassigned_scores
            flattened = np.sort(reassigned_scores, axis=None)
            thresholds = local_thresholds[stratum_index]
            pooled_exceedances[stratum_index] += flattened.size - np.searchsorted(
                flattened, thresholds, side="left"
            )
            del values
            del random_keys
            del order
            del permuted
            del reassigned_scores
            del flattened
        batch_scores.sort(axis=1)
        for batch_offset, iteration_scores in enumerate(batch_scores):
            global_counts += pair_count - np.searchsorted(
                iteration_scores, unique_thresholds, side="left"
            )
            reporting_counts[:, completed + batch_offset] = pair_count - np.searchsorted(
                iteration_scores,
                reporting_threshold_array,
                side="left",
            )
        del batch_scores
        completed += current_batch
    return (
        unique_thresholds,
        observed_discoveries,
        global_counts,
        local_thresholds,
        pooled_exceedances,
        tuple(
            tuple(int(count) for count in reporting_counts[index])
            for index in range(len(reporting_threshold_array))
        ),
    )


def _write_scope_result(
    dataset: CompactGroupScoreDataset,
    output_root: Path,
    scope: CalibrationScope,
    member_order: np.ndarray,
    offsets: Sequence[int],
    weights: np.ndarray,
    *,
    iterations: int,
    seed: int,
    batch_size: int,
    reporting_thresholds: Sequence[float],
) -> CompactScopeCalibrationReceipt:
    scope_root = output_root / _scope_directory(scope)
    scope_root.mkdir(parents=False, exist_ok=False)
    score_matrix = dataset.score_matrix(scope)
    observed_path = output_root / _scope_output_path(scope, "observed-scores")
    observed = _compute_observed_scores(
        score_matrix,
        observed_path,
        tuple(float(value) for value in weights),
    )
    (
        unique_thresholds,
        observed_discoveries,
        global_counts,
        local_thresholds,
        pooled_exceedances,
        reporting_counts,
    ) = _permutation_counts(
        score_matrix,
        observed,
        member_order,
        offsets,
        weights,
        pair_count=dataset.receipt.pair_count,
        iterations=iterations,
        seed=seed,
        batch_size=batch_size,
        reporting_thresholds=reporting_thresholds,
    )
    observed_sorted = np.sort(np.asarray(observed))
    reporting_summaries = tuple(
        build_ensemble_null_threshold_summary(
            scope=scope,
            threshold=threshold,
            observed_count=dataset.receipt.pair_count
            - int(np.searchsorted(observed_sorted, threshold, side="left")),
            null_counts=reporting_counts[index],
            hypothesis_count=dataset.receipt.pair_count,
        )
        for index, threshold in enumerate(reporting_thresholds)
    )
    del observed_sorted
    raw_fdr = np.empty(len(unique_thresholds), dtype=np.float64)
    for index in range(len(unique_thresholds)):
        mean_null = (int(global_counts[index]) + 1) / (iterations + 1)
        raw_fdr[index] = min(mean_null / int(observed_discoveries[index]), 1.0)
    monotone_fdr = np.empty(len(unique_thresholds), dtype=np.float64)
    running_fdr = 0.0
    for index in range(len(unique_thresholds) - 1, -1, -1):
        running_fdr = max(running_fdr, float(raw_fdr[index]))
        monotone_fdr[index] = running_fdr

    output_arrays: dict[str, np.memmap] = {}
    for name, dtype in _OUTPUT_ARRAY_DTYPES.items():
        if name == "observed-scores":
            output_arrays[name] = observed
            continue
        output_arrays[name] = np.memmap(
            output_root / _scope_output_path(scope, name),
            mode="w+",
            dtype=dtype,
            shape=(dataset.receipt.pair_count,),
        )
    global_threshold_indices = np.searchsorted(unique_thresholds, observed)
    output_arrays["null-discovery-count-sums"][:] = global_counts[global_threshold_indices]
    output_arrays["observed-discovery-counts"][:] = observed_discoveries[global_threshold_indices]
    output_arrays["monotone-empirical-fdr"][:] = monotone_fdr[global_threshold_indices]
    for stratum_index, (start, stop) in enumerate(pairwise(offsets)):
        members = member_order[start:stop]
        local_indices = np.searchsorted(local_thresholds[stratum_index], observed[members])
        output_arrays["null-exceedance-counts"][members] = pooled_exceedances[stratum_index][
            local_indices
        ]
    del global_threshold_indices
    for name, array in output_arrays.items():
        array.flush()
        _fsync_existing(output_root / _scope_output_path(scope, name))
    del output_arrays
    del score_matrix
    del observed
    del observed_discoveries
    del global_counts
    del local_thresholds
    del pooled_exceedances
    del reporting_counts
    del raw_fdr
    del monotone_fdr
    artifacts = tuple(
        sorted(
            (
                _artifact(
                    output_root / _scope_output_path(scope, name),
                    output_root,
                    dtype=dtype.str,
                    shape=(dataset.receipt.pair_count,),
                )
                for name, dtype in _OUTPUT_ARRAY_DTYPES.items()
            ),
            key=lambda item: item.relative_path,
        )
    )
    return CompactScopeCalibrationReceipt(
        calibration_scope=scope,
        unique_observed_threshold_count=len(unique_thresholds),
        artifacts=artifacts,
        reporting_threshold_summaries=reporting_summaries,
        persistent_bytes=sum(artifact.size_bytes for artifact in artifacts),
    )


def _explicit_resource_bound(
    *,
    pair_count: int,
    group_count: int,
    maximum_stratum_size: int,
    iterations: int,
    batch_size: int,
) -> int:
    # Conservative sum of every explicitly allocated ndarray that can coexist:
    # global/local threshold and count vectors (80 bytes/pair upper bound),
    # member order, one stratum value matrix, random keys, argsort indices,
    # permuted values, stratum scores and their flattened copy, and batch scores.
    fixed_arrays = pair_count * 80
    stratum_values = group_count * maximum_stratum_size * 8
    random_keys = batch_size * group_count * maximum_stratum_size * 4
    order = batch_size * group_count * maximum_stratum_size * 8
    permuted = batch_size * group_count * maximum_stratum_size * 8
    stratum_scores_and_flattened = batch_size * maximum_stratum_size * 16
    batch_scores = batch_size * pair_count * 8
    return (
        fixed_arrays
        + stratum_values
        + random_keys
        + order
        + permuted
        + stratum_scores_and_flattened
        + batch_scores
    )


def calibrate_compact_ensemble_nulls(
    dataset: CompactGroupScoreDataset,
    destination: Path,
    *,
    config: FinalDiscoveryConfig,
    iterations: int,
    seed: int,
) -> CompactNullCalibrationResult:
    """Calibrate both registered scopes with exact production RNG semantics.

    This API is intentionally production-only.  It resets the pinned NumPy
    generator for each scope, matching two independent calls to the current
    reference function with the same registered seed.
    """

    authenticated = open_compact_group_scores(dataset.root)
    if authenticated.receipt != dataset.receipt:
        raise CompactNullCalibrationError("compact input receipt changed before calibration")
    configured_groups = tuple(config.ensemble.group_weights)
    if authenticated.receipt.group_ids != configured_groups:
        raise CompactNullCalibrationError(
            "compact input group order differs from the configured ensemble registry"
        )
    if authenticated.receipt.missing_group_score != config.ensemble.missing_group_score:
        raise CompactNullCalibrationError(
            "compact input missing-group score differs from the configured ensemble"
        )
    if iterations != config.calibration.production_iterations:
        raise CompactNullCalibrationError(
            "compact final null requires the preregistered production iteration count"
        )
    expected_seed = config.calibration.seeds.get("stratified_permutation")
    if seed != expected_seed or seed < 0:
        raise CompactNullCalibrationError(
            "compact final null requires the preregistered permutation seed"
        )
    pair_count = authenticated.receipt.pair_count
    if pair_count * iterations > np.iinfo(_COUNT_DTYPE).max:
        raise CompactNullCalibrationError("compact null counts exceed signed 64-bit capacity")
    output_root = destination.resolve()
    try:
        output_root.relative_to(authenticated.root)
    except ValueError:
        pass
    else:
        raise CompactNullCalibrationError(
            "compact calibration output cannot be inside its authenticated input dataset"
        )
    output_root = _require_new_directory(destination, label="compact null-calibration dataset")
    member_order, _lexical_codes, offsets = _member_order_and_offsets(authenticated)
    weights = np.asarray(
        [config.ensemble.group_weights[group] for group in configured_groups],
        dtype=np.float64,
    )
    batch_size = _batch_size(pair_count, len(configured_groups), iterations)
    reporting_thresholds = ensemble_reporting_thresholds(config)
    scope_receipts = tuple(
        _write_scope_result(
            authenticated,
            output_root,
            scope,
            member_order,
            offsets,
            weights,
            iterations=iterations,
            seed=seed,
            batch_size=batch_size,
            reporting_thresholds=reporting_thresholds,
        )
        for scope in _SCOPES
    )
    maximum_stratum_size = max(authenticated.receipt.stratum_counts_by_code)
    resource_bounds = CompactCalibrationResourceReceipt(
        pair_count=pair_count,
        group_count=len(configured_groups),
        stratum_count=len(authenticated.receipt.stratum_labels_by_code),
        maximum_stratum_size=maximum_stratum_size,
        permutation_batch_size=batch_size,
        maximum_explicit_numpy_working_bytes_upper_bound=_explicit_resource_bound(
            pair_count=pair_count,
            group_count=len(configured_groups),
            maximum_stratum_size=maximum_stratum_size,
            iterations=iterations,
            batch_size=batch_size,
        ),
        pair_iteration_matrix_bytes_if_materialized=pair_count * iterations * 8,
        pair_iteration_matrix_persisted=False,
        reporting_threshold_count=len(reporting_thresholds),
        reporting_count_vector_cells_per_scope=len(reporting_thresholds) * iterations,
        reporting_count_vectors_persisted_in_authenticated_receipt=True,
        output_rows_retained_in_memory=False,
        row_emission="one_pydantic_row_at_a_time",
    )
    config_sha256 = final_discovery_config_sha256(config)
    logical_sha256 = _calibration_logical_sha256(
        input_sha256=authenticated.receipt.logical_sha256,
        config_sha256=config_sha256,
        iterations=iterations,
        seed=seed,
        scope_receipts=scope_receipts,
    )
    receipt = CompactNullCalibrationReceipt(
        input_logical_sha256=authenticated.receipt.logical_sha256,
        config_sha256=config_sha256,
        pair_count=pair_count,
        group_ids=configured_groups,
        stratum_labels_by_code=authenticated.receipt.stratum_labels_by_code,
        stratum_counts_by_code=authenticated.receipt.stratum_counts_by_code,
        calibration_scopes=_SCOPES,
        iterations=iterations,
        seed=seed,
        minimum_effective_null_draws=config.calibration.minimum_effective_null_draws,
        null_method=config.ensemble.final_null_method,
        numpy_version=np.__version__,
        random_bit_generator="PCG64",
        permutation_key_dtype="float32",
        permutation_order="lexical_stratum_then_lexical_pair_numpy_argsort_axis_2",
        scope_receipts=scope_receipts,
        resource_bounds=resource_bounds,
        persistent_bytes=sum(receipt.persistent_bytes for receipt in scope_receipts),
        logical_sha256=logical_sha256,
    )
    _write_model_new(output_root / _CALIBRATION_RECEIPT_NAME, receipt)
    del member_order
    del weights
    return open_compact_null_calibration(output_root, input_dataset=authenticated)


def _scope_receipt(
    receipt: CompactNullCalibrationReceipt, scope: CalibrationScope
) -> CompactScopeCalibrationReceipt:
    for scope_receipt in receipt.scope_receipts:
        if scope_receipt.calibration_scope == scope:
            return scope_receipt
    raise CompactNullCalibrationError(f"compact calibration scope is absent: {scope}")


def open_compact_null_calibration(
    root: Path,
    *,
    input_dataset: CompactGroupScoreDataset,
) -> CompactNullCalibrationResult:
    """Authenticate and open an aggregate compact calibration result."""

    authenticated_input = open_compact_group_scores(input_dataset.root)
    if authenticated_input.receipt != input_dataset.receipt:
        raise CompactNullCalibrationError("compact input receipt changed")
    resolved = root.resolve()
    receipt_path = resolved / _CALIBRATION_RECEIPT_NAME
    try:
        receipt = CompactNullCalibrationReceipt.model_validate_json(receipt_path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise CompactNullCalibrationError(
            f"invalid compact null-calibration receipt {receipt_path}: {exc}"
        ) from exc
    if receipt.input_logical_sha256 != authenticated_input.receipt.logical_sha256:
        raise CompactNullCalibrationError("compact calibration is bound to another input")
    if receipt.pair_count != authenticated_input.receipt.pair_count:
        raise CompactNullCalibrationError("compact calibration pair count differs from input")
    if receipt.group_ids != authenticated_input.receipt.group_ids:
        raise CompactNullCalibrationError("compact calibration group registry differs from input")
    if (
        receipt.stratum_labels_by_code != authenticated_input.receipt.stratum_labels_by_code
        or receipt.stratum_counts_by_code != authenticated_input.receipt.stratum_counts_by_code
    ):
        raise CompactNullCalibrationError("compact calibration strata differ from input")
    artifacts = tuple(
        artifact for scope_receipt in receipt.scope_receipts for artifact in scope_receipt.artifacts
    )
    _authenticate_artifacts(
        resolved,
        artifacts,
        receipt_name=_CALIBRATION_RECEIPT_NAME,
    )
    expected_logical = _calibration_logical_sha256(
        input_sha256=receipt.input_logical_sha256,
        config_sha256=receipt.config_sha256,
        iterations=receipt.iterations,
        seed=receipt.seed,
        scope_receipts=receipt.scope_receipts,
    )
    if expected_logical != receipt.logical_sha256:
        raise CompactNullCalibrationError("compact calibration logical SHA-256 differs")
    return CompactNullCalibrationResult(
        root=resolved,
        input_dataset=authenticated_input,
        receipt=receipt,
    )
