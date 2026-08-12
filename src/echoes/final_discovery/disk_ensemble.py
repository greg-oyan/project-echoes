"""Bounded multi-pass final ensemble construction for production-scale ledgers.

The small in-memory implementation in :mod:`echoes.final_discovery.ensemble`
remains the executable oracle.  This module applies the same pair-local draft
and finalization functions while retaining only global p/q arrays, a Tier-B
top-100 set, and one bounded output-sort chunk at a time.
"""

from __future__ import annotations

import heapq
import json
import math
import os
from bisect import insort
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from itertools import groupby, zip_longest
from pathlib import Path
from typing import Literal, Self, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoes.final_discovery.config import FinalDiscoveryConfig
from echoes.final_discovery.ensemble import (
    EnsembleError,
    _Draft,
    _draft_from_pair,
    _final_candidate_from_draft,
)
from echoes.final_discovery.knownness import KnownnessIndex
from echoes.final_discovery.models import EvidenceRow, FinalCandidate, PassageRecord
from echoes.final_discovery.nulls import EnsembleNullCalibrationRow
from echoes.final_discovery.storage import iter_jsonl, sha256_file
from echoes.lexical.statistics import benjamini_hochberg


class DiskEnsembleError(RuntimeError):
    """Raised when a streamed candidate population is incomplete or inconsistent."""


