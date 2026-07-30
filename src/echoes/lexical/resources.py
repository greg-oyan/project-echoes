"""Fail-closed process-resource controls for the Milestone 7 lexical pipeline."""

from __future__ import annotations

import ctypes
import os
import sys
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
GIBIBYTE = 1024**3
MINIMUM_DUCKDB_MEMORY_BYTES = 64 * MEBIBYTE
M7_CLOUD_MAXIMUM_MEMORY_BYTES = 56 * GIBIBYTE
M7_CLOUD_DUCKDB_MEMORY_BYTES = 48 * GIBIBYTE
M7_CLOUD_EXECUTION_ENV = "ECHOES_M7_CLOUD_EXECUTION"
MAXIMUM_MEMORY_ENV = "ECHOES_MAXIMUM_MEMORY_BYTES"
DUCKDB_MEMORY_LIMIT_ENV = "ECHOES_DUCKDB_MEMORY_LIMIT_BYTES"
THREAD_COUNT_ENV = "ECHOES_THREAD_COUNT"
DUCKDB_TEMP_DIRECTORY_ENV = "ECHOES_DUCKDB_TEMP_DIRECTORY"
_OPERATIONAL_OVERRIDE_ENVIRONMENT = (
    MAXIMUM_MEMORY_ENV,
    DUCKDB_MEMORY_LIMIT_ENV,
    THREAD_COUNT_ENV,
    DUCKDB_TEMP_DIRECTORY_ENV,
)


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


if sys.platform == "win32":

    class _MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
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

    def _windows_physical_memory_bytes() -> int:
        status = _MemoryStatus()
        status.length = ctypes.sizeof(_MemoryStatus)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical)
        return 0

else:

    def _windows_process_rss_bytes() -> int:
        raise LexicalResourceError("Windows process RSS probe is unavailable on this platform")

    def _windows_physical_memory_bytes() -> int:
        return 0


def _sysconf_value(name: str) -> int:
    """Read one POSIX sysconf value without exposing platform-only os attributes to mypy."""

    sysconf = getattr(os, "sysconf", None)
    if not callable(sysconf):
        raise LexicalResourceError("POSIX sysconf is unavailable on this platform")
    try:
        return int(sysconf(name))
    except (OSError, ValueError) as exc:
        raise LexicalResourceError(f"could not read POSIX sysconf value {name}: {exc}") from exc


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
        page_size = _sysconf_value("SC_PAGE_SIZE")
    except (ValueError, LexicalResourceError) as exc:
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


def physical_memory_bytes() -> int:
    """Return installed physical RAM using an explicit platform-native probe."""

    if sys.platform == "win32":
        return _windows_physical_memory_bytes()
    try:
        return _sysconf_value("SC_PAGE_SIZE") * _sysconf_value("SC_PHYS_PAGES")
    except LexicalResourceError:
        return 0


