#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/project-echoes/final-discovery.env"
readonly STATE_ROOT="/var/lib/project-echoes/final-discovery"

usage() {
    cat <<'EOF'
Usage: sudo bash /srv/project-echoes/repo/cloud/verify_final_discovery_cleanup.sh

Perform one bounded deletion-gate reauthentication of the final Stage 11 B2
checkpoint and write a new immutable local receipt. The command never sleeps,
retries, polls, follows logs, provisions resources, or deletes anything.
EOF
}

die() {
    printf 'final-discovery cleanup verification failed: %s\n' "$1" >&2
    exit 1
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

[[ $EUID -eq 0 ]] || die "run the exact documented command with sudo"
for executable in python3 stat runuser date install sha256sum mv chmod awk; do
    command -v "$executable" >/dev/null 2>&1 || die "required command is unavailable: $executable"
done
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || die "protected environment is absent or unsafe"
[[ "$(stat -c '%u' "$ENV_FILE")" == 0 ]] || die "protected environment must be root-owned"
env_mode="$(stat -c '%a' "$ENV_FILE")"
[[ "$env_mode" =~ ^[0-7]{3,4}$ ]] || die "could not validate environment mode"
(( (8#$env_mode & 077) == 0 )) || die "protected environment is group/world accessible"

declare -A environment_names=()
while IFS= read -r environment_line || [[ -n "$environment_line" ]]; do
    environment_line="${environment_line%$'\r'}"
    [[ -n "$environment_line" && "${environment_line:0:1}" != "#" ]] || continue
    [[ "$environment_line" == *=* ]] || die "protected environment contains a malformed line"
    environment_name="${environment_line%%=*}"
    environment_value="${environment_line#*=}"
    [[ "$environment_name" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "environment name is invalid"
    [[ -z "${environment_names[$environment_name]+present}" ]] || die "environment repeats a name"
    [[ "$environment_value" != *$'\n'* && "$environment_value" != *$'\r'* ]] ||
        die "environment value contains a control character"
    environment_names["$environment_name"]=1
    printf -v "$environment_name" '%s' "$environment_value"
done < "$ENV_FILE"

for name in ECHOES_REPO_ROOT ECHOES_WORK_DIR ECHOES_UV_BIN ECHOES_SERVICE_USER \
    ECHOES_OUTPUT_BUCKET ECHOES_OUTPUT_PREFIX ECHOES_EXPECTED_GIT_COMMIT \
    B2_APPLICATION_KEY_ID B2_APPLICATION_KEY; do
    [[ -n "${!name-}" ]] || die "required environment value is absent: $name"
done
for name in ECHOES_REPO_ROOT ECHOES_WORK_DIR ECHOES_UV_BIN; do
    [[ "${!name}" =~ ^/[A-Za-z0-9._/+:-]+$ ]] || die "$name is not a safe absolute path"
done
[[ -d "$ECHOES_REPO_ROOT" && ! -L "$ECHOES_REPO_ROOT" ]] || die "repository is unsafe"
[[ -d "$ECHOES_WORK_DIR" && ! -L "$ECHOES_WORK_DIR" ]] || die "work directory is unsafe"
[[ -x "$ECHOES_UV_BIN" && ! -L "$ECHOES_UV_BIN" ]] || die "uv executable is unsafe"

receipt_root="$STATE_ROOT/cleanup-verifications"
install -d -m 0700 -o root -g root "$receipt_root"
verification_id="$(date -u +%Y%m%dT%H%M%SZ)-${ECHOES_EXPECTED_GIT_COMMIT:0:12}"
receipt_path="$receipt_root/$verification_id.finalization.json"
temporary_path="$receipt_root/.$verification_id.$$.tmp"
failed_path="$receipt_root/$verification_id.failed.json"
for path in "$receipt_path" "$temporary_path" "$failed_path"; do
    [[ ! -e "$path" && ! -L "$path" ]] || die "verification-owned path already exists: $path"
done
umask 077

if ! (
    while IFS= read -r exported_name; do
        case "$exported_name" in
            PATH|LANG|LC_*) ;;
            *) export -n "$exported_name" ;;
        esac
    done < <(compgen -e)
    export B2_APPLICATION_KEY_ID B2_APPLICATION_KEY
    runuser -u "$ECHOES_SERVICE_USER" --preserve-environment -- sh -c \
        'cd -- "$1" && exec "$2" run --frozen --no-sync echoes verify-final-discovery-finalization --work-dir "$3" --output-bucket "$4" --output-prefix "$5" --json' \
        sh "$ECHOES_REPO_ROOT" "$ECHOES_UV_BIN" "$ECHOES_WORK_DIR" \
        "$ECHOES_OUTPUT_BUCKET" "$ECHOES_OUTPUT_PREFIX"
) > "$temporary_path"; then
    mv -- "$temporary_path" "$failed_path"
    chmod 0400 "$failed_path"
    die "bounded B2 reauthentication did not pass; preserved $failed_path"
fi

if ! python3 - "$temporary_path" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"cleanup receipt is invalid JSON: {exc}") from exc
remote = payload.get("remote_verification") if isinstance(payload, dict) else None
if (
    payload.get("experiment_id") != "final-discovery-v1"
    or payload.get("cleanup_finalization_reauthenticated") is not True
    or not isinstance(remote, dict)
    or remote.get("stage_number") != 11
    or remote.get("initial_full_content_check_bound_by_checkpoint_receipt") is not True
    or not isinstance(remote.get("object_count"), int)
    or remote["object_count"] < 3
):
    raise SystemExit("cleanup receipt does not satisfy the deletion gate")
PY
then
    mv -- "$temporary_path" "$failed_path"
    chmod 0400 "$failed_path"
    die "cleanup receipt validation did not pass; preserved $failed_path"
fi

mv -- "$temporary_path" "$receipt_path"
chmod 0400 "$receipt_path"
receipt_sha256="$(sha256sum "$receipt_path" | awk '{print $1}')"
printf 'Finalization checkpoint reauthenticated once.\n'
printf 'Cleanup receipt: %s\n' "$receipt_path"
printf 'Cleanup receipt SHA-256: %s\n' "$receipt_sha256"
