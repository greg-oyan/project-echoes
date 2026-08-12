"""Regression tests for bounded per-stage DuckDB memory selection."""

from __future__ import annotations

import pytest

from echoes.lexical import resources
from echoes.lexical.resources import (
    GIBIBYTE,
    MEBIBYTE,
    LexicalResourceError,
    ProcessResourceGuard,
)


def _guard(*, maximum: int, cloud_ceiling: int | None) -> ProcessResourceGuard:
    return ProcessResourceGuard(
        maximum_memory_bytes=maximum,
        duckdb_memory_limit_bytes=cloud_ceiling,
    )


def test_preferred_allocation_below_cloud_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "process_rss_bytes", lambda: 6 * GIBIBYTE)
    guard = _guard(maximum=28 * GIBIBYTE, cloud_ceiling=22 * GIBIBYTE)

    selected = guard.bounded_duckdb_memory_bytes(
        "candidate-materialization",
        preferred_bytes=512 * MEBIBYTE,
        reserve_for_python_bytes=512 * MEBIBYTE,
    )

    assert selected == 512 * MEBIBYTE


def test_available_memory_can_bound_cloud_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "process_rss_bytes", lambda: 6 * GIBIBYTE)
    guard = _guard(maximum=28 * GIBIBYTE, cloud_ceiling=22 * GIBIBYTE)

    selected = guard.bounded_duckdb_memory_bytes(
        "large-stage",
        preferred_bytes=24 * GIBIBYTE,
        reserve_for_python_bytes=1 * GIBIBYTE,
    )

    assert selected == 21 * GIBIBYTE


def test_cloud_ceiling_bounds_larger_preference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "process_rss_bytes", lambda: 1 * GIBIBYTE)
    guard = _guard(maximum=40 * GIBIBYTE, cloud_ceiling=4 * GIBIBYTE)

    selected = guard.bounded_duckdb_memory_bytes(
        "cloud-ceiling",
        preferred_bytes=8 * GIBIBYTE,
        reserve_for_python_bytes=1 * GIBIBYTE,
    )

    assert selected == 4 * GIBIBYTE


def test_available_memory_below_minimum_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "process_rss_bytes", lambda: 960 * MEBIBYTE)
    guard = _guard(maximum=1 * GIBIBYTE, cloud_ceiling=None)

    with pytest.raises(LexicalResourceError, match="insufficient governed memory"):
        guard.bounded_duckdb_memory_bytes(
            "too-small",
            preferred_bytes=128 * MEBIBYTE,
            reserve_for_python_bytes=16 * MEBIBYTE,
            minimum_bytes=64 * MEBIBYTE,
        )


def test_selected_limit_is_mib_aligned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "process_rss_bytes", lambda: 0)
    guard = _guard(maximum=8 * GIBIBYTE, cloud_ceiling=None)

    selected = guard.bounded_duckdb_memory_bytes(
        "alignment",
        preferred_bytes=(2 * MEBIBYTE) + 12345,
        reserve_for_python_bytes=0,
        minimum_bytes=1 * MEBIBYTE,
    )

    assert selected == 2 * MEBIBYTE
    assert selected % MEBIBYTE == 0
