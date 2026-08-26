#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/project-echoes/scaleway-poweroff.env"
readonly API_ROOT="https://api.scaleway.com/instance/v1/zones"

usage() {
    cat <<'EOF'
Usage:
  sudo bash /srv/project-echoes/repo/cloud/scaleway_poweroff_guard.sh --verify-only
  sudo bash /srv/project-echoes/repo/cloud/scaleway_poweroff_guard.sh --poweroff

Verify the exact Scaleway Instance identity using a root-only, least-privilege
API key, or request a true provider-side poweroff. The secret is passed to curl
through a temporary root-only header file and never appears in argv or output.
EOF
}

fail() {
    printf 'Scaleway poweroff guard refused: %s\n' "$1" >&2
    exit 1
}

mode=""
if (($# == 1)); then
    case "$1" in
        --verify-only) mode="verify" ;;
        --poweroff) mode="poweroff" ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
else
    usage >&2
    exit 2
fi

[[ $EUID -eq 0 ]] || fail "run as root"
for executable in curl python3 stat mktemp; do
    command -v "$executable" >/dev/null 2>&1 || fail "required command is missing: $executable"
done

[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "root-only guard environment is absent"
[[ "$(stat -c '%u' "$ENV_FILE")" == 0 ]] || fail "guard environment must be owned by root"
env_mode="$(stat -c '%a' "$ENV_FILE")"
[[ "$env_mode" =~ ^[0-7]{3,4}$ ]] || fail "guard environment mode is invalid"
(( (8#$env_mode & 077) == 0 )) || fail "guard environment must not be group/world accessible"

declare -A observed_names=()
while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -n "$line" && "${line:0:1}" != "#" ]] || continue
    [[ "$line" == *=* ]] || fail "guard environment contains a malformed line"
    name="${line%%=*}"
    value="${line#*=}"
    [[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]] || fail "guard environment has an invalid name"
    [[ -z "${observed_names[$name]+present}" ]] || fail "guard environment repeats a name"
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || fail "guard value has a control character"
    [[ "$value" != [[:space:]]* && "$value" != *[[:space:]] ]] ||
        fail "guard value has surrounding whitespace"
    observed_names["$name"]=1
    printf -v "$name" '%s' "$value"
done < "$ENV_FILE"

required=(
    SCW_SECRET_KEY
    SCW_INSTANCE_ZONE
    SCW_INSTANCE_ID
    SCW_INSTANCE_NAME
    SCW_INSTANCE_TYPE
)
declare -A required_set=()
for name in "${required[@]}"; do
    required_set["$name"]=1
    [[ -n "${!name-}" ]] || fail "required guard value is absent: $name"
    [[ "${!name}" != *OWNER_SET* ]] || fail "$name still contains a placeholder"
done
for name in "${!observed_names[@]}"; do
    [[ -n "${required_set[$name]+present}" ]] || fail "guard environment has an unexpected name"
done

[[ "$SCW_INSTANCE_ZONE" =~ ^nl-ams-[123]$ ]] || fail "Instance zone must be nl-ams-1, -2, or -3"
[[ "$SCW_INSTANCE_ID" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] ||
    fail "Instance ID must be one lowercase UUID"
[[ "$SCW_INSTANCE_NAME" == project-echoes-final-discovery ]] || fail "Instance name differs"
[[ "$SCW_INSTANCE_TYPE" == POP2-16C-64G ]] || fail "Instance type differs"

work="$(mktemp -d)"
cleanup() {
    rm -rf -- "$work"
}
trap cleanup EXIT
chmod 0700 "$work"
header_file="$work/auth-header"
response_file="$work/response.json"
printf 'X-Auth-Token: %s\n' "$SCW_SECRET_KEY" >"$header_file"
chmod 0600 "$header_file"

server_url="${API_ROOT}/${SCW_INSTANCE_ZONE}/servers/${SCW_INSTANCE_ID}"
http_code="$(
    curl \
        --silent \
        --show-error \
        --location \
        --connect-timeout 10 \
        --max-time 45 \
        --retry 3 \
        --retry-delay 2 \
        --retry-all-errors \
        --header "@$header_file" \
        --output "$response_file" \
        --write-out '%{http_code}' \
        "$server_url"
)" || fail "could not query the Scaleway Instance API"
[[ "$http_code" == 200 ]] || fail "Instance identity query returned HTTP $http_code"

identity_json="$(python3 - "$response_file" "$SCW_INSTANCE_ID" "$SCW_INSTANCE_NAME" \
    "$SCW_INSTANCE_TYPE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path, expected_id, expected_name, expected_type = sys.argv[1:]
try:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit("Scaleway identity response is invalid JSON") from exc
server = payload.get("server") if isinstance(payload, dict) else None
if not isinstance(server, dict):
    raise SystemExit("Scaleway identity response lacks a server object")
observed = {
    "id": server.get("id"),
    "name": server.get("name"),
    "commercial_type": server.get("commercial_type"),
    "state": server.get("state"),
}
expected = {
    "id": expected_id,
    "name": expected_name,
    "commercial_type": expected_type,
}
for name, value in expected.items():
    if observed.get(name) != value:
        raise SystemExit(
            f"Scaleway Instance identity differs for {name}: "
            f"expected={value}, observed={observed.get(name)}"
        )
if not isinstance(observed["state"], str) or not observed["state"]:
    raise SystemExit("Scaleway Instance state is absent")
print(json.dumps(observed, sort_keys=True, separators=(",", ":")))
PY
)" || fail "Scaleway Instance identity authentication failed"

if [[ "$mode" == verify ]]; then
    printf '%s\n' "$identity_json"
    printf 'SCALEWAY_POWEROFF_GUARD_VERIFIED\n'
    exit 0
fi

state="$(python3 - "$identity_json" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["state"])
PY
)"
case "$state" in
    stopped|stopping)
        printf 'SCALEWAY_POWEROFF_NOT_NEEDED state=%s\n' "$state"
        exit 0
        ;;
    locked|error)
        # These states do not stop billing by themselves. Return failure so the
        # bounded systemd unit retries the provider request after the temporary
        # or administrative state clears.
        fail "Instance is not yet poweroff-actionable: state=$state"
        ;;
esac

printf '{"action":"poweroff"}\n' >"$work/action.json"
http_code="$(
    curl \
        --silent \
        --show-error \
        --location \
        --connect-timeout 10 \
        --max-time 45 \
        --retry 3 \
        --retry-delay 2 \
        --retry-all-errors \
        --header "@$header_file" \
        --header 'Content-Type: application/json' \
        --request POST \
        --data-binary "@$work/action.json" \
        --output "$response_file" \
        --write-out '%{http_code}' \
        "${server_url}/action"
)" || fail "could not request the provider-side poweroff"
[[ "$http_code" == 200 || "$http_code" == 202 ]] ||
    fail "provider-side poweroff returned HTTP $http_code"
printf 'SCALEWAY_POWEROFF_REQUEST_ACCEPTED instance=%s zone=%s\n' \
    "$SCW_INSTANCE_ID" "$SCW_INSTANCE_ZONE"
