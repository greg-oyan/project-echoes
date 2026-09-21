"""Execute the launcher's billing metadata and environment admission paths."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "cloud" / "launch_final_discovery.sh"
BILLING_NAMES = (
    "ECHOES_HARD_BUDGET_USD",
    "ECHOES_VERIFIED_RATE_USD_PER_HOUR",
    "ECHOES_RATE_VERIFIED_AT_UTC",
    "ECHOES_SERVER_CREATED_AT_UTC",
    "ECHOES_ACCRUED_INFRASTRUCTURE_USD",
    "ECHOES_ACCRUED_COST_VERIFIED_AT_UTC",
    "ECHOES_B2_COST_RESERVE_USD",
)


@pytest.mark.parametrize("legacy_value", [None, "OWNER_SET_STALE_VALUE", "999999.00"])
def test_billing_receipt_is_unknown_regardless_of_absent_or_legacy_inputs(
    legacy_value: str | None,
) -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    marker = "budget_json=\"$(python3 - <<'PY'\n"
    assert script.count(marker) == 1
    python_source, separator, _ = script.split(marker, 1)[1].partition("\nPY\n")
    assert separator
    environment = {key: value for key, value in os.environ.items() if key not in BILLING_NAMES}
    if legacy_value is not None:
        environment.update(dict.fromkeys(BILLING_NAMES, legacy_value))
    result = subprocess.run(
        [sys.executable, "-c", python_source],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt == {
        "billing_status": "unknown",
        "manual_billing_inputs_required": False,
        "dollar_cap_enforced": False,
        "verified_rate_usd_per_hour": None,
        "verified_accrued_infrastructure_usd": None,
        "maximum_worker_hours": 96,
        "projected_future_infrastructure_usd": None,
        "b2_cost_reserve_usd": None,
        "projected_all_in_usd": None,
        "hard_cap_usd": None,
    }


@pytest.mark.parametrize(
    ("legacy_inputs", "missing_required", "unexpected_name", "succeeds"),
    [
        (False, None, None, True),
        (True, None, None, True),
        (False, "B2_APPLICATION_KEY", None, False),
        (False, "ECHOES_M7_MANIFEST_SHA256", None, False),
        (False, None, "ECHOES_UNKNOWN_SETTING", False),
    ],
)
def test_actual_environment_validation_ignores_billing_but_retains_authentication_inputs(
    legacy_inputs: bool,
    missing_required: str | None,
    unexpected_name: str | None,
    succeeds: bool,
) -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    validation = script[script.index("required_names=(") : script.index("# Only nonsecret")]
    required_block = validation.split(")\n", 1)[0]
    required_names = re.findall(r"^    ([A-Z][A-Z0-9_]+)$", required_block, flags=re.MULTILINE)
    assert required_names
    assert set(required_names).isdisjoint(BILLING_NAMES)
    values = {name: "fixture" for name in required_names if name != missing_required}
    if legacy_inputs:
        values.update(dict.fromkeys(BILLING_NAMES, "OWNER_SET_UNUSED"))
    if unexpected_name is not None:
        values[unexpected_name] = "fixture"
    setup = ["declare -A environment_names=()"]
    for name, value in values.items():
        setup.extend((f"{name}={shlex.quote(value)}", f"environment_names[{name}]=1"))
    helpers = script[script.index("die() {") : script.index("require_exact() {")]
    result = subprocess.run(
        ["bash", "-eu", "-c", helpers + "\n".join(setup) + "\n" + validation],
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith("ECHOES_")
            and key not in ("B2_APPLICATION_KEY", "B2_APPLICATION_KEY_ID")
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is succeeds, result.stderr
    if not succeeds:
        assert "final-discovery launch refused:" in result.stderr
        assert (missing_required or unexpected_name) in result.stderr


@pytest.mark.parametrize(
    "example_name", ["final-discovery.env.example", "final-discovery-scaleway.env.example"]
)
def test_environment_templates_do_not_request_billing_inputs(example_name: str) -> None:
    text = (ROOT / "cloud" / example_name).read_text(encoding="utf-8")
    assert not any(f"{name}=" in text for name in BILLING_NAMES)
    assert "ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS=96" in text
