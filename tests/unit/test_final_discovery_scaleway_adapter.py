"""Static contracts for the Scaleway final-discovery provider adapter."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "cloud" / "launch_final_discovery_scaleway.sh"


def test_scaleway_adapter_changes_only_reviewed_provider_identity_strings() -> None:
    script = ADAPTER.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert 'readonly SOURCE_LAUNCHER="$REPO_ROOT/cloud/launch_final_discovery.sh"' in script
    assert "require_exact ECHOES_EXPECTED_SERVER_TYPE POP2-16C-64G" in script
    assert "require_exact ECHOES_SERVER_NAME project-echoes-final-discovery" in script
    assert (
        "Scaleway POP2-16C-64G / Ubuntu 24.04 / 16 dedicated AMD vCPU / "
        "64 GB / 400 GB Block Storage 5K"
    ) in script

    # The adapter must not provision, start, stop, or delete cloud resources.
    forbidden = (
        "scw instance server create",
        "scw instance server delete",
        "hcloud server create",
        "hcloud server delete",
        "curl http://169.254.169.254",
    )
    for token in forbidden:
        assert token not in script

    # Scientific/resource gates remain delegated to the frozen launcher rather
    # than being reimplemented or weakened here.
    assert "ECHOES_FINAL_DISCOVERY_THREADS" not in script
    assert "ECHOES_HARD_BUDGET_USD" not in script
    assert "CONFIG_FILE_SHA256" not in script
    assert "M7_MANIFEST_SHA256" not in script
