"""Static contracts for the least-privilege Scaleway auto-poweroff guard."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "cloud" / "scaleway_poweroff_guard.sh"
INSTALLER = ROOT / "cloud" / "install_scaleway_poweroff_guard.sh"
PREFLIGHT = ROOT / "cloud" / "preflight_final_discovery_scaleway.sh"
UNIT = ROOT / "cloud" / "echoes-final-discovery-poweroff.service"
ENV_EXAMPLE = ROOT / "cloud" / "scaleway-poweroff.env.example"
ADAPTER = ROOT / "cloud" / "launch_final_discovery_scaleway.sh"


def test_guard_has_verify_and_true_provider_poweroff_modes() -> None:
    script = GUARD.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert "--verify-only" in script
    assert "--poweroff" in script
    assert '"${server_url}/action"' in script
    assert "SCALEWAY_POWEROFF_REQUEST_ACCEPTED" in script
    assert "SCALEWAY_POWEROFF_GUARD_VERIFIED" in script
    assert "poweron" not in script
    assert "delete" not in script.lower()


def test_guard_never_places_secret_on_argv_or_output() -> None:
    script = GUARD.read_text(encoding="utf-8")

    assert "printf 'X-Auth-Token: %s\\n' \"$SCW_SECRET_KEY\"" in script
    assert '--header "@$header_file"' in script
    assert '-H "X-Auth-Token: $SCW_SECRET_KEY"' not in script
    assert 'printf "%s" "$SCW_SECRET_KEY"' not in script


def test_guard_binds_exact_instance_identity_and_least_privilege_template() -> None:
    script = GUARD.read_text(encoding="utf-8")
    example = ENV_EXAMPLE.read_text(encoding="utf-8")

    for token in (
        "SCW_INSTANCE_ZONE",
        "SCW_INSTANCE_ID",
        "SCW_INSTANCE_NAME",
        "SCW_INSTANCE_TYPE",
        "project-echoes-final-discovery",
        "POP2-16C-64G",
    ):
        assert token in script
    assert "InstancesReadOnly" in example
    assert "InstancesServerStop" in example
    assert "only once" in example


def test_poweroff_unit_is_bounded_and_retries_only_the_api_request() -> None:
    unit = UNIT.read_text(encoding="utf-8")

    assert "Type=oneshot" in unit
    assert "Restart=on-failure" in unit
    assert "RestartSec=30s" in unit
    assert "StartLimitBurst=5" in unit
    assert "TimeoutStartSec=2min" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "ProtectSystem=strict" in unit
    assert "scaleway_poweroff_guard.sh --poweroff" in unit


def test_installer_only_installs_and_verifies_guard() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    operational = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )

    assert "systemctl daemon-reload" in script
    assert 'bash "$GUARD" --verify-only' in script
    assert "SCALEWAY_POWEROFF_GUARD_INSTALLED" in script
    assert "systemctl start" not in operational
    assert "--poweroff" not in operational


def test_preflight_always_requests_provider_poweroff_and_preserves_result() -> None:
    script = PREFLIGHT.read_text(encoding="utf-8")

    assert 'bash "$ADAPTER" --preflight-only || preflight_status=$?' in script
    assert 'bash "$POWER_OFF_GUARD" --poweroff || poweroff_status=$?' in script
    assert "SCALEWAY_PREFLIGHT_POWERDOWN_REQUESTED" in script
    assert 'exit "$preflight_status"' in script
    assert "systemd-run" not in script


def test_scaleway_adapter_binds_poweroff_after_success_and_failure_once() -> None:
    script = ADAPTER.read_text(encoding="utf-8")

    assert "scaleway_poweroff_guard.sh" in script
    assert 'bash "$POWER_OFF_GUARD" --verify-only' in script
    assert script.count("--property=OnSuccess=echoes-final-discovery-poweroff.service") == 1
    assert script.count("--property=OnFailure=echoes-final-discovery-poweroff.service") == 1
    assert script.count('exec bash "$adapter" "$@"') == 1
    assert not re.search(r'exec bash "\$adapter"(?: "\$@"){2,}', script)
