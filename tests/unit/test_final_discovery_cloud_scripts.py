"""Static fail-closed contracts for the owner-only final-discovery launcher."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCH = ROOT / "cloud" / "launch_final_discovery.sh"
STATUS = ROOT / "cloud" / "final_discovery_status.sh"
CLEANUP_VERIFY = ROOT / "cloud" / "verify_final_discovery_cleanup.sh"
ENV_EXAMPLE = ROOT / "cloud" / "final-discovery.env.example"
RUNBOOK = ROOT / "docs" / "final-discovery-cloud-runbook.md"
CONFIG = ROOT / "config" / "experiments" / "final-discovery-v1.yaml"

CONFIG_SHA256 = "a38c2f6d1c3d84264c7b81a8a62c3a84cae8b993894f6634e339958cdc1f76b0"
M7_SHA256 = "e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_launcher_has_exact_detached_resource_and_scientific_contract() -> None:
    script = _text(LAUNCH)

    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert 'readonly ENV_FILE="/etc/project-echoes/final-discovery.env"' in script
    assert "systemd-run" in script
    assert "--property=Restart=no" in script
    assert "--property=RuntimeMaxSec=96h" in script
    assert "--property=MemoryMax=56G" in script
    assert "--property=MemorySwapMax=0" in script
    assert "--property=CPUQuota=1200%" in script
    assert "--setenv=CUDA_VISIBLE_DEVICES=-1" in script
    assert "--setenv=NVIDIA_VISIBLE_DEVICES=void" in script
    assert 'chmod 0400 "$stdout_log" "$stderr_log"' in script
    assert "ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB 80" in script
    assert "available_bytes >= 280 * 1024 * 1024 * 1024" in script
    assert "ECHOES_HARD_BUDGET_USD 75.00" in script
    assert "projected_all_in > cap" in script
    assert "require_exact ECHOES_AUTHORIZE_PRODUCTION final-discovery-v1" in script
    assert 'knownness_receipt_path="${ECHOES_KNOWNNESS_PATH%.jsonl}.receipt.json"' in script
    assert "service user cannot read the knownness projection receipt" in script
    assert f'readonly M7_MANIFEST_SHA256="{M7_SHA256}"' in script
    assert f'readonly CONFIG_FILE_SHA256="{CONFIG_SHA256}"' in script
    assert "validate-final-discovery-model-runtime --json" in script
    assert "inspect-final-discovery-output" in script
    assert "ECHOES_MANAGED_LAUNCH_ID" in script
    assert "ECHOES_MANAGED_LAUNCH_INTENT_PATH" in script
    assert "ECHOES_MANAGED_LAUNCH_INTENT_SHA256" in script
    assert 'chown "root:$ECHOES_SERVICE_GROUP" "$intent_path"' in script

    expected_arguments = (
        "run-final-discovery",
        "--production",
        "--work-dir",
        "--prepared-passages",
        "--knownness-path",
        "--offline-model-root",
        "--m7-bucket",
        "--m7-prefix",
        "--output-bucket",
        "--output-prefix",
    )
    for argument in expected_arguments:
        assert argument in script


def test_launcher_never_provisions_polls_or_places_secrets_on_command_line() -> None:
    script = _text(LAUNCH)
    operational_lines = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )

    assert "hcloud server create" not in script
    assert "hcloud server delete" not in script
    assert "journalctl -f" not in script
    assert not re.search(r"^\s*(sleep|watch)\b", operational_lines, flags=re.MULTILINE)
    assert "Restart=always" not in script
    assert "Restart=on-failure" not in script
    assert "--setenv=B2_APPLICATION_KEY" not in script
    assert "--setenv=B2_APPLICATION_KEY_ID" not in script
    assert '--property="EnvironmentFile=$ENV_FILE"' in script
    assert '"B2_APPLICATION_KEY": "present_not_recorded"' in script
    assert '"B2_APPLICATION_KEY_ID": "present_not_recorded"' in script


def test_status_is_one_shot_read_only_and_does_not_emit_logs_or_secrets() -> None:
    script = _text(STATUS)
    operational_lines = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )

    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert '"one_shot": True' in script
    assert '"mutated_state": False' in script
    assert '"logs_are_not_printed": True' in script
    assert "subprocess.run(" in script
    assert not re.search(r"^\s*(sleep|watch)\b", operational_lines, flags=re.MULTILINE)
    assert "journalctl" not in script
    assert "systemctl start" not in script
    assert "systemctl stop" not in script
    assert "systemctl restart" not in script
    assert "B2_APPLICATION_KEY" not in script
    assert "stdout_tail" not in script
    assert "stderr_tail" not in script


def test_cleanup_verification_is_one_shot_preserving_and_non_destructive() -> None:
    script = _text(CLEANUP_VERIFY)
    operational_lines = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )

    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert "verify-final-discovery-finalization" in script
    assert "cleanup-verifications" in script
    assert "cleanup_finalization_reauthenticated" in script
    assert "initial_full_content_check_bound_by_checkpoint_receipt" in script
    assert "failed.json" in script
    assert script.count('mv -- "$temporary_path" "$failed_path"') == 2
    assert "cleanup receipt validation did not pass; preserved $failed_path" in script
    assert not re.search(r"^\s*(sleep|watch)\b", operational_lines, flags=re.MULTILINE)
    assert "journalctl" not in script
    assert "systemctl start" not in script
    assert "systemctl stop" not in script
    assert "hcloud server delete" not in script
    assert "rclone delete" not in script


def test_environment_template_requires_exact_identity_resources_and_secrets() -> None:
    example = _text(ENV_EXAMPLE)

    required = {
        "ECHOES_AUTHORIZE_PRODUCTION": "final-discovery-v1",
        "ECHOES_EXPECTED_SERVER_TYPE": "CCX43",
        "ECHOES_SERVER_NAME": "project-echoes-final-discovery-v1",
        "ECHOES_FINAL_DISCOVERY_THREADS": "12",
        "ECHOES_FINAL_DISCOVERY_PROCESS_MEMORY_GIB": "56",
        "ECHOES_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_GIB": "40",
        "ECHOES_FINAL_DISCOVERY_INITIAL_FREE_DISK_GIB": "280",
        "ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB": "80",
        "ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS": "96",
        "ECHOES_HARD_BUDGET_USD": "75.00",
        "ECHOES_M7_MANIFEST_SHA256": M7_SHA256,
    }
    for name, value in required.items():
        assert f"{name}={value}" in example
    for name in (
        "ECHOES_EXPECTED_GIT_COMMIT",
        "ECHOES_REPO_ROOT",
        "ECHOES_WORK_DIR",
        "ECHOES_PREPARED_PASSAGES",
        "ECHOES_KNOWNNESS_PATH",
        "ECHOES_MODEL_ROOT",
        "ECHOES_OUTPUT_BUCKET",
        "ECHOES_OUTPUT_PREFIX",
        "B2_APPLICATION_KEY_ID",
        "B2_APPLICATION_KEY",
        "ECHOES_RATE_VERIFIED_AT_UTC",
        "ECHOES_SERVER_CREATED_AT_UTC",
        "ECHOES_ACCRUED_INFRASTRUCTURE_USD",
        "ECHOES_ACCRUED_COST_VERIFIED_AT_UTC",
        "ECHOES_ACCRUED_INFRASTRUCTURE_USD",
        "ECHOES_ACCRUED_COST_VERIFIED_AT_UTC",
    ):
        assert re.search(rf"^{name}=\S+$", example, flags=re.MULTILINE)


def test_runbook_has_exact_owner_launch_status_validation_and_cleanup_gates() -> None:
    runbook = _text(RUNBOOK)

    assert "sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery.sh" in runbook
    assert "sudo bash /srv/project-echoes/repo/cloud/final_discovery_status.sh" in runbook
    assert "sudo bash /srv/project-echoes/repo/cloud/verify_final_discovery_cleanup.sh" in runbook
    assert "echoes validate-final-discovery --all --work-dir" in runbook
    assert "hcloud server describe project-echoes-final-discovery-v1 -o json" in runbook
    assert "hcloud server delete project-echoes-final-discovery-v1" in runbook
    assert "identical exact local and" in runbook
    assert "remote inventory SHA-256 values" in runbook
    assert "Do not use `watch`" in runbook
    assert "A second full production" in runbook


def test_frozen_config_byte_hash_is_current() -> None:
    assert hashlib.sha256(CONFIG.read_bytes()).hexdigest() == CONFIG_SHA256
