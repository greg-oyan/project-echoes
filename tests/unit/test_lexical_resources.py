"""Cross-platform lexical resource-probe contracts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import echoes.lexical.resources as lexical_resources
from echoes.lexical.resources import (
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
        )


def test_cloud_operational_limits_are_explicit_and_preserve_frozen_threads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_directory = tmp_path / "duckdb"
    monkeypatch.setenv("ECHOES_M7_CLOUD_EXECUTION", "1")
    monkeypatch.setenv("ECHOES_MAXIMUM_MEMORY_BYTES", str(56 * 1024**3))
    monkeypatch.setenv("ECHOES_DUCKDB_MEMORY_LIMIT_BYTES", str(48 * 1024**3))
    monkeypatch.setenv("ECHOES_THREAD_COUNT", "1")
    monkeypatch.setenv("ECHOES_DUCKDB_TEMP_DIRECTORY", str(temp_directory))

    limits = resolve_operational_limits(
        configured_maximum_memory_bytes=6 * 1024**3,
        configured_thread_count=1,
    )

    assert limits.cloud_execution is True
    assert limits.maximum_memory_bytes == 56 * 1024**3
    assert limits.duckdb_memory_limit_bytes == 48 * 1024**3
    assert limits.thread_count == 1
    assert limits.duckdb_temp_directory == temp_directory.resolve()

    monkeypatch.setenv("ECHOES_THREAD_COUNT", "12")
    with pytest.raises(LexicalResourceError, match="preserve the frozen"):
        resolve_operational_limits(
            configured_maximum_memory_bytes=6 * 1024**3,
            configured_thread_count=1,
        )

    monkeypatch.setenv("ECHOES_THREAD_COUNT", "1")
    monkeypatch.setenv("ECHOES_DUCKDB_MEMORY_LIMIT_BYTES", str(47 * 1024**3))
    with pytest.raises(LexicalResourceError, match="must be exactly"):
        resolve_operational_limits(
            configured_maximum_memory_bytes=6 * 1024**3,
            configured_thread_count=1,
        )


def test_cloud_duckdb_override_is_exact_and_leaves_process_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lexical_resources, "process_rss_bytes", lambda: 2 * 1024**3)
    guard = ProcessResourceGuard(
        maximum_memory_bytes=56 * 1024**3,
        duckdb_memory_limit_bytes=48 * 1024**3,
    )

    selected = guard.bounded_duckdb_memory_bytes(
        "fixture",
        preferred_bytes=512 * 1024**2,
        reserve_for_python_bytes=4 * 1024**3,
    )

    assert selected == 48 * 1024**3