class DiskEnsembleReceipt(BaseModel):
    """Portable identity and resource contract for one streamed candidate ledger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experiment_id: Literal["final-discovery-v1"] = "final-discovery-v1"
    method: Literal["three_pass_pair_stream_external_score_sort"] = (
        "three_pass_pair_stream_external_score_sort"
    )
    candidate_pair_count: int = Field(ge=1)
    evidence_row_count: int = Field(ge=1)
    maximum_candidate_pair_count: int = Field(ge=1)
    maximum_evidence_rows_per_pair: int = Field(ge=1)
    tier_a_count: int = Field(ge=0)
    tier_b_count: int = Field(ge=0, le=100)
    chunk_size: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    bh_method: Literal["benjamini_hochberg"] = "benjamini_hochberg"
    output_ordering: Literal["ensemble_score_desc_candidate_pair_id_asc"] = (
        "ensemble_score_desc_candidate_pair_id_asc"
    )
    output_file_name: str = Field(min_length=1)
    output_size: int = Field(ge=1)
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def counts_fit_contract(self) -> Self:
        if self.candidate_pair_count > self.maximum_candidate_pair_count:
            raise ValueError("candidate population exceeds the governed maximum")
        if self.tier_a_count + self.tier_b_count > self.candidate_pair_count:
            raise ValueError("tier counts exceed the candidate population")
        return self


@dataclass(frozen=True, slots=True)
class _PassStatistics:
    pair_count: int
    evidence_count: int
    maximum_rows_per_pair: int
    stratum_counts: dict[str, int]
    stratum_sizes: dict[str, int]
    hypothesis_count: int


def _canonical_model_line(model: BaseModel) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def _evidence_groups(path: Path) -> Iterator[tuple[str, tuple[EvidenceRow, ...]]]:
    prior_pair: str | None = None
    for pair_id, raw_group in groupby(
        iter_jsonl(path, EvidenceRow),
        key=lambda row: row.candidate_pair_id,
    ):
        if prior_pair is not None and pair_id <= prior_pair:
            raise DiskEnsembleError("evidence pairs are duplicate or not strictly ordered")
        rows = tuple(raw_group)
        if not rows:
            raise DiskEnsembleError(f"evidence group is empty: {pair_id}")
        detector_ids = [row.detector_id for row in rows]
        evidence_ids = [row.evidence_id for row in rows]
        if len(detector_ids) != len(set(detector_ids)):
            raise DiskEnsembleError(f"evidence repeats a detector/pair: {pair_id}")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise DiskEnsembleError(f"evidence IDs repeat inside a pair: {pair_id}")
        prior_pair = pair_id
        yield pair_id, rows


def _null_rows(
    path: Path,
    *,
    scope: Literal["full", "remove_all_english"],
) -> Iterator[EnsembleNullCalibrationRow]:
    prior_pair: str | None = None
    for row in iter_jsonl(path, EnsembleNullCalibrationRow):
        if row.calibration_scope != scope:
            raise DiskEnsembleError(f"{scope} null ledger contains the wrong scope")
        if prior_pair is not None and row.candidate_pair_id <= prior_pair:
            raise DiskEnsembleError(f"{scope} null pairs are duplicate or not ordered")
        prior_pair = row.candidate_pair_id
        yield row


def _validate_null_provenance(
    row: EnsembleNullCalibrationRow,
    *,
    pair_id: str,
    config: FinalDiscoveryConfig,
    expected_hypothesis_count: int | None,
) -> int:
    permitted_iterations = {
        config.calibration.fixture_iterations,
        config.calibration.production_iterations,
    }
    if (
        row.candidate_pair_id != pair_id
        or row.null_method != config.ensemble.final_null_method
        or row.seed != config.calibration.seeds["stratified_permutation"]
        or row.iterations not in permitted_iterations
    ):
        raise DiskEnsembleError(f"null provenance disagrees for pair {pair_id}")
    if expected_hypothesis_count is not None and (
        row.hypothesis_count != expected_hypothesis_count
    ):
        raise DiskEnsembleError("null ledgers disagree on the hypothesis count")
    return row.hypothesis_count


def _draft_stream(
    evidence_path: Path,
    full_null_path: Path,
    ablated_null_path: Path,
    *,
    passages: Mapping[str, PassageRecord],
    knownness: KnownnessIndex,
    config: FinalDiscoveryConfig,
) -> Iterator[tuple[_Draft, EnsembleNullCalibrationRow, EnsembleNullCalibrationRow]]:
    sentinel = object()
    hypothesis_count: int | None = None
    combined = zip_longest(
        _evidence_groups(evidence_path),
        _null_rows(full_null_path, scope="full"),
        _null_rows(ablated_null_path, scope="remove_all_english"),
        fillvalue=sentinel,
    )
    for evidence_item, full_item, ablated_item in combined:
        if sentinel in (evidence_item, full_item, ablated_item):
            raise DiskEnsembleError("evidence and null ledgers cover different populations")
        pair_id, rows = cast(tuple[str, tuple[EvidenceRow, ...]], evidence_item)
        full_null = cast(EnsembleNullCalibrationRow, full_item)
        ablated_null = cast(EnsembleNullCalibrationRow, ablated_item)
        if full_null.candidate_pair_id != pair_id or ablated_null.candidate_pair_id != pair_id:
            raise DiskEnsembleError("evidence and null pair ordering/populations differ")
        hypothesis_count = _validate_null_provenance(
            full_null,
            pair_id=pair_id,
            config=config,
            expected_hypothesis_count=hypothesis_count,
        )
        _validate_null_provenance(
            ablated_null,
            pair_id=pair_id,
            config=config,
            expected_hypothesis_count=hypothesis_count,
        )
        first = rows[0]
        try:
            left = passages[first.passage_a_id]
            right = passages[first.passage_b_id]
        except KeyError as exc:
            raise DiskEnsembleError(f"evidence references an absent passage: {exc}") from exc
        try:
            draft = _draft_from_pair(
                pair_id,
                rows,
                left,
                right,
                knownness=knownness,
                config=config,
                full_null=full_null,
                ablated_null=ablated_null,
                ablation_null_available=True,
            )
        except EnsembleError as exc:
            raise DiskEnsembleError(str(exc)) from exc
        yield draft, full_null, ablated_null


def _first_pass(
    evidence_path: Path,
    full_null_path: Path,
    ablated_null_path: Path,
    *,
    passages: Mapping[str, PassageRecord],
    knownness: KnownnessIndex,
    config: FinalDiscoveryConfig,
    maximum_candidate_pairs: int,
) -> tuple[_PassStatistics, list[float], list[float]]:
    p_values: list[float] = []
    ablated_p_values: list[float] = []
    evidence_count = 0
    maximum_rows = 0
    stratum_counts: dict[str, int] = defaultdict(int)
    stratum_sizes: dict[str, int] = {}
    hypothesis_count = 0
    for draft, full_null, ablated_null in _draft_stream(
        evidence_path,
        full_null_path,
        ablated_null_path,
        passages=passages,
        knownness=knownness,
        config=config,
    ):
        p_values.append(draft.empirical_p_value)
        ablated_p_values.append(draft.english_ablation_empirical_p_value)
        row_count = len(draft.evidence)
        evidence_count += row_count
        maximum_rows = max(maximum_rows, row_count)
        stratum_counts[full_null.stratum] += 1
        prior_size = stratum_sizes.setdefault(full_null.stratum, full_null.stratum_size)
        if prior_size != full_null.stratum_size or (
            ablated_null.stratum != full_null.stratum
            or ablated_null.stratum_size != full_null.stratum_size
        ):
            raise DiskEnsembleError("full/ablated null stratum identities disagree")
        hypothesis_count = full_null.hypothesis_count
        if len(p_values) > maximum_candidate_pairs:
            raise DiskEnsembleError("candidate population exceeds the preregistered resource bound")
    pair_count = len(p_values)
    if pair_count < 1:
        raise DiskEnsembleError("candidate construction requires a nonempty population")
    if hypothesis_count != pair_count:
        raise DiskEnsembleError(
            f"null hypothesis count differs from population: {hypothesis_count} != {pair_count}"
        )
    if dict(stratum_counts) != stratum_sizes:
        raise DiskEnsembleError("declared null stratum sizes differ from observed counts")
    return (
        _PassStatistics(
            pair_count=pair_count,
            evidence_count=evidence_count,
            maximum_rows_per_pair=maximum_rows,
            stratum_counts=dict(stratum_counts),
            stratum_sizes=stratum_sizes,
            hypothesis_count=hypothesis_count,
        ),
        p_values,
        ablated_p_values,
    )


def _tier_state(
    evidence_path: Path,
    full_null_path: Path,
    ablated_null_path: Path,
    *,
    passages: Mapping[str, PassageRecord],
    knownness: KnownnessIndex,
    config: FinalDiscoveryConfig,
    q_values: Sequence[float],
    ablated_q_values: Sequence[float],
) -> tuple[bytearray, dict[str, int]]:
    tier_a = bytearray()
    tier_b_keys: list[tuple[tuple[float, str], str]] = []
    for index, (draft, _, _) in enumerate(
        _draft_stream(
            evidence_path,
            full_null_path,
            ablated_null_path,
            passages=passages,
            knownness=knownness,
            config=config,
        )
    ):
        provisional = _final_candidate_from_draft(
            draft,
            q_value=q_values[index],
            english_ablation_q_value=ablated_q_values[index],
            tier_b_rank=None,
            config=config,
        )
        tier_a.append(provisional.tier_a_eligible)
        if (
            not provisional.tier_a_eligible
            and draft.knownness_status == "unknown"
            and not draft.quality.basic_exclusion
        ):
            key = (-draft.ensemble_score, draft.pair_id)
            insort(tier_b_keys, (key, draft.pair_id))
            if len(tier_b_keys) > config.tiers.tier_b_size:
                tier_b_keys.pop()
    if len(tier_a) != len(q_values):
        raise DiskEnsembleError("second-pass candidate population changed")
    return tier_a, {pair_id: rank for rank, (_, pair_id) in enumerate(tier_b_keys, start=1)}


def _write_chunk(path: Path, rows: list[FinalCandidate]) -> None:
    rows.sort(key=lambda row: (-row.ensemble_score, row.candidate_pair_id))
    with path.open("xb") as handle:
        for row in rows:
            handle.write(_canonical_model_line(row))
        handle.flush()
        os.fsync(handle.fileno())


def _line_sort_key(line: bytes) -> tuple[float, str]:
    try:
        value = json.loads(line)
        score = float(value["ensemble_score"])
        pair_id = str(value["candidate_pair_id"])
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise DiskEnsembleError("candidate sort chunk contains an invalid row") from exc
    if not math.isfinite(score) or not pair_id:
        raise DiskEnsembleError("candidate sort chunk contains an invalid key")
    return -score, pair_id


def _merge_chunks(chunk_paths: Sequence[Path], output_path: Path) -> tuple[int, str]:
    if output_path.exists():
        raise DiskEnsembleError(f"refusing to replace candidate output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    count = 0
    prior_key: tuple[float, str] | None = None
    try:
        with ExitStack() as stack:
            handles = [stack.enter_context(path.open("rb")) for path in chunk_paths]
            heap: list[tuple[float, str, int, bytes]] = []
            for index, handle in enumerate(handles):
                line = handle.readline()
                if line:
                    key = _line_sort_key(line)
                    heapq.heappush(heap, (*key, index, line))
            with temporary.open("xb") as output:
                while heap:
                    negative_score, pair_id, index, line = heapq.heappop(heap)
                    key = (negative_score, pair_id)
                    if prior_key is not None and key <= prior_key:
                        raise DiskEnsembleError(
                            "externally sorted candidates are duplicate or out of order"
                        )
                    if not line.endswith(b"\n"):
                        raise DiskEnsembleError("candidate sort chunk lacks a final LF")
                    output.write(line)
                    count += 1
                    prior_key = key
                    next_line = handles[index].readline()
                    if next_line:
                        next_key = _line_sort_key(next_line)
                        heapq.heappush(heap, (*next_key, index, next_line))
                output.flush()
                os.fsync(output.fileno())
        temporary.replace(output_path)
    except Exception:
        # Staging/chunks are deliberately preserved for post-failure diagnosis.
        raise
    return count, sha256_file(output_path)


def build_final_candidates_disk_backed(
    evidence_path: Path,
    full_null_path: Path,
    ablated_null_path: Path,
    output_path: Path,
    *,
    work_directory: Path,
    passages: Mapping[str, PassageRecord],
    knownness: KnownnessIndex,
    config: FinalDiscoveryConfig,
    maximum_candidate_pairs: int,
    chunk_size: int = 10_000,
) -> DiskEnsembleReceipt:
    """Build exact global-BH candidates in bounded memory using three passes."""

    if maximum_candidate_pairs < 1 or chunk_size < 1:
        raise DiskEnsembleError("resource bounds and chunk size must be positive")
    if output_path.exists():
        raise DiskEnsembleError(f"refusing to replace candidate output: {output_path}")
    if work_directory.exists() and (not work_directory.is_dir() or any(work_directory.iterdir())):
        raise DiskEnsembleError("disk-ensemble work directory must be new or empty")
    work_directory.mkdir(parents=True, exist_ok=True)
    chunks_root = work_directory / "candidate-sort-chunks"
    chunks_root.mkdir()

    statistics, p_values, ablated_p_values = _first_pass(
        evidence_path,
        full_null_path,
        ablated_null_path,
        passages=passages,
        knownness=knownness,
        config=config,
        maximum_candidate_pairs=maximum_candidate_pairs,
    )
    q_values = benjamini_hochberg(p_values)
    ablated_q_values = benjamini_hochberg(ablated_p_values)
    del p_values, ablated_p_values
    tier_a, tier_b_ranks = _tier_state(
        evidence_path,
        full_null_path,
        ablated_null_path,
        passages=passages,
        knownness=knownness,
        config=config,
        q_values=q_values,
        ablated_q_values=ablated_q_values,
    )

    buffer: list[FinalCandidate] = []
    chunk_paths: list[Path] = []
    tier_a_count = 0
    for index, (draft, _, _) in enumerate(
        _draft_stream(
            evidence_path,
            full_null_path,
            ablated_null_path,
            passages=passages,
            knownness=knownness,
            config=config,
        )
    ):
        candidate = _final_candidate_from_draft(
            draft,
            q_value=q_values[index],
            english_ablation_q_value=ablated_q_values[index],
            tier_b_rank=tier_b_ranks.get(draft.pair_id),
            config=config,
        )
        if candidate.tier_a_eligible != bool(tier_a[index]):
            raise DiskEnsembleError("candidate Tier A state changed between passes")
        tier_a_count += candidate.tier_a_eligible
        buffer.append(candidate)
        if len(buffer) >= chunk_size:
            chunk_path = chunks_root / f"chunk-{len(chunk_paths):06d}.jsonl"
            _write_chunk(chunk_path, buffer)
            chunk_paths.append(chunk_path)
            buffer = []
    if buffer:
        chunk_path = chunks_root / f"chunk-{len(chunk_paths):06d}.jsonl"
        _write_chunk(chunk_path, buffer)
        chunk_paths.append(chunk_path)
    if not chunk_paths:
        raise DiskEnsembleError("candidate construction emitted no sort chunks")
    output_count, output_sha256 = _merge_chunks(chunk_paths, output_path)
    if output_count != statistics.pair_count:
        raise DiskEnsembleError("candidate output count changed during external sort")
    return DiskEnsembleReceipt(
        candidate_pair_count=statistics.pair_count,
        evidence_row_count=statistics.evidence_count,
        maximum_candidate_pair_count=maximum_candidate_pairs,
        maximum_evidence_rows_per_pair=statistics.maximum_rows_per_pair,
        tier_a_count=tier_a_count,
        tier_b_count=len(tier_b_ranks),
        chunk_size=chunk_size,
        chunk_count=len(chunk_paths),
        output_file_name=output_path.name,
        output_size=output_path.stat().st_size,
        output_sha256=output_sha256,
    )


__all__ = [
    "DiskEnsembleError",
    "DiskEnsembleReceipt",
    "build_final_candidates_disk_backed",
]
