"""End-to-end contracts for the text-free final-discovery scale benchmark."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "benchmark_final_discovery.py"


def _load_benchmark_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("echoes_benchmark_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


benchmark = _load_benchmark_module()


def _command(work_dir: Path, output_path: Path) -> list[str]:
    return [
        sys.executable,
        str(SCRIPT),
        "--pairs",
        "12",
        "--iterations",
        "2",
        "--calibration-pairs",
        "4",
        "--strata",
        "2",
        "--lookup-count",
        "2",
        "--candidate-chunk-size",
        "2",
        "--duckdb-memory-mib",
        "256",
        "--work-dir",
        str(work_dir),
        "--output",
        str(output_path),
    ]


def test_benchmark_emits_atomic_cardinality_checked_report_and_cleans_work(
    tmp_path: Path,
) -> None:
    work_dir = tmp_path / "owned-work"
    output_path = tmp_path / "report.json"
    command = _command(work_dir, output_path)

    completed = subprocess.run(
        command,
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert output_path.is_file()
    assert not work_dir.exists()
    report = json.loads(output_path.read_text(encoding="utf-8"))
    expected_returncode = 0 if report["acceptance_gate"]["status"] == "pass" else 1
    assert completed.returncode == expected_returncode
    if expected_returncode == 1:
        assert "benchmark acceptance gates failed closed" in completed.stderr
    assert report["schema_version"] == 2
    assert report["benchmark_id"] == "final-discovery-disk-scale-v2"
    assert report["report_status"] in {
        "commit_bound_clean",
        "provisional_dirty_worktree",
    }
    assert report["synthetic_text_free"] is True
    assert report["data_policy"] == {
        "model_loaded": False,
        "network_used": False,
        "source_text_loaded": False,
        "synthetic_identifiers_and_numeric_scores_only": True,
    }
    contract = report["hard_cardinality_contract"]
    assert contract["status"] == "pass"
    assert contract["observed"] == contract["expected"]
    assert contract["observed"]["compact_group_score_pairs"] == 12
    assert contract["observed"]["compact_null_rows_per_scope"] == 12
    assert contract["observed"]["compact_null_scopes"] == 2
    assert contract["observed"]["raw_evidence_rows"] == 36
    assert contract["observed"]["detectors_per_calibration_pair"] == 9
    assert contract["observed"]["disk_ensemble_candidates"] == 4
    assert set(report["measurements"]) >= {
        "canonical_raw_evidence_stream",
        "compact_group_score_build",
        "compact_null_both_scopes",
        "disk_detector_calibration_sample",
        "direct_detector_null_kernels",
        "disk_ensemble_candidate_build",
        "review_evidence_offset_index_build",
        "review_offset_lookup_sample",
    }
    assert report["resources"]["peak_memory"]["peak_rss_bytes"] > 0
    memory_gate = report["production_extrapolation"]["resource_gate"]["memory"]
    assert memory_gate["limit_bytes"] == 56 * 1024**3
    assert memory_gate["limit_basis"] == "registered_production_systemd_MemoryMax_56G"
    assert (
        memory_gate["observed_peak_rss_bytes"]
        == report["resources"]["peak_memory"]["peak_rss_bytes"]
    )
    assert memory_gate["status"] == "pass"
    assert report["config_identity"]["physical_sha256"]
    assert report["config_identity"]["benchmark_semantic_sha256"]
    assert report["code_identity"]["benchmark_script_sha256"]
    extrapolation = report["production_extrapolation"]
    assert extrapolation["target_candidate_pairs"] == 2_592_480
    assert extrapolation["target_raw_and_calibrated_evidence_rows"] == 11_718_699
    assert extrapolation["target_null_iterations"] == 1_000
    assert extrapolation["safety_factor"] == 1.25
    assert extrapolation["persistent_disk_bytes"]["total_bytes"] > 0
    scale = extrapolation["campaign_scale_contract"]
    assert scale["maximum_calibration_pair_strata"] == 6_633
    assert scale["maximum_calibration_detector_strata"] == 59_697
    assert scale["maximum_permutation_like_calibration_rows"] == 10_123_211
    assert scale["maximum_bootstrap_calibration_rows"] == 1_595_488
    elapsed = extrapolation["elapsed_seconds"]
    assert "ensemble_group_projection_seconds" not in elapsed
    assert "ensemble_null_both_scopes_seconds" not in elapsed
    assert "detector_calibration_fixed_io_upper_seconds" in elapsed
    assert "detector_calibration_permutation_kernel_seconds_n_log_n" in elapsed
    assert (
        extrapolation["calibration_runtime_model"]["iteration_multiplier_applied_to_fixed_io"]
        is False
    )
    expected_range = extrapolation["expected_wall_clock_range_seconds"]
    assert expected_range["lower"] < expected_range["upper"]
    assert expected_range["upper"] == extrapolation["elapsed_seconds_total"]
    disk_gate = extrapolation["resource_gate"]["disk"]
    assert disk_gate["initial_free_bytes"] == 280 * 1024**3
    assert disk_gate["minimum_free_floor_bytes"] == 80 * 1024**3
    assert disk_gate["projected_bytes_including_m7"] > 0
    acceptance_gate = report["acceptance_gate"]
    assert acceptance_gate["required_gates"] == [
        "runtime",
        "memory",
        "disk",
        "hard_cardinality",
    ]
    assert acceptance_gate["failed_gates"] == [
        name for name, status in acceptance_gate["observed_statuses"].items() if status != "pass"
    ]

    original_report = output_path.read_bytes()
    repeated = subprocess.run(
        command,
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert repeated.returncode == 1
    assert "refusing to replace benchmark report" in repeated.stderr
    assert output_path.read_bytes() == original_report
    assert not work_dir.exists()

    overlapping_output = tmp_path / "overlapping-output"
    overlapping = subprocess.run(
        _command(overlapping_output / "work", overlapping_output),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert overlapping.returncode == 1
    assert "output and work paths cannot overlap" in overlapping.stderr
    assert not overlapping_output.exists()


@pytest.mark.parametrize("failed_gate", ["runtime", "memory", "disk", "hard_cardinality"])
def test_gate_checked_report_is_preserved_and_fails_closed(
    tmp_path: Path,
    failed_gate: str,
) -> None:
    report: dict[str, object] = {
        "hard_cardinality_contract": {"status": "pass"},
        "production_extrapolation": {
            "resource_gate": {
                "runtime": {"status": "pass"},
                "memory": {"status": "pass"},
                "disk": {"status": "pass"},
            }
        },
    }
    if failed_gate == "hard_cardinality":
        report["hard_cardinality_contract"] = {"status": "fail"}
    else:
        resource_gate = report["production_extrapolation"]["resource_gate"]
        resource_gate[failed_gate] = {"status": "fail"}

    output_path = tmp_path / f"{failed_gate}.json"
    with pytest.raises(
        benchmark.BenchmarkError,
        match=rf"benchmark acceptance gates failed closed: {failed_gate}",
    ):
        benchmark._write_gate_checked_report(output_path, report)

    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["acceptance_gate"]["status"] == "fail"
    assert persisted["acceptance_gate"]["failed_gates"] == [failed_gate]
