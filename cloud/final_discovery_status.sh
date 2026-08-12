#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/project-echoes/final-discovery.env"
readonly STATE_ROOT="/var/lib/project-echoes/final-discovery"
readonly UNIT_NAME="echoes-final-discovery.service"

usage() {
    cat <<'EOF'
Usage: sudo bash /srv/project-echoes/repo/cloud/final_discovery_status.sh

Take exactly one bounded service/checkpoint/filesystem snapshot and exit.
This command never sleeps, retries, follows logs, polls, or changes campaign
state. It does not print service credentials or log contents.
EOF
}

if (($#)); then
    case "$1" in
        -h|--help)
            (($# == 1)) || { usage >&2; exit 2; }
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
fi

if [[ $EUID -ne 0 ]]; then
    printf 'final_discovery_status.sh must run as root (use sudo).\n' >&2
    exit 1
fi
if [[ ! -f "$ENV_FILE" || -L "$ENV_FILE" ]]; then
    printf 'Protected service environment is missing or unsafe.\n' >&2
    exit 1
fi

python3 - "$ENV_FILE" "$STATE_ROOT" "$UNIT_NAME" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

env_path = Path(sys.argv[1])
state_root = Path(sys.argv[2])
unit_name = sys.argv[3]


def read_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not name or name in values:
            raise SystemExit("service environment is malformed")
        values[name] = value
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bounded_json(path: Path, maximum_bytes: int = 2 * 1024 * 1024) -> tuple[Any, str | None]:
    if not path.is_file() or path.is_symlink():
        return None, "missing_or_unsafe"
    try:
        size = path.stat().st_size
        if size > maximum_bytes:
            return None, "exceeds_status_read_bound"
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "unreadable_or_invalid_json"


def service_snapshot() -> dict[str, object]:
    properties = (
        "Id",
        "LoadState",
        "ActiveState",
        "SubState",
        "Result",
        "MainPID",
        "ExecMainCode",
        "ExecMainStatus",
        "ExecMainStartTimestamp",
        "ExecMainExitTimestamp",
        "CPUUsageNSec",
        "MemoryCurrent",
        "MemoryPeak",
        "MemoryHigh",
        "MemoryMax",
        "RuntimeMaxUSec",
    )
    completed = subprocess.run(
        ["systemctl", "show", unit_name, *[f"--property={name}" for name in properties]],
        check=False,
        capture_output=True,
        text=True,
    )
    result: dict[str, object] = {"query_exit_code": completed.returncode}
    numeric = {
        "MainPID",
        "ExecMainCode",
        "ExecMainStatus",
        "CPUUsageNSec",
        "MemoryCurrent",
        "MemoryPeak",
        "MemoryHigh",
        "MemoryMax",
        "RuntimeMaxUSec",
    }
    for line in completed.stdout.splitlines():
        name, separator, value = line.partition("=")
        if separator:
            result[name] = int(value) if name in numeric and value.isdigit() else value
    return result


def process_snapshot(pid_value: object) -> dict[str, object]:
    pid = pid_value if isinstance(pid_value, int) else 0
    result: dict[str, object] = {
        "pid": pid,
        "exists": False,
        "resident_bytes": None,
        "virtual_bytes": None,
    }
    status = Path(f"/proc/{pid}/status")
    if pid <= 0 or not status.is_file():
        return result
    result["exists"] = True
    try:
        for line in status.read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                result["resident_bytes"] = int(line.split()[1]) * 1024
            elif line.startswith("VmSize:"):
                result["virtual_bytes"] = int(line.split()[1]) * 1024
    except (OSError, ValueError):
        result["read_error"] = True
    return result


environment = read_environment(env_path)
for required in ("ECHOES_REPO_ROOT", "ECHOES_WORK_DIR"):
    if not environment.get(required):
        raise SystemExit(f"service environment lacks {required}")
repo_root = Path(environment["ECHOES_REPO_ROOT"])
work_root = Path(environment["ECHOES_WORK_DIR"])
stage_store = work_root / "stages"

launch_directory = state_root / "launches"
intent_paths = sorted(launch_directory.glob("*.intent.json")) if launch_directory.is_dir() else []
latest_intent = intent_paths[-1] if intent_paths else None
intent_payload: dict[str, object] | None = None
intent_error: str | None = None
intent_sha256: str | None = None
startup_path: Path | None = None
startup_payload: object = None
startup_error: str | None = None
startup_sha256: str | None = None
if latest_intent is not None:
    raw_intent, intent_error = bounded_json(latest_intent)
    if isinstance(raw_intent, dict):
        intent_payload = raw_intent
    intent_sha256 = sha256_file(latest_intent) if intent_error is None else None
    startup_path = latest_intent.with_name(latest_intent.name.replace(".intent.json", ".startup.json"))
    startup_payload, startup_error = bounded_json(startup_path)
    startup_sha256 = sha256_file(startup_path) if startup_error is None else None

stage_specs = (
    (1, "authenticate_materialize_inputs"),
    (2, "semantic_representations_indexes"),
    (3, "semantic_candidate_evidence"),
    (4, "grammatical_syntactic_evidence"),
    (5, "structural_narrative_evidence"),
    (6, "anomaly_evidence"),
    (7, "empirical_null_controls"),
    (8, "transparent_final_ensemble"),
    (9, "tier_a_tier_b_outputs"),
    (10, "strict_validation"),
    (11, "package_upload_verify"),
)
stages: list[dict[str, object]] = []
artifact_roots: dict[int, Path] = {}
for number, stage_id in stage_specs:
    root = stage_store / f"{number:02d}-{stage_id}"
    completion_path = root / "completion.json"
    completion, completion_error = bounded_json(completion_path)
    summary: dict[str, object] = {
        "number": number,
        "stage_id": stage_id,
        "completion_path": str(completion_path),
        "completion_present": completion_error is None,
        "completion_read_error": completion_error,
        "completion_sha256": sha256_file(completion_path) if completion_error is None else None,
        "failure_record_count": len(tuple((root / "failures").glob("*.json"))) if (root / "failures").is_dir() else 0,
        "in_progress_attempt_count": len(tuple((root / "in-progress").iterdir())) if (root / "in-progress").is_dir() else 0,
    }
    if isinstance(completion, dict):
        summary.update(
            {
                "manifest_status": completion.get("status"),
                "attempt_id": completion.get("attempt_id"),
                "completed_at": completion.get("completed_at"),
                "code_commit": completion.get("code_commit"),
                "config_sha256": completion.get("config_sha256"),
                "output_inventory_sha256": completion.get("output_inventory_sha256"),
                "artifact_count": len(completion.get("artifacts", ())) if isinstance(completion.get("artifacts"), list) else None,
            }
        )
        raw_artifacts_root = completion.get("artifacts_root")
        if isinstance(raw_artifacts_root, str):
            relative = PurePosixPath(raw_artifacts_root)
            if not relative.is_absolute() and ".." not in relative.parts:
                artifact_roots[number] = root.joinpath(*relative.parts)
    stages.append(summary)

validation_path = artifact_roots.get(10, Path("/__absent__")) / "validation-report.json"
validation_payload, validation_error = bounded_json(validation_path)
validation_summary = {
    "path": str(validation_path),
    "read_error": validation_error,
    "passed": validation_payload.get("passed") if isinstance(validation_payload, dict) else None,
    "error_count": validation_payload.get("error_count") if isinstance(validation_payload, dict) else None,
    "authenticated_stage_count": validation_payload.get("authenticated_stage_count") if isinstance(validation_payload, dict) else None,
    "tier_a_count": validation_payload.get("tier_a_count") if isinstance(validation_payload, dict) else None,
    "tier_b_count": validation_payload.get("tier_b_count") if isinstance(validation_payload, dict) else None,
}

transfer_path = artifact_roots.get(11, Path("/__absent__")) / "transfer-verification.json"
transfer_payload, transfer_error = bounded_json(transfer_path)
transfer_action_path = artifact_roots.get(11, Path("/__absent__")) / "transfer-action.json"
transfer_action_payload, transfer_action_error = bounded_json(transfer_action_path)
transfer_summary = {
    "path": str(transfer_path),
    "read_error": transfer_error,
    "identity": transfer_payload.get("identity") if isinstance(transfer_payload, dict) else None,
    "local_inventory_sha256": transfer_payload.get("local_inventory_sha256") if isinstance(transfer_payload, dict) else None,
    "remote_inventory_sha256": transfer_payload.get("remote_inventory_sha256") if isinstance(transfer_payload, dict) else None,
    "object_count": transfer_payload.get("object_count") if isinstance(transfer_payload, dict) else None,
    "total_size": transfer_payload.get("total_size") if isinstance(transfer_payload, dict) else None,
    "action_path": str(transfer_action_path),
    "action_read_error": transfer_action_error,
    "action": transfer_action_payload.get("action") if isinstance(transfer_action_payload, dict) else None,
}

service = service_snapshot()
disk: dict[str, object]
try:
    usage = shutil.disk_usage(work_root)
    disk = {
        "path": str(work_root),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "below_checkpoint_floor": usage.free < 80 * 1024**3,
    }
except OSError:
    disk = {"path": str(work_root), "read_error": True}

completed_count = sum(item["completion_present"] is True for item in stages)
transfer_exact = (
    isinstance(transfer_payload, dict)
    and transfer_payload.get("local_inventory_sha256")
    == transfer_payload.get("remote_inventory_sha256")
    and isinstance(transfer_payload.get("object_count"), int)
    and transfer_payload["object_count"] >= 2
)
stage_evidence_complete = (
    completed_count == 11
    and isinstance(validation_payload, dict)
    and validation_payload.get("passed") is True
    and validation_payload.get("error_count") == 0
    and transfer_exact
)

report = {
    "schema_version": 1,
    "experiment_id": "final-discovery-v1",
    "inspected_at_utc": datetime.now(UTC).isoformat(),
    "one_shot": True,
    "mutated_state": False,
    "repository": str(repo_root),
    "work_directory": str(work_root),
    "service": service,
    "process": process_snapshot(service.get("MainPID")),
    "disk": disk,
    "latest_launch": {
        "intent_path": str(latest_intent) if latest_intent else None,
        "intent_sha256": intent_sha256,
        "intent_read_error": intent_error,
        "intent": intent_payload,
        "startup_path": str(startup_path) if startup_path else None,
        "startup_sha256": startup_sha256,
        "startup_read_error": startup_error,
        "startup": startup_payload,
    },
    "checkpoint_summary": {
        "completion_count": completed_count,
        "expected_completion_count": 11,
        "stages": stages,
    },
    "stage_10_validation": validation_summary,
    "stage_11_transfer_verification": transfer_summary,
    "stage_evidence_complete": stage_evidence_complete,
    "cleanup_warning": (
        "This snapshot is observational. Before server deletion, the owner must also run "
        "the documented --all validator, inspect its passing result, confirm the systemd "
        "Result is success, and preserve the B2 package/transfer receipt."
    ),
    "logs_are_not_printed": True,
}
print(json.dumps(report, indent=2, sort_keys=True))
PY
