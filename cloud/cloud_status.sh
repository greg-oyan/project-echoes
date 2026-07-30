#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: cloud_status.sh [--log-lines N]

Take exactly one service/filesystem/process snapshot and exit. This script
never polls, sleeps, or waits for state to change.
EOF
}

ENV_FILE="/etc/project-echoes/m7.env"
LOG_LINES=30

while (($#)); do
    case "$1" in
        --log-lines)
            (($# >= 2)) || { usage >&2; exit 2; }
            LOG_LINES="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done
[[ "$LOG_LINES" =~ ^[0-9]+$ ]] && ((LOG_LINES >= 1 && LOG_LINES <= 500)) || {
    printf -- '--log-lines must be an integer from 1 through 500.\n' >&2
    exit 2
}
if [[ $EUID -ne 0 ]]; then
    printf 'cloud_status.sh must run as root (use sudo) to inspect protected logs.\n' >&2
    exit 1
fi
if [[ ! -r "$ENV_FILE" ]]; then
    printf 'Service environment is missing.\n' >&2
    exit 1
fi

python3 - "$ENV_FILE" "$LOG_LINES" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

env_file = Path(sys.argv[1])
log_lines = int(sys.argv[2])
environment: dict[str, str] = {}
for raw_line in env_file.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    name, separator, value = line.partition("=")
    if not separator:
        raise SystemExit(f"malformed service environment line: {raw_line!r}")
    environment[name] = value

repo = Path(environment["ECHOES_REPO_ROOT"])
canonical = Path(environment["ECHOES_OUTPUT_DIRECTORY"])
configured_staging = Path(environment["ECHOES_RESUME_STAGING"])
state_root = Path(environment["ECHOES_STATE_ROOT"])
log_root = Path(environment["ECHOES_LOG_ROOT"])
lexical_parent = canonical.parent
promotion_journal = Path(
    environment.get(
        "ECHOES_PROMOTION_JOURNAL",
        str(lexical_parent / ".schema-v1.promotion-intent.json"),
    )
)


def command(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, check=False, capture_output=True, text=True)


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
    "TasksCurrent",
    "RuntimeMaxUSec",
)
service_result = command(
    ["systemctl", "show", "echoes-m7.service", *[f"--property={item}" for item in properties]]
)
service: dict[str, Any] = {}
for line in service_result.stdout.splitlines():
    key, separator, value = line.partition("=")
    if separator:
        service[key] = value
for key in (
    "MainPID",
    "ExecMainCode",
    "ExecMainStatus",
    "CPUUsageNSec",
    "MemoryCurrent",
    "MemoryPeak",
    "MemoryHigh",
    "MemoryMax",
    "TasksCurrent",
    "RuntimeMaxUSec",
):
    raw = service.get(key, "")
    service[key] = int(raw) if str(raw).isdigit() else None

pid = service.get("MainPID") or 0
process: dict[str, Any] = {
    "pid": pid,
    "elapsed_seconds": None,
    "cpu_time": None,
    "resident_bytes": None,
    "virtual_committed_bytes": None,
    "command_line": None,
}
if pid and Path(f"/proc/{pid}").exists():
    ps = command(["ps", "-p", str(pid), "-o", "etimes=", "-o", "cputime=", "-o", "args="])
    if ps.returncode == 0 and ps.stdout.strip():
        match = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)", ps.stdout.strip())
        if match:
            process["elapsed_seconds"] = int(match.group(1))
            process["cpu_time"] = match.group(2)
            process["command_line"] = match.group(3)
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                process["resident_bytes"] = int(line.split()[1]) * 1024
            elif line.startswith("VmSize:"):
                process["virtual_committed_bytes"] = int(line.split()[1]) * 1024
    except OSError:
        pass


def directory_size(path: Path) -> int:
    if not path.is_dir() or path.is_symlink():
        return 0
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [
            name for name in directories if not (Path(root) / name).is_symlink()
        ]
        for name in files:
            candidate = Path(root) / name
            if not candidate.is_symlink():
                try:
                    total += candidate.stat().st_size
                except OSError:
                    pass
    return total


def partition_counts(path: Path) -> dict[str, int]:
    if not path.is_dir() or path.is_symlink():
        return {}
    result: dict[str, int] = {}
    for child in sorted(path.iterdir(), key=lambda item: item.name):
        if child.is_dir() and not child.is_symlink() and not child.name.startswith("."):
            result[child.name] = sum(
                1
                for part in child.glob("part-*.parquet")
                if part.is_file() and not part.is_symlink()
            )
    return result


def latest_output(path: Path) -> dict[str, Any] | None:
    if not path.is_dir() or path.is_symlink():
        return None
    latest: tuple[int, Path] | None = None
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [
            name for name in directories if not (Path(root) / name).is_symlink()
        ]
        for name in files:
            candidate = Path(root) / name
            if candidate.is_symlink():
                continue
            try:
                modified = candidate.stat().st_mtime_ns
            except OSError:
                continue
            if latest is None or modified > latest[0]:
                latest = (modified, candidate)
    if latest is None:
        return None
    return {
        "path": str(latest[1]),
        "modified_at_utc": datetime.fromtimestamp(
            latest[0] / 1_000_000_000, tz=UTC
        ).isoformat(),
    }


staging_candidates = []
if lexical_parent.is_dir():
    staging_candidates = sorted(
        (
            child
            for child in lexical_parent.iterdir()
            if child.is_dir()
            and not child.is_symlink()
            and re.fullmatch(r"\.schema-v1\.writing-[0-9a-fA-F]{32}", child.name)
        ),
        key=lambda child: child.name,
    )

staging_reports: list[dict[str, Any]] = []
for staging in staging_candidates:
    checkpoint = staging / ".resume-primary-candidates"
    tier3 = checkpoint / "tier3-evaluation"
    staging_reports.append(
        {
            "path": str(staging),
            "configured": staging.resolve() == configured_staging.resolve(),
            "size_bytes": directory_size(staging),
            "primary_checkpoint_part_count": (
                sum(1 for item in checkpoint.glob("part-*.parquet") if item.is_file())
                if checkpoint.is_dir()
                else 0
            ),
            "primary_checkpoint_manifest_exists": (
                checkpoint.joinpath("complete.json").is_file()
            ),
            "tier3_checkpoint_part_count": (
                sum(1 for item in tier3.glob("*.parquet") if item.is_file())
                if tier3.is_dir()
                else 0
            ),
            "tier3_checkpoint_manifest_count": (
                sum(1 for item in tier3.glob("*.json") if item.is_file())
                if tier3.is_dir()
                else 0
            ),
            "partition_counts": partition_counts(staging),
            "latest_output": latest_output(staging),
        }
    )

launch: dict[str, Any] = {}
latest_launch = state_root / "latest-launch.json"
if latest_launch.is_file():
    try:
        launch = json.loads(latest_launch.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        launch = {"read_error": str(exc)}


def tail(path_value: object) -> list[str]:
    if not isinstance(path_value, str):
        return []
    path = Path(path_value)
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-log_lines:]
    except OSError as exc:
        return [f"<log read failed: {exc}>"]


def read_pointer(name: str) -> str | None:
    path = state_root / name
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def bounded_json(path: Path, *, maximum_bytes: int = 65_536) -> tuple[dict[str, Any] | None, str | None, int | None, str | None]:
    if path.is_symlink():
        return None, None, None, "path is a symlink"
    if not path.is_file():
        return None, None, None, "path is not a regular file"
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, None, None, str(exc)
    if size > maximum_bytes:
        return None, None, size, f"file exceeds the {maximum_bytes}-byte status bound"
    try:
        content = path.read_bytes()
        payload = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, None, size, str(exc)
    if not isinstance(payload, dict):
        return None, hashlib.sha256(content).hexdigest(), size, "JSON root is not an object"
    return payload, hashlib.sha256(content).hexdigest(), size, None


def promotion_journal_details(path: Path, *, active: bool) -> dict[str, Any]:
    exists = path.exists() or path.is_symlink()
    report: dict[str, Any] = {
        "path": str(path),
        "active": active,
        "exists": exists,
        "safe_regular_file": False,
        "size_bytes": None,
        "sha256": None,
        "details": None,
    }
    if not exists:
        return report
    payload, digest, size, error = bounded_json(path)
    report["size_bytes"] = size
    report["sha256"] = digest
    if error is not None:
        report["read_error"] = error
        return report
    assert payload is not None
    expected_keys = {
        "schema_version",
        "output_dir",
        "staging_dir",
        "backup_dir",
        "database_path",
        "execution_manifest_path",
        "execution_id",
        "promotion_id",
        "table_hash_manifest_sha256",
    }
    if set(payload) != expected_keys:
        report["read_error"] = "journal JSON has an unexpected schema"
        return report
    string_fields = expected_keys.difference({"schema_version"})
    if (
        payload.get("schema_version") != 1
        or any(not isinstance(payload.get(name), str) or not payload[name] for name in string_fields)
        or not re.fullmatch(
            r"[0-9a-f]{64}",
            str(payload.get("table_hash_manifest_sha256", "")),
        )
        or not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("promotion_id", "")))
        or not re.fullmatch(
            r"[A-Za-z0-9._-]+",
            str(payload.get("execution_id", "")),
        )
    ):
        report["read_error"] = "journal JSON contains invalid governed values"
        return report
    report["safe_regular_file"] = True
    report["details"] = {
        "schema_version": payload["schema_version"],
        "output_dir": payload["output_dir"],
        "staging_dir": payload["staging_dir"],
        "backup_dir": payload["backup_dir"],
        "database_path": payload["database_path"],
        "execution_manifest_path": payload["execution_manifest_path"],
        "execution_id": payload["execution_id"],
        "promotion_id": payload["promotion_id"],
        "table_hash_manifest_sha256": payload["table_hash_manifest_sha256"],
    }
    return report


