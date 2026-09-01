"""Cost and preflight contracts for the production owner launcher."""

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


def test_budget_uses_verified_accrued_cost_not_server_wall_clock() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "ECHOES_ACCRUED_INFRASTRUCTURE_USD" in script
    assert "ECHOES_ACCRUED_COST_VERIFIED_AT_UTC" in script
    assert "projected_all_in = accrued + projected_future_infrastructure + reserve" in script
    assert "accrued_hours" not in script


def test_scaleway_adapter_retains_worker_and_protects_pre_worker_failures() -> None:
    adapter = ADAPTER.read_text(encoding="utf-8")
    assert "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96" in adapter
    assert 'worker_hours = Decimal("96")' in adapter
    assert '"maximum_worker_hours": 96,' in adapter
    assert "--property=RuntimeMaxSec=96h" in adapter
    assert "require_exact ECHOES_HARD_BUDGET_USD 150.00" in adapter
    assert 'cap != Decimal("150.00")' in adapter
    assert "trap cleanup EXIT" in adapter
    assert "trap 'exit 1' HUP INT TERM" in adapter
    assert 'bash "$POWER_OFF_GUARD" --poweroff' in adapter
    assert 'bash "$adapter" "$@"' in adapter
    assert "poweroff_if_unsuccessful=false" in adapter


def test_scaleway_environment_template_contains_every_cost_input() -> None:
    example = SCALEWAY_ENV.read_text(encoding="utf-8")
    for token in (
        "ECHOES_EXPECTED_SERVER_TYPE=POP2-16C-64G",
        "ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS=96",
        "ECHOES_HARD_BUDGET_USD=150.00",
        "ECHOES_ACCRUED_INFRASTRUCTURE_USD=",
        "ECHOES_ACCRUED_COST_VERIFIED_AT_UTC=",
        "ECHOES_B2_COST_RESERVE_USD=10.00",
    ):
        assert token in example
