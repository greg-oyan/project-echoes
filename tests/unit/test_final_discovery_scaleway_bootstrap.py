"""Static safety contracts for the Scaleway final-discovery bootstrap."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "cloud" / "bootstrap_final_discovery_scaleway.sh"


def _script() -> str:
    return BOOTSTRAP.read_text(encoding="utf-8")


def test_bootstrap_has_separate_preflight_and_execute_modes() -> None:
    script = _script()

    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert "--preflight-only" in script
    assert "--execute" in script
    assert 'if [[ "$MODE" == preflight ]]; then' in script
    assert "PREFLIGHT_COMPLETE" in script
    assert "BOOTSTRAP_COMPLETE" in script


def test_bootstrap_parses_uv_numeric_version_instead_of_full_output() -> None:
    script = _script()

    expected = "/usr/local/bin/uv -V | awk 'NR == 1 {print $2}'"
    assert script.count(expected) == 2
    assert '[[ "$observed_uv_version" == "$UV_VERSION" ]]' in script
    assert '[[ "$(/usr/local/bin/uv --version)" ==' not in script


def test_bootstrap_uses_valid_df_invocation_and_fail_closed_host_identity() -> None:
    script = _script()

    assert "df -B1 --output=avail /" in script
    assert "df -P -B1 --output=avail" not in script
    assert "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256" in script
    assert '[[ "$(nproc --all)" == 16 ]]' in script
    assert "less than 60 GiB RAM is visible" in script
    assert "less than 300 GiB disk is available" in script
    assert "origin/main differs" in script


def test_preflight_does_not_install_clone_sync_or_download_model_bodies() -> None:
    script = _script()
    preflight_boundary = script.index('if [[ "$MODE" == preflight ]]; then')
    execute_body = script[preflight_boundary:]

    assert "apt-get install" in execute_body
    assert "git clone" in execute_body
    assert "uv sync --locked --all-groups" in execute_body
    assert "hf_hub_download" in execute_body
    assert "--head" in script[:preflight_boundary]


def test_bootstrap_never_manages_cloud_resources_or_scientific_configuration() -> None:
    script = _script()
    operational_lines = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )

    forbidden = (
        "scw instance server create",
        "scw instance server delete",
        "hcloud server create",
        "hcloud server delete",
        "config/experiments/final-discovery-v1.yaml >",
        "sed -i config/experiments",
    )
    for token in forbidden:
        assert token not in operational_lines
    assert not re.search(r"^\s*(sleep|watch)\b", operational_lines, flags=re.MULTILINE)


def test_bootstrap_writes_a_root_owned_completion_receipt() -> None:
    script = _script()

    assert 'readonly STATE_ROOT="/var/lib/project-echoes/final-discovery/bootstrap"' in script
    assert '"passed": True' in script
    assert 'install -m 0400 -o root -g root "$receipt_staging"' in script