def recovery_receipt_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    payload, digest, size, error = bounded_json(path)
    report: dict[str, Any] = {
        "path": str(path),
        "size_bytes": size,
        "sha256": digest,
    }
    if error is not None:
        report["read_error"] = error
        return report
    assert payload is not None
    report.update(
        {
            "receipt_path": payload.get("receipt_path"),
            "passed": payload.get("passed"),
            "cli_exit_code": payload.get("cli_exit_code"),
            "cli_output_bytes": payload.get("cli_output_bytes"),
            "recovered_at_utc": payload.get("recovered_at_utc"),
            "state": payload.get("state"),
            "canonical_output_present": payload.get("canonical_output_present"),
            "journal_path": payload.get("journal_path"),
            "journal_before_exists": payload.get("journal_before_exists"),
            "journal_before_sha256": payload.get("journal_before_sha256"),
            "archived_journal": payload.get("archived_journal"),
            "archived_journal_sha256": payload.get("archived_journal_sha256"),
            "commit_witness": payload.get("commit_witness"),
            "journal_after_exists": payload.get("journal_after_exists"),
        }
    )
    return report


def finalization_receipt_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    payload, digest, size, error = bounded_json(path)
    report: dict[str, Any] = {
        "path": str(path),
        "size_bytes": size,
        "sha256": digest,
    }
    if error is not None:
        report["read_error"] = error
        return report
    assert payload is not None
    report.update(
        {
            "receipt_path": payload.get("receipt_path"),
            "required": payload.get("required"),
            "passed": payload.get("passed"),
            "finalized_at_utc": payload.get("finalized_at_utc"),
            "cli_exit_code": payload.get("cli_exit_code"),
            "journal_path": payload.get("journal_path"),
            "journal_before_sha256": payload.get("journal_before_sha256"),
            "journal_archive": payload.get("journal_archive"),
            "journal_archive_sha256": payload.get("journal_archive_sha256"),
            "journal_after_exists": payload.get("journal_after_exists"),
            "validation_report": payload.get("validation_report"),
            "validation_report_sha256": payload.get("validation_report_sha256"),
            "service_result": payload.get("service_result"),
        }
    )
    return report


