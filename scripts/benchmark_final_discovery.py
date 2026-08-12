"""Text-free, bounded scale benchmark for the final-discovery disk pipeline."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby, islice
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from pydantic import BaseModel

from echoes.final_discovery.compact_nulls import (
    CompactGroupScoreRow,
    calibrate_compact_ensemble_nulls,
    write_compact_group_scores,
)
from echoes.final_discovery.config import (
    DEFAULT_FINAL_DISCOVERY_CONFIG,
    FinalDiscoveryConfig,
    final_discovery_config_sha256,
    load_final_discovery_config,
)
from echoes.final_discovery.disk_calibration import (
    PairStratum,
    calibrate_detector_evidence_disk_backed,
)
from echoes.final_discovery.disk_ensemble import build_final_candidates_disk_backed
from echoes.final_discovery.evidence_index import (
    EvidenceOffsetLookup,
    build_evidence_offset_index,
)
from echoes.final_discovery.features import candidate_pair_id, canonical_json
from echoes.final_discovery.knownness import KnownnessIndex
from echoes.final_discovery.models import (
    EvidenceRow,
    FinalCandidate,
    PassageRecord,
    RawEvidence,
)
from echoes.final_discovery.nulls import _vectorized_detector_exceedances
from echoes.final_discovery.scale import (
    EXPECTED_PRIMARY_PASSAGE_COUNT,
    campaign_scale_contract,
)
from echoes.final_discovery.storage import (
    iter_canonical_jsonl,
    sha256_file,
    write_json_atomic_new,
    write_jsonl_stream_atomic,
)

TARGET_PRODUCTION_PAIRS = 2_592_480
TARGET_PRODUCTION_ITERATIONS = 1_000
TARGET_PRODUCTION_EVIDENCE_ROWS = 11_718_699
CAMPAIGN_RUNTIME_LIMIT_SECONDS = 96 * 60 * 60
CAMPAIGN_PROCESS_MEMORY_LIMIT_BYTES = 56 * 1024**3
INITIAL_FREE_DISK_BYTES = 280 * 1024**3
MINIMUM_FREE_DISK_FLOOR_BYTES = 80 * 1024**3
CANONICAL_M7_BYTES_ESTIMATE = math.ceil(17.149 * 1024**3)
KERNEL_BENCHMARK_ITERATIONS = 1_000
UNBENCHMARKED_RESERVE_SECONDS = {
    "representations_and_detector_feature_extraction": 16 * 60 * 60,
    "b2_materialization_upload_and_verification": 8 * 60 * 60,
    "strict_validation_packaging_and_review_artifacts": 8 * 60 * 60,
}
SYNTHETIC_SEED = 81_191
SYNTHETIC_TRACE_PADDING_BYTES = 2_048
DETECTOR_IDS = (
    "grammar_rare_pattern",
    "grammar_sequence_alignment",
    "lemma_root_sequence_semantic",
    "m7_lexical_rrf",
    "multilingual_e5_english_gloss",
    "multilingual_e5_original_language",
    "participant_frame_progression",
    "semantic_domain_overlap",
    "stratified_representation_anomaly",
)

REQUIRED_ACCEPTANCE_GATE_PATHS = (
    ("runtime", ("production_extrapolation", "resource_gate", "runtime", "status")),
    ("memory", ("production_extrapolation", "resource_gate", "memory", "status")),
    ("disk", ("production_extrapolation", "resource_gate", "disk", "status")),
    ("hard_cardinality", ("hard_cardinality_contract", "status")),
)

PROFILE_DEFAULTS = {
    "quick": {
        "pairs": 10_000,
        "iterations": 20,
        "calibration_pairs": 64,
        "strata": 8,
        "lookup_count": 32,
        "candidate_chunk_size": 16,
        "kernel_sample_size": 10_000,
    },
    "scale-gate": {
        "pairs": 250_000,
        "iterations": 100,
        "calibration_pairs": 512,
        "strata": 32,
        "lookup_count": 256,
        "candidate_chunk_size": 128,
        "kernel_sample_size": 100_000,
    },
}


class BenchmarkError(RuntimeError):
    """Raised when a measured population or resource contract differs."""


@dataclass(frozen=True, slots=True)
class SyntheticPair:
    candidate_pair_id: str
    passage_a_id: str
    passage_b_id: str
    stratum: str
    source_index: int


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded, synthetic-only Project Echoes disk-pipeline benchmark."
    )
    parser.add_argument(
        "--scale-gate",
        action="store_true",
        help="Use the 250k-pair / 100-iteration scale-gate defaults.",
    )
    parser.add_argument("--pairs", type=_positive_int, help="Compact-null candidate pairs.")
    parser.add_argument("--iterations", type=_positive_int, help="Null iterations.")
    parser.add_argument(
        "--calibration-pairs",
        type=_positive_int,
        help="Representative pairs for raw evidence, detector calibration, and ensemble.",
    )
    parser.add_argument("--strata", type=_positive_int, help="Synthetic confounder strata.")
    parser.add_argument(
        "--lookup-count",
        type=_positive_int,
        help="Candidate-to-evidence offset-index lookups.",
    )
    parser.add_argument(
        "--candidate-chunk-size",
        type=_positive_int,
        help="Rows per disk-ensemble external-sort chunk.",
    )
    parser.add_argument(
        "--kernel-sample-size",
        type=_positive_int,
        help="Scores per direct 1,000-iteration detector-null kernel timing.",
    )
    parser.add_argument(
        "--duckdb-memory-mib",
        type=_positive_int,
        default=512,
        help="DuckDB memory limit in MiB (minimum 256).",
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Retain the newly created benchmark work directory.",
    )
    return parser.parse_args(argv)


def _resolved_parameters(args: argparse.Namespace) -> dict[str, int | str | bool]:
    profile = "scale-gate" if args.scale_gate else "quick"
    defaults = PROFILE_DEFAULTS[profile]
    parameters: dict[str, int | str | bool] = {
        "profile": profile,
        "compact_pair_count": args.pairs or defaults["pairs"],
        "null_iterations": args.iterations or defaults["iterations"],
        "calibration_pair_count": args.calibration_pairs or defaults["calibration_pairs"],
        "stratum_count": args.strata or defaults["strata"],
        "lookup_count": args.lookup_count or defaults["lookup_count"],
        "candidate_chunk_size": args.candidate_chunk_size or defaults["candidate_chunk_size"],
        "kernel_sample_size": args.kernel_sample_size or defaults["kernel_sample_size"],
        "duckdb_memory_limit_bytes": args.duckdb_memory_mib * 1024**2,
        "detector_count": len(DETECTOR_IDS),
        "synthetic_seed": SYNTHETIC_SEED,
        "synthetic_trace_padding_bytes": SYNTHETIC_TRACE_PADDING_BYTES,
        "keep_work": bool(args.keep_work),
    }
    if int(parameters["duckdb_memory_limit_bytes"]) < 256 * 1024**2:
        raise BenchmarkError("DuckDB benchmark memory must be at least 256 MiB")
    if int(parameters["calibration_pair_count"]) > int(parameters["compact_pair_count"]):
        raise BenchmarkError("calibration-pairs cannot exceed the compact pair population")
    if int(parameters["kernel_sample_size"]) < 2:
        raise BenchmarkError("kernel-sample-size must be at least 2")
    if int(parameters["lookup_count"]) > int(parameters["calibration_pair_count"]):
        raise BenchmarkError("lookup-count cannot exceed calibration-pairs")
    return parameters


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _windows_memory() -> tuple[int | None, int | None]:
    if platform.system() != "Windows":
        return None, None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.GetCurrentProcess()
    succeeded = psapi.GetProcessMemoryInfo(
        handle,
        ctypes.byref(counters),
        counters.cb,
    )
    if not succeeded:
        return None, None
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def _proc_memory() -> tuple[int | None, int | None]:
    status = Path("/proc/self/status")
    if not status.is_file():
        return None, None
    values: dict[str, int] = {}
    try:
        for line in status.read_text(encoding="ascii").splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                name, raw_value, unit = line.split()
                if unit != "kB":
                    continue
                values[name.rstrip(":")] = int(raw_value) * 1024
    except (OSError, UnicodeError, ValueError):
        return None, None
    return values.get("VmRSS"), values.get("VmHWM")


def _resource_peak_memory() -> int | None:
    try:
        import resource

        resource_api: Any = resource
        value = int(resource_api.getrusage(resource_api.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, ImportError, OSError, ValueError):
        return None
    return value if platform.system() == "Darwin" else value * 1024


def _memory_snapshot() -> dict[str, int | str | None]:
    current, peak = _windows_memory()
    source = "windows_process_memory_counters"
    if peak is None:
        current, peak = _proc_memory()
        source = "linux_proc_status"
    if peak is None:
        peak = _resource_peak_memory()
        current = None
        source = "resource_getrusage_peak_only" if peak is not None else "unavailable"
    _, traced_peak = tracemalloc.get_traced_memory()
    return {
        "source": source,
        "current_rss_bytes": current,
        "peak_rss_bytes": peak,
        "python_tracemalloc_peak_bytes": traced_peak,
    }


def _nested_value(document: Mapping[str, Any], path: Sequence[str]) -> object:
    current: object = document
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _failed_acceptance_gates(report: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        name
        for name, path in REQUIRED_ACCEPTANCE_GATE_PATHS
        if _nested_value(report, path) != "pass"
    )


def _write_gate_checked_report(output_path: Path, report: dict[str, Any]) -> None:
    observed_statuses = {
        name: _nested_value(report, path) for name, path in REQUIRED_ACCEPTANCE_GATE_PATHS
    }
    failed_gates = _failed_acceptance_gates(report)
    report["acceptance_gate"] = {
        "status": "pass" if not failed_gates else "fail",
        "required_gates": [name for name, _path in REQUIRED_ACCEPTANCE_GATE_PATHS],
        "observed_statuses": observed_statuses,
        "failed_gates": list(failed_gates),
    }
    write_json_atomic_new(output_path, report)
    if failed_gates:
        raise BenchmarkError("benchmark acceptance gates failed closed: " + ", ".join(failed_gates))


def _timed_stage(
    name: str,
    stages: dict[str, dict[str, Any]],
    work_dir: Path,
    action: Callable[[], Any],
    *,
    rows: int | None = None,
) -> Any:
    started = time.perf_counter()
    result = action()
    elapsed = time.perf_counter() - started
    measurement: dict[str, Any] = {
        "elapsed_seconds": elapsed,
        "work_directory_bytes_after": _directory_size(work_dir),
        "memory_after": _memory_snapshot(),
    }
    if rows is not None:
        measurement["row_count"] = rows
        measurement["rows_per_second"] = rows / elapsed if elapsed else None
    stages[name] = measurement
    return result


def _compact_rows(
    pair_count: int,
    stratum_count: int,
    config: FinalDiscoveryConfig,
) -> Iterator[CompactGroupScoreRow]:
    group_count = len(config.ensemble.group_weights)
    for index in range(pair_count):
        full = tuple(
            ((index * (group_index + 3) * 37 + group_index * 101) % 1_001) / 1_000
            for group_index in range(group_count)
        )
        ablated = tuple(
            score * (0.65 if group_id == "english_bridge" else 1.0)
            for group_id, score in zip(config.ensemble.group_weights, full, strict=True)
        )
        yield CompactGroupScoreRow(
            candidate_pair_id=f"BENCHPAIR~{index:012d}",
            stratum=f"stratum-{index % stratum_count:04d}",
            full_scores=full,
            remove_all_english_scores=ablated,
        )


def _sample_pairs(pair_count: int, stratum_count: int) -> list[SyntheticPair]:
    pairs = [
        SyntheticPair(
            candidate_pair_id=candidate_pair_id(f"BENCH-A-{index:08d}", f"BENCH-B-{index:08d}"),
            passage_a_id=f"BENCH-A-{index:08d}",
            passage_b_id=f"BENCH-B-{index:08d}",
            stratum=f"stratum-{index % stratum_count:04d}",
            source_index=index,
        )
        for index in range(pair_count)
    ]
    pairs.sort(key=lambda pair: pair.candidate_pair_id)
    return pairs


def _passage(passage_id: str, index: int, side: str) -> PassageRecord:
    marker = f"m-{index % 97}"
    return PassageRecord(
        passage_id=passage_id,
        reference=f"BENCH {index}:{side}",
        corpus="hebrew",
        book=f"B{index % 12:02d}",
        genre=("narrative", "poetry", "discourse")[index % 3],
        analysis_profile="edition_complete",
        analysis_reading="qere",
        granularity="verse",
        token_count=1,
        token_ids=(f"{passage_id}-t0",),
        original_text="_",
        normalized_text="_",
        lemma_sequence=(marker,),
        root_sequence=(marker,),
        pos_sequence=("NOUN",),
        morphology_sequence=("synthetic",),
        semantic_domains=(f"d-{index % 23}",),
        entities=(None,),
        participants=(None,),
        frames=(None,),
        formulaic_language=(index % 101 == 0),
        source_digest=hashlib.sha256(passage_id.encode("ascii")).hexdigest(),
    )


def _passage_index(pairs: Sequence[SyntheticPair]) -> dict[str, PassageRecord]:
    passages: dict[str, PassageRecord] = {}
    for pair in pairs:
        passages[pair.passage_a_id] = _passage(pair.passage_a_id, pair.source_index, "a")
        passages[pair.passage_b_id] = _passage(pair.passage_b_id, pair.source_index, "b")
    return passages


def _raw_evidence_rows(
    pairs: Sequence[SyntheticPair], config: FinalDiscoveryConfig
) -> Iterator[RawEvidence]:
    registrations = {item.detector_id: item for item in config.detectors}
    for pair in pairs:
        for detector_index, detector_id in enumerate(DETECTOR_IDS):
            registration = registrations[detector_id]
            score = (
                (pair.source_index * (detector_index + 11) * 29 + detector_index * 43) % 1_001
            ) / 1_000
            contains_english = registration.contains_english_derived_evidence
            trace: dict[str, object] = {
                "benchmark_synthetic_only": True,
                "detector_id": detector_id,
            }
            if detector_id == "m7_lexical_rrf":
                trace["m7_both_null_families_present"] = True
            trace.update(
                {
                    "candidate_ordinal": pair.source_index,
                    "component_scores": {
                        "primary": score,
                        "secondary": score * 0.875,
                        "diagnostic": score * 0.625,
                    },
                    "synthetic_capacity_padding": "x" * SYNTHETIC_TRACE_PADDING_BYTES,
                    "synthetic_lineage_sha256": hashlib.sha256(
                        f"{pair.candidate_pair_id}:{detector_id}".encode("ascii")
                    ).hexdigest(),
                }
            )
            yield RawEvidence(
                candidate_pair_id=pair.candidate_pair_id,
                passage_a_id=pair.passage_a_id,
                passage_b_id=pair.passage_b_id,
                detector_id=detector_id,
                family=registration.family,
                independence_group=registration.independence_group,
                raw_score=score,
                contains_english_derived_evidence=contains_english,
                english_ablation_raw_score=(
                    score * 0.8
                    if contains_english and registration.original_language_capable
                    else 0.0
                    if contains_english
                    else None
                ),
                original_language_evidence_remains=registration.original_language_capable,
                counts_for_independence=registration.counts_for_independence,
                trace_json=canonical_json(trace),
                source_artifact_id=f"synthetic-{detector_id}",
                source_artifact_sha256=hashlib.sha256(detector_id.encode("ascii")).hexdigest(),
            )


def _evidence_group_rows(
    evidence_path: Path,
    strata_by_pair: Mapping[str, str],
    config: FinalDiscoveryConfig,
) -> Iterator[CompactGroupScoreRow]:
    groups = tuple(config.ensemble.group_weights)
    indexes = {group: index for index, group in enumerate(groups)}
    missing = config.ensemble.missing_group_score
    for pair_id, rows in groupby(
        iter_canonical_jsonl(evidence_path, EvidenceRow),
        key=lambda row: row.candidate_pair_id,
    ):
        full = [missing] * len(groups)
        ablated = [missing] * len(groups)
        for row in rows:
            index = indexes[row.independence_group]
            full[index] = max(full[index], row.normalized_score)
            if row.contains_english_derived_evidence:
                if row.english_ablation_normalized_score is not None:
                    ablated[index] = max(ablated[index], row.english_ablation_normalized_score)
            else:
                ablated[index] = max(ablated[index], row.normalized_score)
        yield CompactGroupScoreRow(
            candidate_pair_id=pair_id,
            stratum=strata_by_pair[pair_id],
            full_scores=tuple(full),
            remove_all_english_scores=tuple(ablated),
        )


def _benchmark_detector_null_kernels(
    sample_size: int,
    config: FinalDiscoveryConfig,
) -> dict[str, dict[str, float | int | str]]:
    observed = np.arange(sample_size, dtype=np.float64) / max(sample_size, 1)
    results: dict[str, dict[str, float | int | str]] = {}
    for label, null_family in (
        ("permutation_like", "stratified_permutation"),
        ("bootstrap", "stratified_score_bootstrap"),
    ):
        seed = config.calibration.seeds[null_family]
        started = time.perf_counter()
        exceedances = _vectorized_detector_exceedances(
            observed,
            null_family=null_family,
            iterations=KERNEL_BENCHMARK_ITERATIONS,
            random_source=np.random.default_rng(seed),
        )
        elapsed = time.perf_counter() - started
        if (
            len(exceedances) != sample_size
            or np.any(exceedances < 0)
            or np.any(exceedances > KERNEL_BENCHMARK_ITERATIONS)
        ):
            raise BenchmarkError(f"{label} kernel emitted invalid exceedance counts")
        cells = sample_size * KERNEL_BENCHMARK_ITERATIONS
        results[label] = {
            "null_family": null_family,
            "seed": seed,
            "sample_score_count": sample_size,
            "iterations": KERNEL_BENCHMARK_ITERATIONS,
            "cells": cells,
            "elapsed_seconds": elapsed,
            "cells_per_second": cells / elapsed,
        }
    return results


def _assert_equal(label: str, observed: int, expected: int) -> None:
    if observed != expected:
        raise BenchmarkError(f"{label} cardinality is {observed}; expected {expected}")


def _raw_evidence_order_key(row: BaseModel) -> tuple[str, ...]:
    payload = row.model_dump()
    return str(payload["candidate_pair_id"]), str(payload["detector_id"])


def _candidate_pair_order_key(row: BaseModel) -> tuple[str, ...]:
    return (str(row.model_dump()["candidate_pair_id"]),)


def _git_identity(project_root: Path) -> dict[str, Any]:
    def run(*arguments: str) -> str | None:
        try:
            completed = subprocess.run(
                ("git", *arguments),
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return completed.stdout.strip()

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "dirty": None if status is None else bool(status),
    }


def _module_hash(project_root: Path, relative: str) -> str:
    return sha256_file(project_root / relative)


def _linear_extrapolation(
    measured_seconds: float,
    *,
    measured_units: int,
    target_units: int,
    measured_iterations: int | None,
    safety_factor: float,
) -> float:
    unit_factor = target_units / measured_units
    iteration_factor = (
        TARGET_PRODUCTION_ITERATIONS / measured_iterations
        if measured_iterations is not None
        else 1.0
    )
    return measured_seconds * unit_factor * iteration_factor * safety_factor


def _run_benchmark(
    parameters: Mapping[str, int | str | bool],
    work_dir: Path,
    project_root: Path,
) -> dict[str, Any]:
    pair_count = int(parameters["compact_pair_count"])
    iterations = int(parameters["null_iterations"])
    calibration_pairs = int(parameters["calibration_pair_count"])
    stratum_count = int(parameters["stratum_count"])
    lookup_count = int(parameters["lookup_count"])
    detector_count = len(DETECTOR_IDS)
    memory_limit = int(parameters["duckdb_memory_limit_bytes"])
    chunk_size = int(parameters["candidate_chunk_size"])
    kernel_sample_size = int(parameters["kernel_sample_size"])
    base_config = load_final_discovery_config(project_root / DEFAULT_FINAL_DISCOVERY_CONFIG)
    benchmark_config = base_config.model_copy(
        update={
            "calibration": base_config.calibration.model_copy(
                update={"production_iterations": iterations}
            )
        }
    )
    registered_detector_ids = tuple(
        sorted(registration.detector_id for registration in benchmark_config.detectors)
    )
    if registered_detector_ids != DETECTOR_IDS:
        raise BenchmarkError(
            "benchmark detector inventory differs from the frozen registration: "
            f"{registered_detector_ids} != {DETECTOR_IDS}"
        )
    scale_contract = campaign_scale_contract(
        benchmark_config,
        primary_passage_count=EXPECTED_PRIMARY_PASSAGE_COUNT,
    )
    if (
        scale_contract.maximum_retained_candidate_pairs != TARGET_PRODUCTION_PAIRS
        or scale_contract.maximum_total_raw_evidence_rows != TARGET_PRODUCTION_EVIDENCE_ROWS
    ):
        raise BenchmarkError("frozen campaign scale caps differ from benchmark constants")
    stages: dict[str, dict[str, Any]] = {}
    maximum_work_bytes = 0

    def update_peak_work() -> None:
        nonlocal maximum_work_bytes
        maximum_work_bytes = max(maximum_work_bytes, _directory_size(work_dir))

    compact_dataset = _timed_stage(
        "compact_group_score_build",
        stages,
        work_dir,
        lambda: write_compact_group_scores(
            _compact_rows(pair_count, stratum_count, benchmark_config),
            work_dir / "compact-group-scores",
            group_ids=tuple(benchmark_config.ensemble.group_weights),
            missing_group_score=benchmark_config.ensemble.missing_group_score,
        ),
        rows=pair_count,
    )
    update_peak_work()
    _assert_equal("compact group-score pairs", compact_dataset.receipt.pair_count, pair_count)
    stages["compact_group_score_build"].update(
        {
            "persistent_bytes": compact_dataset.receipt.persistent_bytes,
            "bytes_per_pair": compact_dataset.receipt.persistent_bytes / pair_count,
        }
    )

    compact_null = _timed_stage(
        "compact_null_both_scopes",
        stages,
        work_dir,
        lambda: calibrate_compact_ensemble_nulls(
            compact_dataset,
            work_dir / "compact-null",
            config=benchmark_config,
            iterations=iterations,
            seed=benchmark_config.calibration.seeds["stratified_permutation"],
        ),
        rows=pair_count * 2,
    )
    update_peak_work()
    _assert_equal("compact null pairs", compact_null.receipt.pair_count, pair_count)
    _assert_equal("compact null iterations", compact_null.receipt.iterations, iterations)
    emitted_by_scope: dict[str, int] = {}
    for scope in ("full", "remove_all_english"):
        emitted = sum(1 for _ in compact_null.iter_rows(scope))
        _assert_equal(f"compact {scope} rows", emitted, pair_count)
        emitted_by_scope[scope] = emitted
    stages["compact_null_both_scopes"].update(
        {
            "persistent_bytes": compact_null.receipt.persistent_bytes,
            "bytes_per_pair_both_scopes": compact_null.receipt.persistent_bytes / pair_count,
            "emitted_rows_by_scope": emitted_by_scope,
            "resource_bounds": compact_null.receipt.resource_bounds.model_dump(mode="json"),
        }
    )

    kernel_measurements = _timed_stage(
        "direct_detector_null_kernels",
        stages,
        work_dir,
        lambda: _benchmark_detector_null_kernels(kernel_sample_size, benchmark_config),
    )
    stages["direct_detector_null_kernels"].update(
        {
            "sample_score_count_per_family": kernel_sample_size,
            "iterations": KERNEL_BENCHMARK_ITERATIONS,
            "families": kernel_measurements,
            "output_rows_retained": 0,
        }
    )

    synthetic_pairs = _timed_stage(
        "calibration_pair_identity_build",
        stages,
        work_dir,
        lambda: _sample_pairs(calibration_pairs, stratum_count),
        rows=calibration_pairs,
    )
    passages = _timed_stage(
        "synthetic_passage_index_build",
        stages,
        work_dir,
        lambda: _passage_index(synthetic_pairs),
        rows=calibration_pairs * 2,
    )
    _assert_equal("synthetic passage index", len(passages), calibration_pairs * 2)
    strata_by_pair = {pair.candidate_pair_id: pair.stratum for pair in synthetic_pairs}

    raw_path = work_dir / "raw-evidence.jsonl"
    raw_rows = calibration_pairs * detector_count
    raw_write_receipt = _timed_stage(
        "canonical_raw_evidence_stream",
        stages,
        work_dir,
        lambda: write_jsonl_stream_atomic(
            raw_path,
            _raw_evidence_rows(synthetic_pairs, benchmark_config),
            order_key=_raw_evidence_order_key,
        ),
        rows=raw_rows,
    )
    update_peak_work()
    _assert_equal("raw evidence rows", raw_write_receipt.row_count, raw_rows)
    stages["canonical_raw_evidence_stream"].update(
        {
            "persistent_bytes": raw_write_receipt.size_bytes,
            "bytes_per_evidence_row": raw_write_receipt.size_bytes / raw_rows,
            "sha256": raw_write_receipt.sha256,
        }
    )

    disk_calibration = _timed_stage(
        "disk_detector_calibration_sample",
        stages,
        work_dir,
        lambda: calibrate_detector_evidence_disk_backed(
            (raw_path,),
            (
                PairStratum(candidate_pair_id=pair.candidate_pair_id, stratum=pair.stratum)
                for pair in synthetic_pairs
            ),
            work_dir / "disk-detector-calibration",
            config=benchmark_config,
            iterations=iterations,
            memory_limit_bytes=memory_limit,
            temp_directory=work_dir / "duckdb-temp",
            threads=1,
            batch_size=8_192,
        ),
        rows=raw_rows,
    )
    update_peak_work()
    _assert_equal(
        "disk calibration evidence rows",
        disk_calibration.receipt.raw_evidence_row_count,
        raw_rows,
    )
    _assert_equal(
        "disk calibration pair population",
        disk_calibration.receipt.candidate_pair_count,
        calibration_pairs,
    )
    calibration_bytes = sum(
        item.size_bytes for item in disk_calibration.receipt.output_files.values()
    )
    stages["disk_detector_calibration_sample"].update(
        {
            "persistent_bytes_excluding_receipt": calibration_bytes,
            "bytes_per_evidence_row": calibration_bytes / raw_rows,
            "sample_is_separate_from_250k_compact_gate": True,
        }
    )

    index_path = work_dir / "evidence-offset-index.sqlite3"
    evidence_index_receipt = _timed_stage(
        "review_evidence_offset_index_build",
        stages,
        work_dir,
        lambda: build_evidence_offset_index(
            disk_calibration.evidence_path,
            index_path,
            expected_source_sha256=(disk_calibration.receipt.output_files["evidence.jsonl"].sha256),
            expected_evidence_row_count=raw_rows,
            expected_maximum_rows_per_pair=detector_count,
        ),
        rows=raw_rows,
    )
    update_peak_work()
    _assert_equal(
        "evidence offset-index pairs",
        evidence_index_receipt.candidate_pair_count,
        calibration_pairs,
    )
    stages["review_evidence_offset_index_build"].update(
        {
            "persistent_bytes": index_path.stat().st_size,
            "bytes_per_candidate_pair": index_path.stat().st_size / calibration_pairs,
            "payload_bytes_copied_into_index": 0,
        }
    )

    ensemble_scores = _timed_stage(
        "disk_ensemble_group_score_projection",
        stages,
        work_dir,
        lambda: write_compact_group_scores(
            _evidence_group_rows(
                disk_calibration.evidence_path,
                strata_by_pair,
                benchmark_config,
            ),
            work_dir / "ensemble-group-scores",
            group_ids=tuple(benchmark_config.ensemble.group_weights),
            missing_group_score=benchmark_config.ensemble.missing_group_score,
        ),
        rows=calibration_pairs,
    )
    _assert_equal(
        "ensemble group-score pairs", ensemble_scores.receipt.pair_count, calibration_pairs
    )
    ensemble_null = _timed_stage(
        "disk_ensemble_compact_null_sample",
        stages,
        work_dir,
        lambda: calibrate_compact_ensemble_nulls(
            ensemble_scores,
            work_dir / "ensemble-null",
            config=benchmark_config,
            iterations=iterations,
            seed=benchmark_config.calibration.seeds["stratified_permutation"],
        ),
        rows=calibration_pairs * 2,
    )
    full_null_path = work_dir / "ensemble-null-full.jsonl"
    ablated_null_path = work_dir / "ensemble-null-ablated.jsonl"
    full_null_receipt = write_jsonl_stream_atomic(
        full_null_path,
        ensemble_null.iter_rows("full"),
        order_key=_candidate_pair_order_key,
    )
    ablated_null_receipt = write_jsonl_stream_atomic(
        ablated_null_path,
        ensemble_null.iter_rows("remove_all_english"),
        order_key=_candidate_pair_order_key,
    )
    _assert_equal("full ensemble-null rows", full_null_receipt.row_count, calibration_pairs)
    _assert_equal("ablated ensemble-null rows", ablated_null_receipt.row_count, calibration_pairs)
    stages["disk_ensemble_compact_null_sample"].update(
        {
            "serialized_null_bytes": (
                full_null_receipt.size_bytes + ablated_null_receipt.size_bytes
            ),
            "serialized_bytes_per_pair_both_scopes": (
                full_null_receipt.size_bytes + ablated_null_receipt.size_bytes
            )
            / calibration_pairs,
        }
    )

    candidates_path = work_dir / "final-candidates.jsonl"
    disk_ensemble_receipt = _timed_stage(
        "disk_ensemble_candidate_build",
        stages,
        work_dir,
        lambda: build_final_candidates_disk_backed(
            disk_calibration.evidence_path,
            full_null_path,
            ablated_null_path,
            candidates_path,
            work_directory=work_dir / "disk-ensemble-work",
            passages=passages,
            knownness=KnownnessIndex(()),
            config=benchmark_config,
            maximum_candidate_pairs=calibration_pairs,
            chunk_size=min(chunk_size, calibration_pairs),
        ),
        rows=calibration_pairs,
    )
    update_peak_work()
    _assert_equal(
        "disk ensemble candidate rows",
        disk_ensemble_receipt.candidate_pair_count,
        calibration_pairs,
    )
    candidate_output_bytes = candidates_path.stat().st_size
    candidate_sort_chunk_bytes = _directory_size(
        work_dir / "disk-ensemble-work" / "candidate-sort-chunks"
    )
    stages["disk_ensemble_candidate_build"].update(
        {
            "candidate_output_bytes": candidate_output_bytes,
            "candidate_sort_chunk_bytes": candidate_sort_chunk_bytes,
            "persistent_bytes": candidate_output_bytes + candidate_sort_chunk_bytes,
            "bytes_per_candidate_including_sort_chunks": (
                candidate_output_bytes + candidate_sort_chunk_bytes
            )
            / calibration_pairs,
            "chunk_count": disk_ensemble_receipt.chunk_count,
            "tier_a_count": disk_ensemble_receipt.tier_a_count,
            "tier_b_count": disk_ensemble_receipt.tier_b_count,
        }
    )

    def perform_lookups() -> tuple[int, int]:
        count = 0
        evidence_count = 0
        with EvidenceOffsetLookup(
            index_path,
            disk_calibration.evidence_path,
            verify_source_sha256=True,
        ) as lookup:
            for candidate in islice(
                iter_canonical_jsonl(candidates_path, FinalCandidate), lookup_count
            ):
                rows = lookup(candidate)
                count += 1
                evidence_count += len(rows)
        return count, evidence_count

    looked_up, looked_up_evidence = _timed_stage(
        "review_offset_lookup_sample",
        stages,
        work_dir,
        perform_lookups,
        rows=lookup_count,
    )
    _assert_equal("review lookup count", looked_up, lookup_count)
    _assert_equal("review lookup evidence rows", looked_up_evidence, lookup_count * detector_count)
    stages["review_offset_lookup_sample"].update(
        {
            "evidence_rows_returned": looked_up_evidence,
            "maximum_rows_retained_per_lookup": detector_count,
        }
    )
    update_peak_work()

    expected_contract = {
        "compact_group_score_pairs": pair_count,
        "compact_null_rows_per_scope": pair_count,
        "compact_null_scopes": 2,
        "null_iterations": iterations,
        "calibration_pairs": calibration_pairs,
        "raw_evidence_rows": raw_rows,
        "detectors_per_calibration_pair": detector_count,
        "calibrated_evidence_rows": raw_rows,
        "detector_null_rows": raw_rows,
        "evidence_index_pairs": calibration_pairs,
        "evidence_index_rows": raw_rows,
        "evidence_index_maximum_rows_per_pair": detector_count,
        "disk_ensemble_candidates": calibration_pairs,
        "disk_ensemble_evidence_rows": raw_rows,
        "disk_ensemble_maximum_evidence_rows_per_pair": detector_count,
        "review_offset_lookups": lookup_count,
    }
    observed_contract = {
        "compact_group_score_pairs": compact_dataset.receipt.pair_count,
        "compact_null_rows_per_scope": emitted_by_scope["full"],
        "compact_null_scopes": len(emitted_by_scope),
        "null_iterations": compact_null.receipt.iterations,
        "calibration_pairs": disk_calibration.receipt.candidate_pair_count,
        "raw_evidence_rows": raw_write_receipt.row_count,
        "detectors_per_calibration_pair": disk_calibration.receipt.detector_count,
        "calibrated_evidence_rows": disk_calibration.receipt.output_files[
            "evidence.jsonl"
        ].row_count,
        "detector_null_rows": disk_calibration.receipt.output_files[
            "detector-null-calibration.jsonl"
        ].row_count,
        "evidence_index_pairs": evidence_index_receipt.candidate_pair_count,
        "evidence_index_rows": evidence_index_receipt.evidence_row_count,
        "evidence_index_maximum_rows_per_pair": (evidence_index_receipt.maximum_rows_per_pair),
        "disk_ensemble_candidates": disk_ensemble_receipt.candidate_pair_count,
        "disk_ensemble_evidence_rows": disk_ensemble_receipt.evidence_row_count,
        "disk_ensemble_maximum_evidence_rows_per_pair": (
            disk_ensemble_receipt.maximum_evidence_rows_per_pair
        ),
        "review_offset_lookups": looked_up,
    }
    if observed_contract != expected_contract:
        raise BenchmarkError(
            f"hard cardinality contract differs: {observed_contract} != {expected_contract}"
        )

    safety_factor = 1.25
    compact_build_seconds = stages["compact_group_score_build"]["elapsed_seconds"]
    compact_null_seconds = stages["compact_null_both_scopes"]["elapsed_seconds"]
    raw_write_seconds = stages["canonical_raw_evidence_stream"]["elapsed_seconds"]
    detector_calibration_seconds = stages["disk_detector_calibration_sample"]["elapsed_seconds"]
    index_seconds = stages["review_evidence_offset_index_build"]["elapsed_seconds"]
    ensemble_build_seconds = stages["disk_ensemble_candidate_build"]["elapsed_seconds"]
    log_factor = math.log2(TARGET_PRODUCTION_PAIRS) / max(math.log2(calibration_pairs), 1.0)
    observed_detector_strata = disk_calibration.receipt.detector_stratum_count
    target_detector_strata = scale_contract.maximum_calibration_detector_strata
    calibration_row_io_upper_seconds = detector_calibration_seconds * (
        TARGET_PRODUCTION_EVIDENCE_ROWS / raw_rows
    )
    calibration_stratum_io_upper_seconds = detector_calibration_seconds * (
        target_detector_strata / observed_detector_strata
    )
    calibration_fixed_io_upper_seconds = (
        calibration_row_io_upper_seconds + calibration_stratum_io_upper_seconds
    ) * safety_factor
    permutation_kernel = kernel_measurements["permutation_like"]
    bootstrap_kernel = kernel_measurements["bootstrap"]
    permutation_kernel_log_factor = math.log2(TARGET_PRODUCTION_PAIRS) / math.log2(
        kernel_sample_size
    )
    permutation_kernel_seconds = (
        float(permutation_kernel["elapsed_seconds"])
        * (scale_contract.maximum_permutation_like_calibration_rows / kernel_sample_size)
        * permutation_kernel_log_factor
        * safety_factor
    )
    bootstrap_kernel_seconds = (
        float(bootstrap_kernel["elapsed_seconds"])
        * (scale_contract.maximum_bootstrap_calibration_rows / kernel_sample_size)
        * safety_factor
    )
    stages["disk_ensemble_group_score_projection"]["production_projection_role"] = (
        "integration_cross_check_not_an_additional_production_execution"
    )
    stages["disk_ensemble_compact_null_sample"]["production_projection_role"] = (
        "integration_cross_check_not_an_additional_production_execution"
    )
    time_extrapolations = {
        "compact_group_score_build_seconds": _linear_extrapolation(
            compact_build_seconds,
            measured_units=pair_count,
            target_units=TARGET_PRODUCTION_PAIRS,
            measured_iterations=None,
            safety_factor=safety_factor,
        ),
        "compact_null_both_scopes_seconds": _linear_extrapolation(
            compact_null_seconds,
            measured_units=pair_count,
            target_units=TARGET_PRODUCTION_PAIRS,
            measured_iterations=iterations,
            safety_factor=safety_factor,
        ),
        "raw_evidence_stream_seconds": _linear_extrapolation(
            raw_write_seconds,
            measured_units=raw_rows,
            target_units=TARGET_PRODUCTION_EVIDENCE_ROWS,
            measured_iterations=None,
            safety_factor=safety_factor,
        ),
        "detector_calibration_fixed_io_upper_seconds": (calibration_fixed_io_upper_seconds),
        "detector_calibration_permutation_kernel_seconds_n_log_n": (permutation_kernel_seconds),
        "detector_calibration_bootstrap_kernel_seconds": bootstrap_kernel_seconds,
        "evidence_offset_index_seconds": _linear_extrapolation(
            index_seconds,
            measured_units=calibration_pairs,
            target_units=TARGET_PRODUCTION_PAIRS,
            measured_iterations=None,
            safety_factor=safety_factor,
        ),
        "disk_ensemble_candidate_build_seconds_n_log_n": (
            _linear_extrapolation(
                ensemble_build_seconds,
                measured_units=calibration_pairs,
                target_units=TARGET_PRODUCTION_PAIRS,
                measured_iterations=None,
                safety_factor=safety_factor,
            )
            * log_factor
        ),
    }
    disk_components = {
        "compact_group_scores_bytes": (
            compact_dataset.receipt.persistent_bytes / pair_count * TARGET_PRODUCTION_PAIRS
        ),
        "compact_null_aggregate_bytes": (
            compact_null.receipt.persistent_bytes / pair_count * TARGET_PRODUCTION_PAIRS
        ),
        "canonical_raw_evidence_bytes": (
            raw_write_receipt.size_bytes / raw_rows * TARGET_PRODUCTION_EVIDENCE_ROWS
        ),
        "detector_calibration_outputs_bytes": (
            calibration_bytes / raw_rows * TARGET_PRODUCTION_EVIDENCE_ROWS
        ),
        "evidence_offset_index_bytes": (
            index_path.stat().st_size / calibration_pairs * TARGET_PRODUCTION_PAIRS
        ),
        "serialized_ensemble_null_bytes": (
            (full_null_receipt.size_bytes + ablated_null_receipt.size_bytes)
            / calibration_pairs
            * TARGET_PRODUCTION_PAIRS
        ),
        "final_candidate_ledger_bytes": (
            candidate_output_bytes / calibration_pairs * TARGET_PRODUCTION_PAIRS
        ),
        "candidate_sort_chunk_bytes": (
            candidate_sort_chunk_bytes / calibration_pairs * TARGET_PRODUCTION_PAIRS
        ),
    }
    disk_extrapolation = {
        key: math.ceil(value * safety_factor) for key, value in disk_components.items()
    }
    disk_extrapolation["total_bytes"] = sum(disk_extrapolation.values())
    projected_disk_with_m7 = disk_extrapolation["total_bytes"] + CANONICAL_M7_BYTES_ESTIMATE
    projected_free_disk = INITIAL_FREE_DISK_BYTES - projected_disk_with_m7
    required_initial_free_disk = projected_disk_with_m7 + MINIMUM_FREE_DISK_FLOOR_BYTES
    extrapolated_measured_seconds = sum(time_extrapolations.values())
    unbenchmarked_reserve_seconds = sum(UNBENCHMARKED_RESERVE_SECONDS.values())
    extrapolated_total_seconds = extrapolated_measured_seconds + unbenchmarked_reserve_seconds
    peak_memory = _memory_snapshot()
    observed_peak_rss = peak_memory["peak_rss_bytes"]
    measured_peak_rss = (
        observed_peak_rss
        if isinstance(observed_peak_rss, int) and not isinstance(observed_peak_rss, bool)
        else None
    )

    config_path = (project_root / DEFAULT_FINAL_DISCOVERY_CONFIG).resolve()
    git_identity = _git_identity(project_root)
    return {
        "schema_version": 2,
        "benchmark_id": "final-discovery-disk-scale-v2",
        "report_status": (
            "commit_bound_clean" if git_identity["dirty"] is False else "provisional_dirty_worktree"
        ),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "synthetic_text_free": True,
        "data_policy": {
            "source_text_loaded": False,
            "model_loaded": False,
            "network_used": False,
            "synthetic_identifiers_and_numeric_scores_only": True,
        },
        "input_parameters": dict(parameters),
        "platform": {
            "platform": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "numpy": np.__version__,
            "duckdb": duckdb.__version__,
        },
        "config_identity": {
            "path": DEFAULT_FINAL_DISCOVERY_CONFIG.as_posix(),
            "physical_sha256": sha256_file(config_path),
            "base_semantic_sha256": final_discovery_config_sha256(base_config),
            "benchmark_semantic_sha256": final_discovery_config_sha256(benchmark_config),
            "benchmark_override": {"calibration.production_iterations": iterations},
            "benchmark_config": benchmark_config.model_dump(mode="json", exclude_none=False),
        },
        "code_identity": {
            **git_identity,
            "benchmark_script_sha256": sha256_file(Path(__file__).resolve()),
            "compact_nulls_sha256": _module_hash(
                project_root, "src/echoes/final_discovery/compact_nulls.py"
            ),
            "disk_calibration_sha256": _module_hash(
                project_root, "src/echoes/final_discovery/disk_calibration.py"
            ),
            "disk_ensemble_sha256": _module_hash(
                project_root, "src/echoes/final_discovery/disk_ensemble.py"
            ),
            "evidence_index_sha256": _module_hash(
                project_root, "src/echoes/final_discovery/evidence_index.py"
            ),
            "scale_contract_sha256": _module_hash(
                project_root, "src/echoes/final_discovery/scale.py"
            ),
        },
        "hard_cardinality_contract": {
            "status": "pass",
            "expected": expected_contract,
            "observed": observed_contract,
        },
        "measurements": stages,
        "resources": {
            "peak_memory": peak_memory,
            "maximum_observed_work_directory_bytes": maximum_work_bytes,
            "final_work_directory_bytes": _directory_size(work_dir),
            "disk_free_bytes_after": shutil.disk_usage(work_dir.parent).free,
        },
        "production_extrapolation": {
            "target_candidate_pairs": TARGET_PRODUCTION_PAIRS,
            "target_raw_and_calibrated_evidence_rows": (TARGET_PRODUCTION_EVIDENCE_ROWS),
            "target_null_iterations": TARGET_PRODUCTION_ITERATIONS,
            "campaign_scale_contract": scale_contract.model_dump(mode="json"),
            "method": (
                "decomposed_registered_units_with_direct_null_kernels_1.25_safety_and_n_log_n_sorts"
            ),
            "safety_factor": safety_factor,
            "planning_only_not_a_runtime_guarantee": True,
            "stage_accounting": {
                "counted_once": [
                    "canonical_raw_evidence_stream",
                    "disk_detector_calibration_fixed_io",
                    "detector_null_kernels",
                    "review_evidence_offset_index_build",
                    "compact_group_score_build",
                    "compact_null_both_scopes",
                    "disk_ensemble_candidate_build",
                ],
                "integration_only_not_counted_again": [
                    "disk_ensemble_group_score_projection",
                    "disk_ensemble_compact_null_sample",
                ],
            },
            "calibration_runtime_model": {
                "measured_whole_stage_seconds": detector_calibration_seconds,
                "measured_raw_rows": raw_rows,
                "measured_detector_strata": observed_detector_strata,
                "target_raw_rows": TARGET_PRODUCTION_EVIDENCE_ROWS,
                "target_detector_strata": target_detector_strata,
                "fixed_io_row_scaled_upper_seconds_before_safety": (
                    calibration_row_io_upper_seconds
                ),
                "fixed_io_stratum_scaled_upper_seconds_before_safety": (
                    calibration_stratum_io_upper_seconds
                ),
                "fixed_io_combination": (
                    "sum_of_gross_row_scaled_and_detector_stratum_scaled_bounds"
                ),
                "iteration_multiplier_applied_to_fixed_io": False,
                "direct_kernel_sample_score_count": kernel_sample_size,
                "direct_kernel_iterations": KERNEL_BENCHMARK_ITERATIONS,
                "direct_kernel_measurements": kernel_measurements,
                "permutation_like_target_rows": (
                    scale_contract.maximum_permutation_like_calibration_rows
                ),
                "bootstrap_target_rows": (scale_contract.maximum_bootstrap_calibration_rows),
                "permutation_n_log_n_factor": permutation_kernel_log_factor,
                "seeded_algorithm_and_output_contract_unchanged": True,
            },
            "elapsed_seconds": time_extrapolations,
            "measured_stage_projection_seconds_total": (extrapolated_measured_seconds),
            "unbenchmarked_reserve_seconds": UNBENCHMARKED_RESERVE_SECONDS,
            "unbenchmarked_reserve_seconds_total": unbenchmarked_reserve_seconds,
            "expected_wall_clock_range_seconds": {
                "lower": extrapolated_measured_seconds,
                "upper": extrapolated_total_seconds,
            },
            "elapsed_seconds_total": extrapolated_total_seconds,
            "persistent_disk_bytes": disk_extrapolation,
            "resource_gate": {
                "runtime": {
                    "limit_seconds": CAMPAIGN_RUNTIME_LIMIT_SECONDS,
                    "measured_stage_projection_seconds": (extrapolated_measured_seconds),
                    "unbenchmarked_reserve_seconds": unbenchmarked_reserve_seconds,
                    "projected_seconds": extrapolated_total_seconds,
                    "status": (
                        "pass"
                        if extrapolated_total_seconds <= CAMPAIGN_RUNTIME_LIMIT_SECONDS
                        else "fail"
                    ),
                },
                "memory": {
                    "scope": "observed_benchmark_process_peak_rss",
                    "limit_bytes": CAMPAIGN_PROCESS_MEMORY_LIMIT_BYTES,
                    "limit_basis": "registered_production_systemd_MemoryMax_56G",
                    "observed_peak_rss_bytes": measured_peak_rss,
                    "measurement_source": peak_memory["source"],
                    "status": (
                        "pass"
                        if measured_peak_rss is not None
                        and measured_peak_rss <= CAMPAIGN_PROCESS_MEMORY_LIMIT_BYTES
                        else "fail"
                    ),
                },
                "disk": {
                    "scope": "benchmark_persistent_artifacts_plus_canonical_m7",
                    "initial_free_bytes": INITIAL_FREE_DISK_BYTES,
                    "minimum_free_floor_bytes": MINIMUM_FREE_DISK_FLOOR_BYTES,
                    "canonical_m7_bytes_estimate": CANONICAL_M7_BYTES_ESTIMATE,
                    "canonical_m7_basis": "documented_17.149_GiB_rounded_up",
                    "projected_benchmark_artifact_bytes": disk_extrapolation["total_bytes"],
                    "projected_bytes_including_m7": projected_disk_with_m7,
                    "projected_free_bytes_after": projected_free_disk,
                    "required_initial_free_bytes": required_initial_free_disk,
                    "status": (
                        "pass" if projected_free_disk >= MINIMUM_FREE_DISK_FLOOR_BYTES else "fail"
                    ),
                },
            },
        },
        "limitations": [
            (
                "Synthetic numeric scores exercise storage and calibration mechanics, "
                "not detector feature extraction."
            ),
            (
                "The detector-calibration and disk-ensemble workload is a separately "
                "declared bounded sample."
            ),
            (
                "RSS is a portable best-effort process peak and may include interpreter "
                "state before the benchmark."
            ),
            (
                "Registered-unit extrapolations include a 1.25 safety factor but cannot "
                "predict host contention or filesystem variance."
            ),
            (
                "Representation extraction, B2 transfer, strict validation, packaging, "
                "and review-artifact generation are covered by explicit planning reserves, "
                "not claimed as measured stages."
            ),
            "No source text, offline model, cloud resource, or network request is used.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    parameters = _resolved_parameters(args)
    project_root = Path(__file__).resolve().parents[1]
    work_dir = args.work_dir.resolve()
    output_path = args.output.resolve()
    if output_path.exists():
        raise BenchmarkError(f"refusing to replace benchmark report: {output_path}")
    if (
        output_path == work_dir
        or output_path.is_relative_to(work_dir)
        or work_dir.is_relative_to(output_path)
    ):
        raise BenchmarkError("benchmark output and work paths cannot overlap")
    if work_dir.exists():
        raise BenchmarkError(f"benchmark work directory must be absent: {work_dir}")
    work_dir.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(exist_ok=False)
    tracemalloc.start()
    started = time.perf_counter()
    try:
        report = _run_benchmark(parameters, work_dir, project_root)
        report["total_elapsed_seconds"] = time.perf_counter() - started
        _write_gate_checked_report(output_path, report)
    finally:
        tracemalloc.stop()
        if not args.keep_work and work_dir.exists():
            shutil.rmtree(work_dir)
    print(
        json.dumps(
            {
                "status": "pass",
                "profile": parameters["profile"],
                "output": str(output_path),
                "work_retained": bool(args.keep_work),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BenchmarkError, ValueError, OSError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
