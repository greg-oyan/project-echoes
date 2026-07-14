"""Fail-closed process-resource controls for the Milestone 7 lexical pipeline."""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb


class LexicalResourceError(RuntimeError):
    """Raised when a governed resource control cannot be enforced."""


THREAD_ENVIRONMENT_VARIABLES: tuple[str, ...] = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
    "POLARS_MAX_THREADS",
)

MEBIBYTE = 1024**2
MINIMUM_DUCKDB_MEMORY_BYTES = 64 * MEBIBYTE


def _duckdb_memory_setting_bytes(value: object) -> int:
    """Parse DuckDB's canonical binary memory setting for exact verification."""

    parts = str(value).split()
    if len(parts) != 2:
        raise LexicalResourceError(f"DuckDB returned an invalid memory_limit: {value!r}")
    unit_bytes = {"B": 1, "KiB": 1024, "MiB": MEBIBYTE, "GiB": 1024**3}
    if parts[1] not in unit_bytes:
        raise LexicalResourceError(f"DuckDB returned an unknown memory_limit unit: {value!r}")
    try:
        return int(float(parts[0]) * unit_bytes[parts[1]])
    except ValueError as exc:
        raise LexicalResourceError(f"DuckDB returned an invalid memory_limit: {value!r}") from exc


def initialize_thread_controls(thread_count: int = 1) -> dict[str, str]:
    """Set deterministic defaults before numeric libraries initialize their pools."""

    if thread_count < 1:
        raise LexicalResourceError("thread_count must be positive")
    value = str(thread_count)
    for name in THREAD_ENVIRONMENT_VARIABLES:
        os.environ.setdefault(name, value)
    return {name: os.environ[name] for name in THREAD_ENVIRONMENT_VARIABLES}


def enforce_thread_controls(thread_count: int) -> dict[str, str]:
    """Apply the configured thread ceiling and return its complete environment record."""

    if thread_count < 1:
        raise LexicalResourceError("thread_count must be positive")
    value = str(thread_count)
    for name in THREAD_ENVIRONMENT_VARIABLES:
        os.environ[name] = value
    return {name: os.environ[name] for name in THREAD_ENVIRONMENT_VARIABLES}


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t),
        ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
        ("quota_non_paged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
    ]


def _windows_process_rss_bytes() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_memory_info = psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    get_process_memory_info.restype = ctypes.c_int
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not get_process_memory_info(get_current_process(), ctypes.byref(counters), counters.cb):
        error = ctypes.get_last_error()
        raise LexicalResourceError(f"GetProcessMemoryInfo failed with Windows error {error}")
    return int(counters.working_set_size)


def _linux_process_rss_bytes() -> int:
    statm = Path("/proc/self/statm")
    try:
        fields = statm.read_text(encoding="ascii").split()
    except (OSError, UnicodeError) as exc:
        raise LexicalResourceError(f"could not read process RSS from {statm}: {exc}") from exc
    if len(fields) < 2:
        raise LexicalResourceError(f"process RSS record is incomplete: {statm}")
    try:
        resident_pages = int(fields[1])
        sysconf: Callable[[str], int] = os.sysconf  # type: ignore[attr-defined]
        page_size = int(sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError) as exc:
        raise LexicalResourceError(f"could not decode process RSS from {statm}: {exc}") from exc
    return resident_pages * page_size


def process_rss_bytes() -> int:
    """Return current resident process memory using an OS-native, dependency-free probe."""

    if sys.platform == "win32":
        return _windows_process_rss_bytes()
    if sys.platform.startswith("linux"):
        return _linux_process_rss_bytes()
    raise LexicalResourceError(
        f"current process RSS measurement is unsupported on platform {sys.platform!r}"
    )