def transient_task(kind: str) -> dict[str, Any]:
    unit = read_pointer(f"latest-{kind}-unit.txt")
    stdout_path = read_pointer(f"latest-{kind}-stdout.txt")
    stderr_path = read_pointer(f"latest-{kind}-stderr.txt")
    task: dict[str, Any] = {
        "unit": unit,
        "service": None,
        "stdout_path": stdout_path,
        "stdout_tail": tail(stdout_path),
        "stderr_path": stderr_path,
        "stderr_tail": tail(stderr_path),
    }
    if unit:
        result = command(
            [
                "systemctl",
                "show",
                unit,
                "--property=LoadState",
                "--property=ActiveState",
                "--property=SubState",
                "--property=Result",
                "--property=MainPID",
            ]
        )
        snapshot: dict[str, Any] = {"query_exit_code": result.returncode}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                snapshot[key] = int(value) if key == "MainPID" and value.isdigit() else value
        task["service"] = snapshot
    return task


validation_summary: dict[str, Any] | None = None
latest_validation = state_root / "latest-validation.json"
if latest_validation.is_file() and not latest_validation.is_symlink():
    try:
        validation_payload = json.loads(latest_validation.read_text(encoding="utf-8"))
        validation_summary = {
            "path": str(latest_validation),
            "passed": validation_payload.get("passed"),
            "validated_at_utc": validation_payload.get("validated_at_utc"),
            "current_database_sha256": validation_payload.get("current_database_sha256"),
            "service_completion": validation_payload.get("service_completion"),
            "lexical_promotion": validation_payload.get("lexical_promotion"),
        }
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        validation_summary = {"path": str(latest_validation), "read_error": str(exc)}

