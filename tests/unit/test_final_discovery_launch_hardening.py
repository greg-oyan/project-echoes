"""Billing metadata and preflight contracts for the production launcher."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "cloud" / "launch_final_discovery.sh"
ADAPTER = ROOT / "cloud" / "launch_final_discovery_scaleway.sh"
SCALEWAY_ENV = ROOT / "cloud" / "final-discovery-scaleway.env.example"


def test_launcher_has_true_no_service_preflight_boundary() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "--preflight-only" in script
    assert 'if [[ "$launch_mode" == preflight ]]; then' in script
    assert "FINAL_DISCOVERY_PREFLIGHT_COMPLETE" in script
    assert '"service_created": False' in script
    assert script.index('if [[ "$launch_mode" == preflight ]]; then') < script.index(
        'launch_id="$(date -u'
    )


def test_preflight_authenticates_exact_m7_remote_identity() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "inventory.object_count != 18_606" in script
    assert "inventory.total_size != 18_413_699_180" in script
    assert "remote M7 table-hashes.json differs" in script
    assert "canonical M7 remote identity or credentials failed preflight" in script


def test_billing_is_unknown_without_a_fabricated_dollar_guarantee() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    assert '"billing_status": "unknown"' in script
    assert '"dollar_cap_enforced": False' in script
    assert '"verified_accrued_infrastructure_usd": None' in script
    assert '"projected_all_in_usd": None' in script
    assert "projected_all_in > cap" not in script


def test_scaleway_adapter_retains_worker_without_poweroff_on_preparation_errors() -> None:
    adapter = ADAPTER.read_text(encoding="utf-8")
    assert "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96" in adapter
    assert '"maximum_worker_hours": 96,' in adapter
    assert '--property="RuntimeMaxSec=${remaining_runtime_seconds}s"' in adapter
    assert '"billing_status": "unknown",' in adapter
    assert '"dollar_cap_enforced": False,' in adapter
    assert "trap cleanup EXIT" in adapter
    assert "trap 'exit 1' HUP INT TERM" in adapter
    assert 'bash "$POWER_OFF_GUARD" --verify-only' in adapter
    assert 'bash "$POWER_OFF_GUARD" --poweroff' not in adapter
    assert 'bash "$adapter" "$@"' in adapter
    assert "poweroff_if_unsuccessful" not in adapter


def test_scaleway_environment_template_has_resources_without_cost_inputs() -> None:
    example = SCALEWAY_ENV.read_text(encoding="utf-8")
    for token in (
        "ECHOES_EXPECTED_SERVER_TYPE=POP2-16C-64G",
        "ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS=96",
    ):
        assert token in example
    for token in ("ECHOES_HARD_BUDGET_USD=", "ECHOES_ACCRUED_", "ECHOES_VERIFIED_RATE_"):
        assert token not in example
