"""Static contracts for the Scaleway final-discovery provider adapter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "cloud" / "launch_final_discovery_scaleway.sh"
LAUNCHER = ROOT / "cloud" / "launch_final_discovery.sh"
ENV_EXAMPLE = ROOT / "cloud" / "final-discovery-scaleway.env.example"


def test_scaleway_adapter_binds_reviewed_provider_budget_and_full_runtime() -> None:
    script = ADAPTER.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    expected_tokens = (
        'readonly SOURCE_LAUNCHER="$REPO_ROOT/cloud/launch_final_discovery.sh"',
        "require_source_occurrence",
        "require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G",
        "require_exact ECHOES_SERVER_NAME project-echoes-final-discovery",
        "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96",
        'worker_hours = Decimal("96")',
        '"maximum_worker_hours": 96,',
        "--property=RuntimeMaxSec=96h",
        "require_exact ECHOES_HARD_BUDGET_USD 125.00",
        'cap != Decimal("125.00")',
        "verified accrued cost plus worker window and B2 reserve exceeds $125",
        "current owner-verified pricing does not fit the owner-authorized $125 all-in cap",
        'install -d -m 0710 -o root -g "$ECHOES_SERVICE_GROUP"',
        'die "service user cannot traverse the launch directory"',
        'die "service user cannot read the authenticated launch intent"',
        (
            "Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / "
            "64 GB / 400 GB Block Storage 5K"
        ),
    )
    for token in expected_tokens:
        assert token in script

    # The adapter must fail closed if any pinned upstream substitution or
    # retained runtime/launch-intent contract stops matching exactly once.
    pinned_upstream_literals = (
        "require_exact ECHOES_EXPECTED_SERVER_TYPE CCX43",
        "require_exact ECHOES_SERVER_NAME project-echoes-final-discovery-v1",
        "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96",
        'worker_hours = Decimal("96")',
        '"maximum_worker_hours": 96,',
        "--property=RuntimeMaxSec=96h",
        "require_exact ECHOES_HARD_BUDGET_USD 75.00",
        'cap != Decimal("75.00")',
        "verified accrued cost plus worker window and B2 reserve exceeds $75",
        "current owner-verified pricing does not fit the frozen $75 all-in cap",
        ('install -d -m 0700 -o root -g root "$STATE_ROOT" "$STATE_ROOT/launches" "$LOG_ROOT"'),
        'intent_sha256="$(sha256sum "$intent_path" | awk',
    )
    for literal in pinned_upstream_literals:
        assert f"require_source_occurrence '{literal}' 1" in script

    # The adapter never provisions, starts, resizes, or deletes a cloud
    # resource. Provider poweroff is delegated to the separately reviewed
    # least-privilege guard.
    forbidden = (
        "scw instance server create",
        "scw instance server delete",
        "scw instance server start",
        "scw instance server stop",
        "hcloud server create",
        "hcloud server delete",
        "curl http://169.254.169.254",
    )
    for token in forbidden:
        assert token not in script

    # Scientific identities and CPU/memory/disk ceilings remain delegated to
    # the frozen launcher. Only provider identity, the separately authorized
    # budget ceiling, launch-intent traversal, and provider-side poweroff are
    # adapted.
    delegated_tokens = (
        "CONFIG_FILE_SHA256",
        "M7_MANIFEST_SHA256",
        "ECHOES_FINAL_DISCOVERY_THREADS",
        "ECHOES_FINAL_DISCOVERY_PROCESS_MEMORY_GIB",
        "ECHOES_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_GIB",
        "ECHOES_FINAL_DISCOVERY_INITIAL_FREE_DISK_GIB",
        "ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB",
    )
    for token in delegated_tokens:
        assert token not in script


def test_scaleway_adapter_generated_launcher_authenticates_intent_as_worker(
    tmp_path: Path,
) -> None:
    """Execute the adapter's Python rewrite against the frozen launcher bytes."""

    script = ADAPTER.read_text(encoding="utf-8")
    marker = 'python3 - "$adapter" "$POWER_OFF_UNIT" <<\'PY\'\n'
    terminator = '\nPY\nchmod 0700 "$adapter"'
    assert script.count(marker) == 1
    python_source, separator, _ = script.split(marker, 1)[1].partition(terminator)
    assert separator

    launcher_copy = tmp_path / "launch_final_discovery.sh"
    launcher_copy.write_text(LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            python_source,
            str(launcher_copy),
            "echoes-final-discovery-poweroff.service",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    generated = launcher_copy.read_text(encoding="utf-8")
    expected = (
        (
            'install -d -m 0710 -o root -g "$ECHOES_SERVICE_GROUP" '
            '"$STATE_ROOT" "$STATE_ROOT/launches"'
        ),
        'install -d -m 0700 -o root -g root "$LOG_ROOT"',
        'die "service user cannot traverse the state root"',
        'die "service user cannot traverse the launch directory"',
        'worker_intent_sha256="$(',
        'die "service user cannot read the authenticated launch intent"',
        'die "service user observes a different authenticated launch intent"',
        "--property=OnSuccess=echoes-final-discovery-poweroff.service",
        "--property=OnFailure=echoes-final-discovery-poweroff.service",
    )
    for token in expected:
        assert token in generated

    assert generated.index("worker_intent_sha256") < generated.index("systemd-run")
    assert (
        'install -d -m 0700 -o root -g root "$STATE_ROOT" '
        '"$STATE_ROOT/launches" "$LOG_ROOT"' not in generated
    )


def test_scaleway_environment_authorizes_125_dollars_and_96_hours() -> None:
    environment = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS=96\n" in environment
    assert "ECHOES_HARD_BUDGET_USD=125.00\n" in environment
    assert "ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS=68\n" not in environment
    assert "ECHOES_HARD_BUDGET_USD=75.00\n" not in environment