active_promotion_journal = promotion_journal_details(promotion_journal, active=True)
discovered_promotion_paths: set[Path] = {promotion_journal}
for parent in (lexical_parent, state_root):
    if not parent.is_dir() or parent.is_symlink():
        continue
    try:
        for candidate in parent.iterdir():
            if re.fullmatch(r"\.schema-v1\.promotion-[A-Za-z0-9._-]+\.json", candidate.name):
                discovered_promotion_paths.add(candidate)
    except OSError:
        pass
promotion_journals = [
    promotion_journal_details(path, active=path == promotion_journal)
    for path in sorted(discovered_promotion_paths, key=lambda item: str(item))
]
latest_promotion_recovery = recovery_receipt_summary(
    state_root / "latest-promotion-recovery.json"
)
latest_promotion_finalization = finalization_receipt_summary(
    state_root / "latest-promotion-finalization.json"
)


memory_committed = None
try:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("Committed_AS:"):
            memory_committed = int(line.split()[1]) * 1024
            break
except OSError:
    pass

disk = shutil.disk_usage(lexical_parent)
report = {
    "schema_version": 1,
    "inspected_at_utc": datetime.now(UTC).isoformat(),
    "one_shot": True,
    "repository": str(repo),
    "service": service,
    "process": process,
    "memory": {
        "cgroup_current_bytes": service.get("MemoryCurrent"),
        "cgroup_peak_bytes": service.get("MemoryPeak"),
        "system_committed_bytes": memory_committed,
    },
    "disk": {
        "path": str(lexical_parent),
        "free_bytes": disk.free,
        "total_bytes": disk.total,
    },
    "canonical_output": {
        "path": str(canonical),
        "exists": canonical.is_dir() and not canonical.is_symlink(),
        "size_bytes": directory_size(canonical),
        "partition_counts": partition_counts(canonical),
        "table_hash_manifest_exists": (canonical / "table-hashes.json").is_file(),
        "latest_output": latest_output(canonical),
    },
    "lexical_promotion": {
        "recovery_guidance": (
            f"sudo bash {repo}/cloud/cloud_start.sh; never edit or delete a promotion journal"
        ),
        "active_journal": active_promotion_journal,
        "discovered_journals": promotion_journals,
        "latest_recovery": latest_promotion_recovery,
        "latest_finalization": latest_promotion_finalization,
    },
    "staging_directory_count": len(staging_reports),
    "staging": staging_reports,
    "latest_launch": launch,
    "logs": {
        "stdout_path": launch.get("stdout_log"),
        "stdout_tail": tail(launch.get("stdout_log")),
        "stderr_path": launch.get("stderr_log"),
        "stderr_tail": tail(launch.get("stderr_log")),
    },
    "background_tasks": {
        "validation": transient_task("validation"),
        "packaging": transient_task("package"),
    },
    "latest_validation": validation_summary,
    "packages": {
        "latest_review_package": read_pointer("latest-review-package.txt"),
        "latest_full_manifest": read_pointer("latest-full-manifest.txt"),
    },
}
print(json.dumps(report, indent=2, sort_keys=True))
PY