def _positive_environment_integer(name: str) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        raise LexicalResourceError(f"cloud execution requires {name}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise LexicalResourceError(f"{name} must be a base-10 integer") from exc
    if value < 1:
        raise LexicalResourceError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class LexicalOperationalLimits:
    """Execution-only limits that never participate in scientific configuration identity."""

    maximum_memory_bytes: int
    duckdb_memory_limit_bytes: int | None
    thread_count: int
    duckdb_temp_directory: Path | None
    cloud_execution: bool

    def manifest_values(self) -> dict[str, object]:
        """Return a stable, non-secret execution-provenance payload."""

        return {
            "cloud_execution": self.cloud_execution,
            "maximum_memory_bytes": self.maximum_memory_bytes,
            "duckdb_memory_limit_bytes": self.duckdb_memory_limit_bytes,
            "thread_count": self.thread_count,
            "duckdb_temp_directory": (
                None
                if self.duckdb_temp_directory is None
                else self.duckdb_temp_directory.as_posix()
            ),
        }


def resolve_operational_limits(
    *,
    configured_maximum_memory_bytes: int,
    configured_thread_count: int,
) -> LexicalOperationalLimits:
    """Resolve an explicit cloud profile without changing frozen config hashes."""

    cloud_raw = os.environ.get(M7_CLOUD_EXECUTION_ENV)
    if cloud_raw is None:
        unexpected = [name for name in _OPERATIONAL_OVERRIDE_ENVIRONMENT if name in os.environ]
        if unexpected:
            raise LexicalResourceError(
                f"operational overrides require {M7_CLOUD_EXECUTION_ENV}=1: {unexpected}"
            )
        return LexicalOperationalLimits(
            maximum_memory_bytes=configured_maximum_memory_bytes,
            duckdb_memory_limit_bytes=None,
            thread_count=configured_thread_count,
            duckdb_temp_directory=None,
            cloud_execution=False,
        )
    if cloud_raw != "1":
        raise LexicalResourceError(f"{M7_CLOUD_EXECUTION_ENV} must be exactly 1 when set")

    maximum_memory_bytes = _positive_environment_integer(MAXIMUM_MEMORY_ENV)
    duckdb_memory_limit_bytes = _positive_environment_integer(DUCKDB_MEMORY_LIMIT_ENV)
    thread_count = _positive_environment_integer(THREAD_COUNT_ENV)
    raw_temp = os.environ.get(DUCKDB_TEMP_DIRECTORY_ENV)
    if raw_temp is None or not raw_temp.strip():
        raise LexicalResourceError(f"cloud execution requires {DUCKDB_TEMP_DIRECTORY_ENV}")
    temp_directory = Path(raw_temp)
    if not temp_directory.is_absolute():
        raise LexicalResourceError(f"{DUCKDB_TEMP_DIRECTORY_ENV} must be an absolute path")
    if thread_count > 12:
        raise LexicalResourceError("cloud execution cannot exceed twelve computational threads")
    if maximum_memory_bytes != M7_CLOUD_MAXIMUM_MEMORY_BYTES:
        raise LexicalResourceError(
            "Milestone 7 cloud process ceiling must be exactly "
            f"{M7_CLOUD_MAXIMUM_MEMORY_BYTES} bytes"
        )
    if duckdb_memory_limit_bytes != M7_CLOUD_DUCKDB_MEMORY_BYTES:
        raise LexicalResourceError(
            f"Milestone 7 cloud DuckDB limit must be exactly {M7_CLOUD_DUCKDB_MEMORY_BYTES} bytes"
        )
    if thread_count != configured_thread_count:
        raise LexicalResourceError(
            "cloud thread count must preserve the frozen scientific configuration: "
            f"configured={configured_thread_count}, operational={thread_count}"
        )
    if maximum_memory_bytes < configured_maximum_memory_bytes:
        raise LexicalResourceError(
            "cloud process ceiling cannot be lower than the frozen configured ceiling"
        )
    if duckdb_memory_limit_bytes < MINIMUM_DUCKDB_MEMORY_BYTES:
        raise LexicalResourceError(
            f"cloud DuckDB limit must be at least {MINIMUM_DUCKDB_MEMORY_BYTES} bytes"
        )
    if duckdb_memory_limit_bytes >= maximum_memory_bytes:
        raise LexicalResourceError(
            "cloud DuckDB limit must leave memory headroom below the process ceiling"
        )
    return LexicalOperationalLimits(
        maximum_memory_bytes=maximum_memory_bytes,
        duckdb_memory_limit_bytes=duckdb_memory_limit_bytes,
        thread_count=thread_count,
        duckdb_temp_directory=temp_directory.resolve(),
        cloud_execution=True,
    )


@dataclass(slots=True)
class ProcessResourceGuard:
    """Measure current RSS at every checkpoint and fail before promotion on overflow."""

    maximum_memory_bytes: int
    duckdb_memory_limit_bytes: int | None = None
    peak_rss_bytes: int = 0
    last_stage: str = "not_started"

    def __post_init__(self) -> None:
        if self.maximum_memory_bytes < 1:
            raise LexicalResourceError("maximum_memory_bytes must be positive")
        if (
            self.duckdb_memory_limit_bytes is not None
            and self.duckdb_memory_limit_bytes < MINIMUM_DUCKDB_MEMORY_BYTES
        ):
            raise LexicalResourceError(
                f"duckdb_memory_limit_bytes must be at least {MINIMUM_DUCKDB_MEMORY_BYTES}"
            )

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
        if self.duckdb_memory_limit_bytes is not None:
            if self.duckdb_memory_limit_bytes > available:
                raise LexicalResourceError(
                    "cloud DuckDB memory limit does not fit beneath the governed process "
                    f"ceiling at {stage}: requested={self.duckdb_memory_limit_bytes}, "
                    f"available={available}"
                )
            selected = self.duckdb_memory_limit_bytes
        else:
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
