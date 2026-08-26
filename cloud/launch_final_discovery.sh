#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/project-echoes/final-discovery.env"
readonly STATE_ROOT="/var/lib/project-echoes/final-discovery"
readonly LOG_ROOT="/var/log/project-echoes/final-discovery"
readonly UNIT_NAME="echoes-final-discovery.service"
readonly CONFIG_RELATIVE_PATH="config/experiments/final-discovery-v1.yaml"
readonly CONFIG_FILE_SHA256="a38c2f6d1c3d84264c7b81a8a62c3a84cae8b993894f6634e339958cdc1f76b0"
readonly CONFIG_SEMANTIC_SHA256="7b5c511fed3be041576f9c2ea784d71e028a0f539d7642d84ddcf61eccd22627"
readonly M7_MANIFEST_SHA256="e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6"

usage() {
    cat <<'EOF'
Usage:
  sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery.sh --preflight-only
  sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery.sh

Fail-closed owner launcher for the single final-discovery-v1 production
worker. Preflight performs every local, budget, model, M7 identity, credential,
and output-namespace check but never creates a service or launch record. Launch
starts one detached systemd service, takes one startup snapshot, and exits. The
script never provisions, purchases, stops, deletes, or polls a cloud resource.
EOF
}

die() {
    printf 'final-discovery launch refused: %s\n' "$1" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command is unavailable: $1"
}

require_value() {
    local name="$1"
    [[ -n "${!name-}" ]] || die "required environment value is absent: $name"
    [[ "${!name}" != *$'\n'* && "${!name}" != *$'\r'* ]] ||
        die "environment value contains a control character: $name"
}

require_exact() {
    local name="$1"
    local expected="$2"
    [[ "${!name}" == "$expected" ]] || die "$name differs from the frozen value"
}

require_absolute_path() {
    local name="$1"
    [[ "${!name}" =~ ^/[A-Za-z0-9._/+:-]+$ ]] ||
        die "$name must be an absolute path using portable characters"
}

