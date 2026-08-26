"""Static contracts for the Scaleway final-discovery provider adapter."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "cloud" / "launch_final_discovery_scaleway.sh"


def test_scaleway_adapter_binds_reviewed_provider_and_operational_cap() -> None:
    script = ADAPTER.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert 'readonly SOURCE_LAUNCHER="$REPO_ROOT/cloud/launch_final_discovery.sh"' in script
    assert "require_source_occurrence" in script
    assert "require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G" in script
    assert "require_exact ECHOES_SERVER_NAME project-echoes-final-discovery" in script
    assert "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 80" in script
    assert 'worker_hours = Decimal("80")' in script
    assert '"maximum_worker_hours": 80,' in script
    assert "--property=RuntimeMaxSec=80h" in script
    assert (
        "Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / "
        "64 GB / 400 GB Block Storage 5K"
    ) in script

    # The adapter must fail closed if any pinned upstream substitution stops
    # matching exactly once.
    pinned_upstream_literals = (
        "require_exact ECHOES_EXPECTED_SERVER_TYPE CCX43",
        "require_exact ECHOES_SERVER_NAME project-echoes-final-discovery-v1",
        "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96",
        'worker_hours = Decimal(\"96\")',
        '\"maximum_worker_hours\": 96,',
        "--property=RuntimeMaxSec=96h",
    )
    for literal in pinned_upstream_literals:
        assert f"require_source_occurrence '{literal}' 1" in script

    # The adapter never provisions, starts, stops, resizes, or deletes a cloud
    # resource. It only invokes the frozen owner launcher on an already-created
    # host.
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
    # the frozen launcher. Only the provider identity and separately authorized
    # operational stop are adapted.
    assert "CONFIG_FILE_SHA256" not in script
    assert "M7_MANIFEST_SHA256" not in script
    assert "ECHOES_FINAL_DISCOVERY_THREADS" not in script
    assert "ECHOES_FINAL_DISCOVERY_PROCESS_MEMORY_GIB" not in script
    assert "ECHOES_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_GIB" not in script
    assert "ECHOES_FINAL_DISCOVERY_INITIAL_FREE_DISK_GIB" not in script
    assert "ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB" not in script
    assert "ECHOES_HARD_BUDGET_USD" not in script
