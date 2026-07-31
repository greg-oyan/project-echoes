"""Cross-platform lexical resource-probe contracts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import echoes.lexical.resources as lexical_resources
from echoes.lexical.config import load_lexical_config
from echoes.lexical.resources import (
    M7_CLOUD_DUCKDB_MEMORY_BYTES,
    M7_CLOUD_MACHINE_CPU_COUNT,
    M7_CLOUD_MACHINE_MEMORY_BYTES,
    M7_CLOUD_MACHINE_STORAGE_BYTES,
    M7_CLOUD_MAXIMUM_MEMORY_BYTES,
    M7_CLOUD_MAXIMUM_THREAD_COUNT,
    M7_CLOUD_MEMORY_HIGH_BYTES,
    M7_CLOUD_MINIMUM_LAUNCH_FREE_DISK_BYTES,
    M7_CLOUD_SAFE_STOP_FREE_DISK_BYTES,
    LexicalResourceError,
    ProcessResourceGuard,
    physical_memory_bytes,
    process_rss_bytes,
    resolve_operational_limits,
)


@pytest.mark.skipif(
    sys.platform != "win32" and not sys.platform.startswith("linux"),
    reason="the governed RSS probe supports Windows and Linux",
)
def test_platform_memory_probes_report_positive_byte_counts() -> None:
    assert process_rss_bytes() > 0
    assert physical_memory_bytes() > 0


def test_local_operational_limits_reject_unscoped_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ECHOES_M7_CLOUD_EXECUTION", raising=False)
    monkeypatch.setenv("ECHOES_MAXIMUM_MEMORY_BYTES", "123")

    with pytest.raises(LexicalResourceError, match="require ECHOES_M7_CLOUD_EXECUTION=1"):
        resolve_operational_limits(
            configured_maximum_memory_bytes=6 * 1024**3,
            configured_thread_count=1,
            configured_minimum_free_disk_bytes=10 * 1024**3,
        )


def test_cloud_operational_limits_are_explicit_and_preserve_frozen_threads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_directory = tmp_path / "duckdb"
    monkeypatch.setenv("ECHOES_M7_CLOUD_EXECUTION", "1")
    monkeypatch.setenv("ECHOES_MAXIMUM_MEMORY_BYTES", str(M7_CLOUD_MAXIMUM_MEMORY_BYTES))
    monkeypatch.setenv(
        "ECHOES_DUCKDB_MEMORY_LIMIT_BYTES",
        str(M7_CLOUD_DUCKDB_MEMORY_BYTES),
    )
    monkeypatch.setenv("ECHOES_THREAD_COUNT", "1")
    monkeypatch.setenv("ECHOES_DUCKDB_TEMP_DIRECTORY", str(temp_directory))
    monkeypatch.setenv(
        "ECHOES_MINIMUM_FREE_DISK_BYTES",
        str(M7_CLOUD_SAFE_STOP_FREE_DISK_BYTES),
    )

    limits = resolve_operational_limits(
        configured_maximum_memory_bytes=6 * 1024**3,
        configured_thread_count=1,
        configured_minimum_free_disk_bytes=10 * 1024**3,
    )

    assert limits.cloud_execution is True
    assert limits.maximum_memory_bytes == M7_CLOUD_MAXIMUM_MEMORY_BYTES
    assert limits.duckdb_memory_limit_bytes == M7_CLOUD_DUCKDB_MEMORY_BYTES
    assert limits.thread_count == 1
    assert limits.duckdb_temp_directory == temp_directory.resolve()
    assert limits.minimum_free_disk_bytes == M7_CLOUD_SAFE_STOP_FREE_DISK_BYTES

    monkeypatch.setenv("ECHOES_THREAD_COUNT", str(M7_CLOUD_MAXIMUM_THREAD_COUNT + 1))
    with pytest.raises(LexicalResourceError, match="cannot exceed 6"):
        resolve_operational_limits(
            configured_maximum_memory_bytes=6 * 1024**3,
            configured_thread_count=1,
            configured_minimum_free_disk_bytes=10 * 1024**3,
        )

    monkeypatch.setenv("ECHOES_THREAD_COUNT", str(M7_CLOUD_MAXIMUM_THREAD_COUNT))
    with pytest.raises(LexicalResourceError, match="preserve the frozen"):
        resolve_operational_limits(
            configured_maximum_memory_bytes=6 * 1024**3,
            configured_thread_count=1,
            configured_minimum_free_disk_bytes=10 * 1024**3,
        )

    monkeypatch.setenv("ECHOES_THREAD_COUNT", "1")
    monkeypatch.setenv(
        "ECHOES_DUCKDB_MEMORY_LIMIT_BYTES",
        str(M7_CLOUD_DUCKDB_MEMORY_BYTES - 1),
    )
    with pytest.raises(LexicalResourceError, match="must be exactly"):
        resolve_operational_limits(
            configured_maximum_memory_bytes=6 * 1024**3,
            configured_thread_count=1,
            configured_minimum_free_disk_bytes=10 * 1024**3,
        )

    monkeypatch.setenv(
        "ECHOES_DUCKDB_MEMORY_LIMIT_BYTES",
        str(M7_CLOUD_DUCKDB_MEMORY_BYTES),
    )
    monkeypatch.setenv(
        "ECHOES_MINIMUM_FREE_DISK_BYTES",
        str(M7_CLOUD_SAFE_STOP_FREE_DISK_BYTES - 1),
    )
    with pytest.raises(LexicalResourceError, match="safe-stop disk floor"):
        resolve_operational_limits(
            configured_maximum_memory_bytes=6 * 1024**3,
            configured_thread_count=1,
            configured_minimum_free_disk_bytes=10 * 1024**3,
        )


def test_cloud_duckdb_override_is_exact_and_leaves_process_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lexical_resources, "process_rss_bytes", lambda: 2 * 1024**3)
    guard = ProcessResourceGuard(
        maximum_memory_bytes=M7_CLOUD_MAXIMUM_MEMORY_BYTES,
        duckdb_memory_limit_bytes=M7_CLOUD_DUCKDB_MEMORY_BYTES,
    )

    selected = guard.bounded_duckdb_memory_bytes(
        "fixture",
        preferred_bytes=512 * 1024**2,
        reserve_for_python_bytes=4 * 1024**3,
    )

    assert selected == M7_CLOUD_DUCKDB_MEMORY_BYTES


def test_simulated_ccx33_profile_satisfies_the_operational_contract() -> None:
    frozen_thread_count = load_lexical_config().resource_limits.thread_count
    simulated_free_disk_bytes = M7_CLOUD_MINIMUM_LAUNCH_FREE_DISK_BYTES
    superseded_ccx43_launch_floor = 250 * 1024**3

    assert M7_CLOUD_MACHINE_MEMORY_BYTES == 32 * 1024**3
    assert M7_CLOUD_MACHINE_STORAGE_BYTES == 240_000_000_000
    assert M7_CLOUD_MACHINE_CPU_COUNT == 8
    assert simulated_free_disk_bytes <= M7_CLOUD_MACHINE_STORAGE_BYTES
    assert superseded_ccx43_launch_floor > M7_CLOUD_MACHINE_STORAGE_BYTES
    assert M7_CLOUD_DUCKDB_MEMORY_BYTES < M7_CLOUD_MAXIMUM_MEMORY_BYTES
    assert M7_CLOUD_MEMORY_HIGH_BYTES < M7_CLOUD_MAXIMUM_MEMORY_BYTES
    assert M7_CLOUD_MAXIMUM_MEMORY_BYTES <= M7_CLOUD_MACHINE_MEMORY_BYTES
    assert M7_CLOUD_MAXIMUM_THREAD_COUNT <= M7_CLOUD_MACHINE_CPU_COUNT
    assert frozen_thread_count == 1
    assert frozen_thread_count <= M7_CLOUD_MAXIMUM_THREAD_COUNT
    assert M7_CLOUD_SAFE_STOP_FREE_DISK_BYTES < M7_CLOUD_MINIMUM_LAUNCH_FREE_DISK_BYTES