launch_mode="launch"
if (($#)); then
    case "$1" in
        --preflight-only)
            (($# == 1)) || { usage >&2; exit 2; }
            launch_mode="preflight"
            ;;
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

[[ $EUID -eq 0 ]] || die "run the exact documented command with sudo"
for executable in systemd-run systemctl git python3 sha256sum stat nproc runuser realpath df \
    install awk grep tail tr date id getent uname rclone; do
    require_command "$executable"
done

[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] ||
    die "root-owned service environment is missing or unsafe: $ENV_FILE"
[[ "$(stat -c '%u' "$ENV_FILE")" == "0" ]] || die "service environment must be owned by root"
env_mode="$(stat -c '%a' "$ENV_FILE")"
[[ "$env_mode" =~ ^[0-7]{3,4}$ ]] || die "could not validate service-environment mode"
(( (8#$env_mode & 077) == 0 )) || die "service environment must not be group/world accessible"

# Parse the root-owned file as data, not shell code. The same simple KEY=value
# bytes are consumed later by systemd. Secret values remain shell-local and
# are never inherited by preflight subprocesses or placed on a command line.
declare -A environment_names=()
while IFS= read -r environment_line || [[ -n "$environment_line" ]]; do
    environment_line="${environment_line%$'\r'}"
    [[ -n "$environment_line" && "${environment_line:0:1}" != "#" ]] || continue
    [[ "$environment_line" == *=* ]] || die "service environment contains a malformed line"
    environment_name="${environment_line%%=*}"
    environment_value="${environment_line#*=}"
    [[ "$environment_name" =~ ^[A-Z][A-Z0-9_]*$ ]] ||
        die "service environment contains an invalid variable name"
    [[ -z "${environment_names[$environment_name]+present}" ]] ||
        die "service environment repeats a variable"
    case "$environment_value" in
        \"*|\'*|*\"|*\') die "service environment values must be unquoted" ;;
    esac
    [[ "$environment_value" != [[:space:]]* && "$environment_value" != *[[:space:]] ]] ||
        die "service environment values must not have surrounding whitespace"
    environment_names["$environment_name"]=1
    printf -v "$environment_name" '%s' "$environment_value"
done < "$ENV_FILE"

required_names=(
    ECHOES_AUTHORIZE_PRODUCTION
    ECHOES_EXPECTED_SERVER_TYPE
    ECHOES_SERVER_NAME
    ECHOES_REPO_ROOT
    ECHOES_WORK_DIR
    ECHOES_PREPARED_PASSAGES
    ECHOES_KNOWNNESS_PATH
    ECHOES_MODEL_ROOT
    ECHOES_UV_BIN
    ECHOES_SERVICE_USER
    ECHOES_SERVICE_GROUP
    ECHOES_EXPECTED_GIT_COMMIT
    ECHOES_M7_BUCKET
    ECHOES_M7_PREFIX
    ECHOES_M7_MANIFEST_SHA256
    ECHOES_OUTPUT_BUCKET
    ECHOES_OUTPUT_PREFIX
    B2_APPLICATION_KEY_ID
    B2_APPLICATION_KEY
    ECHOES_FINAL_DISCOVERY_THREADS
    ECHOES_FINAL_DISCOVERY_PROCESS_MEMORY_GIB
    ECHOES_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_GIB
    ECHOES_FINAL_DISCOVERY_INITIAL_FREE_DISK_GIB
    ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB
    ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS
    ECHOES_HARD_BUDGET_USD
    ECHOES_VERIFIED_RATE_USD_PER_HOUR
    ECHOES_RATE_VERIFIED_AT_UTC
    ECHOES_SERVER_CREATED_AT_UTC
    ECHOES_ACCRUED_INFRASTRUCTURE_USD
    ECHOES_ACCRUED_COST_VERIFIED_AT_UTC
    ECHOES_B2_COST_RESERVE_USD
)
declare -A required_name_set=()
for name in "${required_names[@]}"; do
    required_name_set["$name"]=1
    require_value "$name"
    [[ "${!name}" != *OWNER_SET* ]] || die "$name still contains an OWNER_SET placeholder"
done
for name in "${!environment_names[@]}"; do
    [[ -n "${required_name_set[$name]+present}" ]] ||
        die "service environment contains an unexpected variable: $name"
done

# Only nonsecret fields needed by the metadata writer are exported locally.
# B2 credentials reach the worker exclusively through systemd EnvironmentFile.
metadata_environment_names=(
    ECHOES_AUTHORIZE_PRODUCTION ECHOES_EXPECTED_SERVER_TYPE ECHOES_SERVER_NAME
    ECHOES_REPO_ROOT ECHOES_WORK_DIR ECHOES_PREPARED_PASSAGES ECHOES_KNOWNNESS_PATH
    ECHOES_MODEL_ROOT ECHOES_UV_BIN ECHOES_SERVICE_USER ECHOES_SERVICE_GROUP
    ECHOES_EXPECTED_GIT_COMMIT ECHOES_M7_BUCKET ECHOES_M7_PREFIX
    ECHOES_M7_MANIFEST_SHA256 ECHOES_OUTPUT_BUCKET ECHOES_OUTPUT_PREFIX
    ECHOES_FINAL_DISCOVERY_THREADS ECHOES_FINAL_DISCOVERY_PROCESS_MEMORY_GIB
    ECHOES_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_GIB
    ECHOES_FINAL_DISCOVERY_INITIAL_FREE_DISK_GIB
    ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS
    ECHOES_HARD_BUDGET_USD ECHOES_ACCRUED_INFRASTRUCTURE_USD
    ECHOES_ACCRUED_COST_VERIFIED_AT_UTC
)
for name in "${metadata_environment_names[@]}"; do
    export "$name"
done

require_exact ECHOES_AUTHORIZE_PRODUCTION final-discovery-v1
require_exact ECHOES_EXPECTED_SERVER_TYPE CCX43
require_exact ECHOES_SERVER_NAME project-echoes-final-discovery-v1
require_exact ECHOES_M7_BUCKET project-echoes-archive
require_exact ECHOES_M7_PREFIX m7/canonical-schema-v1
require_exact ECHOES_M7_MANIFEST_SHA256 "$M7_MANIFEST_SHA256"
require_exact ECHOES_FINAL_DISCOVERY_THREADS 12
require_exact ECHOES_FINAL_DISCOVERY_PROCESS_MEMORY_GIB 56
require_exact ECHOES_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_GIB 40
require_exact ECHOES_FINAL_DISCOVERY_INITIAL_FREE_DISK_GIB 280
require_exact ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB 80
require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 96
require_exact ECHOES_HARD_BUDGET_USD 75.00

for name in ECHOES_REPO_ROOT ECHOES_WORK_DIR ECHOES_PREPARED_PASSAGES \
    ECHOES_KNOWNNESS_PATH ECHOES_MODEL_ROOT ECHOES_UV_BIN; do
    require_absolute_path "$name"
done
[[ "$ECHOES_SERVICE_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "invalid service user"
[[ "$ECHOES_SERVICE_GROUP" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "invalid service group"
[[ "$ECHOES_EXPECTED_GIT_COMMIT" =~ ^[0-9a-f]{40,64}$ ]] ||
    die "ECHOES_EXPECTED_GIT_COMMIT must be one full lowercase Git object ID"
[[ "$ECHOES_OUTPUT_BUCKET" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$ ]] ||
    die "invalid B2 output bucket"
[[ "$ECHOES_OUTPUT_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$ ]] ||
    die "invalid B2 output prefix"
[[ "$ECHOES_OUTPUT_PREFIX" != */../* && "$ECHOES_OUTPUT_PREFIX" != ../* &&
   "$ECHOES_OUTPUT_PREFIX" != */.. && "$ECHOES_OUTPUT_PREFIX" != */ ]] ||
    die "B2 output prefix must be normalized and confined"

[[ -d "$ECHOES_REPO_ROOT/.git" && ! -L "$ECHOES_REPO_ROOT" ]] ||
    die "repository root is missing or unsafe"
[[ -f "$ECHOES_PREPARED_PASSAGES" && -s "$ECHOES_PREPARED_PASSAGES" &&
   ! -L "$ECHOES_PREPARED_PASSAGES" ]] || die "prepared-passage projection is missing or unsafe"
[[ -f "$ECHOES_KNOWNNESS_PATH" && -s "$ECHOES_KNOWNNESS_PATH" &&
   ! -L "$ECHOES_KNOWNNESS_PATH" ]] || die "knownness projection is missing or unsafe"
[[ "$ECHOES_KNOWNNESS_PATH" == *.jsonl ]] ||
    die "knownness projection must use the fixed .jsonl/receipt sidecar convention"
knownness_receipt_path="${ECHOES_KNOWNNESS_PATH%.jsonl}.receipt.json"
[[ -f "$knownness_receipt_path" && -s "$knownness_receipt_path" &&
   ! -L "$knownness_receipt_path" ]] ||
    die "knownness projection receipt is missing or unsafe: $knownness_receipt_path"
[[ -d "$ECHOES_MODEL_ROOT" && ! -L "$ECHOES_MODEL_ROOT" ]] ||
    die "offline model root is missing or unsafe"
[[ -x "$ECHOES_UV_BIN" && ! -L "$ECHOES_UV_BIN" ]] || die "uv binary is missing or unsafe"
id "$ECHOES_SERVICE_USER" >/dev/null 2>&1 || die "service user does not exist"
getent group "$ECHOES_SERVICE_GROUP" >/dev/null 2>&1 || die "service group does not exist"
runuser -u "$ECHOES_SERVICE_USER" -- /usr/bin/test -r "$ECHOES_PREPARED_PASSAGES" ||
    die "service user cannot read the prepared-passage projection"
runuser -u "$ECHOES_SERVICE_USER" -- /usr/bin/test -r "$ECHOES_KNOWNNESS_PATH" ||
    die "service user cannot read the knownness projection"
runuser -u "$ECHOES_SERVICE_USER" -- /usr/bin/test -r "$knownness_receipt_path" ||
    die "service user cannot read the knownness projection receipt"
runuser -u "$ECHOES_SERVICE_USER" -- rclone version >/dev/null ||
    die "service user cannot execute rclone"

source /etc/os-release
[[ "${ID-}" == ubuntu && "${VERSION_ID-}" == 24.04 ]] ||
    die "production requires Ubuntu 24.04"
[[ "$(uname -m)" == x86_64 ]] || die "production requires x86_64"
[[ "$(nproc --all)" == 16 ]] || die "CCX43 contract requires exactly 16 visible vCPUs"
grep -qE 'vendor_id[[:space:]]*:[[:space:]]*AuthenticAMD|model name[[:space:]]*:[[:space:]].*AMD' \
    /proc/cpuinfo || die "CCX43 contract requires AMD CPUs"
memory_bytes=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) * 1024 ))
(( memory_bytes >= 60 * 1024 * 1024 * 1024 )) ||
    die "CCX43 contract requires a host advertised with 64 GB RAM"

repo_resolved="$(realpath "$ECHOES_REPO_ROOT")"
work_resolved="$(realpath -m "$ECHOES_WORK_DIR")"
case "$work_resolved/" in
    "$repo_resolved"/*) die "work directory must remain outside the Git repository" ;;
esac

install -d -m 0700 -o "$ECHOES_SERVICE_USER" -g "$ECHOES_SERVICE_GROUP" \
    "$ECHOES_WORK_DIR" "$ECHOES_WORK_DIR/tmp" "$ECHOES_WORK_DIR/duckdb-spill"
install -d -m 0700 -o root -g root "$STATE_ROOT" "$STATE_ROOT/launches" "$LOG_ROOT"
[[ ! -L "$ECHOES_WORK_DIR" && ! -L "$STATE_ROOT" && ! -L "$LOG_ROOT" ]] ||
    die "work, state, and log directories must not be symbolic links"
runuser -u "$ECHOES_SERVICE_USER" -- /usr/bin/test -w "$ECHOES_WORK_DIR" ||
    die "service user cannot write the campaign work directory"

available_bytes="$(df -B1 --output=avail "$ECHOES_WORK_DIR" | tail -n 1 | tr -d ' ')"
[[ "$available_bytes" =~ ^[0-9]+$ ]] || die "could not measure work-filesystem free space"
(( available_bytes >= 280 * 1024 * 1024 * 1024 )) ||
    die "work filesystem has less than the required 280 GiB free at launch"

budget_json="$(python3 - \
    "$ECHOES_VERIFIED_RATE_USD_PER_HOUR" \
    "$ECHOES_RATE_VERIFIED_AT_UTC" \
    "$ECHOES_SERVER_CREATED_AT_UTC" \
    "$ECHOES_ACCRUED_INFRASTRUCTURE_USD" \
    "$ECHOES_ACCRUED_COST_VERIFIED_AT_UTC" \
    "$ECHOES_B2_COST_RESERVE_USD" \
    "$ECHOES_HARD_BUDGET_USD" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation


def timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"{label} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SystemExit(f"{label} must include the UTC offset")
    return parsed.astimezone(UTC)


try:
    rate = Decimal(sys.argv[1])
    accrued = Decimal(sys.argv[4])
    reserve = Decimal(sys.argv[6])
    cap = Decimal(sys.argv[7])
except InvalidOperation as exc:
    raise SystemExit("rate, accrued cost, B2 reserve, and budget must be decimals") from exc
if rate <= 0 or accrued < 0 or reserve < 0 or cap != Decimal("75.00"):
    raise SystemExit("invalid rate, accrued cost, B2 reserve, or frozen budget")

now = datetime.now(UTC)
rate_verified_at = timestamp(sys.argv[2], "rate verification")
created_at = timestamp(sys.argv[3], "server creation")
accrued_verified_at = timestamp(sys.argv[5], "accrued-cost verification")
for verified_at, label in (
    (rate_verified_at, "all-in hourly rate"),
    (accrued_verified_at, "accrued infrastructure cost"),
):
    if verified_at > now + timedelta(minutes=5) or now - verified_at > timedelta(hours=24):
        raise SystemExit(f"the owner must reverify the {label} within 24 hours of launch")
if created_at > now + timedelta(minutes=5):
    raise SystemExit("server creation time cannot be in the future")

worker_hours = Decimal("96")
projected_future_infrastructure = worker_hours * rate
projected_all_in = accrued + projected_future_infrastructure + reserve
if projected_all_in > cap:
    raise SystemExit("verified accrued cost plus worker window and B2 reserve exceeds $75")
print(
    json.dumps(
        {
            "verified_rate_usd_per_hour": str(rate),
            "rate_verified_at_utc": rate_verified_at.isoformat(),
            "server_created_at_utc": created_at.isoformat(),
            "verified_accrued_infrastructure_usd": str(accrued),
            "accrued_cost_verified_at_utc": accrued_verified_at.isoformat(),
            "maximum_worker_hours": 96,
            "projected_future_infrastructure_usd": str(
                projected_future_infrastructure.quantize(Decimal("0.001"))
            ),
            "b2_cost_reserve_usd": str(reserve),
            "projected_all_in_usd": str(projected_all_in.quantize(Decimal("0.001"))),
            "hard_cap_usd": str(cap),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
PY
)" || die "current owner-verified pricing does not fit the frozen $75 all-in cap"

git_as_service=(runuser -u "$ECHOES_SERVICE_USER" -- git -C "$ECHOES_REPO_ROOT")
observed_commit="$("${git_as_service[@]}" rev-parse --verify HEAD)"
[[ "$observed_commit" == "$ECHOES_EXPECTED_GIT_COMMIT" ]] ||
    die "repository HEAD differs from ECHOES_EXPECTED_GIT_COMMIT"
[[ -z "$("${git_as_service[@]}" status --porcelain=v1 --untracked-files=all)" ]] ||
    die "repository must be completely clean, including untracked files"
git_tree="$("${git_as_service[@]}" rev-parse 'HEAD^{tree}')"
git_archive_sha256="$("${git_as_service[@]}" archive --format=tar HEAD | sha256sum | awk '{print $1}')"

config_path="$ECHOES_REPO_ROOT/$CONFIG_RELATIVE_PATH"
observed_config_sha256="$(sha256sum "$config_path" | awk '{print $1}')"
[[ "$observed_config_sha256" == "$CONFIG_FILE_SHA256" ]] ||
    die "final-discovery-v1 YAML bytes differ from the frozen SHA-256"
uv_lock_sha256="$(sha256sum "$ECHOES_REPO_ROOT/uv.lock" | awk '{print $1}')"

# Validate configuration and the exact offline model allowlist before stage 1
# can spend time materializing the archived M7 tree. Offline flags prevent an
# accidental model download; B2 remains available to the campaign itself.
runuser -u "$ECHOES_SERVICE_USER" -- sh -c \
    'cd -- "$1" && exec "$2" run --frozen --no-sync echoes validate-config' \
    sh "$ECHOES_REPO_ROOT" "$ECHOES_UV_BIN" >/dev/null
model_runtime_json="$(runuser -u "$ECHOES_SERVICE_USER" -- sh -c \
    'cd -- "$1" && exec "$2" run --frozen --no-sync echoes validate-final-discovery-model-runtime --json' \
    sh "$ECHOES_REPO_ROOT" "$ECHOES_UV_BIN")" ||
    die "installed model dependency versions differ from the preregistration"
runuser -u "$ECHOES_SERVICE_USER" -- env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    sh -c 'cd -- "$1" && exec "$2" run --frozen --no-sync python - "$3" "$4"' \
    sh "$ECHOES_REPO_ROOT" "$ECHOES_UV_BIN" "$ECHOES_MODEL_ROOT" \
    "$CONFIG_SEMANTIC_SHA256" <<'PY'
from pathlib import Path
import sys

from echoes.final_discovery.config import (
    final_discovery_config_sha256,
    load_final_discovery_config,
)
from echoes.final_discovery.semantic import verify_model_artifacts

config = load_final_discovery_config()
if final_discovery_config_sha256(config) != sys.argv[2]:
    raise SystemExit("final-discovery semantic configuration SHA-256 differs")
verify_model_artifacts(Path(sys.argv[1]), config.embedding_model)
PY

load_state="$(systemctl show "$UNIT_NAME" --property=LoadState --value 2>/dev/null || true)"
active_state="$(systemctl show "$UNIT_NAME" --property=ActiveState --value 2>/dev/null || true)"
case "$active_state" in
    active|activating|reloading|deactivating)
        die "the sole final-discovery worker is already active"
        ;;
esac
if [[ -n "$load_state" && "$load_state" != not-found ]]; then
    systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
    load_state="$(systemctl show "$UNIT_NAME" --property=LoadState --value 2>/dev/null || true)"
    [[ -z "$load_state" || "$load_state" == not-found ]] ||
        die "a prior unit remains loaded; inspect it before relaunch"
fi

# Inspect the complete base namespace once before systemd starts. Credentials
# are inherited only through the child environment and never enter argv,
# output, the intent record, or a temporary config owned by this script.
output_namespace_json="$(
    while IFS= read -r exported_name; do
        case "$exported_name" in
            PATH|LANG|LC_*) ;;
            *) export -n "$exported_name" ;;
        esac
    done < <(compgen -e)
    export B2_APPLICATION_KEY_ID B2_APPLICATION_KEY
    runuser -u "$ECHOES_SERVICE_USER" --preserve-environment -- sh -c \
        'cd -- "$1" && exec "$2" run --frozen --no-sync echoes inspect-final-discovery-output --work-dir "$3" --output-bucket "$4" --output-prefix "$5" --json' \
        sh "$ECHOES_REPO_ROOT" "$ECHOES_UV_BIN" "$ECHOES_WORK_DIR" \
        "$ECHOES_OUTPUT_BUCKET" "$ECHOES_OUTPUT_PREFIX"
)" || die "B2 output namespace is neither empty nor an authenticated resumable state"

# Authenticate the exact remote M7 identity without downloading its 17 GiB
# body. Stage 1 still downloads every object and verifies every manifest-listed
# SHA-256 before analysis. This preflight catches credentials, bucket/prefix,
# remote inventory, and manifest-identity errors before a worker can start.
m7_preflight_json="$(
    while IFS= read -r exported_name; do
        case "$exported_name" in
            PATH|LANG|LC_*) ;;
            *) export -n "$exported_name" ;;
        esac
    done < <(compgen -e)
    export B2_APPLICATION_KEY_ID B2_APPLICATION_KEY
    runuser -u "$ECHOES_SERVICE_USER" --preserve-environment -- sh -c \
        'cd -- "$1" && exec "$2" run --frozen --no-sync python - "$3" "$4" "$5"' \
        sh "$ECHOES_REPO_ROOT" "$ECHOES_UV_BIN" "$ECHOES_M7_BUCKET" \
        "$ECHOES_M7_PREFIX" "$M7_MANIFEST_SHA256" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys

from echoes.final_discovery.inputs import RcloneB2ObjectStore

bucket, prefix, expected_manifest_sha256 = sys.argv[1:]
store = RcloneB2ObjectStore(bucket=bucket, prefix=prefix)
inventory = store.inventory()
manifest = store.read_bytes("table-hashes.json", maximum_bytes=64 * 1024 * 1024)
observed_manifest_sha256 = hashlib.sha256(manifest).hexdigest()
if observed_manifest_sha256 != expected_manifest_sha256:
    raise SystemExit(
        "remote M7 table-hashes.json differs: "
        f"expected={expected_manifest_sha256}, observed={observed_manifest_sha256}"
    )
if inventory.object_count != 18_606 or inventory.total_size != 18_413_699_180:
    raise SystemExit(
        "remote M7 object inventory differs from the verified archive: "
        f"objects={inventory.object_count}, bytes={inventory.total_size}"
    )
print(
    json.dumps(
        {
            "identity": inventory.identity.canonical_uri,
            "object_count": inventory.object_count,
            "total_size": inventory.total_size,
            "table_hashes_sha256": observed_manifest_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
PY
)" || die "canonical M7 remote identity or credentials failed preflight"

if [[ "$launch_mode" == preflight ]]; then
    python3 - "$observed_commit" "$available_bytes" "$budget_json" \
        "$m7_preflight_json" "$output_namespace_json" <<'PY'
from __future__ import annotations

import json
import sys

commit, available_bytes, budget, m7, output_namespace = sys.argv[1:]
print(
    json.dumps(
        {
            "schema_version": 1,
            "experiment_id": "final-discovery-v1",
            "preflight_passed": True,
            "service_created": False,
            "git_commit": commit,
            "available_bytes": int(available_bytes),
            "budget": json.loads(budget),
            "m7": json.loads(m7),
            "output_namespace": json.loads(output_namespace),
        },
        indent=2,
        sort_keys=True,
    )
)
PY
    printf 'FINAL_DISCOVERY_PREFLIGHT_COMPLETE\n'
    exit 0
fi

launch_id="$(date -u +%Y%m%dT%H%M%SZ)-${observed_commit:0:12}"
intent_path="$STATE_ROOT/launches/$launch_id.intent.json"
startup_path="$STATE_ROOT/launches/$launch_id.startup.json"
stdout_log="$LOG_ROOT/$launch_id.stdout.log"
stderr_log="$LOG_ROOT/$launch_id.stderr.log"
for path in "$intent_path" "$startup_path" "$stdout_log" "$stderr_log"; do
    [[ ! -e "$path" && ! -L "$path" ]] || die "launch-owned path already exists: $path"
done
install -m 0600 -o "$ECHOES_SERVICE_USER" -g "$ECHOES_SERVICE_GROUP" /dev/null "$stdout_log"
install -m 0600 -o "$ECHOES_SERVICE_USER" -g "$ECHOES_SERVICE_GROUP" /dev/null "$stderr_log"
seal_logs() {
    chown root:root "$stdout_log" "$stderr_log" >/dev/null 2>&1 || true
    chmod 0400 "$stdout_log" "$stderr_log" >/dev/null 2>&1 || true
}
trap seal_logs EXIT

python3 - "$intent_path" "$launch_id" "$observed_commit" "$git_tree" \
    "$git_archive_sha256" "$observed_config_sha256" "$CONFIG_SEMANTIC_SHA256" \
    "$uv_lock_sha256" "$model_runtime_json" "$output_namespace_json" \
    "$available_bytes" "$budget_json" "$stdout_log" "$stderr_log" <<'PY'
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

(
    output_name,
    launch_id,
    commit,
    tree,
    archive_hash,
    config_hash,
    config_semantic_hash,
    lock_hash,
    model_runtime_json,
    output_namespace_json,
    available_bytes,
    budget_json,
    stdout_log,
    stderr_log,
) = sys.argv[1:]

safe_names = (
    "ECHOES_AUTHORIZE_PRODUCTION",
    "ECHOES_EXPECTED_SERVER_TYPE",
    "ECHOES_SERVER_NAME",
    "ECHOES_REPO_ROOT",
    "ECHOES_WORK_DIR",
    "ECHOES_PREPARED_PASSAGES",
    "ECHOES_KNOWNNESS_PATH",
    "ECHOES_MODEL_ROOT",
    "ECHOES_UV_BIN",
    "ECHOES_SERVICE_USER",
    "ECHOES_SERVICE_GROUP",
    "ECHOES_EXPECTED_GIT_COMMIT",
    "ECHOES_M7_BUCKET",
    "ECHOES_M7_PREFIX",
    "ECHOES_M7_MANIFEST_SHA256",
    "ECHOES_OUTPUT_BUCKET",
    "ECHOES_OUTPUT_PREFIX",
    "ECHOES_FINAL_DISCOVERY_THREADS",
    "ECHOES_FINAL_DISCOVERY_PROCESS_MEMORY_GIB",
    "ECHOES_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_GIB",
    "ECHOES_FINAL_DISCOVERY_INITIAL_FREE_DISK_GIB",
    "ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB",
    "ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS",
    "ECHOES_HARD_BUDGET_USD",
)
command = [
    os.environ["ECHOES_UV_BIN"],
    "run",
    "--frozen",
    "--no-sync",
    "echoes",
    "run-final-discovery",
    "--production",
    "--work-dir",
    os.environ["ECHOES_WORK_DIR"],
    "--prepared-passages",
    os.environ["ECHOES_PREPARED_PASSAGES"],
    "--knownness-path",
    os.environ["ECHOES_KNOWNNESS_PATH"],
    "--offline-model-root",
    os.environ["ECHOES_MODEL_ROOT"],
    "--m7-bucket",
    os.environ["ECHOES_M7_BUCKET"],
    "--m7-prefix",
    os.environ["ECHOES_M7_PREFIX"],
    "--output-bucket",
    os.environ["ECHOES_OUTPUT_BUCKET"],
    "--output-prefix",
    os.environ["ECHOES_OUTPUT_PREFIX"],
]
payload = {
    "schema_version": 1,
    "experiment_id": "final-discovery-v1",
    "launch_id": launch_id,
    "recorded_at_utc": datetime.now(UTC).isoformat(),
    "service_unit": "echoes-final-discovery.service",
    "command": command,
    "environment": {name: os.environ[name] for name in safe_names},
    "secret_environment": {
        "B2_APPLICATION_KEY_ID": "present_not_recorded",
        "B2_APPLICATION_KEY": "present_not_recorded",
    },
    "code": {
        "git_commit": commit,
        "git_tree": tree,
        "git_archive_sha256": archive_hash,
        "working_tree_clean": True,
        "uv_lock_sha256": lock_hash,
        "model_runtime": json.loads(model_runtime_json),
    },
    "configuration": {
        "path": "config/experiments/final-discovery-v1.yaml",
        "file_sha256": config_hash,
        "semantic_sha256": config_semantic_hash,
    },
    "output_namespace_preflight": json.loads(output_namespace_json),
    "resource_contract": {
        "host": "CCX43 / Ubuntu 24.04 / 16 dedicated AMD vCPU / 64 GB / 360 GB SSD",
        "cpu_thread_ceiling": 12,
        "process_memory_ceiling_gib": 56,
        "duckdb_ceiling_gib": 40,
        "m7_projection_internal_bound": "1 GiB and one thread",
        "initial_free_disk_gib": 280,
        "checkpoint_disk_floor_gib": 80,
        "runtime_max_hours": 96,
        "available_bytes_at_launch": int(available_bytes),
    },
    "budget": json.loads(budget_json),
    "logs": {"stdout": stdout_log, "stderr": stderr_log},
    "polling_or_automatic_restart": False,
}
path = Path(output_name)
with path.open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
path.chmod(0o400)
PY

# The scientific worker authenticates this nonsecret, immutable intent before
# accepting production mode. Group read access is limited to the service
# account; no credential value is present in the record.
chown "root:$ECHOES_SERVICE_GROUP" "$intent_path"
chmod 0440 "$intent_path"
intent_sha256="$(sha256sum "$intent_path" | awk '{print $1}')"
[[ "$intent_sha256" =~ ^[a-f0-9]{64}$ ]] || die "could not authenticate launch intent"

systemd-run \
    --unit="$UNIT_NAME" \
    --description="Project Echoes final-discovery-v1 canonical campaign" \
    --property=Type=exec \
    --property="User=$ECHOES_SERVICE_USER" \
    --property="Group=$ECHOES_SERVICE_GROUP" \
    --property="WorkingDirectory=$ECHOES_REPO_ROOT" \
    --property="EnvironmentFile=$ENV_FILE" \
    --property=Restart=no \
    --property=RuntimeMaxSec=96h \
    --property=TimeoutStopSec=5min \
    --property=KillMode=control-group \
    --property=OOMPolicy=stop \
    --property=MemoryAccounting=yes \
    --property=MemoryHigh=54G \
    --property=MemoryMax=56G \
    --property=MemorySwapMax=0 \
    --property=CPUAccounting=yes \
    --property=CPUQuota=1200% \
    --property=TasksAccounting=yes \
    --property=UMask=0077 \
    --property=NoNewPrivileges=yes \
    --property=PrivateTmp=yes \
    --property="StandardOutput=append:$stdout_log" \
    --property="StandardError=append:$stderr_log" \
    --setenv=PYTHONUNBUFFERED=1 \
    --setenv=HF_HUB_OFFLINE=1 \
    --setenv=TRANSFORMERS_OFFLINE=1 \
    --setenv=CUDA_VISIBLE_DEVICES=-1 \
    --setenv=NVIDIA_VISIBLE_DEVICES=void \
    --setenv=OMP_NUM_THREADS=12 \
    --setenv=OPENBLAS_NUM_THREADS=12 \
    --setenv=MKL_NUM_THREADS=12 \
    --setenv=NUMEXPR_NUM_THREADS=12 \
    --setenv=POLARS_MAX_THREADS=12 \
    --setenv=RAYON_NUM_THREADS=12 \
    --setenv="ECHOES_MANAGED_LAUNCH_ID=$launch_id" \
    --setenv="ECHOES_MANAGED_LAUNCH_INTENT_PATH=$intent_path" \
    --setenv="ECHOES_MANAGED_LAUNCH_INTENT_SHA256=$intent_sha256" \
    --setenv="TMPDIR=$ECHOES_WORK_DIR/tmp" \
    --setenv="ECHOES_DUCKDB_TEMP_DIRECTORY=$ECHOES_WORK_DIR/duckdb-spill" \
    "$ECHOES_UV_BIN" run --frozen --no-sync echoes run-final-discovery \
    --production \
    --work-dir "$ECHOES_WORK_DIR" \
    --prepared-passages "$ECHOES_PREPARED_PASSAGES" \
    --knownness-path "$ECHOES_KNOWNNESS_PATH" \
    --offline-model-root "$ECHOES_MODEL_ROOT" \
    --m7-bucket "$ECHOES_M7_BUCKET" \
    --m7-prefix "$ECHOES_M7_PREFIX" \
    --output-bucket "$ECHOES_OUTPUT_BUCKET" \
    --output-prefix "$ECHOES_OUTPUT_PREFIX" >/dev/null

# PID 1 opened the unique append-only descriptors before the service became
# active. Remove path-level write access now; the running worker retains only
# those already-open stdout/stderr descriptors, and no restart can reopen them.
chown root:root "$stdout_log" "$stderr_log"
chmod 0400 "$stdout_log" "$stderr_log"
trap - EXIT

# Exactly one bounded startup snapshot follows the detached launch. There is
# deliberately no sleep, retry, watch, journal follow, or polling loop.
startup_snapshot="$(systemctl show "$UNIT_NAME" \
    --property=Id \
    --property=LoadState \
    --property=ActiveState \
    --property=SubState \
    --property=Result \
    --property=MainPID \
    --property=ExecMainStartTimestamp \
    --property=MemoryHigh \
    --property=MemoryMax \
    --property=RuntimeMaxUSec \
    --property=CPUQuotaPerSecUSec)"

python3 - "$startup_path" "$launch_id" "$intent_path" "$startup_snapshot" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

output_name, launch_id, intent_name, raw_snapshot = sys.argv[1:]
properties: dict[str, object] = {}
for line in raw_snapshot.splitlines():
    key, separator, value = line.partition("=")
    if separator:
        properties[key] = int(value) if key in {"MainPID", "MemoryHigh", "MemoryMax", "RuntimeMaxUSec", "CPUQuotaPerSecUSec"} and value.isdigit() else value
intent = Path(intent_name)
payload = {
    "schema_version": 1,
    "experiment_id": "final-discovery-v1",
    "launch_id": launch_id,
    "recorded_at_utc": datetime.now(UTC).isoformat(),
    "intent_path": str(intent),
    "intent_sha256": hashlib.sha256(intent.read_bytes()).hexdigest(),
    "single_startup_verification": True,
    "service": properties,
}
path = Path(output_name)
with path.open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
path.chmod(0o400)
PY

startup_active="$(printf '%s\n' "$startup_snapshot" | awk -F= '$1 == "ActiveState" {print $2}')"
startup_pid="$(printf '%s\n' "$startup_snapshot" | awk -F= '$1 == "MainPID" {print $2}')"
[[ "$startup_active" == active && "$startup_pid" =~ ^[1-9][0-9]*$ ]] ||
    die "the detached unit did not pass its single startup verification; inspect one-shot status"

printf 'Started %s as PID %s.\n' "$UNIT_NAME" "$startup_pid"
printf 'Launch metadata: %s and %s\n' "$intent_path" "$startup_path"
printf 'Logs: %s and %s\n' "$stdout_log" "$stderr_log"
printf 'One-shot status: sudo bash %s/cloud/final_discovery_status.sh\n' "$ECHOES_REPO_ROOT"
