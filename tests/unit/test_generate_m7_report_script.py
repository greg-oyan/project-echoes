"""Command-exit contracts for the Milestone 7 report wrapper."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_report_script() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "generate_m7_report.py"
    spec = importlib.util.spec_from_file_location("generate_m7_report_script", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load report wrapper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_m7_report = _load_report_script()


@pytest.mark.parametrize(
    ("accepted", "allow_failed", "expected_exit"),
    ((True, False, 0), (False, False, 1), (False, True, 0)),
)
def test_report_script_exit_status_tracks_acceptance_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    accepted: bool,
    allow_failed: bool,
    expected_exit: int,
) -> None:
    artifacts = SimpleNamespace(
        acceptance_gate_passed=accepted,
        determinism=SimpleNamespace(status="passed"),
        execution_determinism=SimpleNamespace(
            status="passed",
            first_execution_id="execution-first",
            second_execution_id="execution-second",
        ),
        paths=(Path("outputs/reports/report.md"),),
        sha256_by_name={"report.md": "a" * 64},
    )
    monkeypatch.setattr(
        generate_m7_report,
        "generate_lexical_baseline_reports",
        lambda **_: artifacts,
    )
    arguments = ["generate_m7_report.py"]
    if allow_failed:
        arguments.append("--allow-failed-acceptance")
    monkeypatch.setattr(sys, "argv", arguments)

    assert generate_m7_report.main() == expected_exit
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["acceptance_gate_passed"] is accepted
    assert receipt["determinism_status"] == "passed"
    assert receipt["execution_determinism_status"] == "passed"
    assert receipt["first_execution_id"] == "execution-first"
    assert receipt["second_execution_id"] == "execution-second"
