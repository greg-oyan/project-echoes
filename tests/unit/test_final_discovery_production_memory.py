"""Production resource contracts proven by measured full-scale preparation."""

from __future__ import annotations

import inspect

import echoes.final_discovery.pipeline as pipeline


def test_stage_one_knownness_uses_measured_four_gib_bound() -> None:
    assert pipeline._KNOWNNESS_PROJECTION_MEMORY_LIMIT_BYTES == 4 * 1024**3
    source = inspect.getsource(pipeline._produce_stage_one)
    assert "memory_limit_bytes=_KNOWNNESS_PROJECTION_MEMORY_LIMIT_BYTES" in source


def test_knownness_change_does_not_relax_other_production_bounds() -> None:
    assert pipeline._M7_PROJECTION_MEMORY_LIMIT_BYTES == 1024**3
    assert pipeline._FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_BYTES == 4 * 1024**3
    assert pipeline._MINIMUM_PRODUCTION_DISK_FLOOR_BYTES == 80 * 1024**3