@dataclass(slots=True)
class ProcessResourceGuard:
    """Measure current RSS at every checkpoint and fail before promotion on overflow."""

    maximum_memory_bytes: int
    peak_rss_bytes: int = 0
    last_stage: str = "not_started"

    def __post_init__(self) -> None:
        if self.maximum_memory_bytes < 1:
            raise LexicalResourceError("maximum_memory_bytes must be positive")

    def check(self, stage: str, *, estimated_additional_bytes: int = 0) -> int:
        """Check current and reserved RSS against the configured hard ceiling."""

        if not stage:
            raise LexicalResourceError("resource checkpoint stage must be nonempty")
        if estimated_additional_bytes < 0:
            raise LexicalResourceError("estimated additional memory cannot be negative")
        rss = process_rss_bytes()
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
        self.last_stage = stage
        projected = rss + estimated_additional_bytes
        if projected > self.maximum_memory_bytes:
            raise LexicalResourceError(
                "lexical memory ceiling exceeded at "
                f"{stage}: rss={rss}, reserved={estimated_additional_bytes}, "
                f"maximum={self.maximum_memory_bytes}"
            )
        return rss

    def bounded_duckdb_memory_bytes(
        self,
        stage: str,
        *,
        preferred_bytes: int,
        reserve_for_python_bytes: int,
        minimum_bytes: int = MINIMUM_DUCKDB_MEMORY_BYTES,
    ) -> int:
        """Return a MiB-aligned DuckDB ceiling while retaining Python-process headroom."""

        if preferred_bytes < minimum_bytes:
            raise LexicalResourceError("preferred DuckDB memory is below its safe minimum")
        if reserve_for_python_bytes < 0:
            raise LexicalResourceError("DuckDB Python-process reserve cannot be negative")
        rss = self.check(stage)
        available = self.maximum_memory_bytes - rss - reserve_for_python_bytes
        if available < minimum_bytes:
            raise LexicalResourceError(
                "insufficient governed memory for bounded DuckDB work at "
                f"{stage}: rss={rss}, python_reserve={reserve_for_python_bytes}, "
                f"minimum_duckdb={minimum_bytes}, maximum={self.maximum_memory_bytes}"
            )
        selected = min(preferred_bytes, available)
        return max(minimum_bytes, (selected // MEBIBYTE) * MEBIBYTE)


def configure_duckdb_connection(
    connection: duckdb.DuckDBPyConnection,
    *,
    memory_limit_bytes: int,
    temp_directory: Path,
    thread_count: int = 1,
) -> dict[str, object]:
    """Apply and verify deterministic bounded settings on one DuckDB connection."""

    if thread_count != 1:
        raise LexicalResourceError("Milestone 7 DuckDB connections must use exactly one thread")
    if memory_limit_bytes < MINIMUM_DUCKDB_MEMORY_BYTES:
        raise LexicalResourceError(
            f"DuckDB memory_limit must be at least {MINIMUM_DUCKDB_MEMORY_BYTES} bytes"
        )
    memory_limit_mib = memory_limit_bytes // MEBIBYTE
    resolved_temp = temp_directory.resolve()
    resolved_temp.mkdir(parents=True, exist_ok=True)
    escaped_temp = resolved_temp.as_posix().replace("'", "''")
    connection.execute(f"SET threads={thread_count}")
    connection.execute(f"SET memory_limit='{memory_limit_mib}MiB'")
    connection.execute(f"SET temp_directory='{escaped_temp}'")
    connection.execute("SET preserve_insertion_order=false")
    observed = connection.execute(
        "SELECT current_setting('threads'), current_setting('memory_limit'), "
        "current_setting('temp_directory'), current_setting('preserve_insertion_order')"
    ).fetchone()
    if observed is None or int(str(observed[0])) != thread_count:
        raise LexicalResourceError("DuckDB did not retain the governed single-thread setting")
    observed_memory_bytes = _duckdb_memory_setting_bytes(observed[1])
    expected_memory_bytes = memory_limit_mib * MEBIBYTE
    if observed_memory_bytes != expected_memory_bytes:
        raise LexicalResourceError(
            "DuckDB did not retain the governed memory limit: "
            f"expected={expected_memory_bytes}, observed={observed_memory_bytes}"
        )
    observed_temp = Path(str(observed[2])).resolve()
    if os.path.normcase(str(observed_temp)) != os.path.normcase(str(resolved_temp)):
        raise LexicalResourceError(
            "DuckDB did not retain the governed temp directory: "
            f"expected={resolved_temp}, observed={observed_temp}"
        )
    if bool(observed[3]):
        raise LexicalResourceError("DuckDB did not disable insertion-order preservation")
    return {
        "threads": int(str(observed[0])),
        "memory_limit": str(observed[1]),
        "memory_limit_bytes": observed_memory_bytes,
        "temp_directory": str(observed_temp),
        "preserve_insertion_order": bool(observed[3]),
    }
